"""Allowlisted, non-secret connection metadata; C3 will own secret references."""

SAFE_KEYS = frozenset({
    "host", "port", "database", "service_name", "username", "schema",
    "sslmode", "ssl_mode", "tls", "encrypt", "trust_server_certificate",
    "secure", "verify", "connect_timeout", "read_timeout",
})


def safe_connection_metadata(configuration, *, strict=False):
    if not isinstance(configuration, dict):
        raise ValueError("Connection metadata must be an object.")
    result = {}
    for key, value in configuration.items():
        if key not in SAFE_KEYS:
            if strict:
                raise ValueError("Only non-secret connection metadata may be stored.")
            continue
        if not isinstance(value, (str, int, bool)) or len(str(value)) > 500:
            raise ValueError("Connection metadata contains an invalid value.")
        result[key] = value
    return result


def public_source(source):
    return {
        "id": source.pk,
        "workspace_id": source.workspace_id,
        "name": source.name,
        "engine": source.engine,
        "connection_metadata": source.connection_metadata,
        "selected_tables": source.selected_tables,
        "state": source.state,
        "transport": source.transport,
        "credential_configured": source.credentials.filter(state="active").exists(),
        "configuration_version": source.configuration_version,
        "created_at": source.created_at,
        "updated_at": source.updated_at,
    }
