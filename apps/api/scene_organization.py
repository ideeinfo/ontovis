"""Scene-local groups and saved cameras; these never assert engineering facts."""
from __future__ import annotations

import copy
import math
from uuid import UUID

MAX_GROUPS = 16
MAX_VIEWPOINTS = 32
MAX_ROUTES = 8
MAX_ROUTE_STEPS = 32


class OrganizationError(ValueError):
    def __init__(self, *, limit=False):
        self.code = 'SCENE_LIMIT_EXCEEDED' if limit else 'INVALID_SCENE_ORGANIZATION'
        self.status = 413 if limit else 422
        super().__init__(self.code)


def _require(value, *, limit=False):
    if not value:
        raise OrganizationError(limit=limit)


def _fields(value, keys):
    _require(type(value) is dict and set(value) == set(keys))


def _uuid(value):
    try:
        normalized = str(UUID(value))
    except (ValueError, AttributeError, TypeError):
        raise OrganizationError() from None
    _require(normalized == value)
    return normalized


def _text(value, limit=80):
    _require(type(value) is str and 0 < len(value.strip()) <= limit
             and all(ord(character) >= 32 for character in value))
    return value.strip()


def _number(value, minimum, maximum):
    _require(type(value) in (int, float) and math.isfinite(value) and minimum <= value <= maximum)


def _items(value, limit):
    _require(type(value) is list)
    _require(len(value) <= limit, limit=True)
    return value


def _identity(item, key, seen):
    identifier = _uuid(item[key])
    _require(identifier not in seen)
    seen.add(identifier)
    item['displayName'] = _text(item['displayName'])
    return identifier


def validate_organization(value, instance_ids):
    """Keep stale camera targets as repairable data, but never dangling group members."""
    _fields(value, ('groups', 'viewpoints', 'routes'))
    result = copy.deepcopy(value)
    group_ids, memberships, viewpoint_ids, route_ids = set(), set(), set(), set()
    for group in _items(result['groups'], MAX_GROUPS):
        _fields(group, ('groupId', 'displayName', 'instanceIds'))
        _identity(group, 'groupId', group_ids)
        members = _items(group['instanceIds'], 100)
        _require(len(members) >= 2)
        normalized = [_uuid(member) for member in members]
        _require(len(set(normalized)) == len(normalized)
                 and set(normalized) <= instance_ids and not memberships.intersection(normalized))
        memberships.update(normalized)
    for viewpoint in _items(result['viewpoints'], MAX_VIEWPOINTS):
        _fields(viewpoint, ('viewpointId', 'displayName', 'kind', 'view', 'frameRevision', 'modelTarget'))
        _identity(viewpoint, 'viewpointId', viewpoint_ids)
        _require(viewpoint['kind'] in ('component', 'overview'))
        viewpoint['frameRevision'] = _text(viewpoint['frameRevision'], 200)
        view = viewpoint['view']
        _fields(view, ('eye', 'target'))
        for vector in (view['eye'], view['target']):
            _require(type(vector) is list and len(vector) == 3)
            for number in vector:
                _number(number, -1_000_000, 1_000_000)
        _require(sum((a-b)**2 for a, b in zip(view['eye'], view['target'])) > 1e-12)
        target = viewpoint['modelTarget']
        _require(viewpoint['kind'] != 'component' or target is not None)
        if target is not None:
            _fields(target, ('sceneModelInstanceId', 'modelVersionId'))
            _uuid(target['sceneModelInstanceId']); _uuid(target['modelVersionId'])
    for route in _items(result['routes'], MAX_ROUTES):
        _fields(route, ('routeId', 'displayName', 'steps'))
        _identity(route, 'routeId', route_ids)
        step_ids = set()
        for step in _items(route['steps'], MAX_ROUTE_STEPS):
            _fields(step, ('stepId', 'viewpointId', 'flightSeconds', 'dwellSeconds'))
            identifier = _uuid(step['stepId'])
            _require(identifier not in step_ids and _uuid(step['viewpointId']) in viewpoint_ids)
            step_ids.add(identifier)
            _number(step['flightSeconds'], .2, 30)
            _number(step['dwellSeconds'], 0, 300)
    return result
