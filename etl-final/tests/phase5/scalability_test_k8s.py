import argparse
import subprocess


def run(cmd: list[str]) -> None:
    subprocess.check_call(cmd)


def scale_and_wait(namespace: str, deployment: str, replicas: int) -> None:
    run(["kubectl", "scale", "deployment", deployment, "-n", namespace, f"--replicas={replicas}"])
    run(["kubectl", "rollout", "status", "deployment", deployment, "-n", namespace])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--namespace", default="etl")
    parser.add_argument("--deployment", default="transformer-service")
    parser.add_argument("--replicas", nargs="+", type=int, default=[1, 10, 100])
    args = parser.parse_args()

    for count in args.replicas:
        print(f"[SCALE] Scaling {args.deployment} to {count} replicas")
        scale_and_wait(args.namespace, args.deployment, count)
