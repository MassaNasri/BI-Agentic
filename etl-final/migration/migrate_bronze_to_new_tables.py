import argparse
from clickhouse_driver import Client
from shared.utils.ch_identifiers import quote_table_name


def migrate_bronze(source_table: str, target_table: str, client: Client) -> None:
    # Non-destructive migration: create target if missing, insert from source
    safe_source = quote_table_name(source_table)
    safe_target = quote_table_name(target_table)
    client.execute(f"CREATE TABLE IF NOT EXISTS {safe_target} AS {safe_source}")
    client.execute(f"INSERT INTO {safe_target} SELECT * FROM {safe_source}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-table", required=True)
    parser.add_argument("--target-table", required=True)
    parser.add_argument("--host", default="clickhouse")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--database", default="etl")
    parser.add_argument("--user", default="default")
    parser.add_argument("--password", default="")
    args = parser.parse_args()

    client = Client(
        host=args.host,
        port=args.port,
        user=args.user,
        password=args.password,
        database=args.database,
    )
    migrate_bronze(args.source_table, args.target_table, client)
