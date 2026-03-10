import argparse
import time
from uuid import uuid4
from clickhouse_driver import Client
from shared.utils.kafka_producer import KafkaMessageProducer


def fetch_rows(client: Client, table: str, limit: int, offset: int):
    query = f"SELECT * FROM {table} LIMIT {limit} OFFSET {offset}"
    return client.execute(query, with_column_types=True)


def reprocess_table(table: str, batch_size: int, client: Client, producer: KafkaMessageProducer):
    batch_id = str(uuid4())
    offset = 0
    while True:
        rows, columns = fetch_rows(client, table, batch_size, offset)
        if not rows:
            break
        col_names = [c[0] for c in columns]
        payload_rows = []
        for row in rows:
            payload_rows.append({"data": dict(zip(col_names, row)), "batch_id": batch_id})
        producer.send("extracted_rows_topic", {
            "source": table,
            "batch_id": batch_id,
            "rows": payload_rows,
            "row_count": len(payload_rows),
        })
        offset += batch_size
        time.sleep(0.01)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--table", required=True)
    parser.add_argument("--batch-size", type=int, default=500)
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
    producer = KafkaMessageProducer()
    reprocess_table(args.table, args.batch_size, client, producer)
