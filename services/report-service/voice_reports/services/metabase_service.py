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
        return [str(value).strip() for value in values if str(value or "").strip()]

    @staticmethod
    def _normalize_display(value: Optional[str]) -> Optional[str]:
        if not isinstance(value, str):
            return None
        cleaned = value.strip().lower()
        if not cleaned:
            return None
        return CHART_TYPE_MAPPING.get(cleaned, cleaned)

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
        if len(numeric_columns) == 1 and row_count == 1:
            settings["graph.metrics"] = [numeric_columns[0]]
            return "scalar"
        return "table"

    def _prepare_visualization_settings(self, visualization_settings: Optional[Dict[str, Any]]) -> tuple[str, Dict[str, Any]]:
        settings: Dict[str, Any] = dict(visualization_settings or {})
        requested_display = self._normalize_display(settings.get("display") or settings.get("chart_type"))
        fallback_applied = False
        fallback_reason = ""
        if not requested_display:
            requested_display = self._safe_display_from_shape(settings)
            fallback_applied = True
            fallback_reason = "missing_requested_display"

        display = requested_display
        if display not in SUPPORTED_DISPLAYS:
            display = self._safe_display_from_shape(settings)
            fallback_applied = True
            fallback_reason = f"unsupported_display:{requested_display}"

        if display == "line":
            dimensions = self._string_list(settings.get("graph.dimensions")) or self._string_list(settings.get("time_columns"))
            metrics = self._string_list(settings.get("graph.metrics")) or self._string_list(settings.get("numeric_columns"))
            if dimensions and metrics:
                settings["graph.dimensions"] = [dimensions[0]]
                settings["graph.metrics"] = [metrics[0]]
            else:
                fallback_applied = True
                fallback_reason = "invalid_line_shape"
                display = self._safe_display_from_shape(settings)
        elif display == "scatter":
            dimensions = self._string_list(settings.get("graph.dimensions"))
            metrics = self._string_list(settings.get("graph.metrics"))
            numeric_columns = self._string_list(settings.get("numeric_columns"))
            x_axis = dimensions[0] if dimensions else (numeric_columns[0] if len(numeric_columns) >= 1 else "")
            y_axis = metrics[0] if metrics else (numeric_columns[1] if len(numeric_columns) >= 2 else "")
            if x_axis and y_axis and x_axis != y_axis:
                settings["graph.dimensions"] = [x_axis]
                settings["graph.metrics"] = [y_axis]
            else:
                fallback_applied = True
                fallback_reason = "invalid_scatter_shape"
                display = self._safe_display_from_shape(settings)
        elif display == "bar":
            dimensions = self._string_list(settings.get("graph.dimensions")) or self._string_list(settings.get("category_columns"))
            metrics = self._string_list(settings.get("graph.metrics")) or self._string_list(settings.get("numeric_columns"))
            if dimensions:
                settings["graph.dimensions"] = [dimensions[0]]
            if metrics:
                settings["graph.metrics"] = [metrics[0]]
        elif display in {"histogram", "scalar"}:
            metrics = self._string_list(settings.get("graph.metrics")) or self._string_list(settings.get("numeric_columns"))
            if metrics:
                settings["graph.metrics"] = [metrics[0]]

        settings["display"] = display
        settings["requested_display"] = requested_display
        settings["fallback_applied"] = fallback_applied
        settings["fallback_reason"] = fallback_reason
        self.last_display = display
        self.last_fallback_applied = fallback_applied
        self.last_fallback_reason = fallback_reason
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
        display, visualization_settings = self._prepare_visualization_settings(visualization_settings)

        payload: Dict[str, Any] = {
            "name": name,
            "dataset_query": {
                "type": "native",
                "native": {"query": sql},
                "database": self.database_id,
            },
            "display": display,
            "visualization_settings": visualization_settings,
        }
        clean_description = self._clean_non_blank_string(description)
        if clean_description is not None:
            payload["description"] = clean_description

        logger.info(
            "Creating Metabase question: name=%s database_id=%s display=%s sql_len=%s",
            name,
            self.database_id,
            payload.get("display"),
            len(sql or "")
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
        display, visualization_settings = self._prepare_visualization_settings(visualization_settings)

        payload: Dict[str, Any] = {
            "name": name,
            "dataset_query": {
                "type": "native",
                "native": {"query": sql},
                "database": self.database_id,
            },
            "display": display,
            "visualization_settings": visualization_settings,
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
