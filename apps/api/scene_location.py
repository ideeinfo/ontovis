"""Locate a current object in one fixed, freshly checked scene revision.

The caller owns current-user authorization and engineering reads. This module
does not follow model-node ancestry, fetch documents, or derive geographic poses.
"""
from __future__ import annotations

import copy
import itertools
import math

from .authority import PreviewError
from .scene_bindings import validate_bindings, validate_expectations, validate_ref


def _require(condition, code='INVALID_REQUEST', status=422):
    if not condition:
        raise PreviewError(status, code)


def _text(value):
    _require(type(value) is str and 0 < len(value) <= 512 and value == value.strip()
             and all(ord(character) >= 32 for character in value))
    return value


def _key(ref):
    return ref['ontobaseConnectionId'], ref['projectCode'], ref['entityUid']


def _number(value):
    _require(type(value) in (int, float) and math.isfinite(value), 'RESOURCE_CHANGED', 409)
    return value


def _vector(value):
    _require(type(value) is list and len(value) == 3, 'RESOURCE_CHANGED', 409)
    return [_number(number) for number in value]


def _box(value):
    _require(type(value) is list and len(value) == 2, 'RESOURCE_CHANGED', 409)
    low, high = _vector(value[0]), _vector(value[1])
    _require(all(a <= b for a, b in zip(low, high)), 'RESOURCE_CHANGED', 409)
    return low, high


def _summary(item, scope):
    # Project only current reader fields; never forward an upstream private key.
    fields = ('entityUid', 'entityRevision', 'displayName', 'objectKind', 'reviewStatus',
              'objectScope', 'installationContextId', 'lifecycle', 'sourceTemplateEntityUid',
              'installationPurpose', 'hasChildren', 'classification', 'identifiers')
    result = {key: copy.deepcopy(item[key]) for key in fields if key in item}
    if type(result.get('classification')) is dict:
        result['classification'] = {key: result['classification'].get(key)
                                    for key in ('code', 'nameZh', 'nameEn', 'reviewState')}
    if type(result.get('identifiers')) is list:
        result['identifiers'] = [{key: identifier.get(key) for key in (
            'scheme', 'value', 'role', 'scopeType', 'scopeKey', 'status')}
            for identifier in result['identifiers'] if type(identifier) is dict]
    result['objectRef'] = {'ontobaseConnectionId': scope['connection_id'],
                         'projectCode': scope['project_code'], 'entityUid': item['entityUid']}
    return result


def _matrix(calibration):
    _require(type(calibration) is dict and calibration.get('state') == 'verified'
             and calibration.get('unit') == 'm' and calibration.get('axes') == 'Y_UP_RIGHT_HANDED',
             'RESOURCE_NOT_READY', 409)
    value = calibration.get('modelToCalibrated')
    _require(type(value) is list and len(value) == 16, 'RESOURCE_CHANGED', 409)
    value = [_number(number) for number in value]
    # ProjectModelLibrary verifies a rigid Y rotation and translated base point.
    # Reject malformed resource data rather than turn a scale/shear into accuracy.
    _require(all(abs(value[index]) <= 1e-10 for index in (1, 3, 4, 6, 7, 9, 11))
             and abs(value[5] - 1) <= 1e-10 and abs(value[15] - 1) <= 1e-10
             and abs(value[0] - value[10]) <= 1e-10
             and abs(value[2] + value[8]) <= 1e-10
             and abs(value[0] ** 2 + value[8] ** 2 - 1) <= 1e-8,
             'RESOURCE_CHANGED', 409)
    return value


def _world_bounds(boxes, matrix, position, yaw):
    cosine, sine = math.cos(yaw), math.sin(yaw)
    points = []
    for low, high in boxes:
        # Transform each source box separately before the union. Combining local
        # boxes first would include empty rotated space between components.
        for point in itertools.product(*zip(low, high)):
            x, y, z = [sum(matrix[4 * column + row] * point[column] for column in range(3))
                       + matrix[12 + row] for row in range(3)]
            points.append([cosine * x + sine * z + position[0], y + position[1],
                           -sine * x + cosine * z + position[2]])
    _require(points and all(math.isfinite(value) for point in points for value in point),
             'RESOURCE_CHANGED', 409)
    return [[min(point[axis] for point in points) for axis in range(3)],
            [max(point[axis] for point in points) for axis in range(3)]]


