"""Recoverable scene deletion keeps immutable content and enforces current scope."""
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.scene_library import SceneLibrary
from tests import test_scene_library as fixture


class SceneLifecycleTests(unittest.TestCase):
    setUp = fixture.SceneLibraryTests.setUp
    authorize = fixture.SceneLibraryTests.authorize
    resources = fixture.SceneLibraryTests.resources
    engineering = fixture.SceneLibraryTests.engineering
    create = fixture.SceneLibraryTests.create
    item = fixture.SceneLibraryTests.item
    body = fixture.SceneLibraryTests.body
    save = fixture.SceneLibraryTests.save
    opened = fixture.SceneLibraryTests.opened
    uses = fixture.SceneLibraryTests.uses
    expect = fixture.SceneLibraryTests.expect

    def request(self, scene, version=0):
        return {'sceneId': scene['sceneId'], 'expectedSceneRevision': scene['sceneRevision'],
                'expectedLifecycleRevision': version, 'clientRequestId': str(uuid4())}

    def change(self, scene, action='delete', version=0, body=None, authorize=None):
        return self.scenes.lifecycle(body or self.request(scene, version), 'fixture-admin',
                                     authorize or self.authorize, action=action)

    def listing(self, **options):
        return self.scenes.listing('fixture-admin', self.authorize, access_revision='grant:1', **options)

    def rows(self):
        with self.models.connect() as db:
            return {table: [tuple(row) for row in db.execute('select * from '+table)]
                    for table in ('scenes','scene_revisions','scene_resource_uses','scene_spatial_validations',
                                  'scene_terrain_uses','scene_requests','scene_audit','scene_lifecycle','scene_catalog')}

    def test_delete_restore_preserves_content_identity_and_retained_resources(self):
        created = self.create(); saved = self.save(self.body(created, [self.item()]))
        opened = self.opened(saved); before = self.rows()
        deleted = self.change(saved)
        self.assertEqual((deleted['state'], deleted['lifecycleRevision']), ('deleted', 1))
        self.assertEqual(self.listing()['items'], [])
        row = self.listing(state='deleted')['items'][0]
        self.assertEqual((row['sceneId'], row['lifecycleRevision']), (created['sceneId'], 1))
        self.expect('SCENE_DELETED', lambda: self.opened(saved))
        self.expect('SCENE_DELETED', lambda: self.opened(saved, created['sceneRevision']))
        self.expect('SCENE_DELETED', lambda: self.save(self.body(opened)))
        self.expect('SCENE_DELETED', lambda: self.scenes.head(saved['sceneId'], saved['sceneRevision'], 'fixture-admin', self.authorize))
        uses = self.uses()
        self.assertEqual((uses['currentInstanceCount'], uses['retainedInstanceCount'], uses['retainedReferenceCount']), (0, 1, 1))
        self.assertEqual(uses['items'][0]['sceneState'], 'deleted')
        self.expect('RESOURCE_IN_USE', lambda: self.scenes.assert_model_unused(self.model['versionId'], self.authorize))
        restored = self.change(saved, 'restore', 1)
        self.assertEqual((restored['state'], restored['lifecycleRevision']), ('active', 2))
        self.assertEqual(self.opened(saved)['snapshot'], opened['snapshot'])
        self.assertEqual(self.opened(saved, created['sceneRevision'])['snapshot'], created['snapshot'])
        self.assertEqual(self.uses()['currentInstanceCount'], 1)
        after = self.rows()
        for table in ('scenes','scene_revisions','scene_resource_uses','scene_spatial_validations','scene_terrain_uses'):
            self.assertEqual(before[table], after[table], table)
        self.assertEqual(len(after['scene_audit']), len(before['scene_audit'])+2)

    def test_replay_is_fixed_and_cannot_change_current_state_after_restore(self):
        scene = self.create(); body = self.request(scene)
        result = self.change(scene, body=body)
        before = self.rows(); self.assertEqual(self.change(scene, body=body), result)
        self.assertEqual(before, self.rows())
        self.change(scene, 'restore', 1)
        before = self.rows(); self.assertEqual(self.change(scene, body=body), result)
        self.assertEqual(before, self.rows()); self.assertEqual(len(self.listing()['items']), 1)
        altered = {**body, 'expectedLifecycleRevision': 2}
        self.expect('REQUEST_CONFLICT', lambda: self.change(scene, body=altered))
        self.allowed = False
        self.expect('SCENE_WRITE_FORBIDDEN', lambda: self.change(scene, body=body))

    def test_old_content_and_old_lifecycle_versions_are_refused(self):
        scene = self.create(); saved = self.save(self.body(scene, [self.item()]))
        self.expect('SCENE_CHANGED', lambda: self.change(scene))
        self.change(saved); self.change(saved, 'restore', 1)
        before = self.rows()
        self.expect('SCENE_CHANGED', lambda: self.change(saved, version=0))
        self.expect('SCENE_CHANGED', lambda: self.change(saved, 'restore', 1))
        self.assertEqual(before, self.rows())
        self.assertEqual(self.change(saved, version=2)['lifecycleRevision'], 3)

    def test_final_authorization_failure_rolls_back_state_audit_and_receipt(self):
        scene = self.create(); before = self.rows(); calls = 0
        def authorize():
            nonlocal calls
            calls += 1
            if calls == 2:raise PreviewError(403, 'SCENE_WRITE_FORBIDDEN')
        self.expect('SCENE_WRITE_FORBIDDEN', lambda: self.change(scene, authorize=authorize))
        self.assertEqual(before, self.rows())
        self.allowed = False
        self.expect('SCENE_WRITE_FORBIDDEN', lambda: self.change(scene))
        self.assertEqual(before, self.rows())

    def test_cross_scope_unknown_scene_and_invalid_fields_never_mutate(self):
        scene = self.create(); before = self.rows()
        with self.models.connect() as db:
            db.execute('update scenes set project_code=? where id=?', ('other-project', scene['sceneId']))
        self.expect('NOT_FOUND_OR_FORBIDDEN', lambda: self.change(scene))
        with self.models.connect() as db:db.execute('update scenes set project_code=? where id=?', (self.scenes.project_code, scene['sceneId']))
        for body in ({**self.request(scene), 'sceneId': str(uuid4())},):
            self.expect('NOT_FOUND_OR_FORBIDDEN', lambda: self.change(scene, body=body))
        for value in (True, -1, 1.5, '0', 2**53):
            body = {**self.request(scene), 'expectedLifecycleRevision': value}
            self.expect('INVALID_REQUEST', lambda: self.change(scene, body=body))
        for key in ('owner','projectCode','snapshot'):
            body = {**self.request(scene), key: 'untrusted'}
            self.expect('INVALID_REQUEST', lambda: self.change(scene, body=body))
        self.assertEqual(before, self.rows())

    def test_concurrent_delete_has_one_winner_and_one_version_conflict(self):
        scene = self.create(); barrier = Barrier(2)
        def attempt(_):
            body = self.request(scene); barrier.wait()
            try:return self.change(scene, body=body)['state']
            except PreviewError as error:return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:results = list(pool.map(attempt, range(2)))
        self.assertCountEqual(results, ['deleted','SCENE_CHANGED'])
        self.assertEqual(len(self.listing(state='deleted')['items']), 1)

    def test_catalog_cursor_is_bound_to_state_and_invalidated_by_lifecycle_change(self):
        scene = self.create('A'); self.create('B')
        first = self.listing(limit=1); self.assertIsNotNone(first['nextCursor'])
        self.expect('INVALID_REQUEST', lambda: self.listing(limit=1, state='deleted', cursor=first['nextCursor']))
        self.change(scene)
        self.expect('SNAPSHOT_EXPIRED', lambda: self.listing(limit=1, cursor=first['nextCursor']))
        self.assertEqual(self.listing(state='deleted', q='A')['items'][0]['sceneId'], scene['sceneId'])
        self.expect('INVALID_REQUEST', lambda: self.listing(state='all'))

    def test_legacy_schema_initialization_preserves_original_rows(self):
        self.create(); before = self.rows()
        with self.models.connect() as db:
            db.execute('drop trigger scene_lifecycle_identity');db.execute('drop trigger scene_lifecycle_no_delete')
            db.execute('drop table scene_lifecycle')
        SceneLibrary(self.models)
        self.assertEqual(before, self.rows())

    def test_lifecycle_history_cannot_be_erased_or_jump_versions(self):
        scene = self.create();self.change(scene)
        for statement in ('delete from scene_lifecycle', "update scene_lifecycle set revision=99,state='active'",
                          "update scene_lifecycle set scene_id='different',revision=2,state='active'"):
            with self.assertRaises(sqlite3.IntegrityError), self.models.connect() as db:db.execute(statement)

    def test_save_started_before_delete_restore_cannot_commit_an_old_edit(self):
        scene = self.create(); body = self.body(scene); body['snapshot']['displayName'] = 'Stale edit'
        changed = False
        def resources(snapshot):
            nonlocal changed
            self.resources(snapshot)
            if not changed:
                changed = True
                self.change(scene); self.change(scene, 'restore', 1)
        self.expect('SCENE_CHANGED', lambda: self.save(body, resources=resources))
        self.assertEqual(self.opened(scene)['snapshot'], scene['snapshot'])
        body['expectedLifecycleRevision'] = 2
        self.assertEqual(self.save(body)['sceneId'], scene['sceneId'])

    def test_create_replay_cannot_reopen_a_deleted_scene(self):
        request = str(uuid4()); scene = self.create(request_id=request); self.change(scene)
        self.expect('SCENE_DELETED', lambda: self.create(request_id=request))
