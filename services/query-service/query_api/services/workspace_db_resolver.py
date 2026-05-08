"""Workspace -> ClickHouse database resolver.

query-service owns the database upload/resolver domain. Runtime resolution is
therefore local to query-service tables:

    workspace_id -> manager_databases.workspace_id -> clickhouse_database
"""

from __future__ import annotations

from dataclasses import dataclass


class WorkspaceClickhouseDbResolutionError(Exception):
    """Raised when a workspace cannot be bound to a ClickHouse database."""

    def __init__(self, code: str, message: str, *, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = int(http_status)


@dataclass(frozen=True)
class WorkspaceClickhouseDbResolution:
    workspace_id: int
    clickhouse_db: str
    workspace_name: str = ""


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
    "resolve_workspace_clickhouse_db",
]
