"""Disposable native ClickHouse TLS and hostname verification proof."""

import os
import logging
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from verify_foundation_c4_tls import _write_certificates

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "etl-final"))
sys.path.insert(0, str(ROOT))

from shared.connectors import connector_registry  # noqa: E402
from shared.security.destination_policy import DestinationPolicyError  # noqa: E402


CONTAINER = "biavora-c4-clickhouse-tls"
PORT = 19440
PASSWORD = "c4-clickhouse-disposable-only"
IMAGE = "clickhouse/clickhouse-server@sha256:0b2d7824347397b2ba6fcb216f0ae772568105f1f47e19f0d3247e24c79bc10a"


def main():
    logging.getLogger("clickhouse_driver.connection").setLevel(logging.CRITICAL)
    if os.getenv("BIAVORA_C4_DISPOSABLE") != "1":
        raise SystemExit("ClickHouse TLS proof requires BIAVORA_C4_DISPOSABLE=1.")
    existing = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"name=^{CONTAINER}$", "--format", "{{.Names}}"],
        capture_output=True, text=True, check=True,
    )
    if existing.stdout.strip():
        raise RuntimeError("Disposable ClickHouse TLS container name is already in use.")
    created = False
    with tempfile.TemporaryDirectory(prefix="biavora-c4-clickhouse-tls-") as temp:
        directory = Path(temp)
        _write_certificates(directory)
        (directory / "ssl.xml").write_text(
            "<clickhouse><tcp_port_secure>9440</tcp_port_secure><openSSL><server>"
            "<certificateFile>/fixture/server.crt</certificateFile>"
            "<privateKeyFile>/fixture/server.key</privateKeyFile>"
            "<verificationMode>none</verificationMode>"
            "</server></openSSL></clickhouse>",
            encoding="utf-8",
        )
        try:
            subprocess.run([
                "docker", "run", "--rm", "-d", "--name", CONTAINER,
                "-p", f"127.0.0.1:{PORT}:9440",
                "-v", f"{directory}:/fixture:ro",
                "-v", f"{directory / 'ssl.xml'}:/etc/clickhouse-server/config.d/c4-ssl.xml:ro",
                "-e", "CLICKHOUSE_DB=c4_tls",
                "-e", "CLICKHOUSE_USER=c4_reader",
                "-e", f"CLICKHOUSE_PASSWORD={PASSWORD}", IMAGE,
            ], check=True, stdout=subprocess.DEVNULL)
            created = True
            os.environ["APP_ENV"] = "production"
            os.environ["ETL_SOURCE_CLICKHOUSE_CA_FILE"] = str(directory / "ca.crt")
            config = {
                "host": "source.test", "port": PORT, "database": "c4_tls",
                "username": "c4_reader", "password": PASSWORD,
                "secure": True, "verify": True, "connect_timeout": 3,
                "read_timeout": 5, "resolved_host": "127.0.0.1",
            }
            connector = connector_registry.get("clickhouse")
            with patch("shared.security.transport.validate_destination", return_value=("127.0.0.1",)):
                for attempt in range(40):
                    try:
                        connection = connector.connect(config)
                        cursor = connection.cursor()
                        cursor.execute("SELECT 1")
                        assert cursor.fetchone()[0] == 1
                        connection.close()
                        break
                    except Exception:
                        if attempt == 39:
                            raise RuntimeError("Disposable ClickHouse TLS listener did not become ready.")
                        time.sleep(1)
                for bad in ({**config, "host": "wrong.test"},):
                    try:
                        connection = connector.connect(bad)
                        connection.cursor().execute("SELECT 1")
                    except Exception:
                        pass
                    else:
                        connection.close()
                        raise AssertionError("Wrong ClickHouse TLS hostname was accepted")
                os.environ["ETL_SOURCE_CLICKHOUSE_CA_FILE"] = str(directory / "unrelated-ca.crt")
                try:
                    connection = connector.connect(config)
                    connection.cursor().execute("SELECT 1")
                except Exception:
                    pass
                else:
                    connection.close()
                    raise AssertionError("Untrusted ClickHouse CA was accepted")
                try:
                    connector.connect({**config, "secure": False})
                except DestinationPolicyError:
                    pass
                else:
                    raise AssertionError("Production insecure ClickHouse mode was accepted")
            print("C4 ClickHouse TLS: trusted hostname/read PASS; wrong host, untrusted CA, insecure mode DENIED")
        finally:
            if created:
                subprocess.run(["docker", "stop", CONTAINER], check=True, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
