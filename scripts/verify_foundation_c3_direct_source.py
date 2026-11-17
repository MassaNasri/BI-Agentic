"""Disposable PostgreSQL source check for DirectTransport and read-only discovery.

Requires BIAVORA_C3_DISPOSABLE=1 and a disposable local PostgreSQL container.
No credential is embedded or printed by this script.
"""

import os
import sys

if os.getenv("BIAVORA_C3_DISPOSABLE") != "1":
    raise SystemExit("Set BIAVORA_C3_DISPOSABLE=1 for a disposable source only.")

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "etl-final"))

import psycopg2
from psycopg2 import sql
from shared.connectors import connector_registry

host = os.getenv("BIAVORA_C3_SOURCE_HOST", "127.0.0.1")
port = int(os.getenv("BIAVORA_C3_SOURCE_PORT", "5439"))
database = os.environ["BIAVORA_C3_SOURCE_DATABASE"]
admin_password = os.environ["BIAVORA_C3_SOURCE_ADMIN_PASSWORD"]
reader_password = os.environ["BIAVORA_C3_SOURCE_READER_PASSWORD"]

with psycopg2.connect(host=host, port=port, dbname=database, user="postgres", password=admin_password) as admin:
    with admin.cursor() as cursor:
        cursor.execute("CREATE TABLE IF NOT EXISTS c3_orders (id integer PRIMARY KEY, amount integer NOT NULL)")
        cursor.execute("TRUNCATE c3_orders")
        cursor.execute("INSERT INTO c3_orders VALUES (1, 10), (2, 20)")
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = 'c3_reader'")
        if not cursor.fetchone():
            cursor.execute(sql.SQL("CREATE ROLE c3_reader LOGIN PASSWORD {}").format(sql.Literal(reader_password)))
        cursor.execute("GRANT USAGE ON SCHEMA public TO c3_reader")
        cursor.execute("GRANT SELECT ON c3_orders TO c3_reader")

config = {
    "host": host, "port": port, "database": database, "username": "c3_reader",
    # The stock disposable image has SSL disabled. Production rejects this mode.
    "password": reader_password, "sslmode": os.getenv("BIAVORA_C3_SOURCE_SSLMODE", "disable"), "connect_timeout": 5,
}
connector = connector_registry.get("postgres")
assert connector.test_connection(config)["success"] is True
discovery = connector.discover(config, schema="public", table="c3_orders")
assert any(item["name"] == "c3_orders" for item in discovery["tables"])
assert discovery["table"]["primary_key"] == ["id"]
connection = connector.connect(connector.validate_configuration(config))
try:
    rows = [row for batch in connector.iter_rows(connection, "public", "c3_orders", chunk_size=1, order_by="id") for row in batch]
    assert [(row["id"], row["amount"]) for row in rows] == [(1, 10), (2, 20)]
    with connection.cursor() as cursor:
        try:
            cursor.execute("INSERT INTO c3_orders VALUES (3, 30)")
        except psycopg2.errors.InsufficientPrivilege:
            connection.rollback()
        else:
            raise AssertionError("Reader unexpectedly has write permission.")
finally:
    connection.close()

print("Direct PostgreSQL test/discovery/2-row snapshot and denied write: PASS")
