from unittest.mock import Mock

from shared.utils.idempotency_manager import IdempotencyManager, IdempotencyKey, PipelineStage


def test_claim_new_keys_inserts_before_reading_winners():
    client = Mock()
    calls = []

    def _execute(query, params=None):
        calls.append((query, params))
        if "argMax" in query:
            # Winner is the claim inserted by current call for h2 only.
            inserted_payload = calls[0][1]
            winner_h2 = None
            for row in inserted_payload:
                if row["_dedup_key"].endswith(":h2"):
                    winner_h2 = row["_row_id"]
            return [("src:b:h1", "other-claim"), ("src:b:h2", winner_h2)]
        return None

    client.execute.side_effect = _execute
    manager = IdempotencyManager(client)
    keys = [
        IdempotencyKey(source_id="src", batch_id="b", row_hash="h1"),
        IdempotencyKey(source_id="src", batch_id="b", row_hash="h2"),
    ]

    claims = manager.claim_new_keys(keys, PipelineStage.TRANSFORM)

    assert len(claims) == 1
    assert claims[0].key.row_hash == "h2"
    assert "INSERT INTO deduplication_log" in calls[0][0]
    assert "argMax" in calls[1][0]


def test_check_and_mark_batch_uses_claims_and_returns_only_new():
    client = Mock()

    def _execute(query, params=None):
        if "argMax" in query:
            inserted_payload = client.execute.call_args_list[0][0][1]
            winner = inserted_payload[0]["_row_id"]
            return [("src:b:h1", winner)]
        return None

    client.execute.side_effect = _execute
    manager = IdempotencyManager(client)

    keys = [IdempotencyKey(source_id="src", batch_id="b", row_hash="h1")]
    new_keys = manager.check_and_mark_batch(keys, PipelineStage.LOAD)

    assert len(new_keys) == 1
    assert new_keys[0].row_hash == "h1"


def test_rollback_claims_deletes_by_claim_row_ids():
    client = Mock()
    manager = IdempotencyManager(client)
    keys = [IdempotencyKey(source_id="src", batch_id="b", row_hash="h1")]

    # Make claim query select itself as winner.
    def _execute(query, params=None):
        if "argMax" in query:
            inserted_payload = client.execute.call_args_list[0][0][1]
            return [("src:b:h1", inserted_payload[0]["_row_id"])]
        return None

    client.execute.side_effect = _execute
    claims = manager.claim_new_keys(keys, PipelineStage.EXTRACT)
    ok = manager.rollback_claims(claims, PipelineStage.EXTRACT)

    assert ok is True
    rollback_query = client.execute.call_args_list[-1][0][0]
    rollback_params = client.execute.call_args_list[-1][0][1]
    assert "ALTER TABLE deduplication_log" in rollback_query
    assert rollback_params["stage"] == "extract"
    assert len(rollback_params["row_ids"]) == 1
