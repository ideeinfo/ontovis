"""Bounded scene organization metadata, including repairable stale cameras."""
import copy
import math
import unittest
from uuid import uuid4

from apps.api.scene_organization import OrganizationError, validate_organization


def organization(instance_ids, model_id):
    view_id = str(uuid4())
    return {
        'groups': ([{'groupId': str(uuid4()), 'displayName': '设备组', 'instanceIds': list(instance_ids)}]
                   if len(instance_ids) > 1 else []),
        'viewpoints': [{'viewpointId': view_id, 'displayName': '构件视点', 'kind': 'component',
                        'view': {'eye': [20, 30, 40], 'target': [0, 10, 0]}, 'frameRevision': 'local-r1',
                        'modelTarget': {'sceneModelInstanceId': instance_ids[0], 'modelVersionId': model_id}}],
        'routes': [{'routeId': str(uuid4()), 'displayName': '检修路线', 'steps': [
            {'stepId': str(uuid4()), 'viewpointId': view_id, 'flightSeconds': 1.2, 'dwellSeconds': 2}]}],
    }


class SceneOrganizationTests(unittest.TestCase):
    def setUp(self):
        self.ids = {str(uuid4()), str(uuid4())}
        self.value = organization(sorted(self.ids), str(uuid4()))

    def invalid(self, change, *, limit=False):
        value = copy.deepcopy(self.value)
        change(value)
        with self.assertRaises(OrganizationError) as caught:
            validate_organization(value, self.ids)
        self.assertEqual(caught.exception.code, 'SCENE_LIMIT_EXCEEDED' if limit else 'INVALID_SCENE_ORGANIZATION')

    def test_normalizes_names_without_mutating_caller_and_keeps_independent_copy(self):
        self.value['groups'][0]['displayName'] = '  设备组  '
        before = copy.deepcopy(self.value)
        result = validate_organization(self.value, self.ids)
        self.assertEqual(self.value, before)
        self.assertEqual(result['groups'][0]['displayName'], '设备组')
        result['viewpoints'][0]['view']['eye'][0] = 99
        self.assertEqual(self.value['viewpoints'][0]['view']['eye'][0], 20)

    def test_group_members_must_exist_be_unique_and_not_overlap(self):
        for members in [[], [next(iter(self.ids))], [str(uuid4()), str(uuid4())], [next(iter(self.ids))]*2]:
            with self.subTest(members=members):
                self.invalid(lambda value: value['groups'][0].update(instanceIds=members))
        self.invalid(lambda value: value['groups'].append({**value['groups'][0], 'groupId': str(uuid4())}))
        self.invalid(lambda value: value['groups'][0].update(children=[]))

    def test_identity_names_and_all_fields_are_strict(self):
        self.invalid(lambda value: value.update(arbitrary=True))
        self.invalid(lambda value: value['groups'][0].update(groupId='not-an-id'))
        self.invalid(lambda value: value['groups'][0].update(groupId='ABCDEF12-3456-7890-ABCD-123456789ABC'))
        for name in ['', ' ', 'x'*81, 'line\nbreak']:
            self.invalid(lambda value: value['viewpoints'][0].update(displayName=name))
        self.invalid(lambda value: value['viewpoints'].append(copy.deepcopy(value['viewpoints'][0])))
        self.invalid(lambda value: value['routes'].append(copy.deepcopy(value['routes'][0])))

    def test_camera_requires_finite_bounded_vectors_and_nonzero_direction(self):
        for number in [True, math.nan, math.inf, -math.inf, 1_000_001, '2']:
            self.invalid(lambda value: value['viewpoints'][0]['view']['eye'].__setitem__(0, number))
        self.invalid(lambda value: value['viewpoints'][0]['view'].update(eye=[0, 10, 0]))
        self.invalid(lambda value: value['viewpoints'][0]['view'].update(eye=[0, 1]))
        self.invalid(lambda value: value['viewpoints'][0].update(kind='equipment'))
        self.invalid(lambda value: value['viewpoints'][0].update(modelTarget=None))
        self.invalid(lambda value: value['viewpoints'][0]['modelTarget'].update(entityUid='forged-fact'))

    def test_stale_camera_target_and_frame_are_retained_as_repairable_metadata(self):
        self.value['viewpoints'][0]['modelTarget'] = {'sceneModelInstanceId': str(uuid4()), 'modelVersionId': str(uuid4())}
        self.value['viewpoints'][0]['frameRevision'] = 'old-frame'
        self.assertEqual(validate_organization(self.value, self.ids), self.value)
        self.value['viewpoints'][0].update(kind='overview', modelTarget=None)
        self.assertEqual(validate_organization(self.value, self.ids), self.value)

    def test_route_references_durations_and_step_identity_are_checked(self):
        self.invalid(lambda value: value['routes'][0]['steps'][0].update(viewpointId=str(uuid4())))
        self.invalid(lambda value: value['routes'][0]['steps'].append(copy.deepcopy(value['routes'][0]['steps'][0])))
        for key, numbers in [('flightSeconds', [0, .199, 30.001, True, math.nan]),
                             ('dwellSeconds', [-.1, 300.001, False, math.inf])]:
            for number in numbers:
                self.invalid(lambda value: value['routes'][0]['steps'][0].update({key: number}))
        for flight, dwell in [(.2, 0), (30, 300)]:
            self.value['routes'][0]['steps'][0].update(flightSeconds=flight, dwellSeconds=dwell)
            validate_organization(self.value, self.ids)

    def test_collection_limits_and_empty_drafts(self):
        for key, maximum in [('groups', 16), ('viewpoints', 32), ('routes', 8)]:
            self.invalid(lambda value: value.update({key: [value[key][0]]*(maximum+1)}), limit=True)
        self.invalid(lambda value: value['routes'][0].update(steps=[value['routes'][0]['steps'][0]]*33), limit=True)
        self.value['routes'][0]['steps'] = []
        validate_organization(self.value, self.ids)
        self.assertEqual(validate_organization({'groups': [], 'viewpoints': [], 'routes': []}, set()),
                         {'groups': [], 'viewpoints': [], 'routes': []})
