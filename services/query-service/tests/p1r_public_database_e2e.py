"""P1-R public gateway-to-ClickHouse acceptance for one live database engine.

Run inside query-service. Configuration is supplied only through environment
variables; secrets are never printed. The script creates no source data and
always deletes the BIAVORA dataset it creates.
"""
from __future__ import annotations

import json
import os
import sys
import time
import base64
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
PUBLIC_HOST_HEADER = os.getenv("P1_PUBLIC_API_HOST_HEADER", "").strip()
ENGINE = os.environ["P1R_ENGINE"]
CONFIGURATION = json.loads(
    base64.b64decode(os.environ["P1R_CONFIGURATION_B64"]).decode("utf-8")
    if os.getenv("P1R_CONFIGURATION_B64")
    else os.environ["P1R_CONFIGURATION"]
)
SCHEMA = os.getenv("P1R_SCHEMA") or None
EXPECTED = json.loads(os.getenv(
    "P1R_EXPECTED",
    '{"customers":8,"empty_table":0,"large_events":2500,"Sales Data":4}',
))
WORKSPACE_ID = int(os.getenv("P1R_WORKSPACE_ID", "99101"))
MANAGER_ID = int(os.getenv("P1R_MANAGER_ID", str(WORKSPACE_ID)))


def data(response: requests.Response, expected=(200,)) -> dict:
    if response.status_code not in expected:
        raise AssertionError(f"HTTP {response.status_code}: {response.text[:500]}")
    payload = response.json()
    if not payload.get("success"):
        raise AssertionError(json.dumps(payload, sort_keys=True)[:500])
    return payload.get("data", payload)


def post(headers, suffix, payload, expected=(200,), timeout=45):
    return data(
        requests.post(f"{BASE_URL}{suffix}", headers=headers, json=payload, timeout=timeout),
        expected=expected,
    )


def failure_case(headers, label, configuration, allowed_codes):
    response = requests.post(
        f"{BASE_URL}/database/sources/test/",
        headers=headers,
        json={"engine": ENGINE, "configuration": configuration},
        timeout=45,
    )
    payload = response.json()
    if payload.get("success"):
        raise AssertionError(f"{label} unexpectedly succeeded")
    error = payload.get("error") or {}
    code = error.get("code")
    if code not in allowed_codes:
        raise AssertionError(f"{label} returned {code}: {json.dumps(payload)[:300]}")
    rendered = json.dumps(payload).lower()
    secret = str(CONFIGURATION.get("password") or "").lower()
    forbidden = ["traceback", "password=", "private key"]
    if secret and secret in rendered:
        raise AssertionError(f"{label} disclosed a credential")
    if any(value in rendered for value in forbidden):
        raise AssertionError(f"{label} disclosed unsafe diagnostics")
    return code


