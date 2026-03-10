import json
import time
import argparse
from pathlib import Path

from load_test_100k_rows import run_load_test


def load_baseline(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", default="performance_baseline.json")
    parser.add_argument("--rows", type=int, default=1_000_000)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--rate", type=int, default=150000)
    args = parser.parse_args()

    baseline = load_baseline(Path(args.baseline))
    start = time.time()
    run_load_test(args.rows, args.batch_size, args.rate)
    duration = time.time() - start
    rate = args.rows / max(duration, 0.001)

    min_rate = baseline.get("min_rows_per_sec", 0)
    max_duration = baseline.get("max_duration_seconds")

    if rate < min_rate:
        raise SystemExit(f"Throughput regression: {rate:.2f} < {min_rate}")
    if max_duration is not None and duration > max_duration:
        raise SystemExit(f"Duration regression: {duration:.2f}s > {max_duration}")
    print(f"Performance regression test passed: {rate:.2f} rows/sec")
