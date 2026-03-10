from unittest.mock import Mock

from shared.utils.quarantine_manager import QuarantineManager, QuarantineRecord


def _build_manager():
    client = Mock()
    # First execute call is create table in constructor.
    client.execute.return_value = None
    manager = QuarantineManager(client, table_name="q;drop")
    return manager, client


def test_quarantine_insert_uses_safe_table_name():
    manager, client = _build_manager()
    client.execute.reset_mock()

    manager.quarantine(
        QuarantineRecord(
            source_id="s",
            batch_id="b",
            quarantine_reason="bad",
            validation_errors=["e"],
            original_row={"x": 1},
        )
    )

    query = client.execute.call_args[0][0]
    assert "INSERT INTO `q_drop`" in query


def test_list_quarantined_uses_safe_table_name():
    manager, client = _build_manager()
    client.execute.reset_mock()
    client.execute.return_value = []

    manager.list_quarantined(limit=10, offset=0)

    query = client.execute.call_args[0][0]
    assert "FROM `q_drop`" in query


def test_mark_reprocessed_uses_safe_table_name():
    manager, client = _build_manager()
    client.execute.reset_mock()

    manager.mark_reprocessed(["abc"])

    query = client.execute.call_args[0][0]
    assert "ALTER TABLE `q_drop`" in query
