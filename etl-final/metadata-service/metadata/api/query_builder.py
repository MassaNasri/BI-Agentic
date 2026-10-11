import json


ALLOWED_METADATA_TABLES = {
    "connection_metadata",
    "schema_metadata",
    "extraction_metadata",
    "cleaning_metadata",
    "loading_metadata",
}


def build_select_query(table: str, scope=None):
    if table not in ALLOWED_METADATA_TABLES:
        raise ValueError("Unsupported metadata table")
    if scope is None:
        raise ValueError("Metadata scope is required")
    dataset = json.dumps(scope.dataset_id)
    job = json.dumps(str(scope.ingestion_job_id))
    return (
        f"SELECT * FROM {table} WHERE workspace_id = {int(scope.workspace_id)} "
        f"AND dataset_id = {dataset} AND ingestion_job_id = {job};"
    )
