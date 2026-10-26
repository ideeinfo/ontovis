"""Editable model labels retain fixed geometry, revisions and scene references."""
import sqlite3
from threading import Barrier, Thread
import unittest
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.project_model_library import ProjectModelLibrary
from tests import test_project_model_library as project


class ModelInfoTests(unittest.TestCase):
    def setUp(self):
        self.fixture = project.ProjectModelLibraryTests()
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.models, self.library, self.guard = self.fixture.models, self.fixture.old, self.fixture.guard
        self.version = self.fixture.calibrate(self.fixture.upload())

    def body(self, **changes):
        return {'modelAssetId': self.version['modelAssetId'], 'modelVersionId': self.version['modelVersionId'],
            'expectedAssetRevision': self.fixture.model(self.version)['assetRevision'], 'clientRequestId': str(uuid4()),
            'displayName': '合成模型 · 外观版', 'purpose': 'environment', 'description': '人工说明\n第二行', **changes}

    def save(self, body=None, guard=None):
        return self.models.save_info(body or self.body(), 'fixture-admin', guard or self.guard)

    def expect(self, code, action):
        with self.assertRaises(PreviewError) as caught: action()
        self.assertEqual(caught.exception.code, code)

    def state(self):
        with self.library.connect() as db:
            return {table: [tuple(row) for row in db.execute('select * from ' + table)] for table in
                ('project_model_assets', 'project_model_info_revisions', 'project_model_requests', 'project_model_audit', 'library')}

    def test_edit_is_visible_on_every_version_and_search_without_changing_fixed_content(self):
        with self.library.connect() as db:
            original = {table: [tuple(row) for row in db.execute('select * from ' + table)] for table in
                        ('versions', 'project_model_versions')}
        files = {p.name: p.read_bytes() for p in (self.library.root / 'files').iterdir()}
        before = self.fixture.listing(); saved = self.save()
        self.assertNotEqual(saved['assetRevision'], self.version['assetRevision'])
        self.assertNotEqual(saved['libraryRevision'], before['libraryRevision'])
        self.assertEqual(saved['versionDisplayName'], self.version['displayName'])
        listing = self.fixture.listing(q='外观版', purpose='environment')
        self.assertEqual(len(listing['items']), 1)
        asset = listing['items'][0]
        self.assertEqual((asset['displayName'], asset['description']), ('合成模型 · 外观版', '人工说明\n第二行'))
        self.assertEqual(len(asset['versions']), 2)
        for version in asset['versions']:
            self.assertEqual(version['displayName'], asset['displayName'])
            value = self.fixture.model(version)
            self.assertEqual(value['assetRevision'], saved['assetRevision'])
            self.assertEqual(value['description'], saved['description'])
        self.assertFalse(self.fixture.listing(q='合成设备')['items'])
        with self.library.connect() as db:
            for table, rows in original.items(): self.assertEqual([tuple(row) for row in db.execute('select * from ' + table)], rows)
        self.assertEqual(files, {p.name: p.read_bytes() for p in (self.library.root / 'files').iterdir()})
        reopened = ProjectModelLibrary(self.library)
        self.assertEqual(reopened.model(saved['modelAssetId'], saved['modelVersionId'], self.guard),
                         {k: v for k, v in saved.items() if k != 'libraryRevision'})

    def test_stale_head_rejected_and_same_request_replay_never_overwrites_later_information(self):
        body = self.body(); first = self.save(body); second = self.save(self.body(displayName='第二次修改'))
        self.assertEqual(self.save(body), first)
        self.assertEqual(self.fixture.model(second)['displayName'], '第二次修改')
        self.expect('MODEL_ASSET_CHANGED', lambda: self.save({**body, 'clientRequestId': str(uuid4())}))
        self.expect('REQUEST_CONFLICT', lambda: self.save({**body, 'description': '改变正文'}))
        with self.library.connect() as db:
            self.assertEqual(db.execute('select count(*) from project_model_info_revisions').fetchone()[0], 2)

    def test_final_authorization_failure_rolls_back_heads_history_audit_and_receipts(self):
        before = self.state(); calls = 0
        def guard():
            nonlocal calls
            calls += 1
            if calls == 3: raise PreviewError(403, 'MODEL_WRITE_FORBIDDEN')
        self.expect('MODEL_WRITE_FORBIDDEN', lambda: self.save(guard=guard))
        self.assertEqual(self.state(), before)
        body = self.body(); self.save(body); self.guard.allowed = False
        self.expect('MODEL_WRITE_FORBIDDEN', lambda: self.save(body))

    def test_simultaneous_updates_have_one_winner(self):
        body = self.body(); barrier = Barrier(2); results = []
        def run():
            barrier.wait()
            try: self.save({**body, 'clientRequestId': str(uuid4())}); results.append('ok')
            except PreviewError as error: results.append(error.code)
        threads = [Thread(target=run) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(8); self.assertFalse(thread.is_alive())
        self.assertCountEqual(results, ['ok', 'MODEL_ASSET_CHANGED'])

    def test_other_assets_and_scopes_are_rejected_and_unrelated_edit_does_not_conflict(self):
        body = self.body(); other = self.fixture.upload()
        self.expect('NOT_FOUND_OR_FORBIDDEN', lambda: self.save({**body, 'modelVersionId': other['modelVersionId']}))
        self.expect('NOT_FOUND_OR_FORBIDDEN', lambda: self.save({**body, 'modelAssetId': str(uuid4())}))
        self.save(body)
        with self.library.connect() as db:
            db.execute('update project_model_assets set project_code=? where id=?', ('other-project', body['modelAssetId']))
        self.expect('NOT_FOUND_OR_FORBIDDEN', lambda: self.save({**body, 'clientRequestId': str(uuid4())}))

    def test_invalid_info_is_bounded_and_never_partially_written(self):
        body = self.body(); before = self.state()
        for changes in ({'displayName': ''}, {'displayName': 'x'*201}, {'displayName': 'x\x00'},
                        {'purpose': 'unknown'}, {'purpose': []}, {'description': 'x'*2001},
                        {'description': '\x00'}, {'description': '\ud800'}, {'equipmentUid': 'untrusted'},
                        {'modelAssetId': 'invalid'}, {'expectedAssetRevision': ''}, {'clientRequestId': 'invalid'}):
            with self.subTest(changes=repr(changes)):
                self.expect('INVALID_REQUEST', lambda: self.save({**body, **changes}))
                self.assertEqual(self.state(), before)

    def test_information_history_is_immutable_and_retains_previous_labels(self):
        body = self.body(); self.save(body)
        with self.library.connect() as db:
            row = db.execute('select * from project_model_info_revisions').fetchone()
            self.assertIn(self.version['displayName'], row['previous_info'])
            for sql in ('delete from project_model_info_revisions', 'update project_model_info_revisions set name=name'):
                with self.assertRaises(sqlite3.IntegrityError): db.execute(sql)


if __name__ == '__main__': unittest.main()
