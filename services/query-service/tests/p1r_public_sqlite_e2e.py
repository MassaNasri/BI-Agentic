"""P1-R public SQLite upload-to-ClickHouse acceptance harness.

Run inside query-service. The harness enters through the API gateway, uses a
real SQLite file, verifies multi-table/empty-table behavior and file-boundary
rejections, and deletes the resulting dataset in ``finally``.
"""
from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

import django
import requests


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "service_config.settings")
django.setup()

from rest_framework_simplejwt.tokens import AccessToken  # noqa: E402
from database.models import Database  # noqa: E402
from database.utils import ClickHouseClient, quote_clickhouse_identifier  # noqa: E402


BASE_URL = os.getenv("P1_PUBLIC_API_URL", "http://api-gateway:8000").rstrip("/")
WORKSPACE_ID = int(os.getenv("P1_E2E_WORKSPACE_ID", "99992"))
MANAGER_ID = int(os.getenv("P1_E2E_MANAGER_ID", str(WORKSPACE_ID)))


def auth_headers(workspace_id: int, manager_id: int) -> dict[str, str]:
    token = AccessToken()
    token["user_id"] = manager_id
    token["role"] = "manager"
    token["workspace_id"] = workspace_id
    token["email"] = f"p1r-sqlite-{workspace_id}@example.invalid"
    token["name"] = "P1-R SQLite"
    token["is_verified"] = True
    return {"Authorization": f"Bearer {token}"}


def response_data(response: requests.Response, expected=(200,)) -> dict:
    if response.status_code not in expected:
        raise AssertionError(f"HTTP {response.status_code}: {response.text[:500]}")
    payload = response.json()
    if not payload.get("success"):
        raise AssertionError(json.dumps(payload, sort_keys=True)[:500])
    return payload.get("data", payload)


def assert_safe_failure(response: requests.Response, label: str, forbidden: str = "") -> str:
    if response.status_code < 400:
        raise AssertionError(f"{label} unexpectedly succeeded")
    payload = response.json()
    if payload.get("success"):
        raise AssertionError(f"{label} returned a successful envelope")
    rendered = json.dumps(payload).lower()
    if "traceback" in rendered or "private key" in rendered:
        raise AssertionError(f"{label} disclosed unsafe diagnostics")
    if forbidden and forbidden.lower() in rendered:
        raise AssertionError(f"{label} reflected an opaque source token")
    return str((payload.get("error") or {}).get("code") or response.status_code)


