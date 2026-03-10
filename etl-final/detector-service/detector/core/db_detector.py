from shared.utils.db_type_utils import normalize_db_type


def detect_db_type(config: dict):
    """
    Detect database type based on config OR simple heuristics.
    """

    db_type = normalize_db_type(config.get("db_type"))
    if db_type in ["mysql", "postgres"]:
        return db_type

    raise Exception("Unsupported database type")
