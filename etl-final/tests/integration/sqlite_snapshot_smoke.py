"""Runtime smoke test for SQLite prepare -> discover -> Kafka snapshot queueing.

Run this inside the connector container.  It intentionally reads the internal
service credential from the process environment and never prints it.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import uuid

import requests


BASE_URL = os.getenv("CONNECTOR_SMOKE_BASE_URL", "http://127.0.0.1:8000/api")
WORKSPACE_ID = int(os.getenv("CONNECTOR_SMOKE_WORKSPACE_ID", "99991"))
DATASET_ID = os.getenv("CONNECTOR_SMOKE_DATASET_ID", "9999101")
JOB_ID = str(uuid.uuid4())


def headers() -> dict[str, str]:
    return {
        "X-Internal-Service": "etl-admin",
        "X-Internal-API-Key": os.environ["ETL_INTERNAL_API_KEY"],
        "X-Workspace-ID": str(WORKSPACE_ID),
        "X-Dataset-ID": DATASET_ID,
        "X-Ingestion-Job-ID": JOB_ID,
    }


def assert_success(response: requests.Response, expected=(200,)) -> dict:
    if response.status_code not in expected:
        raise AssertionError(f"HTTP {response.status_code}: {response.text[:500]}")
    payload = response.json()
    if not payload.get("success"):
        raise AssertionError(json.dumps(payload, sort_keys=True))
    return payload["data"]


def main() -> None:
    capabilities = assert_success(
        requests.get(f"{BASE_URL}/databases/capabilities/", headers=headers(), timeout=15)
    )
    connector_ids = [item["id"] for item in capabilities["connectors"]]

    with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as handle:
        sqlite_path = handle.name
    try:
        connection = sqlite3.connect(sqlite_path)
        connection.execute(
            'CREATE TABLE "Sales Data" ('
            '"Order ID" INTEGER PRIMARY KEY, "customer" TEXT, '
            '"amount" NUMERIC, "optional" TEXT)'
        )
        connection.executemany(
            'INSERT INTO "Sales Data" VALUES (?, ?, ?, ?)',
            [
                (1, "Damascus – مرحبا", "12.3400", None),
                (2, "Zoë", "0.01", "quoted \"value\""),
                (3, "東京", "999999.99", ""),
            ],
        )
        connection.commit()
        connection.close()

        with open(sqlite_path, "rb") as uploaded:
            prepared = assert_success(
                requests.post(
                    f"{BASE_URL}/databases/sqlite/prepare/",
                    headers=headers(),
                    files={"file": ("sales.sqlite3", uploaded, "application/vnd.sqlite3")},
                    timeout=30,
                )
            )
        tables = prepared["tables"]
        selected = next(item for item in tables if item["name"] == "Sales Data")
        queued = assert_success(
            requests.post(
                f"{BASE_URL}/databases/snapshot/",
                headers=headers(),
                json={
                    "engine": "sqlite",
                    "configuration": {"sqlite_token": prepared["sqlite_token"]},
                    "tables": [{"schema": selected.get("schema"), "name": selected["name"]}],
                    "chunk_size": 100,
                },
                timeout=30,
            ),
            expected=(202,),
        )
        print(
            json.dumps(
                {
                    "connectors": connector_ids,
                    "discovered_table": selected["name"],
                    "queued_state": queued["state"],
                    "rows_seeded": 3,
                    "workspace_id": WORKSPACE_ID,
                    "dataset_id": DATASET_ID,
                    "job_id": JOB_ID,
                },
                sort_keys=True,
            )
        )
    finally:
        try:
            os.unlink(sqlite_path)
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    main()
