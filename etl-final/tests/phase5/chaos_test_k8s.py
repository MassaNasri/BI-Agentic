import argparse
import subprocess
import time


def run(cmd: list[str]) -> None:
    subprocess.check_call(cmd)


def chaos_kill_pods(namespace: str, label: str, iterations: int, wait_seconds: int) -> None:
    for i in range(iterations):
        print(f"[CHAOS] Iteration {i + 1}/{iterations} - deleting pods with label {label}")
        run(["kubectl", "delete", "pods", "-n", namespace, "-l", label])
        time.sleep(wait_seconds)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--namespace", default="etl")
    parser.add_argument("--label", default="app=transformer-service")
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--wait", type=int, default=30)
    args = parser.parse_args()

    chaos_kill_pods(args.namespace, args.label, args.iterations, args.wait)
