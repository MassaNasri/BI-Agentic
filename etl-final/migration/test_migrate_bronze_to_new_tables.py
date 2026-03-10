from unittest.mock import Mock

from migrate_bronze_to_new_tables import migrate_bronze


def test_migrate_bronze_sanitizes_and_quotes_table_names():
    client = Mock()

    migrate_bronze("bronze.bad table", "target;drop", client)

    first = client.execute.call_args_list[0][0][0]
    second = client.execute.call_args_list[1][0][0]
    assert first == "CREATE TABLE IF NOT EXISTS `target_drop` AS `bronze`.`bad_table`"
    assert second == "INSERT INTO `target_drop` SELECT * FROM `bronze`.`bad_table`"
