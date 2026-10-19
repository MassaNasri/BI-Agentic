"""Production-oriented, one-time database snapshot connectors.

The registry is deliberately driver-lazy: capability discovery works even when an
optional engine driver is unavailable, while connection attempts return the stable
``DRIVER_UNAVAILABLE`` error code.  No method logs credentials or builds a
credential-bearing URL.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import base64
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
import os
import re
import socket
import time as wall_time
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence
from uuid import UUID

from shared.security.destination_policy import DestinationPolicyError, validate_destination
from shared.utils.db_type_utils import normalize_db_type


class ConnectorError(RuntimeError):
    """Safe, application-level connector failure."""

    def __init__(self, code: str, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message}


def normalize_snapshot_value(value: Any) -> Any:
    """Convert driver values to loss-aware, deterministic Kafka JSON values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "base64:" + base64.b64encode(bytes(value)).decode("ascii")
    if isinstance(value, Enum):
        return normalize_snapshot_value(value.value)
    if isinstance(value, Mapping):
        return {str(key): normalize_snapshot_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [normalize_snapshot_value(item) for item in value]
    return str(value)


def normalize_snapshot_row(row: Mapping[str, Any]) -> dict:
    return {str(key): normalize_snapshot_value(value) for key, value in row.items()}


def safe_connector_error(exc: Exception) -> ConnectorError:
    """Map driver failures without reflecting DSNs, credentials, or tracebacks."""

    if isinstance(exc, ConnectorError):
        return exc
    if isinstance(exc, DestinationPolicyError):
        if "could not be resolved" in str(exc).lower() or "resolved to no addresses" in str(exc).lower():
            return ConnectorError(
                "DNS_RESOLUTION_FAILED", "The database host could not be resolved.", status_code=502
            )
        return ConnectorError("DESTINATION_NOT_ALLOWED", str(exc))
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return ConnectorError("CONNECTION_TIMEOUT", "The database connection timed out.", status_code=504)
    driver_code = None
    if getattr(exc, "args", None):
        driver_code = exc.args[0]
    if driver_code in (1045, 18456):
        return ConnectorError("AUTHENTICATION_FAILED", "Database authentication failed.", status_code=401)
    if driver_code in (1044, 1142):
        return ConnectorError("PERMISSION_DENIED", "The database user lacks the required permission.", status_code=403)
    if driver_code in (1049,):
        return ConnectorError("DATABASE_NOT_FOUND", "The requested database or service was not found.", status_code=404)
    lowered = str(exc).lower()
    if any(token in lowered for token in (
        "connection refused", "actively refused", "errno 111", "winerror 10061", "ora-12541",
    )):
        return ConnectorError("CONNECTION_REFUSED", "The database endpoint refused the connection.", status_code=502)
    if any(token in lowered for token in (
        "name or service not known", "nodename nor servname", "temporary failure in name resolution",
        "getaddrinfo failed", "unknown host", "ora-12545",
    )):
        return ConnectorError("DNS_RESOLUTION_FAILED", "The database host could not be resolved.", status_code=502)
    if any(token in lowered for token in ("password", "authentication", "login failed", "ora-01017", "28p01")):
        return ConnectorError("AUTHENTICATION_FAILED", "Database authentication failed.", status_code=401)
    if any(token in lowered for token in ("certificate", "ssl", "tls")):
        return ConnectorError("TLS_ERROR", "The secure database connection could not be established.")
    if any(token in lowered for token in ("permission", "not authorized", "access denied")):
        return ConnectorError("PERMISSION_DENIED", "The database user lacks the required permission.", status_code=403)
    if any(token in lowered for token in ("unknown database", "does not exist", "ora-12514")):
        return ConnectorError("DATABASE_NOT_FOUND", "The requested database or service was not found.", status_code=404)
    return ConnectorError("CONNECTION_FAILED", "The database operation failed.", status_code=502)


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    kind: str = "text"
    required: bool = True
    default: Any = None
    options: Sequence[str] = ()

    def as_dict(self) -> dict:
        result = {
            "name": self.name,
            "label": self.label,
            "type": self.kind,
            "required": self.required,
        }
        if self.default is not None:
            result["default"] = self.default
        if self.options:
            result["options"] = list(self.options)
        return result


SERVER_FIELDS = (
    Field("host", "Host"),
    Field("port", "Port", "number"),
    Field("database", "Database"),
    Field("username", "Username"),
    Field("password", "Password", "password"),
    Field("connect_timeout", "Connection timeout (seconds)", "number", False, 10),
)


class BaseDatabaseConnector:
    key = "base"
    label = "Database"
    default_port: Optional[int] = None
    driver = ""
    server_based = True
    supports_schemas = True
    placeholder = "%s"
    fields: Sequence[Field] = SERVER_FIELDS

    def capabilities(self) -> dict:
        fields = []
        for field in self.fields:
            value = field
            if field.name == "port" and field.default is None and self.default_port is not None:
                value = Field(field.name, field.label, field.kind, field.required, self.default_port, field.options)
            fields.append(value.as_dict())
        return {
            "id": self.key,
            "label": self.label,
            "driver": self.driver,
            "workflow": "server" if self.server_based else "file_upload",
            "fields": fields,
            "capabilities": {
                "test_connection": True,
                "schema_discovery": self.supports_schemas,
                "table_discovery": True,
                "column_introspection": True,
                "primary_key_discovery": True,
                "snapshot_extraction": True,
                "chunked_extraction": True,
                "tls": self.server_based,
                "cdc": False,
            },
        }

    def validate_configuration(self, raw: Mapping[str, Any]) -> dict:
        cfg = dict(raw or {})
        cfg["db_type"] = self.key
        if "username" not in cfg and "user" in cfg:
            cfg["username"] = cfg.get("user")
        if self.server_based:
            for name in ("host", "database", "username"):
                if not str(cfg.get(name, "")).strip():
                    raise ConnectorError("INVALID_CONFIGURATION", f"{name} is required.")
            if "password" not in cfg:
                raise ConnectorError("INVALID_CONFIGURATION", "password is required.")
            try:
                cfg["port"] = int(cfg.get("port") or self.default_port)
                if not 1 <= cfg["port"] <= 65535:
                    raise ValueError
                cfg["connect_timeout"] = max(1, min(int(cfg.get("connect_timeout", 10)), 120))
                cfg["read_timeout"] = max(1, min(int(cfg.get("read_timeout", 60)), 3600))
            except (TypeError, ValueError):
                raise ConnectorError("INVALID_CONFIGURATION", "port and timeout values must be valid integers.")
            resolved = validate_destination(str(cfg["host"]).strip(), cfg["port"])
            cfg["resolved_host"] = resolved[0]
        return cfg

    def connect(self, config: Mapping[str, Any]):
        raise NotImplementedError

    def close(self, connection) -> None:
        if connection is not None:
            connection.close()

    def test_connection(self, config: Mapping[str, Any]) -> dict:
        connection = None
        try:
            connection = self.connect(self.validate_configuration(config))
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            return {"success": True, "code": "CONNECTION_OK", "message": "Connection successful."}
        except Exception as exc:
            raise safe_connector_error(exc) from exc
        finally:
            self.close(connection)

    def quote_identifier(self, identifier: str) -> str:
        value = str(identifier or "")
        if not value or "\x00" in value:
            raise ConnectorError("INVALID_CONFIGURATION", "Identifier cannot be empty.")
        return '"' + value.replace('"', '""') + '"'

    def qualified_table(self, schema: Optional[str], table: str) -> str:
        pieces = [self.quote_identifier(part) for part in (schema, table) if part]
        if not pieces:
            raise ConnectorError("TABLE_NOT_FOUND", "A table is required.")
        return ".".join(pieces)

    @staticmethod
    def _rows(cursor) -> List[dict]:
        values = cursor.fetchall()
        columns = [str(item[0]) for item in (cursor.description or [])]
        result = []
        for value in values:
            if isinstance(value, dict):
                result.append(dict(value))
            elif hasattr(value, "keys"):
                result.append({key: value[key] for key in value.keys()})
            else:
                result.append(dict(zip(columns, value)))
        return result

    def list_schemas(self, connection) -> List[str]:
        return []

    def list_tables(self, connection, schema: Optional[str] = None) -> List[dict]:
        raise NotImplementedError

    def inspect_table(self, connection, schema: Optional[str], table: str) -> dict:
        raise NotImplementedError

    def discover(self, config: Mapping[str, Any], *, schema: Optional[str] = None, table: Optional[str] = None) -> dict:
        connection = None
        try:
            cfg = self.validate_configuration(config)
            connection = self.connect(cfg)
            result = {"schemas": self.list_schemas(connection), "tables": self.list_tables(connection, schema)}
            if table:
                result["table"] = self.inspect_table(connection, schema, table)
            return result
        except Exception as exc:
            raise safe_connector_error(exc) from exc
        finally:
            self.close(connection)

    def build_snapshot_query(
        self,
        schema: Optional[str],
        table: str,
        *,
        columns: Optional[Sequence[str]] = None,
        order_by: Optional[str] = None,
        offset: int = 0,
        limit: int = 1000,
        last_pk: Any = None,
    ) -> tuple[str, tuple]:
        projection = ", ".join(self.quote_identifier(col) for col in columns) if columns else "*"
        query = f"SELECT {projection} FROM {self.qualified_table(schema, table)}"
        params: List[Any] = []
        if order_by and last_pk is not None:
            query += f" WHERE {self.quote_identifier(order_by)} > {self.placeholder}"
            params.append(last_pk)
        if order_by:
            query += f" ORDER BY {self.quote_identifier(order_by)}"
        query += f" LIMIT {int(limit)}"
        if last_pk is None:
            query += f" OFFSET {int(offset)}"
        return query, tuple(params)

    def iter_rows(
        self,
        connection,
        schema: Optional[str],
        table: str,
        *,
        chunk_size: int = 1000,
        order_by: Optional[str] = None,
    ) -> Iterator[List[dict]]:
        offset = 0
        last_pk = None
        while True:
            query, params = self.build_snapshot_query(
                schema, table, order_by=order_by, offset=offset, limit=chunk_size, last_pk=last_pk
            )
            cursor = connection.cursor()
            cursor.execute(query, params) if params else cursor.execute(query)
            rows = self._rows(cursor)
            if not rows:
                break
            yield rows
            if order_by:
                last_pk = rows[-1].get(order_by)
            else:
                offset += len(rows)
            if len(rows) < chunk_size:
                break


class InformationSchemaConnector(BaseDatabaseConnector):
    """Shared metadata implementation for PostgreSQL/MySQL/MariaDB."""

    excluded_schemas: Sequence[str] = ()

    @staticmethod
    def _information_schema_row(row: Mapping[str, Any]) -> dict:
        """Case-fold driver-specific INFORMATION_SCHEMA result labels."""
        return {str(key).lower(): value for key, value in row.items()}

    def list_schemas(self, connection) -> List[str]:
        cursor = connection.cursor()
        cursor.execute("SELECT schema_name FROM information_schema.schemata ORDER BY schema_name")
        schemas = []
        for row in cursor.fetchall():
            if isinstance(row, dict):
                row = self._information_schema_row(row)
                schemas.append(str(row.get("schema_name")))
            else:
                schemas.append(str(row[0]))
        return schemas

    def list_tables(self, connection, schema: Optional[str] = None) -> List[dict]:
        cursor = connection.cursor()
        query = (
            "SELECT table_schema, table_name, table_type FROM information_schema.tables "
            "WHERE table_type IN ('BASE TABLE', 'VIEW')"
        )
        params: list = []
        if schema:
            query += f" AND table_schema = {self.placeholder}"
            params.append(schema)
        if self.excluded_schemas:
            marks = ",".join([self.placeholder] * len(self.excluded_schemas))
            query += f" AND table_schema NOT IN ({marks})"
            params.extend(self.excluded_schemas)
        query += " ORDER BY table_schema, table_name"
        cursor.execute(query, tuple(params)) if params else cursor.execute(query)
        rows = [self._information_schema_row(row) for row in self._rows(cursor)]
        return [
            {"schema": row.get("table_schema"), "name": row.get("table_name"), "type": row.get("table_type")}
            for row in rows
        ]

    def inspect_table(self, connection, schema: Optional[str], table: str) -> dict:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT column_name, data_type, is_nullable, ordinal_position "
            f"FROM information_schema.columns WHERE table_schema = {self.placeholder} "
            f"AND table_name = {self.placeholder} ORDER BY ordinal_position",
            (schema or self.default_schema(connection), table),
        )
        columns = [self._information_schema_row(row) for row in self._rows(cursor)]
        cursor.execute(
            "SELECT kcu.column_name FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "ON tc.constraint_name = kcu.constraint_name "
            "AND tc.table_schema = kcu.table_schema AND tc.table_name = kcu.table_name "
            f"WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = {self.placeholder} "
            f"AND tc.table_name = {self.placeholder} ORDER BY kcu.ordinal_position",
            (schema or self.default_schema(connection), table),
        )
        primary_key = [
            self._information_schema_row(row).get("column_name")
            for row in self._rows(cursor)
        ]
        if not columns:
            raise ConnectorError("TABLE_NOT_FOUND", "The requested table was not found.", status_code=404)
        return {"schema": schema or self.default_schema(connection), "name": table, "columns": columns, "primary_key": primary_key}

    def default_schema(self, connection) -> str:
        raise NotImplementedError


