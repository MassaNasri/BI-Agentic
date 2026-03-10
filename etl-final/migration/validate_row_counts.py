import argparse
from clickhouse_driver import Client
from shared.utils.ch_identifiers import quote_table_name


def get_count(client: Client, table: str) -> int:
    result = client.execute(f"SELECT count() FROM {quote_table_name(table)}")
    return int(result[0][0]) if result else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--old-table", required=True)
    parser.add_argument("--new-table", required=True)
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
    old_count = get_count(client, args.old_table)
    new_count = get_count(client, args.new_table)
    diff = abs(old_count - new_count)
    pct = (diff / max(old_count, 1)) * 100.0
    print(f"Old: {old_count} New: {new_count} Diff: {diff} ({pct:.4f}%)")
