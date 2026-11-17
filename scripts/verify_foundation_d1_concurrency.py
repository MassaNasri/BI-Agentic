"""Verify duplicate CDC enable requests against disposable PostgreSQL only."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

if (os.getenv("BIAVORA_MIGRATION_DISPOSABLE") != "1"
        or not os.getenv("DB_NAME", "").startswith("foundation_d_migration")):
    raise SystemExit("Requires an explicitly disposable foundation_d_migration database.")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "service_config.settings")
os.environ["CDC_ENABLED"] = "1"
import django
django.setup()

from django.db import close_old_connections, connection  # noqa: E402
from rest_framework.test import APIRequestFactory, force_authenticate  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from database.models import Database  # noqa: E402
from integration.credentials import configure_credential  # noqa: E402
from integration.cdc import SourceCdcView  # noqa: E402
from integration.models import CdcAudit, CdcPipeline, DataSource  # noqa: E402

if connection.vendor != "postgresql":
    raise SystemExit("Concurrency verification requires PostgreSQL row locks.")

source = DataSource.objects.create(
    workspace_id=70001, created_by=70011, name="d1-concurrent-enable",
    engine="postgres", selected_tables=[{"schema": "public", "name": "orders"}],
)
configure_credential(source.pk, "disposable-d1-credential")
barrier = Barrier(2)


def enable():
    close_old_connections()
    user = SimpleNamespace(id=70011, pk=70011, role="manager", workspace_id=70001,
                           is_authenticated=True)
    request = APIRequestFactory().post("/database/sources/cdc/",
                                       {"schema": "public", "table": "orders"}, format="json")
    force_authenticate(request, user=user)
    barrier.wait(timeout=10)
    try:
        response = SourceCdcView.as_view()(request, source_id=source.pk, action="enable")
        return response.status_code, response.data
    finally:
        close_old_connections()


with ThreadPoolExecutor(max_workers=2) as pool:
    responses = list(pool.map(lambda _: enable(), range(2)))

assert [status for status, _ in responses] == [202, 202], responses
ids = {body["data"]["id"] for _, body in responses}
assert len(ids) == 1, responses
pipeline = CdcPipeline.objects.get(pk=ids.pop())
assert CdcPipeline.objects.filter(source=source).count() == 1
assert Database.objects.filter(source=source, source_kind="cdc").count() == 1
assert Database.objects.get(pk=pipeline.dataset_id).etl_status == "pending"
assert CdcAudit.objects.filter(pipeline=pipeline, action="enable").count() == 2
print("Foundation-D D1 concurrent duplicate enable: PASS; one pipeline, one pending Dataset, two accepted responses")