class PostgresConnector(InformationSchemaConnector):
    key, label, default_port, driver = "postgres", "PostgreSQL", 5432, "psycopg2"
    excluded_schemas = ("pg_catalog", "information_schema")
    fields = SERVER_FIELDS + (
        Field("schema", "Default schema", required=False, default="public"),
        Field("sslmode", "TLS mode", "select", False, "require", ("disable", "prefer", "require", "verify-ca", "verify-full")),
    )

    def connect(self, config):
        cfg = self.validate_configuration(config) if "resolved_host" not in config else dict(config)
        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor
        except ImportError as exc:
            raise ConnectorError("DRIVER_UNAVAILABLE", "The PostgreSQL driver is unavailable.", status_code=503) from exc
        return psycopg2.connect(
            host=cfg["resolved_host"], port=cfg["port"], dbname=cfg["database"],
            user=cfg["username"], password=cfg.get("password", ""),
            connect_timeout=cfg["connect_timeout"], sslmode=cfg.get("sslmode", "require"),
            cursor_factory=RealDictCursor,
        )

    def default_schema(self, connection):
        return "public"

    def inspect_table(self, connection, schema: Optional[str], table: str) -> dict:
        result = super().inspect_table(connection, schema, table)
        if result["primary_key"]:
            return result

        # PostgreSQL's information_schema only exposes table constraints to the
        # owner (or a role with a non-SELECT privilege). Snapshot credentials are
        # intentionally read-only, so use the public pg_catalog metadata instead.
        cursor = connection.cursor()
        cursor.execute(
            "SELECT attribute.attname AS column_name "
            "FROM pg_catalog.pg_index AS index "
            "JOIN pg_catalog.pg_class AS relation ON relation.oid = index.indrelid "
            "JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace "
            "JOIN unnest(index.indkey) WITH ORDINALITY AS key(attnum, position) ON TRUE "
            "JOIN pg_catalog.pg_attribute AS attribute "
            "ON attribute.attrelid = relation.oid AND attribute.attnum = key.attnum "
            "WHERE index.indisprimary AND namespace.nspname = %s AND relation.relname = %s "
            "ORDER BY key.position",
            (schema or self.default_schema(connection), table),
        )
        result["primary_key"] = [
            self._information_schema_row(row).get("column_name")
            for row in self._rows(cursor)
        ]
        return result


