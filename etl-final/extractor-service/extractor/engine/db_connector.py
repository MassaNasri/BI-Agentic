"""Compatibility facade over the shared database connector registry."""

from shared.connectors import connector_registry


class DBConnector:
    """Open snapshot connections without source-specific listener branches."""

    def get_connector(self, cfg):
        return connector_registry.get(cfg.get("db_type"))

    def connect(self, cfg):
        connector = self.get_connector(cfg)
        validated = connector.validate_configuration(cfg)
        return connector.connect(validated)

    def close(self, connection):
        if connection is not None:
            connection.close()
