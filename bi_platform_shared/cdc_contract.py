"""ChangeEnvelope.v1: dependency-free, tenant-bound PostgreSQL change records.

Kafka offsets are delivery positions, never source row versions. Source LSN and
transaction order make replay and delayed delivery independent of arrival order.
"""
from dataclasses import dataclass
import hashlib
import json
import re
from uuid import UUID


class CdcError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", value):
        raise CdcError("CDC_IDENTIFIER_UNSUPPORTED")
    if value.startswith("_cdc_"):
        raise CdcError("CDC_RESERVED_COLUMN")
    return value


@dataclass(frozen=True)
class Scope:
    workspace_id: int
    source_id: str
    pipeline_id: str
    dataset_id: int
    schema: str
    table: str
    generation: int = 1
    configuration_epoch: int = 0
    credential_epoch: int = 0

    def __post_init__(self):
        if type(self.workspace_id) is not int or self.workspace_id < 1 or type(self.dataset_id) is not int or self.dataset_id < 1:
            raise CdcError("CDC_SCOPE_INVALID")
        UUID(self.source_id)
        UUID(self.pipeline_id)
        identifier(self.schema)
        identifier(self.table)
        if type(self.generation) is not int or self.generation < 1:
            raise CdcError("CDC_GENERATION_INVALID")
        if (type(self.configuration_epoch) is not int or self.configuration_epoch < 0
                or type(self.credential_epoch) is not int or self.credential_epoch < 0):
            raise CdcError("CDC_GENERATION_INVALID")

    @property
    def event_scope(self):
        # Preserve the physical names of already provisioned D1-D4 scopes.
        # The retained generation-1 ChangeEnvelope.v1 also stays byte-stable.
        return {key: value for key, value in self.__dict__.items()
                if key not in {"configuration_epoch", "credential_epoch"}
                and (key != "generation" or self.generation != 1)}

    @property
    def token(self):
        return hashlib.sha256(canonical(self.event_scope).encode()).hexdigest()[:40]

    @property
    def publication_token(self):
        # PostgreSQL publication is a table selection, not an offset lineage.
        # Reusing generation 1's exact table publication is safe; every new
        # Debezium slot, topic, connector and warehouse object still isolates.
        identity = {k: v for k, v in self.event_scope.items() if k != "generation"}
        return hashlib.sha256(canonical(identity).encode()).hexdigest()[:40]

    def topic(self, stage):
        if stage not in {"raw", "normalized", "transformed", "dlq", "notification"}:
            raise CdcError("CDC_STAGE_INVALID")
        return f"biavora.cdc.v1.{self.token}.{stage}"

    @property
    def raw_topic(self):
        return f"{self.topic('raw')}.{self.schema}.{self.table}"


OPERATIONS = {"r": "SNAPSHOT", "c": "INSERT", "u": "UPDATE", "d": "DELETE"}
SCOPE_FIELDS = ("workspace_id", "source_id", "pipeline_id", "dataset_id")


def _uint(value, bits):
    if type(value) is int:
        number = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]{1,20}", value):
        number = int(value)
    else:
        raise CdcError("CDC_POSITION_INVALID")
    if not 0 <= number < 2**bits:
        raise CdcError("CDC_POSITION_INVALID")
    return number


