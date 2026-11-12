"""Canvas recycle-bin transactions on disposable PostgreSQL databases."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import os
from threading import Barrier
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.api import analysis_drafts as draft, analysis_lifecycle as lifecycle
from apps.api.analysis_evidence import AnalysisEvidence
from apps.api.authority import PreviewError
from tests.test_analysis_drafts import CONNECTION, PROJECT, OWNER, OTHER, snapshot
from tests import test_analysis_drafts_integration as base
from tools import analysis_draft_backup as backup, analysis_lifecycle_upgrade as migration


@unittest.skipUnless(os.environ.get('ONTOVIS_ANALYSIS_TEST_DATABASE_URL'), 'Set an owned disposable PG test connection')
class AnalysisLifecycleTests(unittest.TestCase):
    setUpClass = classmethod(base.AnalysisDraftIntegrationTests.setUpClass.__func__)
    tearDownClass = classmethod(base.AnalysisDraftIntegrationTests.tearDownClass.__func__)
    consumer = base.AnalysisDraftIntegrationTests.consumer
    write = base.AnalysisDraftIntegrationTests.write
    create = base.AnalysisDraftIntegrationTests.create
    save = base.AnalysisDraftIntegrationTests.save
    data = base.AnalysisDraftIntegrationTests.data

    def setUp(self):
        base.AnalysisDraftIntegrationTests.setUp(self)
        store_id = self.store.store_id; self.store.close()
        migration.upgrade(self.urls[0], store_id, [self.root], service_stopped=True)
        self.store = self.consumer()

    def body(self, created, revision=0):
        return {'analysisSessionId': created['analysisSessionId'], 'expectedAnalysisRevision': created['analysisRevision'],
                'expectedLifecycleRevision': revision, 'requestId': str(uuid4())}

    def action(self, action, body, store=None, actor=OWNER, role='admin', authorize=lambda: None):
        return lifecycle.change(store or self.store, actor, role, action, body, authorize)

    def listing(self, **body):
        return self.store.listing(OWNER, body, lambda: None, cursor_key=b'fixture-key', session_revision='fixture')

    def test_trash_restore_preserve_content_identity_and_old_revisions(self):
        created = self.create(); before = self.data()
        deleted = self.action('trash', self.body(created))
        self.assertEqual((deleted['analysisRevision'], deleted['lifecycleRevision'], deleted['lifecycle']), (1, 1, 'trashed'))
        self.assertEqual(self.listing()['total'], 0)
        self.assertEqual(self.listing(lifecycle='trashed')['items'][0]['analysisSessionId'], created['analysisSessionId'])
        detail = self.store.detail(OWNER, created['analysisSessionId'], lambda: None, revision=1)
        self.assertEqual(detail['snapshot'], snapshot()); self.assertEqual(detail['lifecycle'], 'trashed')
        restored = self.action('untrash', self.body(created, 1))
        self.assertEqual(restored['lifecycleRevision'], 2); self.assertEqual(self.listing()['total'], 1)
        self.assertEqual(self.listing(lifecycle='trashed')['total'], 0)
        after = self.data()
        for name in ('store_meta', 'analysis_sessions', 'analysis_revisions', 'analysis_evidence_refs'):
            self.assertEqual(before['tables'][name], after['tables'][name])
        self.assertEqual(self.save(created)['analysisRevision'], 2)

    def test_idempotency_does_not_reapply_an_old_delete_after_restore(self):
        created = self.create(); body = self.body(created)
        deleted = self.action('trash', body); self.assertEqual(self.action('trash', body), deleted)
        self.action('untrash', self.body(created, 1)); self.assertEqual(self.action('trash', body), deleted)
        self.assertEqual(self.listing()['total'], 1)
        self.assertEqual(len(self.data()['tables']['analysis_lifecycle_events']), 2)
        with self.assertRaises(PreviewError) as error: self.action('trash', {**body, 'expectedLifecycleRevision': 2})
        self.assertEqual(error.exception.code, 'ANALYSIS_REQUEST_CONFLICT')

    def test_owner_project_role_and_request_fields_cannot_be_forged(self):
        created = self.create(); before = self.data(); body = self.body(created)
        for kwargs, code in (({'actor': OTHER}, 'NOT_FOUND_OR_FORBIDDEN'),
                             ({'store': self.consumer(project='OTHER')}, 'NOT_FOUND_OR_FORBIDDEN'),
                             ({'role': 'viewer'}, 'ANALYSIS_WRITE_FORBIDDEN')):
            with self.assertRaises(PreviewError) as error: self.action('trash', body, **kwargs)
            self.assertEqual(error.exception.code, code)
        for bad in ({**body, 'actorId': OWNER}, {**body, 'expectedLifecycleRevision': True}):
            with self.assertRaises(PreviewError): self.action('trash', bad)
        self.assertEqual(self.data(), before)

    def test_stale_content_and_lifecycle_versions_are_rejected(self):
        created = self.create(); stale = self.body(created); saved = self.save(created)
        with self.assertRaises(PreviewError) as error: self.action('trash', stale)
        self.assertEqual(error.exception.code, 'ANALYSIS_CHANGED')
        self.action('trash', self.body(saved)); self.action('untrash', self.body(saved, 1))
        with self.assertRaises(PreviewError) as error: self.action('trash', self.body(saved))
        self.assertEqual(error.exception.code, 'ANALYSIS_LIFECYCLE_CHANGED')

    def test_deleted_canvas_rejects_save_restore_and_old_write_replay(self):
        created = self.create(); saved = self.save(created)
        self.action('trash', self.body(saved)); before = self.data()
        for action, body in (('save', {'requestId': str(uuid4()), 'analysisSessionId': created['analysisSessionId'], 'expectedAnalysisRevision': 2, 'snapshot': snapshot()}),
                             ('restore', {'requestId': str(uuid4()), 'analysisSessionId': created['analysisSessionId'], 'expectedAnalysisRevision': 2, 'restoreRevision': 1})):
            with self.assertRaises(PreviewError) as error: self.write(action, body)
            self.assertEqual(error.exception.code, 'ANALYSIS_TRASHED')
        self.assertEqual(self.data(), before)

    def test_deleted_canvas_keeps_fixed_sources_readable_and_blocks_registration(self):
        created = self.create(); sources = AnalysisEvidence(self.store)
        descriptor = {'entityUid': 'synthetic-object', 'expectedEntityRevision': 'r1', 'installationContextId': None, 'expectedHierarchyRevision': None}
        body = {**self.body(created), 'sourceKind': 'object', 'selector': descriptor}; body.pop('expectedLifecycleRevision')
        reference = sources.register(OWNER, body, lambda: None, lambda *_: descriptor)
        self.action('trash', self.body(created)); before = self.data()
        fixed = sources.descriptor(OWNER, {'analysisSessionId': created['analysisSessionId'], 'evidenceRefId': reference['evidenceRefId']}, lambda: None)
        self.assertEqual(fixed[1], descriptor)
        for payload in (body, {**body, 'requestId': str(uuid4())}):
            with self.assertRaises(PreviewError) as error: sources.register(OWNER, payload, lambda: None, lambda *_: descriptor)
            self.assertEqual(error.exception.code, 'ANALYSIS_TRASHED')
        self.assertEqual(before, self.data())

    def test_final_revocation_rolls_back_event_and_receipt(self):
        created = self.create(); before = self.data(); calls = 0
        def authorize():
            nonlocal calls
            calls += 1
            if calls == 2: raise PreviewError(409, 'ACCESS_CHANGED')
        with self.assertRaises(PreviewError): self.action('trash', self.body(created), authorize=authorize)
        self.assertEqual(self.data(), before)

    def test_concurrent_save_and_trash_serialize_without_lost_changes(self):
        created = self.create(); other = self.consumer(); barrier = Barrier(2)
        def run(deleting):
            barrier.wait(timeout=10)
            try:
                return self.action('trash', self.body(created), store=other) if deleting else self.save(created)
            except PreviewError as error: return error.code
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(run, (False, True)))
        self.assertEqual(sum(isinstance(value, dict) for value in results), 1)
        self.assertIn(next(value for value in results if isinstance(value, str)), ('ANALYSIS_CHANGED', 'ANALYSIS_TRASHED'))
        backup.validate_package(self.data())

    def test_v3_backup_restore_and_tampered_lifecycle_are_checked(self):
        created = self.create(); self.action('trash', self.body(created)); package = self.data()
        receipt = backup.snapshot(self.urls[0], self.root/'snapshot')
        backup.restore_new(self.root/'snapshot', receipt['manifestSha256'], self.urls[1])
        restored = backup.export_package(self.urls[1]); self.assertEqual(restored['format'], draft.FORMAT_V3)
        for name in draft.V3_COLUMNS:
            if name != 'store_meta': self.assertEqual(restored['tables'][name], package['tables'][name])
        tampered = deepcopy(package); tampered['tables']['analysis_lifecycle_events'][0]['state'] = 'active'
        with self.assertRaises(PreviewError): backup.validate_package(tampered)

        tampered = deepcopy(package); tampered['tables']['analysis_lifecycle_events'] = []
        with self.assertRaises(PreviewError): backup.validate_package(tampered)

    def test_deleted_event_is_neither_resumed_nor_recommended_as_history(self):
        from apps.api import simulated_faults as sim
        from apps.api.analysis_queries import start_analysis, matching_history
        from tests import test_analysis_canvas as canvas
        store = self.consumer(project='Demo-PDS'); reader = canvas.CanvasStorageTests.reader(self)
        dataset = sim.identity('13001'); entry = {k: dataset[k] for k in ('datasetId', 'datasetRevision')}
        created = start_analysis(store, OWNER, reader, {'entry': entry, 'requestId': str(uuid4())}, lambda: None)
        self.action('trash', self.body(created), store=store)
        self.assertEqual(matching_history(store, OWNER, dataset, None, lambda: None), [])
        next_event = start_analysis(store, OWNER, reader, {'entry': entry, 'requestId': str(uuid4())}, lambda: None)
        self.assertNotEqual(next_event['analysisSessionId'], created['analysisSessionId'])
        self.assertFalse(next_event['resumed']); self.assertFalse(next_event['historyImported'])

    def test_upgrade_preserves_populated_v2_rows_and_is_repeatable(self):
        meta = draft.provision(self.urls[1], CONNECTION)
        other = self.consumer(self.urls[1]); self.write('create', {'requestId': str(uuid4()), 'snapshot': snapshot()}, store=other); other.close()
        before = backup.export_package(self.urls[1])
        with self.assertRaises(PreviewError): migration.upgrade(self.urls[1], meta['storeId'], [self.root])
        with self.assertRaises(PreviewError): migration.upgrade(self.urls[1], str(uuid4()), [self.root], service_stopped=True)
        result = migration.upgrade(self.urls[1], meta['storeId'], [self.root], service_stopped=True)
        self.assertTrue(result['changed']); self.assertFalse(migration.upgrade(self.urls[1], meta['storeId'], [self.root], service_stopped=True)['changed'])
        after = backup.export_package(self.urls[1]); self.assertEqual(after['sourceStoreId'], before['sourceStoreId'])
        for name in draft.COLUMNS:
            if name != 'store_meta': self.assertEqual(after['tables'][name], before['tables'][name])
        self.assertEqual(after['tables']['analysis_lifecycle_events'], [])
