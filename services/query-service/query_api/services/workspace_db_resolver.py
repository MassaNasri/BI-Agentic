"""Workspace -> ClickHouse database resolver.

query-service owns the database upload/resolver domain. Runtime resolution is
therefore local to query-service tables:

    workspace_id -> manager_databases.workspace_id -> clickhouse_database
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


class WorkspaceClickhouseDbResolutionError(Exception):
    """Raised when a workspace cannot be bound to a ClickHouse database."""

    def __init__(self, code: str, message: str, *, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = int(http_status)


class WorkspaceDatasetBindingError(Exception):
    """Raised when workspace dataset metadata is missing, stale, or unsafe."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int = 422,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = int(http_status)
        self.details = dict(details or {})


@dataclass(frozen=True)
class WorkspaceClickhouseDbResolution:
    workspace_id: int
    clickhouse_db: str
    workspace_name: str = ""


@dataclass(frozen=True)
class WorkspaceDatasetBinding:
    workspace_id: int
    dataset_id: int
    manager_id: int
    clickhouse_db: str
    table_name: str
    allowed_tables: frozenset[str]
    etl_status: str


def _required_positive_int(value: object, *, field_name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise WorkspaceDatasetBindingError(
            f"{field_name}_invalid",
            f"{field_name} must be a positive integer.",
            http_status=400,
        ) from exc
    if parsed <= 0:
        raise WorkspaceDatasetBindingError(
            f"{field_name}_invalid",
            f"{field_name} must be a positive integer.",
            http_status=400,
        )
    return parsed


def resolve_workspace_dataset_binding(
    workspace_id: object,
    *,
    dataset_id: object = None,
    table_name: object = None,
    verify_physical: bool = True,
    require_dataset_id: bool = False,
    database_model=None,
    table_exists: Callable[[str, str], dict] | None = None,
) -> WorkspaceDatasetBinding:
    """Resolve and validate one authoritative workspace dataset binding."""

    workspace_id_int = _required_positive_int(workspace_id, field_name="workspace_id")

    if database_model is None:
        from database.models import Database

        database_model = Database

    requested_dataset_id = None
    if dataset_id not in (None, "", b""):
        requested_dataset_id = _required_positive_int(dataset_id, field_name="dataset_id")
        database = database_model.objects.filter(pk=requested_dataset_id).first()
        if database is None:
            raise WorkspaceDatasetBindingError(
                "dataset_metadata_stale",
                f"Dataset {requested_dataset_id} no longer exists in query-service metadata.",
                details={"workspace_id": workspace_id_int, "dataset_id": requested_dataset_id},
            )
    elif require_dataset_id:
        raise WorkspaceDatasetBindingError(
            "dataset_id_required",
            "A logical dataset_id is required for analytical queries.",
            http_status=400,
            details={"workspace_id": workspace_id_int},
        )
    else:
        database = (
            database_model.objects.filter(workspace_id=workspace_id_int)
            .order_by("-upload_date")
            .first()
        )
        if database is None:
            raise WorkspaceDatasetBindingError(
                "dataset_metadata_missing",
                f"Workspace {workspace_id_int} has no uploaded dataset.",
                details={"workspace_id": workspace_id_int},
            )

    database_workspace_id = getattr(database, "workspace_id", None)
    if database_workspace_id is None or int(database_workspace_id) != workspace_id_int:
        raise WorkspaceDatasetBindingError(
            "dataset_workspace_mismatch",
            "The requested dataset does not belong to the authenticated workspace.",
            http_status=403,
            details={
                "workspace_id": workspace_id_int,
                "dataset_id": int(database.pk),
            },
        )

    etl_status = str(getattr(database, "etl_status", "") or "").strip().lower()
    if etl_status in {"pending", "processing"}:
        raise WorkspaceDatasetBindingError(
            "dataset_not_ready",
            f"Dataset {database.pk} is still processing.",
            http_status=409,
            details={"workspace_id": workspace_id_int, "dataset_id": int(database.pk)},
        )
    if etl_status != "completed":
        raise WorkspaceDatasetBindingError(
            "dataset_metadata_invalid",
            f"Dataset {database.pk} is not usable (ETL status: {etl_status or 'unknown'}).",
            details={"workspace_id": workspace_id_int, "dataset_id": int(database.pk)},
        )

    clickhouse_db = str(getattr(database, "clickhouse_database", "") or "").strip()
    stored_table_name = str(getattr(database, "clickhouse_table_name", "") or "").strip()
    allowed_tables: list[str] = []
    if stored_table_name:
        allowed_tables.append(stored_table_name)
    source_tables = getattr(database, "source_tables", None)
    if isinstance(source_tables, (list, tuple)):
        for source_table in source_tables:
            if not isinstance(source_table, dict):
                continue
            destination = str(source_table.get("destination_table") or "").strip()
            status = str(source_table.get("status") or "completed").strip().lower()
            if destination and status == "completed":
                allowed_tables.append(destination)
    allowed_tables = list(dict.fromkeys(allowed_tables))
    if not clickhouse_db or not allowed_tables:
        raise WorkspaceDatasetBindingError(
            "dataset_metadata_invalid",
            f"Dataset {database.pk} has incomplete ClickHouse metadata.",
            details={"workspace_id": workspace_id_int, "dataset_id": int(database.pk)},
        )

    requested_table_name = str(table_name or "").strip()
    if requested_table_name and requested_table_name not in allowed_tables:
        raise WorkspaceDatasetBindingError(
            "dataset_table_mismatch",
            "The requested table does not match the dataset metadata.",
            details={
                "workspace_id": workspace_id_int,
                "dataset_id": int(database.pk),
            },
        )

    if verify_physical:
        if table_exists is None:
            from database.utils import ClickHouseClient

            client = ClickHouseClient()
            table_exists = client.table_exists
        for allowed_table in allowed_tables:
            result = table_exists(clickhouse_db, allowed_table)
            if not result.get("success"):
                raise WorkspaceDatasetBindingError(
                    "dataset_source_unavailable",
                    "ClickHouse could not validate the dataset table.",
                    http_status=503,
                    details={"workspace_id": workspace_id_int, "dataset_id": int(database.pk)},
                )
            if not result.get("exists"):
                raise WorkspaceDatasetBindingError(
                    "dataset_physical_table_missing",
                    "The dataset metadata points to a ClickHouse table that does not exist.",
                    details={"workspace_id": workspace_id_int, "dataset_id": int(database.pk)},
                )

    return WorkspaceDatasetBinding(
        workspace_id=workspace_id_int,
        dataset_id=int(database.pk),
        manager_id=int(database.manager),
        clickhouse_db=clickhouse_db,
        table_name=stored_table_name,
        allowed_tables=frozenset(allowed_tables),
        etl_status=etl_status,
    )


def resolve_workspace_clickhouse_db(workspace_id: object) -> WorkspaceClickhouseDbResolution:
    """Resolve workspace_id to a bound ClickHouse database name."""

    if workspace_id in (None, "", b""):
        raise WorkspaceClickhouseDbResolutionError(
            "workspace_id_missing",
            "Internal query API requires workspace_id; none was provided.",
            http_status=400,
        )

    try:
        workspace_id_int = int(workspace_id)
    except (TypeError, ValueError) as exc:
        raise WorkspaceClickhouseDbResolutionError(
            "workspace_id_missing",
            f"Internal query API requires a numeric workspace_id (got {workspace_id!r}).",
            http_status=400,
        ) from exc

    from database.models import Database

    database = (
        Database.objects.filter(workspace_id=workspace_id_int)
        .order_by("-upload_date")
        .first()
    )
    if database is None:
        raise WorkspaceClickhouseDbResolutionError(
            "workspace_database_missing",
            f"Workspace {workspace_id_int} has no uploaded database binding in query-service.",
            http_status=403,
        )

    clickhouse_db = str(getattr(database, "clickhouse_database", "") or "").strip()
    if not clickhouse_db:
        raise WorkspaceClickhouseDbResolutionError(
            "workspace_clickhouse_db_missing",
            (
                f"Workspace {workspace_id_int} database row has an empty clickhouse_database; "
                "the workspace cannot run analytical queries."
            ),
            http_status=403,
        )

    return WorkspaceClickhouseDbResolution(
        workspace_id=workspace_id_int,
        clickhouse_db=clickhouse_db,
        workspace_name="",
    )


__all__ = [
    "WorkspaceClickhouseDbResolution",
    "WorkspaceClickhouseDbResolutionError",
    "WorkspaceDatasetBinding",
    "WorkspaceDatasetBindingError",
    "resolve_workspace_clickhouse_db",
    "resolve_workspace_dataset_binding",
]
