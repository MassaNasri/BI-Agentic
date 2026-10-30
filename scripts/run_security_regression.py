"""Run one release security suite in its own service dependency environment.

CI supplies a fresh matrix runner; locally invoke this with a separate venv's
Python for each suite. Never install multiple suites into the same interpreter.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SUITES = {
    "query": {
        "requirements": ["services/query-service/requirements.txt"],
        "cwd": "services/query-service",
        "commands": [
            ["-m", "pytest", "tests/test_clickhouse_credential_redaction.py", "tests/test_ingestion_callback_security.py", "tests/test_security_configuration.py", "-q"],
            ["manage.py", "test", "integration.test_public_boundary", "--settings=service_config.sqlite_test_settings", "--verbosity", "1"],
        ],
    },
    "visualization": {
        "requirements": ["services/visualization-service/requirements.txt"],
        "cwd": "services/visualization-service",
        "commands": [["-m", "pytest", "visualization_api/tests/test_security_ownership_and_query_reference.py", "-q"]],
    },
    "voice": {
        "requirements": ["services/voice-service/requirements.txt"],
        "cwd": "services/voice-service",
        "commands": [["-m", "pytest", "voice_reports/tests_security_workspace_authorization.py", "-q"]],
    },
    "auth": {
        "requirements": ["services/auth-service/requirements.txt"],
        "cwd": "services/auth-service",
        "commands": [["manage.py", "test", "users.tests_security_invitation", "--verbosity", "1"]],
    },
    "workspace": {
        "requirements": ["services/workspace-service/requirements.txt"],
        "cwd": "services/workspace-service",
        "commands": [["manage.py", "test", "workspace.tests_security_invitation", "--verbosity", "1"]],
    },
    "etl": {
        # The security test initializes Connector's Django app, so shared alone
        # is insufficient. Both native ETL manifests agree on Kafka 2.3.0.
        "requirements": ["etl-final/shared/requirements.txt", "etl-final/connector-service/requirements.txt"],
        "cwd": ".",
        "commands": [["-m", "pytest", "etl-final/shared/security/test_security_controls.py", "-q"]],
    },
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", choices=SUITES)
    parser.add_argument("--install", action="store_true", help="Install only this suite's native requirements, then exit.")
    args = parser.parse_args()
    suite = SUITES[args.suite]
    if args.install:
        requirements = [arg for path in suite["requirements"] for arg in ("-r", str(ROOT / path))]
        subprocess.run([sys.executable, "-m", "pip", "install", *requirements], check=True)
        subprocess.run([sys.executable, "-m", "pip", "check"], check=True)
        return
    env = dict(os.environ)
    paths = [str(ROOT)]
    if args.suite == "etl":
        paths.append(str(ROOT / "etl-final"))
    env["PYTHONPATH"] = os.pathsep.join(paths)
    for command in suite["commands"]:
        print(f"[{args.suite}] python {' '.join(command)}", flush=True)
        subprocess.run([sys.executable, *command], cwd=ROOT / suite["cwd"], env=env, check=True)


if __name__ == "__main__":
    main()
