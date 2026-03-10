import os
import time
import argparse
from uuid import uuid4

from shared.utils.kafka_producer import KafkaMessageProducer


def generate_row(i: int) -> dict:
    return {
        "row_id": i,
        "data": {
            "id": i,
            "value": f"value_{i}",
            "flag": i % 2 == 0,
        },
        "_dedup_key": str(i),
        "_extracted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def run_load_test(total_rows: int, batch_size: int, target_rows_per_sec: int) -> None:
    producer = KafkaMessageProducer()
    source_id = os.getenv("LOAD_TEST_SOURCE", "load_test_source")
    batch_id = str(uuid4())

    rows_sent = 0
    start_time = time.time()
    per_batch_target = max(1, batch_size)
    target_batch_interval = per_batch_target / max(1, target_rows_per_sec)

    while rows_sent < total_rows:
        batch_rows = []
        for _ in range(min(batch_size, total_rows - rows_sent)):
            batch_rows.append(generate_row(rows_sent))
            rows_sent += 1

        message = {
            "source": source_id,
            "batch_id": batch_id,
            "schema_version": "load_test_v1",
            "rows": batch_rows,
            "row_count": len(batch_rows),
        }
        producer.send("extracted_rows_topic", message)

        elapsed = time.time() - start_time
        expected_elapsed = (rows_sent / max(1, target_rows_per_sec))
        sleep_time = expected_elapsed - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)

    duration = time.time() - start_time
    rate = rows_sent / max(duration, 0.001)
    print(f"Sent {rows_sent} rows in {duration:.2f}s ({rate:.2f} rows/sec)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=100000, help="Total rows to send")
    parser.add_argument("--batch-size", type=int, default=500, help="Rows per Kafka message")
    parser.add_argument("--rate", type=int, default=100000, help="Target rows per second")
    args = parser.parse_args()

    run_load_test(args.rows, args.batch_size, args.rate)