class MySQLConnector(InformationSchemaConnector):
    key, label, default_port, driver = "mysql", "MySQL", 3306, "PyMySQL"
    supports_schemas = False
    excluded_schemas = ("information_schema", "mysql", "performance_schema", "sys")
    fields = SERVER_FIELDS + (
        Field("ssl_mode", "TLS mode", "select", False, "required", ("disabled", "preferred", "required", "verify_ca", "verify_identity")),
        Field("ssl_ca", "CA certificate path", required=False),
    )

    def connect(self, config):
        cfg = self.validate_configuration(config) if "resolved_host" not in config else dict(config)
        try:
            import pymysql
        except ImportError as exc:
            raise ConnectorError("DRIVER_UNAVAILABLE", "The MySQL driver is unavailable.", status_code=503) from exc
        ssl_mode = str(cfg.get("ssl_mode", "required")).lower()
        kwargs = {}
        if ssl_mode != "disabled":
            kwargs["ssl"] = {"ca": cfg.get("ssl_ca")} if cfg.get("ssl_ca") else {}
        return pymysql.connect(
            host=cfg["resolved_host"], port=cfg["port"], database=cfg["database"],
            user=cfg["username"], password=cfg.get("password", ""),
            connect_timeout=cfg["connect_timeout"], read_timeout=cfg["read_timeout"],
            cursorclass=pymysql.cursors.DictCursor, **kwargs,
        )

    def default_schema(self, connection):
        cursor = connection.cursor()
        cursor.execute("SELECT DATABASE() AS name")
        row = cursor.fetchone()
        return row.get("name") if isinstance(row, dict) else row[0]

    def list_schemas(self, connection):
        return []

    def list_tables(self, connection, schema=None):
        return super().list_tables(connection, schema or self.default_schema(connection))

    def inspect_table(self, connection, schema, table):
        effective_schema = schema or self.default_schema(connection)
        result = super().inspect_table(connection, effective_schema, table)
        if result["primary_key"]:
            return result

        # MariaDB can hide table_constraints rows from SELECT-only accounts,
        # while still exposing the non-sensitive COLUMN_KEY flag.
        cursor = connection.cursor()
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s AND column_key = 'PRI' "
            "ORDER BY ordinal_position",
            (effective_schema, table),
        )
        result["primary_key"] = [
            self._information_schema_row(row).get("column_name")
            for row in self._rows(cursor)
        ]
        return result

    def quote_identifier(self, identifier):
        value = str(identifier or "")
        if not value or "\x00" in value:
            raise ConnectorError("INVALID_CONFIGURATION", "Identifier cannot be empty.")
        return "`" + value.replace("`", "``") + "`"


