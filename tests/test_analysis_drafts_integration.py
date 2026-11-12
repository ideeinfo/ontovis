"""Real PG transactions on two disposable ONTOVis databases, never a live store."""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.api import analysis_drafts as draft
from apps.api.authority import PreviewError
from tests.test_analysis_drafts import CONNECTION, PROJECT, OWNER, OTHER, snapshot, create_body
from tools import analysis_draft_backup as backup

BASE_URL = os.environ.get('ONTOVIS_ANALYSIS_TEST_DATABASE_URL')


@unittest.skipUnless(BASE_URL, 'Set an owned disposable PG test connection')
class AnalysisDraftIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo
        cls.driver, cls.sql, cls.conninfo = psycopg, sql, staticmethod(make_conninfo)
        cls.admin = make_conninfo(BASE_URL, dbname='postgres')
        cls.names = ['ontovis_analysis_test_'+uuid4().hex[:12] for _ in range(2)]
        cls.urls = [make_conninfo(BASE_URL, dbname=name) for name in cls.names]
        if os.environ.get('ONTOVIS_ANALYSIS_TEST_TARGET_RECORD'):
            with open(os.environ['ONTOVIS_ANALYSIS_TEST_TARGET_RECORD'], 'x') as stream:
                json.dump({'databases': cls.names}, stream)
        cls.created = []
        try:
            with psycopg.connect(cls.admin, autocommit=True) as db:
                for name in cls.names:
                    db.execute(sql.SQL('create database {} template template0').format(sql.Identifier(name)))
                    cls.created.append(name)
        except BaseException:
            cls.tearDownClass(); raise

    @classmethod
    def tearDownClass(cls):
        with cls.driver.connect(cls.admin, autocommit=True) as db:
            for name in cls.created:
                db.execute('select pg_terminate_backend(pid) from pg_stat_activity where datname=%s and pid<>pg_backend_pid()', (name,))
                db.execute(cls.sql.SQL('drop database {}').format(cls.sql.Identifier(name)))
        cls.created = []

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        for url in self.urls:
            with self.driver.connect(url) as db:
                db.execute('drop schema if exists '+draft.SCHEMA+' cascade')
        draft.provision(self.urls[0], CONNECTION)
        self.store = self.consumer()

    def consumer(self, url=None, project=PROJECT):
        store = draft.AnalysisDrafts(url or self.urls[0], CONNECTION, project)
        self.addCleanup(store.close)
        return store

    def write(self, action, body, store=None, actor=OWNER, role='admin', authorize=lambda: None):
        return (store or self.store).write(actor, role, action, body, authorize)

    def create(self, value=None):
        return self.write('create', create_body(value))

    def save(self, created, value=None, **extra):
        return self.write('save', {'requestId': str(uuid4()), 'analysisSessionId': created['analysisSessionId'],
                          'expectedAnalysisRevision': created['analysisRevision'], 'snapshot': value or snapshot()}, **extra)

    def data(self):
        return backup.export_package(self.urls[0])

    def no_target(self):
        with self.driver.connect(self.urls[1]) as db:
            self.assertIsNone(db.execute('select to_regnamespace(%s)', (draft.SCHEMA,)).fetchone()[0])

    def test_create_replay_and_changed_request_content(self):
        body = create_body(); first = self.write('create', body)
        self.assertEqual(self.write('create', body), first)
        body['snapshot']['title'] = '请求内容变化'
        with self.assertRaises(PreviewError) as error: self.write('create', body)
        self.assertEqual(error.exception.code, 'ANALYSIS_REQUEST_CONFLICT')
        self.assertEqual(len(self.data()['tables']['analysis_sessions']), 1)

    def test_concurrent_identical_create_has_one_receipt_and_one_revision(self):
        stores = [self.consumer() for _ in range(4)]
        body, barrier = create_body(), Barrier(4)
        def run(store):
            barrier.wait(timeout=10)
            return self.write('create', body, store=store)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(run, stores))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual([len(self.data()['tables'][name]) for name in ('analysis_sessions', 'analysis_revisions', 'analysis_requests')], [1,1,1])

    def test_concurrent_saves_have_one_winner_without_lost_update(self):
        created = self.create(); stores = [self.consumer(), self.consumer()]; barrier = Barrier(2)
        def run(args):
            i, store = args; value = snapshot(); value['cards'][0]['note'] = 'candidate-'+str(i)
            barrier.wait(timeout=10)
            try: return self.save(created, value, store=store)
            except PreviewError as error: return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, enumerate(stores)))
        self.assertEqual(sum(type(r) is dict for r in results), 1)
        self.assertIn('ANALYSIS_CHANGED', results)
        self.assertEqual(len(self.data()['tables']['analysis_revisions']), 2)

    def test_final_authorization_failure_rolls_back_head_history_and_receipt(self):
        created = self.create(); before = self.data(); calls = 0
        def revoked():
            nonlocal calls
            calls += 1
            if calls == 2: raise PreviewError(403, 'FORBIDDEN')
        body = {'requestId':str(uuid4()), 'analysisSessionId':created['analysisSessionId'],
                'expectedAnalysisRevision':1, 'snapshot':snapshot()}
        with self.assertRaises(PreviewError): self.write('save', body, authorize=revoked)
        self.assertEqual(before, self.data())
        self.assertEqual(self.write('save', body)['analysisRevision'], 2)

    def test_revoked_replay_does_not_return_a_previous_success(self):
        body = create_body(); self.write('create', body)
        def denied(): raise PreviewError(403, 'FORBIDDEN')
        with self.assertRaises(PreviewError) as error: self.write('create', body, authorize=denied)
        self.assertEqual(error.exception.code, 'FORBIDDEN')

    def test_owner_and_project_are_required_even_with_admin_role(self):
        created = self.create(); other_project = self.consumer(project='ANOTHER-PROJECT')
        for store, actor in ((self.store, OTHER), (other_project, OWNER)):
            with self.assertRaises(PreviewError) as error:
                store.detail(actor, created['analysisSessionId'], lambda: None)
            self.assertEqual(error.exception.code, 'NOT_FOUND_OR_FORBIDDEN')
            with self.assertRaises(PreviewError): self.save(created, store=store, actor=actor)
        self.assertEqual(len(self.data()['tables']['analysis_revisions']), 1)

    def test_read_only_owner_can_read_but_cannot_save_or_replay_write(self):
        body = create_body(); created = self.write('create', body)
        self.assertEqual(self.store.detail(OWNER, created['analysisSessionId'], lambda: None)['headRevision'], 1)
        with self.assertRaises(PreviewError) as error: self.write('create', body, role='viewer')
        self.assertEqual(error.exception.code, 'ANALYSIS_WRITE_FORBIDDEN')

    def test_restore_appends_new_revision_and_history_stays_fixed(self):
        created = self.create(); old = self.store.detail(OWNER, created['analysisSessionId'], lambda: None)
        changed = snapshot(); changed['cards'][0]['note'] = '补充核查记录'; self.save(created, changed)
        restored = self.write('restore', {'requestId':str(uuid4()), 'analysisSessionId':created['analysisSessionId'],
                             'expectedAnalysisRevision':2, 'restoreRevision':1})
        self.assertEqual((restored['analysisRevision'], restored['contentSha256']), (3, old['contentSha256']))
        self.assertEqual(self.store.detail(OWNER, created['analysisSessionId'], lambda: None, revision=1)['snapshot'], old['snapshot'])
        page = self.store.history(OWNER, created['analysisSessionId'], lambda: None, limit=2)
        self.assertEqual([row['revision'] for row in page['items']], [3,2]); self.assertEqual(page['nextBeforeRevision'], 2)
        self.assertEqual(self.store.history(OWNER, created['analysisSessionId'], lambda: None, before=2)['items'][0]['revision'], 1)

    def test_new_consumer_process_reads_original_snapshot(self):
        created = self.create(); self.store.close()
        program = "from apps.api.analysis_drafts import AnalysisDrafts;import os,json;s=AnalysisDrafts(os.environ['TEST_DRAFT_DSN'],os.environ['TEST_DRAFT_CONNECTION'],os.environ['TEST_DRAFT_PROJECT']);r=s.detail(os.environ['TEST_DRAFT_OWNER'],os.environ['TEST_DRAFT_ID'],lambda:None);print(json.dumps({'sha':r['contentSha256'],'revision':r['analysisRevision']}));s.close()"
        env = {**os.environ, 'TEST_DRAFT_DSN':self.urls[0], 'TEST_DRAFT_CONNECTION':CONNECTION,
               'TEST_DRAFT_PROJECT':PROJECT, 'TEST_DRAFT_OWNER':OWNER, 'TEST_DRAFT_ID':created['analysisSessionId']}
        result = subprocess.run([sys.executable, '-c', program], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, 'new consumer process failed')
        self.assertEqual(json.loads(result.stdout), {'sha':created['contentSha256'], 'revision':1})

    def test_no_implicit_provisioning_or_cross_connection_binding(self):
        with self.assertRaises(PreviewError): self.consumer(self.urls[1])
        self.no_target()
        with self.assertRaises(PreviewError) as error: draft.AnalysisDrafts(self.urls[0], 'another-source', PROJECT)
        self.assertEqual(error.exception.code, 'ANALYSIS_STORE_SCOPE_MISMATCH')

    def test_snapshot_restore_preserves_data_ids_hashes_and_replays(self):
        body = create_body(); created = self.write('create', body)
        self.save(created); before = self.data()
        receipt = backup.snapshot(self.urls[0], self.root/'B1')
        restored = backup.restore_new(self.root/'B1', receipt['manifestSha256'], self.urls[1])
        self.assertNotEqual(restored['storeId'], before['sourceStoreId'])
        copied = backup.export_package(self.urls[1])
        for name in ('analysis_sessions', 'analysis_revisions', 'analysis_requests'):
            self.assertEqual(copied['tables'][name], before['tables'][name])
        target = self.consumer(self.urls[1])
        self.assertEqual(self.write('create', body, store=target), created)
        self.assertEqual(self.data(), before)

    def test_existing_target_and_existing_backup_are_never_overwritten(self):
        self.create(); receipt = backup.snapshot(self.urls[0], self.root/'B1'); before = self.data()
        with self.assertRaises(PreviewError) as error: backup.restore_new(self.root/'B1', receipt['manifestSha256'], self.urls[0])
        self.assertEqual(error.exception.code, 'ANALYSIS_TARGET_OCCUPIED')
        with self.assertRaises(PreviewError): backup.snapshot(self.urls[0], self.root/'B1')
        self.assertEqual(before, self.data())

    def test_modified_package_and_symlink_refused_before_target_creation(self):
        self.create(); receipt = backup.snapshot(self.urls[0], self.root/'B1')
        original = (self.root/'B1'/'analysis.json').read_bytes()
        (self.root/'B1'/'analysis.json').write_bytes(original+b' ')
        with self.assertRaises(PreviewError) as error: backup.restore_new(self.root/'B1', receipt['manifestSha256'], self.urls[1])
        self.assertEqual(error.exception.code, 'ANALYSIS_CONTENT_CHANGED'); self.no_target()
        (self.root/'B1'/'analysis.json').unlink(); (self.root/'outside').write_bytes(original)
        (self.root/'B1'/'analysis.json').symlink_to(self.root/'outside')
        with self.assertRaises(OSError): backup.restore_new(self.root/'B1', receipt['manifestSha256'], self.urls[1])
        self.no_target()

    def test_package_semantics_reject_dangling_revisions_and_forged_ownership(self):
        self.create(); package = self.data()
        for change in ('head', 'owner', 'receipt', 'scope', 'bad_id'):
            value = copy.deepcopy(package)
            if change == 'head': value['tables']['analysis_sessions'][0]['head_revision'] = 2
            elif change == 'owner': value['tables']['analysis_sessions'][0]['owner_id'] = OTHER
            elif change == 'receipt': value['tables']['analysis_requests'] = []
            elif change == 'bad_id': value['tables']['analysis_revisions'][0]['session_id'] = []
            else: value['tables']['analysis_sessions'][0]['project_code'] = 'other'
            with self.assertRaises(PreviewError): backup.validate_package(value)

    def test_immutable_history_and_owner_are_enforced_by_database(self):
        self.create(); before = self.data()
        statements = [f"update {draft.SCHEMA}.analysis_revisions set content_sha256=repeat('0',64)",
                      f'delete from {draft.SCHEMA}.analysis_requests',
                      f"update {draft.SCHEMA}.analysis_sessions set owner_id='{OTHER}'",
                      f"update {draft.SCHEMA}.store_meta set connection_id='other'"]
        for query in statements:
            with self.assertRaises(self.driver.Error):
                with self.driver.connect(self.urls[0]) as db: db.execute(query)
        self.assertEqual(before, self.data())

    def test_runtime_without_ddl_delete_or_history_update_can_use_store(self):
        role = 'ontovis_analysis_role_'+uuid4().hex[:10]
        with self.driver.connect(self.urls[0], autocommit=True) as db:
            db.execute(self.sql.SQL('create role {} nologin').format(self.sql.Identifier(role)))
            db.execute(self.sql.SQL('grant usage on schema {} to {}').format(self.sql.Identifier(draft.SCHEMA), self.sql.Identifier(role)))
            db.execute(self.sql.SQL('grant select on all tables in schema {} to {}').format(self.sql.Identifier(draft.SCHEMA), self.sql.Identifier(role)))
            for table in ('analysis_sessions', 'analysis_revisions', 'analysis_requests'):
                db.execute(self.sql.SQL('grant insert on {}.{} to {}').format(self.sql.Identifier(draft.SCHEMA), self.sql.Identifier(table), self.sql.Identifier(role)))
            db.execute(self.sql.SQL('grant update(head_revision,title,status,updated_at) on {}.analysis_sessions to {}').format(self.sql.Identifier(draft.SCHEMA), self.sql.Identifier(role)))
        try:
            url = self.conninfo(self.urls[0], options='-c role='+role)
            app = self.consumer(url); created = self.write('create', create_body(), store=app)
            self.save(created, store=app)
            for query in (f'create table {draft.SCHEMA}.unauthorized(x int)', f'delete from {draft.SCHEMA}.analysis_sessions',
                          f"update {draft.SCHEMA}.analysis_revisions set operation='save'"):
                with self.assertRaises(self.driver.Error):
                    with self.driver.connect(url) as db: db.execute(query)
            app.close()
        finally:
            with self.driver.connect(self.urls[0], autocommit=True) as db:
                db.execute(self.sql.SQL('drop owned by {}').format(self.sql.Identifier(role)))
                db.execute(self.sql.SQL('drop role {}').format(self.sql.Identifier(role)))

    def test_store_budget_rejects_before_unexportable_history_is_committed(self):
        created = self.create(); before = self.data()
        with patch.object(draft, 'MAX_STORE_BYTES', len(draft.canonical(snapshot()).encode()) + 10):
            with self.assertRaises(PreviewError) as error: self.save(created)
            self.assertEqual(error.exception.code, 'ANALYSIS_STORE_LIMIT')
        self.assertEqual(before, self.data())
        with patch.object(draft, 'MAX_STORE_BYTES', 1):
            with self.assertRaises(PreviewError): backup.validate_package(before)

    def test_export_is_consistent_while_another_consumer_saves(self):
        created = self.create(); writer = self.consumer(); barrier = Barrier(2)
        def write_versions():
            current = created; barrier.wait(timeout=10)
            for i in range(4):
                value = snapshot(); value['cards'][0]['note'] = 'parallel-'+str(i)
                current = self.save(current, value, store=writer)
            return current
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(write_versions); barrier.wait(timeout=10)
            for _ in range(4): backup.validate_package(self.data())
            self.assertEqual(pending.result()['analysisRevision'], 5)
        backup.validate_package(self.data())


if __name__ == '__main__':
    unittest.main()
