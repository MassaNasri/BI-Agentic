"""Cross-owner typed digest invariants for watermark reconciliation."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from bi_platform_shared.cdc_reconciliation import chunk_digest, lsn_number


def test_typed_chunk_digest_preserves_exact_business_state():
    columns = [
        {"name": "id", "postgres_type": "bigint"},
        {"name": "amount", "postgres_type": "numeric(20,4)"},
        {"name": "payload", "postgres_type": "jsonb"},
        {"name": "at", "postgres_type": "timestamp with time zone"},
        {"name": "reference", "postgres_type": "uuid"},
        {"name": "optional", "postgres_type": "text"},
    ]
    source = {"id": 9007199254740993, "amount": Decimal("1.2300"),
              "payload": {"b": [Decimal("1.20"), None], "a": "x"},
              "at": datetime(2026, 1, 1, 2, 3, 4, 123456, timezone.utc),
              "reference": UUID("4b8f31e0-5889-4c40-92c6-42197a616a7e"),
              "optional": None}
    query = {"id": "9007199254740993", "amount": "1.2300",
             "payload": '{"a":"x","b":[1.20,null]}',
             "at": "2026-01-01 02:03:04.123456",
             "reference": "4b8f31e0-5889-4c40-92c6-42197a616a7e",
             "optional": None}
    assert chunk_digest([source], columns) == chunk_digest([query], columns)
    assert chunk_digest([source], columns) != chunk_digest([{**query, "optional": ""}], columns)
    assert chunk_digest([source], columns) != chunk_digest([{**query, "amount": "1.2301"}], columns)
    assert chunk_digest([source], columns) != chunk_digest([{**query, "id": "9007199254740994"}], columns)


def test_lsn_is_numeric_not_lexicographic():
    assert lsn_number("1/0") == 2**32
    assert lsn_number("0/FFFFFFFF") < lsn_number("1/0")
