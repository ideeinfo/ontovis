"""Generic representation selection against the real shared-configuration store."""
import copy
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.equipment_configurations import EquipmentConfigurations
from apps.api.model_library import ModelLibrary
from apps.api.scene_representation import inspection_projection, location_projection


class SceneRepresentationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.store = EquipmentConfigurations(ModelLibrary(Path(directory.name), 'plant', None), 'source', 'plant')
        self.cid, self.outer, self.inner = (str(uuid4()) for _ in range(3))
        self.scope = {'ontobaseConnectionId': 'source', 'projectCode': 'plant'}
        self.application = {'applicationId': str(uuid4()), 'revisionId': str(uuid4()), 'projectCode': 'plant',
            'specification': {'objectKind': 'compressor'}, 'snapshot': {'name': '合成压缩机规格',
                'specificationRevisionId': str(uuid4()), 'rootDefinition': None,
                'mappings': [{'roleKey': uid, 'entityUid': uid, 'expectedEntityRevision': 'definition:1'}
                             for uid in ('shell', 'shaft')]}}
        self.models = {version: {'modelAssetId': str(uuid4()), 'modelVersionId': version,
            'contentRevision': version + ':1', 'sha256': digest * 64, 'representationType': kind,
            'state': 'ready', 'assetState': 'active', 'calibrationState': 'verified',
            'canPlace': True, 'canPlaceGeographic': False, 'calibration': {
                'state': 'verified', 'unit': 'm', 'axes': 'Y_UP_RIGHT_HANDED',
                'modelToCalibrated': [1,0,0,0,0,1,0,0,0,0,1,0,offset,0,0,1]}}
            for version, kind, digest, offset in ((self.outer, 'appearance', 'a', 0), (self.inner, 'detailed', 'b', 5))}
        self.entries = [{'modelVersionId': version, 'mappings': [{'objectRef': {**self.scope, 'entityUid': uid},
            'expectedEntityRevision': 'definition:1', 'componentKeys': [key]}]}
            for version, uid, key in ((self.outer, 'shell', 'outside-key'), (self.inner, 'shaft', 'inside-key'))]
        self.configuration = self.save()
        self.scene = {'sceneId': 'scene', 'sceneRevision': 'scene:1', 'headRevision': 'scene:1',
            'snapshot': {'coordinateFrame': {'mode': 'local_plane'}, 'instances': [
                {'sceneModelInstanceId': uid, 'modelVersionId': self.outer, 'visible': True,
                 'placement': {'position': {'xM': i * 100, 'zM': 20}, 'headingDeg': 27},
                 'rootBinding': {'objectRef': {**self.scope, 'entityUid': uid}}, 'componentBindings': []}
                for i, uid in enumerate(('compressor-7', 'compressor-18'))]},
            'resourceRefs': [{key: self.models[self.outer][key] for key in ('modelAssetId', 'modelVersionId', 'contentRevision', 'sha256')}],
            'validation': {'engineeringExpectations': []}}
        self.scene, _ = self.store.resolve_scene(self.scene, self.equipment, self.authorize)
        self.choice = {'sceneModelInstanceId': 'compressor-7', 'modelVersionId': self.outer}

    @staticmethod
    def authorize(): pass

    def save(self, revision=None):
        app = self.application
        return self.store.save({'configurationId': self.cid, 'expectedConfigurationRevision': revision,
            'clientRequestId': str(uuid4()), 'snapshot': {'projectApplicationRef': {
                'applicationId': app['applicationId'], 'applicationRevisionId': app['revisionId'],
                'specificationRevisionId': app['snapshot']['specificationRevisionId']}, 'models': self.entries}},
            'reader', self.authorize,
            lambda uid: {'item': {'installationContextId': None, 'entityRevision': 'definition:1'}},
            lambda _: [{'componentKey': 'outside-key'}, {'componentKey': 'inside-key'}], application=app)

    def equipment(self, uids):
        return {uid: {'adoption': self.configuration['snapshot']['projectApplicationRef'],
            'context': {'installationContextId': uid + ':context', 'hierarchyRevision': uid + ':tree'},
            'children': [{'entityUid': uid + '-' + role, 'entityRevision': 'installed:1', 'sourceTemplateEntityUid': role}
                         for role in ('shell', 'shaft')]} for uid in uids}

    def project(self, **options):
        return inspection_projection(options.get('scene', self.scene), options.get('choice', self.choice), self.store,
            options.get('equipment', self.equipment), options.get('load', self.models.__getitem__), options.get('authorize', self.authorize))

    def test_arbitrary_model_pair_uses_own_keys_and_calibration_without_changing_saved_scene_or_other_instances(self):
        before = copy.deepcopy(self.scene)
        projected, uses = self.project()
        selected, other = projected['snapshot']['instances']
        self.assertEqual(selected['modelVersionId'], self.inner)
        self.assertEqual(selected['placement'], before['snapshot']['instances'][0]['placement'])
        self.assertEqual(selected['rootBinding'], before['snapshot']['instances'][0]['rootBinding'])
        self.assertEqual(selected['componentBindings'], [{'objectRef': {**self.scope, 'entityUid': 'compressor-7-shaft'}, 'componentKeys': ['inside-key']}])
        self.assertEqual(other, before['snapshot']['instances'][1])
        self.assertEqual(self.scene, before)
        self.assertEqual(len(projected['resourceRefs']), 2)
        self.assertTrue(all(use['configurationId'] == self.cid for use in uses))
        self.assertEqual(self.models[self.inner]['calibration']['modelToCalibrated'][12], 5)

    def test_historical_scene_and_wrong_choice_do_not_read_or_guess_a_new_model(self):
        def unexpected(_): self.fail('No model read expected')
        for changes in ({'scene': dict(self.scene, headRevision='new'), 'load': unexpected},
                        {'choice': dict(self.choice, modelVersionId=str(uuid4())), 'load': unexpected}):
            scene = changes.get('scene', self.scene)
            self.assertEqual(self.project(**changes), (scene, None))

    def test_unadopted_equipment_and_models_outside_its_configuration_do_not_switch(self):
        def unadopted(uids): return {uid: dict(row, adoption=None) for uid, row in self.equipment(uids).items()}
        self.assertEqual(self.project(equipment=unadopted), (self.scene, None))
        unrelated = str(uuid4()); self.models[unrelated] = dict(self.models[self.outer], modelVersionId=unrelated)
        scene = copy.deepcopy(self.scene); scene['snapshot']['instances'][0]['modelVersionId'] = unrelated
        self.assertEqual(self.project(scene=scene, choice=dict(self.choice, modelVersionId=unrelated)), (scene, None))

    def test_multiple_detail_versions_are_ambiguous_even_if_one_is_not_calibrated(self):
        extra = str(uuid4()); self.models[extra] = dict(self.models[self.inner], modelVersionId=extra, calibrationState='unverified')
        self.entries.append({'modelVersionId': extra, 'mappings': []})
        self.save(self.configuration['configurationRevision'])
        with self.assertRaisesRegex(PreviewError, 'AMBIGUOUS_REPRESENTATION'): self.project()

    def test_missing_detail_stays_appearance_and_uncalibrated_detail_is_blocked(self):
        self.models[self.inner]['representationType'] = 'other'
        self.assertEqual(self.project(), (self.scene, None))
        self.models[self.inner]['representationType'] = 'detailed'
        self.models[self.inner]['calibrationState'] = 'unverified'
        with self.assertRaisesRegex(PreviewError, 'MODEL_CALIBRATION_REQUIRED'): self.project()

    def test_geographic_scene_requires_geographic_calibration_but_local_scene_does_not(self):
        self.assertEqual(self.project()[0]['snapshot']['instances'][0]['modelVersionId'], self.inner)
        scene = copy.deepcopy(self.scene); scene['snapshot']['coordinateFrame']['mode'] = 'projected_site'
        self.models[self.outer]['canPlaceGeographic'] = True
        with self.assertRaisesRegex(PreviewError, 'MODEL_CALIBRATION_REQUIRED'): self.project(scene=scene)

    def test_configuration_change_during_detail_read_rejects_mixed_revisions(self):
        changed = False
        def load(version):
            nonlocal changed
            if version == self.inner and not changed:
                changed = True; self.save(self.configuration['configurationRevision'])
            return self.models[version]
        with self.assertRaisesRegex(PreviewError, 'REVISION_CONFLICT'): self.project(load=load)

    def test_adoption_change_or_revoked_access_during_projection_returns_no_geometry(self):
        reads = 0
        def equipment(uids):
            nonlocal reads
            reads += 1
            rows = self.equipment(uids)
            if reads >= 3:
                for row in rows.values(): row['adoption'] = None
            return rows
        with self.assertRaisesRegex(PreviewError, 'REVISION_CONFLICT'): self.project(equipment=equipment)
        permitted = True
        def load(version):
            nonlocal permitted
            if version == self.inner: permitted = False
            return self.models[version]
        def authorize():
            if not permitted: raise PreviewError(403, 'FORBIDDEN')
        with self.assertRaisesRegex(PreviewError, 'FORBIDDEN'): self.project(load=load, authorize=authorize)

    def test_location_composes_the_raw_scene_once_and_retains_fresh_adoption_recheck(self):
        scene=copy.deepcopy(self.scene)
        for instance in scene['snapshot']['instances']: instance['componentBindings']=[]
        before=copy.deepcopy(scene);reads=[]
        def equipment(uids):
            reads.append(list(uids));return self.equipment(uids)
        projected,uses=location_projection(scene,self.choice,True,self.store,equipment,self.models.__getitem__,self.authorize)
        self.assertEqual(reads,[['compressor-7'],['compressor-18','compressor-7'],['compressor-7']])
        self.assertEqual(projected['snapshot']['instances'][0]['modelVersionId'],self.inner)
        self.assertEqual(projected['snapshot']['instances'][0]['componentBindings'][0]['componentKeys'],['inside-key'])
        self.assertEqual(projected['snapshot']['instances'][1]['componentBindings'][0]['componentKeys'],['outside-key'])
        self.assertEqual(len(uses),2);self.assertEqual(scene,before)

    def test_location_without_a_detail_candidate_still_composes_normal_bindings(self):
        reads=[];scene=copy.deepcopy(self.scene)
        for instance in scene['snapshot']['instances']: instance['componentBindings']=[]
        self.models[self.outer]['representationType']='detailed'
        def equipment(uids):
            reads.append(list(uids));return self.equipment(uids)
        for preferred in (False,True):
            reads.clear()
            projected,uses=location_projection(scene,self.choice,preferred,self.store,equipment,self.models.__getitem__,self.authorize)
            self.assertEqual(reads,[['compressor-18','compressor-7']]);self.assertEqual(len(uses),2)
            self.assertEqual(projected['snapshot']['instances'][0]['componentBindings'][0]['componentKeys'],['outside-key'])

    def test_location_refuses_access_or_adoption_changes_after_the_single_composition(self):
        reads=0
        def equipment(uids):
            nonlocal reads
            reads+=1;result=self.equipment(uids)
            if reads==3:
                for row in result.values(): row['adoption']=None
            return result
        with self.assertRaisesRegex(PreviewError,'REVISION_CONFLICT'):
            location_projection(self.scene,self.choice,True,self.store,equipment,self.models.__getitem__,self.authorize)
        calls=0
        def authorize():
            nonlocal calls
            calls+=1
            if calls>=3:raise PreviewError(403,'FORBIDDEN')
        with self.assertRaisesRegex(PreviewError,'FORBIDDEN'):
            location_projection(self.scene,self.choice,True,self.store,self.equipment,self.models.__getitem__,authorize)


if __name__ == '__main__': unittest.main()
