from __future__ import annotations

from typing import Any


class DatasetBindingError(ValueError):
    pass


def normalize_dataset_context(payload: dict[str, Any] | None) -> dict[str, str]:
    source = payload if isinstance(payload, dict) else {}
    context = {
        "workspace_id": str(source.get("workspace_id", "")).strip(),
        "dataset_id": str(source.get("dataset_id", "")).strip() or str(source.get("source_id", "")).strip(),
        "manager_id": str(source.get("manager_id", "")).strip() or str(source.get("user_id", "")).strip(),
        "table_name": str(source.get("table_name", "")).strip() or str(source.get("dataset_table", "")).strip(),
        "source_id": str(source.get("source_id", "")).strip(),
        "report_id": str(source.get("report_id", "")).strip(),
    }
    return context


def validate_dataset_context(context: dict[str, str]) -> dict[str, str]:
    required = ("workspace_id", "dataset_id", "manager_id", "table_name")
    missing = [field for field in required if not str(context.get(field, "")).strip()]
    if missing:
        raise DatasetBindingError(
            f"Dataset binding context is missing required fields: {', '.join(missing)}"
        )
    return context

