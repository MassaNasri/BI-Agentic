"""Catalog-driven PostgreSQL mapping; never infer CDC types from row samples."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID
import json
import re
from bi_platform_shared.cdc_contract import CdcError, identifier


def clickhouse_type(pg_type, nullable):
    mapping = {"smallint": "Int16", "integer": "Int32", "bigint": "Int64", "boolean": "Bool",
               "text": "String", "uuid": "UUID", "date": "Date32", "json": "String", "jsonb": "String",
               "timestamp without time zone": "DateTime64(6, 'UTC')",
               "timestamp with time zone": "DateTime64(6, 'UTC')"}
    base = mapping.get(pg_type)
    if re.fullmatch(r"(?:character varying|character)(?:\(\d+\))?", pg_type):
        base = "String"
    numeric = re.fullmatch(r"numeric\((\d+),(\d+)\)", pg_type)
    if numeric:
        precision, scale = map(int, numeric.groups())
        if 1 <= precision <= 76 and 0 <= scale <= precision:
            base = f"Decimal({precision}, {scale})"
    if not base:
        raise CdcError("CDC_TYPE_UNSUPPORTED")
    return f"Nullable({base})" if nullable else base


def inspect_schema(connection, schema, table):
    identifier(schema), identifier(table)
    with connection.cursor() as cur:
        cur.execute("""SELECT a.attname, format_type(a.atttypid,a.atttypmod), NOT a.attnotnull,
                       EXISTS(SELECT 1 FROM pg_index i WHERE i.indrelid=c.oid AND i.indisprimary AND a.attnum=ANY(i.indkey))
                       FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
                       JOIN pg_namespace n ON n.oid=c.relnamespace
                       WHERE n.nspname=%s AND c.relname=%s AND a.attnum>0 AND NOT a.attisdropped
                       ORDER BY a.attnum""", (schema, table))
        rows = cur.fetchall()
    columns = [{"name": identifier(name), "postgres_type": typ, "nullable": nullable,
                "clickhouse_type": clickhouse_type(typ, nullable)} for name, typ, nullable, pk in rows]
    primary_key = [name for name, typ, nullable, pk in rows if pk]
    if not columns or not primary_key:
        raise CdcError("CDC_PRIMARY_KEY_REQUIRED")
    return columns, primary_key


def schema_additions(previous, current, old_key, new_key):
    old, new = {c["name"]: c for c in previous}, {c["name"]: c for c in current}
    if old_key != new_key or any(new.get(name) != value for name, value in old.items()):
        raise CdcError("CDC_SCHEMA_INCOMPATIBLE")
    added = [c for c in current if c["name"] not in old]
    if any(not c["nullable"] for c in added):
        raise CdcError("CDC_SCHEMA_INCOMPATIBLE")
    return added


def canonical_json(value, depth=0):
    """Serialize JSONB without converting exact JSON numbers through float."""
    if depth > 64:
        raise CdcError("CDC_VALUE_INVALID")
    if value is None:
        return 'null'
    if value is True:
        return 'true'
    if value is False:
        return 'false'
    if type(value) is int:
        return str(value)
    if isinstance(value, Decimal) and value.is_finite():
        exact = format(value, 'f')
        return exact.rstrip('0').rstrip('.') if '.' in exact else exact
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return '[' + ','.join(canonical_json(item, depth+1) for item in value) + ']'
    if isinstance(value, dict) and all(isinstance(k, str) for k in value):
        return '{' + ','.join(json.dumps(k, ensure_ascii=False) + ':' + canonical_json(value[k], depth+1)
                              for k in sorted(value)) + '}'
    raise CdcError("CDC_VALUE_INVALID")


def convert(value, column):
    if value is None:
        if not column["nullable"]:
            raise CdcError("CDC_NULL_NOT_ALLOWED")
        return None
    pg = column["postgres_type"]
    try:
        if pg in {"smallint", "integer", "bigint"}:
            bits = {"smallint": 16, "integer": 32, "bigint": 64}[pg]
            if type(value) is not int or not -(2**(bits-1)) <= value < 2**(bits-1):
                raise ValueError
        elif pg == "boolean":
            if type(value) is not bool:
                raise ValueError
        elif pg.startswith("numeric("):
            if isinstance(value, (float, bool, dict, list)):
                raise ValueError
            precision, scale = map(int, re.findall(r"\d+", pg))
            number = Decimal(str(value))
            if not number.is_finite() or number.as_tuple().exponent < -scale or number.copy_abs() >= Decimal(10)**(precision-scale):
                raise ValueError
            return format(number, f'.{scale}f')
        elif pg == "uuid":
            if not isinstance(value, str):
                raise ValueError
            return str(UUID(value))
        elif pg == "date":
            return (date(1970, 1, 1) + timedelta(days=value)).isoformat() if type(value) is int else date.fromisoformat(value).isoformat()
        elif pg.startswith("timestamp"):
            # Debezium adaptive_time_microseconds: timestamp is microseconds;
            # timestamptz is an ISO UTC string. Never pass through a float.
            if pg == 'timestamp without time zone' and type(value) is int:
                parsed = datetime(1970, 1, 1) + timedelta(microseconds=value)
            elif pg == 'timestamp with time zone' and isinstance(value, str):
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError
                parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            else:
                raise ValueError
            return parsed.isoformat(sep=" ", timespec="microseconds")
        elif pg in {"json", "jsonb"}:
            parsed = json.loads(value, parse_float=Decimal,
                                parse_constant=lambda _: (_ for _ in ()).throw(ValueError())) if isinstance(value, str) else value
            return canonical_json(parsed)
        elif not isinstance(value, str) or value == "__debezium_unavailable_value":
            raise ValueError
    except (ValueError, TypeError, OverflowError, ArithmeticError, RecursionError):
        raise CdcError("CDC_VALUE_INVALID") from None
    return value


def ensure_row_images(event, columns):
    expected = {c["name"] for c in columns}
    if len(expected) != len(columns):
        raise CdcError("CDC_SCHEMA_INCOMPATIBLE")
    for image in (event["before"], event["after"]):
        if image is None:
            continue
        if not isinstance(image, dict) or set(image) != expected:
            raise CdcError("CDC_SCHEMA_INCOMPATIBLE")
        for column in columns:
            convert(image[column["name"]], column)


def transform(event, columns, primary_key, schema_version=None):
    if schema_version is not None and event.get("schema_version") != schema_version:
        raise CdcError("CDC_SCHEMA_INCOMPATIBLE")
    ensure_row_images(event, columns)
    row = event["before"] if event["operation"] == "DELETE" else event["after"]
    return {**event, "row": {c["name"]: convert(row[c["name"]], c) for c in columns}}
