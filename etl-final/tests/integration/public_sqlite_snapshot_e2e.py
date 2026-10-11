"""Authenticated public-API smoke for the complete SQLite snapshot path.

Run inside query-service in the Compose stack.  The script mints a short-lived
test token using that service's configured signing key, enters through the API
gateway, and cleans up the query-service/ClickHouse dataset in ``finally``.
No token or secret is printed.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time

import django
import requests


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "service_config.settings")
django.setup()

from rest_framework_simplejwt.tokens import AccessToken  # noqa: E402


BASE_URL = os.getenv("P1_PUBLIC_API_URL", "http://api-gateway:8000").rstrip("/")
WORKSPACE_ID = int(os.getenv("P1_E2E_WORKSPACE_ID", "99992"))
MANAGER_ID = int(os.getenv("P1_E2E_MANAGER_ID", "99992"))


def response_data(response: requests.Response, expected=(200,)) -> dict:
    if response.status_code not in expected:
        raise AssertionError(f"HTTP {response.status_code}: {response.text[:600]}")
    payload = response.json()
    if not payload.get("success"):
        raise AssertionError(json.dumps(payload, sort_keys=True))
    return payload.get("data", payload)


def main() -> None:
    token = AccessToken()
    token["user_id"] = MANAGER_ID
    token["role"] = "manager"
    token["workspace_id"] = WORKSPACE_ID
    token["email"] = "p1-e2e@example.invalid"
    token["name"] = "P1 E2E"
    token["is_verified"] = True
    headers = {"Authorization": f"Bearer {token}"}

    dataset_created = False
    sqlite_token = None
    with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as handle:
        sqlite_path = handle.name
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
                (3, "東京", "999999.9900", None),
            ],
        )
        source.commit()
        source.close()

        capabilities = response_data(
            requests.get(f"{BASE_URL}/database/sources/capabilities/", headers=headers, timeout=20)
        )
        connector_ids = [item["id"] for item in capabilities["connectors"]]

        with open(sqlite_path, "rb") as uploaded:
            prepared = response_data(
                requests.post(
                    f"{BASE_URL}/database/sources/sqlite/prepare/",
                    headers=headers,
                    files={"file": ("sales.sqlite3", uploaded, "application/vnd.sqlite3")},
                    timeout=40,
                )
            )
        sqlite_token = prepared["sqlite_token"]
        configuration = {"sqlite_token": sqlite_token}

        tested = response_data(
            requests.post(
                f"{BASE_URL}/database/sources/test/",
                headers=headers,
                json={"engine": "sqlite", "configuration": configuration},
                timeout=30,
            )
        )
        discovered = response_data(
            requests.post(
                f"{BASE_URL}/database/sources/discover/",
                headers=headers,
                json={"engine": "sqlite", "configuration": configuration},
                timeout=30,
            )
        )
        selected = next(item for item in discovered["tables"] if item["name"] == "Sales Data")
        started = response_data(
            requests.post(
                f"{BASE_URL}/database/sources/snapshot/",
                headers=headers,
                json={
                    "engine": "sqlite",
                    "configuration": configuration,
                    "tables": [{"schema": selected.get("schema"), "name": selected["name"]}],
                    "chunk_size": 100,
                },
                timeout=40,
            ),
            expected=(202,),
        )
        dataset_created = True
        dataset_id = started["id"]

        detail = None
        time.sleep(2)
        for _ in range(30):
            response = requests.get(
                f"{BASE_URL}/database/",
                headers=headers,
                params={"dataset_id": dataset_id},
                timeout=20,
            )
            if response.status_code == 200:
                candidate = response_data(response)
                if candidate.get("etl_status") == "completed":
                    detail = candidate
                    break
            elif response.status_code not in (202, 409):
                raise AssertionError(f"Polling failed HTTP {response.status_code}: {response.text[:600]}")
            time.sleep(1)
        if detail is None:
            raise AssertionError("Dataset did not reach completed state within 32 seconds")
        if detail["row_count"] != 3 or detail["column_count"] < 4:
            raise AssertionError(f"Unexpected dataset metadata: {detail}")

        preview = response_data(
            requests.get(f"{BASE_URL}/database/preview/", headers=headers, timeout=20)
        )
        customers = sorted(row["customer"] for row in preview["rows"])
        null_count = sum(row["optional"] is None for row in preview["rows"])
        if len(preview["rows"]) != 3 or null_count != 2:
            raise AssertionError(f"Unexpected preview: {preview}")

        print(json.dumps({
            "public_gateway": True,
            "connector_count": len(connector_ids),
            "test_connection": tested["code"],
            "discovered_table": selected["name"],
            "dataset_status": detail["etl_status"],
            "schema_columns": detail["column_count"],
            "preview_rows": len(preview["rows"]),
            "preview_nulls": null_count,
            "unicode_values": customers,
        }, ensure_ascii=False, sort_keys=True))
    finally:
        if dataset_created:
            try:
                requests.delete(f"{BASE_URL}/database/", headers=headers, timeout=30)
            except requests.RequestException:
                pass
        try:
            os.unlink(sqlite_path)
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    main()
