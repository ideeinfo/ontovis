"""Real same-origin HTTP/SQLite/model files with synthetic OntoBase authority.

Model upload and calibration use the public service. Engineering reads use the
existing live wire contract and the actual Reader/Validator, never a fake check.
No real account, business data, production service or GIS fixture is used.
"""
import copy
from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.model_validation import validate
from apps.api.session_http import handler_type
from apps.api.workbench_server import WorkbenchSessions
from tests import test_project_model_http as project_http
from tests import test_scene_engineering as engineering
from tests import test_scene_engineering_http as object_http
from tests import test_scene_http as scene_http
from tests.test_model_upload import glb


SCENES = '/api/workbench/scenes'
SECOND_CHILD = 'synthetic-device-B'


class BindingAuthority(object_http.ObjectAuthority):
    def __init__(self, base):
        super().__init__(base)
        source = self.engineering
        source.objects[SECOND_CHILD] = source.object(SECOND_CHILD, engineering.OTHER_CTX)
        source.parents[SECOND_CHILD] = engineering.OTHER_ROOT
        source.relations[SECOND_CHILD, engineering.OTHER_ROOT] = source.relation(SECOND_CHILD, engineering.OTHER_ROOT)


class SceneBindingsHttpTests(unittest.TestCase):
    request = project_http.ProjectModelHttpTests.request
    login = project_http.ProjectModelHttpTests.login
    authority = project_http.ProjectModelHttpTests.authority
    listing = project_http.ProjectModelHttpTests.listing
    metadata = project_http.ProjectModelHttpTests.metadata
    upload = project_http.ProjectModelHttpTests.upload
    calibration = project_http.ProjectModelHttpTests.calibration
    calibrate = project_http.ProjectModelHttpTests.calibrate
    model = project_http.ProjectModelHttpTests.model
    expect = project_http.ProjectModelHttpTests.expect

    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.sessions = WorkbenchSessions('http://127.0.0.1:1234', engineering.PROJECT,
            engineering.CTX, library_root=self.root/'private',
            ontobase_connection_id=engineering.CONNECTION, factory=BindingAuthority)
        self.data = glb(self.root/'synthetic.glb').read_bytes()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler_type(self.sessions, scene_http.ORIGIN, development=True))
        self.thread = Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.addCleanup(self.server.server_close); self.addCleanup(self.thread.join); self.addCleanup(self.server.shutdown)
        self.admin = self.login('synthetic-admin')
        self.version = self.upload_calibrated()
        self.component_key = self.version['components'][0]['componentKey']

    def upload_calibrated(self, asset=None):
        metadata = self.metadata(**({'modelAssetId': asset} if asset else {}))
        status, raw, _ = self.upload(metadata)
        self.assertEqual(status, 200, raw); self.assertFalse(raw['canPlace'])
        status, calibrated, _ = self.calibrate(self.calibration(raw))
        self.assertEqual(status, 200, calibrated); self.assertTrue(calibrated['canPlace'])
        return calibrated

    @staticmethod
    def ref(uid):
        return {'ontobaseConnectionId': engineering.CONNECTION, 'projectCode': engineering.PROJECT, 'entityUid': uid}

    def item(self, name, root=None, version=None):
        return {'sceneModelInstanceId': str(uuid4()), 'displayName': name,
            'modelVersionId': (version or self.version)['modelVersionId'],
            'placement': {'position': {'mode': 'local', 'xM': 10, 'zM': 20},
                'height': {'mode': 'local_relative', 'relativeHeightM': 0}, 'headingDeg': 30},
            'visible': True, 'positionLocked': False,
            'rootBinding': {'objectRef': self.ref(root)} if root else None, 'componentBindings': []}

    def create(self):
        status, scene, _ = self.request(SCENES+'/create', {'displayName': '合成双设备场景', 'clientRequestId': str(uuid4())})
        self.assertEqual(status, 200, scene)
        return scene

    def opened(self, scene, revision=None, **options):
        body = {'sceneId': scene['sceneId']}
        if revision is not None: body['sceneRevision'] = revision
        return self.request(SCENES+'/open', body, **options)

    def open_ok(self, scene, revision=None, **options):
        status, value, _ = self.opened(scene, revision, **options)
        self.assertEqual(status, 200, value)
        return value

    def check(self, scene, candidate=None, **options):
        return self.request(SCENES+'/check', {'kind': 'validate', 'sceneId': scene['sceneId'],
            'expectedSceneRevision': scene['sceneRevision'], 'snapshot': candidate or scene['snapshot']}, **options)

    def checked_body(self, scene, candidate=None):
        status, value, _ = self.check(scene, candidate)
        self.assertEqual(status, 200, value)
        return {'sceneId': scene['sceneId'], 'expectedSceneRevision': scene['sceneRevision'],
            'clientRequestId': str(uuid4()), 'snapshot': value['proposedSnapshot'],
            'reviewedEngineering': value['reviewedEngineering'], 'rootBindingChanges': value['rootBindingChanges']}

    def saved(self, scene, candidate=None):
        status, value, _ = self.request(SCENES+'/save', self.checked_body(scene, candidate))
        self.assertEqual(status, 200, value)
        return self.open_ok(scene)

    def bound_scene(self, *, nested=False):
        scene = self.create(); roots_only = copy.deepcopy(scene['snapshot'])
        roots_only['instances'] = [self.item('设备 A', engineering.CABINET if nested else engineering.ROOT),
                                   self.item('设备 B', engineering.OTHER_ROOT)]
        scene = self.saved(scene, roots_only)
        root_revision = scene['sceneRevision']
        candidate = copy.deepcopy(scene['snapshot'])
        for item, uid in zip(candidate['instances'], (engineering.CHILD, SECOND_CHILD)):
            item['componentBindings'] = [{'objectRef': self.ref(uid), 'componentKeys': [self.component_key]}]
        return self.saved(scene, candidate), root_revision

    def counts(self):
        with self.sessions.library.connect() as db:
            return {name: db.execute('select count(*) from '+name).fetchone()[0]
                for name in ('scene_revisions', 'scene_audit', 'scene_requests', 'scene_resource_uses', 'scene_spatial_validations')}

    def test_two_instances_share_resource_but_keep_distinct_current_and_retained_bindings(self):
        scene, root_revision = self.bound_scene()
        self.assertIsNone(self.sessions.model)
        self.assertTrue(scene['capabilities']['supportsEngineeringBindings'])
        self.assertEqual(scene['capabilities']['scope'], 'project_scenes')
        self.assertEqual(scene['validation']['scope'], 'local_plane_bound')
        instances = scene['snapshot']['instances']
        self.assertEqual({item['modelVersionId'] for item in instances}, {self.version['modelVersionId']})
        self.assertEqual([item['componentBindings'][0]['objectRef']['entityUid'] for item in instances], [engineering.CHILD, SECOND_CHILD])
        self.assertEqual({tuple(item['componentBindings'][0]['componentKeys']) for item in instances}, {(self.component_key,)})
        self.assertEqual(len(scene['validation']['engineeringExpectations']), 4)
        old = self.open_ok(scene, root_revision)
        self.assertEqual(old['sceneRevision'], root_revision)
        self.assertTrue(all(item['componentBindings'] == [] for item in old['snapshot']['instances']))
        self.assertNotIn('privateServerPath', repr(scene))

    def test_nested_non_turbine_root_accepts_actual_descendant(self):
        self.authority().engineering.objects[engineering.CABINET]['objectKind'] = 'control_cabinet'
        scene, _ = self.bound_scene(nested=True)
        self.assertEqual(scene['snapshot']['instances'][0]['rootBinding']['objectRef']['entityUid'], engineering.CABINET)
        self.assertEqual(scene['validation']['bindingIssues'], [])

    def test_same_instance_component_key_cannot_be_claimed_by_two_objects(self):
        scene, _ = self.bound_scene(); before = self.counts()
        candidate = copy.deepcopy(scene['snapshot'])
        candidate['instances'][0]['componentBindings'].append({'objectRef': self.ref(engineering.CABINET),
            'componentKeys': [self.component_key]})
        self.expect(self.check(scene, candidate), 422, 'INVALID_REQUEST')
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.open_ok(scene)['sceneRevision'], scene['sceneRevision'])

    def test_definition_wrong_installation_and_sibling_subtree_cannot_be_bound(self):
        scene, _ = self.bound_scene(nested=True); before = self.counts()
        for uid in ('definition', engineering.OTHER_ROOT, engineering.ROOT):
            with self.subTest(uid=uid):
                candidate = copy.deepcopy(scene['snapshot'])
                candidate['instances'][0]['componentBindings'] = [{'objectRef': self.ref(uid), 'componentKeys': [self.component_key]}]
                self.expect(self.check(scene, candidate), 409, 'ENGINEERING_CHANGED')
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.open_ok(scene)['sceneRevision'], scene['sceneRevision'])

    def test_forged_entity_hierarchy_or_context_review_never_advances_head(self):
        scene, _ = self.bound_scene(); body = self.checked_body(scene); before = self.counts()
        for field, value in [('expectedEntityRevision', 'forged:1'),
                             ('expectedHierarchyRevision', engineering.CTX+':999'),
                             ('installationContextId', engineering.OTHER_CTX)]:
            with self.subTest(field=field):
                changed = copy.deepcopy(body); changed['clientRequestId'] = str(uuid4())
                selected = next(item for item in changed['reviewedEngineering']
                                if item['ref']['entityUid'] == engineering.CHILD)
                self.assertNotEqual(selected[field], value)
                selected[field] = value
                self.expect(self.request(SCENES+'/save', changed), 409, 'ENGINEERING_CHANGED')
        self.assertEqual(self.counts(), before)

    def test_model_replacement_keeps_other_instance_and_retains_review_issue_until_explicit_rebind(self):
        scene, _ = self.bound_scene(); candidate = self.upload_calibrated(self.version['modelAssetId'])
        target = scene['snapshot']['instances'][0]['sceneModelInstanceId']; before = self.counts()
        status, preview, _ = self.request(SCENES+'/replacement-check', {'kind': 'model',
            'sceneId': scene['sceneId'], 'expectedSceneRevision': scene['sceneRevision'],
            'snapshot': scene['snapshot'], 'sceneModelInstanceId': target,
            'candidateModelVersionId': candidate['modelVersionId']})
        self.assertEqual(status, 200, preview)
        self.assertEqual(self.counts(), before)  # cancelling the preview is no write
        self.assertEqual(self.open_ok(scene)['snapshot'], scene['snapshot'])
        self.assertEqual(preview['proposedSnapshot']['instances'][0]['componentBindings'], [])
        self.assertEqual(preview['proposedSnapshot']['instances'][1], scene['snapshot']['instances'][1])
        self.assertEqual(preview['validation']['bindingIssues'][0]['kind'], 'model_version_changed')
        body = {'sceneId': scene['sceneId'], 'expectedSceneRevision': scene['sceneRevision'],
            'clientRequestId': str(uuid4()), 'snapshot': preview['proposedSnapshot'],
            'spatialChange': preview['spatialChange'], 'reviewedEngineering': preview['reviewedEngineering'],
            'rootBindingChanges': preview['rootBindingChanges']}
        missing = copy.deepcopy(body)
        missing['reviewedEngineering'] = [item for item in missing['reviewedEngineering'] if item['ref']['entityUid'] != engineering.CHILD]
        self.expect(self.request(SCENES+'/save', missing), 409, 'ENGINEERING_CHANGED')
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.request(SCENES+'/save', body)[0], 200)
        changed = self.open_ok(scene)
        self.assertEqual(changed['snapshot']['instances'][1], scene['snapshot']['instances'][1])
        self.assertEqual(changed['validation']['bindingIssues'][0]['objectRef']['entityUid'], engineering.CHILD)
        rebound = copy.deepcopy(changed['snapshot'])
        rebound['instances'][0]['componentBindings'] = [{'objectRef': self.ref(engineering.CHILD), 'componentKeys': [self.component_key]}]
        self.assertEqual(self.saved(changed, rebound)['validation']['bindingIssues'], [])
        self.assertEqual(self.open_ok(scene, scene['sceneRevision'])['snapshot'], scene['snapshot'])

    def test_ordinary_component_removal_requires_review_of_removed_object(self):
        scene, _ = self.bound_scene(); candidate = copy.deepcopy(scene['snapshot'])
        candidate['instances'][0]['componentBindings'] = []
        body = self.checked_body(scene, candidate); before = self.counts()
        self.assertIn(engineering.CHILD, [item['ref']['entityUid'] for item in body['reviewedEngineering']])
        missing = copy.deepcopy(body)
        missing['reviewedEngineering'] = [item for item in missing['reviewedEngineering'] if item['ref']['entityUid'] != engineering.CHILD]
        self.expect(self.request(SCENES+'/save', missing), 409, 'ENGINEERING_CHANGED')
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.request(SCENES+'/save', body)[0], 200)

    def test_root_switch_requires_exact_removal_consent_and_clears_only_target(self):
        scene, _ = self.bound_scene(); candidate = copy.deepcopy(scene['snapshot'])
        candidate['instances'][0].update(rootBinding={'objectRef': self.ref(engineering.CABINET)}, componentBindings=[])
        body = self.checked_body(scene, candidate); before = self.counts()
        self.assertEqual(len(body['rootBindingChanges']), 1)
        for declaration in ([], [{**body['rootBindingChanges'][0], 'reviewedRemovedBindingsDigest': '0'*64}]):
            invalid = copy.deepcopy(body); invalid['rootBindingChanges'] = declaration
            self.expect(self.request(SCENES+'/save', invalid), 409, 'ENGINEERING_CHANGED')
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.request(SCENES+'/save', body)[0], 200)
        current = self.open_ok(scene)
        self.assertEqual(current['snapshot']['instances'][1], scene['snapshot']['instances'][1])

    def test_open_engineering_drift_blocks_without_mutating_old_revision_then_explicit_review_repairs(self):
        scene, _ = self.bound_scene(); before = self.counts(); source = self.authority().engineering
        stale = self.checked_body(scene)
        source.objects[engineering.CHILD]['entityRevision'] += '-new'
        source.contexts[engineering.CTX]['hierarchyRevision'] = engineering.CTX+':8'
        opened = self.open_ok(scene, scene['sceneRevision'])
        self.assertEqual(opened['snapshot'], scene['snapshot'])
        self.assertTrue(opened['validation']['bindingIssues'])
        self.assertEqual(self.counts(), before)
        self.expect(self.request(SCENES+'/save', stale), 409, 'ENGINEERING_CHANGED')
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.saved(scene)['validation']['bindingIssues'], [])
        self.assertTrue(self.open_ok(scene, scene['sceneRevision'])['validation']['bindingIssues'])

    def test_read_only_member_can_open_but_cannot_persist_or_replay_writes(self):
        scene, _ = self.bound_scene(); body = self.checked_body(scene); before = self.counts()
        member = self.login('synthetic-reader'); self.authority(member).role = 'reader'
        opened = self.open_ok(scene, client=member)
        self.assertFalse(opened['capabilities']['canWrite'])
        self.expect(self.request(SCENES+'/save', body, client=member), 403, 'SCENE_WRITE_FORBIDDEN')
        self.assertEqual(self.counts(), before)
        self.expect(self.opened(scene, client=False), 401, 'SESSION_EXPIRED')

    def test_permission_revoked_on_final_reader_pass_rolls_back_all_sqlite_records(self):
        scene, _ = self.bound_scene(); body = self.checked_body(scene); before = self.counts()
        account = self.authority(); reads = 0
        def revoke(source, method, path, request):
            nonlocal reads
            if method == 'POST' and path.endswith('/objects/resolve') and request == {'entityUids': [engineering.CHILD], 'resolutionMode': 'live'}:
                reads += 1
                if reads == 2: account.allowed = False
        account.engineering.after = revoke
        self.expect(self.request(SCENES+'/save', body), 403, 'FORBIDDEN')
        self.assertEqual(reads, 2)
        self.assertEqual(self.counts(), before)

    def test_idempotent_replay_rechecks_current_grant_but_not_advanced_head_or_new_engineering(self):
        scene, _ = self.bound_scene(); body = self.checked_body(scene)
        status, first, _ = self.request(SCENES+'/save', body); self.assertEqual(status, 200, first)
        after = self.counts(); self.authority().engineering.calls.clear()
        again = self.request(SCENES+'/save', body)
        self.assertEqual(again[0], 200, again[1]); self.assertEqual(again[1]['sceneRevision'], first['sceneRevision'])
        self.assertEqual(self.authority().engineering.calls, [])
        self.assertEqual(self.counts(), after)
        changed = copy.deepcopy(body); changed['snapshot']['displayName'] = '不同请求内容'
        self.expect(self.request(SCENES+'/save', changed), 409, 'REQUEST_CONFLICT')
        old_head = copy.deepcopy(body); old_head['clientRequestId'] = str(uuid4())
        self.expect(self.request(SCENES+'/save', old_head), 409, 'SCENE_CHANGED')
        self.authority().allowed = False
        self.expect(self.request(SCENES+'/save', body), 403, 'FORBIDDEN')
        self.assertEqual(self.counts(), after)

    def test_only_calibrated_project_resource_can_bind_and_legacy_unbound_remains_readable(self):
        status, raw, _ = self.upload(); self.assertEqual(status, 200, raw)
        scene = self.create(); candidate = copy.deepcopy(scene['snapshot'])
        candidate['instances'] = [self.item('未校准设备', engineering.ROOT, raw)]
        self.expect(self.check(scene, candidate), 409, 'MODEL_CALIBRATION_REQUIRED')
        source = glb(self.root/'legacy.glb')
        legacy = self.sessions.library.save_upload(source, {'expectedSessionRevision': 'synthetic:1',
            'expectedLibraryRevision': self.sessions.library.listing()['libraryRevision'], 'clientRequestId': str(uuid4()),
            'displayName': 'Synthetic legacy', 'sourceNote': 'Synthetic old-resource fixture', 'rightsDeclared': True},
            'synthetic-admin', validate(source), lambda: None)
        candidate['instances'] = [self.item('已有局部模型', version={'modelVersionId': legacy['versionId']})]
        legacy_scene = self.saved(scene, candidate)
        self.assertEqual(self.open_ok(legacy_scene)['snapshot'], candidate)
        candidate['instances'][0]['rootBinding'] = {'objectRef': self.ref(engineering.ROOT)}
        self.expect(self.check(legacy_scene, candidate), 409, 'MODEL_CALIBRATION_REQUIRED')

    def test_direct_engineering_401_discards_scene_and_invalidates_current_session(self):
        scene, _ = self.bound_scene()
        def expired(*args): raise PreviewError(401, 'SESSION_EXPIRED')
        self.authority().engineering.request = expired
        self.expect(self.opened(scene), 401, 'SESSION_EXPIRED')
        self.assertNotIn(self.admin['cookie'].split('=', 1)[1], self.sessions.rows)


if __name__ == '__main__': unittest.main()
