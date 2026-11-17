"""CDC route, lifecycle, and callback isolation against a real ORM schema."""
import os
import uuid
from datetime import timedelta
from unittest.mock import patch
from django.db import DatabaseError, IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory
from database.models import Database
from database.views import DatabaseDetailView
from database.cdc import CdcDatasetBindingError, create_live_dataset
from .cdc import SourceCdcView, InternalCdcView, pipeline_scope, public_pipeline
from .credentials import configure_credential
from .models import DataSource, SourceCredential, CdcPipeline, CdcGeneration, CdcAudit
from .views import SourceDetailView, SourceCredentialView, SourceReplacementActionView
from .tests import principal, request


class CdcBoundaryTests(TestCase):
    def setUp(self):
        keys = patch.dict(os.environ, {'APP_ENV':'test','CDC_ENABLED':'1',
            'CDC_RESEED_OPERATOR_KEY':'isolated-operator-key',
            'CREDENTIAL_SECRET_KEY':'cdc-unit-encryption-key-for-isolated-tests',
            'CDC_CONTROLLER_KEY':'controller-unit-identity','CDC_LOAD_KEY':'load-unit-identity',
            'CDC_NORMALIZE_KEY':'normalize-unit-identity','CDC_TRANSFORM_KEY':'transform-unit-identity'})
        keys.start()
        self.addCleanup(keys.stop)
        self.controller_owner = str(uuid.uuid4())
        self.source=DataSource.objects.create(workspace_id=7,created_by=11,name='orders',engine='postgres',
            selected_tables=[{'schema':'public','name':'orders'}])
        configure_credential(self.source.pk,'unit-secret-never-in-public-response')
        self.snapshot=Database.objects.create(manager=11,workspace_id=7,source=self.source,filename='snapshot',
            file_size=0,file_path='',etl_status='completed',clickhouse_table_name='immutable_snapshot')

    def enable(self):
        response=SourceCdcView.as_view()(request('post','/',principal(),{'schema':'public','table':'orders'}),source_id=self.source.pk,action='enable')
        self.assertEqual(response.status_code,202)
        return CdcPipeline.objects.get(pk=response.data['data']['id'])

    def action(self, p, action, source=None, person=None, extra=None):
        payload = {'pipeline_id': str(p.pk)}
        if extra:
            payload.update(extra)
        return SourceCdcView.as_view()(request('post','/',person or principal(),payload),
                                       source_id=(source or self.source).pk,action=action)

    def reseed_action(self, p, action='reseed', person=None, source=None, reason='operator_reseed', key=True):
        from rest_framework.test import force_authenticate
        body = {'pipeline_id': str(p.pk), 'intent': 'reseed', 'reason': reason} if action == 'reseed' else {
            'pipeline_id': str(p.pk), 'intent': 'abort_candidate'}
        req = APIRequestFactory().post('/', body, format='json', **(
            {'HTTP_X_CDC_OPERATOR_KEY': 'isolated-operator-key'} if key else {}))
        force_authenticate(req, user=person or principal())
        return SourceCdcView.as_view()(req, source_id=(source or self.source).pk, action=action)

    def ready_candidate(self, empty=False):
        from .cdc_reseed import scope_for_number
        p = self.enable()
        old = scope_for_number(p, 1)
        dataset = Database.objects.get(pk=p.dataset_id)
        dataset.etl_status = 'completed'
        dataset.cdc_generation = 1
        dataset.clickhouse_table_name = f'cdc_{old.token}_current'
        dataset.save(update_fields=['etl_status', 'cdc_generation', 'clickhouse_table_name'])
        self.assertEqual(self.reseed_action(p).status_code, 202)
        p.refresh_from_db()
        p.columns = [{'name': 'id', 'clickhouse_type': 'Int64'}]
        p.primary_key = ['id']
        p.checkpoints = {} if empty else {'load:0': {'partition': 0, 'offset': 5, 'lsn': 50}}
        p.snapshot_signal = {'status': 'COMPLETED', 'completed': empty}
        p.health = {'slot_active': True}
        p.capture_slot_seen = True
        p.capture_ready = True
        p.observed_state = 'STREAMING'
        p.save()
        return p, old

    def comparing_attempt(self, candidate, proof):
        attempt_id = str(uuid.uuid4())
        candidate.reconciliation_attempt = {
            'id': attempt_id, 'generation': candidate.number,
            'state': 'COMPARING', 'source_lsn': proof['source_lsn'],
            'stage_ends': proof['stage_ends']}
        candidate.save(update_fields=['reconciliation_attempt'])
        proof['attempt_id'] = attempt_id

    def test_reseed_is_server_owned_idempotent_and_isolated(self):
        from .cdc_reseed import scope_for_number
        p = self.enable()
        old = scope_for_number(p, 1)
        self.assertEqual(self.reseed_action(p, key=False).status_code, 403)
        self.assertEqual(self.reseed_action(p, person=principal(8)).status_code, 404)
        analyst = principal(); analyst.role = 'analyst'
        self.assertEqual(self.reseed_action(p, person=analyst).status_code, 403)
        first = self.reseed_action(p)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(self.reseed_action(p).status_code, 202)
        p.refresh_from_db()
        self.assertEqual(p.generation, 2)
        self.assertEqual(CdcGeneration.objects.filter(pipeline=p, state='CANDIDATE').count(), 1)
        self.assertEqual(Database.objects.filter(pk=p.dataset_id).count(), 1)
        self.assertNotEqual(old.token, scope_for_number(p, 2).token)
        self.assertEqual(self.callback(p, {'scope': old.__dict__, 'checkpoint': {
            'partition': 0, 'offset': 1, 'lsn': 1}}).status_code, 409)

    def test_candidate_snapshot_start_is_not_old_dataset_resnapshot(self):
        p = self.enable()
        Database.objects.filter(pk=p.dataset_id).update(etl_status='completed', cdc_generation=1)
        self.assertEqual(self.reseed_action(p).status_code, 202)
        p.refresh_from_db()
        self.assertEqual(self.callback(p, {'checkpoint': {
            'partition': 0, 'offset': 1, 'lsn': 1}}, stage='normalize').status_code, 200)
        self.assertEqual(self.callback(p, {'snapshot_notification': {
            'type': 'STARTED', 'offset': 0, 'partition': 0,
            'id': str(uuid.uuid4()), 'timestamp_ms': int(timezone.now().timestamp()*1000)}},
            stage='normalize').status_code, 200)
        p.refresh_from_db()
        self.assertNotEqual(p.observed_state, 'RESEED_REQUIRED')
        self.assertEqual(CdcGeneration.objects.get(pipeline=p, number=2).state, 'CANDIDATE')

    def test_empty_candidate_completion_does_not_rebind_old_query(self):
        p = self.enable()
        Database.objects.filter(pk=p.dataset_id).update(etl_status='completed', cdc_generation=1)
        self.assertEqual(self.reseed_action(p).status_code, 202)
        p.refresh_from_db()
        p.columns = [{'name': 'id', 'clickhouse_type': 'Int32'}]
        p.primary_key = ['id']
        p.save(update_fields=['columns', 'primary_key'])
        for index, kind, extra in [(1, 'STARTED', {}),
                                   (2, 'TABLE_SCAN_COMPLETED', {'empty': True}),
                                   (3, 'COMPLETED', {})]:
            result = self.callback(p, {'snapshot_notification': {
                'type': kind, 'offset': index, 'partition': 0,
                'id': str(uuid.uuid4()), 'timestamp_ms': int(timezone.now().timestamp()*1000),
                **extra}}, stage='normalize')
            self.assertEqual(result.status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.observed_state, 'STREAMING')
        self.assertEqual(Database.objects.get(pk=p.dataset_id).cdc_generation, 1)

    def test_restart_skipped_notification_preserves_completed_snapshot(self):
        from .cdc import _next_snapshot_signal
        completed = {'status': 'COMPLETED', 'offset': 7, 'completed': True,
                     'empty_scan': True, 'notification_id': str(uuid.uuid4())}
        signal = {'type': 'SKIPPED', 'offset': 8, 'partition': 0,
                  'id': str(uuid.uuid4()),
                  'timestamp_ms': int(timezone.now().timestamp() * 1000)}
        folded = _next_snapshot_signal(completed, signal)
        self.assertEqual(folded['status'], 'COMPLETED')
        self.assertTrue(folded['completed'])
        self.assertEqual(folded['offset'], 8)
        self.assertEqual(folded['notification_id'], completed['notification_id'])

    def test_candidate_constraint_abort_and_orphan_classification(self):
        from .cdc_reseed import classify_orphans
        p = self.enable()
        self.assertEqual(self.reseed_action(p).status_code, 202)
        p.refresh_from_db()
        with self.assertRaises(IntegrityError), transaction.atomic():
            CdcGeneration.objects.create(pipeline=p, number=3, state='CANDIDATE',
                workspace_id=p.workspace_id, source_id=p.source_id, dataset_id=p.dataset_id,
                table_schema=p.table_schema, table_name=p.table_name)
        self.assertEqual(self.reseed_action(p, action='abort').status_code, 202)
        self.assertEqual(self.reseed_action(p, action='abort').status_code, 202)
        self.assertEqual(CdcGeneration.objects.get(pipeline=p, number=2).state, 'FAILED')
        self.assertEqual(CdcGeneration.objects.get(pipeline=p, number=1).state, 'ACTIVE')
        self.assertEqual(classify_orphans(p), [{
            'code': 'CDC_FAILED_GENERATION_RETAINED',
            'repair': 'manual_operator_review'}])
        self.assertEqual(self.reseed_action(p).status_code, 202)
        p.refresh_from_db()
        self.assertEqual(p.generation, 3)
        self.assertEqual(CdcGeneration.objects.get(pipeline=p, number=3).previous_number, 1)
        CdcGeneration.objects.filter(pipeline=p, number=3).delete()
        self.assertEqual(classify_orphans(p)[0]['code'], 'CDC_GENERATION_MISSING')
        Database.objects.filter(pk=p.dataset_id).delete()
        self.assertIn('CDC_DATASET_MISSING', [item['code'] for item in classify_orphans(p)])

    @patch('integration.cdc_reseed.ClickHouseClient')
    def test_missing_candidate_storage_is_retryable_only_before_durable_progress(self, client):
        from .cdc_reseed import classify_orphans
        p, _ = self.ready_candidate()
        p.checkpoints = {}
        p.snapshot_signal = {}
        p.save(update_fields=['checkpoints', 'snapshot_signal'])
        client.return_value.execute_query.return_value = {'success': True, 'data': ''}
        findings = classify_orphans(p)
        self.assertIn({'code': 'CDC_CANDIDATE_STORAGE_MISSING',
                       'repair': 'recoverable_retry'}, findings)
        p.checkpoints = {'load:0': {'partition': 0, 'offset': 1, 'lsn': 1}}
        p.save(update_fields=['checkpoints'])
        findings = classify_orphans(p)
        self.assertIn({'code': 'CDC_CANDIDATE_STORAGE_MISSING',
                       'repair': 'manual_operator_review'}, findings)

    @patch('integration.cdc_reseed._assert_current_view_ready')
    @patch('database.cdc._assert_current_view_ready')
    def test_cutover_recovers_before_and_after_query_binding(self, query_proof, candidate_proof):
        from .cdc_reseed import issue_local_certificate, cutover_candidate, recover_pending_cutovers
        p, old = self.ready_candidate()
        issue_local_certificate(p.pk)
        with self.assertRaisesRegex(RuntimeError, 'BEFORE_QUERY'):
            cutover_candidate(p.pk, fault='before_query')
        dataset = Database.objects.get(pk=p.dataset_id)
        self.assertEqual(dataset.cdc_generation, 1)
        self.assertEqual(dataset.clickhouse_table_name, f'cdc_{old.token}_current')
        with self.assertRaisesRegex(RuntimeError, 'AFTER_QUERY'):
            cutover_candidate(p.pk, fault='after_query')
        self.assertEqual(Database.objects.get(pk=p.dataset_id).cdc_generation, 2)
        self.assertEqual(CdcGeneration.objects.get(pipeline=p, number=1).state, 'ACTIVE')
        from .cdc_reseed import classify_orphans
        self.assertIn('CDC_QUERY_BOUND_PENDING',
                      [finding['code'] for finding in classify_orphans(p)])
        recover_pending_cutovers()
        self.assertEqual(CdcGeneration.objects.get(pipeline=p, number=2).state, 'ACTIVE')
        self.assertEqual(CdcGeneration.objects.get(pipeline=p, number=1).state, 'SUPERSEDED')
        self.assertEqual(self.callback(p, {'scope': old.__dict__, 'checkpoint': {
            'partition': 0, 'offset': 2, 'lsn': 2}}).status_code, 409)

    @patch('integration.cdc_reseed._assert_current_view_ready')
    def test_retirement_and_revocation_block_candidate_certificate(self, candidate_proof):
        from .cdc_reseed import issue_local_certificate
        from bi_platform_shared.cdc_contract import CdcError
        p, _ = self.ready_candidate()
        with patch.dict(os.environ, {'APP_ENV': 'production',
                                     'CDC_D5_R1_LOCAL_CERTIFICATE': '1'}):
            with self.assertRaises(CdcError):
                issue_local_certificate(p.pk)
        DataSource.objects.filter(pk=self.source.pk).update(state=DataSource.RETIRED)
        internal = APIRequestFactory().get('/internal/v1/cdc/',
            HTTP_X_CDC_STAGE='controller', HTTP_X_CDC_KEY='controller-unit-identity')
        item = InternalCdcView.as_view()(internal).data['pipelines'][0]
        self.assertEqual(item['desired_state'], 'STOPPED')
        with self.assertRaises(CdcError):
            issue_local_certificate(p.pk)
        DataSource.objects.filter(pk=self.source.pk).update(state=DataSource.ACTIVE)
        SourceCredential.objects.filter(source=self.source, state='active').update(state='revoked')
        internal = APIRequestFactory().get('/internal/v1/cdc/',
            HTTP_X_CDC_STAGE='controller', HTTP_X_CDC_KEY='controller-unit-identity')
        item = InternalCdcView.as_view()(internal).data['pipelines'][0]
        self.assertEqual(item['desired_state'], 'STOPPED')
        self.assertNotIn('credential', item)
        with self.assertRaises(Exception):
            issue_local_certificate(p.pk)

    @patch('integration.cdc_reseed._assert_current_view_ready')
    @patch('database.cdc._assert_current_view_ready')
    def test_retire_or_revoke_after_ready_blocks_new_binding(self, query_proof, candidate_proof):
        from .cdc_reseed import issue_local_certificate, cutover_candidate
        p, _ = self.ready_candidate()
        issue_local_certificate(p.pk)
        DataSource.objects.filter(pk=self.source.pk).update(state=DataSource.RETIRED)
        with self.assertRaises(Exception):
            cutover_candidate(p.pk)
        self.assertEqual(Database.objects.get(pk=p.dataset_id).cdc_generation, 1)
        DataSource.objects.filter(pk=self.source.pk).update(state=DataSource.ACTIVE)
        SourceCredential.objects.filter(source=self.source, state='active').update(state='revoked')
        with self.assertRaises(Exception):
            cutover_candidate(p.pk)
        self.assertEqual(Database.objects.get(pk=p.dataset_id).cdc_generation, 1)

    @patch('integration.cdc_reseed._assert_current_view_ready')
    @patch('database.cdc._assert_current_view_ready')
    def test_post_bind_recovery_finalizes_after_source_retirement(self, query_proof, candidate_proof):
        from .cdc_reseed import issue_local_certificate, cutover_candidate, recover_pending_cutovers
        p, _ = self.ready_candidate()
        issue_local_certificate(p.pk)
        with self.assertRaisesRegex(RuntimeError, 'AFTER_QUERY'):
            cutover_candidate(p.pk, fault='after_query')
        DataSource.objects.filter(pk=self.source.pk).update(state=DataSource.RETIRED)
        recover_pending_cutovers()
        self.assertEqual(CdcGeneration.objects.get(pipeline=p, number=2).state, 'ACTIVE')
        self.assertEqual(CdcGeneration.objects.get(pipeline=p, number=1).state, 'SUPERSEDED')

    @patch('integration.cdc_reseed._assert_current_view_ready')
    @patch('database.cdc._assert_current_view_ready')
    def test_incompatible_schema_reseeds_with_fresh_catalog(self, query_proof, candidate_proof):
        from .cdc_reseed import issue_local_certificate, cutover_candidate
        p = self.enable()
        self.assertEqual(self.callback(p, {'error_code': 'CDC_SCHEMA_INCOMPATIBLE'}).status_code, 200)
        self.assertEqual(CdcGeneration.objects.get(pipeline=p, number=1).state, 'RESEED_REQUIRED')
        self.assertEqual(self.reseed_action(p, reason='schema_incompatible').status_code, 202)
        p.refresh_from_db()
        p.columns = [{'name': 'id', 'clickhouse_type': 'Int64'},
                     {'name': 'replacement', 'clickhouse_type': 'String'}]
        p.primary_key = ['id']
        p.checkpoints = {'load:0': {'partition': 0, 'offset': 3, 'lsn': 90}}
        p.snapshot_signal = {'status': 'COMPLETED', 'completed': False}
        p.health = {'slot_active': True}
        p.capture_slot_seen = True
        p.capture_ready = True
        p.observed_state = 'STREAMING'
        p.save()
        issue_local_certificate(p.pk)
        cutover_candidate(p.pk)
        dataset = Database.objects.get(pk=p.dataset_id)
        self.assertEqual(dataset.cdc_generation, 2)
        self.assertEqual(dataset.columns_schema['replacement'], 'String')

    @patch('integration.cdc_reseed._assert_current_view_ready')
    @patch('database.cdc._assert_current_view_ready')
    def test_empty_candidate_can_bind_zero_row_view(self, query_proof, candidate_proof):
        from .cdc_reseed import issue_local_certificate, cutover_candidate
        p, _ = self.ready_candidate(empty=True)
        issue_local_certificate(p.pk)
        cutover_candidate(p.pk)
        self.assertEqual(Database.objects.get(pk=p.dataset_id).cdc_generation, 2)

    @patch('integration.cdc_reseed._assert_current_view_ready')
    @patch('database.cdc._assert_current_view_ready')
    def test_watermark_certificate_gates_cutover_and_invalidates_on_change(self, query_proof, candidate_proof):
        from .cdc_reseed import (issue_local_certificate, issue_watermark_certificate,
                                 cutover_candidate, scope_for_number, _certificate_valid)
        from bi_platform_shared.cdc_contract import CdcError
        p, _ = self.ready_candidate()
        candidate = CdcGeneration.objects.get(pipeline=p, number=2)
        scope = scope_for_number(p, 2)
        with self.assertRaises(CdcError):
            cutover_candidate(p.pk)
        issue_local_certificate(p.pk)
        candidate.refresh_from_db()
        with patch.dict(os.environ, {'APP_ENV': 'production'}):
            self.assertFalse(_certificate_valid(p, candidate, scope))
        proof = {'source_lsn': 50, 'capture_lsn': 60,
                 'stage_ends': {'normalize': {'0': 0}, 'transform': {'0': 0},
                                'load': {'0': 6}},
                 'checkpoints': p.checkpoints, 'source_count': 1, 'query_count': 1,
                 'chunk_count': 1, 'mismatch_chunks': [],
                 'duration_ms': 10, 'query_duration_ms': 2}
        self.comparing_attempt(candidate, proof)
        issue_watermark_certificate(p, candidate, scope, proof)
        with patch.dict(os.environ, {'APP_ENV': 'production'}):
            self.assertTrue(_certificate_valid(p, candidate, scope))
        cutover_candidate(p.pk)
        self.assertEqual(Database.objects.get(pk=p.dataset_id).cdc_generation, 2)
        self.assertEqual(CdcGeneration.objects.get(pipeline=p, number=1).state, 'SUPERSEDED')

    @patch('integration.cdc_reseed._assert_current_view_ready')
    def test_post_bind_recovery_does_not_waive_certificate_expiry_or_checkpoint(self, candidate_proof):
        from .cdc_reseed import issue_watermark_certificate, scope_for_number, _certificate_valid
        p, _ = self.ready_candidate()
        candidate = CdcGeneration.objects.get(pipeline=p, number=2)
        scope = scope_for_number(p, 2)
        proof = {'source_lsn': 50, 'capture_lsn': 60,
                 'stage_ends': {'normalize': {'0': 0}, 'transform': {'0': 0},
                                'load': {'0': 6}},
                 'checkpoints': p.checkpoints, 'source_count': 1, 'query_count': 1,
                 'chunk_count': 1, 'mismatch_chunks': [],
                 'duration_ms': 10, 'query_duration_ms': 2}
        self.comparing_attempt(candidate, proof)
        issue_watermark_certificate(p, candidate, scope, proof)
        candidate.refresh_from_db()
        self.assertTrue(_certificate_valid(p, candidate, scope, already_bound=True))
        p.checkpoints = {'load:0': {'partition': 0, 'offset': 7, 'lsn': 51}}
        self.assertFalse(_certificate_valid(p, candidate, scope, already_bound=True))
        p.refresh_from_db()
        candidate.validation_certificate['issued_at'] = (
            timezone.now() - timedelta(seconds=61)).isoformat()
        self.assertFalse(_certificate_valid(p, candidate, scope, already_bound=True))

    @patch('integration.cdc_reseed._assert_current_view_ready')
    def test_watermark_mismatch_and_stale_checkpoint_fail_closed(self, candidate_proof):
        from .cdc_reseed import issue_watermark_certificate, cutover_candidate, scope_for_number
        from bi_platform_shared.cdc_contract import CdcError
        p, _ = self.ready_candidate()
        candidate = CdcGeneration.objects.get(pipeline=p, number=2)
        scope = scope_for_number(p, 2)
        proof = {'source_lsn': 50, 'capture_lsn': 60,
                 'stage_ends': {'normalize': {'0': 0}, 'transform': {'0': 0},
                                'load': {'0': 6}},
                 'checkpoints': p.checkpoints, 'source_count': 1, 'query_count': 1,
                 'chunk_count': 1, 'mismatch_chunks': [0],
                 'duration_ms': 10, 'query_duration_ms': 2}
        self.comparing_attempt(candidate, proof)
        issue_watermark_certificate(p, candidate, scope, proof)
        with self.assertRaises(CdcError):
            cutover_candidate(p.pk)
        self.assertEqual(Database.objects.get(pk=p.dataset_id).cdc_generation, 1)
        proof['mismatch_chunks'] = []
        self.comparing_attempt(candidate, proof)
        issue_watermark_certificate(p, candidate, scope, proof)
        self.assertEqual(self.callback(p, {'checkpoint': {
            'partition': 0, 'offset': 6, 'lsn': 51}}).status_code, 200)
        with self.assertRaises(CdcError):
            cutover_candidate(p.pk)
        self.assertEqual(Database.objects.get(pk=p.dataset_id).cdc_generation, 1)

    @patch('integration.cdc_reseed._assert_current_view_ready')
    def test_watermark_issuer_rejects_checkpoint_movement_during_digest(self, candidate_proof):
        from .cdc_reseed import issue_watermark_certificate, scope_for_number
        from bi_platform_shared.cdc_contract import CdcError
        p, _ = self.ready_candidate()
        candidate = CdcGeneration.objects.get(pipeline=p, number=2)
        scope = scope_for_number(p, 2)
        proof = {'source_lsn': 50, 'capture_lsn': 60,
                 'stage_ends': {'normalize': {'0': 0}, 'transform': {'0': 0},
                                'load': {'0': 6}},
                 'checkpoints': p.checkpoints.copy(), 'source_count': 1,
                 'query_count': 1, 'chunk_count': 1, 'mismatch_chunks': [],
                 'duration_ms': 10, 'query_duration_ms': 2}
        self.comparing_attempt(candidate, proof)
        p.checkpoints = {'load:0': {'partition': 0, 'offset': 6, 'lsn': 51}}
        with self.assertRaises(CdcError) as caught:
            issue_watermark_certificate(p, candidate, scope, proof)
        self.assertEqual(caught.exception.code, 'CDC_RECONCILIATION_CHECKPOINT_MOVED')

    def test_foreign_workspace_cannot_request_reconciliation(self):
        p = self.enable()
        response = self.action(p, 'reconcile', person=principal(8))
        self.assertEqual(response.status_code, 404)
        p.refresh_from_db()
        self.assertFalse(p.reconcile_requested)

    def test_candidate_attempt_survives_controller_restart_and_fails_explicitly(self):
        p, _ = self.ready_candidate()
        self.assertEqual(self.action(p, 'reconcile').status_code, 202)
        candidate = CdcGeneration.objects.get(pipeline=p, number=2)
        attempt_id = candidate.reconciliation_attempt['id']
        self.assertEqual(candidate.reconciliation_attempt['state'], 'REQUESTED')
        progress = {'action': 'reconciliation_progress', 'attempt_id': attempt_id,
                    'state': 'SOURCE_SNAPSHOT_OPEN', 'source_lsn': 0,
                    'stage_ends': {}, 'failure_code': ''}
        self.assertEqual(self.callback(p, progress, stage='controller').status_code, 200)
        candidate.refresh_from_db()
        self.assertEqual(candidate.reconciliation_attempt['state'], 'SOURCE_SNAPSHOT_OPEN')
        progress.update(state='FAILED', failure_code='CDC_RECONCILIATION_INTERRUPTED')
        self.assertEqual(self.callback(p, progress, stage='controller').status_code, 200)
        candidate.refresh_from_db()
        p.refresh_from_db()
        self.assertEqual(candidate.reconciliation_attempt['failure_code'],
                         'CDC_RECONCILIATION_INTERRUPTED')
        self.assertFalse(p.reconcile_requested)
        self.assertFalse(candidate.validation_certificate)

    def test_live_dataset_is_distinct_and_enable_is_idempotent(self):
        first=self.enable()
        self.assertEqual(first.pk,self.enable().pk)
        self.assertNotEqual(first.dataset_id,self.snapshot.pk)
        self.snapshot.refresh_from_db()
        self.assertEqual(self.snapshot.clickhouse_table_name,'immutable_snapshot')
        self.assertEqual(Database.objects.get(pk=first.dataset_id).source_kind,'cdc')

    def test_foreign_workspace_and_non_manager_denied(self):
        for person,status in [(principal(8),404),(principal(),403)]:
            if status == 403:
                person.role='analyst'
            response=SourceCdcView.as_view()(request('get','/',person),source_id=self.source.pk)
            self.assertEqual(response.status_code,status)

    def test_arbitrary_connector_configuration_denied(self):
        for key in ('connector.class', 'snapshot.select.statement.overrides.public.orders'):
            response=SourceCdcView.as_view()(request('post','/',principal(),
                {'schema':'public','table':'orders',key:'arbitrary'}),
                source_id=self.source.pk,action='enable')
            self.assertEqual(response.status_code,400)
        self.assertFalse(CdcPipeline.objects.exists())

    def test_reseed_does_not_accept_snapshot_sql(self):
        from rest_framework.test import force_authenticate
        p = self.enable()
        body = {'pipeline_id': str(p.pk), 'intent': 'reseed',
                'reason': 'operator_reseed',
                'snapshot.select.statement.overrides.public.orders': 'SELECT 1'}
        req = APIRequestFactory().post('/', body, format='json',
                                       HTTP_X_CDC_OPERATOR_KEY='isolated-operator-key')
        force_authenticate(req, user=principal())
        response = SourceCdcView.as_view()(req, source_id=self.source.pk, action='reseed')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(CdcGeneration.objects.filter(pipeline=p, number=2).exists())

    def test_callback_rejects_public_jwt_and_wrong_stage_secret(self):
        for headers in ({},{'HTTP_X_CDC_STAGE':'load','HTTP_X_CDC_KEY':'controller-unit-identity'}):
            req=APIRequestFactory().get('/internal/v1/cdc/',**headers)
            self.assertIn(InternalCdcView.as_view()(req).status_code,(401,403))

    def callback(self,p,body,stage='load'):
        payload={'pipeline_id':str(p.pk),'scope':pipeline_scope(p).__dict__,**body}
        if stage == 'controller':
            claim = APIRequestFactory().post('/internal/v1/cdc/', {
                'action': 'claim', 'pipeline_id': str(p.pk), 'scope': payload['scope'],
                'owner': self.controller_owner}, format='json',
                HTTP_X_CDC_STAGE=stage, HTTP_X_CDC_KEY=f'{stage}-unit-identity')
            claim_response = InternalCdcView.as_view()(claim)
            if claim_response.status_code == 200:
                payload.update(lease_owner=self.controller_owner,
                               lease_fence=claim_response.data['fence'])
        req=APIRequestFactory().post('/internal/v1/cdc/',payload,format='json',
            HTTP_X_CDC_STAGE=stage,HTTP_X_CDC_KEY=f'{stage}-unit-identity')
        return InternalCdcView.as_view()(req)

    def test_callback_scope_and_stage_authority(self):
        p=self.enable()
        self.assertEqual(self.callback(p,{'scope':{**pipeline_scope(p).__dict__,'workspace_id':8}}).status_code,400)
        self.assertEqual(self.callback(p,{'columns':[]}).status_code,400)
        self.assertEqual(self.callback(p,{'health':{'password':'private'}}).status_code,400)

    def test_checkpoint_is_monotonic_and_persisted(self):
        p=self.enable()
        for offset,lsn in [(10,100),(8,80),(11,90)]:
            self.assertEqual(self.callback(p,{'checkpoint':{'offset':offset,'partition':0,'lsn':lsn}}).status_code,200)
        p.refresh_from_db()
        self.assertEqual(p.checkpoints['load:0'],{'offset':11,'partition':0,'lsn':100})

    def test_generation_lineage_is_persisted_and_stale_stage_callbacks_are_denied(self):
        p = self.enable()
        first_scope = pipeline_scope(p).__dict__
        first = CdcGeneration.objects.get(pipeline=p, number=1)
        self.assertEqual(first.state, 'ACTIVE')
        first.state = 'SUPERSEDED'
        first.save(update_fields=['state'])
        CdcGeneration.objects.create(
            pipeline=p, number=2, state='ACTIVE', previous_number=1,
            workspace_id=p.workspace_id, source_id=p.source_id,
            dataset_id=p.dataset_id, table_schema=p.table_schema, table_name=p.table_name)
        CdcPipeline.objects.filter(pk=p.pk).update(generation=2)
        before = Database.objects.get(pk=p.dataset_id).clickhouse_table_name
        for stage, body in (
            ('controller', {'observed_state': 'STREAMING', 'columns': [{'name': 'wrong'}]}),
            ('normalize', {'checkpoint': {'partition': 0, 'offset': 9, 'lsn': 9}}),
            ('transform', {'checkpoint': {'partition': 0, 'offset': 9, 'lsn': 9}}),
            ('load', {'checkpoint': {'partition': 0, 'offset': 9, 'lsn': 9},
                      'snapshot_complete': True}),
        ):
            response = self.callback(p, {'scope': first_scope, **body}, stage=stage)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.data['error']['code'], 'CDC_STALE_CALLBACK')
        p.refresh_from_db()
        self.assertEqual(p.generation, 2)
        self.assertEqual(p.checkpoints, {})
        self.assertEqual(p.columns, [])
        self.assertEqual(p.observed_state, 'PROVISIONING')
        self.assertEqual(Database.objects.get(pk=p.dataset_id).clickhouse_table_name, before)

    def test_failed_candidate_accepts_only_fenced_physical_stop_completion(self):
        p = self.enable()
        generation = CdcGeneration.objects.get(pipeline=p, number=1)
        generation.state = 'FAILED'
        generation.save(update_fields=['state'])
        CdcPipeline.objects.filter(pk=p.pk).update(
            desired_state='STOPPED', observed_state='STOPPING')
        p.refresh_from_db()
        self.assertEqual(self.callback(p, {'checkpoint': {
            'partition': 0, 'offset': 1, 'lsn': 1}}).status_code, 409)
        self.assertEqual(self.callback(p, {'observed_state': 'STOPPED',
            'columns': [{'name': 'wrong'}]}, stage='controller').status_code, 409)
        self.assertEqual(self.callback(p, {'observed_state': 'STOPPED'},
            stage='controller').status_code, 200)
        p.refresh_from_db()
        generation.refresh_from_db()
        self.assertEqual(p.observed_state, 'STOPPED')
        self.assertEqual(generation.state, 'FAILED')
        self.assertEqual(p.columns, [])

    def test_configuration_and_credential_epoch_fence_old_workers(self):
        p = self.enable()
        old_scope = pipeline_scope(p).__dict__
        self.assertEqual(self.callback(p, {'checkpoint': {
            'partition': 0, 'offset': 1, 'lsn': 1}}).status_code, 200)
        DataSource.objects.filter(pk=self.source.pk).update(configuration_version=2)
        p.refresh_from_db()
        response = self.callback(p, {'scope': old_scope, 'checkpoint': {
            'partition': 0, 'offset': 2, 'lsn': 2}})
        self.assertEqual((response.status_code, response.data['error']['code']),
                         (409, 'CDC_STALE_CALLBACK'))
        current_scope = pipeline_scope(p).__dict__
        SourceCredential.objects.filter(source=self.source, state='active').update(state='superseded')
        SourceCredential.objects.create(source=self.source, version=2, key_version='v1',
                                        ciphertext='opaque-test-value', state='active')
        response = self.callback(p, {'scope': current_scope, 'checkpoint': {
            'partition': 0, 'offset': 2, 'lsn': 2}})
        self.assertEqual((response.status_code, response.data['error']['code']),
                         (409, 'CDC_STALE_CALLBACK'))
        self.assertEqual(self.callback(p, {'checkpoint': {
            'partition': 0, 'offset': 2, 'lsn': 2}}).status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.checkpoints['load:0']['offset'], 2)

    def test_two_controllers_have_one_database_fenced_callback_authority(self):
        p = self.enable()
        scope = pipeline_scope(p).__dict__
        def post(body):
            req = APIRequestFactory().post('/internal/v1/cdc/', {
                'pipeline_id': str(p.pk), 'scope': scope, **body}, format='json',
                HTTP_X_CDC_STAGE='controller', HTTP_X_CDC_KEY='controller-unit-identity')
            return InternalCdcView.as_view()(req)
        owner_b = str(uuid.uuid4())
        first = post({'action': 'claim', 'owner': self.controller_owner})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(post({'action': 'verify', 'lease_owner': self.controller_owner,
                               'lease_fence': first.data['fence']}).status_code, 200)
        self.assertEqual(post({'action': 'claim', 'owner': owner_b}).status_code, 409)
        CdcPipeline.objects.filter(pk=p.pk).update(
            controller_lease_until=timezone.now() - timedelta(seconds=1))
        second = post({'action': 'claim', 'owner': owner_b})
        self.assertEqual(second.status_code, 200)
        self.assertGreater(second.data['fence'], first.data['fence'])
        self.assertEqual(post({'action': 'verify', 'lease_owner': self.controller_owner,
                               'lease_fence': first.data['fence']}).status_code, 409)
        self.assertEqual(post({'action': 'verify', 'lease_owner': owner_b,
                               'lease_fence': second.data['fence']}).status_code, 200)
        stale = post({'lease_owner': self.controller_owner,
                      'lease_fence': first.data['fence'], 'observed_state': 'SNAPSHOTTING'})
        self.assertEqual((stale.status_code, stale.data['error']['code']),
                         (409, 'CDC_STALE_CALLBACK'))
        self.assertEqual(post({'lease_owner': owner_b,
                               'lease_fence': second.data['fence'],
                               'observed_state': 'SNAPSHOTTING'}).status_code, 200)

    def test_empty_snapshot_signal_is_ordered_durable_and_publishes_without_row(self):
        p = self.enable()
        p.columns = [{'name': 'id', 'clickhouse_type': 'Int32'}]
        p.primary_key = ['id']
        p.save(update_fields=['columns', 'primary_key'])
        def signal(kind, offset, **extra):
            return {'type': kind, 'offset': offset, 'partition': 0,
                    'id': str(uuid.uuid4()), 'timestamp_ms': 1000 + offset, **extra}
        started = signal('STARTED', 1)
        scanned = signal('TABLE_SCAN_COMPLETED', 2, empty=True)
        completed = signal('COMPLETED', 3)
        with patch('database.cdc._assert_current_view_ready') as physical:
            for notification in (started, scanned):
                self.assertEqual(self.callback(p, {
                    'snapshot_notification': notification}, stage='normalize').status_code, 200)
                self.assertEqual(Database.objects.get(pk=p.dataset_id).etl_status, 'pending')
            self.assertEqual(self.callback(p, {
                'snapshot_notification': completed}, stage='normalize').status_code, 200)
            physical.assert_called_once()
        p.refresh_from_db()
        self.assertEqual(p.snapshot_signal['status'], 'COMPLETED')
        self.assertTrue(p.snapshot_signal['completed'])
        self.assertEqual(p.observed_state, 'STREAMING')
        self.assertEqual(Database.objects.get(pk=p.dataset_id).etl_status, 'completed')
        self.assertEqual(CdcGeneration.objects.get(pipeline=p, number=1).snapshot_signal,
                         p.snapshot_signal)
        self.assertEqual(self.callback(p, {'snapshot_notification': started},
                                       stage='normalize').status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.observed_state, 'STREAMING')
        self.assertEqual(self.callback(p, {'checkpoint': {
            'partition': 0, 'offset': 0, 'lsn': 42}}).status_code, 200)

    def test_unexpected_new_initial_snapshot_requires_reseed(self):
        p = self.enable()
        p.snapshot_signal = {'status': 'COMPLETED', 'offset': 5, 'completed': True}
        p.save(update_fields=['snapshot_signal'])
        signal = {'type': 'STARTED', 'offset': 6, 'partition': 0,
                  'id': str(uuid.uuid4()), 'timestamp_ms': 1006}
        self.assertEqual(self.callback(p, {'snapshot_notification': signal},
                                       stage='normalize').status_code, 200)
        p.refresh_from_db()
        self.assertEqual((p.observed_state, p.error_code),
                         ('RESEED_REQUIRED', 'CDC_UNEXPECTED_RESNAPSHOT'))

    def test_reseed_is_sticky_and_cannot_resume(self):
        p=self.enable()
        self.assertEqual(self.callback(p,{'error_code':'CDC_SCHEMA_INCOMPATIBLE'}).status_code,200)
        self.assertEqual(self.callback(p,{'observed_state':'PAUSED'},stage='controller').status_code,200)
        p.refresh_from_db()
        self.assertEqual(p.observed_state,'RESEED_REQUIRED')
        for action in ('pause', 'disable'):
            response=SourceCdcView.as_view()(request('post','/',principal(),{'pipeline_id':str(p.pk)}),source_id=self.source.pk,action=action)
            self.assertEqual(response.status_code,202)
            p.refresh_from_db()
            self.assertEqual(p.observed_state,'RESEED_REQUIRED')
        response=SourceCdcView.as_view()(request('post','/',principal(),{'pipeline_id':str(p.pk)}),source_id=self.source.pk,action='resume')
        self.assertEqual(response.status_code,409)

    def test_equal_version_conflict_is_sticky(self):
        p = self.enable()
        self.assertEqual(self.callback(p, {'error_code':'CDC_VERSION_CONFLICT'}).status_code, 200)
        p.refresh_from_db()
        self.assertEqual((p.desired_state,p.observed_state), ('PAUSED','RESEED_REQUIRED'))
        self.assertEqual(self.action(p,'resume').status_code,409)

    def test_legacy_storage_is_sticky(self):
        p = self.enable()
        self.assertEqual(self.callback(p, {'error_code':'CDC_STORAGE_INCOMPATIBLE'}).status_code, 200)
        p.refresh_from_db()
        self.assertEqual((p.desired_state,p.observed_state), ('PAUSED','RESEED_REQUIRED'))
        self.assertEqual(self.action(p,'resume').status_code,409)

    def test_transient_failure_can_pause_and_resume_without_offset_reset(self):
        p = self.enable()
        checkpoint = {'partition':0,'offset':12,'lsn':104}
        self.assertEqual(self.callback(p, {'checkpoint':checkpoint}).status_code, 200)
        self.assertEqual(self.callback(p, {'error_code':'CDC_TEMPORARY_FAILURE'}).status_code, 200)
        p.refresh_from_db()
        self.assertEqual((p.desired_state, p.observed_state), ('PAUSED', 'DEGRADED'))
        self.assertEqual(self.callback(p, {'observed_state':'PAUSED'}, stage='controller').status_code, 200)
        self.assertEqual(self.action(p, 'resume').status_code, 202)
        p.refresh_from_db()
        self.assertEqual(p.checkpoints['load:0'], checkpoint)

    def test_controller_health_cannot_publish_secrets(self):
        p=self.enable()
        self.assertEqual(self.callback(p,{'health':{'password':'private'}},stage='controller').status_code,400)
        self.assertEqual(self.callback(p,{'health':{'slot_active':True,'retained_wal_bytes':12,'wal_warning':False}},stage='controller').status_code,200)

    def test_stale_capture_is_not_reported_as_healthy_streaming(self):
        p=self.enable()
        p.observed_state='STREAMING'
        p.health={'capture_timestamp_ms':1}
        status=public_pipeline(p)
        self.assertEqual(status['observed_state'],'DEGRADED')
        self.assertEqual(status['error_code'],'CDC_CAPTURE_STALE')

    def test_public_status_has_no_private_configuration(self):
        self.enable()
        response=SourceCdcView.as_view()(request('get','/',principal()),source_id=self.source.pk)
        rendered=str(response.data)
        for forbidden in ('ciphertext','connector.class','credential_id','topic.prefix','unit-secret','password'):
            self.assertNotIn(forbidden,rendered)

    def test_snapshot_delete_route_cannot_destroy_live_storage(self):
        p=self.enable()
        with patch('database.views.cleanup_database') as cleanup:
            response=DatabaseDetailView.as_view()(request('delete',f'/?dataset_id={p.dataset_id}',principal()))
        self.assertEqual(response.status_code,409)
        cleanup.assert_not_called()

    def test_transition_matrix_and_idempotent_commands(self):
        p = self.enable()
        self.assertEqual(self.action(p, 'resume').status_code, 202)
        self.assertEqual(self.action(p, 'pause').status_code, 202)
        self.assertEqual(self.action(p, 'pause').status_code, 202)
        self.assertEqual(self.action(p, 'resume').status_code, 409)  # PAUSING is not ready.
        self.assertEqual(self.callback(p, {'observed_state': 'PAUSED'}, stage='controller').status_code, 200)
        self.assertEqual(self.action(p, 'resume').status_code, 202)
        self.assertEqual(self.action(p, 'resume').status_code, 202)
        self.assertEqual(self.action(p, 'disable').status_code, 202)
        self.assertEqual(self.action(p, 'disable').status_code, 202)
        self.assertEqual(self.action(p, 'pause').status_code, 409)
        self.assertEqual(self.callback(p, {'observed_state': 'STOPPED'}, stage='controller').status_code, 200)
        self.assertEqual(self.action(p, 'resume').status_code, 202)
        p.refresh_from_db()
        self.assertEqual((p.desired_state, p.observed_state), ('STREAMING', 'PROVISIONING'))
        self.assertEqual(CdcAudit.objects.filter(pipeline=p).count(), 9)
        self.assertEqual(CdcAudit.objects.filter(pipeline=p, result_code='CDC_IDEMPOTENT').count(), 4)

    def test_source_disable_and_retirement_stop_capture_without_deleting_dataset(self):
        p = self.enable()
        disabled = SourceDetailView.as_view()(request('patch','/',principal(),{'state':'disabled'}), source_id=self.source.pk)
        self.assertEqual(disabled.status_code, 200)
        self.assertEqual(disabled.data['data']['state'], 'disabled')
        p.refresh_from_db()
        self.assertEqual((p.desired_state, p.observed_state), ('STOPPED', 'STOPPING'))
        self.assertEqual(self.action(p, 'resume').status_code, 400)
        self.assertEqual(self.callback(p, {'snapshot_complete': True,
            'checkpoint': {'partition':0,'offset':0,'lsn':1}}).status_code, 409)
        self.assertEqual(self.callback(p, {'error_code':'CDC_SLOT_LOST'}, stage='controller').status_code, 409)
        self.assertTrue(Database.objects.filter(pk=p.dataset_id, etl_status='pending').exists())
        retired = SourceDetailView.as_view()(request('delete','/',principal()), source_id=self.source.pk)
        self.assertEqual(retired.status_code, 200)
        self.assertEqual(retired.data['data']['state'], 'retired')
        self.assertTrue(Database.objects.filter(pk=p.dataset_id).exists())
        self.assertEqual(CdcAudit.objects.filter(pipeline=p, action='source_disabled').count(), 1)

    def test_credential_revoke_stops_capture_and_replacement_requires_future_cutover(self):
        p = self.enable()
        blocked = SourceReplacementActionView.as_view()(
            request('post','/',principal(),{}), source_id=self.source.pk, action='cutover')
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.data['error']['code'], 'CDC_SOURCE_BOUND')
        revoked = SourceCredentialView.as_view()(
            request('post','/',principal(),{}), source_id=self.source.pk, action='revoke')
        self.assertEqual(revoked.status_code, 200)
        p.refresh_from_db()
        self.assertEqual((p.desired_state, p.observed_state), ('STOPPED', 'STOPPING'))
        self.assertEqual(self.action(p, 'resume').status_code, 400)
        self.assertEqual(self.enable_existing_response().status_code, 400)
        self.assertEqual(CdcAudit.objects.filter(pipeline=p, action='credential_revoked').count(), 1)

    def test_foreign_pipeline_and_wrong_dataset_binding_fail_closed(self):
        p = self.enable()
        other = DataSource.objects.create(workspace_id=7, created_by=11, name='other', engine='postgres',
            selected_tables=[{'schema':'public','name':'orders'}])
        self.assertEqual(self.action(p, 'pause', source=other).status_code, 404)
        self.assertEqual(self.action(p, 'pause', person=principal(8)).status_code, 404)
        viewer = principal()
        viewer.role = 'viewer'
        self.assertEqual(self.action(p, 'pause', person=viewer).status_code, 403)
        self.assertEqual(self.action(p, 'pause', extra={'topic':'physical'}).status_code, 400)
        Database.objects.filter(pk=p.dataset_id).update(workspace_id=8)
        self.assertEqual(self.action(p, 'pause').status_code, 409)
        self.assertEqual(self.enable_existing_response().status_code, 409)

    def enable_existing_response(self):
        return SourceCdcView.as_view()(request('post','/',principal(),
            {'schema':'public','table':'orders'}),source_id=self.source.pk,action='enable')

    def test_pending_dataset_is_reused_after_interrupted_enable(self):
        dataset, created = create_live_dataset(self.source, 11, 'public', 'orders')
        self.assertTrue(created)
        p = self.enable()
        self.assertEqual(p.dataset_id, dataset.pk)
        self.assertEqual(Database.objects.filter(source=self.source, source_kind='cdc').count(), 1)
        self.assertEqual(p.pk, self.enable().pk)

    def test_cross_store_creation_failure_has_no_query_ready_orphan(self):
        with patch('integration.cdc.create_live_dataset', side_effect=DatabaseError('unavailable')):
            response = self.enable_existing_response()
        self.assertEqual(response.status_code, 503)
        self.assertFalse(CdcPipeline.objects.exists())
        self.assertFalse(Database.objects.filter(source_kind='cdc').exists())
        with patch('integration.cdc.CdcPipeline.objects.create', side_effect=IntegrityError('duplicate')):
            response = self.enable_existing_response()
        self.assertEqual(response.status_code, 409)
        self.assertFalse(CdcPipeline.objects.exists())
        self.assertFalse(Database.objects.filter(source_kind='cdc').exists())
        self.assertEqual(self.enable_existing_response().status_code, 202)

    def test_dataset_created_then_reply_lost_rolls_back_on_single_alias(self):
        def interrupted(source, actor, schema, table):
            create_live_dataset(source, actor, schema, table)
            raise DatabaseError('reply lost')
        with patch('integration.cdc.create_live_dataset', side_effect=interrupted):
            self.assertEqual(self.enable_existing_response().status_code, 503)
        self.assertFalse(CdcPipeline.objects.exists())
        self.assertFalse(Database.objects.filter(source=self.source, source_kind='cdc').exists())
        self.assertEqual(self.enable_existing_response().status_code, 202)

    def test_existing_pipeline_missing_dataset_is_not_rebound(self):
        p = self.enable()
        Database.objects.filter(pk=p.dataset_id).delete()
        self.assertEqual(self.enable_existing_response().status_code, 409)
        self.assertEqual(self.action(p, 'pause').status_code, 409)
        self.assertFalse(Database.objects.filter(source_kind='cdc').exists())

    def test_resumed_candidate_uses_durable_loader_checkpoint(self):
        p, _ = self.ready_candidate()
        p.observed_state = 'PROVISIONING'
        p.save(update_fields=['observed_state'])
        response = self.callback(p, {'observed_state': 'STREAMING'}, stage='controller')
        self.assertEqual(response.status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.observed_state, 'STREAMING')

    def test_active_replacement_generation_can_request_same_generation_reconciliation(self):
        p, _ = self.ready_candidate()
        CdcGeneration.objects.filter(pipeline=p, number=1).update(state='SUPERSEDED')
        generation = CdcGeneration.objects.get(pipeline=p, number=2)
        generation.state = 'ACTIVE'
        generation.save(update_fields=['state'])
        self.assertEqual(self.action(p, 'reconcile').status_code, 202)
        p.refresh_from_db()
        generation.refresh_from_db()
        self.assertTrue(p.reconcile_requested)
        self.assertEqual(generation.reconciliation_attempt, {})

    def test_publication_needs_loader_checkpoint_and_retries_after_failure(self):
        p = self.enable()
        p.columns = [{'name':'id','clickhouse_type':'Int32'}]
        p.primary_key = ['id']
        p.save(update_fields=['columns','primary_key'])
        self.assertEqual(self.callback(p, {'observed_state':'STREAMING'}, stage='controller').status_code, 400)
        self.assertEqual(self.callback(p, {'snapshot_complete':True}).status_code, 409)
        payload = {'checkpoint': {'partition':0,'offset':7,'lsn':42}, 'snapshot_complete':True}
        with patch('integration.cdc.publish_live_dataset', side_effect=CdcDatasetBindingError('CDC_DATASET_BINDING_INVALID')):
            self.assertEqual(self.callback(p, payload).status_code, 409)
        self.assertEqual(Database.objects.get(pk=p.dataset_id).etl_status, 'pending')
        self.assertEqual(self.callback(p, {'checkpoint': {'partition':0,'offset':7,'lsn':41},
            'snapshot_complete':True}).status_code, 409)
        with patch('database.cdc._assert_current_view_ready') as physical:
            self.assertEqual(self.callback(p, payload).status_code, 200)
            physical.assert_called_once()
        self.assertEqual(Database.objects.get(pk=p.dataset_id).etl_status, 'completed')
        self.assertEqual(self.action(p, 'pause').status_code, 202)
        self.assertEqual(Database.objects.get(pk=p.dataset_id).etl_status, 'completed')

    def test_audit_scope_and_public_response_are_bounded(self):
        p = self.enable()
        self.action(p, 'pause')
        audit = CdcAudit.objects.filter(pipeline=p, action='pause').get()
        self.assertEqual((audit.workspace_id, audit.source_id, audit.dataset_id, audit.actor_id),
                         (7, self.source.pk, p.dataset_id, 11))
        self.assertEqual((audit.previous_desired_state, audit.new_desired_state, audit.result_code),
                         ('STREAMING', 'PAUSED', 'CDC_ACCEPTED'))
        for forbidden in ('unit-secret', 'ciphertext', 'topic.prefix'):
            self.assertNotIn(forbidden, str(audit.__dict__))
        p.reconciliation = {'status':'MATCH','password':'sensitive'}
        self.assertEqual(public_pipeline(p)['reconciliation'], {})

    def test_unique_source_table_and_dataset_constraints(self):
        p = self.enable()
        with self.assertRaises(IntegrityError), transaction.atomic():
            CdcPipeline.objects.create(source=self.source, workspace_id=7, dataset_id=p.dataset_id+1,
                table_schema='public', table_name='orders')
        with self.assertRaises(IntegrityError), transaction.atomic():
            CdcPipeline.objects.create(source=self.source, workspace_id=7, dataset_id=p.dataset_id,
                table_schema='public', table_name='other')
        self.assertEqual(CdcPipeline.objects.count(), 1)
