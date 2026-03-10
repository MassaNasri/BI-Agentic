import argparse
from load_test_100k_rows import run_load_test


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=10_000_000, help="Total rows to send")
    parser.add_argument("--batch-size", type=int, default=1000, help="Rows per Kafka message")
    parser.add_argument("--rate", type=int, default=200000, help="Target rows per second")
    args = parser.parse_args()

    run_load_test(args.rows, args.batch_size, args.rate)
