"""
Metabase Self-Hosted Integration Service

- Session auth via POST /api/session
- Health check with retries before login
- In-memory session caching with TTL
- Auto re-auth on 401
- Graceful fallback with structured last_error
"""

import json
import logging
import os
import time
from typing import Any, Dict, Optional

import requests
from bi_platform_shared.sql import sanitize_sql_for_metabase

logger = logging.getLogger(__name__)

_session_token: Optional[str] = None
_session_token_expires_at: float = 0.0

METABASE_TIMEOUT_SECONDS = int(os.getenv("METABASE_TIMEOUT_SECONDS", "30"))
METABASE_AUTH_RETRIES = int(os.getenv("METABASE_AUTH_RETRIES", "2"))
METABASE_HEALTH_RETRIES = int(os.getenv("METABASE_HEALTH_RETRIES", "2"))
METABASE_SESSION_TTL_SECONDS = int(os.getenv("METABASE_SESSION_TTL_SECONDS", "1800"))

CHART_TYPE_MAPPING: Dict[str, str] = {
    "line": "line",
    "line_multi": "line",
    "cumulative_line": "line",
    "bar": "bar",
    "bar_grouped": "bar",
    "bar_stacked": "bar",
    "pie": "pie",
    "area": "area",
    "combo_line_bar": "combo",
    "combo": "combo",
    "map": "map",
    "heatmap": "table",
    "scatter": "scatter",
    "histogram": "bar",
    "kpi": "scalar",
    "card": "scalar",
    "scalar": "scalar",
    "number": "scalar",
    "grouped_bar": "bar",
    "row": "row",
    "funnel": "funnel",
    "gauge": "gauge",
    "waterfall": "waterfall",
    "table": "table",
}
SUPPORTED_DISPLAYS = {
    "line",
    "bar",
    "scatter",
    "scalar",
    "table",
    "pie",
    "area",
    "combo",
    "map",
    "row",
    "funnel",
    "gauge",
    "waterfall",
}
DEFAULT_FALLBACK_DISPLAY = "table"


def _metabase_base_url() -> str:
    return (os.getenv("METABASE_URL") or "http://localhost:3000").rstrip("/")


def _metabase_embed_base_url() -> str:
    return (
        os.getenv("METABASE_EMBED_URL")
        or os.getenv("METABASE_PUBLIC_URL")
        or os.getenv("METABASE_URL")
        or "http://localhost:3000"
    ).rstrip("/")


def _credentials() -> tuple[Optional[str], Optional[str]]:
    return os.getenv("METABASE_USERNAME"), os.getenv("METABASE_PASSWORD")


def check_metabase_health(*, retries: int = METABASE_HEALTH_RETRIES) -> bool:
    url = f"{_metabase_base_url()}/api/health"
    for attempt in range(retries + 1):
        try:
            response = requests.get(url, timeout=METABASE_TIMEOUT_SECONDS)
            if response.status_code == 200:
                return True
        except Exception as exc:
            logger.warning("Metabase health check failed (attempt %s): %s", attempt + 1, exc)
        if attempt < retries:
            time.sleep(1 + attempt)
    return False


def get_metabase_session(force_refresh: bool = False) -> Optional[str]:
    global _session_token, _session_token_expires_at

    if (
        _session_token
        and not force_refresh
        and time.time() < _session_token_expires_at
    ):
        return _session_token

    username, password = _credentials()
    if not username or not password:
        logger.error("METABASE_USERNAME and METABASE_PASSWORD must be configured")
        clear_metabase_session()
        return None

    if not check_metabase_health():
        logger.error("Metabase is unavailable at %s", _metabase_base_url())
        clear_metabase_session()
        return None

    session_url = f"{_metabase_base_url()}/api/session"
    payload = {"username": username, "password": password}

    for attempt in range(METABASE_AUTH_RETRIES + 1):
        try:
            response = requests.post(
                session_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=METABASE_TIMEOUT_SECONDS,
            )
            if response.status_code == 200:
                data = response.json()
                token = data.get("id")
                if token:
                    _session_token = token
                    _session_token_expires_at = time.time() + METABASE_SESSION_TTL_SECONDS
                    logger.info("Metabase session obtained successfully")
                    return _session_token
            logger.error(
                "Metabase login failed (attempt %s): status=%s body=%s",
                attempt + 1,
                response.status_code,
                (response.text or "")[:300],
            )
        except Exception as exc:
            logger.error("Metabase session error (attempt %s): %s", attempt + 1, exc)

        if attempt < METABASE_AUTH_RETRIES:
            time.sleep(1 + attempt)

    clear_metabase_session()
    return None


def clear_metabase_session() -> None:
    global _session_token, _session_token_expires_at
    _session_token = None
    _session_token_expires_at = 0.0


def get_metabase_headers() -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    session_id = get_metabase_session()
    if session_id:
        headers["X-Metabase-Session"] = session_id
    return headers


