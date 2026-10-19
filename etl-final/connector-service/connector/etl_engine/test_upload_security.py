import os
import sqlite3
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, Client, override_settings

from etl_engine.file_storage import (
    cleanup_expired_uploads, refresh_queued_sqlite_file, save_uploaded_file, save_sqlite_file,
)


class PrivateStorageTests(SimpleTestCase):
    def test_generated_workspace_name_and_expiry_cleanup(self):
        with TemporaryDirectory() as root, patch('etl_engine.file_storage.BASE_DIR', root):
            source = SimpleUploadedFile('report.csv', b'a,b\n1,2')
            path = Path(save_uploaded_file(source, 23))
            self.assertEqual(path.parent, Path(root) / '23')
            self.assertNotIn('report', path.name)
            self.assertEqual(path.read_bytes(), b'a,b\n1,2')
            old = time.time() - 90000
            os.utime(path, (old, old))
            self.assertEqual(cleanup_expired_uploads(), 1)
            self.assertFalse(path.exists())

    def test_workspace_paths_are_distinct(self):
        with TemporaryDirectory() as root, patch('etl_engine.file_storage.BASE_DIR', root):
            one = Path(save_uploaded_file(SimpleUploadedFile('x.csv', b'a\n1'), 1))
            two = Path(save_uploaded_file(SimpleUploadedFile('x.csv', b'a\n2'), 2))
            self.assertNotEqual(one.parent, two.parent)
            self.assertNotEqual(one.name, two.name)

    def test_cleanup_keeps_unrelated_root_and_workspace_files(self):
        with TemporaryDirectory() as root, patch('etl_engine.file_storage.BASE_DIR', root):
            workspace = Path(root) / '23'
            workspace.mkdir()
            unrelated = [Path(root) / 'notes.txt', workspace / 'notes.csv']
            for path in unrelated:
                path.write_bytes(b'keep')
                os.utime(path, (1, 1))
            self.assertEqual(cleanup_expired_uploads(), 0)
            self.assertTrue(all(path.exists() for path in unrelated))

    def test_generated_sqlite_token_expires_without_cross_workspace_deletion(self):
        with TemporaryDirectory() as root, patch('etl_engine.file_storage.BASE_DIR', root):
            source = SimpleUploadedFile('local.sqlite', b'SQLite format 3\x00' + b'0' * 100)
            token = save_sqlite_file(source, 23)
            path = Path(root) / token
            self.assertTrue(token.startswith('sqlite_23_'))
            if os.name != 'nt':
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            os.utime(path, (1, 1))
            self.assertEqual(cleanup_expired_uploads(retention_seconds=86400), 1)
            self.assertFalse(path.exists())

    def test_snapshot_dispatch_refreshes_nearly_expired_sqlite_only_for_owner(self):
        with TemporaryDirectory() as root, patch('etl_engine.file_storage.BASE_DIR', root):
            token = save_sqlite_file(
                SimpleUploadedFile('local.sqlite', b'SQLite format 3\x00' + b'0' * 100), 23,
            )
            path = Path(root) / token
            old = time.time() - 86390
            os.utime(path, (old, old))
            with self.assertRaises(ValueError):
                refresh_queued_sqlite_file(token, 24)
            self.assertLess(path.stat().st_mtime, time.time() - 86000)
            refresh_queued_sqlite_file(token, 23)
            self.assertGreater(path.stat().st_mtime, time.time() - 60)
            self.assertEqual(cleanup_expired_uploads(), 0)
            os.utime(path, (time.time() - 86401,) * 2)
            with self.assertRaises(ValueError):
                refresh_queued_sqlite_file(token, 23)


class SQLitePrepareEndpointTests(SimpleTestCase):
    def setUp(self):
        self.client = Client(
            HTTP_X_INTERNAL_SERVICE='query-service',
            HTTP_X_INTERNAL_API_KEY='upload-test-only-key',
            HTTP_X_WORKSPACE_ID='23',
            HTTP_X_DATASET_ID='dataset-23',
            HTTP_X_INGESTION_JOB_ID='7d429d28-e064-4d0f-b0bb-c6667a911b8f',
        )

    @override_settings(ETL_INTERNAL_API_KEY='upload-test-only-key')
    def test_valid_sqlite_prepare_is_private_and_workspace_scoped(self):
        with TemporaryDirectory() as root, patch('etl_engine.file_storage.BASE_DIR', root), \
                patch.dict(os.environ, {'ETL_SQLITE_ROOT': root}):
            source = Path(root) / 'source.sqlite'
            connection = sqlite3.connect(source)
            connection.execute('CREATE TABLE sample (id INTEGER PRIMARY KEY, name TEXT)')
            connection.commit()
            connection.close()
            uploaded = SimpleUploadedFile('source.sqlite', source.read_bytes())
            response = self.client.post('/api/databases/sqlite/prepare/', {'file': uploaded})
            self.assertEqual(response.status_code, 200)
            token = response.json()['data']['sqlite_token']
            self.assertTrue(token.startswith('sqlite_23_'))
            self.assertNotIn(root, response.content.decode())
            self.assertTrue((Path(root) / token).is_file())
            other = Client(
                HTTP_X_INTERNAL_SERVICE='query-service',
                HTTP_X_INTERNAL_API_KEY='upload-test-only-key',
                HTTP_X_WORKSPACE_ID='24',
                HTTP_X_DATASET_ID='dataset-24',
                HTTP_X_INGESTION_JOB_ID='7d429d28-e064-4d0f-b0bb-c6667a911b8f',
            )
            denied = other.post('/api/databases/test/', data='{"engine":"sqlite","configuration":{"sqlite_token":"' + token + '"}}', content_type='application/json')
            self.assertEqual(denied.status_code, 403)
            self.assertTrue((Path(root) / token).is_file())

    @override_settings(ETL_INTERNAL_API_KEY='upload-test-only-key')
    def test_failed_sqlite_discovery_removes_staging(self):
        with TemporaryDirectory() as root, patch('etl_engine.file_storage.BASE_DIR', root), \
                patch.dict(os.environ, {'ETL_SQLITE_ROOT': root}):
            uploaded = SimpleUploadedFile('broken.db', b'SQLite format 3\x00' + b'0' * 100)
            response = self.client.post('/api/databases/sqlite/prepare/', {'file': uploaded})
            self.assertEqual(response.status_code, 400)
            self.assertFalse(list(Path(root).glob('sqlite_*.db')))

