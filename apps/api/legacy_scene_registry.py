"""One-way registration of exact legacy sources to saved compatibility scenes.

The service supplies current-user authorization and a fixed source/proof validator.
This store never reads caller paths, authenticates users or writes OntoBase.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
from datetime import datetime, timezone
from uuid import uuid4

from .authority import PreviewError
from .model_library import ModelLibrary
from .scene_bindings import validate_bindings, validate_expectations
from .scene_library import SceneLibrary, _json, _sha, _text, _uuid, validate_local_snapshot

MAX_SOURCES = 21
IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
DOMAIN = b'ontovis.legacy-scene-registry.v1'


def _require(value, code='INVALID_REQUEST', status=422):
    if not value:
        raise PreviewError(status, code)


def _fields(value, names):
    _require(type(value) is dict and set(value) == set(names))


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _decoded(value, expected_type):
    try:
        result = json.loads(value)
    except (ValueError, TypeError, UnicodeError):
        raise PreviewError(409, 'LEGACY_TARGET_INVALID') from None
    _require(type(result) is expected_type, 'LEGACY_TARGET_INVALID', 409)
    _json(result)
    return result


def _source_key(kind, key):
    _require(kind in ('fixed_model', 'uploaded_version'))
    return _sha(key) if kind == 'fixed_model' else _uuid(key)


def source_set_digest(sources):
    """Canonical inventory digest shared with the trusted server source reader."""
    _require(type(sources) is list and 1 <= len(sources) <= MAX_SOURCES)
    values, seen = [], set()
    for item in sources:
        _fields(item, ('sourceKind', 'sourceKey', 'sourceDigest'))
        kind, key = item['sourceKind'], _source_key(item['sourceKind'], item['sourceKey'])
        _require((kind, key) not in seen)
        seen.add((kind, key))
        values.append({'sourceKind': kind, 'sourceKey': key, 'sourceDigest': _sha(item['sourceDigest'])})
    return _digest(sorted(values, key=lambda item: (item['sourceKind'], item['sourceKey'])))


class LegacySceneRegistry:
    """The registry is inert until one complete, authorized activation commits.

    ``source_validator(db, sources, default_key)`` is constructed by the service,
    never from request JSON. It verifies files, original source mappings and fresh
    Reader/Validator conditions, returning exactly two SHA256 facts:
    ``sourceSetDigest`` (using :func:`source_set_digest`) and ``engineeringDigest``.
    It is called twice on checks and under the activation's write transaction.
    """

    def __init__(self, library: ModelLibrary):
        self.library = library
        with library.connect() as db:
            self.project = db.execute('select project_code from library where id=1').fetchone()[0]
            _require(db.execute("select 1 from sqlite_master where type='table' and name='scene_catalog'").fetchone(),
                     'LEGACY_REGISTRY_UNAVAILABLE', 503)
            db.executescript('''
                create table if not exists legacy_scene_registry_state (
                    id integer primary key check(id=1), project_code text not null,
                    state text not null, default_source_key text, activation_id text, activated_at text);
                create table if not exists legacy_scene_registry_entries (
                    source_kind text not null, source_key text not null, source_digest text not null,
                    scene_id text not null unique references scenes(id),
                    registered_revision text not null references scene_revisions(revision),
                    instance_id text not null, activation_id text not null,
                    primary key(source_kind,source_key));
                create table if not exists legacy_scene_registry_requests (
                    project_code text not null, actor text not null, request_id text not null,
                    payload_sha256 text not null, result text not null,
                    primary key(project_code,actor,request_id));
                create table if not exists legacy_scene_registry_audit (
                    id integer primary key, actor text not null, request_id text not null,
                    activation_id text not null, payload_sha256 text not null,
                    facts_sha256 text not null, activated_at text not null);
            ''')
            db.execute('insert or ignore into legacy_scene_registry_state values (1,?,?,?,?,?)',
                       (self.project, 'unregistered', None, None, None))

    @staticmethod
    def assert_legacy_writable(db):
        """Call inside each legacy upload/bind write transaction, before replay."""
        table = db.execute("select 1 from sqlite_master where type='table' and name='legacy_scene_registry_state'").fetchone()
        if table is None:
            return
        state = db.execute('select state from legacy_scene_registry_state where id=1').fetchone()
        _require(state is not None and state[0] in ('unregistered', 'active'), 'LEGACY_REGISTRY_UNAVAILABLE', 503)
        _require(state[0] != 'active', 'LEGACY_MODEL_READ_ONLY', 409)

    def _state(self, db):
        row = db.execute('select * from legacy_scene_registry_state where id=1').fetchone()
        _require(row is not None and row['project_code'] == self.project
                 and row['state'] in ('unregistered', 'active'), 'LEGACY_REGISTRY_UNAVAILABLE', 503)
        return row

    @staticmethod
    def _business(body, *, activating=False):
        _json(body)
        names = {'expectedLibraryRevision', 'sources', 'defaultSourceKey'}
        _fields(body, names | ({'receipt', 'clientRequestId'} if activating else set()))
        revision, default = _text(body['expectedLibraryRevision'], 100), _sha(body['defaultSourceKey'])
        items = body['sources']
        _require(type(items) is list and 1 <= len(items) <= MAX_SOURCES)
        sources, keys, targets, scenes = [], set(), set(), set()
        for item in items:
            _fields(item, ('sourceKind', 'sourceKey', 'expectedSourceDigest', 'sceneId',
                           'expectedSceneRevision', 'sceneModelInstanceId'))
            kind, key = item['sourceKind'], _source_key(item['sourceKind'], item['sourceKey'])
            scene_id, instance_id = _uuid(item['sceneId']), _uuid(item['sceneModelInstanceId'])
            _require((kind, key) not in keys and (scene_id, instance_id) not in targets and scene_id not in scenes)
            keys.add((kind, key)); targets.add((scene_id, instance_id)); scenes.add(scene_id)
            sources.append({'sourceKind': kind, 'sourceKey': key, 'expectedSourceDigest': _sha(item['expectedSourceDigest']),
                'sceneId': scene_id, 'expectedSceneRevision': _text(item['expectedSceneRevision']),
                'sceneModelInstanceId': instance_id})
        fixed = [item for item in sources if item['sourceKind'] == 'fixed_model']
        _require(len(fixed) == 1 and fixed[0]['sourceKey'] == default)
        if activating:
            _uuid(body['clientRequestId'])
            _require(type(body['receipt']) is str and 0 < len(body['receipt']) <= 8192)
        return {'expectedLibraryRevision': revision, 'sources': sorted(sources, key=lambda item: (item['sourceKind'], item['sourceKey'])),
                'defaultSourceKey': default}

    @staticmethod
    def _legacy_rows(db):
        rows = db.execute('''select v.* from versions v left join project_model_versions p on p.version_id=v.id
            where p.version_id is null order by v.id''').fetchall()
        _require(len(rows) <= MAX_SOURCES - 1, 'LEGACY_SOURCE_CHANGED', 409)
        result = {}
        for row in rows:
            value = dict(row)
            value['bindings'] = [dict(item) for item in db.execute('select * from bindings where version_id=? order by entity_uid', (row['id'],))]
            value['audit'] = [dict(item) for item in db.execute('select * from audit where version_id=? order by id', (row['id'],))]
            _json(value)
            result[row['id']] = value
        return result

    @staticmethod
    def _target(db, source, legacy, project):
        row = db.execute('''select s.head_revision,r.snapshot,r.resource_refs,v.validation from scenes s
            join scene_revisions r on r.scene_id=s.id and r.revision=s.head_revision
            left join scene_spatial_validations v on v.revision=r.revision
            where s.id=? and s.project_code=?''', (source['sceneId'], project)).fetchone()
        _require(row is not None, 'NOT_FOUND_OR_FORBIDDEN', 404)
        _require(row['head_revision'] == source['expectedSceneRevision'], 'SCENE_CHANGED', 409)
        snapshot = validate_local_snapshot(_decoded(row['snapshot'], dict), engineering=True)
        _require(len(snapshot['instances']) == 1, 'LEGACY_TARGET_INVALID', 409)
        item = snapshot['instances'][0]
        _require(item['sceneModelInstanceId'] == source['sceneModelInstanceId'], 'LEGACY_TARGET_INVALID', 409)
        placement = item['placement']
        _require(placement['position'] == {'mode': 'local', 'xM': 0, 'zM': 0}
                 and placement['height'] == {'mode': 'local_relative', 'relativeHeightM': 0}
                 and placement['headingDeg'] == 0, 'LEGACY_TARGET_INVALID', 409)
        model = db.execute('''select v.*,p.asset_id,p.content_revision,p.calibration,p.source_version_id
            from versions v join project_model_versions p on p.version_id=v.id
            join project_model_assets a on a.id=p.asset_id where v.id=? and a.project_code=?''',
            (item['modelVersionId'], project)).fetchone()
        _require(model is not None, 'LEGACY_TARGET_INVALID', 409)
        calibration = _decoded(model['calibration'], dict) if model['calibration'] else {}
        _require(calibration.get('state') in ('verified', 'legacy_display') and calibration.get('unit') == 'm'
                 and calibration.get('axes') == 'Y_UP_RIGHT_HANDED', 'LEGACY_TARGET_INVALID', 409)
        matrix = calibration.get('modelToCalibrated')
        _require(type(matrix) is list and len(matrix) == 16 and all(type(n) in (int, float) and math.isfinite(n) for n in matrix)
                 and matrix == IDENTITY, 'LEGACY_TARGET_INVALID', 409)
        ancestry, cursor = set(), model['id']
        while cursor not in legacy:
            _require(cursor not in ancestry and len(ancestry) < 20, 'LEGACY_TARGET_INVALID', 409)
            ancestry.add(cursor)
            parent = db.execute('select source_version_id from project_model_versions where version_id=?', (cursor,)).fetchone()
            _require(parent is not None and parent[0] is not None, 'LEGACY_TARGET_INVALID', 409)
            cursor = parent[0]
        if source['sourceKind'] == 'uploaded_version':
            _require(cursor == source['sourceKey'], 'LEGACY_TARGET_INVALID', 409)
        original = legacy[cursor]
        _require(model['sha256'] == original['sha256'] and model['bytes'] == original['bytes']
                 and _decoded(model['components'], list) == _decoded(original['components'], list), 'LEGACY_TARGET_INVALID', 409)
        fixed = {'modelAssetId': model['asset_id'], 'modelVersionId': model['id'],
                 'contentRevision': model['content_revision'], 'sha256': model['sha256']}
        _require(_decoded(row['resource_refs'], list) == [fixed], 'LEGACY_TARGET_INVALID', 409)
        _require(item['rootBinding'] is not None, 'LEGACY_TARGET_INVALID', 409)
        root = item['rootBinding']['objectRef']
        bindings = validate_bindings(item['rootBinding'], item['componentBindings'],
            connection_id=root['ontobaseConnectionId'], project_code=project)
        parts = _decoded(model['components'], list)
        _require(all(type(part) is dict and type(part.get('componentKey')) is str for part in parts), 'LEGACY_TARGET_INVALID', 409)
        components = {part['componentKey']: part for part in parts}
        _require(len(components) == len(parts), 'LEGACY_TARGET_INVALID', 409)
        cabinet_rows = bindings['componentBindings']
        _require(len(cabinet_rows) == 3 and all(len(binding['componentKeys']) == 1 for binding in cabinet_rows)
                 and all(binding['objectRef'] != root for binding in cabinet_rows), 'LEGACY_TARGET_INVALID', 409)
        selected = {binding['objectRef']['entityUid']: binding['componentKeys'][0] for binding in cabinet_rows}
        original_bindings = original['bindings']
        _require(len(original_bindings) == 3 and selected == {binding['entity_uid']: binding['component_key'] for binding in original_bindings}
                 and all(key in components for key in selected.values()), 'LEGACY_TARGET_INVALID', 409)
        quality_values = [components[key].get('geometryQuality') for key in selected.values()]
        _require(all(value in ('proxy_schematic', 'source_candidate') for value in quality_values), 'LEGACY_TARGET_INVALID', 409)
        qualities = sorted(quality_values)
        _require(qualities == ['proxy_schematic', 'proxy_schematic', 'source_candidate'], 'LEGACY_TARGET_INVALID', 409)
        validation = _decoded(row['validation'], dict) if row['validation'] else {}
        _require(validation.get('bindingIssues') == [], 'LEGACY_TARGET_INVALID', 409)
        refs = [root, *[binding['objectRef'] for binding in cabinet_rows]]
        expectations = validate_expectations(validation.get('engineeringExpectations'),
            connection_id=root['ontobaseConnectionId'], project_code=project, required_refs=refs)
        by_uid = {fact['ref']['entityUid']: fact for fact in expectations}
        context = db.execute('select context_id from library where id=1').fetchone()[0]
        for binding in original_bindings:
            fact = by_uid[binding['entity_uid']]
            _require(fact['expectedEntityRevision'] == binding['entity_revision'] and fact['installationContextId'] == context
                     and fact['expectedHierarchyRevision'] == binding['hierarchy_revision'], 'LEGACY_TARGET_INVALID', 409)
        return {'sceneId': source['sceneId'], 'sceneRevision': row['head_revision'], 'instanceId': item['sceneModelInstanceId'],
                'snapshot': snapshot, 'resourceRef': fixed, 'model': dict(model), 'validation': validation}

    def _collect(self, db, business, validator):
        _require(ModelLibrary.revision(db) == business['expectedLibraryRevision'], 'MODEL_LIBRARY_CHANGED', 409)
        legacy = self._legacy_rows(db)
        requested = {item['sourceKey'] for item in business['sources'] if item['sourceKind'] == 'uploaded_version'}
        _require(requested == set(legacy), 'LEGACY_SOURCE_CHANGED', 409)
        targets = [self._target(db, item, legacy, self.project) for item in business['sources']]
        facts = validator(db, json.loads(_json(business['sources'])), business['defaultSourceKey'])
        _fields(facts, ('sourceSetDigest', 'engineeringDigest'))
        expected = source_set_digest([{'sourceKind': item['sourceKind'], 'sourceKey': item['sourceKey'],
            'sourceDigest': item['expectedSourceDigest']} for item in business['sources']])
        _require(_sha(facts['sourceSetDigest']) == expected, 'LEGACY_SOURCE_CHANGED', 409)
        _sha(facts['engineeringDigest'])
        return {'databaseDigest': _digest({key: _digest(value) for key, value in legacy.items()}),
                'targetDigest': _digest([_digest(target) for target in targets]), **facts}

    def _context(self, business, actor, access, facts):
        return {'kind': 'legacy-scene-registry-v1', 'projectCode': self.project, 'actor': actor,
                'accessRevision': access, 'businessDigest': _digest(business), **facts}

    @staticmethod
    def _key(db):
        return hmac.digest(SceneLibrary._catalog(db)[1], DOMAIN, 'sha256')

    def check(self, body, actor, authorize, source_validator, *, access_revision):
        _require(callable(authorize) and callable(source_validator))
        actor, access = _text(actor), _text(access_revision)
        business = self._business(body)
        authorize()
        with self.library.connect() as db:
            db.execute('pragma query_only=on')
            db.execute('begin')
            _require(self._state(db)['state'] == 'unregistered', 'LEGACY_MIGRATION_ALREADY_ACTIVE', 409)
            facts = self._collect(db, business, source_validator)
            _require(self._collect(db, business, source_validator) == facts, 'LEGACY_SOURCE_CHANGED', 409)
            authorize()
            receipt = SceneLibrary._cursor(self._context(business, actor, access, facts), self._key(db))
        return {'receipt': receipt, 'sourceSetDigest': facts['sourceSetDigest'],
                'impact': {'sourceCount': len(business['sources']), 'defaultSourceKey': business['defaultSourceKey'],
                           'legacyWritesWillBecomeReadOnly': True}}

    def activate(self, body, actor, authorize, source_validator, *, access_revision):
        _require(callable(authorize) and callable(source_validator))
        actor, access = _text(actor), _text(access_revision)
        business = self._business(body, activating=True)
        digest = _digest({**business, 'receipt': body['receipt']})
        authorize()
        with self.library.connect() as db:
            db.execute('begin immediate')
            prior = db.execute('''select payload_sha256,result from legacy_scene_registry_requests
                where project_code=? and actor=? and request_id=?''', (self.project, actor, body['clientRequestId'])).fetchone()
            if prior is not None:
                _require(hmac.compare_digest(prior['payload_sha256'], digest), 'REQUEST_CONFLICT', 409)
                authorize()
                return json.loads(prior['result'])
            _require(self._state(db)['state'] == 'unregistered', 'LEGACY_MIGRATION_ALREADY_ACTIVE', 409)
            facts = self._collect(db, business, source_validator)
            try:
                receipt = SceneLibrary._uncursor(body['receipt'], self._key(db))
                _require(receipt == self._context(business, actor, access, facts), 'LEGACY_PRECHECK_INVALID', 409)
            except PreviewError:
                raise PreviewError(409, 'LEGACY_PRECHECK_INVALID') from None
            identifier, now = str(uuid4()), datetime.now(timezone.utc).isoformat()
            for item in business['sources']:
                db.execute('insert into legacy_scene_registry_entries values (?,?,?,?,?,?,?)',
                    (item['sourceKind'], item['sourceKey'], item['expectedSourceDigest'], item['sceneId'],
                     item['expectedSceneRevision'], item['sceneModelInstanceId'], identifier))
            db.execute('''update legacy_scene_registry_state set state='active',default_source_key=?,activation_id=?,activated_at=? where id=1''',
                       (business['defaultSourceKey'], identifier, now))
            result = {'activationId': identifier, 'activatedAt': now, 'sourceCount': len(business['sources']),
                      'defaultSourceKey': business['defaultSourceKey'], 'legacyReadOnly': True}
            db.execute('insert into legacy_scene_registry_requests values (?,?,?,?,?)',
                       (self.project, actor, body['clientRequestId'], digest, _json(result)))
            db.execute('''insert into legacy_scene_registry_audit(actor,request_id,activation_id,payload_sha256,facts_sha256,activated_at)
                values (?,?,?,?,?,?)''', (actor, body['clientRequestId'], identifier, digest, _digest(facts), now))
            _require(self._collect(db, business, source_validator) == facts, 'LEGACY_SOURCE_CHANGED', 409)
            authorize()
        return result

    def entry(self, body, actor, authorize):
        _require(callable(authorize)); _text(actor)
        encoded = _json(body)
        _require(len(encoded.encode()) <= 16384, 'SCENE_LIMIT_EXCEEDED', 413)
        _require(type(body) is dict and set(body) in (set(), {'sourceKind', 'sourceKey'}))
        if body:
            _source_key(body['sourceKind'], body['sourceKey'])
        authorize()
        with self.library.connect() as db:
            db.execute('pragma query_only=on')
            db.execute('begin')
            state = self._state(db)
            kind = body.get('sourceKind', 'fixed_model')
            key = body.get('sourceKey', state['default_source_key'])
            row = db.execute('select * from legacy_scene_registry_entries where source_kind=? and source_key=?', (kind, key)).fetchone()
            result = {'migrated': row is not None, 'legacyReadOnly': state['state'] == 'active',
                      'available': False, 'entry': None, 'reason': 'NOT_REGISTERED'}
            if row is not None:
                target = db.execute('''select s.head_revision,r.snapshot from scenes s join scene_revisions r
                    on r.scene_id=s.id and r.revision=s.head_revision where s.id=? and s.project_code=?''',
                    (row['scene_id'], self.project)).fetchone()
                snapshot = _decoded(target['snapshot'], dict) if target is not None else None
                items = snapshot.get('instances') if snapshot is not None else []
                _require(type(items) is list and all(type(item) is dict for item in items), 'LEGACY_TARGET_INVALID', 409)
                present = [item for item in items if item.get('sceneModelInstanceId') == row['instance_id']]
                if len(present) == 1:
                    result.update(available=True, reason=None, entry={'sceneId': row['scene_id'],
                        'sceneRevision': target['head_revision'], 'registeredSceneRevision': row['registered_revision'],
                        'sceneModelInstanceId': row['instance_id']})
                else:
                    result['reason'] = 'TARGET_INSTANCE_MISSING'
            authorize()
            return result
