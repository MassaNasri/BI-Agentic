"""Typed, bounded CDC reconciliation digests shared by source and Query."""

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal


def lsn_number(value):
    """PostgreSQL pg_lsn text to its unsigned 64-bit position."""
    high, low = value.split("/")
    return (int(high, 16) << 32) | int(low, 16)


def canonical_cell(value, column):
    if value is None:
        return ["null", None]
    kind = column["postgres_type"]
    if kind in {"smallint", "integer", "bigint"}:
        return [kind, str(int(value))]
    if kind == "boolean":
        if value is True or str(value).lower() in {"1", "true"}:
            return [kind, "true"]
        if value is False or str(value).lower() in {"0", "false"}:
            return [kind, "false"]
        raise ValueError("Invalid reconciliation boolean")
    if kind.startswith("numeric("):
        scale = int(kind.rsplit(",", 1)[1].rstrip(")"))
        number = Decimal(str(value))
        if not number.is_finite():
            raise ValueError("Invalid reconciliation decimal")
        return [kind, format(number, f".{scale}f")]
    if kind in {"json", "jsonb"}:
        parsed = json.loads(value, parse_float=Decimal) if isinstance(value, str) else value
        return [kind, _canonical_json(parsed)]
    if kind == "date":
        return [kind, value.isoformat() if isinstance(value, date) else str(value)]
    if kind.startswith("timestamp"):
        if isinstance(value, datetime):
            if value.tzinfo is not None:
                value = value.astimezone(timezone.utc).replace(tzinfo=None)
            value = value.isoformat(sep=" ", timespec="microseconds")
        else:
            value = str(value).replace("T", " ")
            if "." not in value:
                value += ".000000"
            else:
                base, micros = value.split(".", 1)
                value = base + "." + micros.ljust(6, "0")
        return [kind, value]
    return [kind, str(value)]


def row_bytes(row, columns):
    typed = [[column["name"], canonical_cell(row[column["name"]], column)]
             for column in columns]
    return json.dumps(typed, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _canonical_json(value, depth=0):
    if depth > 64:
        raise ValueError("Reconciliation JSON depth exceeded")
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if type(value) is int:
        return str(value)
    if isinstance(value, Decimal) and value.is_finite():
        exact = format(value, "f")
        return exact.rstrip("0").rstrip(".") if "." in exact else exact
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ",".join(_canonical_json(item, depth + 1) for item in value) + "]"
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return "{" + ",".join(json.dumps(key, ensure_ascii=False) + ":" +
                             _canonical_json(value[key], depth + 1) for key in sorted(value)) + "}"
    raise ValueError("Invalid reconciliation JSON")


def chunk_digest(rows, columns):
    digest = hashlib.sha256()
    count = 0
    for row in rows:
        encoded = row_bytes(row, columns)
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        count += 1
    return {"count": count, "sha256": digest.hexdigest()}
