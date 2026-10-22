from types import SimpleNamespace
from unittest.mock import Mock, patch
import importlib
import os
from datetime import timedelta

from django.apps import apps
from django.db import connection
from django.test import TestCase
from django.test import override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from database.models import Database
from database.serializers import DatabaseSerializer
from database.views import DatabaseSnapshotStartView, DatabaseSourceDiscoveryView, DatabaseUploadView, DatasetListView
from .models import DataSource, SourceCredential, SourceExecution
from .views import SourceDetailView, SourcesView, SourceCredentialView, SourceReplacementView, SourceReplacementActionView
from .internal_views import ResolveSourceCredentialView


def principal(workspace_id=7):
    return SimpleNamespace(
        id=11, pk=11, role="manager", workspace_id=workspace_id,
        email="manager@example.test", name="Manager", is_authenticated=True,
    )


def request(method, url, user, payload=None):
    factory = APIRequestFactory()
    req = getattr(factory, method)(url, payload, format="json") if payload is not None else getattr(factory, method)(url)
    force_authenticate(req, user=user)
    return req


class IntegrationOwnershipTests(TestCase):
    def setUp(self):
        self.keys = patch.dict(os.environ, {"CREDENTIAL_SECRET_KEY": "test-key-with-at-least-thirty-two-characters", "CREDENTIAL_RESOLVER_API_KEY": "resolver-key-with-at-least-thirty-two-characters"})
        self.keys.start()
        self.addCleanup(self.keys.stop)

    def create_source(self):
        response = SourcesView.as_view()(request("post", "/database/sources/", principal(), {
            "name": "Sales", "engine": "postgresql",
            "connection_metadata": {"host": "db.example.test", "port": 5432, "database": "sales"},
            "selected_tables": [{"schema": "public", "name": "orders"}],
            "password": "private",
        }))
        self.assertEqual(response.status_code, 201)
        return DataSource.objects.get(pk=response.data["data"]["id"])

    def test_public_upload_failure_does_not_echo_upstream_diagnostics(self):
        factory = APIRequestFactory()
        uploaded = SimpleUploadedFile("safe.csv", b"name\nexample\n", content_type="text/csv")
        req = factory.post("/database/upload/", {"file": uploaded}, format="multipart")
        force_authenticate(req, user=principal())
        upstream = Mock(status_code=500, headers={"Content-Type": "application/json"})
        upstream.json.return_value = {"message": "internal-host synthetic-secret-marker"}
        with patch("database.views.validate_upload"), patch("database.views.requests.post", return_value=upstream):
            response = DatabaseUploadView.as_view()(req)
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("internal-host", str(response.data))
        self.assertNotIn("synthetic-secret-marker", str(response.data))
        self.assertNotIn("synthetic-secret-marker", Database.objects.latest("pk").etl_message)

    def test_workspace_crud_and_secret_rejection(self):
        source = self.create_source()
        self.assertEqual(DataSource.objects.count(), 1)
        foreign = principal(8)
        self.assertEqual(SourcesView.as_view()(request("get", "/database/sources/", foreign)).data["data"], [])
        detail = SourceDetailView.as_view()
        for method in ("get", "patch", "delete"):
            response = detail(request(method, f"/database/sources/{source.pk}/", foreign,
                                      {"state": "disabled"} if method == "patch" else None), source_id=source.pk)
            self.assertEqual(response.status_code, 404)
        secret = SourcesView.as_view()(request("post", "/database/sources/", principal(), {
            "name": "bad", "engine": "postgresql", "connection_metadata": {"password": "must-not-store"},
        }))
        self.assertEqual(secret.status_code, 400)
        self.assertEqual(DataSource.objects.count(), 1)
        self.assertNotIn("password", str(SourcesView.as_view()(request("get", "/database/sources/", principal())).data))
        disabled = detail(request("patch", f"/database/sources/{source.pk}/", principal(), {"state": "disabled"}), source_id=source.pk)
        self.assertEqual(disabled.status_code, 200)
        self.assertEqual(DataSource.objects.get(pk=source.pk).state, "disabled")
        enabled = detail(request("patch", f"/database/sources/{source.pk}/", principal(), {"state": "active"}), source_id=source.pk)
        self.assertEqual(enabled.status_code, 200)

    def test_source_and_dataset_lifecycle_are_separate(self):
        source = self.create_source()
        old = Database.objects.create(
            manager=11, workspace_id=7, filename="old.csv", file_size=2, file_path="",
            source_kind="file", etl_status="completed", clickhouse_table_name="old_table",
        )
        payload = {
            "source_id": str(source.pk), "engine": "postgresql",
            "configuration": {},
            "tables": [{"schema": "public", "name": "orders"}],
        }
        upstream = Mock(status_code=202)
        upstream.json.return_value = {"success": True}
        with patch("database.views.requests.post", return_value=upstream) as post:
            result = DatabaseSnapshotStartView.as_view()(request("post", "/database/sources/snapshot/", principal(), payload))
        self.assertEqual(result.status_code, 202)
        self.assertEqual(Database.objects.count(), 2)
        self.assertTrue(Database.objects.filter(pk=old.pk).exists())
        dataset = Database.objects.get(source=source)
        self.assertNotEqual(str(dataset.pk), str(source.pk))
        self.assertEqual(dataset.workspace_id, source.workspace_id)
        self.assertNotIn("configuration", post.call_args.kwargs["json"])
        self.assertEqual(post.call_args.kwargs["json"]["credential_ref"]["source_id"], str(source.pk))
        self.assertEqual(post.call_args.kwargs["json"]["integration_source_id"], str(source.pk))
        self.assertNotIn("private", str(source.connection_metadata))
        dataset.etl_message = "Driver failed at physical_private_table in clickhouse_private_db"
        dataset.save(update_fields=["etl_message"])
        serialized = DatabaseSerializer(dataset).data
        self.assertEqual(str(serialized["source_id"]), str(source.pk))
        self.assertNotIn("clickhouse_table_name", serialized)
        self.assertNotIn("clickhouse_database", serialized)
        self.assertNotIn("password", str(serialized))
        self.assertNotIn("physical_private_table", str(serialized))
        self.assertNotIn("clickhouse_private_db", str(serialized))

        retired = SourceDetailView.as_view()(request("delete", f"/database/sources/{source.pk}/", principal()), source_id=source.pk)
        self.assertEqual(retired.status_code, 200)
        self.assertTrue(Database.objects.filter(pk=dataset.pk).exists())
        denied = DatabaseSnapshotStartView.as_view()(request("post", "/database/sources/snapshot/", principal(), payload))
        self.assertEqual(denied.status_code, 404)

    def test_cross_workspace_probe_and_snapshot_do_not_reach_connector(self):
        source = self.create_source()
        payload = {"source_id": str(source.pk), "engine": "postgresql", "configuration": {},
                   "tables": [{"name": "orders"}]}
        with patch("database.views.requests.post") as post:
            discovery = DatabaseSourceDiscoveryView.as_view()(request("post", "/database/sources/discover/", principal(8), payload))
            snapshot = DatabaseSnapshotStartView.as_view()(request("post", "/database/sources/snapshot/", principal(8), payload))
        self.assertEqual(discovery.status_code, 404)
        self.assertEqual(snapshot.status_code, 404)
        post.assert_not_called()
        self.assertEqual(Database.objects.count(), 0)

    def test_credentials_are_encrypted_and_never_public(self):
        source = self.create_source()
        credential = SourceCredential.objects.get(source=source)
        self.assertNotIn("private", credential.ciphertext)
        public = SourceDetailView.as_view()(request("get", f"/database/sources/{source.pk}/", principal()), source_id=source.pk)
        self.assertTrue(public.data["data"]["credential_configured"])
        self.assertNotIn("private", str(public.data))
        self.assertNotIn("ciphertext", str(public.data))
        self.assertNotIn("credential_id", str(public.data))
        self.assertEqual(str(credential), "Source credential")

    @override_settings(CREDENTIAL_RESOLVER_API_KEY="resolver-key-with-at-least-thirty-two-characters")
    def test_internal_resolution_requires_exact_scope_and_service(self):
        from .credentials import authorize_execution, execution_reference, resolve_execution, CredentialUnavailable
        import uuid
        source = self.create_source()
        grant = authorize_execution(source, job_id=uuid.uuid4(), dataset_id="31", kind="snapshot")
        payload = execution_reference(grant)
        factory = APIRequestFactory()
        def resolve(body, service="etl-connector", key="resolver-key-with-at-least-thirty-two-characters"):
            req = factory.post("/internal/v1/source-credentials/resolve/", body, format="json",
                               HTTP_X_INTERNAL_SERVICE=service, HTTP_X_CREDENTIAL_RESOLVER_KEY=key)
            return ResolveSourceCredentialView.as_view()(req)
        allowed = resolve(payload)
        self.assertEqual(allowed.status_code, 200)
        self.assertNotIn("private", str(allowed.data))
        self.assertIn("ciphertext", allowed.data["data"])
        self.assertEqual(resolve({**payload, "workspace_id": 8}).status_code, 403)
        self.assertEqual(resolve({**payload, "source_id": str(uuid.uuid4())}).status_code, 403)
        self.assertEqual(resolve(payload, service="ai-service").status_code, 403)
        self.assertEqual(resolve(payload, key="wrong").status_code, 403)
        probe = authorize_execution(source, job_id=uuid.uuid4(), dataset_id="probe-1", kind="test")
        self.assertEqual(resolve(execution_reference(probe), service="etl-extractor").status_code, 403)

    @override_settings(
        APP_ENV="production",
        CREDENTIAL_RESOLVER_CONNECTOR_KEY="connector-key-with-at-least-thirty-two-characters",
        CREDENTIAL_RESOLVER_EXTRACTOR_KEY="extractor-key-with-at-least-thirty-two-characters",
        CREDENTIAL_RESOLVER_CONNECTOR_KEY_PREVIOUS="previous-connector-key-with-thirty-two-characters",
        CREDENTIAL_RESOLVER_EXTRACTOR_KEY_PREVIOUS="previous-extractor-key-with-thirty-two-characters",
        CREDENTIAL_RESOLVER_API_KEY="legacy-shared-key-with-at-least-thirty-two-characters",
    )
    def test_production_resolver_keys_are_service_scoped_and_rotatable(self):
        import uuid
        from .credentials import authorize_execution, execution_reference

        source = self.create_source()
        grant = authorize_execution(source, job_id=uuid.uuid4(), dataset_id="31", kind="snapshot")
        payload = execution_reference(grant)
        factory = APIRequestFactory()

        def resolve(service, key):
            req = factory.post(
                "/internal/v1/source-credentials/resolve/", payload, format="json",
                HTTP_X_INTERNAL_SERVICE=service, HTTP_X_CREDENTIAL_RESOLVER_KEY=key,
            )
            return ResolveSourceCredentialView.as_view()(req)

        self.assertEqual(resolve("etl-connector", "connector-key-with-at-least-thirty-two-characters").status_code, 200)
        self.assertEqual(resolve("etl-connector", "previous-connector-key-with-thirty-two-characters").status_code, 200)
        self.assertEqual(resolve("etl-extractor", "extractor-key-with-at-least-thirty-two-characters").status_code, 200)
        self.assertEqual(resolve("etl-extractor", "previous-extractor-key-with-thirty-two-characters").status_code, 200)
        self.assertEqual(resolve("etl-extractor", "connector-key-with-at-least-thirty-two-characters").status_code, 403)
        self.assertEqual(resolve("etl-connector", "legacy-shared-key-with-at-least-thirty-two-characters").status_code, 403)
        with override_settings(
            CREDENTIAL_RESOLVER_CONNECTOR_KEY_PREVIOUS="",
            CREDENTIAL_RESOLVER_EXTRACTOR_KEY_PREVIOUS="",
        ):
            self.assertEqual(resolve("etl-connector", "previous-connector-key-with-thirty-two-characters").status_code, 403)
            self.assertEqual(resolve("etl-extractor", "previous-extractor-key-with-thirty-two-characters").status_code, 403)
            self.assertEqual(resolve("etl-connector", "connector-key-with-at-least-thirty-two-characters").status_code, 200)
            self.assertEqual(resolve("etl-extractor", "extractor-key-with-at-least-thirty-two-characters").status_code, 200)

    def test_failed_rotation_preserves_old_and_revoke_blocks_new_grants(self):
        import uuid
        from .credentials import (
            CredentialUnavailable, authorize_execution, execution_reference, resolve_execution,
        )
        source = self.create_source()
        old = SourceCredential.objects.get(source=source)
        old_grant = authorize_execution(source, job_id=uuid.uuid4(), dataset_id="old-snapshot", kind="snapshot")
        with patch("integration.views._test_candidate", return_value=False):
            response = SourceCredentialView.as_view()(request("post", "/rotate/", principal(), {"password": "bad"}), source_id=source.pk, action="rotate")
        self.assertEqual(response.status_code, 400)
        old.refresh_from_db()
        self.assertEqual(old.state, SourceCredential.ACTIVE)
        with patch("integration.views._test_candidate", return_value=True):
            response = SourceCredentialView.as_view()(request("post", "/rotate/", principal(), {"password": "better"}), source_id=source.pk, action="rotate")
        self.assertEqual(response.status_code, 200)
        old.refresh_from_db()
        self.assertEqual(old.state, SourceCredential.SUPERSEDED)
        self.assertEqual(SourceCredential.objects.get(source=source, state=SourceCredential.ACTIVE).version, 3)
        self.assertEqual(SourceCredentialView.as_view()(request("post", "/revoke/", principal(), {}), source_id=source.pk, action="revoke").status_code, 200)
        old_ref = execution_reference(old_grant)
        with self.assertRaises(CredentialUnavailable):
            resolve_execution(
                workspace_id=7, source_id=source.pk, job_id=old_grant.job_id,
                dataset_id="old-snapshot", credential_id=old_grant.credential_id,
                version=old_ref["credential_version"],
            )
        self.assertFalse(SourceCredential.objects.filter(source=source).exclude(ciphertext="").exists())
        from .credentials import active_credential
        with self.assertRaises(CredentialUnavailable):
            active_credential(source)

    def test_existing_grant_keeps_its_version_after_rotation(self):
        from .credentials import CredentialUnavailable, authorize_execution, execution_reference, resolve_execution
        import uuid
        source = self.create_source()
        old_grant = authorize_execution(source, job_id=uuid.uuid4(), dataset_id="31", kind="snapshot")
        old_ref = execution_reference(old_grant)
        with patch("integration.views._test_candidate", return_value=True):
            rotated = SourceCredentialView.as_view()(request("post", "/rotate/", principal(), {"password": "new"}), source_id=source.pk, action="rotate")
        self.assertEqual(rotated.status_code, 200)
        new_grant = authorize_execution(source, job_id=uuid.uuid4(), dataset_id="32", kind="snapshot")
        self.assertNotEqual(old_grant.credential_id, new_grant.credential_id)
        self.assertEqual(resolve_execution(
            workspace_id=7, source_id=source.pk, job_id=old_grant.job_id,
            dataset_id="31", credential_id=old_grant.credential_id,
            version=old_ref["credential_version"],
        ).credential_id, old_grant.credential_id)
        with self.assertRaises(CredentialUnavailable):
            authorize_execution(source, job_id=uuid.uuid4(), dataset_id="33", kind="snapshot", credential=old_grant.credential)

    def test_malformed_ciphertext_fails_without_secret_diagnostic(self):
        from bi_platform_shared.credential_crypto import CredentialCryptoError, decrypt_credential
        with self.assertRaises(CredentialCryptoError) as caught:
            decrypt_credential("v1", "malformed-ciphertext")
        self.assertNotIn("malformed-ciphertext", str(caught.exception))

    def test_superseded_ciphertext_is_pruned_after_grants_expire(self):
        from .credentials import authorize_execution, prune_old_credentials
        import uuid
        source = self.create_source()
        old = SourceCredential.objects.get(source=source, state=SourceCredential.ACTIVE)
        grant = authorize_execution(source, job_id=uuid.uuid4(), dataset_id="31", kind="snapshot")
        with patch("integration.views._test_candidate", return_value=True):
            SourceCredentialView.as_view()(request("post", "/rotate/", principal(), {"password": "new"}), source_id=source.pk, action="rotate")
        old.deactivated_at = timezone.now() - timedelta(hours=25)
        old.save(update_fields=["deactivated_at"])
        self.assertEqual(prune_old_credentials(), 0)
        SourceExecution.objects.filter(pk=grant.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(prune_old_credentials(), 1)
        old.refresh_from_db()
        self.assertEqual(old.state, SourceCredential.REVOKED)
        self.assertEqual(old.ciphertext, "")

    def test_scheduled_prune_command_runs_and_writes_heartbeat(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from django.core.management import call_command
        from integration.management.commands import run_credential_prune_worker as worker

        with TemporaryDirectory() as directory, patch.object(worker, "HEARTBEAT", Path(directory) / "heartbeat"):
            call_command("run_credential_prune_worker", "--once", verbosity=0)
            self.assertTrue(worker.HEARTBEAT.exists())

    def test_source_network_admission_is_shared_and_workspace_scoped(self):
        from .limits import LIMITS_PER_MINUTE, admit_source_operation

        with patch.dict(LIMITS_PER_MINUTE, {"test": 2}):
            self.assertTrue(admit_source_operation(7, 11, "test"))
            self.assertTrue(admit_source_operation(7, 11, "test"))
            self.assertFalse(admit_source_operation(7, 11, "test"))
            self.assertTrue(admit_source_operation(8, 11, "test"))

    def test_replacement_requires_validated_snapshot_and_supports_rollback(self):
        source = self.create_source()
        old_credential = SourceCredential.objects.get(source=source, state=SourceCredential.ACTIVE)
        replacement = {
            "engine": "postgres", "connection_metadata": {
                "host": "new.example.test", "port": 5432, "database": "sales2", "username": "reader",
            }, "selected_tables": [{"schema": "public", "name": "orders"}], "password": "new-secret",
        }
        with patch("integration.views._test_candidate", return_value=False):
            bad = SourceReplacementView.as_view()(request("post", "/replacement/", principal(), replacement), source_id=source.pk)
        self.assertEqual(bad.status_code, 400)
        source.refresh_from_db()
        self.assertEqual(source.connection_metadata["host"], "db.example.test")
        with patch("integration.views._test_candidate", return_value=True):
            staged = SourceReplacementView.as_view()(request("post", "/replacement/", principal(), replacement), source_id=source.pk)
        self.assertEqual(staged.status_code, 201)
        candidate_id = staged.data["data"]["candidate_id"]
        discovery_upstream = Mock(status_code=200)
        discovery_upstream.json.return_value = {"success": True, "data": {"tables": [{"schema": "public", "name": "orders"}]}}
        with patch("integration.views.requests.post", return_value=discovery_upstream) as post:
            discovered = SourceReplacementActionView.as_view()(
                request("post", "/replacement/discover/", principal(), {}),
                source_id=source.pk, action="discover",
            )
        self.assertEqual(discovered.status_code, 200)
        self.assertEqual(discovered.data["data"]["tables"][0]["name"], "orders")
        self.assertEqual(post.call_args.kwargs["json"]["credential_ref"]["source_id"], str(source.pk))
        self.assertNotIn("password", str(post.call_args.kwargs["json"]))
        foreign_discovery = SourceReplacementActionView.as_view()(
            request("post", "/replacement/discover/", principal(8), {}),
            source_id=source.pk, action="discover",
        )
        self.assertEqual(foreign_discovery.status_code, 404)
        cutover = SourceReplacementActionView.as_view()(request("post", "/cutover/", principal(), {}), source_id=source.pk, action="cutover")
        self.assertEqual(cutover.status_code, 409)
        upstream = Mock(status_code=202)
        upstream.json.return_value = {"success": True}
        with patch("database.views.requests.post", return_value=upstream):
            queued = DatabaseSnapshotStartView.as_view()(request("post", "/database/sources/snapshot/", principal(), {
                "source_id": str(source.pk), "replacement_id": str(candidate_id), "configuration": {},
            }))
        self.assertEqual(queued.status_code, 202, queued.data)
        dataset = Database.objects.get(source=source)
        dataset.etl_status = "completed"
        dataset.save(update_fields=["etl_status"])
        cutover = SourceReplacementActionView.as_view()(request("post", "/cutover/", principal(), {}), source_id=source.pk, action="cutover")
        self.assertEqual(cutover.status_code, 200)
        source.refresh_from_db()
        old_credential.refresh_from_db()
        self.assertEqual(source.connection_metadata["host"], "new.example.test")
        self.assertEqual(source.configuration_version, 2)
        self.assertEqual(old_credential.state, SourceCredential.SUPERSEDED)
        self.assertTrue(Database.objects.filter(pk=dataset.pk).exists())
        rollback = SourceReplacementActionView.as_view()(request("post", "/rollback/", principal(), {}), source_id=source.pk, action="rollback")
        self.assertEqual(rollback.status_code, 200)
        source.refresh_from_db()
        self.assertEqual(source.connection_metadata["host"], "db.example.test")
        self.assertEqual(source.configuration_version, 3)

    def test_legacy_backfill_is_idempotent_and_preserves_dataset(self):
        legacy = Database.objects.create(
            manager=11, workspace_id=7, filename="postgresql:orders",
            file_size=0, file_path="", source_kind="database", source_engine="postgresql",
            source_tables=[{"schema": "public", "name": "orders", "destination_table": "private_table"}],
        )
        migrate = importlib.import_module("database.migrations.0006_dataset_source")
        editor = SimpleNamespace(connection=connection)
        migrate.backfill_sources(apps, editor)
        legacy.refresh_from_db()
        source_id = legacy.source_id
        self.assertIsNotNone(source_id)
        self.assertEqual(DataSource.objects.get(pk=source_id).selected_tables, [{"schema": "public", "name": "orders"}])
        Database.objects.filter(pk=legacy.pk).update(source=None)
        migrate.backfill_sources(apps, editor)
        legacy.refresh_from_db()
        self.assertEqual(legacy.source_id, source_id)
        self.assertEqual(DataSource.objects.count(), 1)

    def test_dataset_list_is_workspace_scoped(self):
        owned = Database.objects.create(manager=11, workspace_id=7, filename="owned.csv", file_size=1, file_path="")
        Database.objects.create(manager=11, workspace_id=8, filename="foreign.csv", file_size=1, file_path="")
        response = DatasetListView.as_view()(request("get", "/database/datasets/", principal()))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data["data"]], [owned.pk])
