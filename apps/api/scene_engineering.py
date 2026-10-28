"""Current-user reads of explicit OntoBase object and installation identities.

This reader does not authenticate a user, confirm engineering facts, or write
either database. Its caller supplies the current-session/project guard.
"""
from __future__ import annotations

from urllib.parse import quote, urlencode
from uuid import UUID

from .authority import PreviewError


def _require(value, code='SOURCE_UNAVAILABLE', status=502):
    if not value:
        raise PreviewError(status, code)


def _text(value, limit=512):
    _require(isinstance(value, str) and 0 < len(value) <= limit and value.strip()
             and all(ord(character) >= 32 for character in value))
    return value


def _argument(value, limit=512):
    _require(isinstance(value, str) and 0 < len(value) <= limit and value.strip()
             and all(ord(character) >= 32 for character in value), 'INVALID_REQUEST', 422)
    return value


def _description(value, limit):
    _require(isinstance(value, str) and 0 < len(value) <= limit and value.strip()
             and all(ord(character) >= 32 or character in '\t\r\n' for character in value))
    return value


def _context_id(value, *, request=False):
    try:
        canonical = str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise PreviewError(422 if request else 502, 'INVALID_REQUEST' if request else 'SOURCE_UNAVAILABLE') from None
    _require(canonical == value, 'INVALID_REQUEST' if request else 'SOURCE_UNAVAILABLE', 422 if request else 502)
    return canonical


def _object(value):
    _require(type(value) is dict)
    _text(value.get('entityUid')); _text(value.get('entityRevision'), 200)
    _require(value.get('lifecycle') == 'active', 'IDENTITY_CHANGED', 409)
    _require(value.get('objectScope') in ('definition', 'unclassified', 'installation'))
    result = {key: value.get(key) for key in ('entityUid', 'entityRevision', 'lifecycle', 'objectScope',
        'installationContextId', 'sourceTemplateEntityUid', 'installationPurpose')}
    _require(result['installationContextId'] is None or isinstance(result['installationContextId'], str))
    for key, limit in (('displayName', 2000), ('objectKind', 80), ('reviewStatus', 80)):
        result[key] = _description(value.get(key), limit) if key == 'displayName' else _text(value.get(key), limit)
    _require(type(value.get('hasChildren')) is bool)
    result['hasChildren'] = value['hasChildren']
    parent = value.get('definitionParentEntityUid')
    if parent is not None: _text(parent)
    count = value.get('definitionChildCount', 0)
    _require(type(count) is int and 0 <= count <= 100000)
    result.update(definitionParentEntityUid=parent, definitionChildCount=count)
    result['equipmentState'] = value.get('equipmentState', 'active')
    _require(result['equipmentState'] in ('active', 'inactive'))
    if result['sourceTemplateEntityUid'] is not None: _text(result['sourceTemplateEntityUid'])
    _require(result['installationPurpose'] in (None, 'demonstration', 'engineering'))
    classification = value.get('classification')
    _require(classification is None or type(classification) is dict)
    result['classification'] = None if classification is None else {
        key: classification.get(key) for key in ('code', 'nameZh', 'nameEn', 'reviewState')}
    if result['classification'] is not None:
        for item in result['classification'].values():
            if item is not None: _text(item, 2000)
    identifiers = value.get('identifiers')
    _require(type(identifiers) is list and len(identifiers) <= 200)
    result['identifiers'] = []
    for item in identifiers:
        _require(type(item) is dict)
        projected = {key: item.get(key) for key in ('scheme', 'value', 'role', 'scopeType', 'scopeKey', 'status')}
        for field in projected.values():
            if field is not None: _text(field, 2000)
        result['identifiers'].append(projected)
    return result


