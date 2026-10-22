"""Prove Django service connections use distinct critical-domain LOGIN roles.

Run only against a disposable database after all five domain migrations and
foundation_c4_owner_schemas.py apply. No application data is changed.
"""

import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

import psycopg2

from foundation_c4_owner_schemas import OWNERS, configure_runtime_roles


ROOT = Path(__file__).resolve().parents[1]
SERVICES = {
    "auth": "auth-service",
    "workspace": "workspace-service",
    "query": "query-service",
    "entitlement": "subscription-service",
}


def _probe(service, domain, env, *, alias="default"):
    own_table = OWNERS[domain][0]
    foreign_domain = "integration" if domain != "integration" else "query"
    foreign_table = OWNERS[foreign_domain][0]
    code = f"""
from django.db import connections
from psycopg2.errors import InsufficientPrivilege
c = connections[{alias!r}]
with c.cursor() as cursor:
    cursor.execute('SELECT current_user, current_schema()')
    assert cursor.fetchone() == ('biavora_{domain}_runtime', 'biavora_{domain}')
    cursor.execute('SELECT 1 FROM biavora_{domain}.{own_table} LIMIT 1')
    cursor.execute('SELECT 1 FROM public.django_migrations LIMIT 1')
    cursor.execute('INSERT INTO biavora_{domain}.{own_table} SELECT * FROM biavora_{domain}.{own_table} WHERE FALSE')
    cursor.execute('UPDATE biavora_{domain}.{own_table} SET id=id WHERE FALSE')
    cursor.execute('DELETE FROM biavora_{domain}.{own_table} WHERE FALSE')
    for statement in ('INSERT INTO biavora_{foreign_domain}.{foreign_table} SELECT * FROM biavora_{foreign_domain}.{foreign_table} WHERE FALSE', 'UPDATE biavora_{foreign_domain}.{foreign_table} SET id=id WHERE FALSE', 'DELETE FROM biavora_{foreign_domain}.{foreign_table} WHERE FALSE'):
        try:
            cursor.execute(statement)
        except Exception as exc:
            assert isinstance(exc.__cause__, InsufficientPrivilege), type(exc).__name__
            c.rollback()
        else:
            raise AssertionError('foreign owner mutation was allowed')
print('domain role PASS')
"""
    result = subprocess.run(
        [sys.executable, "manage.py", "shell", "-c", code],
        cwd=ROOT / "services" / service, env=env,
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode:
        raise RuntimeError(f"{service}/{alias} role probe failed:\n{result.stderr[-3000:]}")


def _probe_query_integration_flow(env):
    code = """
from integration.models import DataSource
from integration.credentials import configure_credential
from database.models import Database
source = DataSource.objects.create(
    workspace_id=7, created_by=11, name='disposable', engine='postgresql',
    connection_metadata={'host':'example.invalid'}, selected_tables=[],
)
credential = configure_credential(source.pk, 'synthetic-disposable-password')
assert credential.source_id == source.pk and credential.ciphertext
dataset = Database.objects.create(
    manager=11, workspace_id=7, filename='disposable', file_size=0,
    file_path='', source=source,
)
assert dataset.source_id == source.pk
dataset.delete()
source.state = DataSource.RETIRED
source.save(update_fields=['state'])
print('cross-alias source/dataset write PASS')
"""
    result = subprocess.run(
        [sys.executable, "manage.py", "shell", "-c", code],
        cwd=ROOT / "services" / "query-service", env=env,
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode:
        raise RuntimeError(f"Query/Integration flow failed:\n{result.stderr[-3000:]}")


def _probe_running_readiness(service, env):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    runtime_env = dict(env)
    runtime_env.update({"READINESS_TCP_TARGETS": "", "READINESS_HTTP_URLS": ""})
    server_code = (
        "from wsgiref.simple_server import make_server; "
        "from service_config.wsgi import application; "
        f"make_server('127.0.0.1', {port}, application).serve_forever()"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", server_code],
        cwd=ROOT / "services" / service, env=runtime_env,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    try:
        last_detail = ""
        for _ in range(40):
            if process.poll() is not None:
                detail = process.stderr.read().decode("utf-8", "replace")[-2000:]
                for name, value in runtime_env.items():
                    if ("KEY" in name or "PASSWORD" in name) and len(value) >= 8:
                        detail = detail.replace(value, "[REDACTED]")
                raise RuntimeError(f"{service} production-profile HTTP process exited early: {detail}")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/ready/", timeout=1) as response:
                    if response.status == 200:
                        return
            except urllib.error.HTTPError as exc:
                last_detail = exc.read().decode("utf-8", "replace")[-500:]
            except (OSError, TimeoutError) as exc:
                last_detail = f"{type(exc).__name__}: {exc}"
            time.sleep(0.25)
        process.terminate()
        detail = process.communicate(timeout=5)[1].decode("utf-8", "replace")[-4000:]
        for name, value in runtime_env.items():
            if ("KEY" in name or "PASSWORD" in name) and len(value) >= 8:
                detail = detail.replace(value, "[REDACTED]")
        raise RuntimeError(f"{service} production-profile readiness did not pass: {last_detail} {detail}")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def main():
    if os.getenv("BIAVORA_C5_DISPOSABLE") != "1":
        raise SystemExit("Service role probe requires BIAVORA_C5_DISPOSABLE=1.")
    required = ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD")
    if any(not os.getenv(name) for name in required):
        raise SystemExit("Disposable administrator connection is incomplete.")
    passwords = {domain: secrets.token_urlsafe(40) for domain in OWNERS}
    connection = psycopg2.connect(
        host=os.environ["DB_HOST"], port=os.getenv("DB_PORT", "5432"),
        dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )
    try:
        configure_runtime_roles(connection, passwords)
    finally:
        connection.close()
    base = dict(os.environ)
    base.update({
        "PYTHONPATH": str(ROOT), "APP_ENV": "production",
        "DJANGO_SECRET_KEY": secrets.token_urlsafe(40),
        "ALLOWED_HOSTS": "localhost,127.0.0.1",
        "DJANGO_ALLOWED_HOSTS": "localhost,127.0.0.1",
        "CREDENTIAL_SECRET_KEY": secrets.token_urlsafe(40),
        "CREDENTIAL_RESOLVER_CONNECTOR_KEY": secrets.token_urlsafe(40),
        "CREDENTIAL_RESOLVER_EXTRACTOR_KEY": secrets.token_urlsafe(40),
        "ETL_INTERNAL_API_KEY": secrets.token_urlsafe(40),
        "INGESTION_CALLBACK_API_KEY": secrets.token_urlsafe(40),
        "CLICKHOUSE_PASSWORD": secrets.token_urlsafe(40),
        "DB_ACCESS_MODE": "runtime",
    })
    for domain, service in SERVICES.items():
        env = dict(base)
        env["DB_USER"] = f"biavora_{domain}_runtime"
        env["DB_PASSWORD"] = passwords[domain]
        if domain == "query":
            env["INTEGRATION_DB_USER"] = "biavora_integration_runtime"
            env["INTEGRATION_DB_PASSWORD"] = passwords["integration"]
        _probe(service, domain, env)
        _probe_running_readiness(service, env)
        if domain == "query":
            _probe(service, "integration", env, alias="integration")
            _probe_query_integration_flow(env)
    print("C5 Django service credentials: all five domain roles and foreign write denials PASS")


if __name__ == "__main__":
    main()