class SceneLocationResolver:
    """Use trusted open/selection DTOs and a current-user fixed-version loader.

    ``representation_choice`` is exactly ``{sceneModelInstanceId, modelVersionId}``.
    Both inputs must have been read for the same request/session; the integrating
    service must guard the request again after this pure result is produced.
    """

    def __init__(self, model_loader):
        _require(callable(model_loader))
        self.model_loader = model_loader

    def resolve(self, scene_open, selected, context_epoch, representation_choice=None):
        _text(context_epoch)
        _require(type(scene_open) is dict and type(selected) is dict)
        scene_id, revision = _text(scene_open.get('sceneId')), _text(scene_open.get('sceneRevision'))
        snapshot, validation = scene_open.get('snapshot'), scene_open.get('validation')
        _require(type(snapshot) is dict and type(validation) is dict
                 and type(snapshot.get('instances')) is list and len(snapshot['instances']) <= 100)
        ref = selected.get('objectRef')
        _require(type(ref) is dict)
        scope = {'connection_id': ref.get('ontobaseConnectionId'), 'project_code': scene_open.get('projectCode')}
        validate_ref(ref, **scope)
        item = selected.get('item')
        _require(type(item) is dict and item.get('entityUid') == ref['entityUid'])
        _text(item.get('entityRevision'))
        if representation_choice is not None:
            _require(type(representation_choice) is dict
                     and set(representation_choice) == {'sceneModelInstanceId', 'modelVersionId'})
            for value in representation_choice.values(): _text(value)
        result = {'sceneId': scene_id, 'sceneRevision': revision,
            'selectedObject': _summary(item, scope), 'status': 'unavailable', 'mode': None,
            'hostObject': None, 'sceneModelInstanceId': None, 'componentKeys': [], 'modelVersionId': None,
            'geometryQuality': None, 'relationshipStatus': None, 'worldBounds': None,
            'choices': [], 'reason': None, 'contextEpoch': context_epoch}

        def unavailable(reason):
            return {**result, 'reason': reason}

        context, ancestors = selected.get('context'), selected.get('ancestors')
        if item.get('objectScope') != 'installation' or context is None:
            return unavailable('NO_REPRESENTATION')
        if type(ancestors) is not dict or ancestors.get('completeness') != 'complete':
            return unavailable('INCOMPLETE_PHYSICAL_CHAIN')
        path = ancestors.get('path')
        _require(type(context) is dict and type(path) is list and len(path) <= 32)
        ctx, hierarchy = context.get('installationContextId'), context.get('hierarchyRevision')
        nodes, relations, seen = [item], [], {item['entityUid']}
        for entry in path:
            _require(type(entry) is dict and type(entry.get('object')) is dict and type(entry.get('relation')) is dict)
            parent, relation = entry['object'], entry['relation']
            if (relation.get('childEntityUid') != nodes[-1]['entityUid']
                    or relation.get('parentEntityUid') != parent.get('entityUid')
                    or parent.get('entityUid') in seen or relation.get('status') not in ('confirmed', 'assumed')):
                return unavailable('INCOMPLETE_PHYSICAL_CHAIN')
            seen.add(parent['entityUid']); nodes.append(parent); relations.append(relation)
        if (nodes[-1]['entityUid'] != context.get('rootEntityUid')
                or any(node.get('installationContextId') != ctx or node.get('objectScope') != 'installation'
                       or node.get('lifecycle') != 'active' for node in nodes)):
            return unavailable('INCOMPLETE_PHYSICAL_CHAIN')
        expectation = selected.get('expectation')
        if (not selected.get('bindingEligible') or type(expectation) is not dict
                or expectation.get('ref') != ref or expectation.get('expectedEntityRevision') != item['entityRevision']
                or expectation.get('installationContextId') != ctx or expectation.get('expectedHierarchyRevision') != hierarchy):
            return unavailable('BINDING_NEEDS_REVIEW')

        expected = {_key(row['ref']): row for row in validate_expectations(
            validation.get('engineeringExpectations', []), **scope)}
        issues = validation.get('bindingIssues', [])
        _require(type(issues) is list)
        instances, identifiers = [], set()
        for instance in snapshot['instances']:
            _require(type(instance) is dict)
            identifier = _text(instance.get('sceneModelInstanceId'))
            _require(identifier not in identifiers); identifiers.add(identifier)
            bindings = validate_bindings(instance.get('rootBinding'), instance.get('componentBindings'), **scope)
            instances.append({**instance, **bindings})
        fixed_models = scene_open.get('resourceRefs')
        _require(type(fixed_models) is list)
        model_refs = {}
        for fixed in fixed_models:
            _require(type(fixed) is dict and type(fixed.get('modelVersionId')) is str
                     and fixed['modelVersionId'] not in model_refs)
            model_refs[fixed['modelVersionId']] = fixed
        poses = {}
        if snapshot.get('coordinateFrame', {}).get('mode') == 'projected_site':
            display = validation.get('displayPlacements')
            _require(type(display) is list, 'RESOURCE_CHANGED', 409)
            for pose in display:
                _require(type(pose) is dict and pose.get('sceneModelInstanceId') in identifiers
                         and pose['sceneModelInstanceId'] not in poses, 'RESOURCE_CHANGED', 409)
                poses[pose['sceneModelInstanceId']] = pose
            _require(set(poses) == identifiers, 'RESOURCE_CHANGED', 409)
        else:
            _require(snapshot.get('coordinateFrame', {}).get('mode') == 'local_plane')
        models = {}

        def matches(object_ref, node):
            basis = expected.get(_key(object_ref))
            return (basis is not None and basis['installationContextId'] == ctx
                    and basis['expectedHierarchyRevision'] == hierarchy
                    and basis['expectedEntityRevision'] == node.get('entityRevision'))

        for index, host in enumerate(nodes):
            host_ref = {**ref, 'entityUid': host['entityUid']}
            blocked, candidates, resource_reason = False, [], None
            for issue in issues:
                _require(type(issue) is dict and issue.get('blocking') is True
                         and issue.get('sceneModelInstanceId') in identifiers)
                validate_ref(issue.get('objectRef'), **scope)
                if issue['objectRef'] == host_ref and issue.get('installationContextId') == ctx:
                    blocked = True
            for instance in instances:
                root = instance['rootBinding']
                if root is None: continue
                root_ref = root['objectRef']
                root_node = next((node for node in nodes[index:] if node['entityUid'] == root_ref['entityUid']), None)
                component = next((binding for binding in instance['componentBindings'] if binding['objectRef'] == host_ref), None)
                direct_root = root_ref == host_ref
                if not component and not direct_root: continue
                if (root_node is None or not matches(host_ref, host) or not matches(root_ref, root_node)
                        or any(issue['sceneModelInstanceId'] == instance['sceneModelInstanceId']
                               and issue['objectRef'] == root_ref and issue.get('installationContextId') == ctx for issue in issues)):
                    blocked = True; continue
                if any(issue['sceneModelInstanceId'] == instance['sceneModelInstanceId']
                       and issue['objectRef'] == host_ref and issue.get('installationContextId') == ctx for issue in issues):
                    continue
                keys = component['componentKeys'] if component else []
                try:
                    version = instance['modelVersionId']
                    if version not in models: models[version] = self.model_loader(version)
                    model = models[version]; fixed = model_refs.get(version)
                    _require(type(model) is dict and model.get('modelVersionId') == version
                             and fixed is not None and all(model.get(name) == fixed.get(name) for name in ('contentRevision', 'sha256'))
                             and ('modelAssetId' not in fixed or model.get('modelAssetId') == fixed['modelAssetId']), 'RESOURCE_CHANGED', 409)
                    _require(model.get('state') == 'ready' and model.get('canPlace') is True
                             and model.get('calibrationState') == 'verified', 'RESOURCE_NOT_READY', 409)
                    matrix = _matrix(model.get('calibration'))
                    if keys:
                        catalog = model.get('components')
                        _require(type(catalog) is list and all(type(row) is dict
                            and type(row.get('componentKey')) is str and 0 < len(row['componentKey']) <= 512
                            for row in catalog), 'RESOURCE_CHANGED', 409)
                        by_key = {row.get('componentKey'): row for row in catalog}
                        _require(len(by_key) == len(catalog) and all(key in by_key for key in keys), 'BINDING_NEEDS_REVIEW', 409)
                        parts = [by_key[key] for key in keys]
                        _require(all(row.get('geometryQuality') in ('source_candidate', 'proxy_schematic') for row in parts), 'RESOURCE_CHANGED', 409)
                        quality = 'proxy_schematic' if any(row['geometryQuality'] == 'proxy_schematic' for row in parts) else 'source_candidate'
                        boxes = [_box(row.get('bounds')) for row in parts]
                    else:
                        report = model.get('report')
                        _require(type(report) is dict and type(report.get('bounds')) is dict, 'RESOURCE_CHANGED', 409)
                        bounds = report['bounds']
                        boxes = [_box([bounds.get('min'), bounds.get('max')])]; quality = 'source_candidate'
                    if poses:
                        pose = poses[instance['sceneModelInstanceId']]
                        position, yaw = _vector(pose.get('position')), _number(pose.get('threeYawRad'))
                    else:
                        placement = instance['placement']; local = placement['position']; height = placement['height']
                        _require(local.get('mode') == 'local' and height.get('mode') == 'local_relative', 'RESOURCE_CHANGED', 409)
                        position = [_number(local.get('xM')), _number(height.get('relativeHeightM')), _number(local.get('zM'))]
                        yaw = -math.radians(_number(placement.get('headingDeg')))
                    world = _world_bounds(boxes, matrix, position, yaw)
                    choice = {'sceneModelInstanceId': instance['sceneModelInstanceId'], 'instanceName': instance['displayName'],
                        'modelVersionId': version, 'componentKeys': list(keys), 'geometryQuality': quality,
                        'visible': instance['visible'], 'hostObject': _summary(host, scope)}
                    candidates.append((choice, world))
                except PreviewError as error:
                    if error.status not in (409, 422): raise
                    blocked = True; resource_reason = error.code
            if not candidates and not blocked: continue
            candidates.sort(key=lambda candidate: candidate[0]['sceneModelInstanceId'])
            if not candidates:
                return unavailable(resource_reason or 'BINDING_NEEDS_REVIEW')
            chosen = None
            if representation_choice is not None:
                chosen = next((candidate for candidate in candidates if all(
                    candidate[0][key] == value for key, value in representation_choice.items())), None)
                if chosen is None: return unavailable('BINDING_NEEDS_REVIEW')
            elif len(candidates) > 1 or blocked:
                return {**result, 'status': 'choose_representation',
                    'choices': [candidate[0] for candidate in candidates],
                    'reason': 'BINDING_NEEDS_REVIEW' if blocked else 'AMBIGUOUS_REPRESENTATION'}
            else:
                chosen = candidates[0]
            choice, bounds = chosen
            relationship = None if index == 0 else ('assumed' if any(
                relation['status'] == 'assumed' for relation in relations[:index]) else 'confirmed')
            return {**result, 'status': 'located', 'mode': 'direct' if index == 0 else 'ancestor',
                'hostObject': choice['hostObject'], 'sceneModelInstanceId': choice['sceneModelInstanceId'],
                'componentKeys': choice['componentKeys'], 'modelVersionId': choice['modelVersionId'],
                'geometryQuality': choice['geometryQuality'], 'relationshipStatus': relationship,
                'worldBounds': bounds}
        return unavailable('NO_REPRESENTATION')