class MariaDBConnector(MySQLConnector):
    key, label, driver = "mariadb", "MariaDB", "PyMySQL"


class SQLiteConnector(BaseDatabaseConnector):
    key, label, driver, server_based, supports_schemas = "sqlite", "SQLite", "sqlite3 (stdlib)", False, False
    fields = (Field("sqlite_token", "SQLite database file", "file"),)
    placeholder = "?"
    _token = re.compile(r"^sqlite_(?P<workspace>[1-9][0-9]*)_[0-9a-f]{32}\.db$")
    staging_ttl_seconds = 24 * 60 * 60

    def validate_configuration(self, raw):
        cfg = dict(raw or {})
        token = str(cfg.get("sqlite_token") or "")
        match = self._token.fullmatch(token)
        if not match:
            raise ConnectorError("INVALID_CONFIGURATION", "A prepared SQLite file token is required.")
        expected_workspace = cfg.get("workspace_id")
        if expected_workspace is not None and int(match.group("workspace")) != int(expected_workspace):
            raise ConnectorError("PERMISSION_DENIED", "The SQLite file belongs to another workspace.", status_code=403)
        root = Path(os.getenv("ETL_SQLITE_ROOT", "/app/uploaded_files")).resolve()
        candidate = root / token
        path = candidate.resolve()
        if candidate.is_symlink() or path.parent != root or not path.is_file():
            raise ConnectorError("DATABASE_NOT_FOUND", "The prepared SQLite file was not found.", status_code=404)
        if wall_time.time() - path.stat().st_mtime >= self.staging_ttl_seconds:
            raise ConnectorError("TOKEN_EXPIRED", "The prepared SQLite file expired. Upload it again.", status_code=410)
        cfg.update({"db_type": self.key, "sqlite_path": str(path)})
        return cfg

    def connect(self, config):
        import sqlite3
        cfg = self.validate_configuration(config) if "sqlite_path" not in config else dict(config)
        connection = sqlite3.connect(f"file:{cfg['sqlite_path']}?mode=ro", uri=True, timeout=cfg.get("connect_timeout", 10))
        connection.row_factory = sqlite3.Row
        return connection

    def list_tables(self, connection, schema=None):
        cursor = connection.cursor()
        cursor.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name")
        return [{"schema": None, "name": row[0], "type": row[1].upper()} for row in cursor.fetchall()]

    def inspect_table(self, connection, schema, table):
        cursor = connection.cursor()
        cursor.execute(f"PRAGMA table_info({self.quote_identifier(table)})")
        rows = cursor.fetchall()
        if not rows:
            raise ConnectorError("TABLE_NOT_FOUND", "The requested table was not found.", status_code=404)
        columns = [
            {"column_name": row[1], "data_type": row[2] or "TEXT", "is_nullable": "NO" if row[3] else "YES", "ordinal_position": row[0] + 1}
            for row in rows
        ]
        primary_key = [row[1] for row in sorted(rows, key=lambda value: value[5]) if row[5]]
        return {"schema": None, "name": table, "columns": columns, "primary_key": primary_key}