class MetabaseService:
    def __init__(self) -> None:
        self.base_url = _metabase_base_url()
        self.embed_base_url = _metabase_embed_base_url()
        self.database_id = int(os.getenv("METABASE_DATABASE_ID", "1"))
        self.last_error: Optional[str] = None
        self.last_display: Optional[str] = None
        self.last_fallback_applied: bool = False
        self.last_fallback_reason: str = ""
        self.last_requested_display: Optional[str] = None
        self.last_requested_chart_type: Optional[str] = None
        self.last_metabase_display: Optional[str] = None
        self.last_visualization_settings: Dict[str, Any] = {}
        self.last_display_verification: str = ""
        self.last_display_verification_reason: str = ""

    @staticmethod
    def _clean_non_blank_string(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned if cleaned else None

    @staticmethod
    def _extract_error_details(response: requests.Response) -> str:
        try:
            payload = response.json()
            return json.dumps(payload, ensure_ascii=False)[:500]
        except Exception:
            text = (response.text or "").strip()
            return text[:500] if text else f"status={response.status_code}"

    @staticmethod
    def _extract_query_runtime_error(response: requests.Response) -> Optional[str]:
        """
        Extract runtime query failure details from a successful HTTP response.

        Metabase may return HTTP 200 with a JSON payload that still contains a
        failed execution status (for example, ``via.status = failed``).
        """
        try:
            payload = response.json()
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None

        # Common envelope used by Metabase for native query execution failures.
        via = payload.get("via")
        if isinstance(via, dict) and str(via.get("status", "")).strip().lower() == "failed":
            via_error = str(via.get("error") or "").strip()
            if via_error:
                return via_error
            return "metabase_query_failed"

        # Defensive fallback across other payload variants.
        status_token = str(payload.get("status", "")).strip().lower()
        if status_token == "failed":
            payload_error = payload.get("error")
            if isinstance(payload_error, dict):
                message = str(payload_error.get("message") or "").strip()
                if message:
                    return message
            elif payload_error:
                return str(payload_error).strip()
            return "metabase_query_failed"
        return None

    def _set_last_error(self, message: Optional[str]) -> None:
        self.last_error = message

    @staticmethod
    def _string_list(values: Any) -> list[str]:
        if not isinstance(values, (list, tuple)):
            return []
        cleaned: list[str] = []
        for value in values:
            if isinstance(value, str):
                stripped = value.strip()
                if stripped:
                    cleaned.append(stripped)
        return cleaned

    @staticmethod
    def _extract_dataset_columns(settings: Dict[str, Any]) -> list[Dict[str, Any]]:
        """
        Normalize dataset column metadata from common payload shapes.
        Supported inputs include:
        - settings["dataset_columns"] / settings["columns"] / settings["result_columns"]
        where each item can be a string column name or a dict with at least a name.
        """
        raw_candidates = (
            settings.get("dataset_columns"),
            settings.get("columns"),
            settings.get("result_columns"),
        )
        for raw in raw_candidates:
            if not isinstance(raw, list):
                continue
            normalized: list[Dict[str, Any]] = []
            for item in raw:
                if isinstance(item, dict):
                    name = str(item.get("name") or "").strip()
                    if not name:
                        continue
                    normalized.append(item)
                elif isinstance(item, str):
                    name = item.strip()
                    if not name:
                        continue
                    normalized.append({"name": name})
            if normalized:
                return normalized
        return []

    @staticmethod
    def _dataset_numeric_columns(dataset_columns: list[Dict[str, Any]]) -> list[str]:
        numeric_columns: list[str] = []
        for column in dataset_columns:
            name = str(column.get("name") or "").strip()
            if not name:
                continue
            is_numeric = bool(column.get("is_numeric"))
            if not is_numeric:
                column_type = str(column.get("type") or "").strip().lower()
                is_numeric = any(token in column_type for token in ("int", "float", "double", "decimal", "numeric"))
            if is_numeric:
                numeric_columns.append(name)
        return numeric_columns

    @staticmethod
    def _extract_result_rows(settings: Dict[str, Any]) -> list[Dict[str, Any]]:
        raw_candidates = (
            settings.get("result_rows"),
            settings.get("rows"),
            settings.get("data_rows"),
        )
        for raw in raw_candidates:
            if not isinstance(raw, list):
                continue
            normalized = [row for row in raw if isinstance(row, dict)]
            if normalized:
                return normalized
        return []

    @staticmethod
    def _is_numeric_like(value: Any) -> bool:
        if isinstance(value, bool):
            return False
        if isinstance(value, (int, float)):
            return True
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return False
            if stripped.startswith("-"):
                stripped = stripped[1:]
            return stripped.replace(".", "", 1).isdigit()
        return False

    def _result_row_numeric_columns(
        self,
        result_rows: list[Dict[str, Any]],
        preferred_order: list[str],
    ) -> list[str]:
        if not result_rows:
            return []

        ordered_names: list[str] = []
        seen: set[str] = set()
        for name in preferred_order:
            cleaned = str(name or "").strip()
            if cleaned and cleaned not in seen:
                ordered_names.append(cleaned)
                seen.add(cleaned)
        for row in result_rows:
            for key in row.keys():
                cleaned = str(key or "").strip()
                if cleaned and cleaned not in seen:
                    ordered_names.append(cleaned)
                    seen.add(cleaned)

        numeric_columns: list[str] = []
        sample_rows = result_rows[:25]
        for column_name in ordered_names:
            observed = [
                row.get(column_name)
                for row in sample_rows
                if column_name in row and row.get(column_name) is not None
            ]
            if observed and all(self._is_numeric_like(value) for value in observed):
                numeric_columns.append(column_name)
        return numeric_columns

    @staticmethod
    def _normalize_display(value: Optional[str]) -> Optional[str]:
        if not isinstance(value, str):
            return None
        cleaned = value.strip().lower()
        if not cleaned:
            return None
        return CHART_TYPE_MAPPING.get(cleaned, cleaned)

    def _resolve_scatter_axes(self, settings: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
        dimensions = self._string_list(settings.get("graph.dimensions"))
        metrics = self._string_list(settings.get("graph.metrics"))
        if len(dimensions) == 1 and len(metrics) == 1:
            return dimensions[0], metrics[0]

        x_column = settings.get("x_column")
        y_column = settings.get("y_column")
        if isinstance(x_column, str) and isinstance(y_column, str):
            x_clean = x_column.strip()
            y_clean = y_column.strip()
            if x_clean and y_clean:
                return x_clean, y_clean

        numeric_columns = self._string_list(settings.get("numeric_columns"))
        if len(numeric_columns) >= 2:
            return numeric_columns[0], numeric_columns[1]

        return None, None

    def _resolve_line_dimension_metrics(self, settings: Dict[str, Any]) -> tuple[Optional[str], list[str]]:
        dimensions = self._string_list(settings.get("graph.dimensions"))
        metrics = self._string_list(settings.get("graph.metrics"))
        if dimensions and metrics:
            return dimensions[0], metrics

        time_columns = self._string_list(settings.get("time_columns"))
        numeric_columns = self._string_list(settings.get("numeric_columns"))
        if time_columns and numeric_columns:
            return time_columns[0], numeric_columns
        category_columns = self._string_list(settings.get("category_columns"))
        if category_columns and numeric_columns:
            return category_columns[0], numeric_columns
        return None, []

    @staticmethod
    def _normalize_forecast_series_type(value: Any) -> str:
        token = str(value or "").strip().lower()
        if not token:
            return ""
        if token in {"actual", "historical", "history", "real", "observed"}:
            return "actual"
        if token in {"forecast", "forecasted", "predicted", "prediction", "projected", "future"}:
            return "forecast"
        return token

    @staticmethod
    def _resolve_column_case_insensitive(candidates: list[str], preferred: str) -> str:
        if not preferred:
            return ""
        preferred_clean = preferred.strip()
        if not preferred_clean:
            return ""
        lowered = preferred_clean.lower()
        for candidate in candidates:
            if candidate.lower() == lowered:
                return candidate
        return ""

    @staticmethod
    def _humanize_identifier(identifier: str) -> str:
        token = str(identifier or "").strip()
        if not token:
            return ""
        return " ".join(part.capitalize() for part in token.replace("-", "_").split("_") if part)

    @staticmethod
    def _is_time_like_identifier(identifier: str) -> bool:
        lowered = str(identifier or "").strip().lower()
        if not lowered:
            return False
        return any(
            token in lowered
            for token in ("date", "time", "timestamp", "period", "day", "week", "month", "quarter", "year", "ds")
        )

    def _resolve_forecast_metric_label(self, settings: Dict[str, Any], metric_column: str) -> str:
        metric_clean = str(metric_column or "").strip()
        if not metric_clean:
            return "Value"

        generic_metric_tokens = {"value", "metric", "amount", "total", "sum", "count"}
        if metric_clean.lower() not in generic_metric_tokens:
            return self._humanize_identifier(metric_clean) or "Value"

        intent_payload = settings.get("intent")
        if isinstance(intent_payload, dict):
            intent_columns = intent_payload.get("columns")
            if isinstance(intent_columns, list):
                for raw_column in intent_columns:
                    candidate = str(raw_column or "").strip()
                    lowered = candidate.lower()
                    if (
                        candidate
                        and lowered not in {"series_type", "series_label", "preferred_color_role", "value", "ds"}
                        and not self._is_time_like_identifier(candidate)
                    ):
                        return self._humanize_identifier(candidate) or "Value"

        return self._humanize_identifier(metric_clean) or "Value"

    def _apply_forecast_series_visual_settings(
        self,
        settings: Dict[str, Any],
        *,
        time_dimension: str,
        metric_columns: list[str],
    ) -> None:
        if not metric_columns or len(metric_columns) != 1:
            return

        metric_column = str(metric_columns[0] or "").strip()
        if not metric_column:
            return

        result_rows = self._extract_result_rows(settings)
        dataset_columns = self._extract_dataset_columns(settings)

        available_columns: list[str] = []
        for column in dataset_columns:
            name = str(column.get("name") or "").strip()
            if name and name not in available_columns:
                available_columns.append(name)
        for row in result_rows[:25]:
            for key in row.keys():
                cleaned_key = str(key or "").strip()
                if cleaned_key and cleaned_key not in available_columns:
                    available_columns.append(cleaned_key)

        if not available_columns:
            return

        hinted_series_type_field = str(settings.get("series_type_field") or "").strip()
        hinted_series_label_field = str(settings.get("series_label_field") or "").strip()
        hinted_color_role_field = str(settings.get("preferred_color_role_field") or "").strip()

        series_type_field = self._resolve_column_case_insensitive(available_columns, hinted_series_type_field)
        if not series_type_field:
            series_type_field = self._resolve_column_case_insensitive(available_columns, "series_type")
        if not series_type_field:
            return

        series_label_field = self._resolve_column_case_insensitive(available_columns, hinted_series_label_field)
        if not series_label_field:
            series_label_field = self._resolve_column_case_insensitive(available_columns, "series_label")

        color_role_field = self._resolve_column_case_insensitive(available_columns, hinted_color_role_field)
        if not color_role_field:
            color_role_field = self._resolve_column_case_insensitive(available_columns, "preferred_color_role")

        chart_series_config = settings.get("chart_series_config")
        normalized_series_config: dict[str, Dict[str, Any]] = {}
        if isinstance(chart_series_config, list):
            for item in chart_series_config:
                if not isinstance(item, dict):
                    continue
                normalized_type = self._normalize_forecast_series_type(item.get("series_type"))
                if normalized_type in {"actual", "forecast"}:
                    normalized_series_config[normalized_type] = item

        row_series_keys: dict[str, str] = {}
        row_series_labels: dict[str, str] = {}
        row_series_color_roles: dict[str, str] = {}
        seen_types: set[str] = set()
        for row in result_rows:
            if not isinstance(row, dict):
                continue
            raw_series_key = str(row.get(series_type_field) or "").strip()
            normalized_type = self._normalize_forecast_series_type(raw_series_key)
            if normalized_type not in {"actual", "forecast"}:
                continue
            seen_types.add(normalized_type)
            if raw_series_key and normalized_type not in row_series_keys:
                row_series_keys[normalized_type] = raw_series_key
            if series_label_field:
                raw_label = str(row.get(series_label_field) or "").strip()
                if raw_label and normalized_type not in row_series_labels:
                    row_series_labels[normalized_type] = raw_label
            if color_role_field:
                raw_role = str(row.get(color_role_field) or "").strip()
                if raw_role and normalized_type not in row_series_color_roles:
                    row_series_color_roles[normalized_type] = raw_role

        has_forecast = "forecast" in seen_types or "forecast" in normalized_series_config
        has_actual = "actual" in seen_types or "actual" in normalized_series_config
        forecast_available = bool(settings.get("forecast_available"))
        if not has_forecast and not forecast_available:
            return
        if not has_actual and not has_forecast:
            return

        default_colors = {"actual": "#2563eb", "forecast": "#f97316"}
        default_dash = {"actual": "", "forecast": "6 4"}
        series_settings: Dict[str, Dict[str, Any]] = {}
        series_order: list[Dict[str, Any]] = []
        metric_label = self._resolve_forecast_metric_label(settings, metric_column)

        for series_type in ("actual", "forecast"):
            if series_type not in seen_types and series_type not in normalized_series_config:
                continue

            config = normalized_series_config.get(series_type, {})
            series_key = (
                row_series_keys.get(series_type)
                or str(config.get("series_type") or "").strip()
                or series_type
            )
            if not series_key:
                continue

            preferred_role = row_series_color_roles.get(series_type) or str(config.get("preferred_color_role") or "").strip()
            if preferred_role:
                preferred_role = self._normalize_forecast_series_type(preferred_role)
            if preferred_role not in {"actual", "forecast"}:
                preferred_role = series_type

            color = str(config.get("preferred_color") or "").strip() or default_colors.get(preferred_role, default_colors[series_type])
            stroke_dasharray = str(config.get("stroke_dasharray") or default_dash.get(series_type, "")).strip()

            fallback_label = "Actual" if series_type == "actual" else "Forecasted"
            series_label = (
                row_series_labels.get(series_type)
                or str(config.get("series_label") or "").strip()
                or fallback_label
            )
            if series_type == "forecast" and series_label.strip().lower() in {"forecast", "predicted", "prediction"}:
                series_label = "Forecasted"
            if series_type == "actual" and series_label.strip().lower() in {"actual", "historical", "history", "real"}:
                series_label = "Actual"

            title = f"{series_label} {metric_label}".strip()
            series_settings[series_key] = {
                "title": title,
                "display": "line",
                "color": color,
            }
            if stroke_dasharray:
                # Kept as semantic hint for renderers that support stroke patterns.
                series_settings[series_key]["stroke_dasharray"] = stroke_dasharray
            if series_type == "forecast":
                # Metabase supports per-series interpolation, but not guaranteed stroke dashing.
                series_settings[series_key]["line.interpolate"] = "linear"

            series_order.append(
                {
                    "key": series_key,
                    "name": title,
                    "enabled": True,
                    "color": color,
                }
            )

        if len(series_settings) < 2:
            return

        settings["graph.dimensions"] = [time_dimension, series_type_field]
        settings["graph.metrics"] = [metric_column]
        settings["graph.series_order_dimension"] = series_type_field
        settings["graph.series_order"] = series_order
        settings["series_settings"] = series_settings
        settings["forecast_series_visualization_applied"] = True
        settings["forecast_series_dimension"] = series_type_field
        settings["forecast_metric_column"] = metric_column

    def _resolve_bar_dimension_metric(self, settings: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
        dimensions = self._string_list(settings.get("graph.dimensions"))
        metrics = self._string_list(settings.get("graph.metrics"))
        if dimensions and metrics:
            return dimensions[0], metrics[0]
        category_columns = self._string_list(settings.get("category_columns"))
        numeric_columns = self._string_list(settings.get("numeric_columns"))
        if category_columns and numeric_columns:
            return category_columns[0], numeric_columns[0]
        return None, None

    def _resolve_histogram_metric(self, settings: Dict[str, Any]) -> Optional[str]:
        # Priority:
        # 1) graph.metrics
        # 2) numeric_columns
        # 3) first numeric column in dataset metadata
        # 4) first numeric column from result column metadata
        # 5) first numeric column inferred from result rows
        # 6) first dataset column
        # 7) legacy axis hints (x_column / y_column)
        metrics = self._string_list(settings.get("graph.metrics"))
        if metrics:
            logger.info("Histogram metric resolved from graph.metrics: %s", metrics[0])
            return metrics[0]

        numeric_columns = self._string_list(settings.get("numeric_columns"))
        if numeric_columns:
            logger.info("Histogram metric resolved from numeric_columns: %s", numeric_columns[0])
            return numeric_columns[0]

        dataset_columns = self._extract_dataset_columns(settings)
        dataset_numeric_columns = self._dataset_numeric_columns(dataset_columns)
        if dataset_numeric_columns:
            logger.info("Histogram metric resolved from dataset_columns: %s", dataset_numeric_columns[0])
            return dataset_numeric_columns[0]

        result_columns = settings.get("result_columns")
        normalized_result_columns: list[Dict[str, Any]] = []
        if isinstance(result_columns, list):
            for item in result_columns:
                if isinstance(item, dict):
                    name = str(item.get("name") or "").strip()
                    if name:
                        normalized_result_columns.append(item)
                elif isinstance(item, str):
                    cleaned = item.strip()
                    if cleaned:
                        normalized_result_columns.append({"name": cleaned})
        result_numeric_columns = self._dataset_numeric_columns(normalized_result_columns)
        if result_numeric_columns:
            logger.info("Histogram metric resolved from result_columns: %s", result_numeric_columns[0])
            return result_numeric_columns[0]

        result_rows = self._extract_result_rows(settings)
        dataset_column_names = [str(col.get("name") or "").strip() for col in dataset_columns if str(col.get("name") or "").strip()]
        row_numeric_columns = self._result_row_numeric_columns(result_rows, dataset_column_names)
        if row_numeric_columns:
            logger.info("Histogram metric resolved from result rows: %s", row_numeric_columns[0])
            return row_numeric_columns[0]

        if dataset_columns:
            fallback_name = str(dataset_columns[0].get("name") or "").strip()
            if fallback_name:
                logger.info("Histogram metric resolved from dataset_columns fallback: %s", fallback_name)
                return fallback_name

        for axis_key in ("x_column", "y_column"):
            axis_value = settings.get(axis_key)
            if isinstance(axis_value, str):
                cleaned = axis_value.strip()
                if cleaned:
                    logger.info("Histogram metric resolved from legacy %s hint: %s", axis_key, cleaned)
                    return cleaned
        logger.warning("Histogram metric resolution fell through all strategies; no metric available.")
        return None

    def _resolve_histogram_bar_axes(self, settings: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
        dimensions = self._string_list(settings.get("graph.dimensions"))
        metrics = self._string_list(settings.get("graph.metrics"))
        if len(dimensions) == 1 and len(metrics) == 1:
            return dimensions[0], metrics[0]

        dataset_columns = self._extract_dataset_columns(settings)
        column_names = [str(col.get("name") or "").strip() for col in dataset_columns if str(col.get("name") or "").strip()]
        numeric_columns = self._dataset_numeric_columns(dataset_columns)
        if not numeric_columns:
            numeric_columns = self._string_list(settings.get("numeric_columns"))
        if not numeric_columns:
            result_rows = self._extract_result_rows(settings)
            numeric_columns = self._result_row_numeric_columns(result_rows, column_names)

        lowered_to_name = {name.lower(): name for name in column_names}
        for token in ("bin_start", "bin", "bucket", "range_start"):
            if token in lowered_to_name:
                bin_dimension = lowered_to_name[token]
                break
        else:
            bin_dimension = ""

        metric_candidates = []
        for token in ("frequency", "count", "value_count"):
            if token in lowered_to_name:
                metric_candidates.append(lowered_to_name[token])
        metric_candidates.extend(numeric_columns)
        metric_candidates = [candidate for candidate in metric_candidates if candidate]

        metric_column = metric_candidates[0] if metric_candidates else None
        dimension_column = bin_dimension or (column_names[0] if column_names else None)
        if metric_column and not dimension_column:
            dimension_column = metric_column

        if metric_column and dimension_column:
            return dimension_column, metric_column
        return None, None

    def _safe_display_from_shape(self, settings: Dict[str, Any]) -> str:
        numeric_columns = self._string_list(settings.get("numeric_columns"))
        time_columns = self._string_list(settings.get("time_columns"))
        category_columns = self._string_list(settings.get("category_columns"))
        row_count = int(settings.get("row_count") or 0)

        if row_count <= 0:
            return "table"

        if time_columns and numeric_columns and row_count > 1:
            settings["graph.dimensions"] = [time_columns[0]]
            settings["graph.metrics"] = [numeric_columns[0]]
            return "line"
        if len(numeric_columns) >= 2 and row_count > 1:
            settings["graph.dimensions"] = [numeric_columns[0]]
            settings["graph.metrics"] = [numeric_columns[1]]
            return "scatter"
        if category_columns and numeric_columns:
            settings["graph.dimensions"] = [category_columns[0]]
            settings["graph.metrics"] = [numeric_columns[0]]
            return "bar"
        if numeric_columns and row_count > 1:
            settings["graph.dimensions"] = [numeric_columns[0]]
            if len(numeric_columns) > 1:
                settings["graph.metrics"] = [numeric_columns[1]]
            return "bar"
        if len(numeric_columns) == 1 and row_count == 1:
            settings["graph.metrics"] = [numeric_columns[0]]
            return "scalar"
        return DEFAULT_FALLBACK_DISPLAY

    def _prepare_visualization_settings(self, visualization_settings: Optional[Dict[str, Any]]) -> tuple[str, Dict[str, Any]]:
        settings: Dict[str, Any] = dict(visualization_settings or {})
        requested_chart_type_raw = str(settings.get("chart_type") or "").strip().lower()
        requested_display_raw = str(settings.get("display") or settings.get("chart_type") or "").strip().lower()
        requested_display = self._normalize_display(settings.get("display") or settings.get("chart_type"))
        fallback_applied = False
        fallback_reason = ""
        row_count: int | None = None
        try:
            if settings.get("row_count") is not None:
                row_count = int(settings.get("row_count"))
        except (TypeError, ValueError):
            row_count = None
        if row_count is not None and row_count <= 0:
            requested_display = "table"
            fallback_applied = True
            fallback_reason = "empty_result_force_table"

        if not requested_display:
            requested_display = DEFAULT_FALLBACK_DISPLAY
            fallback_applied = True
            if not fallback_reason:
                fallback_reason = "missing_selected_display"
            logger.info("No chart display provided; defaulting display to '%s'", requested_display)

        display = requested_display
        if display not in SUPPORTED_DISPLAYS:
            fallback_applied = True
            if not fallback_reason:
                fallback_reason = f"unsupported_display:{requested_display}"
            display = DEFAULT_FALLBACK_DISPLAY
            logger.warning("Unsupported chart display '%s'; defaulting to '%s'", requested_display, display)

        histogram_hint = requested_display_raw == "histogram" or requested_chart_type_raw == "histogram"

        if histogram_hint and display == "bar":
            hist_dimension, hist_metric = self._resolve_histogram_bar_axes(settings)
            if not hist_dimension or not hist_metric:
                fallback_applied = True
                if not fallback_reason:
                    fallback_reason = "histogram_axes_unresolved"
                display = DEFAULT_FALLBACK_DISPLAY
                logger.warning(
                    "Histogram-to-bar mapping unresolved (dimension=%s metric=%s); falling back to table.",
                    hist_dimension,
                    hist_metric,
                )
            else:
                settings["graph.dimensions"] = [hist_dimension]
                settings["graph.metrics"] = [hist_metric]
                settings["histogram_mapped_to_bar"] = True
                settings["histogram_dimension"] = hist_dimension
                settings["histogram_metric"] = hist_metric
        elif display == "scatter":
            x_column, y_column = self._resolve_scatter_axes(settings)
            if not x_column or not y_column or x_column == y_column:
                fallback_applied = True
                if not fallback_reason:
                    fallback_reason = "scatter_axes_unresolved"
                display = DEFAULT_FALLBACK_DISPLAY
                logger.warning(
                    "Scatter display selected but axes could not be resolved (x=%s, y=%s); falling back to table.",
                    x_column,
                    y_column,
                )
            else:
                settings["graph.dimensions"] = [x_column]
                settings["graph.metrics"] = [y_column]
        elif display == "line":
            time_dimension, metric_columns = self._resolve_line_dimension_metrics(settings)
            if not time_dimension or not metric_columns:
                fallback_applied = True
                if not fallback_reason:
                    fallback_reason = "line_axes_unresolved"
                display = DEFAULT_FALLBACK_DISPLAY
                logger.warning(
                    "Line display selected but axes could not be resolved (time=%s, metrics=%s); falling back to table.",
                    time_dimension,
                    metric_columns,
                )
            else:
                settings["graph.dimensions"] = [time_dimension]
                settings["graph.metrics"] = metric_columns
                self._apply_forecast_series_visual_settings(
                    settings,
                    time_dimension=time_dimension,
                    metric_columns=metric_columns,
                )
        elif display == "combo":
            time_dimension, metric_columns = self._resolve_line_dimension_metrics(settings)
            if not time_dimension or len(metric_columns) < 2:
                fallback_applied = True
                if not fallback_reason:
                    fallback_reason = "combo_axes_unresolved"
                display = DEFAULT_FALLBACK_DISPLAY
                logger.warning(
                    "Combo display selected but axes could not be resolved (time=%s, metrics=%s); falling back to table.",
                    time_dimension,
                    metric_columns,
                )
            else:
                settings["graph.dimensions"] = [time_dimension]
                settings["graph.metrics"] = metric_columns
        elif display == "bar":
            dimension_column, metric_column = self._resolve_bar_dimension_metric(settings)
            if not metric_column:
                metric_column = self._resolve_histogram_metric(settings)
            if not metric_column:
                fallback_applied = True
                if not fallback_reason:
                    fallback_reason = "bar_metric_unresolved"
                display = DEFAULT_FALLBACK_DISPLAY
                logger.warning(
                    "Bar display selected but metric could not be resolved (dimension=%s, metric=%s); falling back to table.",
                    dimension_column,
                    metric_column,
                )
            else:
                settings["graph.metrics"] = [metric_column]
                if dimension_column:
                    settings["graph.dimensions"] = [dimension_column]

        settings["display"] = display
        settings["requested_display"] = requested_display
        settings["requested_display_raw"] = requested_display_raw
        settings["requested_chart_type_raw"] = requested_chart_type_raw
        settings["fallback_applied"] = fallback_applied
        settings["fallback_reason"] = fallback_reason
        self.last_display = display
        self.last_fallback_applied = fallback_applied
        self.last_fallback_reason = fallback_reason
        self.last_requested_display = requested_display
        self.last_requested_chart_type = requested_chart_type_raw or None
        self.last_visualization_settings = dict(settings)
        logger.info(
            "chart_selection_result display=%s fallback_applied=%s fallback_reason=%s requested_display=%s",
            display,
            fallback_applied,
            fallback_reason,
            requested_display,
        )
        return display, settings

    def health_check(self) -> bool:
        healthy = check_metabase_health()
        if not healthy:
            self._set_last_error("metabase_unavailable")
        return healthy

    def _headers(self) -> Dict[str, str]:
        return get_metabase_headers()

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Optional[Dict[str, Any]] = None,
        retry_on_401: bool = True,
    ) -> Optional[requests.Response]:
        if not self.health_check():
            return None

        url = f"{self.base_url}{path}" if path.startswith("/") else f"{self.base_url}/{path}"
        headers = self._headers()

        if not headers.get("X-Metabase-Session"):
            self._set_last_error("metabase_authentication_failed")
            return None

        try:
            kwargs: Dict[str, Any] = {"headers": headers, "timeout": METABASE_TIMEOUT_SECONDS}
            if json is not None and method.upper() != "GET":
                kwargs["json"] = json
            response = requests.request(method, url, **kwargs)
        except Exception as exc:
            self._set_last_error(f"metabase_request_error: {exc}")
            logger.error("Metabase request error %s %s: %s", method, path, exc)
            return None

        if response.status_code == 401 and retry_on_401:
            clear_metabase_session()
            if get_metabase_session(force_refresh=True):
                headers = self._headers()
                kwargs["headers"] = headers
                try:
                    response = requests.request(method, url, **kwargs)
                except Exception as exc:
                    self._set_last_error(f"metabase_request_error_after_refresh: {exc}")
                    logger.error("Metabase retry request error %s %s: %s", method, path, exc)
                    return None
            else:
                self._set_last_error("metabase_authentication_failed")
                return None

        return response

    def authenticate(self, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        # username/password override intentionally ignored; env-based auth only.
        _ = username, password
        if not self.health_check():
            return False
        authenticated = get_metabase_session(force_refresh=True) is not None
        self._set_last_error(None if authenticated else "metabase_authentication_failed")
        return authenticated

    def create_question(
        self,
        name: str,
        sql: str,
        description: str = "",
        visualization_settings: Optional[Dict] = None,
    ) -> Optional[int]:
        self._set_last_error(None)
        display, normalized_visualization_settings = self._prepare_visualization_settings(visualization_settings)
        sanitized_sql = sanitize_sql_for_metabase(sql)

        payload: Dict[str, Any] = {
            "name": name,
            "dataset_query": {
                "type": "native",
                "native": {"query": sanitized_sql},
                "database": self.database_id,
            },
            "display": display,
            "visualization_settings": normalized_visualization_settings,
        }
        clean_description = self._clean_non_blank_string(description)
        if clean_description is not None:
            payload["description"] = clean_description

        logger.info(
            "Creating Metabase question: name=%s database_id=%s display=%s sql_len=%s chart_selected=%s fallback_applied=%s",
            name,
            self.database_id,
            payload.get("display"),
            len(sanitized_sql or ""),
            visualization_settings.get("chart_type") if isinstance(visualization_settings, dict) else "",
            bool(
                isinstance(normalized_visualization_settings, dict)
                and normalized_visualization_settings.get("display") != (visualization_settings or {}).get("display")
            ),
        )
        logger.info(
            "Metabase card request chart_type=%s mapped_display=%s visualization_settings=%s",
            normalized_visualization_settings.get("chart_type"),
            payload.get("display"),
            json.dumps(normalized_visualization_settings, ensure_ascii=False)[:1200],
        )
        logger.info("Metabase SQL normalization applied raw_len=%s sanitized_len=%s", len(sql or ""), len(sanitized_sql or ""))
        response = self._request("POST", "/api/card", json=payload)
        if response and response.status_code in (200, 201):
            question_id = response.json().get("id")
            if not isinstance(question_id, int):
                self._set_last_error("create_question_failed: invalid_response_missing_id")
                logger.error(
                    "Create question returned invalid payload: %s",
                    self._extract_error_details(response)
                )
                return None
            if not self._verify_card_display(
                question_id=question_id,
                expected_display=display,
                settings=normalized_visualization_settings,
            ):
                logger.error(
                    "Metabase display verification failed question_id=%s expected=%s actual=%s reason=%s",
                    question_id,
                    display,
                    self.last_metabase_display,
                    self.last_display_verification_reason,
                )
                self.delete_question(question_id)
                return None
            logger.info("Created Metabase question id=%s", question_id)
            return question_id
        if response:
            details = self._extract_error_details(response)
            self._set_last_error(f"create_question_failed: {details}")
            logger.error("Create question failed: %s %s", response.status_code, details)
        elif self.last_error is None:
            self._set_last_error("create_question_failed: no_response")
        return None

    def _verify_card_display(
        self,
        *,
        question_id: int,
        expected_display: str,
        settings: Dict[str, Any],
    ) -> bool:
        self.last_metabase_display = None
        self.last_display_verification = "unverified"
        self.last_display_verification_reason = "display_unchecked"

        response = self._request("GET", f"/api/card/{question_id}")
        if not response:
            self.last_display_verification_reason = "card_fetch_unavailable"
            logger.warning(
                "Metabase card display verification skipped question_id=%s reason=%s",
                question_id,
                self.last_display_verification_reason,
            )
            return True
        if response.status_code not in (200, 201):
            self.last_display_verification_reason = f"card_fetch_status_{response.status_code}"
            logger.warning(
                "Metabase card display verification skipped question_id=%s status=%s",
                question_id,
                response.status_code,
            )
            return True

        try:
            payload = response.json()
        except Exception:
            payload = {}
        actual_display = self._normalize_display(
            payload.get("display") if isinstance(payload, dict) else None
        )
        self.last_metabase_display = actual_display

        if not actual_display:
            self.last_display_verification_reason = "display_missing_in_card_payload"
            logger.warning(
                "Metabase card payload missing display question_id=%s payload_keys=%s",
                question_id,
                sorted(payload.keys()) if isinstance(payload, dict) else [],
            )
            return True

        if actual_display == expected_display:
            self.last_display_verification = "verified"
            self.last_display_verification_reason = "display_match"
            return True

        fallback_accepted = bool(
            actual_display == DEFAULT_FALLBACK_DISPLAY
            and settings.get("fallback_applied")
        )
        if fallback_accepted:
            self.last_display_verification = "verified_fallback"
            self.last_display_verification_reason = "metabase_table_fallback_accepted"
            self.last_fallback_applied = True
            self.last_fallback_reason = str(
                settings.get("fallback_reason")
                or "metabase_display_downgraded_to_table"
            )
            logger.warning(
                "Metabase display downgraded question_id=%s expected=%s actual=%s accepted_fallback_reason=%s",
                question_id,
                expected_display,
                actual_display,
                self.last_fallback_reason,
            )
            return True

        self.last_display_verification = "mismatch"
        self.last_display_verification_reason = f"display_mismatch:{expected_display}->{actual_display}"
        self._set_last_error(
            f"create_question_failed: metabase_display_mismatch expected={expected_display} actual={actual_display}"
        )
        logger.error(
            "Metabase display mismatch question_id=%s expected=%s actual=%s settings=%s",
            question_id,
            expected_display,
            actual_display,
            json.dumps(settings, ensure_ascii=False)[:1200],
        )
        return False

    def validate_question_execution(self, question_id: int) -> bool:
        """
        Force a backend query execution check after card creation.
        This catches cards that are created successfully but fail at runtime.
        """
        self._set_last_error(None)
        payload = {"parameters": []}
        response = self._request("POST", f"/api/card/{question_id}/query/json", json=payload)
        if response and response.status_code == 200:
            runtime_error = self._extract_query_runtime_error(response)
            if runtime_error:
                self._set_last_error(f"question_execution_failed: {runtime_error}")
                logger.error(
                    "Metabase question execution runtime failed id=%s details=%s",
                    question_id,
                    runtime_error,
                )
                return False
            return True
        if response:
            details = self._extract_error_details(response)
            self._set_last_error(f"question_execution_failed: {details}")
            logger.error("Metabase question execution validation failed id=%s details=%s", question_id, details)
            return False

        # Some Metabase deployments do not expose /query/json; try /query.
        response = self._request("POST", f"/api/card/{question_id}/query", json=payload)
        if response and response.status_code in (200, 202):
            runtime_error = self._extract_query_runtime_error(response)
            if runtime_error:
                self._set_last_error(f"question_execution_failed: {runtime_error}")
                logger.error(
                    "Metabase question execution runtime failed (fallback) id=%s details=%s",
                    question_id,
                    runtime_error,
                )
                return False
            # 202 with no explicit failure means async acceptance; treat as not yet validated.
            if response.status_code == 202:
                self._set_last_error("question_execution_pending")
                logger.warning(
                    "Metabase question execution fallback returned 202 without failure for id=%s; treated as pending.",
                    question_id,
                )
                return False
            return True
        if response:
            details = self._extract_error_details(response)
            self._set_last_error(f"question_execution_failed: {details}")
            logger.error("Metabase question execution validation failed (fallback) id=%s details=%s", question_id, details)
            return False

        if self.last_error is None:
            self._set_last_error("question_execution_failed: no_response")
        return False

    def validate_embedded_question_execution(self, question_id: int) -> bool:
        """
        Validate query execution in embed (JWT) context, not only session context.
        This catches permission/sandbox issues that only appear in embedded iframes.
        """
        self._set_last_error(None)
        try:
            from .jwt_embedding import get_jwt_service

            jwt_service = get_jwt_service()
            token = jwt_service.generate_question_token(question_id, params={})
        except Exception as exc:
            self._set_last_error(f"embedded_question_validation_failed: token_generation_error: {exc}")
            logger.error("Embedded validation token generation failed for question=%s error=%s", question_id, exc)
            return False

        # Metabase embed query API commonly supports GET on /query/json.
        embed_paths = [
            f"/api/embed/card/{token}/query/json",
            f"/api/embed/card/{token}/query",
        ]
        for path in embed_paths:
            response = self._request("GET", path, retry_on_401=False)
            if response and response.status_code == 200:
                runtime_error = self._extract_query_runtime_error(response)
                if runtime_error:
                    logger.error(
                        "Embedded question runtime failed question=%s path=%s details=%s",
                        question_id,
                        path,
                        runtime_error,
                    )
                    self._set_last_error(f"embedded_question_execution_failed: {runtime_error}")
                    continue
                return True
            if response:
                details = self._extract_error_details(response)
                logger.error(
                    "Embedded question execution validation failed question=%s path=%s status=%s details=%s",
                    question_id,
                    path,
                    response.status_code,
                    details,
                )
                self._set_last_error(f"embedded_question_execution_failed: {details}")
                continue

        if self.last_error is None:
            self._set_last_error("embedded_question_execution_failed: no_response")
        return False

    def update_question(
        self,
        card_id: int,
        name: str,
        sql: str,
        description: str = "",
        visualization_settings: Optional[Dict] = None,
    ) -> bool:
        self._set_last_error(None)
        display, normalized_visualization_settings = self._prepare_visualization_settings(visualization_settings)
        sanitized_sql = sanitize_sql_for_metabase(sql)

        payload: Dict[str, Any] = {
            "name": name,
            "dataset_query": {
                "type": "native",
                "native": {"query": sanitized_sql},
                "database": self.database_id,
            },
            "display": display,
            "visualization_settings": normalized_visualization_settings,
        }
        clean_description = self._clean_non_blank_string(description)
        if clean_description is not None:
            payload["description"] = clean_description

        response = self._request("PUT", f"/api/card/{card_id}", json=payload)
        if response and response.status_code == 200:
            return True
        if response:
            details = self._extract_error_details(response)
            self._set_last_error(f"update_question_failed: {details}")
        elif self.last_error is None:
            self._set_last_error("update_question_failed: no_response")
        return False

    def create_dashboard(self, name: str, description: str = "") -> Optional[int]:
        self._set_last_error(None)
        payload: Dict[str, Any] = {"name": name}
        clean_description = self._clean_non_blank_string(description)
        if clean_description is not None:
            payload["description"] = clean_description
        response = self._request("POST", "/api/dashboard", json=payload)
        if response and response.status_code in (200, 201):
            dashboard_id = response.json().get("id")
            return dashboard_id
        if response:
            details = self._extract_error_details(response)
            self._set_last_error(f"create_dashboard_failed: {details}")
        elif self.last_error is None:
            self._set_last_error("create_dashboard_failed: no_response")
        return None

    def update_dashboard(self, dashboard_id: int, name: Optional[str] = None, description: Optional[str] = None) -> bool:
        payload: Dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        clean_description = self._clean_non_blank_string(description)
        if clean_description is not None:
            payload["description"] = clean_description
        if not payload:
            return True
        response = self._request("PUT", f"/api/dashboard/{dashboard_id}", json=payload)
        if response and response.status_code == 200:
            return True
        if response:
            details = self._extract_error_details(response)
            self._set_last_error(f"update_dashboard_failed: {details}")
        elif self.last_error is None:
            self._set_last_error("update_dashboard_failed: no_response")
        return False

    def add_question_to_dashboard(
        self,
        question_id: int,
        dashboard_id: int,
        row: int = 0,
        col: int = 0,
        size_x: int = 6,
        size_y: int = 4,
    ) -> bool:
        self._set_last_error(None)
        dashboard = self.get_dashboard(dashboard_id)
        if not dashboard:
            if self.last_error is None:
                self._set_last_error("add_to_dashboard_failed: dashboard_not_found")
            return False

        existing_dashcards = dashboard.get("dashcards") if isinstance(dashboard, dict) else []
        dashcards_payload: list[Dict[str, Any]] = []

        if isinstance(existing_dashcards, list):
            for dashcard in existing_dashcards:
                if not isinstance(dashcard, dict):
                    continue
                dashcard_id = dashcard.get("id")
                if dashcard_id is None:
                    continue
                item: Dict[str, Any] = {
                    "id": dashcard_id,
                    "size_x": int(dashcard.get("size_x", size_x)),
                    "size_y": int(dashcard.get("size_y", size_y)),
                    "row": int(dashcard.get("row", 0)),
                    "col": int(dashcard.get("col", 0)),
                }
                card_id = dashcard.get("card_id")
                if card_id is None and isinstance(dashcard.get("card"), dict):
                    card_id = dashcard["card"].get("id")
                if card_id is not None:
                    item["card_id"] = int(card_id)

                parameter_mappings = dashcard.get("parameter_mappings")
                if parameter_mappings is not None:
                    item["parameter_mappings"] = parameter_mappings
                series = dashcard.get("series")
                if series is not None:
                    item["series"] = series
                tab_id = dashcard.get("dashboard_tab_id")
                if tab_id is not None:
                    item["dashboard_tab_id"] = tab_id
                dashcards_payload.append(item)

        temporary_dashcard_id = -int(time.time() * 1000)
        dashcards_payload.append(
            {
                "id": temporary_dashcard_id,
                "card_id": int(question_id),
                "row": int(row),
                "col": int(col),
                "size_x": int(size_x),
                "size_y": int(size_y),
                "series": [],
                "parameter_mappings": [],
            }
        )

        response = self._request(
            "PUT",
            f"/api/dashboard/{dashboard_id}",
            json={"dashcards": dashcards_payload},
        )
        if response and response.status_code == 200:
            return True
        if response:
            details = self._extract_error_details(response)
            self._set_last_error(f"add_to_dashboard_failed: {details}")
        elif self.last_error is None:
            self._set_last_error("add_to_dashboard_failed: no_response")
        return False

    def get_dashboard(self, dashboard_id: int) -> Optional[Dict]:
        response = self._request("GET", f"/api/dashboard/{dashboard_id}")
        if response and response.status_code == 200:
            return response.json()
        return None

    def get_card(self, card_id: int) -> Optional[Dict]:
        response = self._request("GET", f"/api/card/{card_id}")
        if response and response.status_code == 200:
            return response.json()
        return None

    def delete_question(self, question_id: int) -> bool:
        response = self._request("DELETE", f"/api/card/{question_id}")
        return bool(response and response.status_code == 204)

    def delete_dashboard(self, dashboard_id: int) -> bool:
        response = self._request("DELETE", f"/api/dashboard/{dashboard_id}")
        return bool(response and response.status_code == 204)

    def enable_dashboard_embedding(self, dashboard_id: int) -> bool:
        response = self._request(
            "PUT",
            f"/api/dashboard/{dashboard_id}",
            json={"enable_embedding": True},
        )
        return bool(response and response.status_code == 200)

    def enable_question_embedding(self, question_id: int) -> bool:
        response = self._request(
            "PUT",
            f"/api/card/{question_id}",
            json={"enable_embedding": True},
        )
        return bool(response and response.status_code == 200)

    def get_question_embed_url(self, question_id: int, params: Optional[Dict] = None) -> Optional[str]:
        self._set_last_error(None)
        try:
            from .jwt_embedding import get_jwt_service

            jwt_service = get_jwt_service()
            token = jwt_service.generate_question_token(question_id, params=params or {})
            return f"{self.embed_base_url}/embed/question/{token}#theme=night&bordered=true&titled=true"
        except Exception as exc:
            self._set_last_error(f"question_embed_url_failed: {exc}")
            logger.error("Failed to generate question embed URL for %s: %s", question_id, exc)
            return None

    def get_dashboard_embed_url(self, dashboard_id: int, params: Optional[Dict] = None) -> Optional[str]:
        self._set_last_error(None)
        try:
            from .jwt_embedding import get_jwt_service

            jwt_service = get_jwt_service()
            token = jwt_service.generate_dashboard_token(dashboard_id, params=params or {})
            return f"{self.embed_base_url}/embed/dashboard/{token}#theme=night&bordered=true&titled=true&background=false"
        except Exception as exc:
            self._set_last_error(f"dashboard_embed_url_failed: {exc}")
            logger.error("Failed to generate dashboard embed URL for %s: %s", dashboard_id, exc)
            return None


_metabase_service: Optional[MetabaseService] = None


def get_metabase_service() -> MetabaseService:
    global _metabase_service
    if _metabase_service is None:
        _metabase_service = MetabaseService()
    return _metabase_service
