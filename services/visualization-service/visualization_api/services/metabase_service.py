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

logger = logging.getLogger(__name__)

_session_token: Optional[str] = None
_session_token_expires_at: float = 0.0

METABASE_TIMEOUT_SECONDS = int(os.getenv("METABASE_TIMEOUT_SECONDS", "30"))
METABASE_AUTH_RETRIES = int(os.getenv("METABASE_AUTH_RETRIES", "2"))
METABASE_HEALTH_RETRIES = int(os.getenv("METABASE_HEALTH_RETRIES", "2"))
METABASE_SESSION_TTL_SECONDS = int(os.getenv("METABASE_SESSION_TTL_SECONDS", "1800"))

CHART_TYPE_MAPPING: Dict[str, str] = {
    "line": "line",
    "bar": "bar",
    "scatter": "scatter",
    "histogram": "histogram",
    "kpi": "scalar",
    "card": "scalar",
    "scalar": "scalar",
    "number": "scalar",
    "grouped_bar": "bar",
    "table": "table",
}
SUPPORTED_DISPLAYS = {"line", "bar", "scatter", "scalar", "table", "histogram"}
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

    def _resolve_line_dimension_metric(self, settings: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
        dimensions = self._string_list(settings.get("graph.dimensions"))
        metrics = self._string_list(settings.get("graph.metrics"))
        if dimensions and metrics:
            return dimensions[0], metrics[0]

        time_columns = self._string_list(settings.get("time_columns"))
        numeric_columns = self._string_list(settings.get("numeric_columns"))
        if time_columns and numeric_columns:
            return time_columns[0], numeric_columns[0]
        category_columns = self._string_list(settings.get("category_columns"))
        if category_columns and numeric_columns:
            return category_columns[0], numeric_columns[0]
        return None, None

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

    def _safe_display_from_shape(self, settings: Dict[str, Any]) -> str:
        numeric_columns = self._string_list(settings.get("numeric_columns"))
        time_columns = self._string_list(settings.get("time_columns"))
        category_columns = self._string_list(settings.get("category_columns"))
        row_count = int(settings.get("row_count") or 0)

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
            settings["graph.metrics"] = [numeric_columns[0]]
            return "histogram"
        if len(numeric_columns) == 1 and row_count == 1:
            settings["graph.metrics"] = [numeric_columns[0]]
            return "scalar"
        return DEFAULT_FALLBACK_DISPLAY

    def _prepare_visualization_settings(self, visualization_settings: Optional[Dict[str, Any]]) -> tuple[str, Dict[str, Any]]:
        settings: Dict[str, Any] = dict(visualization_settings or {})

        requested_display = self._normalize_display(
            settings.get("display") or settings.get("chart_type")
        )
        fallback_applied = False
        fallback_reason = ""
        if not requested_display:
            requested_display = self._safe_display_from_shape(settings)
            fallback_applied = True
            fallback_reason = "missing_requested_display"
            logger.info("No chart display provided; selected safe display '%s'", requested_display)

        display = requested_display
        if display not in SUPPORTED_DISPLAYS:
            fallback_applied = True
            fallback_reason = f"unsupported_display:{requested_display}"
            logger.warning(
                "Unsupported chart display '%s'; falling back to '%s'",
                requested_display,
                self._safe_display_from_shape(settings),
            )
            display = self._safe_display_from_shape(settings)

        if display == "scatter":
            x_column, y_column = self._resolve_scatter_axes(settings)
            if not x_column or not y_column or x_column == y_column:
                fallback_applied = True
                fallback_reason = "invalid_scatter_shape"
                logger.warning(
                    "Invalid scatter configuration (x=%s, y=%s); choosing safe display",
                    x_column,
                    y_column,
                )
                display = self._safe_display_from_shape(settings)
            else:
                settings["graph.dimensions"] = [x_column]
                settings["graph.metrics"] = [y_column]
        elif display == "line":
            time_dimension, metric_column = self._resolve_line_dimension_metric(settings)
            if not time_dimension or not metric_column:
                fallback_applied = True
                fallback_reason = "invalid_line_shape"
                logger.warning(
                    "Invalid line configuration (time=%s, metric=%s); choosing safe fallback display",
                    time_dimension,
                    metric_column,
                )
                safe_display = self._safe_display_from_shape(settings)
                if safe_display == "table" and requested_display == "line":
                    display = "line"
                    fallback_reason = "line_axes_unresolved_preserved"
                else:
                    display = safe_display
            else:
                settings["graph.dimensions"] = [time_dimension]
                settings["graph.metrics"] = [metric_column]
        elif display == "histogram":
            metric_column = self._resolve_histogram_metric(settings)
            if not metric_column:
                fallback_applied = True
                fallback_reason = "invalid_histogram_shape"
                logger.warning("Histogram display requested but no metric could be resolved; choosing safe display.")
                display = self._safe_display_from_shape(settings)
            else:
                settings["graph.metrics"] = [metric_column]
                logger.info("Histogram metric resolved: %s", metric_column)
        elif display == "bar":
            dimension_column, metric_column = self._resolve_bar_dimension_metric(settings)
            if not metric_column:
                metric_column = self._resolve_histogram_metric(settings)
            if not metric_column:
                fallback_applied = True
                fallback_reason = "invalid_bar_shape"
                logger.warning(
                    "Invalid bar configuration (dimension=%s, metric=%s); preserving explicit bar display",
                    dimension_column,
                    metric_column,
                )
            else:
                settings["graph.metrics"] = [metric_column]
                if dimension_column:
                    settings["graph.dimensions"] = [dimension_column]

        settings["display"] = display
        settings["requested_display"] = requested_display
        settings["fallback_applied"] = fallback_applied
        settings["fallback_reason"] = fallback_reason
        self.last_display = display
        self.last_fallback_applied = fallback_applied
        self.last_fallback_reason = fallback_reason
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

        payload: Dict[str, Any] = {
            "name": name,
            "dataset_query": {
                "type": "native",
                "native": {"query": sql},
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
            len(sql or ""),
            visualization_settings.get("chart_type") if isinstance(visualization_settings, dict) else "",
            bool(
                isinstance(normalized_visualization_settings, dict)
                and normalized_visualization_settings.get("display") != (visualization_settings or {}).get("display")
            ),
        )
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
            logger.info("Created Metabase question id=%s", question_id)
            return question_id
        if response:
            details = self._extract_error_details(response)
            self._set_last_error(f"create_question_failed: {details}")
            logger.error("Create question failed: %s %s", response.status_code, details)
        elif self.last_error is None:
            self._set_last_error("create_question_failed: no_response")
        return None

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

        payload: Dict[str, Any] = {
            "name": name,
            "dataset_query": {
                "type": "native",
                "native": {"query": sql},
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
        payload = {
            "cardId": question_id,
            "row": row,
            "col": col,
            "sizeX": size_x,
            "sizeY": size_y,
        }
        response = self._request("POST", f"/api/dashboard/{dashboard_id}/cards", json=payload)
        if response and response.status_code in (200, 201):
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
            return f"{self.embed_base_url}/embed/question/{token}#bordered=true&titled=true"
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
            return f"{self.embed_base_url}/embed/dashboard/{token}#bordered=true&titled=true"
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