def main():
    token = AccessToken()
    token["user_id"] = MANAGER_ID
    token["role"] = "manager"
    token["workspace_id"] = WORKSPACE_ID
    token["email"] = f"p1r-{ENGINE}@example.invalid"
    token["name"] = f"P1R {ENGINE}"
    token["is_verified"] = True
    headers = {"Authorization": f"Bearer {token}"}
    if PUBLIC_HOST_HEADER:
        headers["Host"] = PUBLIC_HOST_HEADER
    dataset_id = None
    result = {"engine": ENGINE, "public_gateway": True, "failures": {}}

    try:
        capabilities = data(requests.get(
            f"{BASE_URL}/database/sources/capabilities/", headers=headers, timeout=20
        ))
        connector = next(item for item in capabilities["connectors"] if item["id"] == ENGINE)
        connector_caps = connector.get("capabilities") or {}
        if connector_caps.get("cdc") is not False or connector_caps.get("snapshot_extraction") is not True:
            raise AssertionError("capability contract is not snapshot-only")

        tested = post(headers, "/database/sources/test/", {
            "engine": ENGINE, "configuration": CONFIGURATION,
        })
        result["connection"] = tested["code"]

        if CONFIGURATION.get("password"):
            wrong = {**CONFIGURATION, "password": "definitely-wrong-p1r-password"}
            result["failures"]["wrong_password"] = failure_case(
                headers, "wrong password", wrong,
                {"AUTHENTICATION_FAILED", "CONNECTION_FAILED", "TLS_ERROR"},
            )
        invalid_db = dict(CONFIGURATION)
        db_key = "service_name" if ENGINE == "oracle" else "database"
        invalid_db[db_key] = "p1r_missing_database"
        result["failures"]["invalid_database"] = failure_case(
            headers, "invalid database", invalid_db,
            {"DATABASE_NOT_FOUND", "PERMISSION_DENIED", "AUTHENTICATION_FAILED", "CONNECTION_FAILED", "TLS_ERROR"},
        )
        wrong_port = {**CONFIGURATION, "port": int(CONFIGURATION["port"]) + 37, "connect_timeout": 2}
        result["failures"]["wrong_port"] = failure_case(
            headers, "wrong port", wrong_port,
            {"CONNECTION_REFUSED", "CONNECTION_TIMEOUT", "CONNECTION_FAILED", "TLS_ERROR"},
        )
        blocked = {**CONFIGURATION, "host": "127.0.0.1", "connect_timeout": 2}
        result["failures"]["blocked_host"] = failure_case(
            headers, "blocked host", blocked, {"DESTINATION_NOT_ALLOWED"},
        )

        discovered = post(headers, "/database/sources/discover/", {
            "engine": ENGINE, "configuration": CONFIGURATION, "schema": SCHEMA,
        })
        available = discovered["tables"]
        selected = []
        inspections = {}
        for expected_name in EXPECTED:
            table = next(item for item in available if item["name"].lower() == expected_name.lower())
            selected.append({"schema": table.get("schema"), "name": table["name"]})
            inspected = post(headers, "/database/sources/discover/", {
                "engine": ENGINE,
                "configuration": CONFIGURATION,
                "schema": table.get("schema"),
                "table": table["name"],
            })["table"]
            if not inspected.get("columns") or not inspected.get("primary_key"):
                raise AssertionError(f"column/primary-key discovery failed for {table['name']}")
            inspections[expected_name] = {
                "columns": len(inspected["columns"]),
                "primary_key": inspected["primary_key"],
            }
        result["discovery"] = inspections

        started = post(headers, "/database/sources/snapshot/", {
            "engine": ENGINE,
            "configuration": CONFIGURATION,
            "tables": selected,
            "chunk_size": 1000,
        }, expected=(202,), timeout=60)
        dataset_id = int(started["id"])

        detail = None
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            response = requests.get(
                f"{BASE_URL}/database/", headers=headers,
                params={"dataset_id": dataset_id}, timeout=25,
            )
            if response.status_code == 200:
                candidate = data(response)
                if candidate.get("etl_status") == "failed":
                    raise AssertionError(f"dataset failed: {candidate.get('etl_message')}")
                if candidate.get("etl_status") == "completed":
                    detail = candidate
                    break
            elif response.status_code not in (202, 409):
                raise AssertionError(f"poll failed HTTP {response.status_code}: {response.text[:300]}")
            time.sleep(2)
        if detail is None:
            raise AssertionError("dataset did not complete within 150 seconds")

        imported = detail.get("source_tables") or []
        if len(imported) != len(EXPECTED):
            raise AssertionError(f"expected {len(EXPECTED)} imported tables, got {len(imported)}")
        expected_total = sum(EXPECTED.values())
        if detail.get("row_count") != expected_total:
            raise AssertionError(f"aggregate row count mismatch: {detail.get('row_count')} != {expected_total}")

        table_results = {}
        unicode_values = set()
        for source_name, expected_count in EXPECTED.items():
            imported_table = next(item for item in imported if item["name"].lower() == source_name.lower())
            if imported_table.get("row_count") != expected_count:
                raise AssertionError(f"{source_name} row count mismatch: {imported_table}")
            table_id = imported_table["id"]
            schema_payload = data(requests.get(
                f"{BASE_URL}/database/schema/", headers=headers,
                params={"table": table_id}, timeout=25,
            ))
            preview = data(requests.get(
                f"{BASE_URL}/database/preview/", headers=headers,
                params={"table": table_id}, timeout=25,
            ))
            if preview["total_rows"] != expected_count:
                raise AssertionError(f"{source_name} preview total mismatch")
            if schema_payload["table"]["id"] != table_id or preview["table"]["id"] != table_id:
                raise AssertionError("table-aware schema/preview identity mismatch")
            for row in preview["rows"]:
                value = row.get("customer_name")
                if value:
                    unicode_values.add(value)
            table_results[source_name] = {
                "source_rows": expected_count,
                "destination_rows": preview["total_rows"],
                "columns": schema_payload["total_columns"],
                "preview_rows": len(preview["rows"]),
            }

        database = Database.objects.get(pk=dataset_id, workspace_id=WORKSPACE_ID)
        physical = {item["name"].lower(): item["destination_table"] for item in database.source_tables}
        clickhouse = ClickHouseClient()
        customer_table = physical["customers"]
        customer_qualified = (
            f"{quote_clickhouse_identifier(database.clickhouse_database)}."
            f"{quote_clickhouse_identifier(customer_table)}"
        )
        customer_result = clickhouse.execute_query(
            f"SELECT customer_name FROM {customer_qualified} FORMAT JSONEachRow"
        )
        if not customer_result["success"]:
            raise AssertionError("destination Unicode integrity query failed")
        unicode_values.update(
            json.loads(line)["customer_name"]
            for line in customer_result["data"].splitlines()
            if line.strip()
        )
        large_table = physical["large_events"]
        qualified = (
            f"{quote_clickhouse_identifier(database.clickhouse_database)}."
            f"{quote_clickhouse_identifier(large_table)}"
        )
        integrity = clickhouse.execute_query(
            f"SELECT count() AS rows, uniqExact(id) AS unique_ids FROM {qualified} FORMAT JSONEachRow"
        )
        if not integrity["success"]:
            raise AssertionError("destination integrity query failed")
        integrity_row = json.loads(integrity["data"])
        if int(integrity_row["rows"]) != 2500 or int(integrity_row["unique_ids"]) != 2500:
            raise AssertionError(f"large table integrity mismatch: {integrity_row}")

        required_unicode = {"Damascus – مرحبا", "東京", "Zoë", "Renée 😊"}
        if not required_unicode.issubset(unicode_values):
            raise AssertionError(f"Unicode values missing: {required_unicode - unicode_values}")

        result.update({
            "dataset_status": detail["etl_status"],
            "dataset_id": dataset_id,
            "aggregate_rows": detail["row_count"],
            "tables": table_results,
            "large_events_unique_ids": int(integrity_row["unique_ids"]),
            "unicode_values": sorted(unicode_values),
            "multi_table": True,
            "schema_api": True,
            "preview_api": True,
        })
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    finally:
        if dataset_id is not None:
            requests.delete(f"{BASE_URL}/database/", headers=headers, timeout=45)


if __name__ == "__main__":
    main()
