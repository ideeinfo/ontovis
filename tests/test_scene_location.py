"""Fixed-scene location rules over actual reader DTOs and synthetic model boxes."""
import copy
import json
import math
import unittest

from apps.api.authority import PreviewError
from apps.api.scene_engineering import SceneEngineeringReader
from apps.api.scene_location import SceneLocationResolver
from tests import test_scene_engineering as fixture


INSTANCE = '00000000-0000-0000-0000-000000000001'
SECOND = '00000000-0000-0000-0000-000000000002'
VERSION = '00000000-0000-0000-0000-000000000011'
OTHER_VERSION = '00000000-0000-0000-0000-000000000012'
SCENE = '00000000-0000-0000-0000-000000000099'
IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def ref(uid):
    return {'ontobaseConnectionId': fixture.CONNECTION, 'projectCode': fixture.PROJECT, 'entityUid': uid}


def instance(identifier=INSTANCE, root=fixture.ROOT, bound=fixture.CABINET, keys=None):
    return {'sceneModelInstanceId': identifier, 'displayName': '合成实例 '+identifier[-1],
        'modelVersionId': VERSION, 'rootBinding': {'objectRef': ref(root)} if root else None,
        'componentBindings': [{'objectRef': ref(bound), 'componentKeys': keys or ['signal']}] if bound else [],
        'visible': True, 'positionLocked': False,
        'placement': {'position': {'mode': 'local', 'xM': 10, 'zM': 20},
                      'height': {'mode': 'local_relative', 'relativeHeightM': 3}, 'headingDeg': 0}}


def model():
    return {'modelAssetId': '00000000-0000-0000-0000-000000000031', 'modelVersionId': VERSION,
        'contentRevision': 'fixed-model:1', 'sha256': 'a'*64, 'state': 'ready',
        'canPlace': True, 'calibrationState': 'verified',
        'calibration': {'state': 'verified', 'unit': 'm', 'axes': 'Y_UP_RIGHT_HANDED',
                        'modelToCalibrated': list(IDENTITY)},
        'report': {'bounds': {'min': [-1, 0, -2], 'max': [1, 10, 2], 'basis': 'source_model'}},
        'components': [
            {'componentKey': 'signal', 'geometryQuality': 'source_candidate', 'bounds': [[0, 1, 0], [1, 2, 2]]},
            {'componentKey': 'proxy', 'geometryQuality': 'proxy_schematic', 'bounds': [[3, 1, 4], [4, 2, 5]]}],
        'privateServerPath': '/private/must-not-leak', 'token': 'synthetic-not-returned'}