class SceneEngineeringReader:
    def __init__(self, authority, connection_id, project_code, authorize):
        _require(callable(getattr(authority, 'request', None)) and callable(authorize), 'INVALID_REQUEST', 422)
        self.authority, self.authorize = authority, authorize
        self.connection_id, self.project_code = _text(connection_id, 200), _text(project_code, 200)
        self.prefix = '/api/v1/projects/' + quote(project_code, safe='')

    def _request(self, method, path, body=None):
        self.authorize()
        value = self.authority.request(method, path, body)
        self.authorize()
        _require(type(value) is dict)
        return value

    def cabinet_members(self, parent, cursor=None):
        query = {'parentEntityUid': parent['entityUid'], 'limit': 50}
        if cursor is not None: query['cursor'] = _argument(cursor, 8192)
        value = self._request('GET', self.prefix + '/object-definitions/cabinets/children?' + urlencode(query))
        _require(value.get('projectCode') == self.project_code
            and value.get('relationKind') == 'project_definition_membership'
            and value.get('engineeringConfirmation') is False)
        _require(_object(value.get('parent')) == parent, 'ENGINEERING_CHANGED', 409)
        _require(type(value.get('total')) is int and 0 <= value['total'] <= 100000
            and type(value.get('items')) is list and len(value['items']) <= 50)
        items = []
        for row in value['items']:
            _require(type(row) is dict and row.get('basisKind') == 'user_declared')
            item = _object(row.get('object'))
            _require(item['installationContextId'] is None and item['definitionParentEntityUid'] == parent['entityUid'])
            items.append(item)
        _require(len({item['entityUid'] for item in items}) == len(items))
        token = value.get('nextCursor')
        if token is not None: _text(token, 8192)
        _text(value.get('snapshotRevision'), 200)
        return {'items': items, 'total': value['total'], 'nextCursor': token,
                'snapshotRevision': value['snapshotRevision'], 'basisKind': 'user_declared'}

    def _resolve(self, identifiers, context_id=None):
        _require(0 < len(identifiers) <= 50 and len(set(identifiers)) == len(identifiers), 'INVALID_REQUEST', 422)
        body = {'entityUids': identifiers, 'resolutionMode': 'live'}
        if context_id is not None: body['installationContextId'] = context_id
        value = self._request('POST', self.prefix + '/objects/resolve', body)
        _require(value.get('projectCode') == self.project_code, 'NOT_FOUND_OR_FORBIDDEN', 403)
        _require(value.get('resolutionMode') == 'live' and type(value.get('items')) is list
                 and len(value['items']) == len(identifiers))
        result = {}
        for resolved in value['items']:
            _require(type(resolved) is dict)
            uid = resolved.get('requestedEntityUid')
            _require(isinstance(uid, str) and uid in identifiers and uid not in result)
            if resolved.get('object') is None:
                raise PreviewError(404, 'NOT_FOUND_OR_FORBIDDEN')
            _require(resolved.get('resolution') == 'exact' and resolved.get('canonicalEntityUid') == uid,
                     'IDENTITY_CHANGED', 409)
            item = _object(resolved['object'])
            _require(item['entityUid'] == uid, 'IDENTITY_CHANGED', 409)
            _require(_object(resolved.get('canonicalObject')) == item)
            if context_id is not None:
                _require(item['installationContextId'] == context_id and item['objectScope'] == 'installation',
                         'NOT_FOUND_OR_FORBIDDEN', 403)
            result[uid] = item
        return result

    def _context(self, identifier):
        value = self._request('GET', self.prefix + '/installations/' + identifier)
        item = value.get('item')
        _require(type(item) is dict)
        _require(item.get('projectCode') == self.project_code, 'NOT_FOUND_OR_FORBIDDEN', 403)
        _require(item.get('installationContextId') == identifier, 'IDENTITY_CHANGED', 409)
        _require(item.get('purpose') in ('demonstration', 'engineering')
                 and item.get('engineeringUseAllowed') is (item['purpose'] == 'engineering'))
        result = {key: item.get(key) for key in ('installationContextId', 'projectCode', 'purpose',
            'engineeringUseAllowed', 'rootEntityUid')}
        for key, limit in (('displayName', 200), ('basis', 2000), ('hierarchyRevision', 200)):
            result[key] = _text(item.get(key), limit) if key == 'hierarchyRevision' else _description(item.get(key), limit)
        revision = result['hierarchyRevision'].removeprefix(identifier + ':')
        _require(result['hierarchyRevision'].startswith(identifier + ':') and revision.isascii()
                 and revision.isdecimal() and int(revision) > 0)
        if result['rootEntityUid'] is not None: _text(result['rootEntityUid'])
        return result

    def _relation(self, value, context):
        _require(type(value) is dict)
        identifier = _context_id(value.get('relationId'))
        revision = _text(value.get('relationRevision'), 200)
        introduced = revision.removeprefix(identifier + ':')
        _require(revision.startswith(identifier + ':') and introduced.isascii() and introduced.isdecimal()
                 and 0 < int(introduced) <= int(context['hierarchyRevision'].rsplit(':', 1)[1]))
        _require(value.get('status') == ('assumed' if context['purpose'] == 'demonstration' else 'confirmed'))
        result = {key: value.get(key) for key in ('childEntityUid', 'parentEntityUid', 'status', 'validFrom',
            'validTo', 'reason', 'reviewedBy', 'recordedAt')}
        result.update(relationId=identifier, relationRevision=revision)
        for key in ('childEntityUid', 'parentEntityUid'): _text(result[key])
        for key in ('validFrom', 'recordedAt', 'reviewedBy'): _text(result[key], 200)
        if result['validTo'] is not None: _text(result['validTo'], 200)
        _description(result['reason'], 2000)
        evidence = value.get('evidenceRefs')
        _require(type(evidence) is list and len(evidence) <= 25 and all(isinstance(item, str) for item in evidence)
                 and len(set(evidence)) == len(evidence))
        result['evidenceRefs'] = [_text(item) for item in evidence]
        return result

    def _envelope(self, value, context):
        _require(value.get('projectCode') == self.project_code, 'NOT_FOUND_OR_FORBIDDEN', 403)
        _require(value.get('installationContextId') == context['installationContextId'], 'IDENTITY_CHANGED', 409)
        _require(value.get('hierarchyRevision') == context['hierarchyRevision'], 'ENGINEERING_CHANGED', 409)
        _require(value.get('purpose') == context['purpose'] and value.get('engineeringUseAllowed') == context['engineeringUseAllowed']
                 and value.get('objectMetadataMode') == 'current')

    def _ancestors(self, item, context):
        value = self._request('GET', self.prefix + '/installations/' + context['installationContextId'] + '/ancestors?' +
            urlencode({'entityUid': item['entityUid'], 'resolutionMode': 'live'}))
        self._envelope(value, context)
        _require(value.get('entityUid') == item['entityUid'] and value.get('resolutionMode') == 'live')
        _require(value.get('completeness') in ('complete', 'incomplete') and type(value.get('path')) is list)
        result = {key: value.get(key) for key in ('projectCode', 'installationContextId', 'entityUid',
            'hierarchyRevision', 'resolutionMode', 'objectMetadataMode', 'resolvedAsOf', 'completeness', 'reasonCode')}
        result['path'] = []
        if len(value['path']) > 32:
            return {**result, 'completeness': 'incomplete', 'reasonCode': 'DEPTH_LIMIT'}
        child, seen = item['entityUid'], {item['entityUid']}
        try:
            for entry in value['path']:
                _require(type(entry) is dict)
                parent, relation = _object(entry.get('object')), self._relation(entry.get('relation'), context)
                _require(parent['objectScope'] == 'installation' and parent['installationContextId'] == context['installationContextId']
                         and parent['installationPurpose'] == context['purpose']
                         and parent['entityUid'] not in seen and relation['childEntityUid'] == child
                         and relation['parentEntityUid'] == parent['entityUid'])
                result['path'].append({'object': parent, 'relation': relation})
                child = parent['entityUid']; seen.add(child)
            if result['completeness'] == 'complete':
                _require(child == context['rootEntityUid'] and result['reasonCode'] is None)
            else:
                _require(result['reasonCode'] in ('PATH_UNAVAILABLE', 'INVALID_HIERARCHY', 'DEPTH_LIMIT'))
        except PreviewError:
            return {**result, 'path': [], 'completeness': 'incomplete', 'reasonCode': 'INVALID_HIERARCHY'}
        return result

    def _expectation(self, item, context):
        return {'ref': self._ref(item['entityUid']), 'expectedEntityRevision': item['entityRevision'],
            'installationContextId': context['installationContextId'], 'expectedHierarchyRevision': context['hierarchyRevision']}

    def _ref(self, uid):
        return {'ontobaseConnectionId': self.connection_id, 'projectCode': self.project_code, 'entityUid': uid}

    def _stable(self, item, context, ancestors):
        known = {entry['object']['entityUid']: entry['object'] for entry in ancestors['path']}
        known[item['entityUid']] = item
        current = self._resolve(list(known), context['installationContextId'])
        _require(current == known, 'ENGINEERING_CHANGED', 409)
        _require(self._context(context['installationContextId']) == context, 'ENGINEERING_CHANGED', 409)
        self.authorize()

    def _read(self, uid, expected_entity_revision=None, context_id=None, expected_hierarchy_revision=None, *, explicit=False):
        _require(isinstance(uid, str) and 0 < len(uid) <= 512 and uid.strip()
                 and all(ord(character) >= 32 for character in uid), 'INVALID_REQUEST', 422)
        if expected_entity_revision is not None: _argument(expected_entity_revision, 200)
        item = self._resolve([uid])[uid]
        if expected_entity_revision is not None:
            _require(item['entityRevision'] == expected_entity_revision, 'ENGINEERING_CHANGED', 409)
        actual = item['installationContextId']
        if explicit:
            _require(actual == context_id, 'NOT_FOUND_OR_FORBIDDEN', 403)
        empty = {'path': [], 'completeness': 'not_applicable', 'reasonCode': None}
        result = {'objectRef': self._ref(uid), 'item': item, 'context': None, 'root': None, 'ancestors': empty,
            'expectation': None, 'bindingEligible': False, 'bindingReason': 'SOURCE_ONLY'}
        if item['objectScope'] != 'installation' or actual is None:
            _require(not explicit or context_id is None and expected_hierarchy_revision is None, 'ENGINEERING_CHANGED', 409)
            _require(self._resolve([uid])[uid] == item, 'ENGINEERING_CHANGED', 409)
            self.authorize(); return {**result, 'bindingReason': 'NOT_FOUND_OR_FORBIDDEN' if item['objectScope'] == 'installation' else 'SOURCE_ONLY'}
        try:
            _context_id(actual)
            context = self._context(actual)
        except PreviewError as error:
            if explicit:
                if error.status == 404: raise PreviewError(409, 'ENGINEERING_CHANGED') from None
                raise
            if error.status not in (404, 502): raise
            _require(self._resolve([uid])[uid] == item, 'ENGINEERING_CHANGED', 409)
            self.authorize(); return {**result, 'bindingReason': 'NOT_FOUND_OR_FORBIDDEN'}
        if explicit:
            _require(context['hierarchyRevision'] == expected_hierarchy_revision, 'ENGINEERING_CHANGED', 409)
        _require(item['installationPurpose'] == context['purpose'], 'ENGINEERING_CHANGED', 409)
        ancestors = self._ancestors(item, context)
        self._stable(item, context, ancestors)
        eligible = ancestors['completeness'] == 'complete' and context['rootEntityUid'] is not None and item.get('equipmentState','active')=='active'
        root = item if uid == context['rootEntityUid'] else next((entry['object'] for entry in ancestors['path']
            if entry['object']['entityUid'] == context['rootEntityUid']), None)
        return {**result, 'context': context, 'root': root, 'ancestors': ancestors,
            'expectation': self._expectation(item, context) if eligible else None,
            'bindingEligible': eligible, 'bindingReason': None if eligible else ancestors['reasonCode']}

    def context_for_object(self, entity_uid, expected_entity_revision=None):
        return self._read(entity_uid, expected_entity_revision)

    def detail(self, installation_context_id, entity_uid, expected_hierarchy_revision, *, expected_entity_revision=None):
        if installation_context_id is not None: _context_id(installation_context_id, request=True)
        _require((installation_context_id is None) == (expected_hierarchy_revision is None), 'INVALID_REQUEST', 422)
        if expected_hierarchy_revision is not None: _argument(expected_hierarchy_revision, 200)
        return self._read(entity_uid, expected_entity_revision, installation_context_id, expected_hierarchy_revision, explicit=True)

    def ancestors(self, installation_context_id, entity_uid, expected_hierarchy_revision, *, expected_entity_revision=None):
        return self.detail(installation_context_id, entity_uid, expected_hierarchy_revision,
            expected_entity_revision=expected_entity_revision)

    def children(self, installation_context_id, entity_uid, expected_hierarchy_revision, *, cursor=None):
        _context_id(installation_context_id, request=True)
        _require(cursor is None or isinstance(cursor, str) and 0 < len(cursor) <= 8192, 'INVALID_REQUEST', 422)
        selected = self.detail(installation_context_id, entity_uid, expected_hierarchy_revision)
        context = selected['context']
        _require(context is not None, 'NOT_FOUND_OR_FORBIDDEN', 404)
        query = {'parentEntityUid': entity_uid, 'limit': 50, 'resolutionMode': 'live'}
        if cursor is not None: query['cursor'] = cursor
        value = self._request('GET', self.prefix + '/installations/' + installation_context_id + '/children?' + urlencode(query))
        self._envelope(value, context)
        _require(type(value.get('items')) is list and len(value['items']) <= 50)
        items, known = [], {entity_uid: selected['item']}
        for entry in value['items']:
            _require(type(entry) is dict)
            item, relation = _object(entry.get('object')), self._relation(entry.get('relation'), context)
            _require(item['entityUid'] not in known and item['objectScope'] == 'installation'
                     and item['installationContextId'] == installation_context_id and item['installationPurpose'] == context['purpose']
                     and relation['parentEntityUid'] == entity_uid and relation['childEntityUid'] == item['entityUid'])
            items.append({'object': item, 'relation': relation}); known[item['entityUid']] = item
        for offset in range(0, len(known), 50):
            identifiers = list(known)[offset:offset+50]
            _require(self._resolve(identifiers, installation_context_id) == {uid: known[uid] for uid in identifiers}, 'ENGINEERING_CHANGED', 409)
        _require(self._context(installation_context_id) == context, 'ENGINEERING_CHANGED', 409)
        next_cursor = value.get('nextCursor')
        _require(next_cursor is None or isinstance(next_cursor, str) and 0 < len(next_cursor) <= 8192)
        snapshot_revision = _text(value.get('snapshotRevision'), 300)
        _require(snapshot_revision.startswith(context['hierarchyRevision'] + ':'))
        self.authorize()
        return {'projectCode': self.project_code, 'installationContextId': installation_context_id,
            'parentEntityUid': entity_uid, 'hierarchyRevision': context['hierarchyRevision'],
            'snapshotRevision': snapshot_revision, 'items': items, 'nextCursor': next_cursor,
            'selection': selected}
