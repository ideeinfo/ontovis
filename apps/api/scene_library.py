"""Immutable local-plane scene snapshots in the existing private model library.

This first storage slice accepts unbound models only. The HTTP service must
provide current authorization and resource/engineering checks; this module does
not authenticate users, resolve OntoBase objects or turn a draft into a fact.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import secrets
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID, uuid4

from .authority import PreviewError
from .model_library import ModelLibrary

MAX_SCENE_BYTES = 1024 * 1024
MAX_INSTANCES = 100
MAX_COMPONENT_BINDINGS = 1000
MAX_COORDINATE_M = 1_000_000
Authorize = Callable[[], object]
ValidateResources = Callable[[dict], object]
ValidateEngineering = Callable[[dict, list, list], object]


def _require(condition, code='INVALID_REQUEST', status=422):
    if not condition:
        raise PreviewError(status, code)


def _fields(value, expected):
    _require(type(value) is dict and set(value) == set(expected))


def _text(value, limit=200):
    _require(isinstance(value, str) and 0 < len(value.strip()) <= limit
             and all(ord(character) >= 32 for character in value))
    return value.strip()


def _uuid(value):
    _require(isinstance(value, str))
    try:
        identifier = str(UUID(value))
    except (TypeError, ValueError, AttributeError):
        raise PreviewError(422, 'INVALID_REQUEST') from None
    _require(identifier == value)
    return identifier


def _number(value, limit=MAX_COORDINATE_M):
    _require(type(value) in (float, int) and abs(value) <= limit and math.isfinite(value))
    return value


def _vector(value):
    _require(type(value) is list and len(value) == 3)
    return [_number(component) for component in value]


def _json(value):
    nodes = 0

    def visit(item, depth=0):
        nonlocal nodes
        nodes += 1
        _require(depth <= 24 and nodes <= 150_000, 'SCENE_LIMIT_EXCEEDED', 413)
        if type(item) is dict:
            for key, child in item.items():
                _require(isinstance(key, str) and len(key) <= 200)
                visit(child, depth + 1)
        elif type(item) is list:
            for child in item:
                visit(child, depth + 1)
        elif type(item) is int:
            _require(item.bit_length() <= 64)
        elif type(item) is float:
            _require(math.isfinite(item))
        else:
            _require(item is None or type(item) in (str, bool))

    visit(value)
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'), allow_nan=False)
        _require(len(encoded.encode('utf-8')) <= MAX_SCENE_BYTES, 'SCENE_LIMIT_EXCEEDED', 413)
        return encoded
    except (TypeError, ValueError, OverflowError, UnicodeError):
        raise PreviewError(422, 'INVALID_REQUEST') from None


def decode_scene_request(raw: bytes) -> dict:
    """The eventual HTTP boundary must use this strict, size-bounded decoder."""
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_SCENE_BYTES,
             'SCENE_LIMIT_EXCEEDED', 413)

    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result)
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        _require(type(value) is dict)
        _json(value)
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise PreviewError(422, 'INVALID_REQUEST') from None


def validate_local_snapshot(value: dict) -> dict:
    """Validate the editable whitelist; reject unsupported scope explicitly."""
    _json(value)
    _fields(value, ('displayName', 'coordinateFrame', 'terrain', 'instances', 'initialView', 'defaults'))
    _text(value['displayName'])
    frame = value['coordinateFrame']
    _require(type(frame) is dict)
    _require(frame.get('mode') == 'local_plane', 'SCENE_SCOPE_UNSUPPORTED')
    _fields(frame, ('mode', 'frameRevision', 'origin', 'unit', 'axes'))
    _text(frame['frameRevision'])
    _require(frame['origin'] == [0, 0, 0] and type(frame['origin']) is list
             and all(type(number) is int for number in frame['origin'])
             and frame['unit'] == 'm' and frame['axes'] == 'X_EAST_Y_UP_Z_SOUTH')
    _require(value['terrain'] is None, 'SCENE_SCOPE_UNSUPPORTED')
    _require(type(value['instances']) is list and len(value['instances']) <= MAX_INSTANCES,
             'SCENE_LIMIT_EXCEEDED', 413)
    identifiers = set()
    for item in value['instances']:
        _fields(item, ('sceneModelInstanceId', 'displayName', 'modelVersionId', 'placement',
                       'visible', 'positionLocked', 'rootBinding', 'componentBindings'))
        identifier = _uuid(item['sceneModelInstanceId'])
        _require(identifier not in identifiers, 'DUPLICATE_INSTANCE')
        identifiers.add(identifier)
        _text(item['displayName'])
        _uuid(item['modelVersionId'])
        _require(type(item['visible']) is bool and type(item['positionLocked']) is bool)
        _require(type(item['componentBindings']) is list
                 and len(item['componentBindings']) <= MAX_COMPONENT_BINDINGS,
                 'SCENE_LIMIT_EXCEEDED', 413)
        _require(item['rootBinding'] is None and item['componentBindings'] == [], 'SCENE_SCOPE_UNSUPPORTED')
        placement = item['placement']
        _fields(placement, ('position', 'height', 'headingDeg'))
        position = placement['position']
        _fields(position, ('mode', 'xM', 'zM'))
        _require(position['mode'] == 'local')
        _number(position['xM']); _number(position['zM'])
        height = placement['height']
        _fields(height, ('mode', 'relativeHeightM'))
        _require(height['mode'] == 'local_relative')
        _number(height['relativeHeightM'], 100_000)
        _require(0 <= _number(placement['headingDeg'], 360) < 360)
    view = value['initialView']
    _fields(view, ('eye', 'target'))
    _vector(view['eye']); _vector(view['target'])
    _require(sum((a - b) ** 2 for a, b in zip(view['eye'], view['target'])) > 1e-12)
    defaults = value['defaults']
    _fields(defaults, ('background', 'lighting', 'terrainMaterial'))
    _require(defaults['background'] in ('plain', 'sky')
             and defaults['lighting'] in ('neutral', 'dusk')
             and defaults['terrainMaterial'] in ('solid', 'grass'))
    result = json.loads(_json(value))
    result['displayName'] = _text(result['displayName'])
    for item in result['instances']:
        item['displayName'] = _text(item['displayName'])
    return result


class SceneLibrary:
    """A bounded storage slice, not a public service or an authorization layer."""

    def __init__(self, library: ModelLibrary):
        self.library = library
        with library.connect() as db:
            self.project_code = db.execute('select project_code from library where id=1').fetchone()[0]
            db.executescript('''
                create table if not exists scene_catalog (
                    id integer primary key check(id=1), revision integer not null, cursor_key text not null);
                create table if not exists scenes (
                    id text primary key, project_code text not null, display_name text not null,
                    head_revision text not null, updated_at text not null, instance_count integer not null);
                create table if not exists scene_revisions (
                    revision text primary key, scene_id text not null references scenes(id),
                    snapshot text not null, resource_refs text not null, saved_at text not null);
                create table if not exists scene_resource_uses (
                    revision text not null references scene_revisions(revision),
                    instance_id text not null, model_version_id text not null references versions(id),
                    primary key(revision, instance_id));
                create index if not exists scene_uses_model_version on scene_resource_uses(model_version_id);
                create index if not exists scene_revisions_scene on scene_revisions(scene_id);
                create table if not exists scene_instance_ids (
                    scene_id text not null references scenes(id), instance_id text not null,
                    primary key(scene_id, instance_id));
                create table if not exists scene_requests (
                    project_code text not null, actor text not null, action text not null,
                    request_id text not null, payload_sha256 text not null, result text not null,
                    primary key(project_code, actor, action, request_id));
                create table if not exists scene_audit (
                    id integer primary key, project_code text not null, actor text not null,
                    action text not null, request_id text not null, scene_id text not null,
                    revision text not null, payload_sha256 text not null, created_at text not null);
                create trigger if not exists scene_revision_no_update before update on scene_revisions
                    begin select raise(abort, 'immutable scene revision'); end;
                create trigger if not exists scene_revision_no_delete before delete on scene_revisions
                    begin select raise(abort, 'retained scene revision'); end;
                create trigger if not exists scene_use_no_update before update on scene_resource_uses
                    begin select raise(abort, 'immutable scene reference'); end;
                create trigger if not exists scene_use_no_delete before delete on scene_resource_uses
                    begin select raise(abort, 'retained scene reference'); end;
            ''')
            db.execute('insert or ignore into scene_catalog values (1,0,?)', (secrets.token_hex(32),))

    @staticmethod
    def capabilities():
        return {'storageScope': 'local_plane_unbound', 'supportsGeographic': False,
                'supportsEngineeringBindings': False, 'maxInstances': MAX_INSTANCES,
                'maxSnapshotBytes': MAX_SCENE_BYTES}

    @staticmethod
    def _callbacks(authorize, validate_resources, validate_engineering):
        _require(all(callable(callback) for callback in (authorize, validate_resources, validate_engineering)))

    def _scope(self, db, scene_id):
        row = db.execute('select * from scenes where id=? and project_code=?',
                         (_uuid(scene_id), self.project_code)).fetchone()
        if row is None:
            raise PreviewError(404, 'NOT_FOUND_OR_FORBIDDEN')
        return row

    @staticmethod
    def _revision(db, scene_id, revision):
        _text(revision)
        row = db.execute('select * from scene_revisions where scene_id=? and revision=?',
                         (scene_id, revision)).fetchone()
        if row is None:
            raise PreviewError(404, 'NOT_FOUND_OR_FORBIDDEN')
        return row

    def _prior(self, db, actor, action, request_id, payload_sha):
        row = db.execute('select payload_sha256,result from scene_requests where project_code=? and actor=? and action=? and request_id=?',
                         (self.project_code, actor, action, request_id)).fetchone()
        if row is not None:
            _require(hmac.compare_digest(row['payload_sha256'], payload_sha), 'REQUEST_CONFLICT', 409)
            return json.loads(row['result'])
        return None

    def _finish(self, db, actor, action, request_id, payload_sha, result):
        db.execute('insert into scene_requests values (?,?,?,?,?,?)',
                   (self.project_code, actor, action, request_id, payload_sha, _json(result)))
        db.execute('insert into scene_audit(project_code,actor,action,request_id,scene_id,revision,payload_sha256,created_at) values (?,?,?,?,?,?,?,?)',
                   (self.project_code, actor, action, request_id, result['sceneId'], result['sceneRevision'], payload_sha, result['savedAt']))
        db.execute('update scene_catalog set revision=revision+1 where id=1')

    def _resource_refs(self, db, snapshot):
        refs = []
        for identifier in sorted({item['modelVersionId'] for item in snapshot['instances']}):
            row = db.execute('select id,sha256 from versions where id=?', (identifier,)).fetchone()
            if row is None:
                raise PreviewError(404, 'NOT_FOUND_OR_FORBIDDEN')
            refs.append({'modelVersionId': identifier, 'sha256': row['sha256'],
                         'contentRevision': 'sha256:' + row['sha256']})
        return refs

    def _insert_snapshot(self, db, scene_id, revision, snapshot, now):
        refs = self._resource_refs(db, snapshot)
        db.execute('insert into scene_revisions values (?,?,?,?,?)',
                   (revision, scene_id, _json(snapshot), _json(refs), now))
        for item in snapshot['instances']:
            db.execute('insert into scene_resource_uses values (?,?,?)',
                       (revision, item['sceneModelInstanceId'], item['modelVersionId']))
            db.execute('insert or ignore into scene_instance_ids values (?,?)',
                       (scene_id, item['sceneModelInstanceId']))

    @staticmethod
    def _empty(display_name):
        return {'displayName': display_name, 'coordinateFrame': {'mode': 'local_plane',
                    'frameRevision': 'frame:' + str(uuid4()), 'origin': [0, 0, 0], 'unit': 'm',
                    'axes': 'X_EAST_Y_UP_Z_SOUTH'}, 'terrain': None, 'instances': [],
                'initialView': {'eye': [300, 200, 300], 'target': [0, 0, 0]},
                'defaults': {'background': 'plain', 'lighting': 'neutral', 'terrainMaterial': 'solid'}}

    def create(self, body, actor, authorize: Authorize, validate_resources: ValidateResources,
               validate_engineering: ValidateEngineering):
        self._callbacks(authorize, validate_resources, validate_engineering)
        authorize()
        _json(body)
        _fields(body, ('displayName', 'clientRequestId'))
        actor, name, request_id = _text(actor), _text(body['displayName']), _uuid(body['clientRequestId'])
        digest = hashlib.sha256(_json({'displayName': name}).encode()).hexdigest()
        with self.library.connect() as db:
            db.execute('begin immediate')
            prior = self._prior(db, actor, 'create', request_id, digest)
            if prior is not None:
                authorize()
                return prior
            snapshot = self._empty(name)
            validate_resources(json.loads(_json(snapshot)))
            validate_engineering(json.loads(_json(snapshot)), [], [])
            identifier, revision = str(uuid4()), 'scene:' + str(uuid4())
            now = datetime.now(timezone.utc).isoformat()
            db.execute('insert into scenes values (?,?,?,?,?,?)',
                       (identifier, self.project_code, name, revision, now, 0))
            self._insert_snapshot(db, identifier, revision, snapshot, now)
            result = {'sceneId': identifier, 'projectCode': self.project_code, 'sceneRevision': revision,
                      'headRevision': revision, 'savedAt': now, 'snapshot': snapshot, 'resourceRefs': [],
                      'validation': {'scope': 'local_plane_unbound', 'bindingIssues': []}}
            self._finish(db, actor, 'create', request_id, digest, result)
            validate_resources(json.loads(_json(snapshot)))
            validate_engineering(json.loads(_json(snapshot)), [], [])
            authorize()
            return result

    def save(self, body, actor, authorize: Authorize, validate_resources: ValidateResources,
             validate_engineering: ValidateEngineering):
        self._callbacks(authorize, validate_resources, validate_engineering)
        authorize()
        _json(body)
        _fields(body, ('sceneId', 'expectedSceneRevision', 'clientRequestId', 'snapshot',
                       'reviewedEngineering', 'rootBindingChanges'))
        actor, request_id, scene_id = _text(actor), _uuid(body['clientRequestId']), _uuid(body['sceneId'])
        _text(body['expectedSceneRevision'])
        _require(body['reviewedEngineering'] == [] and body['rootBindingChanges'] == [], 'SCENE_SCOPE_UNSUPPORTED')
        snapshot = validate_local_snapshot(body['snapshot'])
        business = {**body, 'snapshot': snapshot}
        digest = hashlib.sha256(_json(business).encode()).hexdigest()
        with self.library.connect() as db:
            db.execute('begin immediate')
            prior = self._prior(db, actor, 'save', request_id, digest)
            if prior is not None:
                self._scope(db, scene_id)
                authorize()
                return prior
            scene = self._scope(db, scene_id)
            _require(scene['head_revision'] == body['expectedSceneRevision'], 'SCENE_CHANGED', 409)
            previous = json.loads(self._revision(db, scene_id, scene['head_revision'])['snapshot'])
            # A later, richer snapshot must never be silently downgraded by this limited writer.
            validate_local_snapshot(previous)
            _require(previous['coordinateFrame'] == snapshot['coordinateFrame'], 'SCENE_SCOPE_UNSUPPORTED')
            old_items = {item['sceneModelInstanceId']: item for item in previous['instances']}
            new_items = {item['sceneModelInstanceId']: item for item in snapshot['instances']}
            for identifier, old in old_items.items():
                current = new_items.get(identifier)
                if old['positionLocked']:
                    _require(current is not None, 'INSTANCE_POSITION_LOCKED', 409)
                    _require(not current['positionLocked'] or current['placement'] == old['placement'],
                             'INSTANCE_POSITION_LOCKED', 409)
            for identifier in new_items.keys() - old_items.keys():
                reused = db.execute('select 1 from scene_instance_ids where scene_id=? and instance_id=?',
                                    (scene_id, identifier)).fetchone()
                _require(reused is None, 'INSTANCE_ID_REUSED', 409)
            # Both checks are mandatory service callbacks, not claims made by the browser.
            validate_resources(json.loads(_json(snapshot)))
            validate_engineering(json.loads(_json(snapshot)), [], [])
            revision, now = 'scene:' + str(uuid4()), datetime.now(timezone.utc).isoformat()
            self._insert_snapshot(db, scene_id, revision, snapshot, now)
            db.execute('update scenes set display_name=?,head_revision=?,updated_at=?,instance_count=? where id=?',
                       (snapshot['displayName'], revision, now, len(snapshot['instances']), scene_id))
            result = {'sceneId': scene_id, 'sceneRevision': revision, 'headRevision': revision,
                      'savedAt': now, 'validation': {'scope': 'local_plane_unbound', 'bindingIssues': []}}
            self._finish(db, actor, 'save', request_id, digest, result)
            validate_resources(json.loads(_json(snapshot)))
            validate_engineering(json.loads(_json(snapshot)), [], [])
            authorize()
            return result

    def open(self, scene_id, actor, authorize: Authorize, scene_revision=None):
        _text(actor); _require(callable(authorize)); authorize()
        with self.library.connect() as db:
            db.execute('begin')
            scene = self._scope(db, scene_id)
            row = self._revision(db, scene['id'], scene['head_revision'] if scene_revision is None else scene_revision)
            snapshot = validate_local_snapshot(json.loads(row['snapshot']))
            result = {'sceneId': scene['id'], 'projectCode': self.project_code,
                      'sceneRevision': row['revision'], 'headRevision': scene['head_revision'],
                      'savedAt': row['saved_at'], 'snapshot': snapshot,
                      'resourceRefs': json.loads(row['resource_refs']),
                      'validation': {'scope': 'local_plane_unbound', 'bindingIssues': []}}
            authorize()
            return result

    def head(self, scene_id, viewing_revision, actor, authorize: Authorize):
        _text(actor); _require(callable(authorize)); authorize()
        with self.library.connect() as db:
            db.execute('begin')
            scene = self._scope(db, scene_id)
            self._revision(db, scene['id'], viewing_revision)
            result = {'sceneId': scene['id'], 'headRevision': scene['head_revision'],
                      'updateAvailable': scene['head_revision'] != viewing_revision}
            authorize()
            return result

    @staticmethod
    def _catalog(db):
        row = db.execute('select revision,cursor_key from scene_catalog where id=1').fetchone()
        return 'scene-list:' + str(row['revision']), bytes.fromhex(row['cursor_key'])

    @staticmethod
    def _cursor(value, key):
        raw = _json(value).encode()
        return base64.urlsafe_b64encode(raw + hmac.digest(key, raw, 'sha256')).decode()

    @staticmethod
    def _uncursor(value, key):
        _require(isinstance(value, str) and 0 < len(value) <= 8192)
        try:
            raw = base64.b64decode(value, altchars=b'-_', validate=True)
            _require(len(raw) > 32 and hmac.compare_digest(hmac.digest(key, raw[:-32], 'sha256'), raw[-32:]))
            return json.loads(raw[:-32])
        except (ValueError, TypeError, UnicodeError):
            raise PreviewError(422, 'INVALID_REQUEST') from None

    def listing(self, actor, authorize: Authorize, *, access_revision, q='', cursor=None, limit=50):
        actor, access_revision = _text(actor), _text(access_revision)
        _require(callable(authorize)); authorize()
        _require(type(q) is str and len(q) <= 200 and type(limit) is int and 1 <= limit <= 100)
        query = q.strip()
        with self.library.connect() as db:
            db.execute('begin')
            revision, key = self._catalog(db)
            context = {'kind': 'scenes', 'project': self.project_code, 'actor': actor,
                       'accessRevision': access_revision, 'q': query, 'limit': limit}
            last = None
            if cursor is not None:
                page = self._uncursor(cursor, key)
                _require(type(page) is dict and set(page) == set(context) | {'revision', 'last'})
                _require(all(page[name] == value for name, value in context.items()))
                _require(page['revision'] == revision, 'SNAPSHOT_EXPIRED', 409)
                last = page['last']
                _require(type(last) is list and len(last) == 2)
                _text(last[0]); _uuid(last[1])
            params = [self.project_code, query]
            where = 'project_code=? and instr(lower(display_name),lower(?))>0'
            if last:
                where += ' and (updated_at<? or (updated_at=? and id>?))'
                params.extend([last[0], last[0], last[1]])
            rows = db.execute('select * from scenes where ' + where + ' order by updated_at desc,id asc limit ?',
                              (*params, limit + 1)).fetchall()
            visible = rows[:limit]
            next_cursor = self._cursor({**context, 'revision': revision,
                                        'last': [visible[-1]['updated_at'], visible[-1]['id']]}, key) if len(rows) > limit else None
            result = {'items': [{'sceneId': row['id'], 'displayName': row['display_name'],
                                 'headRevision': row['head_revision'], 'updatedAt': row['updated_at'],
                                 'instanceCount': row['instance_count']} for row in visible],
                      'snapshotRevision': revision, 'nextCursor': next_cursor, 'capabilities': self.capabilities()}
            authorize()
            return result

    def uses(self, model_version_id, actor, authorize: Authorize, *, access_revision, scope='current_or_retained',
             cursor=None, limit=50):
        """Count distinct scene/instance identities separately from historical revision references."""
        actor, access_revision = _text(actor), _text(access_revision)
        version_id = _uuid(model_version_id)
        _require(callable(authorize)); authorize()
        _require(scope in ('current', 'retained', 'current_or_retained')
                 and type(limit) is int and 1 <= limit <= 100)
        with self.library.connect() as db:
            db.execute('begin')
            _require(db.execute('select 1 from versions where id=?', (version_id,)).fetchone() is not None,
                     'NOT_FOUND_OR_FORBIDDEN', 404)
            revision, key = self._catalog(db)
            context = {'kind': 'model_uses', 'project': self.project_code, 'actor': actor,
                       'accessRevision': access_revision, 'versionId': version_id, 'scope': scope, 'limit': limit}
            last = None
            if cursor is not None:
                page = self._uncursor(cursor, key)
                _require(type(page) is dict and set(page) == set(context) | {'revision', 'last'})
                _require(all(page[name] == value for name, value in context.items()))
                _require(page['revision'] == revision, 'SNAPSHOT_EXPIRED', 409)
                last = _uuid(page['last'])
            grouped = '''select s.id,s.display_name,
                    count(distinct case when r.revision=s.head_revision then u.instance_id end) current_instances,
                    count(distinct case when r.revision!=s.head_revision then u.instance_id end) retained_instances,
                    sum(case when r.revision!=s.head_revision then 1 else 0 end) retained_refs
                from scene_resource_uses u join scene_revisions r on r.revision=u.revision
                join scenes s on s.id=r.scene_id
                where s.project_code=? and u.model_version_id=? group by s.id,s.display_name'''
            condition = {'current': 'current_instances>0', 'retained': 'retained_refs>0',
                         'current_or_retained': '1=1'}[scope]
            total_current, total_retained, total_retained_refs = db.execute(
                'select coalesce(sum(current_instances),0),coalesce(sum(retained_instances),0),'
                'coalesce(sum(retained_refs),0) from ('
                + grouped + ') where ' + condition, (self.project_code, version_id)).fetchone()
            tail = ' and id>?' if last is not None else ''
            parameters = [self.project_code, version_id]
            if last is not None:
                parameters.append(last)
            rows = db.execute('select * from (' + grouped + ') where ' + condition + tail
                              + ' order by id limit ?', (*parameters, limit + 1)).fetchall()
            visible = rows[:limit]
            next_cursor = self._cursor({**context, 'revision': revision, 'last': visible[-1]['id']}, key) if len(rows) > limit else None
            result = {'versionId': version_id, 'currentInstanceCount': total_current,
                      'retainedInstanceCount': total_retained,
                      'retainedReferenceCount': total_retained_refs,
                      'items': [{'sceneId': row['id'], 'displayName': row['display_name'],
                                 'currentInstanceCount': row['current_instances'],
                                 'retainedInstanceCount': row['retained_instances'],
                                 'retainedReferenceCount': row['retained_refs']} for row in visible],
                      'nextCursor': next_cursor, 'snapshotRevision': revision}
            authorize()
            return result

    def assert_model_unused(self, model_version_id, authorize: Authorize):
        """A future cleaner must call this; no physical-delete API is supplied."""
        _require(callable(authorize)); authorize()
        version_id = _uuid(model_version_id)
        with self.library.connect() as db:
            db.execute('begin')
            _require(db.execute('select 1 from scene_resource_uses where model_version_id=? limit 1',
                                (version_id,)).fetchone() is None, 'RESOURCE_IN_USE', 409)
            authorize()
