"""Real SQLite scene snapshots, rollback, fixed revisions and retained references."""
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
from threading import Barrier, Thread
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.model_library import ModelLibrary
from apps.api.model_validation import validate
from apps.api.scene_library import SceneLibrary, decode_scene_request, validate_local_snapshot
from tests.test_model_upload import glb


class SceneLibraryTests(unittest.TestCase):
    def test_organization_roundtrip_replay_fixed_history_and_permission_conditions(self):
        from tests.test_scene_organization import organization
        scene = self.create()
        body = self.body(scene, [self.item(), self.item()])
        body['snapshot']['organization'] = organization(
            [item['sceneModelInstanceId'] for item in body['snapshot']['instances']], self.model['versionId'])
        saved = self.save(body)
        self.assertEqual(self.opened(scene)['snapshot'], body['snapshot'])
        self.assertNotIn('organization', self.opened(scene, scene['sceneRevision'])['snapshot'])
        counts = self.counts()
        self.assertEqual(self.save(body)['sceneRevision'], saved['sceneRevision'])
        self.assertEqual(self.counts(), counts)
        self.allowed = False
        self.expect('SCENE_WRITE_FORBIDDEN', lambda: self.save(body))
        self.assertEqual(self.counts(), counts)
        self.allowed = True
        stale = copy.deepcopy(body); stale['clientRequestId'] = str(uuid4())
        self.expect('SCENE_CHANGED', lambda: self.save(stale))
        self.assertEqual(self.counts(), counts)

    def test_invalid_organization_does_not_create_partial_revision_or_audit(self):
        from tests.test_scene_organization import organization
        scene = self.create(); body = self.body(scene, [self.item(), self.item()])
        value = organization([item['sceneModelInstanceId'] for item in body['snapshot']['instances']], self.model['versionId'])
        value['groups'][0]['instanceIds'][0] = str(uuid4())
        body['snapshot']['organization'] = value; counts = self.counts()
        self.expect('INVALID_SCENE_ORGANIZATION', lambda: self.save(body))
        self.assertEqual(self.counts(), counts)
        self.assertEqual(self.opened(scene)['sceneRevision'], scene['sceneRevision'])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.models = ModelLibrary(self.root / 'library', 'fixture-project', str(uuid4()))
        source = glb(self.root / 'synthetic.glb')
        metadata = {'expectedSessionRevision': 'session:1',
                    'expectedLibraryRevision': self.models.listing()['libraryRevision'],
                    'clientRequestId': str(uuid4()), 'displayName': 'Synthetic model',
                    'sourceNote': 'Synthetic test geometry.', 'rightsDeclared': True}
        self.model = self.models.save_upload(source, metadata, 'fixture-admin', validate(source), lambda: None)
        self.scenes = SceneLibrary(self.models)
        self.allowed = True
        self.auth_calls = 0
        self.resource_calls = 0
        self.engineering_calls = 0

    def authorize(self):
        self.auth_calls += 1
        if not self.allowed:
            raise PreviewError(403, 'SCENE_WRITE_FORBIDDEN')

    def resources(self, snapshot):
        self.resource_calls += 1
        for item in snapshot['instances']:
            self.models.version(item['modelVersionId'])

    def engineering(self, snapshot, reviewed, changes):
        self.engineering_calls += 1
        self.assertEqual(reviewed, [])
        self.assertEqual(changes, [])
        self.assertTrue(all(item['rootBinding'] is None and not item['componentBindings']
                            for item in snapshot['instances']))

    def create(self, name='合成设备区', actor='fixture-admin', request_id=None):
        return self.scenes.create({'displayName': name, 'clientRequestId': request_id or str(uuid4())},
                                 actor, self.authorize, self.resources, self.engineering)

    def item(self, identifier=None):
        return {'sceneModelInstanceId': identifier or str(uuid4()), 'displayName': '测试模型',
                'modelVersionId': self.model['versionId'],
                'placement': {'position': {'mode': 'local', 'xM': 30, 'zM': -10},
                              'height': {'mode': 'local_relative', 'relativeHeightM': 2}, 'headingDeg': 25},
                'visible': True, 'positionLocked': False, 'rootBinding': None, 'componentBindings': []}

    def body(self, scene, instances=None):
        snapshot = copy.deepcopy(scene['snapshot'])
        if instances is not None:
            snapshot['instances'] = instances
        return {'sceneId': scene['sceneId'], 'expectedSceneRevision': scene['sceneRevision'],
                'clientRequestId': str(uuid4()), 'snapshot': snapshot,
                'reviewedEngineering': [], 'rootBindingChanges': []}

    def save(self, body, actor='fixture-admin', resources=None, engineering=None, authorize=None):
        return self.scenes.save(body, actor, authorize or self.authorize,
                                resources or self.resources, engineering or self.engineering)

    def opened(self, scene, revision=None):
        return self.scenes.open(scene['sceneId'], 'fixture-admin', self.authorize, revision)

    def uses(self, **overrides):
        return self.scenes.uses(self.model['versionId'], 'fixture-admin', self.authorize,
                                access_revision='grant:1', **overrides)

    def counts(self):
        with self.models.connect() as db:
            return {table: db.execute('select count(*) from ' + table).fetchone()[0]
                    for table in ('scenes', 'scene_revisions', 'scene_resource_uses', 'scene_audit', 'scene_requests')}

    def expect(self, code, function):
        with self.assertRaises(PreviewError) as caught:
            function()
        self.assertEqual(caught.exception.code, code)

    def test_create_save_reopen_and_old_snapshot_are_independent(self):
        scene = self.create()
        old_revision = scene['sceneRevision']
        body = self.body(scene, [self.item(), self.item()])
        saved = self.save(body)
        reopened = SceneLibrary(self.models).open(scene['sceneId'], 'fixture-admin', self.authorize)
        self.assertEqual(reopened['snapshot'], body['snapshot'])
        self.assertEqual(reopened['sceneRevision'], saved['sceneRevision'])
        self.assertEqual(self.opened(scene, old_revision)['snapshot']['instances'], [])
        self.assertEqual(reopened['resourceRefs'], [{'modelVersionId': self.model['versionId'],
            'sha256': self.model['sha256'], 'contentRevision': 'sha256:' + self.model['sha256']}])
        body['snapshot']['instances'][0]['displayName'] = 'Changed in caller only'
        self.assertEqual(self.opened(scene)['snapshot']['instances'][0]['displayName'], '测试模型')

    def test_two_writers_from_one_head_have_exactly_one_commit(self):
        scene = self.create()
        barrier = Barrier(2)
        results = []

        def write(x):
            request = self.body(scene, [self.item()])
            request['snapshot']['instances'][0]['placement']['position']['xM'] = x
            barrier.wait()
            try:
                self.save(request)
                results.append('saved')
            except PreviewError as error:
                results.append(error.code)

        workers = [Thread(target=write, args=(10,)), Thread(target=write, args=(20,))]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        self.assertCountEqual(results, ['saved', 'SCENE_CHANGED'])
        self.assertEqual(self.counts()['scene_revisions'], 2)
        self.assertEqual(self.counts()['scene_audit'], 2)

    def test_save_idempotency_precedes_stale_head_but_rechecks_authorization(self):
        scene = self.create()
        request = self.body(scene, [self.item()])
        first = self.save(request)
        counts = self.counts()
        self.assertEqual(self.save(request), first)
        self.assertEqual(self.counts(), counts)
        changed = copy.deepcopy(request)
        changed['snapshot']['displayName'] = 'Changed business body'
        self.expect('REQUEST_CONFLICT', lambda: self.save(changed))
        self.allowed = False
        self.expect('SCENE_WRITE_FORBIDDEN', lambda: self.save(request))
        self.assertEqual(self.counts(), counts)

    def test_request_namespace_is_project_actor_and_action(self):
        request_id = str(uuid4())
        first = self.create(request_id=request_id)
        self.assertEqual(self.create(request_id=request_id), first)
        second = self.create(actor='another-admin', request_id=request_id)
        self.assertNotEqual(first['sceneId'], second['sceneId'])
        request = self.body(first)
        request['clientRequestId'] = request_id
        self.save(request)
        self.assertEqual(self.counts()['scene_requests'], 3)

    def test_authorization_loss_at_final_commit_rolls_back_all_scene_tables(self):
        scene = self.create()
        before = self.counts()
        calls = []

        def authorize():
            calls.append(True)
            if len(calls) == 2:
                raise PreviewError(403, 'SCENE_WRITE_FORBIDDEN')

        self.expect('SCENE_WRITE_FORBIDDEN', lambda: self.save(self.body(scene, [self.item()]), authorize=authorize))
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.opened(scene)['sceneRevision'], scene['sceneRevision'])
        self.assertEqual(self.uses()['currentInstanceCount'], 0)

    def test_resource_failure_before_commit_rolls_back_head_audit_and_references(self):
        scene = self.create()
        before = self.counts()
        calls = []

        def changed_resource(snapshot):
            calls.append(True)
            if len(calls) == 2:
                raise PreviewError(409, 'RESOURCE_CHANGED')

        self.expect('RESOURCE_CHANGED', lambda: self.save(self.body(scene, [self.item()]), resources=changed_resource))
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.opened(scene)['snapshot']['instances'], [])

    def test_callbacks_are_required_and_receive_copies(self):
        scene = self.create()
        request = self.body(scene, [self.item()])
        self.expect('INVALID_REQUEST', lambda: self.scenes.save(request, 'admin', None, self.resources, self.engineering))

        def destructive_check(snapshot):
            snapshot['instances'].clear()

        self.save(request, resources=destructive_check)
        self.assertEqual(len(self.opened(scene)['snapshot']['instances']), 1)
        self.assertGreaterEqual(self.engineering_calls, 4)

    def test_current_and_retained_model_uses_survive_instance_removal(self):
        scene = self.create()
        self.save(self.body(scene, [self.item(), self.item()]))
        current = self.opened(scene)
        self.assertEqual(self.uses()['currentInstanceCount'], 2)
        self.assertEqual(self.uses()['retainedInstanceCount'], 0)
        self.assertEqual(self.uses()['retainedReferenceCount'], 0)
        self.save(self.body(current, []))
        uses = self.uses()
        self.assertEqual(uses['currentInstanceCount'], 0)
        self.assertEqual(uses['retainedInstanceCount'], 2)
        self.assertEqual(uses['retainedReferenceCount'], 2)
        self.assertEqual(uses['items'][0]['displayName'], '合成设备区')
        self.expect('RESOURCE_IN_USE', lambda: self.scenes.assert_model_unused(self.model['versionId'], self.authorize))
        self.assertEqual(len(self.models.listing()['items']), 1)

    def test_database_foreign_key_also_protects_retained_resource(self):
        scene = self.create()
        self.save(self.body(scene, [self.item()]))
        with self.assertRaises(sqlite3.IntegrityError):
            with self.models.connect() as db:
                db.execute('delete from versions where id=?', (self.model['versionId'],))

    def test_removed_instance_identifier_cannot_be_reused(self):
        scene = self.create()
        item = self.item()
        self.save(self.body(scene, [item]))
        current = self.opened(scene)
        self.save(self.body(current, []))
        self.expect('INSTANCE_ID_REUSED', lambda: self.save(self.body(self.opened(scene), [item])))

    def test_locked_instance_must_be_unlocked_to_move_or_remove(self):
        scene = self.create()
        item = self.item()
        item['positionLocked'] = True
        self.save(self.body(scene, [item]))
        current = self.opened(scene)
        move = self.body(current)
        move['snapshot']['instances'][0]['placement']['position']['xM'] += 1
        self.expect('INSTANCE_POSITION_LOCKED', lambda: self.save(move))
        self.expect('INSTANCE_POSITION_LOCKED', lambda: self.save(self.body(current, [])))
        move['snapshot']['instances'][0]['positionLocked'] = False
        self.save(move)
        self.assertFalse(self.opened(scene)['snapshot']['instances'][0]['positionLocked'])

    def test_fixed_view_only_reports_update_and_old_contents_remain(self):
        scene = self.create()
        self.save(self.body(scene, [self.item()]))
        status = self.scenes.head(scene['sceneId'], scene['sceneRevision'], 'admin', self.authorize)
        self.assertTrue(status['updateAvailable'])
        old = self.opened(scene, scene['sceneRevision'])
        self.assertEqual(old['snapshot']['instances'], [])
        self.assertNotEqual(old['headRevision'], old['sceneRevision'])

    def test_list_pagination_is_stable_bound_to_actor_grant_and_filters(self):
        for name in ['First area', 'Second area', 'Third area']:
            self.create(name)
        first = self.scenes.listing('admin', self.authorize, access_revision='grant:1', q='area', limit=1)
        second = self.scenes.listing('admin', self.authorize, access_revision='grant:1', q='area', limit=1, cursor=first['nextCursor'])
        self.assertNotEqual(first['items'][0]['sceneId'], second['items'][0]['sceneId'])
        for actor, grant, query in [('other', 'grant:1', 'area'), ('admin', 'grant:2', 'area'), ('admin', 'grant:1', 'First')]:
            self.expect('INVALID_REQUEST', lambda: self.scenes.listing(actor, self.authorize,
                access_revision=grant, q=query, limit=1, cursor=first['nextCursor']))
        self.create('Later area')
        self.expect('SNAPSHOT_EXPIRED', lambda: self.scenes.listing('admin', self.authorize,
            access_revision='grant:1', q='area', limit=1, cursor=first['nextCursor']))

    def test_model_uses_pagination_and_snapshot_expiration(self):
        for name in ['A', 'B']:
            scene = self.create(name)
            self.save(self.body(scene, [self.item()]))
        page = self.uses(limit=1)
        self.assertEqual(page['currentInstanceCount'], 2)
        self.assertEqual(len(page['items']), 1)
        self.assertIsNotNone(page['nextCursor'])
        next_page = self.uses(limit=1, cursor=page['nextCursor'])
        self.assertNotEqual(page['items'][0]['sceneId'], next_page['items'][0]['sceneId'])
        self.create('C')
        self.expect('SNAPSHOT_EXPIRED', lambda: self.uses(limit=1, cursor=page['nextCursor']))

    def test_history_counts_distinct_instances_separately_from_revision_references(self):
        scene = self.create()
        item = self.item()
        for x in (10, 20, 30):
            item['placement']['position']['xM'] = x
            self.save(self.body(self.opened(scene), [copy.deepcopy(item)]))
        uses = self.uses()
        self.assertEqual(uses['currentInstanceCount'], 1)
        self.assertEqual(uses['retainedInstanceCount'], 1)
        self.assertEqual(uses['retainedReferenceCount'], 2)
        self.assertEqual(uses['items'][0]['currentInstanceCount'], 1)
        self.assertEqual(uses['items'][0]['retainedInstanceCount'], 1)
        self.assertEqual(uses['items'][0]['retainedReferenceCount'], 2)
        self.save(self.body(self.opened(scene), []))
        removed = self.uses()
        self.assertEqual(removed['currentInstanceCount'], 0)
        self.assertEqual(removed['retainedInstanceCount'], 1)
        self.assertEqual(removed['retainedReferenceCount'], 3)
        self.assertEqual(self.uses(scope='retained')['retainedInstanceCount'], 1)
        self.assertEqual(self.uses(scope='current')['items'], [])

    def test_same_identifier_in_two_scenes_counts_two_instances_and_page_totals_match(self):
        shared_id = str(uuid4())
        scenes = []
        for name in ('Area A', 'Area B'):
            scene = self.create(name)
            scenes.append(scene)
            for x in (10, 20, 30):
                item = self.item(shared_id)
                item['placement']['position']['xM'] = x
                self.save(self.body(self.opened(scene), [item]))
        active = self.uses()
        self.assertEqual(active['currentInstanceCount'], 2)
        self.assertEqual(active['retainedInstanceCount'], 2)
        self.assertEqual(active['retainedReferenceCount'], 4)
        for scene in scenes:
            self.save(self.body(self.opened(scene), []))
        first = self.uses(limit=1)
        second = self.uses(limit=1, cursor=first['nextCursor'])
        for page in (first, second):
            self.assertEqual(page['currentInstanceCount'], 0)
            self.assertEqual(page['retainedInstanceCount'], 2)
            self.assertEqual(page['retainedReferenceCount'], 6)
            self.assertEqual(page['items'][0]['currentInstanceCount'], 0)
            self.assertEqual(page['items'][0]['retainedInstanceCount'], 1)
            self.assertEqual(page['items'][0]['retainedReferenceCount'], 3)
        items = first['items'] + second['items']
        self.assertNotEqual(items[0]['sceneId'], items[1]['sceneId'])
        self.assertEqual(sum(item['retainedInstanceCount'] for item in items), first['retainedInstanceCount'])
        self.assertEqual(sum(item['retainedReferenceCount'] for item in items), first['retainedReferenceCount'])

    def test_cursor_tampering_and_invalid_scope_are_rejected(self):
        self.expect('INVALID_REQUEST', lambda: self.scenes.listing('admin', self.authorize,
            access_revision='grant:1', cursor='untrusted'))
        self.expect('INVALID_REQUEST', lambda: self.uses(scope='all-projects'))

    def test_unknown_fields_duplicate_ids_and_nonfinite_coordinates_do_not_write(self):
        scene = self.create()
        before = self.counts()
        for alteration, code in [
            (lambda s: s.update(fileUrl='https://untrusted.invalid/model.glb'), 'INVALID_REQUEST'),
            (lambda s: s['instances'].append(copy.deepcopy(s['instances'][0])), 'DUPLICATE_INSTANCE'),
            (lambda s: s['instances'][0]['placement']['position'].update(xM=float('nan')), 'INVALID_REQUEST'),
            (lambda s: s['instances'][0]['placement']['position'].update(xM=10 ** 1000), 'INVALID_REQUEST'),
            (lambda s: s['instances'][0].update(bindingIssues=[]), 'INVALID_REQUEST'),
        ]:
            request = self.body(scene, [self.item()])
            alteration(request['snapshot'])
            self.expect(code, lambda: self.save(request))
            self.assertEqual(self.counts(), before)

    def test_instance_and_json_size_budgets_are_enforced(self):
        scene = self.create()
        self.expect('SCENE_LIMIT_EXCEEDED', lambda: self.save(self.body(scene, [self.item() for _ in range(101)])))
        self.expect('SCENE_LIMIT_EXCEEDED', lambda: decode_scene_request(b' ' * (1024 * 1024 + 1)))
        request = self.body(scene)
        nested = request['snapshot']
        for _ in range(30):
            nested['extra'] = {}
            nested = nested['extra']
        self.expect('SCENE_LIMIT_EXCEEDED', lambda: self.save(request))

    def test_strict_decoder_rejects_duplicate_json_keys_nonfinite_and_nonobject(self):
        for raw in [b'{"sceneId":1,"sceneId":2}', b'{"value":NaN}', b'[]', b'\xff']:
            self.expect('INVALID_REQUEST', lambda: decode_scene_request(raw))
        self.assertEqual(decode_scene_request(b'{"value":1}'), {'value': 1})

    def test_unimplemented_geography_and_engineering_fail_explicitly(self):
        scene = self.create()
        request = self.body(scene, [self.item()])
        request['snapshot']['coordinateFrame'] = {'mode': 'projected_site'}
        self.expect('SCENE_SCOPE_UNSUPPORTED', lambda: self.save(request))
        request = self.body(scene, [self.item()])
        request['snapshot']['instances'][0]['rootBinding'] = {'objectRef': {'entityUid': 'not-a-real-uid'}}
        self.expect('SCENE_SCOPE_UNSUPPORTED', lambda: self.save(request))
        self.assertFalse(self.scenes.capabilities()['supportsEngineeringBindings'])
        self.assertFalse(self.scenes.capabilities()['supportsGeographic'])

    def test_unknown_model_and_unavailable_read_scope_are_not_exposed(self):
        scene = self.create()
        request = self.body(scene, [self.item()])
        request['snapshot']['instances'][0]['modelVersionId'] = str(uuid4())
        self.expect('MODEL_NOT_FOUND', lambda: self.save(request))
        self.expect('NOT_FOUND_OR_FORBIDDEN', lambda: self.scenes.open(str(uuid4()), 'admin', self.authorize))
        self.allowed = False
        self.expect('SCENE_WRITE_FORBIDDEN', lambda: self.opened(scene))

    def test_initial_view_boolean_numbers_and_altered_frame_are_refused(self):
        scene = self.create()
        for alteration, code in [
            (lambda s: s['initialView'].update(eye=[0, 0, 0]), 'INVALID_REQUEST'),
            (lambda s: s['initialView'].update(eye=[True, 2, 3]), 'INVALID_REQUEST'),
            (lambda s: s['coordinateFrame'].update(frameRevision='different'), 'SCENE_SCOPE_UNSUPPORTED'),
        ]:
            request = self.body(scene)
            alteration(request['snapshot'])
            self.expect(code, lambda: self.save(request))

    def test_snapshot_and_reference_rows_are_immutable_and_old_model_tables_unchanged(self):
        scene = self.create()
        self.save(self.body(scene, [self.item()]))
        for statement in ["update scene_revisions set snapshot='{}'", 'delete from scene_revisions',
                          "update scene_resource_uses set instance_id='changed'", 'delete from scene_resource_uses']:
            with self.assertRaises(sqlite3.IntegrityError):
                with self.models.connect() as db:
                    db.execute(statement)
        self.assertEqual(self.models.version(self.model['versionId'])['bindings'], [])
        self.assertEqual(self.models.listing()['items'][0]['modelRevision'], 1)
        self.assertEqual(self.models.listing()['items'][0]['bindingCount'], 0)

    def test_read_rechecks_authorization_before_returning_private_snapshot(self):
        scene = self.create()
        calls = []

        def revoked_before_return():
            calls.append(True)
            if len(calls) == 2:
                raise PreviewError(403, 'NOT_FOUND_OR_FORBIDDEN')

        self.expect('NOT_FOUND_OR_FORBIDDEN', lambda: self.scenes.open(
            scene['sceneId'], 'admin', revoked_before_return))
        self.assertEqual(len(calls), 2)
        self.expect('INVALID_REQUEST', lambda: self.scenes.open(scene['sceneId'], 'admin', self.authorize, ''))

    def test_missing_resource_cannot_bypass_store_foreign_keys_with_empty_callback(self):
        scene = self.create()
        request = self.body(scene, [self.item()])
        request['snapshot']['instances'][0]['modelVersionId'] = str(uuid4())
        before = self.counts()
        self.expect('NOT_FOUND_OR_FORBIDDEN', lambda: self.save(request, resources=lambda _: None))
        self.assertEqual(self.counts(), before)

    def test_future_richer_snapshot_cannot_be_downgraded_or_clear_binding_issues(self):
        scene = self.create()
        snapshot = copy.deepcopy(scene['snapshot'])
        snapshot['bindingIssues'] = [{'reason': 'model_version_changed', 'blocking': True}]
        revision = 'scene:' + str(uuid4())
        with self.models.connect() as db:
            db.execute('insert into scene_revisions values (?,?,?,?,?)',
                       (revision, scene['sceneId'], json.dumps(snapshot), '[]', scene['savedAt']))
            db.execute('update scenes set head_revision=? where id=?', (revision, scene['sceneId']))
        request = self.body(scene)
        request['expectedSceneRevision'] = revision
        self.expect('INVALID_REQUEST', lambda: self.save(request))
        self.expect('INVALID_REQUEST', lambda: self.opened(scene))
        with self.models.connect() as db:
            self.assertEqual(db.execute('select head_revision from scenes where id=?',
                                        (scene['sceneId'],)).fetchone()[0], revision)

    def test_legacy_binding_revision_does_not_change_fixed_scene_content_identity(self):
        scene = self.create()
        self.save(self.body(scene, [self.item()]))
        fixed = self.opened(scene)
        self.models.bind({'modelVersionId': self.model['versionId'], 'componentKey': 'component:0',
            'entityUid': 'synthetic-cabinet', 'expectedEntityRevision': 'entity:1',
            'expectedHierarchyRevision': 'hierarchy:1', 'expectedModelRevision': 1,
            'clientRequestId': str(uuid4())}, 'fixture-admin', lambda: None)
        self.assertEqual(self.models.version(self.model['versionId'])['modelRevision'], 2)
        self.assertEqual(self.opened(scene)['sceneRevision'], fixed['sceneRevision'])
        self.assertEqual(self.opened(scene)['resourceRefs'], fixed['resourceRefs'])
        self.assertEqual(self.uses()['currentInstanceCount'], 1)

    def test_listing_revision_and_rows_share_one_read_snapshot_during_new_save(self):
        self.create('Earlier area')
        with self.models.connect() as db:
            db.execute('pragma journal_mode=wal')
        original = self.scenes._catalog

        def interleaved_save(db):
            catalog = original(db)
            self.create('Concurrent area')
            return catalog

        with patch.object(self.scenes, '_catalog', side_effect=interleaved_save):
            page = self.scenes.listing('admin', self.authorize, access_revision='grant:1')
        self.assertEqual([item['displayName'] for item in page['items']], ['Earlier area'])
        latest = self.scenes.listing('admin', self.authorize, access_revision='grant:1')
        self.assertEqual(len(latest['items']), 2)
        self.assertNotEqual(page['snapshotRevision'], latest['snapshotRevision'])


if __name__ == '__main__':
    unittest.main()