class SQLServerConnector(InformationSchemaConnector):
    key, label, default_port, driver = "mssql", "Microsoft SQL Server", 1433, "python-tds"
    fields = SERVER_FIELDS + (
        Field("schema", "Default schema", required=False, default="dbo"),
        Field("encrypt", "Encrypt transport", "boolean", False, True),
        Field("trust_server_certificate", "Trust server certificate", "boolean", False, False),
        Field("cafile", "CA certificate path", required=False),
    )

    def connect(self, config):
        cfg = self.validate_configuration(config) if "resolved_host" not in config else dict(config)
        try:
            import pytds
        except ImportError as exc:
            raise ConnectorError("DRIVER_UNAVAILABLE", "The SQL Server driver is unavailable.", status_code=503) from exc
        kwargs = {}
        if cfg.get("encrypt", True):
            if not cfg.get("cafile"):
                raise ConnectorError("INVALID_CONFIGURATION", "cafile is required when SQL Server transport encryption is enabled.")
            kwargs.update({
                "cafile": cfg["cafile"],
                "validate_host": not bool(cfg.get("trust_server_certificate", False)),
            })
        return pytds.connect(
            server=cfg["resolved_host"], port=cfg["port"], database=cfg["database"],
            user=cfg["username"], password=cfg.get("password", ""),
            login_timeout=cfg["connect_timeout"], timeout=cfg["read_timeout"], as_dict=True, **kwargs,
        )

    def default_schema(self, connection):
        return "dbo"

    def quote_identifier(self, identifier):
        value = str(identifier or "")
        if not value or "\x00" in value:
            raise ConnectorError("INVALID_CONFIGURATION", "Identifier cannot be empty.")
        return "[" + value.replace("]", "]]" ) + "]"

    def build_snapshot_query(self, schema, table, *, columns=None, order_by=None, offset=0, limit=1000, last_pk=None):
        projection = ", ".join(self.quote_identifier(col) for col in columns) if columns else "*"
        query = f"SELECT {projection} FROM {self.qualified_table(schema or 'dbo', table)}"
        params = []
        if order_by and last_pk is not None:
            query += f" WHERE {self.quote_identifier(order_by)} > {self.placeholder}"
            params.append(last_pk)
        query += f" ORDER BY {self.quote_identifier(order_by) if order_by else '(SELECT NULL)'}"
        query += f" OFFSET {0 if last_pk is not None else int(offset)} ROWS FETCH NEXT {int(limit)} ROWS ONLY"
        return query, tuple(params)