def normalize(value, key, scope, primary_key, schema_version=1):
    """Only the trusted subscription supplies tenant scope; null is a tombstone."""
    if value is None:
        return None
    if type(schema_version) is not int or schema_version < 1:
        raise CdcError("CDC_SCHEMA_VERSION_INVALID")
    if not isinstance(value, dict):
        raise CdcError("CDC_EVENT_INVALID")
    payload = value.get("payload", value)
    key = key.get("payload", key) if isinstance(key, dict) else key
    if not isinstance(payload, dict) or payload.get("op") not in OPERATIONS:
        raise CdcError("CDC_OPERATION_UNSUPPORTED")
    source = payload.get("source")
    if not isinstance(source, dict):
        raise CdcError("CDC_EVENT_INVALID")
    for claim in (value, payload, source):
        if any(field in claim and claim[field] != getattr(scope, field) for field in SCOPE_FIELDS):
            raise CdcError("CDC_SCOPE_MISMATCH")
        if "generation" in claim and claim["generation"] != scope.generation:
            raise CdcError("CDC_SCOPE_MISMATCH")
    if source.get("schema") != scope.schema or source.get("table") != scope.table:
        raise CdcError("CDC_SCOPE_MISMATCH")
    if (not isinstance(primary_key, list) or not primary_key or len(set(primary_key)) != len(primary_key)
            or not isinstance(key, dict) or set(key) != set(primary_key)
            or any(key[k] is None or isinstance(key[k], (dict, list)) for k in primary_key)):
        raise CdcError("CDC_PRIMARY_KEY_REQUIRED")
    op = OPERATIONS[payload["op"]]
    before, after = payload.get("before"), payload.get("after")
    if op in {"SNAPSHOT", "INSERT"} and (before is not None or not isinstance(after, dict)):
        raise CdcError("CDC_ROW_IMAGE_INVALID")
    if op == "UPDATE" and (not isinstance(before, dict) or not isinstance(after, dict)):
        raise CdcError("CDC_ROW_IMAGE_INVALID")
    if op == "DELETE" and (not isinstance(before, dict) or after is not None):
        raise CdcError("CDC_ROW_IMAGE_INVALID")
    row = before if op == "DELETE" else after
    if not isinstance(row, dict) or any(row.get(k) != key[k] for k in primary_key):
        raise CdcError("CDC_KEY_MISMATCH")
    if op == "UPDATE" and any(before.get(k) != key[k] for k in primary_key):
        raise CdcError("CDC_KEY_MUTATION_UNSUPPORTED")
    try:
        lsn = _uint(source["lsn"], 64)
        transaction = payload.get("transaction")
        order = 0 if op == "SNAPSHOT" and transaction is None else _uint(transaction["total_order"], 32)
        if op != "SNAPSHOT" and order == 0:
            raise CdcError("CDC_POSITION_INVALID")
        txid = source.get("txId")
        transaction_id = "" if op == "SNAPSHOT" and txid is None else str(_uint(txid, 64))
    except (KeyError, TypeError, CdcError):
        raise CdcError("CDC_POSITION_INVALID") from None
    timestamp = source.get("ts_ms")
    if type(timestamp) is not int or timestamp < 0:
        raise CdcError("CDC_TIMESTAMP_INVALID")
    snapshot = source.get("snapshot")
    if op == "SNAPSHOT" and not (snapshot is True or snapshot in ("first", "true", "last")):
        raise CdcError("CDC_SNAPSHOT_INVALID")
    if op != "SNAPSHOT" and not (snapshot is None or snapshot is False or snapshot == "false"):
        raise CdcError("CDC_SNAPSHOT_INVALID")
    position = {"lsn": lsn, "transaction_id": transaction_id, "event_index": order}
    identity = {**scope.event_scope, "primary_key": key, "position": position, "operation": op}
    event = {"contract": "ChangeEnvelope.v1" if scope.generation == 1 else "ChangeEnvelope.v2",
             **identity, "before": before, "after": after,
             "schema_version": schema_version, "source_timestamp_ms": timestamp,
             "snapshot_complete": op != "SNAPSHOT" or snapshot == "last",
             "event_id": hashlib.sha256(canonical(identity).encode()).hexdigest()}
    # Snapshot ranks below streaming at the same LSN. 97 bits fit UInt128.
    event["version"] = str((lsn << 33) + (0 if op == "SNAPSHOT" else 2**32 + order))
    return event


def validate(event, scope, primary_key):
    expected_contract = "ChangeEnvelope.v1" if scope.generation == 1 else "ChangeEnvelope.v2"
    if not isinstance(event, dict) or event.get("contract") != expected_contract:
        raise CdcError("CDC_CONTRACT_INVALID")
    if any(event.get(k) != v for k, v in scope.event_scope.items()):
        raise CdcError("CDC_SCOPE_MISMATCH")
    reverse = {v: k for k, v in OPERATIONS.items()}
    if event.get("operation") not in reverse:
        raise CdcError("CDC_OPERATION_UNSUPPORTED")
    position = event.get("position") or {}
    rebuilt = normalize({"op": reverse[event["operation"]], "before": event.get("before"), "after": event.get("after"),
                         "source": {"schema": scope.schema, "table": scope.table, "lsn": position.get("lsn"),
                                    "txId": position.get("transaction_id") or None, "ts_ms": event.get("source_timestamp_ms"),
                                    "snapshot": ("last" if event.get("snapshot_complete") else "true")
                                    if event["operation"] == "SNAPSHOT" else "false"},
                         "transaction": {"total_order": position.get("event_index")}},
                        event.get("primary_key"), scope, primary_key, event.get("schema_version"))
    if rebuilt != event:
        raise CdcError("CDC_CONTRACT_INVALID")
    return event


def safe_dlq(scope, event_id, code, stage, timestamp):
    """No raw rows, Kafka records, credential references or exception strings."""
    if not isinstance(event_id, str) or not re.fullmatch(r'[0-9a-f]{64}', event_id):
        event_id = None
    if not isinstance(code, str) or not re.fullmatch(r'CDC_[A-Z_]{1,50}', code):
        code = 'CDC_EVENT_INVALID'
    if stage not in {'normalize', 'transform', 'load'}:
        stage = 'normalize'
    if not isinstance(timestamp, str) or len(timestamp) > 40 or not re.fullmatch(r'[0-9TZ:+.\-]{1,40}', timestamp):
        timestamp = ''
    return {"contract": "CdcFailure.v1", **scope.event_scope, "event_id": event_id,
            "reason": code, "stage": stage, "retry_count": 0, "timestamp": timestamp}
