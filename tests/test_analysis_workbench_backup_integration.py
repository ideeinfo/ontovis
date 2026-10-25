"""Complete synthetic workbench plus draft recovery on owned disposable PG DBs."""
import copy
import json
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.api import analysis_drafts as draft, postgres_project_workspaces as registry
from apps.api.authority import PreviewError
from apps.api.project_sessions import ProjectSessions
from tests import test_analysis_drafts_integration as databases
from tests import test_project_registry_postgres as fixture
from tests.test_analysis_drafts import snapshot as manual_snapshot, OWNER
from tests.test_project_workspaces import ProjectsAuthority
from tools import analysis_workbench_backup as bundle, analysis_draft_backup as analysis
from tools import project_registry_runtime as runtime, project_store_backup as backups, model_store_backup as files


@unittest.skipUnless(os.environ.get('ONTOVIS_ANALYSIS_TEST_DATABASE_URL'), 'Set an owned disposable PG test connection')
class AnalysisWorkbenchBackupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        databases.AnalysisDraftIntegrationTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        databases.AnalysisDraftIntegrationTests.tearDownClass.__func__(cls)

    def setUp(self):
        fixture.RegistryPackageTests.setUp(self)
        for url in self.urls:
            with self.driver.connect(url) as db:
                for schema in (draft.SCHEMA, registry.SCHEMA):
                    db.execute('drop schema if exists '+schema+' cascade')
        self.scene = self.sessions._workspace(self.workspace).scenes.create(
            {'clientRequestId': str(uuid4()), 'displayName': '保留的合成场景'},
            'synthetic', lambda: None, lambda _: None, lambda *_: None)
        self.source = self.root/'source'
        self.b1 = self.root/'B1'
        receipt = backups.snapshot(self.sessions.registry.root, self.b1,
            library_root=self.sessions.shared.library.root, service_stopped=True)
        self.sessions.close()
        runtime.activate_new(self.b1, receipt['manifestSha256'], self.urls[0], self.source, service_stopped=True)
        draft.provision(self.urls[0], 'ontobase-primary')
        self.store = draft.AnalysisDrafts(self.urls[0], 'ontobase-primary', 'SYNTHETIC-A')
        self.addCleanup(self.store.close)
        value = manual_snapshot(); value.update(ontobaseConnectionId='ontobase-primary', projectCode='SYNTHETIC-A')
        self.body = {'requestId': str(uuid4()), 'snapshot': value}
        self.created = self.store.write(OWNER, 'admin', 'create', self.body, lambda: None)
        self.value = copy.deepcopy(value); self.value['cards'][0]['note'] = '保留的新修订与人工依据'
        self.saved = self.store.write(OWNER, 'admin', 'save', {
            'requestId': str(uuid4()), 'snapshot': self.value, 'expectedAnalysisRevision': 1,
            'analysisSessionId': self.created['analysisSessionId']}, lambda: None)

    def snapshot(self, destination=None, **extra):
        return bundle.snapshot(self.source/'project-spaces', destination or self.root/'paired', self.urls[0],
            library_root=self.source/'workbench-library', service_stopped=True, **extra)

    def restore(self, receipt, destination=None):
        return bundle.restore_new(self.root/'paired', receipt['manifestSha256'], self.urls[1],
                                  destination or self.root/'recovered', service_stopped=True)

    def assert_target_empty(self):
        with self.driver.connect(self.urls[1]) as db:
            for schema in (draft.SCHEMA, registry.SCHEMA):
                self.assertIsNone(db.execute('select to_regnamespace(%s)', (schema,)).fetchone()[0])

    def test_complete_pair_restores_original_ids_files_history_and_replay(self):
        source = files._inventory(self.source); original = analysis.export_package(self.urls[0])
        receipt = self.snapshot(); self.assertEqual(receipt['analysisCounts']['analysis_revisions'], 2)
        result = self.restore(receipt); self.assertEqual(result['status'], 'recovered_not_activated')
        restored = analysis.export_package(self.urls[1])
        self.assertNotEqual(original['sourceStoreId'], restored['sourceStoreId'])
        for table in ('analysis_sessions', 'analysis_revisions', 'analysis_requests'):
            self.assertEqual(original['tables'][table], restored['tables'][table])
        other = draft.AnalysisDrafts(self.urls[1], 'ontobase-primary', 'SYNTHETIC-A')
        self.addCleanup(other.close)
        self.assertEqual(other.write(OWNER, 'admin', 'create', self.body, lambda: None), self.created)
        self.assertEqual(other.detail(OWNER, self.created['analysisSessionId'], lambda: None)['snapshot'], self.value)
        target = self.root/'recovered/workbench'
        app = ProjectSessions('http://127.0.0.1:1', library_root=target/'workbench-library',
            workspace_root=target/'project-spaces', registry_backend='postgres',
            registry_database_url=self.urls[1], factory=ProjectsAuthority)
        self.addCleanup(app.close)
        self.assertEqual(app.registry.lookup('SYNTHETIC-A')['workspace_id'], self.workspace['workspace_id'])
        self.assertEqual(app.registry.summary('SYNTHETIC-A')['sceneCount'], 1)
        self.assertEqual((self.root/'recovered/recovery.json').stat().st_mode & 0o777, 0o600)
        self.assertEqual(files._inventory(self.source), source)
        self.assertEqual(analysis.export_package(self.urls[0]), original)

    def test_stop_flag_and_active_service_are_required(self):
        with self.assertRaises(files.BackupError), patch.object(draft, 'AnalysisConnection') as connect:
            bundle.snapshot(self.source/'project-spaces', self.root/'no-stop', 'unused',
                            library_root=self.source/'workbench-library')
        connect.assert_not_called()
        app = ProjectSessions('http://127.0.0.1:1', library_root=self.source/'workbench-library',
            workspace_root=self.source/'project-spaces', registry_backend='postgres',
            registry_database_url=self.urls[0], factory=ProjectsAuthority)
        self.addCleanup(app.close)
        with self.assertRaises(PreviewError) as error: self.snapshot()
        self.assertEqual(error.exception.code, 'REGISTRY_IN_USE')
        self.assertFalse((self.root/'paired/manifest.json').exists())
        app.close(); self.snapshot(self.root/'retry')

    def test_unregistered_analysis_project_prevents_publishing_pair(self):
        other = draft.AnalysisDrafts(self.urls[0], 'ontobase-primary', 'UNREGISTERED')
        self.addCleanup(other.close)
        value = copy.deepcopy(self.value); value['projectCode'] = 'UNREGISTERED'
        other.write(OWNER, 'admin', 'create', {'requestId': str(uuid4()), 'snapshot': value}, lambda: None)
        with self.assertRaises(PreviewError) as error: self.snapshot()
        self.assertEqual(error.exception.code, 'ANALYSIS_PROJECT_NOT_REGISTERED')
        self.assertFalse((self.root/'paired/manifest.json').exists())

    def test_bad_manifest_or_partial_pair_never_creates_target_schema(self):
        receipt = self.snapshot()
        with self.assertRaises(PreviewError): self.restore({'manifestSha256': '0'*64})
        self.assert_target_empty(); self.assertFalse((self.root/'recovered').exists())
        path = self.root/'paired/analysis/analysis.json'; path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaises(PreviewError): self.restore(receipt)
        self.assert_target_empty(); self.assertFalse((self.root/'recovered').exists())

    def test_pair_failure_has_no_manifest_and_releases_database_locks(self):
        before = analysis.export_package(self.urls[0]); original = files._inventory(self.source)
        with patch.object(analysis, 'snapshot', side_effect=OSError('synthetic write failure')):
            with self.assertRaises(OSError): self.snapshot()
        self.assertFalse((self.root/'paired/manifest.json').exists())
        self.assertEqual(analysis.export_package(self.urls[0]), before)
        self.assertEqual(files._inventory(self.source), original)
        self.snapshot(self.root/'retry')

    def test_restore_failure_retains_partial_target_without_success_receipt(self):
        receipt = self.snapshot()
        with patch.object(analysis, 'restore_new', side_effect=OSError('synthetic restore failure')):
            with self.assertRaises(OSError): self.restore(receipt)
        self.assertTrue((self.root/'recovered/workbench').exists())
        self.assertFalse((self.root/'recovered/recovery.json').exists())
        with self.assertRaises(PreviewError) as error: self.restore(receipt, self.root/'reuse-database')
        self.assertEqual(error.exception.code, 'ANALYSIS_TARGET_OCCUPIED')
        self.assertFalse((self.root/'reuse-database').exists())

    def test_existing_backup_directory_and_database_are_never_overwritten(self):
        receipt = self.snapshot(); original = files._inventory(self.root/'paired')
        with self.assertRaises(files.BackupError): self.snapshot()
        self.assertEqual(original, files._inventory(self.root/'paired'))
        self.restore(receipt)
        data = analysis.export_package(self.urls[1]); files_before = files._inventory(self.root/'recovered')
        with self.assertRaises(files.BackupError): self.restore(receipt)
        with self.assertRaises(PreviewError): self.restore(receipt, self.root/'other-target')
        self.assertEqual(data, analysis.export_package(self.urls[1]))
        self.assertEqual(files_before, files._inventory(self.root/'recovered'))

    def test_database_writes_are_blocked_during_complete_file_copy(self):
        original = runtime.snapshot
        def inspect_lock(*args, **kwargs):
            with self.assertRaises(self.driver.errors.LockNotAvailable):
                with self.driver.connect(self.urls[0]) as db:
                    db.execute("set local lock_timeout='100ms'")
                    db.execute(f'update {draft.SCHEMA}.analysis_sessions set title=title')
            return original(*args, **kwargs)
        with patch.object(runtime, 'snapshot', side_effect=inspect_lock): self.snapshot()


if __name__ == '__main__':
    unittest.main()
