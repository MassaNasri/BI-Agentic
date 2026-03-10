import argparse
import requests


def check(url: str) -> None:
    resp = requests.get(url, timeout=5)
    if resp.status_code != 200:
        raise SystemExit(f"Health check failed: {url} -> {resp.status_code}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--connector", default="http://localhost:8001/health/")
    parser.add_argument("--extractor", default="http://localhost:8003/health/")
    parser.add_argument("--transformer", default="http://localhost:8004/health/")
    parser.add_argument("--loader", default="http://localhost:8005/health/")
    parser.add_argument("--metadata", default="http://localhost:8006/health/")
    args = parser.parse_args()

    check(args.connector)
    check(args.extractor)
    check(args.transformer)
    check(args.loader)
    check(args.metadata)
    print("Smoke tests passed.")
