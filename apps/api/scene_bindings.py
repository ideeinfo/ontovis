"""Pure scene binding rules; no authentication, source reads or engineering writes.

The service owns the complete EditableSceneSnapshot whitelist and current
authorization. VerifiedBinding and verified_objects must come from fresh trusted
reader/catalog results, never from a client's reviewedEngineering declarations.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from uuid import UUID

from .authority import PreviewError

MAX_COMPONENT_BINDINGS = 1000
MAX_INSTANCES = 100
MAX_JSON_BYTES = 1024 * 1024


def _require(condition, code='INVALID_REQUEST', status=422):
    if not condition:
        raise PreviewError(status, code)


def _fields(value, fields):
    _require(type(value) is dict and set(value) == set(fields))


def _text(value, limit=200):
    _require(type(value) is str and 0 < len(value) <= limit and value == value.strip()
             and all(ord(character) >= 32 for character in value))
    try:
        value.encode('utf-8')
    except UnicodeError:
        raise PreviewError(422, 'INVALID_REQUEST') from None
    return value


def _uuid(value):
    _text(value)
    try:
        _require(str(UUID(value)) == value)
    except (ValueError, TypeError, AttributeError):
        raise PreviewError(422, 'INVALID_REQUEST') from None
    return value


def _json(value):
    count = 0
    def visit(item, depth=0):
        nonlocal count
        count += 1
        _require(depth <= 24 and count <= 150_000, 'SCENE_LIMIT_EXCEEDED', 413)
        if type(item) is dict:
            for key, child in item.items():
                _require(type(key) is str and len(key) <= 512)
                visit(child, depth+1)
        elif type(item) is list:
            for child in item: visit(child, depth+1)
        elif type(item) is int:
            _require(item.bit_length() <= 64)
        elif type(item) is float:
            _require(math.isfinite(item))
        else:
            _require(item is None or type(item) in (str, bool))
    visit(value)
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        _require(len(encoded.encode()) <= MAX_JSON_BYTES, 'SCENE_LIMIT_EXCEEDED', 413)
        return encoded
    except (ValueError, TypeError, UnicodeError, OverflowError):
        raise PreviewError(422, 'INVALID_REQUEST') from None


def _key(ref):
    return ref['ontobaseConnectionId'], ref['projectCode'], ref['entityUid']


def _ref_shape(value):
    _fields(value, ('ontobaseConnectionId', 'projectCode', 'entityUid'))
    _text(value['ontobaseConnectionId']); _text(value['projectCode']); _text(value['entityUid'], 512)
    return dict(value)


def validate_ref(value, *, connection_id, project_code):
    _ref_shape(value)
    _require(value['ontobaseConnectionId'] == _text(connection_id)
             and value['projectCode'] == _text(project_code), 'NOT_FOUND_OR_FORBIDDEN', 404)
    return dict(value)


def _component_keys(value, limit=MAX_COMPONENT_BINDINGS):
    _require(type(value) is list and 0 < len(value) <= limit, 'SCENE_LIMIT_EXCEEDED' if type(value) is list and len(value) > limit else 'INVALID_REQUEST',
             413 if type(value) is list and len(value) > limit else 422)
    keys = [_text(key, 512) for key in value]
    _require(len(set(keys)) == len(keys))
    return sorted(keys)


def validate_binding_shapes(root_binding, component_bindings, *, max_bindings=MAX_COMPONENT_BINDINGS):
    """Validate declarations only; this does not authorize their project or objects."""
    _require(type(max_bindings) is int and 1 <= max_bindings <= MAX_COMPONENT_BINDINGS)
    root = None
    if root_binding is not None:
        _fields(root_binding, ('objectRef',))
        root = {'objectRef': _ref_shape(root_binding['objectRef'])}
    _require(type(component_bindings) is list)
    _require(len(component_bindings) <= max_bindings, 'SCENE_LIMIT_EXCEEDED', 413)
    _require(not component_bindings or root is not None)
    result, objects, used_keys, count = [], set(), set(), 0
    for binding in component_bindings:
        _fields(binding, ('objectRef', 'componentKeys'))
        ref = _ref_shape(binding['objectRef'])
        keys = _component_keys(binding['componentKeys'], max_bindings)
        _require(_key(ref) not in objects and not used_keys.intersection(keys))
        objects.add(_key(ref)); used_keys.update(keys); count += len(keys)
        _require(count <= max_bindings, 'SCENE_LIMIT_EXCEEDED', 413)
        result.append({'objectRef': ref, 'componentKeys': keys})
    result.sort(key=lambda item: _key(item['objectRef']))
    _json(result)
    return {'rootBinding': root, 'componentBindings': result}


def validate_bindings(root_binding, component_bindings, *, connection_id, project_code,
                      max_bindings=MAX_COMPONENT_BINDINGS):
    """Shape validation plus explicit service scope; engineering truth stays upstream."""
    result = validate_binding_shapes(root_binding, component_bindings, max_bindings=max_bindings)
    refs = ([result['rootBinding']['objectRef']] if result['rootBinding'] else [])
    refs += [binding['objectRef'] for binding in result['componentBindings']]
    for ref in refs:
        validate_ref(ref, connection_id=connection_id, project_code=project_code)
    return result


def validate_expectations(items, *, connection_id, project_code, required_refs=None):
    """Validate declarations, not their truth; the reader must compare revisions."""
    _json(items); _require(type(items) is list)
    scope = {'connection_id': connection_id, 'project_code': project_code}
    result, seen = [], set()
    for item in items:
        _fields(item, ('ref', 'expectedEntityRevision', 'installationContextId', 'expectedHierarchyRevision'))
        ref = validate_ref(item['ref'], **scope)
        _require(_key(ref) not in seen)
        seen.add(_key(ref))
        result.append({'ref': ref, 'expectedEntityRevision': _text(item['expectedEntityRevision'], 512),
                       'installationContextId': _text(item['installationContextId'], 512),
                       'expectedHierarchyRevision': _text(item['expectedHierarchyRevision'], 512)})
    if required_refs is not None:
        required = {_key(validate_ref(ref, **scope)) for ref in required_refs}
        _require(seen == required, 'ENGINEERING_CHANGED', 409)
    return sorted(result, key=lambda item: _key(item['ref']))


def _instances(snapshot, scope):
    _json(snapshot)
    _require(type(snapshot) is dict and type(snapshot.get('instances')) is list)
    _require(len(snapshot['instances']) <= MAX_INSTANCES, 'SCENE_LIMIT_EXCEEDED', 413)
    result = {}
    for item in snapshot['instances']:
        _require(type(item) is dict)
        _require({'sceneModelInstanceId', 'modelVersionId', 'rootBinding', 'componentBindings'} <= set(item))
        identifier = _uuid(item.get('sceneModelInstanceId')); _uuid(item.get('modelVersionId'))
        _require(identifier not in result)
        bindings = validate_bindings(item.get('rootBinding'), item.get('componentBindings'), **scope)
        result[identifier] = {**item, **bindings}
    return result


def _root(item):
    return item['rootBinding']['objectRef'] if item is not None and item['rootBinding'] is not None else None


def root_change_reviews(previous_snapshot, previous_scene_revision, snapshot, *, connection_id, project_code):
    scope = {'connection_id': connection_id, 'project_code': project_code}
    before, after = _instances(previous_snapshot, scope), _instances(snapshot, scope)
    revision = _text(previous_scene_revision)
    result = []
    for identifier in sorted(before.keys() | after.keys()):
        old, new = before.get(identifier), after.get(identifier)
        if _root(old) == _root(new): continue
        removed = old['componentBindings'] if old is not None else []
        digest = hashlib.sha256(_json({'sourceSceneRevision': revision, 'sceneModelInstanceId': identifier,
                                       'from': _root(old), 'removedBindings': removed}).encode()).hexdigest()
        result.append({'sceneModelInstanceId': identifier, 'from': _root(old), 'to': _root(new),
                       'clearOldComponentBindings': True, 'reviewedRemovedBindingsDigest': digest,
                       'removedBindings': json.loads(_json(removed))})
    return result


def _root_change(value, scope):
    _fields(value, ('sceneModelInstanceId', 'from', 'to', 'clearOldComponentBindings', 'reviewedRemovedBindingsDigest'))
    _uuid(value['sceneModelInstanceId'])
    for key in ('from', 'to'):
        if value[key] is not None: validate_ref(value[key], **scope)
    digest = value['reviewedRemovedBindingsDigest']
    _require(type(digest) is str and len(digest) == 64 and all(char in '0123456789abcdef' for char in digest))
    _require(value['clearOldComponentBindings'] is True)
    return json.loads(_json(value))


def validate_root_changes(previous_snapshot, previous_scene_revision, snapshot, changes, *, connection_id, project_code):
    scope = {'connection_id': connection_id, 'project_code': project_code}
    reviews = root_change_reviews(previous_snapshot, previous_scene_revision, snapshot, **scope)
    expected = {item['sceneModelInstanceId']: item for item in reviews}
    after = _instances(snapshot, scope)
    _json(changes); _require(type(changes) is list)
    result, seen = [], set()
    for item in changes:
        item = _root_change(item, scope)
        identifier = item['sceneModelInstanceId']
        _require(identifier not in seen and identifier in expected, 'ENGINEERING_CHANGED', 409)
        seen.add(identifier)
        _require(item == {key: value for key, value in expected[identifier].items() if key != 'removedBindings'}, 'ENGINEERING_CHANGED', 409)
        _require(identifier not in after or after[identifier]['componentBindings'] == [], 'ENGINEERING_CHANGED', 409)
        result.append(json.loads(_json(item)))
    _require(seen == set(expected), 'ENGINEERING_CHANGED', 409)
    return sorted(result, key=lambda item: item['sceneModelInstanceId'])


def clear_model_replacement_bindings(previous_snapshot, snapshot, *, connection_id, project_code):
    scope = {'connection_id': connection_id, 'project_code': project_code}
    before, after = _instances(previous_snapshot, scope), _instances(snapshot, scope)
    result = json.loads(_json(snapshot))
    for item in result['instances']:
        identifier = item['sceneModelInstanceId']
        if identifier in before and before[identifier]['modelVersionId'] != after[identifier]['modelVersionId']:
            item['componentBindings'] = []
    return result


@dataclass(frozen=True)
class VerifiedBinding:
    """Server-only proof of current object, subtree and catalog verification.

    Construct after the reader has checked the complete root subtree and actual
    revisions. The class is an explicit trust boundary, not an auth credential.
    """
    scene_model_instance_id: str
    model_version_id: str
    object_ref: dict
    installation_context_id: str
    component_keys: tuple[str, ...]
    entity_revision: str
    hierarchy_revision: str


def _issues(items, scope):
    _json(items); _require(type(items) is list)
    result, seen = [], set()
    common = {'sceneModelInstanceId', 'objectRef', 'installationContextId', 'blocking', 'kind', 'code'}
    for item in items:
        _require(type(item) is dict)
        kind = item.get('kind')
        if kind == 'model_version_changed':
            _fields(item, common | {'previousModelVersionId', 'previousComponentKeys', 'sourceSceneRevision'})
            _uuid(item['previousModelVersionId']); _text(item['sourceSceneRevision'])
            _require(item['code'] in ('COMPONENT_MISSING', 'MIGRATION_REQUIRED', 'SOURCE_ID_AMBIGUOUS'))
            keys = _component_keys(item['previousComponentKeys'])
        else:
            _fields(item, common | {'expectedEntityRevision', 'expectedHierarchyRevision'})
            _require(kind == 'engineering_changed' and item['code'] in ('IDENTITY_CHANGED', 'ENTITY_CHANGED', 'PARENT_CHAIN_CHANGED'))
            _text(item['expectedEntityRevision'], 512); _text(item['expectedHierarchyRevision'], 512)
            keys = None
        _uuid(item['sceneModelInstanceId']); _text(item['installationContextId'], 512)
        _require(item['blocking'] is True)
        ref = validate_ref(item['objectRef'], **scope)
        identity = item['sceneModelInstanceId'], _key(ref), item['installationContextId'], kind
        _require(identity not in seen)
        seen.add(identity)
        value = json.loads(_json(item))
        if keys is not None: value['previousComponentKeys'] = keys
        result.append(value)
    return result


def derive_binding_issues(previous_snapshot, previous_scene_revision, snapshot, previous_issues, *,
                          verified_bindings, verified_objects, current_components, root_changes,
                          connection_id, project_code, historical_expectations=()):
    """Derive model problems; only freshly verified explicit rebindings resolve them.

    Existing engineering_changed problems are retained for the authority layer
    to recompute; model evidence cannot clear a physical-chain problem.
    """
    scope = {'connection_id': connection_id, 'project_code': project_code}
    before, after = _instances(previous_snapshot, scope), _instances(snapshot, scope)
    changes = validate_root_changes(previous_snapshot, previous_scene_revision, snapshot, root_changes, **scope)
    changed_roots = {item['sceneModelInstanceId'] for item in changes}
    _require(type(verified_objects) in (list, tuple) and type(verified_bindings) in (list, tuple))
    objects = {_key(item['ref']): item for item in validate_expectations(list(verified_objects), **scope)}
    historical = {_key(item['ref']): item for item in validate_expectations(list(historical_expectations), **scope)}
    _require(type(current_components) is dict)
    catalog = {}
    for version, keys in current_components.items():
        _uuid(version); _require(type(keys) in (list, tuple, set, frozenset))
        values = [_text(key, 512) for key in keys]
        _require(len(values) == len(set(values)))
        catalog[version] = set(values)
    proofs = {}
    for proof in verified_bindings:
        _require(type(proof) is VerifiedBinding)
        identifier, version = _uuid(proof.scene_model_instance_id), _uuid(proof.model_version_id)
        ref = validate_ref(proof.object_ref, **scope); identity = identifier, _key(ref)
        keys = _component_keys(list(proof.component_keys)) if type(proof.component_keys) is tuple else None
        _require(keys is not None and identity not in proofs)
        _require(identity[0] in after and after[identifier]['modelVersionId'] == version, 'RESOURCE_CHANGED', 409)
        _require(version in catalog and set(keys) <= catalog[version], 'RESOURCE_CHANGED', 409)
        expected = objects.get(_key(ref))
        root_ref = _root(after[identifier])
        root_expectation = objects.get(_key(root_ref)) if root_ref is not None else None
        _require(expected is not None and proof.installation_context_id == expected['installationContextId']
                 and root_expectation is not None and proof.installation_context_id == root_expectation['installationContextId']
                 and proof.entity_revision == expected['expectedEntityRevision']
                 and proof.hierarchy_revision == expected['expectedHierarchyRevision'], 'ENGINEERING_CHANGED', 409)
        bindings = {_key(binding['objectRef']): binding for binding in after[identifier]['componentBindings']}
        _require(_key(ref) in bindings and bindings[_key(ref)]['componentKeys'] == keys, 'ENGINEERING_CHANGED', 409)
        proofs[identity] = proof
    result = []
    for issue in _issues(previous_issues, scope):
        identifier = issue['sceneModelInstanceId']
        if identifier in changed_roots: continue
        proof = proofs.get((identifier, _key(issue['objectRef'])))
        if issue['kind'] == 'model_version_changed' and proof is not None and proof.installation_context_id == issue['installationContextId']:
            continue
        result.append(issue)
    existing = {(item['sceneModelInstanceId'], _key(item['objectRef'])) for item in result if item['kind'] == 'model_version_changed'}
    for identifier, old in before.items():
        new = after.get(identifier)
        if new is None or identifier in changed_roots or old['modelVersionId'] == new['modelVersionId']: continue
        _require(new['componentBindings'] == [], 'ENGINEERING_CHANGED', 409)
        _require(new['modelVersionId'] in catalog, 'RESOURCE_CHANGED', 409)
        for binding in old['componentBindings']:
            ref = binding['objectRef']; identity = identifier, _key(ref)
            if identity in existing: continue
            # Historical facts identify the old association's context only;
            # they never authorize a current binding or enter current proofs.
            basis = historical if historical else objects
            expectation = basis.get(_key(ref))
            root_expectation = basis.get(_key(_root(old)))
            _require(expectation is not None and root_expectation is not None
                     and expectation['installationContextId'] == root_expectation['installationContextId'], 'ENGINEERING_CHANGED', 409)
            result.append({'sceneModelInstanceId': identifier, 'objectRef': ref,
                'installationContextId': expectation['installationContextId'], 'blocking': True,
                'kind': 'model_version_changed', 'previousModelVersionId': old['modelVersionId'],
                'previousComponentKeys': binding['componentKeys'], 'sourceSceneRevision': _text(previous_scene_revision),
                'code': 'COMPONENT_MISSING' if not set(binding['componentKeys']) <= catalog[new['modelVersionId']] else 'MIGRATION_REQUIRED'})
            existing.add(identity)
    result.sort(key=lambda item: (item['sceneModelInstanceId'], _key(item['objectRef']), item['installationContextId'], item['kind']))
    _json(result)
    return result


def required_engineering_refs(snapshot, *, previous_snapshot=None, binding_issues=(), root_changes=(),
                              connection_id, project_code):
    scope = {'connection_id': connection_id, 'project_code': project_code}
    after = _instances(snapshot, scope)
    _require(type(root_changes) in (list, tuple))
    changes = [_root_change(value, scope) for value in root_changes]
    _require(not changes or previous_snapshot is not None)
    refs = {}
    def add(ref):
        if ref is not None:
            value = validate_ref(ref, **scope); refs[_key(value)] = value
    for item in after.values():
        add(_root(item))
        for binding in item['componentBindings']: add(binding['objectRef'])
    for issue in _issues(list(binding_issues), scope): add(issue['objectRef'])
    if previous_snapshot is not None:
        before = _instances(previous_snapshot, scope)
        changed_ids = {identifier for identifier in before.keys() | after.keys()
                       if _root(before.get(identifier)) != _root(after.get(identifier))}
        for change in changes:
            identifier = change['sceneModelInstanceId']
            _require(identifier in changed_ids and change['from'] == _root(before.get(identifier))
                     and change['to'] == _root(after.get(identifier)), 'ENGINEERING_CHANGED', 409)
        for identifier, old in before.items():
            new = after.get(identifier)
            if identifier in changed_ids or new is not None and old['modelVersionId'] != new['modelVersionId']:
                add(_root(old))
                for binding in old['componentBindings']: add(binding['objectRef'])
            elif new is not None:
                current = {_key(binding['objectRef']) for binding in new['componentBindings']}
                for binding in old['componentBindings']:
                    if _key(binding['objectRef']) not in current: add(binding['objectRef'])
    result = [refs[key] for key in sorted(refs)]
    _json(result)
    return result