class OracleConnector(BaseDatabaseConnector):
    key, label, default_port, driver = "oracle", "Oracle Database", 1521, "python-oracledb (thin)"
    fields = tuple(field for field in SERVER_FIELDS if field.name != "database") + (
        Field("service_name", "Service name"),
        Field("schema", "Schema", required=False),
        Field("tls", "Use TLS (TCPS)", "boolean", False, True),
        Field("wallet_location", "Wallet / trust store path", required=False),
    )

    def validate_configuration(self, raw):
        cfg = dict(raw or {})
        cfg["database"] = cfg.get("service_name") or cfg.get("database")
        validated = super().validate_configuration(cfg)
        validated["service_name"] = validated["database"]
        return validated

    def connect(self, config):
        cfg = self.validate_configuration(config) if "resolved_host" not in config else dict(config)
        try:
            import oracledb
        except ImportError as exc:
            raise ConnectorError("DRIVER_UNAVAILABLE", "The Oracle driver is unavailable.", status_code=503) from exc
        kwargs = {
            "user": cfg["username"],
            "password": cfg.get("password", ""),
            "host": cfg["resolved_host"],
            "port": cfg["port"],
            "service_name": cfg["service_name"],
            "protocol": "tcps" if cfg.get("tls", True) else "tcp",
            "tcp_connect_timeout": cfg["connect_timeout"],
        }
        if cfg.get("wallet_location"):
            kwargs["wallet_location"] = cfg["wallet_location"]
        return oracledb.connect(**kwargs)

    def list_schemas(self, connection):
        cursor = connection.cursor()
        cursor.execute("SELECT username FROM all_users ORDER BY username")
        return [row[0] for row in cursor.fetchall()]

    def _schema(self, connection, schema):
        if schema:
            return schema.upper()
        cursor = connection.cursor()
        cursor.execute("SELECT SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') FROM dual")
        return cursor.fetchone()[0]

    def list_tables(self, connection, schema=None):
        owner = self._schema(connection, schema)
        cursor = connection.cursor()
        cursor.execute("SELECT owner, table_name, 'BASE TABLE' FROM all_tables WHERE owner = :1 UNION ALL SELECT owner, view_name, 'VIEW' FROM all_views WHERE owner = :2 ORDER BY 2", (owner, owner))
        return [{"schema": row[0], "name": row[1], "type": row[2]} for row in cursor.fetchall()]

    def inspect_table(self, connection, schema, table):
        owner = self._schema(connection, schema)
        cursor = connection.cursor()
        cursor.execute("SELECT column_name, data_type, nullable, column_id FROM all_tab_columns WHERE owner = :1 AND table_name = :2 ORDER BY column_id", (owner, table))
        rows = cursor.fetchall()
        if not rows:
            raise ConnectorError("TABLE_NOT_FOUND", "The requested table was not found.", status_code=404)
        cursor.execute("SELECT cols.column_name FROM all_constraints cons JOIN all_cons_columns cols ON cons.owner=cols.owner AND cons.constraint_name=cols.constraint_name WHERE cons.constraint_type='P' AND cons.owner=:1 AND cons.table_name=:2 ORDER BY cols.position", (owner, table))
        return {
            "schema": owner, "name": table,
            "columns": [{"column_name": r[0], "data_type": r[1], "is_nullable": "YES" if r[2] == "Y" else "NO", "ordinal_position": r[3]} for r in rows],
            "primary_key": [r[0] for r in cursor.fetchall()],
        }

    @property
    def placeholder(self):
        return ":1"

    def build_snapshot_query(self, schema, table, *, columns=None, order_by=None, offset=0, limit=1000, last_pk=None):
        projection = ", ".join(self.quote_identifier(col) for col in columns) if columns else "*"
        query = f"SELECT {projection} FROM {self.qualified_table(schema, table)}"
        params = []
        if order_by and last_pk is not None:
            query += f" WHERE {self.quote_identifier(order_by)} > :1"
            params.append(last_pk)
        if order_by:
            query += f" ORDER BY {self.quote_identifier(order_by)}"
        query += f" OFFSET {0 if last_pk is not None else int(offset)} ROWS FETCH NEXT {int(limit)} ROWS ONLY"
        return query, tuple(params)


