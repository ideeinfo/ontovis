"""Actual HTTP, stable source subjects and PG drafts on disposable databases."""
import copy
from http.server import ThreadingHTTPServer
import os
from threading import Thread
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.api import analysis_drafts as draft, postgres_project_workspaces as registry
from apps.api.authority import PreviewError
from apps.api.project_sessions import ProjectSessions
from apps.api.session_http import handler_type
from tests import test_analysis_drafts_integration as databases, test_project_registry_postgres as fixture
from tests import test_scene_http as transport
from tests.test_analysis_drafts import snapshot, OWNER, OTHER
from tests.test_project_workspaces import ProjectsAuthority
from tools import project_registry_runtime as runtime, model_store_backup as files, analysis_draft_backup as backup

ROOT = '/api/workbench/analysis-sessions'


@unittest.skipUnless(os.environ.get('ONTOVIS_ANALYSIS_TEST_DATABASE_URL'), 'Set an owned disposable PG test connection')
class AnalysisHttpIntegrationTests(unittest.TestCase):
    request = transport.SceneHttpTests.request
    login = transport.SceneHttpTests.login
    account = transport.SceneHttpTests.account

    @classmethod
    def setUpClass(cls):
        databases.AnalysisDraftIntegrationTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        databases.AnalysisDraftIntegrationTests.tearDownClass.__func__(cls)

    def setUp(self):
        fixture.RegistryPackageTests.setUp(self)
        self.sessions.close()
        for url in self.urls:
            with self.driver.connect(url) as db:
                for schema in (draft.SCHEMA, registry.SCHEMA):
                    db.execute('drop schema if exists '+schema+' cascade')
        self.runtime = self.root/'runtime'
        runtime.activate_new(self.backup, self.receipt['manifestSha256'], self.urls[0], self.runtime, service_stopped=True)
        self.meta = draft.provision(self.urls[0], 'ontobase-primary')
        class Source(ProjectsAuthority):
            projects = {'SYNTHETIC-A': 'Synthetic A', 'B': 'Synthetic B'}
            permissions = {'writer': {'SYNTHETIC-A': 'admin', 'B': 'admin'},
                           'other': {'SYNTHETIC-A': 'admin'}, 'reader': {'SYNTHETIC-A': 'viewer'}}
            subjects = {'writer': OWNER, 'other': OTHER, 'reader': '00000000-0000-4000-8000-000000000021'}
            def request(self, method, path, body=None):
                if path == '/api/v1/auth/login':
                    return {'token': 'synthetic-only', 'user': {'username': body['username'], 'id': self.subjects[body['username']]}}
                if path == '/api/v1/auth/me':
                    return {'user': {'id': self.subjects[self.username], 'username': self.username, 'is_active': True}}
                return super().request(method, path, body)
        self.source = Source
        self.sessions = self.start()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler_type(self.sessions, transport.ORIGIN, development=True))
        thread = Thread(target=self.server.serve_forever, daemon=True); thread.start()
        self.addCleanup(self.server.server_close); self.addCleanup(thread.join); self.addCleanup(self.server.shutdown)
        self.admin = self.login('writer')

    def start(self, store_id='default'):
        app = ProjectSessions('http://127.0.0.1:1', library_root=self.runtime/'workbench-library',
            workspace_root=self.runtime/'project-spaces', registry_backend='postgres', registry_database_url=self.urls[0],
            analysis_store_id=self.meta['storeId'] if store_id == 'default' else store_id, factory=self.source)
        self.addCleanup(app.close)
        return app

    def body(self, **values):
        return {'projectRef': {'ontobaseConnectionId': 'ontobase-primary', 'projectCode': 'SYNTHETIC-A'}, **values}

    def value(self):
        value = snapshot(); value.update(ontobaseConnectionId='ontobase-primary', projectCode='SYNTHETIC-A')
        return value

    def create(self, **extra):
        body = self.body(requestId=str(uuid4()), snapshot=self.value(), **extra)
        result = self.request(ROOT+'/create', body)
        self.assertEqual(result[0], 200, result[1])
        return result[1], body

    def detail(self, session, **extra):
        return self.request(ROOT+'/detail', self.body(analysisSessionId=session['analysisSessionId']), **extra)

    def test_save_restore_history_and_fixed_revision_roundtrip(self):
        created, _ = self.create(); value = self.value(); value['cards'][0]['note'] = '逐单人工草稿。'*500
        body = self.body(analysisSessionId=created['analysisSessionId'], requestId=str(uuid4()),
                         expectedAnalysisRevision=1, snapshot=value)
        saved = self.request(ROOT+'/save', body)
        self.assertEqual((saved[0], saved[1]['analysisRevision']), (200, 2))
        self.assertEqual(self.detail(created)[1]['snapshot'], value)
        original = self.request(ROOT+'/detail', self.body(analysisSessionId=created['analysisSessionId'], analysisRevision=1))
        self.assertEqual(original[1]['snapshot'], self.value())
        result = self.request(ROOT+'/restore', self.body(analysisSessionId=created['analysisSessionId'], requestId=str(uuid4()),
                             expectedAnalysisRevision=2, restoreRevision=1))
        self.assertEqual((result[0], result[1]['analysisRevision']), (200, 3))
        history = self.request(ROOT+'/revisions', self.body(analysisSessionId=created['analysisSessionId'], limit=1))[1]
        self.assertEqual(history['items'][0]['revision'], 3); self.assertEqual(history['nextBeforeRevision'], 3)
        self.assertFalse(result[1]['capabilities']['canConfirmConclusion'])

    def test_scope_subject_origin_and_anonymous_do_not_disclose_drafts(self):
        created, _ = self.create()
        self.assertEqual(self.detail(created, client=False)[0], 401)
        self.assertEqual(self.detail(created, headers={'Origin': 'https://wrong.invalid'})[0], 403)
        other = self.login('other')
        self.assertEqual(self.detail(created, client=other)[0], 404)
        self.assertEqual(self.request(ROOT, self.body(), client=other)[1]['total'], 0)
        cross = self.body(analysisSessionId=created['analysisSessionId']); cross['projectRef']['projectCode'] = 'B'
        self.assertEqual(self.request(ROOT+'/detail', cross)[0], 404)
        cross['projectRef']['ontobaseConnectionId'] = 'wrong'
        self.assertEqual(self.request(ROOT+'/detail', cross)[0], 404)

    def test_owner_cannot_be_forged_and_reader_cannot_write(self):
        body = self.body(requestId=str(uuid4()), snapshot=self.value(), ownerId=OTHER)
        self.assertEqual(self.request(ROOT+'/create', body)[0], 422)
        del body['ownerId']; reader = self.login('reader')
        self.assertEqual(self.request(ROOT+'/create', body, client=reader)[0], 403)
        created, _ = self.create()
        self.source.permissions['writer']['SYNTHETIC-A'] = 'viewer'
        self.assertEqual(self.detail(created)[0], 200)
        self.assertFalse(self.detail(created)[1]['capabilities']['canWrite'])

    def test_replay_uses_same_request_and_never_bypasses_current_permission(self):
        created, body = self.create()
        self.assertEqual(self.request(ROOT+'/create', body)[1], created)
        changed = copy.deepcopy(body); changed['snapshot']['title'] = 'changed'
        self.assertEqual(self.request(ROOT+'/create', changed)[1]['code'], 'ANALYSIS_REQUEST_CONFLICT')
        self.source.permissions['writer'].pop('SYNTHETIC-A')
        self.assertEqual(self.request(ROOT+'/create', body)[0], 403)
        self.assertEqual(len(backup.export_package(self.urls[0])['tables']['analysis_revisions']), 1)

    def test_final_source_revocation_rolls_back_all_draft_rows(self):
        calls = 0; original = self.sessions._access
        def access(*args):
            nonlocal calls
            calls += 1
            if calls == 4: self.source.permissions['writer']['SYNTHETIC-A'] = 'viewer'
            return original(*args)
        with patch.object(self.sessions, '_access', side_effect=access):
            result = self.request(ROOT+'/create', self.body(requestId=str(uuid4()), snapshot=self.value()))
        self.assertEqual((result[0], result[1]['code']), (409, 'ACCESS_CHANGED'))
        package = backup.export_package(self.urls[0])
        for table in ('analysis_sessions', 'analysis_revisions', 'analysis_requests'):
            self.assertEqual(package['tables'][table], [])

    def test_same_username_with_changed_subject_invalidates_session(self):
        created, _ = self.create(); self.source.subjects['writer'] = OTHER
        self.assertEqual(self.detail(created)[0], 401)
        self.source.subjects['writer'] = OWNER
        self.assertEqual(self.detail(created)[0], 401)

    def test_relogin_and_renamed_username_keep_same_owner_uuid(self):
        created, _ = self.create()
        self.request('/api/session/logout', {})
        self.admin = self.login('writer')
        self.assertEqual(self.detail(created)[0], 200)
        self.source.subjects['renamed'] = OWNER; self.source.permissions['renamed'] = {'SYNTHETIC-A': 'admin'}
        self.assertEqual(self.detail(created, client=self.login('renamed'))[0], 200)

    def test_listing_cursor_binds_owner_project_filter_session_and_snapshot(self):
        for _ in range(3): self.create()
        first = self.request(ROOT, self.body(limit=1))[1]
        second = self.request(ROOT, self.body(limit=1, cursor=first['nextCursor']))[1]
        self.assertNotEqual(first['items'][0]['analysisSessionId'], second['items'][0]['analysisSessionId'])
        self.assertEqual(self.request(ROOT, self.body(limit=1, q='changed', cursor=first['nextCursor']))[0], 409)
        self.assertEqual(self.request(ROOT, self.body(limit=1, cursor=first['nextCursor']), client=self.login('other'))[0], 409)
        self.create()
        self.assertEqual(self.request(ROOT, self.body(limit=1, cursor=first['nextCursor']))[0], 409)

    def test_stale_revision_and_confirm_archive_or_source_payloads_are_refused(self):
        created, _ = self.create(); body = self.body(analysisSessionId=created['analysisSessionId'], requestId=str(uuid4()),
                                                   expectedAnalysisRevision=0, snapshot=self.value())
        self.assertEqual(self.request(ROOT+'/save', body)[1]['code'], 'ANALYSIS_CHANGED')
        for state in ('concluded', 'archived'):
            body['snapshot']['status'] = state
            self.assertEqual(self.request(ROOT+'/save', body)[1]['code'], 'ANALYSIS_REVIEW_NOT_CONFIGURED')
        for route in ('confirm', 'archive', 'share'):
            self.assertEqual(self.request(ROOT+'/'+route, {})[0], 404)
        value = self.value(); value['cards'][0]['kind'] = 'photo'
        self.assertEqual(self.request(ROOT+'/create', self.body(requestId=str(uuid4()), snapshot=value))[1]['code'], 'ANALYSIS_SOURCE_NOT_CONNECTED')

    def test_reopened_runtime_reads_persisted_draft_and_rejects_old_session(self):
        created, _ = self.create(); self.sessions.close()
        other = self.start(); sid, row = other.anonymous()
        with self.assertRaises(PreviewError):
            other.analysis_request(sid, ROOT+'/detail', self.body(analysisSessionId=created['analysisSessionId'], expectedSessionRevision=row.revision))
        sid, view = other.login(sid, {'username': 'writer', 'password': 'synthetic-only', 'expectedSessionRevision': row.revision}, 'new-runtime')
        value = other.analysis_request(sid, ROOT+'/detail', self.body(analysisSessionId=created['analysisSessionId'], expectedSessionRevision=view['sessionRevision']))
        self.assertEqual(value['snapshot'], self.value())

    def test_wrong_or_missing_store_identity_fails_startup_before_business_writes(self):
        self.sessions.close(); original = files._inventory(self.runtime)
        for identity in (None, str(uuid4())):
            with self.assertRaises(PreviewError): self.start(identity)
        self.assertEqual(files._inventory(self.runtime), original)

    def test_legacy_backup_refuses_to_omit_analysis_store(self):
        self.create(); self.sessions.close()
        with self.assertRaises(PreviewError) as error:
            runtime.snapshot(self.runtime/'project-spaces', self.root/'wrong-backup', self.urls[0],
                library_root=self.runtime/'workbench-library', service_stopped=True)
        self.assertEqual(error.exception.code, 'ANALYSIS_PAIRED_BACKUP_REQUIRED')
        self.assertFalse((self.root/'wrong-backup').exists())


if __name__ == '__main__': unittest.main()
