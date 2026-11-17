"""Disposable PostgreSQL TLS/hostname proof using test-only certificates."""

import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import psycopg2
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "etl-final"))
sys.path.insert(0, str(ROOT))

from shared.connectors import connector_registry  # noqa: E402
from shared.security.destination_policy import DestinationPolicyError  # noqa: E402


CONTAINER = "biavora-c4-tls-disposable"
PORT = 55435
DATABASE = "biavora_c4_tls"
ADMIN_PASSWORD = "c4-disposable-admin-only"
READER_PASSWORD = "c4-disposable-reader-only"


def _certificate(subject, key, *, issuer=None, issuer_key=None, is_ca=False):
    now = datetime.now(timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)])
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(issuer or name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=is_ca, path_length=None), critical=True))
    if not is_ca:
        cert = cert.add_extension(x509.SubjectAlternativeName([x509.DNSName("source.test")]), critical=False)
    return cert.sign(issuer_key or key, hashes.SHA256())


def _write_certificates(directory):
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca = _certificate("BIAVORA disposable CA", ca_key, is_ca=True)
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server = _certificate("source.test", server_key, issuer=ca.subject, issuer_key=ca_key)
    unrelated_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    unrelated_ca = _certificate("Unrelated disposable CA", unrelated_key, is_ca=True)
    (directory / "ca.crt").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (directory / "unrelated-ca.crt").write_bytes(unrelated_ca.public_bytes(serialization.Encoding.PEM))
    (directory / "server.crt").write_bytes(server.public_bytes(serialization.Encoding.PEM))
    (directory / "server.key").write_bytes(server_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ))


def _connect(host, password, ca_file, *, user="postgres"):
    return psycopg2.connect(
        host=host, hostaddr="127.0.0.1", port=PORT, dbname=DATABASE,
        user=user, password=password, sslmode="verify-full", sslrootcert=str(ca_file),
        gssencmode="disable", connect_timeout=3,
    )


def main():
    if os.getenv("BIAVORA_C4_DISPOSABLE") != "1":
        raise SystemExit("TLS proof requires BIAVORA_C4_DISPOSABLE=1.")
    existing = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"name=^{CONTAINER}$", "--format", "{{.Names}}"],
        capture_output=True, text=True, check=True,
    )
    if existing.stdout.strip():
        raise RuntimeError("Disposable TLS container name is already in use.")
    created = False
    with tempfile.TemporaryDirectory(prefix="biavora-c4-tls-") as temp:
        directory = Path(temp)
        _write_certificates(directory)
        try:
            startup = (
                "cp /fixture/server.crt /tmp/server.crt && "
                "cp /fixture/server.key /tmp/server.key && "
                "chown postgres:postgres /tmp/server.crt /tmp/server.key && "
                "chmod 600 /tmp/server.key && "
                "exec docker-entrypoint.sh postgres -c ssl=on "
                "-c ssl_cert_file=/tmp/server.crt -c ssl_key_file=/tmp/server.key"
            )
            subprocess.run([
                "docker", "run", "--rm", "-d", "--name", CONTAINER,
                "-p", f"127.0.0.1:{PORT}:5432", "-v", f"{directory}:/fixture:ro",
                "-e", f"POSTGRES_DB={DATABASE}", "-e", f"POSTGRES_PASSWORD={ADMIN_PASSWORD}",
                "--entrypoint", "/bin/sh", "postgres:18.3", "-c", startup,
            ], check=True, stdout=subprocess.DEVNULL)
            created = True
            for attempt in range(30):
                try:
                    admin = _connect("source.test", ADMIN_PASSWORD, directory / "ca.crt")
                    break
                except psycopg2.OperationalError:
                    if attempt == 29:
                        raise RuntimeError("Disposable TLS PostgreSQL did not become ready.")
                    time.sleep(1)
            with admin:
                with admin.cursor() as cursor:
                    cursor.execute("CREATE TABLE c4_orders (id bigint PRIMARY KEY)")
                    cursor.execute("INSERT INTO c4_orders (id) VALUES (7)")
                    cursor.execute("CREATE ROLE c4_reader LOGIN PASSWORD %s", (READER_PASSWORD,))
                    cursor.execute("GRANT SELECT ON c4_orders TO c4_reader")
            admin.close()

            os.environ["APP_ENV"] = "production"
            os.environ["ETL_SOURCE_PG_CA_FILE"] = str(directory / "ca.crt")
            config = {
                "host": "source.test", "port": PORT, "database": DATABASE,
                "username": "c4_reader", "password": READER_PASSWORD,
                "sslmode": "verify-full", "connect_timeout": 3,
                "resolved_host": "127.0.0.1",
            }
            with patch("shared.security.transport.validate_destination", return_value=("127.0.0.1",)):
                connector = connector_registry.get("postgres")
                connection = connector.connect(config)
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT id FROM c4_orders")
                        assert cursor.fetchone()["id"] == 7
                        try:
                            cursor.execute("INSERT INTO c4_orders (id) VALUES (8)")
                        except psycopg2.errors.InsufficientPrivilege:
                            connection.rollback()
                        else:
                            raise AssertionError("Read-only source role accepted a write")
                finally:
                    connection.close()
                try:
                    connector.connect({**config, "host": "wrong.test"})
                except psycopg2.OperationalError:
                    pass
                else:
                    raise AssertionError("Wrong TLS hostname was accepted")
                os.environ["ETL_SOURCE_PG_CA_FILE"] = str(directory / "unrelated-ca.crt")
                try:
                    connector.connect(config)
                except psycopg2.OperationalError:
                    pass
                else:
                    raise AssertionError("Untrusted CA was accepted")
                try:
                    connector.connect({**config, "sslmode": "disable"})
                except DestinationPolicyError:
                    pass
                else:
                    raise AssertionError("Production non-TLS connection was accepted")
            print("C4 PostgreSQL TLS: trusted hostname/read PASS; wrong host, untrusted CA, insecure mode, source write DENIED")
        finally:
            if created:
                subprocess.run(["docker", "stop", CONTAINER], check=True, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
