"""Remove only stale SurrealDB metadata created by P0-C E2E attempts."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import requests

from verify_p0c_e2e import read_dotenv


REPO_ROOT = Path(__file__).resolve().parents[1]
SURREAL_URL = "http://127.0.0.1:8008/sql"
TEST_SOURCE_PREFIX = "p0c_sales_"
TABLES = (
    "connection_metadata",
    "schema_metadata",
    "extraction_metadata",
    "cleaning_metadata",
    "loading_metadata",
)


def query(sql: str, config: dict[str, str]) -> list[dict[str, Any]]:
    response = requests.post(
        SURREAL_URL,
        headers={
            "surreal-ns": "bi_etl",
            "surreal-db": "etl_logs",
            "Accept": "application/json",
        },
        auth=(config["SURREAL_USER"], config["SURREAL_PASS"]),
        data=sql,
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError("Unexpected SurrealDB response shape.")
    for statement in payload:
        if statement.get("status") != "OK":
            raise RuntimeError("SurrealDB rejected the scoped cleanup query.")
    return payload


def count_test_rows(config: dict[str, str]) -> dict[str, int]:
    statements = " ".join(
        f"SELECT id FROM {table} WHERE string::starts_with(source_id, '{TEST_SOURCE_PREFIX}');"
        for table in TABLES
    )
    payload = query(statements, config)
    return {
        table: len(statement.get("result") or [])
        for table, statement in zip(TABLES, payload, strict=True)
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="delete the scoped P0-C records")
    args = parser.parse_args()

    config = read_dotenv(REPO_ROOT / ".env")
    before = count_test_rows(config)
    print("P0C_STALE_METADATA_BEFORE:" + ",".join(f"{key}={value}" for key, value in before.items()))

    if not args.apply:
        return 0

    statements = " ".join(
        f"DELETE {table} WHERE string::starts_with(source_id, '{TEST_SOURCE_PREFIX}');"
        for table in TABLES
    )
    query(statements, config)
    after = count_test_rows(config)
    print("P0C_STALE_METADATA_AFTER:" + ",".join(f"{key}={value}" for key, value in after.items()))
    if any(after.values()):
        raise RuntimeError("Scoped P0-C metadata cleanup could not be proven.")
    print("P0C_STALE_METADATA_CLEANUP:PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
