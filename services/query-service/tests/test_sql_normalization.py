from query_api.utils.sql_normalization import normalize_sql_table_references, normalize_table_name


def test_mixed_quoted_qualified_identifier_is_not_corrupted():
    sql = "SELECT * FROM etl.`p0c_sales_abc_csv`"
    assert normalize_sql_table_references(sql, "etl") == "SELECT * FROM etl.p0c_sales_abc_csv"


def test_individually_quoted_qualified_identifier_is_normalized():
    sql = "SELECT * FROM `etl`.`sales` JOIN `etl`.`products` ON sales.id = products.id"
    assert normalize_sql_table_references(sql, "etl") == (
        "SELECT * FROM etl.sales JOIN etl.products ON sales.id = products.id"
    )


def test_unqualified_identifier_receives_default_database():
    assert normalize_sql_table_references("SELECT * FROM sales", "etl") == "SELECT * FROM etl.sales"


def test_quoted_special_identifier_remains_segment_quoted():
    assert normalize_table_name("etl.`sales-2026`", "etl") == "etl.`sales-2026`"
