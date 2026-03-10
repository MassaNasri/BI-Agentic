from shared.utils.db_type_utils import canonical_db_types, normalize_db_type


def test_normalize_db_type_aliases():
    assert normalize_db_type("postgresql") == "postgres"
    assert normalize_db_type("postgres") == "postgres"
    assert normalize_db_type("mysql") == "mysql"
    assert normalize_db_type("sqlite3") == "sqlite"
    assert normalize_db_type("sqlserver") == "mssql"
    assert normalize_db_type("oracle") == "oracle"


def test_normalize_db_type_unknown_returns_none():
    assert normalize_db_type("mongodb") is None
    assert normalize_db_type("") is None
    assert normalize_db_type(None) is None


def test_canonical_db_types_vocabulary():
    assert canonical_db_types() == ("mysql", "postgres", "sqlite", "mssql", "oracle")