def main() -> None:
    headers = auth_headers(WORKSPACE_ID, MANAGER_ID)
    other_headers = auth_headers(WORKSPACE_ID + 1, MANAGER_ID + 1)
    dataset_created = False
    dataset_id = None
    sqlite_token = ""
    fd, sqlite_name = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    sqlite_path = Path(sqlite_name)

    try:
        source = sqlite3.connect(sqlite_path)
        source.execute(
            'CREATE TABLE "Sales Data" ('
            '"Order ID" INTEGER PRIMARY KEY, customer TEXT, amount NUMERIC, optional TEXT)'
        )
        source.executemany(
            'INSERT INTO "Sales Data" VALUES (?, ?, ?, ?)',
            [
                (1, "Damascus – مرحبا", "12.3400", None),
                (2, "Zoë", "0.0100", "present"),
                (3, "東京 😊", "999999.9900", None),
            ],
        )
        source.execute('CREATE TABLE empty_table (id INTEGER PRIMARY KEY, note TEXT)')
        source.execute('CREATE TABLE large_events (id INTEGER PRIMARY KEY, payload TEXT)')
        source.executemany(
            'INSERT INTO large_events VALUES (?, ?)',
            ((index, f"event-{index}") for index in range(1, 2501)),
        )
        source.commit()
        source.close()

        source_bytes = sqlite_path.read_bytes()
        fake_extension = requests.post(
            f"{BASE_URL}/database/sources/sqlite/prepare/",
            headers=headers,
            files={"file": ("source.csv", io.BytesIO(source_bytes), "text/csv")},
            timeout=30,
        )
        invalid_header = requests.post(
            f"{BASE_URL}/database/sources/sqlite/prepare/",
            headers=headers,
            files={"file": ("fake.sqlite", io.BytesIO(b"not a sqlite database"), "application/vnd.sqlite3")},
            timeout=30,
        )
        failures = {
            "fake_extension": assert_safe_failure(fake_extension, "fake extension"),
            "invalid_header": assert_safe_failure(invalid_header, "invalid header"),
        }

        with sqlite_path.open("rb") as uploaded:
            prepared = response_data(requests.post(
                f"{BASE_URL}/database/sources/sqlite/prepare/",
                headers=headers,
                files={"file": ("acceptance.sqlite3", uploaded, "application/vnd.sqlite3")},
                timeout=40,
            ))
        sqlite_token = prepared["sqlite_token"]
        configuration = {"sqlite_token": sqlite_token}

        for label, bad_headers, token in (
            ("wrong_workspace", other_headers, sqlite_token),
            ("path_traversal", headers, "../../etc/passwd"),
            ("absolute_path", headers, "C:\\Windows\\system32\\config"),
        ):
            response = requests.post(
                f"{BASE_URL}/database/sources/test/",
                headers=bad_headers,
                json={"engine": "sqlite", "configuration": {"sqlite_token": token}},
                timeout=30,
            )
            failures[label] = assert_safe_failure(response, label, sqlite_token)

        capabilities = response_data(requests.get(
            f"{BASE_URL}/database/sources/capabilities/", headers=headers, timeout=20
        ))
        if "sqlite" not in {item["id"] for item in capabilities["connectors"]}:
            raise AssertionError("SQLite missing from public capabilities")

        tested = response_data(requests.post(
            f"{BASE_URL}/database/sources/test/",
            headers=headers,
            json={"engine": "sqlite", "configuration": configuration},
            timeout=30,
        ))
        discovered = response_data(requests.post(
            f"{BASE_URL}/database/sources/discover/",
            headers=headers,
            json={"engine": "sqlite", "configuration": configuration},
            timeout=30,
        ))
        expected = {"Sales Data": 3, "empty_table": 0, "large_events": 2500}
        selected = []
        primary_keys = {}
        for table_name in expected:
            table = next(item for item in discovered["tables"] if item["name"] == table_name)
            selected.append({"schema": table.get("schema"), "name": table_name})
            inspected = response_data(requests.post(
                f"{BASE_URL}/database/sources/discover/",
                headers=headers,
                json={
                    "engine": "sqlite",
                    "configuration": configuration,
                    "table": table_name,
                },
                timeout=30,
            ))["table"]
            if not inspected["columns"] or not inspected["primary_key"]:
                raise AssertionError(f"SQLite inspection failed for {table_name}")
            primary_keys[table_name] = inspected["primary_key"]

        started = response_data(requests.post(
            f"{BASE_URL}/database/sources/snapshot/",
            headers=headers,
            json={
                "engine": "sqlite",
                "configuration": configuration,
                "tables": selected,
                "chunk_size": 1000,
            },
            timeout=45,
        ), expected=(202,))
        dataset_created = True
        dataset_id = int(started["id"])

        detail = None
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            response = requests.get(
                f"{BASE_URL}/database/",
                headers=headers,
                params={"dataset_id": dataset_id},
                timeout=25,
            )
            if response.status_code == 200:
                candidate = response_data(response)
                if candidate.get("etl_status") == "failed":
                    raise AssertionError(f"SQLite dataset failed: {candidate.get('etl_message')}")
                if candidate.get("etl_status") == "completed":
                    detail = candidate
                    break
            elif response.status_code not in (202, 409):
                raise AssertionError(f"poll failed HTTP {response.status_code}: {response.text[:300]}")
            time.sleep(2)
        if detail is None:
            raise AssertionError("SQLite dataset did not complete within 120 seconds")
        if detail["row_count"] != sum(expected.values()):
            raise AssertionError(f"SQLite aggregate row mismatch: {detail['row_count']}")

        imported = detail.get("source_tables") or []
        if len(imported) != len(expected):
            raise AssertionError(f"expected three SQLite tables, got {len(imported)}")
        table_results = {}
        unicode_values = set()
        null_count = 0
        for table_name, expected_rows in expected.items():
            imported_table = next(item for item in imported if item["name"] == table_name)
            if imported_table["row_count"] != expected_rows:
                raise AssertionError(f"SQLite table count mismatch: {imported_table}")
            table_id = imported_table["id"]
            schema = response_data(requests.get(
                f"{BASE_URL}/database/schema/",
                headers=headers,
                params={"table": table_id},
                timeout=25,
            ))
            preview = response_data(requests.get(
                f"{BASE_URL}/database/preview/",
                headers=headers,
                params={"table": table_id},
                timeout=25,
            ))
            if preview["total_rows"] != expected_rows:
                raise AssertionError(f"SQLite preview total mismatch for {table_name}")
            if schema["table"]["id"] != table_id or preview["table"]["id"] != table_id:
                raise AssertionError("SQLite table-aware API identity mismatch")
            if table_name == "Sales Data":
                unicode_values.update(row["customer"] for row in preview["rows"])
                null_count = sum(row["optional"] is None for row in preview["rows"])
            table_results[table_name] = {
                "source_rows": expected_rows,
                "destination_rows": preview["total_rows"],
                "columns": schema["total_columns"],
            }

        required_unicode = {"Damascus – مرحبا", "Zoë", "東京 😊"}
        if not required_unicode.issubset(unicode_values) or null_count != 2:
            raise AssertionError("SQLite Unicode/null integrity check failed")

        database = Database.objects.get(pk=dataset_id, workspace_id=WORKSPACE_ID)
        physical = {item["name"]: item["destination_table"] for item in database.source_tables}
        large_qualified = (
            f"{quote_clickhouse_identifier(database.clickhouse_database)}."
            f"{quote_clickhouse_identifier(physical['large_events'])}"
        )
        integrity = ClickHouseClient().execute_query(
            f"SELECT count() AS rows, uniqExact(id) AS unique_ids FROM {large_qualified} FORMAT JSONEachRow"
        )
        if not integrity["success"]:
            raise AssertionError("SQLite destination integrity query failed")
        integrity_row = json.loads(integrity["data"])
        if int(integrity_row["rows"]) != 2500 or int(integrity_row["unique_ids"]) != 2500:
            raise AssertionError(f"SQLite large-table integrity mismatch: {integrity_row}")

        print(json.dumps({
            "engine": "sqlite",
            "public_gateway": True,
            "test_connection": tested["code"],
            "dataset_id": dataset_id,
            "dataset_status": detail["etl_status"],
            "aggregate_rows": detail["row_count"],
            "tables": table_results,
            "primary_keys": primary_keys,
            "large_events_unique_ids": int(integrity_row["unique_ids"]),
            "unicode_values": sorted(unicode_values),
            "preview_nulls": null_count,
            "failure_tests": failures,
            "multi_table": True,
            "schema_api": True,
            "preview_api": True,
        }, ensure_ascii=False, sort_keys=True))
    finally:
        if dataset_created:
            try:
                requests.delete(f"{BASE_URL}/database/", headers=headers, timeout=45)
            except requests.RequestException:
                pass
        sqlite_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