class SceneLocationTests(unittest.TestCase):
    def setUp(self):
        self.authority = fixture.SyntheticAuthority()
        self.reader = SceneEngineeringReader(self.authority, fixture.CONNECTION, fixture.PROJECT, self.authority.guard)
        self.models = {VERSION: model()}; self.loads = []
        def load(version):
            self.authority.guard(); self.loads.append(version)
            return copy.deepcopy(self.models[version])
        self.resolver = SceneLocationResolver(load)
        self.scene = self.opened(instance())

    def opened(self, *instances):
        refs = {binding['objectRef']['entityUid'] for item in instances for binding in item['componentBindings']}
        refs.update(item['rootBinding']['objectRef']['entityUid'] for item in instances if item['rootBinding'])
        return {'sceneId': SCENE, 'sceneRevision': 'fixed-scene:7', 'projectCode': fixture.PROJECT,
            'snapshot': {'coordinateFrame': {'mode': 'local_plane'}, 'instances': list(instances)},
            'resourceRefs': [{key: self.models[VERSION][key] for key in (
                'modelAssetId', 'modelVersionId', 'contentRevision', 'sha256')}],
            'validation': {'engineeringExpectations': [self.reader.context_for_object(uid)['expectation'] for uid in sorted(refs)],
                           'bindingIssues': []}}

    def locate(self, uid=fixture.CHILD, *, scene=None, selection=None, choice=None):
        return self.resolver.resolve(scene or self.scene, selection or self.reader.context_for_object(uid), 'synthetic-intent:3', choice)

    def issue(self, scene=None, uid=fixture.CABINET, identifier=INSTANCE):
        scene = self.scene if scene is None else scene
        scene['validation']['bindingIssues'].append({'sceneModelInstanceId': identifier,
            'objectRef': ref(uid), 'installationContextId': fixture.CTX, 'blocking': True,
            'kind': 'model_version_changed', 'previousModelVersionId': OTHER_VERSION,
            'previousComponentKeys': ['old-signal'], 'sourceSceneRevision': 'fixed-scene:6', 'code': 'COMPONENT_MISSING'})

    def test_no_geometry_child_uses_nearest_cabinet_but_keeps_selected_identity(self):
        result = self.locate()
        self.assertEqual((result['status'], result['mode'], result['sceneModelInstanceId']), ('located', 'ancestor', INSTANCE))
        self.assertEqual(result['selectedObject']['entityUid'], fixture.CHILD)
        self.assertEqual(result['hostObject']['entityUid'], fixture.CABINET)
        self.assertEqual(result['componentKeys'], ['signal'])
        self.assertEqual(result['worldBounds'], [[10, 4, 20], [11, 5, 22]])
        self.assertEqual(result['relationshipStatus'], 'assumed')
        self.assertEqual(result['geometryQuality'], 'source_candidate')
        self.assertEqual(result['contextEpoch'], 'synthetic-intent:3')
        self.assertNotIn('/private', json.dumps(result)); self.assertNotIn('token', json.dumps(result))

    def test_direct_component_relationship_is_null_and_root_is_whole_model(self):
        direct = self.locate(fixture.CABINET)
        self.assertEqual(direct['mode'], 'direct'); self.assertIsNone(direct['relationshipStatus'])
        root = self.locate(fixture.ROOT)
        self.assertEqual(root['componentKeys'], [])
        self.assertEqual(root['worldBounds'], [[9, 3, 18], [11, 13, 22]])
        self.assertEqual(root['geometryQuality'], 'source_candidate')

    def test_root_can_itself_have_internal_component_collection(self):
        scene = self.opened(instance(root=fixture.CABINET, bound=fixture.CABINET, keys=['signal', 'proxy']))
        result = self.locate(fixture.CABINET, scene=scene)
        self.assertEqual(result['componentKeys'], ['proxy', 'signal'])
        self.assertEqual(result['worldBounds'], [[10, 4, 20], [14, 5, 25]])
        self.assertEqual(result['geometryQuality'], 'proxy_schematic')

    def test_confirmed_and_assumed_relationships_use_only_traversed_edges(self):
        selected = self.reader.context_for_object(fixture.CHILD)
        # Exercise edge reduction separately from the authority's context policy.
        selected['ancestors']['path'][0]['relation']['status'] = 'confirmed'
        self.assertEqual(self.locate(selection=selected)['relationshipStatus'], 'confirmed')
        root_only = self.opened(instance(bound=None))
        self.assertEqual(self.locate(scene=root_only, selection=selected)['relationshipStatus'], 'assumed')

    def test_same_model_different_installation_roots_never_cross(self):
        other_child = 'synthetic-other-child'
        self.authority.objects[other_child] = self.authority.object(other_child, fixture.OTHER_CTX)
        self.authority.parents[other_child] = fixture.OTHER_ROOT
        self.authority.relations[other_child, fixture.OTHER_ROOT] = self.authority.relation(other_child, fixture.OTHER_ROOT)
        other = instance(SECOND, fixture.OTHER_ROOT, other_child)
        other['placement']['position']['xM'] = 200
        scene = self.opened(instance(), other)
        self.assertEqual(self.locate(scene=scene)['sceneModelInstanceId'], INSTANCE)
        result = self.locate(other_child, scene=scene)
        self.assertEqual(result['sceneModelInstanceId'], SECOND)
        self.assertEqual(result['worldBounds'][0][0], 200)

    def test_sibling_outside_instance_root_stops_instead_of_using_illegal_component(self):
        sibling = 'synthetic-sibling'
        self.authority.objects[sibling] = self.authority.object(sibling, fixture.CTX)
        self.authority.parents[sibling] = fixture.ROOT
        self.authority.relations[sibling, fixture.ROOT] = self.authority.relation(sibling, fixture.ROOT)
        scene = self.opened(instance(root=fixture.CABINET, bound=sibling))
        self.assertEqual(self.locate(sibling, scene=scene)['reason'], 'BINDING_NEEDS_REVIEW')

    def test_one_object_multiple_instances_requires_explicit_fixed_choice(self):
        scene = self.opened(instance(), instance(SECOND))
        result = self.locate(scene=scene)
        self.assertEqual((result['status'], result['reason']), ('choose_representation', 'AMBIGUOUS_REPRESENTATION'))
        self.assertEqual([row['sceneModelInstanceId'] for row in result['choices']], [INSTANCE, SECOND])
        selected = self.locate(scene=scene, choice={'sceneModelInstanceId': SECOND, 'modelVersionId': VERSION})
        self.assertEqual(selected['sceneModelInstanceId'], SECOND)
        stale = self.locate(scene=scene, choice={'sceneModelInstanceId': SECOND, 'modelVersionId': OTHER_VERSION})
        self.assertEqual(stale['status'], 'unavailable')

    def test_nearest_issue_blocks_farther_root_even_after_components_cleared(self):
        self.scene['snapshot']['instances'][0]['componentBindings'] = []
        self.issue()
        result = self.locate()
        self.assertEqual((result['status'], result['reason']), ('unavailable', 'BINDING_NEEDS_REVIEW'))
        self.assertIsNone(result['hostObject']); self.assertEqual(self.loads, [])
        self.assertEqual(self.locate(fixture.ROOT)['status'], 'located')

    def test_nearest_issue_with_other_valid_representation_still_requires_choice(self):
        scene = self.opened(instance(), instance(SECOND))
        self.issue(scene)
        result = self.locate(scene=scene)
        self.assertEqual(result['reason'], 'BINDING_NEEDS_REVIEW')
        self.assertEqual(result['status'], 'choose_representation')
        self.assertEqual([row['sceneModelInstanceId'] for row in result['choices']], [SECOND])
        self.assertEqual(self.locate(scene=scene, choice={'sceneModelInstanceId': SECOND, 'modelVersionId': VERSION})['status'], 'located')
        self.assertEqual(self.locate(scene=scene, choice={'sceneModelInstanceId': INSTANCE, 'modelVersionId': VERSION})['status'], 'unavailable')

    def test_incomplete_chain_does_not_locate_even_direct_component(self):
        self.authority.parents = {fixture.CHILD: fixture.CABINET}
        result = self.locate(fixture.CABINET)
        self.assertEqual(result['reason'], 'INCOMPLETE_PHYSICAL_CHAIN'); self.assertEqual(self.loads, [])

    def test_complete_chain_cannot_be_cycle_or_unconnected(self):
        selected = self.reader.context_for_object(fixture.CHILD)
        selected['ancestors']['path'][0]['relation']['parentEntityUid'] = fixture.ROOT
        self.assertEqual(self.locate(selection=selected)['reason'], 'INCOMPLETE_PHYSICAL_CHAIN')

    def test_old_host_revision_or_hierarchy_stops_not_farther_root(self):
        for field in ('expectedEntityRevision', 'expectedHierarchyRevision'):
            with self.subTest(field=field):
                scene = copy.deepcopy(self.scene)
                next(row for row in scene['validation']['engineeringExpectations'] if row['ref']['entityUid'] == fixture.CABINET)[field] = 'old'
                self.assertEqual(self.locate(scene=scene)['reason'], 'BINDING_NEEDS_REVIEW')

    def test_selected_own_revision_must_match_current_reader_expectation(self):
        selected = self.reader.context_for_object(fixture.CHILD)
        selected['expectation']['expectedEntityRevision'] = 'stale-selected'
        self.assertEqual(self.locate(selection=selected)['reason'], 'BINDING_NEEDS_REVIEW')

    def test_multiple_instances_share_one_fixed_model_read_without_mutation(self):
        scene = self.opened(instance(), instance(SECOND))
        before = copy.deepcopy(self.models)
        self.assertEqual(self.locate(scene=scene)['status'], 'choose_representation')
        self.assertEqual(self.loads, [VERSION]); self.assertEqual(self.models, before)

    def test_root_issue_invalidates_its_internal_representation(self):
        self.issue(uid=fixture.ROOT)
        self.assertEqual(self.locate()['reason'], 'BINDING_NEEDS_REVIEW')

    def test_missing_expectation_is_not_a_current_binding(self):
        self.scene['validation']['engineeringExpectations'] = []
        self.assertEqual(self.locate()['reason'], 'BINDING_NEEDS_REVIEW')

    def test_other_context_issue_does_not_block_this_installation(self):
        self.issue(); self.scene['validation']['bindingIssues'][0]['installationContextId'] = fixture.OTHER_CTX
        self.assertEqual(self.locate()['status'], 'located')

    def test_hidden_instances_participate_and_snapshot_not_modified(self):
        self.scene['snapshot']['instances'][0]['visible'] = False
        before = copy.deepcopy(self.scene)
        self.assertEqual(self.locate()['status'], 'located')
        self.assertEqual(self.scene, before)

    def test_calibrated_base_rotation_then_instance_yaw_and_translation(self):
        # Calibration is +90deg Three yaw around source base [1,2,3].
        self.models[VERSION]['calibration']['modelToCalibrated'] = [0,0,-1,0,0,1,0,0,1,0,0,0,-3,-2,1,1]
        self.models[VERSION]['components'][0]['bounds'] = [[1,2,3],[3,4,7]]
        self.scene['snapshot']['instances'][0]['placement']['headingDeg'] = 90
        result = self.locate(fixture.CABINET)
        # The two rotations cancel; source base maps to placement.
        for actual, expected in zip(result['worldBounds'][0], [10,3,20]): self.assertAlmostEqual(actual, expected)
        for actual, expected in zip(result['worldBounds'][1], [12,5,24]): self.assertAlmostEqual(actual, expected)

    def test_multiple_component_boxes_transform_separately_before_union(self):
        self.models[VERSION]['components'][0]['bounds'] = [[0,0,0],[1,1,1]]
        self.models[VERSION]['components'][1]['bounds'] = [[3,0,3],[4,1,4]]
        self.scene['snapshot']['instances'][0]['componentBindings'][0]['componentKeys'] = ['signal','proxy']
        self.scene['snapshot']['instances'][0]['placement']['headingDeg'] = 45
        bounds = self.locate(fixture.CABINET)['worldBounds']
        # Rotated separate diagonal boxes span x only +/-sqrt(.5), not +/-sqrt(8).
        self.assertAlmostEqual(bounds[0][0], 10-math.sqrt(.5))
        self.assertAlmostEqual(bounds[1][0], 10+math.sqrt(.5))
        self.assertAlmostEqual(bounds[1][2], 20+4*math.sqrt(2))

    def test_projected_uses_fixed_saved_display_pose_and_no_geographic_approximation(self):
        self.scene['snapshot']['coordinateFrame'] = {'mode':'projected_site'}
        self.scene['snapshot']['instances'][0]['placement'] = {'position': {'mode':'geographic','longitude':113,'latitude':33},
            'height': {'mode':'absolute','valueM':123},'headingDeg':90}
        self.scene['validation']['displayPlacements'] = [{'sceneModelInstanceId':INSTANCE,'position':[40,50,60],'threeYawRad':math.pi/2}]
        result = self.locate(fixture.CABINET)
        for actual, expected in zip(result['worldBounds'][0], [40,51,59]): self.assertAlmostEqual(actual, expected)
        for actual, expected in zip(result['worldBounds'][1], [42,52,60]): self.assertAlmostEqual(actual, expected)

    def test_projected_missing_or_duplicate_pose_is_rejected(self):
        self.scene['snapshot']['coordinateFrame'] = {'mode':'projected_site'}
        for poses in ([], [{'sceneModelInstanceId':INSTANCE,'position':[0,0,0],'threeYawRad':0}]*2):
            self.scene['validation']['displayPlacements'] = poses
            with self.assertRaises(PreviewError) as caught: self.locate()
            self.assertEqual(caught.exception.code, 'RESOURCE_CHANGED')

    def test_missing_components_not_replaced_by_whole_model(self):
        self.models[VERSION]['components'] = []
        self.assertEqual(self.locate()['reason'], 'BINDING_NEEDS_REVIEW')

    def test_unverified_or_unready_model_cannot_locate(self):
        for change in ({'canPlace':False}, {'state':'processing'}, {'calibrationState':'unverified'},
                       {'calibration':{'state':'unverified'}}):
            self.models[VERSION] = {**model(), **change}
            result = self.locate()
            self.assertEqual((result['status'], result['reason']), ('unavailable','RESOURCE_NOT_READY'))

    def test_fixed_model_revision_sha_and_invalid_geometry_refused(self):
        for change in ({'sha256':'b'*64}, {'contentRevision':'new'}, {'modelVersionId':OTHER_VERSION},
                       {'calibration':{**model()['calibration'], 'modelToCalibrated':[float('nan')]*16}}):
            self.models[VERSION] = {**model(), **change}
            result = self.locate()
            self.assertEqual((result['status'], result['reason']), ('unavailable','RESOURCE_CHANGED'))

    def test_malformed_resource_boxes_and_catalogs_are_structured_unavailable(self):
        for components in ([{'componentKey': [], 'bounds':[[0,0,0],[1,1,1]]}],
                           [{'componentKey':'signal','geometryQuality':'source_candidate','bounds':[[2,0,0],[1,1,1]]}],
                           [{'componentKey':'signal','geometryQuality':'source_candidate','bounds':[[0,0,0],[1,float('inf'),1]]}]):
            self.models[VERSION] = {**model(), 'components': components}
            self.assertEqual(self.locate()['reason'], 'RESOURCE_CHANGED')
        self.models[VERSION] = {**model(), 'report':None}
        self.assertEqual(self.locate(fixture.ROOT)['reason'], 'RESOURCE_CHANGED')

    def test_loader_permission_failure_is_not_a_success_or_leaked_choice(self):
        selected = self.reader.context_for_object(fixture.CHILD)
        self.authority.allowed = False
        with self.assertRaises(PreviewError) as caught: self.locate(selection=selected)
        self.assertEqual(caught.exception.status, 403)

    def test_definition_is_readable_but_has_no_representation(self):
        result = self.locate('definition')
        self.assertEqual(result['reason'], 'NO_REPRESENTATION')
        self.assertEqual(result['selectedObject']['entityUid'], 'definition')

    def test_representation_choice_rejects_extra_fields_and_invalid_epoch(self):
        for choice in ({'sceneModelInstanceId':INSTANCE}, {'sceneModelInstanceId':INSTANCE,'modelVersionId':VERSION,'componentKeys':['signal']}):
            with self.assertRaises(PreviewError): self.locate(choice=choice)
        with self.assertRaises(PreviewError): self.resolver.resolve(self.scene, self.reader.context_for_object(fixture.CHILD), '')


if __name__ == '__main__':
    unittest.main()
