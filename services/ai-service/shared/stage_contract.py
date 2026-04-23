from __future__ import annotations

from typing import Any


CANONICAL_STAGE_STATUSES = {"success", "failed", "skipped", "degraded", "rejected"}

_STATUS_ALIASES = {
    "ok": "success",
    "passed": "success",
    "completed": "success",
    "done": "success",
    "routed": "success",
    "error": "failed",
    "failure": "failed",
}


def normalize_stage_status(status: Any, *, degraded: bool = False) -> str:
    normalized = str(status or "").strip().lower()
    canonical = _STATUS_ALIASES.get(normalized, normalized or "unknown")
    if canonical == "success" and degraded:
        return "degraded"
    if canonical in CANONICAL_STAGE_STATUSES:
        return canonical
    return "unknown"


def stage_allows_progress(status: Any, *, degraded: bool = False) -> bool:
    normalized = normalize_stage_status(status, degraded=degraded)
    return normalized in {"success", "degraded"}

