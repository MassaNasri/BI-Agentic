from __future__ import annotations

import logging
import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, SERVICE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from preprocessing_high import value_index as vi  # noqa: E402
from preprocessing_high.schemas import HighPreprocessConfig  # noqa: E402


class _Result:
    def __init__(self, rows):
        self.result_rows = rows


class _FakeClickHouseClient:
    def __init__(self, values_by_column: dict[str, list[str]], cardinality_by_column: dict[str, int] | None = None):
        self.values_by_column = values_by_column
        self.cardinality_by_column = cardinality_by_column or {}
        self.queries: list[str] = []

    def query(self, sql: str):
        self.queries.append(sql)
        column = sql.split("SELECT DISTINCT `", 1)[1].split("`", 1)[0]
        if "SELECT count()" in sql:
            cardinality = self.cardinality_by_column.get(column, len(self.values_by_column.get(column, [])))
            return _Result([(cardinality,)])
        return _Result([(value,) for value in self.values_by_column.get(column, [])])


class _FailingRedis:
    def get(self, key: str):  # noqa: ARG002
        raise RuntimeError("redis down")

    def setex(self, key: str, ttl: int, value: str):  # noqa: ARG002
        raise RuntimeError("redis down")


def setup_function():
    vi._VALUE_INDEX_CACHE.clear()


def _config(**overrides) -> HighPreprocessConfig:
    base = {
        "ollama_url": "http://localhost",
        "ollama_model": "test",
        "request_timeout_seconds": 1.0,
        "max_retries": 0,
        "clickhouse_host": "localhost",
        "clickhouse_port": 8123,
        "clickhouse_user": "user",
        "clickhouse_password": "pass",
        "clickhouse_default_database": "etl",
        "user_database_template": "",
        "schema_cache_ttl_seconds": 0,
        "default_user_id": "u1",
        "value_index_enabled": True,
        "value_index_max_cardinality_threshold": 2,
        "value_index_max_values_per_column": 10,
        "value_index_cache_ttl_seconds": 300,
        "value_index_redis_url": "",
    }
    base.update(overrides)
    return HighPreprocessConfig(**base)


def _schema(*columns: tuple[str, str], database: str = "etl", table: str = "sales_fact", user_id: str = "u1"):
    return SimpleNamespace(
        user_id=user_id,
        database=database,
        schema={
            "tables": [table],
            "columns": {table: [{"name": name, "type": clickhouse_type} for name, clickhouse_type in columns]},
        },
    )


def test_indexes_only_safe_low_cardinality_string_columns():
    loaded_schema = _schema(
        ("city", "String"),
        ("product_name", "LowCardinality(String)"),
        ("amount", "Float64"),
        ("order_date", "Date"),
        ("customer_id", "String"),
        ("email", "String"),
        ("segment", "String"),
    )
    client = _FakeClickHouseClient(
        {
            "city": ["Damascus", "Aleppo"],
            "product_name": ["Samsung Galaxy"],
            "segment": ["VIP", "Retail", "Wholesale"],
        },
        {"segment": 3},
    )

    index = vi.load_value_index(
        loaded_schema=loaded_schema,
        config=_config(),
        logger=logging.getLogger(__name__),
        clickhouse_client=client,
    )

    assert index["damascus"][0]["column"] == "city"
    assert index["samsung galaxy"][0]["column"] == "product_name"
    assert "vip" not in index
    joined_queries = "\n".join(client.queries)
    assert "`amount`" not in joined_queries
    assert "`order_date`" not in joined_queries
    assert "`customer_id`" not in joined_queries
    assert "`email`" not in joined_queries


def test_cache_hit_avoids_additional_clickhouse_requests():
    loaded_schema = _schema(("city", "String"))
    client = _FakeClickHouseClient({"city": ["Damascus"]})
    config = _config()

    first = vi.load_value_index(
        loaded_schema=loaded_schema,
        config=config,
        logger=logging.getLogger(__name__),
        clickhouse_client=client,
    )
    query_count = len(client.queries)
    second = vi.load_value_index(
        loaded_schema=loaded_schema,
        config=config,
        logger=logging.getLogger(__name__),
        clickhouse_client=client,
    )

    assert first == second
    assert len(client.queries) == query_count


def test_workspace_and_table_cache_isolation():
    client = _FakeClickHouseClient({"city": ["Damascus"]})
    config = _config()

    vi.load_value_index(
        loaded_schema=_schema(("city", "String"), database="etl_a", table="sales_a"),
        config=config,
        logger=logging.getLogger(__name__),
        clickhouse_client=client,
    )
    first_count = len(client.queries)
    vi.load_value_index(
        loaded_schema=_schema(("city", "String"), database="etl_b", table="sales_b"),
        config=config,
        logger=logging.getLogger(__name__),
        clickhouse_client=client,
    )

    assert len(client.queries) == first_count * 2


def test_normalization_preserves_arabic_and_multi_word_values():
    assert vi.normalize_value("  Samsung   Galaxy  ") == "samsung galaxy"
    assert vi.normalize_value("دمشق") == "دمشق"


def test_same_value_in_two_columns_returns_multiple_candidates():
    loaded_schema = _schema(("city", "String"), ("region", "String"))
    client = _FakeClickHouseClient({"city": ["North"], "region": ["North"]})

    index = vi.load_value_index(
        loaded_schema=loaded_schema,
        config=_config(),
        logger=logging.getLogger(__name__),
        clickhouse_client=client,
    )

    assert {candidate["column"] for candidate in index["north"]} == {"city", "region"}


def test_redis_failure_does_not_break_value_index_loading():
    loaded_schema = _schema(("city", "String"))
    client = _FakeClickHouseClient({"city": ["Damascus"]})

    index = vi.load_value_index(
        loaded_schema=loaded_schema,
        config=_config(value_index_redis_url="redis://localhost:6379/0"),
        logger=logging.getLogger(__name__),
        clickhouse_client=client,
        redis_client=_FailingRedis(),
    )

    assert "damascus" in index