class ClickHouseConnector(BaseDatabaseConnector):
    key, label, default_port, driver = "clickhouse", "ClickHouse", 9440, "clickhouse-driver"
    supports_schemas = False
    fields = SERVER_FIELDS + (
        Field("secure", "Use TLS", "boolean", False, True),
        Field("verify", "Verify certificate", "boolean", False, True),
        Field("ca_certs", "CA certificate path", required=False),
    )

    def connect(self, config):
        cfg = self.validate_configuration(config) if "resolved_host" not in config else dict(config)
        try:
            from clickhouse_driver import dbapi
        except ImportError as exc:
            raise ConnectorError("DRIVER_UNAVAILABLE", "The ClickHouse driver is unavailable.", status_code=503) from exc
        return dbapi.connect(
            host=cfg["resolved_host"], port=cfg["port"], database=cfg["database"],
            user=cfg["username"], password=cfg.get("password", ""),
            secure=bool(cfg.get("secure", True)), verify=bool(cfg.get("verify", True)),
            ca_certs=cfg.get("ca_certs"), connect_timeout=cfg["connect_timeout"],
            send_receive_timeout=cfg["read_timeout"],
        )

    def list_schemas(self, connection):
        return []

    def list_tables(self, connection, schema=None):
        cursor = connection.cursor()
        cursor.execute("SELECT database, name, 'BASE TABLE' FROM system.tables WHERE database = %(database)s ORDER BY name", {"database": schema} if schema else {}) if schema else cursor.execute("SELECT database, name, 'BASE TABLE' FROM system.tables WHERE database = currentDatabase() ORDER BY name")
        return [{"schema": row[0], "name": row[1], "type": row[2]} for row in cursor.fetchall()]

    def inspect_table(self, connection, schema, table):
        cursor = connection.cursor()
        database = schema
        if database:
            cursor.execute("SELECT name, type, position, is_in_primary_key FROM system.columns WHERE database = %(database)s AND table = %(table)s ORDER BY position", {"database": database, "table": table})
        else:
            cursor.execute("SELECT name, type, position, is_in_primary_key FROM system.columns WHERE database = currentDatabase() AND table = %(table)s ORDER BY position", {"table": table})
        rows = cursor.fetchall()
        if not rows:
            raise ConnectorError("TABLE_NOT_FOUND", "The requested table was not found.", status_code=404)
        return {
            "schema": database, "name": table,
            "columns": [{"column_name": r[0], "data_type": r[1], "is_nullable": "YES" if str(r[1]).startswith("Nullable(") else "NO", "ordinal_position": r[2]} for r in rows],
            "primary_key": [r[0] for r in rows if r[3]],
        }

    def build_snapshot_query(
        self, schema, table, *, columns=None, order_by=None,
        offset=0, limit=1000, last_pk=None,
    ):
        projection = ", ".join(self.quote_identifier(col) for col in columns) if columns else "*"
        query = f"SELECT {projection} FROM {self.qualified_table(schema, table)}"
        params = {}
        if order_by and last_pk is not None:
            # clickhouse-driver's DB-API implements ``pyformat`` rather than
            # the positional ``%s`` style used by PostgreSQL/MySQL drivers.
            query += f" WHERE {self.quote_identifier(order_by)} > %(last_pk)s"
            params["last_pk"] = last_pk
        if order_by:
            query += f" ORDER BY {self.quote_identifier(order_by)}"
        query += f" LIMIT {int(limit)}"
        if last_pk is None:
            query += f" OFFSET {int(offset)}"
        return query, params


class ConnectorRegistry:
    def __init__(self, connectors: Iterable[BaseDatabaseConnector] = ()):
        self._connectors: Dict[str, BaseDatabaseConnector] = {}
        for connector in connectors:
            self.register(connector)

    def register(self, connector: BaseDatabaseConnector) -> None:
        self._connectors[connector.key] = connector

    def get(self, engine: str) -> BaseDatabaseConnector:
        normalized = normalize_db_type(engine)
        if not normalized or normalized not in self._connectors:
            raise ConnectorError("UNSUPPORTED_CONNECTOR", "The requested database connector is not supported.", status_code=404)
        return self._connectors[normalized]

    def capabilities(self) -> dict:
        return {
            "version": 1,
            "mode": "snapshot",
            "connectors": [connector.capabilities() for connector in self._connectors.values()],
        }


connector_registry = ConnectorRegistry((
    PostgresConnector(), MySQLConnector(), MariaDBConnector(), SQLServerConnector(),
    OracleConnector(), SQLiteConnector(), ClickHouseConnector(),
))
