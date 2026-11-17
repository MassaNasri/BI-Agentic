"""Public control-plane response metadata must not reveal internal bindings."""

import re

FORBIDDEN_METADATA_KEYS = frozenset({
    "clickhouse_table_name", "clickhouse_database", "destination_table",
    "physical_table_name", "physical_database", "file_path", "sqlite_path",
    "credential_ref", "credential_id", "ciphertext", "key_version",
    "_password_encrypted", "etl_service_url", "internal_url",
})
DATA_CONTAINERS = frozenset({"rows", "columns_schema"})
INTERNAL_DIAGNOSTIC = re.compile(
    r"(?:Traceback \(most recent call last\)|/app/|/srv/|"
    r"(?:postgresql|clickhouse|redis|kafka)://|"
    r"\bw\d+_d\d+_[A-Za-z0-9_]+\b|"
    r"\b(?:DB_PASSWORD|CLICKHOUSE_PASSWORD|CREDENTIAL_SECRET_KEY|"
    r"CREDENTIAL_RESOLVER_CONNECTOR_KEY|CREDENTIAL_RESOLVER_EXTRACTOR_KEY)\s*[=:]|"
    r"\b(?:biavora_(?:auth|workspace|integration|query|entitlement)|"
    r"clickhouse_(?:database|table_name)|destination_table|"
    r"credential_ref|ciphertext|key_version|authorization:|"
    r"psycopg2?\.|django\.db\.))",
    re.IGNORECASE,
)


def forbidden_public_metadata_keys(payload):
    """Inspect response metadata while treating authorized result rows as data."""
    found = set()

    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                name = str(key).lower()
                if name in FORBIDDEN_METADATA_KEYS:
                    found.add(name)
                elif name not in DATA_CONTAINERS:
                    visit(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    visit(payload)
    return frozenset(found)


def has_internal_error_diagnostic(payload):
    """Detect internal diagnostics in error metadata, excluding analytical rows."""
    if isinstance(payload, str):
        return INTERNAL_DIAGNOSTIC.search(payload) is not None
    if isinstance(payload, (list, tuple)):
        return any(has_internal_error_diagnostic(item) for item in payload)
    if isinstance(payload, dict):
        return any(
            has_internal_error_diagnostic(item)
            for key, item in payload.items() if str(key).lower() not in DATA_CONTAINERS
        )
    return False
