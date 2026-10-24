"""Fixed-revision scene location through real HTTP and private SQLite/GLB.

Authority is synthetic current-user OntoBase wire data. Resource upload,
calibration, binding checks, Reader and location resolution are the actual code.
"""
import copy
import json
import math
from threading import Event, Thread
import unittest
from uuid import uuid4

from tests import test_scene_bindings_http as bindings
from tests import test_scene_engineering as engineering


LOCATE = bindings.SCENES+'/locate'


class SceneLocationHttpTests(unittest.TestCase):
    setUp = bindings.SceneBindingsHttpTests.setUp
    request = bindings.SceneBindingsHttpTests.request
    login = bindings.SceneBindingsHttpTests.login
    authority = bindings.SceneBindingsHttpTests.authority
    listing = bindings.SceneBindingsHttpTests.listing
    metadata = bindings.SceneBindingsHttpTests.metadata
    upload = bindings.SceneBindingsHttpTests.upload
    calibration = bindings.SceneBindingsHttpTests.calibration
    calibrate = bindings.SceneBindingsHttpTests.calibrate
    upload_calibrated = bindings.SceneBindingsHttpTests.upload_calibrated
    expect = bindings.SceneBindingsHttpTests.expect
    ref = staticmethod(bindings.SceneBindingsHttpTests.ref)
    item = bindings.SceneBindingsHttpTests.item
    create = bindings.SceneBindingsHttpTests.create
    opened = bindings.SceneBindingsHttpTests.opened
    open_ok = bindings.SceneBindingsHttpTests.open_ok
    check = bindings.SceneBindingsHttpTests.check
    checked_body = bindings.SceneBindingsHttpTests.checked_body
    saved = bindings.SceneBindingsHttpTests.saved
    bound_scene = bindings.SceneBindingsHttpTests.bound_scene
    counts = bindings.SceneBindingsHttpTests.counts

    def location_body(self, scene, uid=engineering.CHILD, **changes):
        return {'sceneId': scene['sceneId'], 'sceneRevision': scene['sceneRevision'],
            'selectedObjectRef': self.ref(uid), 'contextEpoch': 'synthetic-selection:1', **changes}

    def locate(self, scene, uid=engineering.CHILD, *, choice=None, client=None, **changes):
        body = self.location_body(scene, uid, **changes)
        if choice is not None: body['representationChoice'] = choice
        return self.request(LOCATE, body, client=client)

    def location(self, scene, uid=engineering.CHILD, **options):
        status, value, headers = self.locate(scene, uid, **options)
        self.assertEqual(status, 200, value)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertNotIn('privateServerPath', json.dumps(value))
        self.assertNotIn(str(self.root), json.dumps(value))
        return value

    def test_direct_component_and_whole_root_use_fixed_actual_calibrated_resource(self):
        scene, _ = self.bound_scene(); before = self.counts()
        selected = self.location(scene)
        self.assertEqual((selected['status'], selected['mode']), ('located', 'direct'))
        self.assertEqual(selected['selectedObject']['entityUid'], engineering.CHILD)
        self.assertEqual(selected['hostObject']['entityUid'], engineering.CHILD)
        self.assertEqual(selected['modelVersionId'], self.version['modelVersionId'])
        self.assertEqual(selected['componentKeys'], [self.component_key])
        self.assertEqual(selected['contextEpoch'], 'synthetic-selection:1')
        self.assertEqual(selected['sessionRevision'], self.admin['revision'])
        self.assertTrue(all(math.isfinite(number) for point in selected['worldBounds'] for number in point))
        root = self.location(scene, engineering.ROOT)
        self.assertEqual(root['mode'], 'direct'); self.assertEqual(root['componentKeys'], [])
        other = self.location(scene, bindings.SECOND_CHILD)
        self.assertEqual(other['sceneModelInstanceId'], scene['snapshot']['instances'][1]['sceneModelInstanceId'])
        self.assertNotEqual(other['sceneModelInstanceId'], selected['sceneModelInstanceId'])
        self.assertEqual(self.counts(), before)

    def test_child_without_geometry_uses_nearest_recorded_cabinet_and_keeps_selected_identity(self):
        scene, _ = self.bound_scene(); candidate = copy.deepcopy(scene['snapshot'])
        candidate['instances'][0]['componentBindings'][0]['objectRef'] = self.ref(engineering.CABINET)
        scene = self.saved(scene, candidate); before = self.counts()
        value = self.location(scene)
        self.assertEqual((value['status'], value['mode']), ('located', 'ancestor'))
        self.assertEqual(value['selectedObject']['entityUid'], engineering.CHILD)
        self.assertEqual(value['hostObject']['entityUid'], engineering.CABINET)
        self.assertEqual(value['relationshipStatus'], 'assumed')
        self.assertEqual(value['componentKeys'], [self.component_key])
        self.assertEqual(self.counts(), before)

    def test_multiple_representations_require_exact_instance_and_version_choice(self):
        scene, _ = self.bound_scene(); candidate = copy.deepcopy(scene['snapshot'])
        extra = self.item('第二个表示', engineering.ROOT)
        extra['placement']['position']['xM'] = 200
        candidate['instances'].append(extra); scene = self.saved(scene, candidate)
        candidate = copy.deepcopy(scene['snapshot'])
        candidate['instances'][-1]['componentBindings'] = [{'objectRef': self.ref(engineering.CHILD), 'componentKeys': [self.component_key]}]
        scene = self.saved(scene, candidate); before = self.counts()
        ambiguous = self.location(scene)
        self.assertEqual((ambiguous['status'], ambiguous['reason']), ('choose_representation', 'AMBIGUOUS_REPRESENTATION'))
        self.assertEqual(len(ambiguous['choices']), 2)
        choice = {'sceneModelInstanceId': extra['sceneModelInstanceId'], 'modelVersionId': self.version['modelVersionId']}
        chosen = self.location(scene, choice=choice)
        self.assertEqual(chosen['sceneModelInstanceId'], extra['sceneModelInstanceId'])
        first = self.location(scene, choice={'sceneModelInstanceId': scene['snapshot']['instances'][0]['sceneModelInstanceId'],
            'modelVersionId': self.version['modelVersionId']})
        self.assertAlmostEqual(chosen['worldBounds'][0][0]-first['worldBounds'][0][0], 190)
        stale = self.location(scene, choice={**choice, 'modelVersionId': str(uuid4())})
        self.assertEqual((stale['status'], stale['reason']), ('unavailable', 'BINDING_NEEDS_REVIEW'))
        self.assertIsNone(stale['worldBounds'])
        self.assertEqual(self.counts(), before)

    def test_hidden_instance_can_be_located_without_persisting_visibility(self):
        scene, _ = self.bound_scene(); candidate = copy.deepcopy(scene['snapshot'])
        candidate['instances'][0]['visible'] = False
        scene = self.saved(scene, candidate); before = self.counts()
        self.assertEqual(self.location(scene)['status'], 'located')
        self.assertFalse(self.open_ok(scene)['snapshot']['instances'][0]['visible'])
        self.assertEqual(self.counts(), before)

    def test_specified_old_revision_is_located_without_silently_using_new_head(self):
        old, _ = self.bound_scene(); candidate = copy.deepcopy(old['snapshot'])
        candidate['instances'][0]['placement']['position']['xM'] = 400
        current = self.saved(old, candidate); before = self.counts()
        old_location, new_location = self.location(old), self.location(current)
        self.assertEqual(old_location['sceneRevision'], old['sceneRevision'])
        self.assertEqual(new_location['sceneRevision'], current['sceneRevision'])
        self.assertAlmostEqual(new_location['worldBounds'][0][0]-old_location['worldBounds'][0][0], 390)
        other = self.create()
        self.expect(self.locate(old, sceneRevision=other['sceneRevision']), 404, 'NOT_FOUND_OR_FORBIDDEN')
        # Only the separately created scene writes; all location calls remain read-only.
        after_create = self.counts()
        self.expect(self.locate(old, sceneRevision='scene:nonexistent'), 404, 'NOT_FOUND_OR_FORBIDDEN')
        self.assertEqual(self.counts(), after_create)
        self.assertEqual(after_create['scene_revisions'], before['scene_revisions']+1)

    def test_nearest_model_review_issue_prevents_falling_back_to_whole_root(self):
        scene, _ = self.bound_scene(); replacement = self.upload_calibrated(self.version['modelAssetId'])
        status, checked, _ = self.request(bindings.SCENES+'/replacement-check', {'kind': 'model',
            'sceneId': scene['sceneId'], 'expectedSceneRevision': scene['sceneRevision'], 'snapshot': scene['snapshot'],
            'sceneModelInstanceId': scene['snapshot']['instances'][0]['sceneModelInstanceId'],
            'candidateModelVersionId': replacement['modelVersionId']})
        self.assertEqual(status, 200, checked)
        status, saved, _ = self.request(bindings.SCENES+'/save', {'sceneId': scene['sceneId'],
            'expectedSceneRevision': scene['sceneRevision'], 'clientRequestId': str(uuid4()),
            'snapshot': checked['proposedSnapshot'], 'spatialChange': checked['spatialChange'],
            'reviewedEngineering': checked['reviewedEngineering'], 'rootBindingChanges': checked['rootBindingChanges']})
        self.assertEqual(status, 200, saved)
        current = self.open_ok(scene); before = self.counts()
        blocked = self.location(current)
        self.assertEqual((blocked['status'], blocked['reason']), ('unavailable', 'BINDING_NEEDS_REVIEW'))
        self.assertIsNone(blocked['hostObject']); self.assertIsNone(blocked['worldBounds'])
        self.assertEqual(self.location(current, engineering.ROOT)['status'], 'located')
        self.assertEqual(self.counts(), before)

    def test_incomplete_chain_and_changed_engineering_never_produce_geometry(self):
        scene, _ = self.bound_scene(); before = self.counts(); source = self.authority().engineering
        source.objects[engineering.CHILD]['entityRevision'] += '-new'
        changed = self.location(scene)
        self.assertEqual((changed['status'], changed['reason']), ('unavailable', 'BINDING_NEEDS_REVIEW'))
        source.parents.pop(engineering.CABINET)
        incomplete = self.location(scene)
        self.assertEqual((incomplete['status'], incomplete['reason']), ('unavailable', 'INCOMPLETE_PHYSICAL_CHAIN'))
        self.assertIsNone(incomplete['worldBounds'])
        self.assertEqual(self.counts(), before)

    def test_source_definition_has_no_representation_and_ref_cannot_switch_project_or_connection(self):
        scene, _ = self.bound_scene(); before = self.counts()
        source = self.location(scene, 'definition')
        self.assertEqual((source['status'], source['reason']), ('unavailable', 'NO_REPRESENTATION'))
        for field, value in [('projectCode', 'other-project'), ('ontobaseConnectionId', 'other-connection')]:
            changed = self.ref(engineering.CHILD); changed[field] = value
            self.expect(self.locate(scene, selectedObjectRef=changed), 404, 'NOT_FOUND_OR_FORBIDDEN')
        self.assertEqual(self.counts(), before)

    def test_current_member_can_locate_but_revoked_project_returns_no_payload(self):
        scene, _ = self.bound_scene(); before = self.counts()
        member = self.login('synthetic-reader'); self.authority(member).role = 'reader'
        self.assertEqual(self.location(scene, client=member)['status'], 'located')
        self.authority(member).allowed = False
        self.expect(self.locate(scene, client=member), 403, 'FORBIDDEN')
        self.expect(self.locate(scene, client=False), 401, 'SESSION_EXPIRED')
        self.assertEqual(self.counts(), before)

    def test_access_change_during_current_source_read_discards_late_location(self):
        scene, _ = self.bound_scene(); before = self.counts(); account = self.authority()
        account.engineering.after = lambda *_: setattr(account, 'grant', 'synthetic-grant:changed')
        self.expect(self.locate(scene), 409, 'ACCESS_CHANGED')
        self.assertEqual(self.counts(), before)

    def test_session_revision_change_and_direct_upstream_401_are_not_location_results(self):
        scene, _ = self.bound_scene(); before = self.counts(); account = self.authority()
        account.engineering.calls.clear()
        self.expect(self.locate(scene, expectedSessionRevision='stale-session'), 409, 'SESSION_CHANGED')
        self.assertEqual(account.engineering.calls, [])
        def expired(*args): raise bindings.PreviewError(401, 'SESSION_EXPIRED')
        account.engineering.request = expired
        self.expect(self.locate(scene), 401, 'SESSION_EXPIRED')
        self.assertNotIn(self.admin['cookie'].split('=', 1)[1], self.sessions.rows)
        self.assertEqual(self.counts(), before)

    def test_logout_during_selected_object_read_discards_late_geometry(self):
        scene, _ = self.bound_scene(); before = self.counts()
        account = self.authority(); entered, release = Event(), Event(); reads = 0
        def delay(source, method, path, body):
            nonlocal reads
            if method == 'POST' and path.endswith('/objects/resolve') and body == {'entityUids': [engineering.CHILD], 'resolutionMode': 'live'}:
                reads += 1
                if reads == 2:
                    entered.set(); release.wait(4)
        account.engineering.after = delay
        result = []
        worker = Thread(target=lambda: result.append(self.locate(scene))); worker.start()
        try:
            self.assertTrue(entered.wait(3))
            self.assertEqual(self.request('/api/session/logout')[0], 200)
            fresh = self.login('synthetic-admin')
        finally:
            release.set(); worker.join(5)
        self.assertFalse(worker.is_alive())
        self.expect(result[0], 401, 'SESSION_EXPIRED')
        self.assertIn(fresh['cookie'].split('=', 1)[1], self.sessions.rows)
        self.assertEqual(self.counts(), before)

    def test_resource_content_change_cannot_bypass_fixed_fingerprint(self):
        scene, _ = self.bound_scene(); before = self.counts()
        artifact = self.sessions.library.root/'files'/(self.version['modelVersionId']+'.glb')
        original = artifact.read_bytes(); tampered = bytearray(original); tampered[-1] ^= 1
        artifact.write_bytes(tampered)
        self.expect(self.locate(scene), 409, 'RESOURCE_CHANGED')
        self.assertEqual(self.counts(), before)

    def test_strict_location_body_transport_and_16k_limit_do_not_change_scene(self):
        scene, _ = self.bound_scene(); before = self.counts(); body = self.location_body(scene)
        invalid = [{key: value for key, value in body.items() if key != 'sceneRevision'},
            {**body, 'sceneRevision': None}, {**body, 'sceneRevision': ''},
            {**body, 'contextEpoch': ''}, {**body, 'url': 'https://arbitrary.invalid'},
            {**body, 'representationChoice': None}, {**body, 'representationChoice': {'modelVersionId': self.version['modelVersionId']}},
            {**body, 'representationChoice': {'sceneModelInstanceId': scene['snapshot']['instances'][0]['sceneModelInstanceId'],
                'modelVersionId': self.version['modelVersionId'], 'path': '/private'}}]
        for invalid_body in invalid:
            with self.subTest(fields=list(invalid_body)):
                self.expect(self.request(LOCATE, invalid_body), 422, 'INVALID_REQUEST')
        raw = json.dumps({**body, 'expectedSessionRevision': self.admin['revision']})
        self.expect(self.request(LOCATE, raw=(raw[:-1]+',"contextEpoch":"duplicate"}').encode()), 422, 'INVALID_REQUEST')
        self.expect(self.request(LOCATE, raw=b' ' * 16385), 413, 'INVALID_REQUEST')
        self.expect(self.request(LOCATE, body, headers={'Origin': 'https://other.invalid'}), 403, 'FORBIDDEN')
        self.expect(self.request(LOCATE, method='GET'), 404, 'NOT_FOUND')
        self.assertEqual(self.counts(), before)


if __name__ == '__main__': unittest.main()
