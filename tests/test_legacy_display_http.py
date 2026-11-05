"""Same-origin legacy display with real SQLite/GLB and synthetic engineering APIs."""
import copy
import json
from unittest.mock import patch
import unittest
from uuid import uuid4

from apps.api.model_validation import validate
from tests import test_scene_bindings_http as bindings
from tests import test_scene_engineering as engineering


PRESERVE = '/api/workbench/resources/model/preserve-legacy-display'
IMPORT = '/api/workbench/resources/model/import-existing'
CT = 'synthetic-legacy-CT'
CN1 = 'synthetic-legacy-CN1'


class LegacyDisplayHttpTests(unittest.TestCase):
    request = bindings.SceneBindingsHttpTests.request
    login = bindings.SceneBindingsHttpTests.login
    authority = bindings.SceneBindingsHttpTests.authority
    listing = bindings.SceneBindingsHttpTests.listing
    metadata = bindings.SceneBindingsHttpTests.metadata
    upload = bindings.SceneBindingsHttpTests.upload
    calibration = bindings.SceneBindingsHttpTests.calibration
    calibrate = bindings.SceneBindingsHttpTests.calibrate
    model = bindings.SceneBindingsHttpTests.model
    expect = bindings.SceneBindingsHttpTests.expect
    upload_calibrated = bindings.SceneBindingsHttpTests.upload_calibrated
    ref = staticmethod(bindings.SceneBindingsHttpTests.ref)
    item = bindings.SceneBindingsHttpTests.item
    create = bindings.SceneBindingsHttpTests.create
    opened = bindings.SceneBindingsHttpTests.opened
    open_ok = bindings.SceneBindingsHttpTests.open_ok
    check = bindings.SceneBindingsHttpTests.check
    checked_body = bindings.SceneBindingsHttpTests.checked_body
    saved = bindings.SceneBindingsHttpTests.saved
    counts = bindings.SceneBindingsHttpTests.counts

    def setUp(self):
        bindings.SceneBindingsHttpTests.setUp(self)
        for uid in (CT, CN1):
            source = self.authority().engineering
            source.objects[uid] = source.object(uid, engineering.CTX)
            source.parents[uid] = engineering.ROOT
            source.relations[uid, engineering.ROOT] = source.relation(uid, engineering.ROOT)
        path = self.root/'legacy.glb'; path.write_bytes(self.data)
        result = validate(path)
        result['components'] += [{'componentKey': 'proxy:'+role, 'displayName': role, 'nodeIndices': [],
            'keyStability': 'version_local', 'geometryQuality': 'proxy_schematic',
            'bounds': [[0, 0, 0], [1, 2, 1]]} for role in ('CT', 'CN1')]
        self.legacy = self.sessions.library.save_upload(path, {'expectedSessionRevision': 'fixture-source-only',
            'expectedLibraryRevision': self.sessions.library.listing()['libraryRevision'],
            'clientRequestId': str(uuid4()), 'displayName': 'Synthetic old display', 'sourceNote': 'Synthetic old source',
            'rightsDeclared': True}, 'synthetic-original', result, lambda: None)
        status, self.imported, _ = self.request(IMPORT, {'legacyModelVersionId': self.legacy['versionId'],
            'expectedModelRevision': 1, 'expectedSha256': self.legacy['sha256'],
            'expectedLibraryRevision': self.sessions.library.listing()['libraryRevision'],
            'purpose': 'equipment', 'clientRequestId': str(uuid4())})
        self.assertEqual(status, 200, self.imported)
        self.preservation_body = self.preservation(self.imported)
        status, self.preserved, _ = self.request(PRESERVE, self.preservation_body)
        self.assertEqual(status, 200, self.preserved)
        self.version = self.preserved; self.component_key = 'component:2'

    def preservation(self, source):
        return {'modelVersionId': source['modelVersionId'], 'expectedContentRevision': source['contentRevision'],
            'expectedLibraryRevision': self.listing()[1]['libraryRevision'], 'clientRequestId': str(uuid4()),
            'preservationBasis': {'mode': 'preserve_legacy_display', 'sourceNote': 'Preserve known synthetic display only.'}}

    def three_cabinets(self):
        scene = self.create(); candidate = copy.deepcopy(scene['snapshot'])
        candidate['instances'] = [self.item('Synthetic old turbine', engineering.ROOT)]
        scene = self.saved(scene, candidate); candidate = copy.deepcopy(scene['snapshot'])
        candidate['instances'][0]['componentBindings'] = [{'objectRef': self.ref(uid), 'componentKeys': [key]}
            for uid, key in ((CT, 'proxy:CT'), (CN1, 'proxy:CN1'), (engineering.CABINET, self.component_key))]
        return self.saved(scene, candidate)

    def locate(self, scene, uid):
        return self.request(bindings.SCENES+'/locate', {'sceneId': scene['sceneId'], 'sceneRevision': scene['sceneRevision'],
            'selectedObjectRef': self.ref(uid), 'contextEpoch': 'legacy-display-intent'})

    def test_local_three_cabinets_and_nearest_child_keep_current_identity_and_schematic_quality(self):
        scene = self.three_cabinets()
        self.assertEqual(scene['validation']['bindingIssues'], [])
        self.assertEqual(len(scene['snapshot']['instances'][0]['componentBindings']), 3)
        for uid, quality in ((CT, 'proxy_schematic'), (CN1, 'proxy_schematic'), (engineering.CABINET, 'source_candidate')):
            status, location, _ = self.locate(scene, uid)
            self.assertEqual(status, 200, location); self.assertEqual(location['status'], 'located')
            self.assertEqual(location['geometryQuality'], quality)
        status, child, _ = self.locate(scene, engineering.CHILD)
        self.assertEqual(status, 200, child); self.assertEqual(child['status'], 'located')
        self.assertEqual(child['selectedObject']['entityUid'], engineering.CHILD)
        self.assertEqual(child['hostObject']['entityUid'], engineering.CABINET)
        self.assertEqual(child['relationshipStatus'], 'assumed')
        self.assertFalse(self.preserved['canPlaceGeographic'])
        self.assertEqual(self.preserved['capabilities']['calibrationRequiredForGeographicPlacement'], True)

    def test_preservation_route_enforces_current_admin_and_strict_body_without_default_model(self):
        self.assertIsNone(self.sessions.model)
        self.expect(self.request(PRESERVE, self.preservation_body, client=False), 401, 'SESSION_EXPIRED')
        reader = self.login('synthetic-reader'); self.authority(reader).role = 'reader'
        self.expect(self.request(PRESERVE, self.preservation_body, client=reader), 403, 'MODEL_WRITE_FORBIDDEN')
        for extra in ({'matrix': [1]*16}, {'sourceSha256': self.legacy['sha256']}, {'projectCode': 'another-project'}):
            self.expect(self.request(PRESERVE, {**self.preservation_body, **extra}), 422, 'INVALID_REQUEST')
        self.expect(self.request(PRESERVE, {**self.preservation_body, 'preservationBasis': {
            **self.preservation_body['preservationBasis'], 'verifiedBy': 'client'}}), 422, 'INVALID_REQUEST')
        self.expect(self.request(PRESERVE, self.preservation_body, headers={'Origin': 'https://foreign.invalid'}), 403, 'FORBIDDEN')
        self.expect(self.request(PRESERVE, raw=b'{"modelVersionId":1,"modelVersionId":2}'), 422, 'INVALID_REQUEST')
        self.expect(self.request(PRESERVE, raw=b' '*16385), 413, 'INVALID_REQUEST')

    def test_original_body_replays_under_same_user_new_session_but_revoked_grant_cannot_recover_private_result(self):
        new_session = self.login('synthetic-admin')
        status, replay, _ = self.request(PRESERVE, self.preservation_body, client=new_session)
        self.assertEqual(status, 200, replay); self.assertEqual(replay['modelVersionId'], self.preserved['modelVersionId'])
        self.authority(new_session).allowed = False
        self.expect(self.request(PRESERVE, self.preservation_body, client=new_session), 403, 'FORBIDDEN')
        body = {**self.preservation_body, 'preservationBasis': {**self.preservation_body['preservationBasis'], 'sourceNote': 'Changed'}}
        self.expect(self.request(PRESERVE, body), 409, 'REQUEST_CONFLICT')

    def test_ordinary_upload_cannot_claim_legacy_and_role_loss_before_commit_has_no_new_registration(self):
        status, ordinary, _ = self.upload()
        self.assertEqual(status, 200, ordinary)
        self.expect(self.request(PRESERVE, self.preservation(ordinary)), 422, 'INVALID_REQUEST')
        before = self.sessions.library.listing(); capacity = self.sessions.project_models._capacity
        def revoke(db, size):
            capacity(db, size); self.authority().role = 'reader'
        with patch.object(self.sessions.project_models, '_capacity', side_effect=revoke):
            self.expect(self.request(PRESERVE, self.preservation(self.imported)), 403, 'MODEL_WRITE_FORBIDDEN')
        self.assertEqual(self.sessions.library.listing(), before)
        self.assertTrue(self.sessions.library.slots.acquire(blocking=False)); self.sessions.library.slots.release()

    def test_local_replacement_preview_cancel_and_save_leave_old_resource_and_fixed_old_scene_unchanged(self):
        scene = self.three_cabinets(); original_revision = scene['sceneRevision']; before = self.counts()
        status, verified, _ = self.calibrate(self.calibration(self.preserved))
        self.assertEqual(status, 200, verified)
        status, preview, _ = self.request(bindings.SCENES+'/replacement-check', {'kind': 'model',
            'sceneId': scene['sceneId'], 'expectedSceneRevision': scene['sceneRevision'], 'snapshot': scene['snapshot'],
            'sceneModelInstanceId': scene['snapshot']['instances'][0]['sceneModelInstanceId'],
            'candidateModelVersionId': verified['modelVersionId']})
        self.assertEqual(status, 200, preview)
        self.assertIsNone(preview['validation']['impact']['oldModel']['forward'])
        self.assertIsNone(preview['validation']['impact']['oldModel']['basePoint'])
        self.assertEqual(self.counts(), before)
        body = {'sceneId': scene['sceneId'], 'expectedSceneRevision': scene['sceneRevision'], 'clientRequestId': str(uuid4()),
            'snapshot': preview['proposedSnapshot'], 'spatialChange': preview['spatialChange'],
            'reviewedEngineering': preview['reviewedEngineering'], 'rootBindingChanges': preview['rootBindingChanges']}
        status, saved, _ = self.request(bindings.SCENES+'/save', body)
        self.assertEqual(status, 200, saved)
        self.assertEqual(len(saved['validation']['bindingIssues']), 3)
        fixed = self.open_ok(scene, original_revision)
        self.assertEqual(fixed['snapshot']['instances'][0]['modelVersionId'], self.preserved['modelVersionId'])
        self.assertEqual(len(fixed['snapshot']['instances'][0]['componentBindings']), 3)
        current = self.open_ok(scene)
        self.assertEqual(current['snapshot']['instances'][0]['modelVersionId'], verified['modelVersionId'])
        self.assertEqual(current['snapshot']['instances'][0]['componentBindings'], [])


if __name__ == '__main__': unittest.main()
