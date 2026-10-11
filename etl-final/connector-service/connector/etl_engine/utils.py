from shared.connectors import ConnectorError, connector_registry


def test_db_connection(db_type, host, user, password, database, port):
    """
    Tests a database connection for MySQL or PostgreSQL.
    """

    connector = connector_registry.get(db_type)
    try:
        result = connector.test_connection({
            "host": host, "port": port, "username": user, "password": password,
            "database": database,
        })
        return result["success"], result["message"]
    except ConnectorError as exc:
        return False, exc.message
