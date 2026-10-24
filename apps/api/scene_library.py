"""Immutable local and explicitly anchored regional scene snapshots.

Engineering bindings require an explicit trusted server callback. The HTTP service must
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
from .scene_bindings import MAX_COMPONENT_BINDINGS, validate_binding_shapes
from .scene_environment import validate_environment, environment_write, preserve_environment
from .scene_organization import OrganizationError, validate_organization

MAX_SCENE_BYTES = 1024 * 1024
MAX_INSTANCES = 100
MAX_COORDINATE_M = 1_000_000
Authorize = Callable[[], object]
ValidateResources = Callable[[dict], object]
ValidateEngineering = Callable[[dict, list, list], object]
EngineeringCheck = Callable[..., dict]
ValidateGeometry = Callable[..., dict]


def _require(condition, code='INVALID_REQUEST', status=422):
    if not condition:
        raise PreviewError(status, code)


def _fields(value, expected):
    _require(type(value) is dict and set(value) == set(expected))


def _snapshot_fields(value):
    required = {'displayName', 'coordinateFrame', 'terrain', 'instances', 'initialView', 'defaults'}
    _require(type(value) is dict and required <= set(value) <= required | {'organization','imagery','environment','description'})
    if 'description' in value:
        _description(value['description'])
    validate_environment(value)
    image = value.get('imagery')
    if image is not None:
        _fields(image, ('imageryVersionId','expectedContentRevision','expectedReportSha256','visible'))
        _uuid(image['imageryVersionId']); _text(image['expectedContentRevision']); _sha(image['expectedReportSha256'])
        _require(type(image['visible']) is bool and type(value['coordinateFrame']) is dict
                 and value['coordinateFrame'].get('mode') == 'projected_site' and value['terrain'] is not None, 'SCENE_SCOPE_UNSUPPORTED')


def _organization(value, identifiers):
    if 'organization' in value:
        try:
            value['organization'] = validate_organization(value['organization'], identifiers)
        except OrganizationError as error:
            raise PreviewError(error.status, error.code) from None


def _text(value, limit=200):
    _require(isinstance(value, str) and 0 < len(value.strip()) <= limit
             and all(ord(character) >= 32 for character in value))
    return value.strip()


def _description(value):
    _require(isinstance(value, str) and len(value) <= 2000
             and all(ord(ch) >= 32 or ch == '\n' for ch in value))
    return value


def _information_write(body, previous):
    if body.get('sceneInfoWriteVersion') not in (None, 1) or type(body.get('sceneInfoWriteVersion', 1)) is not int:
        raise PreviewError(409, 'SCENE_INFO_WRITE_VERSION_REQUIRED')
    if 'description' in previous and (body.get('sceneInfoWriteVersion') != 1 or 'description' not in body['snapshot']):
        raise PreviewError(409, 'SCENE_INFO_WRITE_VERSION_REQUIRED')


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


def validate_local_snapshot(value: dict, *, engineering=False) -> dict:
    """Validate the editable whitelist; reject unsupported scope explicitly."""
    _json(value)
    _snapshot_fields(value)
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
    binding_count = component_key_count = 0
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
        if engineering:
            validate_binding_shapes(item['rootBinding'], item['componentBindings'])
            binding_count += len(item['componentBindings'])
            component_key_count += sum(len(binding['componentKeys']) for binding in item['componentBindings'])
            _require(binding_count <= MAX_COMPONENT_BINDINGS and component_key_count <= MAX_COMPONENT_BINDINGS,
                     'SCENE_LIMIT_EXCEEDED', 413)
        else:
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
    _organization(result, identifiers)
    return result


def validate_snapshot(value: dict, *, geographic=False, engineering=False) -> dict:
    """Keep the legacy local whitelist; regional geometry needs a trusted callback."""
    _json(value)
    _snapshot_fields(value)
    frame = value['coordinateFrame']
    _require(type(frame) is dict)
    if frame.get('mode') == 'local_plane':
        return validate_local_snapshot(value, engineering=engineering)
    _require(geographic and frame.get('mode') == 'projected_site', 'SCENE_SCOPE_UNSUPPORTED')
    required = {'mode', 'frameRevision', 'horizontalCrs', 'verticalDatum', 'transformId',
                'originEasting', 'originNorthing', 'originHeight', 'convergenceRuleId', 'anchor'}
    _require(required <= set(frame) <= required | {'relativeReferenceId'})
    for key in ('frameRevision', 'horizontalCrs', 'transformId', 'convergenceRuleId'):
        _text(frame[key], 500)
    _require(frame['verticalDatum'] in ('EGM2008', 'EGM96', 'WGS84_ELLIPSOIDAL', 'UNKNOWN_RELATIVE'))
    for key in ('originEasting', 'originNorthing', 'originHeight'):
        _number(frame[key], 20_000_000)
    _require(type(frame['anchor']) is dict)
    if frame['verticalDatum'] == 'UNKNOWN_RELATIVE':
        _text(frame.get('relativeReferenceId'))
    else:
        _require('relativeReferenceId' not in frame)
    _fields(value['terrain'], ('terrainVersionId', 'expectedContentRevision'))
    _uuid(value['terrain']['terrainVersionId']); _text(value['terrain']['expectedContentRevision'])
    _require(type(value['instances']) is list and len(value['instances']) <= MAX_INSTANCES,
             'SCENE_LIMIT_EXCEEDED', 413)
    result = json.loads(_json(value))
    # Reuse the existing common instance/name/camera/default whitelist without
    # asking the local-plane validator to interpret geographic height fields.
    common = json.loads(_json(value))
    common.pop('environment', None)
    common['coordinateFrame'] = {'mode': 'local_plane', 'frameRevision': 'schema-check',
                                 'origin': [0, 0, 0], 'unit': 'm', 'axes': 'X_EAST_Y_UP_Z_SOUTH'}
    common['terrain'] = None
    common.pop('imagery', None)
    for item, probe in zip(result['instances'], common['instances']):
        _require(type(item) is dict and type(item.get('placement')) is dict)
        placement = item['placement']
        _fields(placement, ('position', 'height', 'headingDeg'))
        position, height = placement['position'], placement['height']
        _fields(position, ('mode', 'longitude', 'latitude', 'transformId', 'frameRevision'))
        _require(position['mode'] == 'geographic'
                 and position['transformId'] == frame['transformId']
                 and position['frameRevision'] == frame['frameRevision'])
        _number(position['longitude'], 180); _number(position['latitude'], 90)
        _require(type(height) is dict)
        if height.get('mode') == 'terrain_ground':
            _fields(height, ('mode', 'terrainVersionId', 'terrainSha256', 'sampleLongitude',
                             'sampleLatitude', 'sampledHeightM', 'offsetM', 'verticalDatum', 'samplingRule'))
            _uuid(height['terrainVersionId']); _sha(height['terrainSha256'])
            _number(height['sampleLongitude'], 180); _number(height['sampleLatitude'], 90)
            _number(height['sampledHeightM'], 100_000); _number(height['offsetM'], 100_000)
            _text(height['samplingRule'])
        else:
            _fields(height, ('mode', 'valueM', 'verticalDatum', 'sourceNote'))
            _require(height['mode'] == 'absolute')
            _number(height['valueM'], 100_000); _text(height['sourceNote'], 2000)
        _require(height['verticalDatum'] == frame['verticalDatum'], 'VERTICAL_DATUM_CONFLICT')
        probe['placement'] = {'position': {'mode': 'local', 'xM': 0, 'zM': 0},
                              'height': {'mode': 'local_relative', 'relativeHeightM': 0},
                              'headingDeg': placement['headingDeg']}
    normalized = validate_local_snapshot(common, engineering=engineering)
    result['displayName'] = normalized['displayName']
    if 'organization' in normalized:
        result['organization'] = normalized['organization']
    for item, normal in zip(result['instances'], normalized['instances']):
        item['displayName'] = normal['displayName']
    return result


def _sha(value):
    _require(isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value))
    return value


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _receipt_snapshot_digest(value):
    # Browser JSON round trips turn 200.0/-0.0 into 200/0. Bind equal numeric
    # values without changing stored snapshots or existing idempotency digests.
    _json(value)

    def normalize(item):
        if type(item) is dict:
            return {key: normalize(child) for key, child in item.items()}
        if type(item) is list:
            return [normalize(child) for child in item]
        if type(item) is float and item.is_integer():
            integer = int(item)
            if integer.bit_length() <= 64:
                return integer
        return item

    return _digest(normalize(value))


class SceneLibrary:
    """A bounded storage slice, not a public service or an authorization layer."""

    def __init__(self, library: ModelLibrary, *, model_identity=None):
        self.library = library
        _require(model_identity is None or callable(model_identity))
        self.model_identity = model_identity
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
                create table if not exists scene_spatial_validations (
                    revision text primary key references scene_revisions(revision),
                    validation text not null, height_provenance text not null);
                create table if not exists scene_terrain_uses (
                    revision text not null references scene_revisions(revision),
                    terrain_version_id text not null references terrain_versions(id), content_revision text not null,
                    source_sha256 text not null, report_sha256 text not null,
                    primary key(revision, terrain_version_id));
                create index if not exists scene_uses_terrain on scene_terrain_uses(terrain_version_id);
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
                create trigger if not exists scene_spatial_no_update before update on scene_spatial_validations
                    begin select raise(abort, 'immutable scene validation'); end;
                create trigger if not exists scene_spatial_no_delete before delete on scene_spatial_validations
                    begin select raise(abort, 'retained scene validation'); end;
                create trigger if not exists scene_terrain_no_update before update on scene_terrain_uses
                    begin select raise(abort, 'immutable scene terrain reference'); end;
                create trigger if not exists scene_terrain_no_delete before delete on scene_terrain_uses
                    begin select raise(abort, 'retained scene terrain reference'); end;
            ''')
            db.execute('insert or ignore into scene_catalog values (1,0,?)', (secrets.token_hex(32),))

    @staticmethod
    def capabilities(*, geographic=False, engineering=False):
        return {'storageScope': 'project_scenes' if engineering else 'projected_site_unbound' if geographic else 'local_plane_unbound', 'supportsGeographic': geographic,
                'supportsEngineeringBindings': engineering, 'maxInstances': MAX_INSTANCES,
                'environmentSchemaVersions': [1], 'waterModes': ['normal-waves'], 'surroundingBackgroundModes': ['auto', 'off'], 'cloudModes': ['procedural-cumulus-v1'], 'sceneInfoWriteVersion': 1,
                'maxSnapshotBytes': MAX_SCENE_BYTES, 'maxCheckJsonBytes': MAX_SCENE_BYTES}

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
            if self.model_identity is None:
                refs.append({'modelVersionId': identifier, 'sha256': row['sha256'],
                             'contentRevision': 'sha256:' + row['sha256']})
            else:
                identity = self.model_identity(identifier, db=db)
                _require(type(identity) is dict and identity.get('modelVersionId') == identifier
                         and identity.get('sha256') == row['sha256'], 'RESOURCE_CHANGED', 409)
                ref = {'modelVersionId': identifier, 'sha256': _sha(identity['sha256']),
                       'contentRevision': _text(identity.get('contentRevision'))}
                if identity.get('modelAssetId') is not None:
                    ref['modelAssetId'] = _uuid(identity['modelAssetId'])
                refs.append(ref)
        return refs

    def _insert_snapshot(self, db, scene_id, revision, snapshot, now, *, refs=None, spatial=None):
        refs = self._resource_refs(db, snapshot) if refs is None else refs
        db.execute('insert into scene_revisions values (?,?,?,?,?)',
                   (revision, scene_id, _json(snapshot), _json(refs), now))
        for item in snapshot['instances']:
            db.execute('insert into scene_resource_uses values (?,?,?)',
                       (revision, item['sceneModelInstanceId'], item['modelVersionId']))
            db.execute('insert or ignore into scene_instance_ids values (?,?)',
                       (scene_id, item['sceneModelInstanceId']))
        spatial = spatial or {'validation': {'scope': 'local_plane_unbound', 'bindingIssues': []},
                              'heightProvenance': [], 'terrainRefs': []}
        db.execute('insert into scene_spatial_validations values (?,?,?)',
                   (revision, _json(spatial['validation']), _json(spatial['heightProvenance'])))
        for terrain in spatial['terrainRefs']:
            db.execute('insert into scene_terrain_uses values (?,?,?,?,?)',
                       (revision, terrain['terrainVersionId'], terrain['contentRevision'],
                        terrain['sha256'], terrain['reportSha256']))
        image = snapshot.get('imagery')
        if image is not None:
            _require(db.execute("select 1 from sqlite_master where type='table' and name='imagery_versions'").fetchone() is not None, 'RESOURCE_VALIDATION_REQUIRED', 409)
            # Old installations need no imagery schema. Create its retained use
            # table atomically on the first actual image save, after its parent exists.
            db.execute('''create table if not exists scene_imagery_uses (
                revision text not null references scene_revisions(revision),
                imagery_version_id text not null references imagery_versions(id), content_revision text not null,
                source_sha256 text not null, report_sha256 text not null, primary key(revision,imagery_version_id))''')
            db.execute("create trigger if not exists scene_imagery_no_update before update on scene_imagery_uses begin select raise(abort, 'immutable scene imagery reference'); end")
            db.execute("create trigger if not exists scene_imagery_no_delete before delete on scene_imagery_uses begin select raise(abort, 'retained scene imagery reference'); end")
            row = db.execute('select * from imagery_versions where id=?', (image['imageryVersionId'],)).fetchone()
            _require(row is not None and row['content_revision'] == image['expectedContentRevision']
                     and row['report_sha256'] == image['expectedReportSha256'], 'RESOURCE_CHANGED', 409)
            db.execute('insert into scene_imagery_uses values (?,?,?,?,?)',
                       (revision,row['id'],row['content_revision'],row['sha256'],row['report_sha256']))

    @staticmethod
    def _empty(display_name):
        return {'displayName': display_name, 'coordinateFrame': {'mode': 'local_plane',
                    'frameRevision': 'frame:' + str(uuid4()), 'origin': [0, 0, 0], 'unit': 'm',
                    'axes': 'X_EAST_Y_UP_Z_SOUTH'}, 'terrain': None, 'instances': [],
                'initialView': {'eye': [300, 200, 300], 'target': [0, 0, 0]},
                'defaults': {'background': 'plain', 'lighting': 'neutral', 'terrainMaterial': 'solid'}}

    def create(self, body, actor, authorize: Authorize, validate_resources: ValidateResources,
               validate_engineering: ValidateEngineering, *, engineering_check: EngineeringCheck | None = None):
        self._callbacks(authorize, validate_resources, validate_engineering)
        authorize()
        _json(body)
        _require(type(body) is dict and {'displayName', 'clientRequestId'} <= set(body) <= {'displayName', 'clientRequestId', 'description'})
        actor, name, request_id = _text(actor), _text(body['displayName']), _uuid(body['clientRequestId'])
        digest = hashlib.sha256(_json({'displayName': name, **({'description': _description(body['description'])} if 'description' in body else {})}).encode()).hexdigest()
        with self.library.connect() as db:
            db.execute('begin immediate')
            prior = self._prior(db, actor, 'create', request_id, digest)
            if prior is not None:
                authorize()
                return prior
            snapshot = self._empty(name)
            if 'description' in body:
                snapshot['description'] = body['description']
            validate_resources(json.loads(_json(snapshot)))
            validate_engineering(json.loads(_json(snapshot)), [], [])
            identifier, revision = str(uuid4()), 'scene:' + str(uuid4())
            now = datetime.now(timezone.utc).isoformat()
            scope = getattr(self.library, 'workspace_scope', None)
            if scope:
                db.execute('insert into scenes(id,project_code,display_name,head_revision,updated_at,instance_count,workspace_id) values (?,?,?,?,?,?,?)',
                           (identifier, self.project_code, name, revision, now, 0, scope[0]))
            else:
                db.execute('insert into scenes(id,project_code,display_name,head_revision,updated_at,instance_count) values (?,?,?,?,?,?)',
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

    @staticmethod
    def _terrain_refs(value):
        _require(type(value) is list and len(value) <= 1, 'RESOURCE_CHANGED', 409)
        refs = []
        for item in value:
            _fields(item, ('terrainVersionId', 'contentRevision', 'sha256', 'reportSha256'))
            refs.append({'terrainVersionId': _uuid(item['terrainVersionId']),
                         'contentRevision': _text(item['contentRevision']),
                         'sha256': _sha(item['sha256']), 'reportSha256': _sha(item['reportSha256'])})
        return refs

    def _manifest(self, snapshot, validate_resources, *, db=None):
        checked = validate_resources(json.loads(_json(snapshot)))
        geographic = snapshot['coordinateFrame']['mode'] == 'projected_site'
        if geographic:
            _require(type(checked) is dict and set(checked) == {'terrains'}, 'RESOURCE_VALIDATION_REQUIRED', 409)
            terrains = self._terrain_refs(checked['terrains'])
            _require(len(terrains) == 1 and terrains[0]['terrainVersionId'] == snapshot['terrain']['terrainVersionId']
                     and terrains[0]['contentRevision'] == snapshot['terrain']['expectedContentRevision'], 'RESOURCE_CHANGED', 409)
        else:
            _require(checked is None or type(checked) is dict and checked.get('terrains') == [], 'SCENE_SCOPE_UNSUPPORTED')
            terrains = []
        if db is not None:
            models = self._resource_refs(db, snapshot)
        else:
            with self.library.connect() as connection:
                models = self._resource_refs(connection, snapshot)
        return {'models': models, 'terrains': terrains}

    @staticmethod
    def _validate_changes(db, scene_id, previous, snapshot, *, anchor_draft=False, anchored=False, reject_model_changes=False):
        old_items = {item['sceneModelInstanceId']: item for item in previous['instances']}
        new_items = {item['sceneModelInstanceId']: item for item in snapshot['instances']}
        for identifier, old in old_items.items():
            current = new_items.get(identifier)
            if old['positionLocked']:
                _require(current is not None, 'INSTANCE_POSITION_LOCKED', 409)
                if anchor_draft:
                    _require(current['placement'] == old['placement'] and current['modelVersionId'] == old['modelVersionId'],
                             'INSTANCE_POSITION_LOCKED', 409)
                elif not anchored and current['positionLocked']:
                    _require(current['placement'] == old['placement'] and current['modelVersionId'] == old['modelVersionId'],
                             'INSTANCE_POSITION_LOCKED', 409)
            if reject_model_changes and current is not None:
                _require(current['modelVersionId'] == old['modelVersionId'], 'SCENE_SCOPE_UNSUPPORTED')
        for identifier in new_items.keys() - old_items.keys():
            reused = db.execute('select 1 from scene_instance_ids where scene_id=? and instance_id=?',
                                (scene_id, identifier)).fetchone()
            _require(reused is None, 'INSTANCE_ID_REUSED', 409)

    @staticmethod
    def _geometry(result, snapshot, manifest, *, engineering=False):
        _require(type(result) is dict and type(result.get('snapshot')) is dict
                 and type(result.get('resourceRefs')) is dict, 'INVALID_GEOMETRY_RESULT')
        normalized = validate_snapshot(result['snapshot'], geographic=True, engineering=engineering)
        _require(normalized['coordinateFrame'] == snapshot['coordinateFrame']
                 and normalized['terrain'] == snapshot['terrain'], 'INVALID_GEOMETRY_RESULT')
        intended = json.loads(_json(normalized))
        for item, original in zip(intended['instances'], snapshot['instances']):
            if item['placement']['height']['mode'] == original['placement']['height']['mode'] == 'terrain_ground':
                for key in ('sampleLongitude', 'sampleLatitude', 'sampledHeightM'):
                    item['placement']['height'][key] = original['placement']['height'][key]
        _require(intended == snapshot, 'INVALID_GEOMETRY_RESULT')
        resources = result['resourceRefs']
        _require(resources.get('models') == sorted({item['modelVersionId'] for item in normalized['instances']})
                 and SceneLibrary._terrain_refs(resources.get('terrains')) == manifest['terrains'], 'RESOURCE_CHANGED', 409)
        provenance = result.get('heightProvenance')
        _require(type(provenance) is list and len(provenance) <= MAX_INSTANCES, 'INVALID_GEOMETRY_RESULT')
        _require(all(type(item) is dict for item in provenance), 'INVALID_GEOMETRY_RESULT')
        actual_ids = [item.get('sceneModelInstanceId') for item in provenance]
        _require(len(actual_ids) == len(set(actual_ids)) and set(actual_ids) == {item['sceneModelInstanceId'] for item in normalized['instances']},
                 'INVALID_GEOMETRY_RESULT')
        validation = {'scope': 'projected_site_unbound', 'bindingIssues': []}
        for key in ('geometrySummary', 'displayPlacements', 'terrainDisplayTransform', 'anchorTransform', 'impact'):
            if key in result:
                validation[key] = result[key]
        _json(validation); _json(provenance)
        return normalized, {'validation': validation, 'heightProvenance': json.loads(_json(provenance)),
                            'terrainRefs': manifest['terrains']}

    @staticmethod
    def _local_spatial():
        return {'validation': {'scope': 'local_plane_unbound', 'bindingIssues': []},
                'heightProvenance': [], 'terrainRefs': []}

    @staticmethod
    def _stored_validation(db, revision):
        row = db.execute('select validation from scene_spatial_validations where revision=?', (revision,)).fetchone()
        return json.loads(row['validation']) if row is not None else SceneLibrary._local_spatial()['validation']

    @staticmethod
    def _engineering(checker, snapshot, reviewed, changes, previous, previous_revision, previous_validation, mode):
        """Accept only explicit server facts, never fields from the editable snapshot."""
        _require(callable(checker))
        facts = checker(json.loads(_json(snapshot)), json.loads(_json(reviewed)), json.loads(_json(changes)),
                        previous_snapshot=json.loads(_json(previous)), previous_revision=previous_revision,
                        previous_validation=json.loads(_json(previous_validation)), mode=mode)
        _fields(facts, ('engineeringExpectations', 'bindingIssues', 'rootBindingChanges', 'rootBindingImpact'))
        _require(all(type(value) is list for value in facts.values()), 'INVALID_ENGINEERING_RESULT')
        current_ids = {item['sceneModelInstanceId'] for item in snapshot['instances']}
        old_ids = {item['sceneModelInstanceId'] for item in previous['instances']}
        allowed_refs = set()
        for source in (snapshot, previous):
            for item in source['instances']:
                if item['rootBinding'] is not None: allowed_refs.add(_json(item['rootBinding']['objectRef']))
                allowed_refs.update(_json(binding['objectRef']) for binding in item['componentBindings'])
        for issue in previous_validation.get('bindingIssues', []):
            allowed_refs.add(_json(issue['objectRef']))
        seen = set()
        for expectation in facts['engineeringExpectations']:
            _fields(expectation, ('ref', 'expectedEntityRevision', 'installationContextId', 'expectedHierarchyRevision'))
            validate_binding_shapes({'objectRef': expectation['ref']}, [])
            identity = _json(expectation['ref'])
            _require(identity not in seen and identity in allowed_refs, 'INVALID_ENGINEERING_RESULT'); seen.add(identity)
            for key in ('expectedEntityRevision', 'installationContextId', 'expectedHierarchyRevision'):
                _text(expectation[key], 512)
        for issue in facts['bindingIssues']:
            _require(type(issue) is dict and issue.get('sceneModelInstanceId') in current_ids,
                     'INVALID_ENGINEERING_RESULT')
            common = {'sceneModelInstanceId', 'objectRef', 'installationContextId', 'blocking', 'kind', 'code'}
            if issue.get('kind') == 'model_version_changed':
                _fields(issue, common | {'previousModelVersionId', 'previousComponentKeys', 'sourceSceneRevision'})
                _uuid(issue['previousModelVersionId']); _text(issue['sourceSceneRevision'])
                _require(issue['code'] in ('COMPONENT_MISSING', 'MIGRATION_REQUIRED', 'SOURCE_ID_AMBIGUOUS'), 'INVALID_ENGINEERING_RESULT')
                validate_binding_shapes({'objectRef': issue['objectRef']},
                                        [{'objectRef': issue['objectRef'], 'componentKeys': issue['previousComponentKeys']}])
            else:
                _fields(issue, common | {'expectedEntityRevision', 'expectedHierarchyRevision'})
                _require(issue['kind'] == 'engineering_changed'
                         and issue['code'] in ('IDENTITY_CHANGED', 'ENTITY_CHANGED', 'PARENT_CHAIN_CHANGED'), 'INVALID_ENGINEERING_RESULT')
                _text(issue['expectedEntityRevision'], 512); _text(issue['expectedHierarchyRevision'], 512)
            validate_binding_shapes({'objectRef': issue.get('objectRef')}, [])
            _text(issue['installationContextId'], 512)
            _require(issue.get('blocking') is True and _json(issue['objectRef']) in allowed_refs, 'INVALID_ENGINEERING_RESULT')
        for key in ('rootBindingChanges', 'rootBindingImpact'):
            change_ids = set()
            for change in facts[key]:
                _require(type(change) is dict and change.get('sceneModelInstanceId') in current_ids | old_ids,
                         'INVALID_ENGINEERING_RESULT')
                fields = {'sceneModelInstanceId', 'from', 'to', 'clearOldComponentBindings', 'reviewedRemovedBindingsDigest'}
                _fields(change, fields | ({'removedBindings'} if key == 'rootBindingImpact' else set()))
                _require(change['sceneModelInstanceId'] not in change_ids, 'INVALID_ENGINEERING_RESULT')
                change_ids.add(change['sceneModelInstanceId'])
                for ref in (change['from'], change['to']):
                    if ref is not None: validate_binding_shapes({'objectRef': ref}, [])
                _require(change['clearOldComponentBindings'] is True, 'INVALID_ENGINEERING_RESULT')
                _sha(change['reviewedRemovedBindingsDigest'])
                if key == 'rootBindingImpact':
                    validate_binding_shapes({'objectRef': change['from']} if change['from'] is not None else None,
                                            change['removedBindings'])
        _json(facts)
        return json.loads(_json(facts))

    @staticmethod
    def _merge_engineering(spatial, snapshot, facts):
        spatial['validation'].update(facts)
        bound = bool(facts['bindingIssues']) or any(item['rootBinding'] is not None or item['componentBindings']
                                                   for item in snapshot['instances'])
        spatial['validation']['scope'] = snapshot['coordinateFrame']['mode'] + ('_bound' if bound else '_unbound')

    @staticmethod
    def _engineering_preview(result, facts):
        if facts is not None:
            result.update(reviewedEngineering=facts['engineeringExpectations'],
                          rootBindingChanges=facts['rootBindingChanges'], rootBindingImpact=facts['rootBindingImpact'])
        return result

    @staticmethod
    def _height_provenance(db, revision):
        row = db.execute('select height_provenance from scene_spatial_validations where revision=?', (revision,)).fetchone()
        return json.loads(row['height_provenance']) if row is not None else []

    @staticmethod
    def _retain_height_basis(previous, proposed, spatial, previous_provenance, previous_revision):
        old_items = {item['sceneModelInstanceId']: item for item in previous['instances']}
        new_items = {item['sceneModelInstanceId']: item for item in proposed['instances']}
        notes = {note['sceneModelInstanceId']: note for note in previous_provenance}
        retained = []
        for note in spatial['heightProvenance']:
            identifier = note['sceneModelInstanceId']
            old, new, basis = old_items.get(identifier), new_items.get(identifier), notes.get(identifier)
            if old is not None and new is not None and basis is not None and _receipt_snapshot_digest(old['placement']['height']) == _receipt_snapshot_digest(new['placement']['height']):
                # The original sample position belongs to this height's basis,
                # even when an absolute-height instance has since moved.
                carried = json.loads(_json(basis))
                carried['kind'] = 'retained_height_basis'
                carried['basisKind'] = basis.get('basisKind', basis['kind'])
                carried['basisSceneRevision'] = basis.get('basisSceneRevision', previous_revision)
                retained.append(carried)
            else:
                retained.append(note)
        _json(retained)
        spatial['heightProvenance'] = retained

    @staticmethod
    def _height_basis(height, note, revision, terrain_ref):
        basis = note.get('heightBasis')
        if basis is None:
            source_height, source_ref = height, terrain_ref if height['mode'] == 'terrain_ground' else None
            # Read the earlier, already-saved estimate form without retaining its
            # complete provenance tree in each later revision.
            if height['mode'] == 'absolute' and type(note.get('previousHeight')) is dict and note['previousHeight'].get('mode') == 'terrain_ground':
                source_height, source_ref = note['previousHeight'], note.get('previousTerrainRef')
            basis = {'kind': note.get('basisKind', note['kind']),
                     'reviewedSceneRevision': note.get('basisSceneRevision', revision),
                     'height': source_height, 'terrainRef': source_ref}
        _fields(basis, ('kind', 'reviewedSceneRevision', 'height', 'terrainRef'))
        _text(basis['kind']); _text(basis['reviewedSceneRevision'])
        source_height = basis['height']
        _require(type(source_height) is dict, 'INVALID_GEOMETRY_RESULT')
        if source_height.get('mode') == 'terrain_ground':
            _fields(source_height, ('mode', 'terrainVersionId', 'terrainSha256', 'sampleLongitude', 'sampleLatitude',
                                    'sampledHeightM', 'offsetM', 'verticalDatum', 'samplingRule'))
            refs = SceneLibrary._terrain_refs([basis['terrainRef']])
            _require(refs[0]['terrainVersionId'] == source_height['terrainVersionId']
                     and refs[0]['sha256'] == source_height['terrainSha256'], 'INVALID_GEOMETRY_RESULT')
        else:
            _fields(source_height, ('mode', 'valueM', 'verticalDatum', 'sourceNote'))
            _require(source_height['mode'] == 'absolute' and basis['terrainRef'] is None, 'INVALID_GEOMETRY_RESULT')
        return json.loads(_json(basis))

    @staticmethod
    def _replacement_height_basis(previous, proposed, spatial, previous_provenance, previous_revision, old_manifest, new_manifest, operation):
        old_items = {item['sceneModelInstanceId']: item for item in previous['instances']}
        new_items = {item['sceneModelInstanceId']: item for item in proposed['instances']}
        notes = {note['sceneModelInstanceId']: note for note in previous_provenance}
        for note in spatial['heightProvenance']:
            identifier = note['sceneModelInstanceId']
            old_height = old_items[identifier]['placement']['height']
            basis = notes.get(identifier)
            _require(basis is not None and _receipt_snapshot_digest(note.get('previousHeight')) == _receipt_snapshot_digest(old_height),
                     'INVALID_GEOMETRY_RESULT')
            old_basis = SceneLibrary._height_basis(old_height, basis, previous_revision, old_manifest['terrains'][0])
            note['previousHeightProvenance'] = {'kind': 'height_basis_summary', 'previousSceneRevision': previous_revision, 'basis': old_basis}
            new_height = new_items[identifier]['placement']['height']
            if operation['strategy'] == 'resample_ground' and old_height['mode'] == 'terrain_ground':
                note['heightBasis'] = SceneLibrary._height_basis(new_height, {'kind': note['kind']}, previous_revision, new_manifest['terrains'][0])
            else:
                note['heightBasis'] = old_basis
            if _receipt_snapshot_digest(old_height) == _receipt_snapshot_digest(new_height):
                note['kind'] = 'retained_height_basis'
                note['basisKind'] = basis.get('basisKind', basis['kind'])
                note['basisSceneRevision'] = basis.get('basisSceneRevision', previous_revision)
        _json(spatial['heightProvenance'])

    @staticmethod
    def _check_model_history(previous_refs, current_refs):
        prior = {item['modelVersionId']: item for item in previous_refs}
        _require(all(item['modelVersionId'] not in prior or prior[item['modelVersionId']] == item for item in current_refs),
                 'RESOURCE_CHANGED', 409)

    @staticmethod
    def _receipt_key(db):
        _, key = SceneLibrary._catalog(db)
        return hmac.digest(key, b'ontovis.scene-anchor-precheck.v1', 'sha256')

    def _receipt_context(self, actor, access_revision, scene_id, base_revision, previous, proposed, manifest):
        return {'kind': 'scene-anchor-precheck-v1', 'project': self.project_code, 'actor': actor,
                'accessRevision': _text(access_revision), 'sceneId': scene_id, 'baseRevision': base_revision,
                'oldSnapshotSha256': _digest(previous), 'proposedSnapshotSha256': _receipt_snapshot_digest(proposed),
                'resourceDigest': _digest(manifest)}

    def _verify_receipt(self, db, receipt, expected):
        try:
            actual = self._uncursor(receipt, self._receipt_key(db))
            _require(actual == expected, 'SPATIAL_PRECHECK_INVALID', 409)
        except PreviewError:
            raise PreviewError(409, 'SPATIAL_PRECHECK_INVALID') from None

    @staticmethod
    def _replacement_operation(value):
        _require(type(value) is dict and value.get('kind') in ('model', 'terrain'))
        if value['kind'] == 'model':
            _fields(value, ('kind', 'sceneModelInstanceId', 'candidateModelVersionId'))
            _uuid(value['sceneModelInstanceId']); _uuid(value['candidateModelVersionId'])
        else:
            _fields(value, ('kind', 'candidateTerrainVersionId', 'strategy'))
            _uuid(value['candidateTerrainVersionId'])
            _require(value['strategy'] in ('keep_height', 'resample_ground'))
        return json.loads(_json(value))

    @staticmethod
    def _replacement_key(db):
        _, key = SceneLibrary._catalog(db)
        return hmac.digest(key, b'ontovis.scene-resource-replacement.v1', 'sha256')

    def _replacement_receipt(self, db, receipt):
        try:
            value = self._uncursor(receipt, self._replacement_key(db))
            _require(type(value) is dict)
            self._replacement_operation(value.get('operation'))
            return value
        except PreviewError:
            raise PreviewError(409, 'SPATIAL_PRECHECK_INVALID') from None

    def _replacement_context(self, actor, access_revision, scene_id, base_revision,
                             previous, proposed, operation, old_manifest, new_manifest):
        return {'kind': 'scene-resource-replacement-v1', 'project': self.project_code, 'actor': actor,
                'accessRevision': _text(access_revision), 'sceneId': scene_id, 'baseRevision': base_revision,
                'operation': operation, 'oldSnapshotSha256': _digest(previous),
                'proposedSnapshotSha256': _receipt_snapshot_digest(proposed),
                'oldResourceDigest': _digest(old_manifest), 'newResourceDigest': _digest(new_manifest)}

    def _verify_replacement(self, db, receipt, expected):
        _require(self._replacement_receipt(db, receipt) == expected, 'SPATIAL_PRECHECK_INVALID', 409)

    @staticmethod
    def _model_summary(value, identifier, reference, *, frame_mode='projected_site'):
        _require(type(value) is dict and value.get('modelVersionId') == identifier
                 and value.get('modelAssetId') == reference.get('modelAssetId')
                 and value.get('contentRevision') == reference['contentRevision']
                 and value.get('sha256') == reference['sha256'], 'RESOURCE_CHANGED', 409)
        _uuid(value.get('modelAssetId'))
        calibration, report = value.get('calibration'), value.get('report')
        _require(value.get('state') == 'ready' and value.get('canPlace') is True
                 and value.get('calibrationState') in ('verified', 'legacy_display') and type(calibration) is dict
                 and calibration.get('state') == value['calibrationState'], 'MODEL_CALIBRATION_REQUIRED', 409)
        legacy_display = calibration['state'] == 'legacy_display'
        if legacy_display:
            _require(frame_mode == 'local_plane', 'MODEL_GEOGRAPHIC_CALIBRATION_REQUIRED', 409)
            _require(calibration.get('modelToCalibrated') == [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]
                     and calibration.get('sourceSha256') == value['sha256'], 'RESOURCE_CHANGED', 409)
        _require(type(report) is dict and type(report.get('bounds')) is dict
                 and type(value.get('components')) is list, 'RESOURCE_CHANGED', 409)
        low, high = _vector(report['bounds'].get('min')), _vector(report['bounds'].get('max'))
        _require(all(a <= b for a, b in zip(low, high)), 'RESOURCE_CHANGED', 409)
        return {'modelAssetId': value['modelAssetId'], 'modelVersionId': identifier,
                'contentRevision': reference['contentRevision'], 'sha256': reference['sha256'],
                'bounds': [low, high], 'dimensionsM': [b-a for a, b in zip(low, high)],
                'basePoint': None if legacy_display else _vector(calibration.get('basePoint')),
                'forward': None if legacy_display else _vector(calibration.get('forward')),
                'componentCount': len(value['components'])}

    @staticmethod
    def _terrain_replacement_shape(previous, proposed, operation, old_manifest, new_manifest):
        _require(proposed['coordinateFrame']['mode'] == previous['coordinateFrame']['mode'] == 'projected_site',
                 'INVALID_GEOMETRY_RESULT')
        _require(all(previous[key] == proposed[key] for key in ('displayName', 'defaults', 'initialView')),
                 'INVALID_GEOMETRY_RESULT')
        preserve_environment(previous, proposed)
        _require(previous.get('description') == proposed.get('description'), 'INVALID_GEOMETRY_RESULT')
        _require(previous.get('organization') == proposed.get('organization'), 'INVALID_GEOMETRY_RESULT')
        old_frame, new_frame = previous['coordinateFrame'], proposed['coordinateFrame']
        _require({key: value for key, value in old_frame.items() if key not in ('frameRevision', 'anchor')}
                 == {key: value for key, value in new_frame.items() if key not in ('frameRevision', 'anchor')},
                 'INVALID_GEOMETRY_RESULT')
        _require(proposed['terrain']['terrainVersionId'] == operation['candidateTerrainVersionId']
                 and len(previous['instances']) == len(proposed['instances']), 'INVALID_GEOMETRY_RESULT')
        for old, new in zip(previous['instances'], proposed['instances']):
            _require(all(old[key] == new[key] for key in old if key != 'placement'), 'INVALID_GEOMETRY_RESULT')
            before, after = old['placement'], new['placement']
            _require(before['headingDeg'] == after['headingDeg']
                     and {key: value for key, value in before['position'].items() if key != 'frameRevision'}
                     == {key: value for key, value in after['position'].items() if key != 'frameRevision'},
                     'INVALID_GEOMETRY_RESULT')
            old_height, new_height = before['height'], after['height']
            if old_height['mode'] == 'absolute':
                _require(old_height == new_height, 'INVALID_GEOMETRY_RESULT')
                continue
            old_h = old_height['sampledHeightM'] + old_height['offsetM']
            new_h = new_height['valueM'] if new_height['mode'] == 'absolute' else new_height['sampledHeightM'] + new_height['offsetM']
            if operation['strategy'] == 'resample_ground':
                _require(new_height['mode'] == 'terrain_ground' and new_height['offsetM'] == old_height['offsetM'],
                         'INVALID_GEOMETRY_RESULT')
            else:
                expected_mode = 'terrain_ground' if old_frame['verticalDatum'] == 'UNKNOWN_RELATIVE' else 'absolute'
                _require(new_height['mode'] == expected_mode and abs(old_h-new_h) <= 1e-6, 'INVALID_GEOMETRY_RESULT')
            if new_height['mode'] == 'terrain_ground':
                _require(new_height['terrainVersionId'] == new_manifest['terrains'][0]['terrainVersionId']
                         and new_height['terrainSha256'] == new_manifest['terrains'][0]['sha256'], 'RESOURCE_CHANGED', 409)
            _require(not old['positionLocked'] or abs(old_h-new_h) <= 1e-6, 'INSTANCE_POSITION_LOCKED', 409)

    def _replacement_result(self, previous, operation, old_manifest, validate_resources,
                            geometry_check, terrain_replacement, model_details, *, engineering=False):
        if operation['kind'] == 'model':
            _require(callable(model_details), 'SCENE_SCOPE_UNSUPPORTED')
            proposed = json.loads(_json(previous))
            items = [item for item in proposed['instances'] if item['sceneModelInstanceId'] == operation['sceneModelInstanceId']]
            _require(len(items) == 1, 'NOT_FOUND_OR_FORBIDDEN', 404)
            item = items[0]
            _require(not item['positionLocked'], 'INSTANCE_POSITION_LOCKED', 409)
            old_id, new_id = item['modelVersionId'], operation['candidateModelVersionId']
            _require(old_id != new_id)
            item['modelVersionId'] = new_id
            if engineering:
                item['componentBindings'] = []
            new_manifest = self._manifest(proposed, validate_resources)
            old_ref = next(ref for ref in old_manifest['models'] if ref['modelVersionId'] == old_id)
            new_ref = next(ref for ref in new_manifest['models'] if ref['modelVersionId'] == new_id)
            old_model = self._model_summary(model_details(old_id), old_id, old_ref, frame_mode=proposed['coordinateFrame']['mode'])
            new_model = self._model_summary(model_details(new_id), new_id, new_ref, frame_mode=proposed['coordinateFrame']['mode'])
            if proposed['coordinateFrame']['mode'] == 'projected_site':
                _require(callable(geometry_check), 'SCENE_SCOPE_UNSUPPORTED')
                result = geometry_check(json.loads(_json(proposed)), expected_frame=json.loads(_json(previous['coordinateFrame'])))
                normalized, spatial = self._geometry(result, proposed, new_manifest, engineering=engineering)
                _require(_receipt_snapshot_digest(normalized) == _receipt_snapshot_digest(proposed), 'INVALID_GEOMETRY_RESULT')
            else:
                spatial = self._local_spatial()
            spatial['validation']['impact'] = {'kind': 'model_replacement',
                'sceneModelInstanceId': item['sceneModelInstanceId'], 'instanceIds': [item['sceneModelInstanceId']],
                'oldModelVersionId': old_id, 'newModelVersionId': new_id, 'oldModel': old_model, 'newModel': new_model,
                'explicitConfirmationRequired': True}
        else:
            _require(callable(terrain_replacement) and previous['coordinateFrame']['mode'] == 'projected_site',
                     'SCENE_SCOPE_UNSUPPORTED')
            _require(previous['terrain']['terrainVersionId'] != operation['candidateTerrainVersionId'])
            result = terrain_replacement(json.loads(_json(previous)), operation['candidateTerrainVersionId'], operation['strategy'])
            _require(type(result) is dict and type(result.get('snapshot')) is dict, 'INVALID_GEOMETRY_RESULT')
            proposed = validate_snapshot(result['snapshot'], geographic=True, engineering=engineering)
            new_manifest = self._manifest(proposed, validate_resources)
            self._terrain_replacement_shape(previous, proposed, operation, old_manifest, new_manifest)
            proposed, spatial = self._geometry(result, proposed, new_manifest, engineering=engineering)
            impact = spatial['validation'].get('impact')
            _require(type(impact) is dict and impact.get('kind') == 'terrain_replacement'
                     and impact.get('strategy') == operation['strategy']
                     and impact.get('oldTerrainRef') == old_manifest['terrains'][0]
                     and impact.get('newTerrainRef') == new_manifest['terrains'][0], 'INVALID_GEOMETRY_RESULT')
        _json(spatial)
        return proposed, spatial, new_manifest

    def replacement_check(self, body, actor, authorize: Authorize, validate_resources: ValidateResources,
                          validate_engineering: ValidateEngineering, geometry_check=None, terrain_replacement=None,
                          model_details=None, *, access_revision, engineering_check: EngineeringCheck | None = None):
        self._callbacks(authorize, validate_resources, validate_engineering)
        authorize(); _json(body)
        _require(type(body) is dict and body.get('kind') in ('model', 'terrain'))
        common = {'sceneId', 'expectedSceneRevision', 'snapshot'}
        optional_environment = ({'environmentWriteVersion'} if 'environmentWriteVersion' in body else set()) | ({'sceneInfoWriteVersion'} if 'sceneInfoWriteVersion' in body else set())
        operation = self._replacement_operation({key: value for key, value in body.items() if key not in common | optional_environment})
        _fields(body, common | set(operation) | optional_environment)
        actor, access_revision = _text(actor), _text(access_revision)
        scene_id, base_revision = _uuid(body['sceneId']), _text(body['expectedSceneRevision'])
        validate_snapshot(body['snapshot'], geographic=callable(geometry_check) or callable(terrain_replacement), engineering=callable(engineering_check))
        with self.library.connect() as db:
            db.execute('begin')
            _require(self._scope(db, scene_id)['head_revision'] == base_revision, 'SCENE_CHANGED', 409)
            row = self._revision(db, scene_id, base_revision)
            previous, previous_refs = validate_snapshot(json.loads(row['snapshot']), geographic=True, engineering=callable(engineering_check)), json.loads(row['resource_refs'])
            environment_write(body, previous)
            _information_write(body, previous)
            previous_provenance = self._height_provenance(db, base_revision)
            previous_validation = self._stored_validation(db, base_revision)
        _require(_receipt_snapshot_digest(body['snapshot']) == _receipt_snapshot_digest(previous), 'SCENE_DRAFT_REQUIRES_SAVE', 409)
        old_manifest = self._manifest(previous, validate_resources)
        self._check_model_history(previous_refs, old_manifest['models'])
        if not callable(engineering_check):
            validate_engineering(json.loads(_json(previous)), [], [])
        proposed, spatial, new_manifest = self._replacement_result(previous, operation, old_manifest, validate_resources,
                                                                  geometry_check, terrain_replacement, model_details, engineering=callable(engineering_check))
        if operation['kind'] == 'model':
            self._retain_height_basis(previous, proposed, spatial, previous_provenance, base_revision)
        else:
            self._replacement_height_basis(previous, proposed, spatial, previous_provenance, base_revision, old_manifest, new_manifest, operation)
        facts = None
        if callable(engineering_check):
            facts = self._engineering(engineering_check, proposed, [], [], previous, base_revision, previous_validation, 'replacement')
            self._merge_engineering(spatial, proposed, facts)
        else:
            validate_engineering(json.loads(_json(proposed)), [], [])
        with self.library.connect() as db:
            db.execute('begin')
            _require(self._scope(db, scene_id)['head_revision'] == base_revision, 'SCENE_CHANGED', 409)
            _require(self._manifest(previous, validate_resources, db=db) == old_manifest
                     and self._manifest(proposed, validate_resources, db=db) == new_manifest, 'RESOURCE_CHANGED', 409)
            if facts is not None:
                _require(self._engineering(engineering_check, proposed, [], [], previous, base_revision,
                                          previous_validation, 'replacement') == facts, 'ENGINEERING_CHANGED', 409)
            authorize()
            receipt = self._cursor(self._replacement_context(actor, access_revision, scene_id, base_revision,
                previous, proposed, operation, old_manifest, new_manifest), self._replacement_key(db))
        return self._engineering_preview({'sceneId': scene_id, 'baseSceneRevision': base_revision, 'proposedSnapshot': proposed,
                'validation': spatial['validation'], 'heightProvenance': spatial['heightProvenance'],
                'resourceRefs': new_manifest, 'spatialChange': {'kind': operation['kind'], 'receipt': receipt}}, facts)

    @staticmethod
    def _anchor_result(local, proposed):
        _require(proposed['coordinateFrame']['mode'] == 'projected_site', 'INVALID_GEOMETRY_RESULT')
        _require(all(local[key] == proposed[key] for key in ('displayName', 'defaults')), 'INVALID_GEOMETRY_RESULT')
        preserve_environment(local, proposed)
        _require(local.get('description') == proposed.get('description'), 'INVALID_GEOMETRY_RESULT')
        _require(local.get('organization') == proposed.get('organization'), 'INVALID_GEOMETRY_RESULT')
        _require(len(local['instances']) == len(proposed['instances']), 'INVALID_GEOMETRY_RESULT')
        for before, after in zip(local['instances'], proposed['instances']):
            _require(all(before[key] == after[key] for key in before if key != 'placement'), 'INVALID_GEOMETRY_RESULT')

    def check(self, body, actor, authorize: Authorize, validate_resources: ValidateResources,
              validate_engineering: ValidateEngineering, geometry_check=None, anchor_preview=None, *, access_revision, engineering_check: EngineeringCheck | None = None):
        """Read-only preflight; a signed anchor receipt stores no draft and holds no lock."""
        self._callbacks(authorize, validate_resources, validate_engineering)
        authorize(); _json(body)
        base = {'kind', 'sceneId', 'expectedSceneRevision', 'snapshot'}
        _require(type(body) is dict and body.get('kind') in ('validate', 'anchor'))
        _fields(body, base | ({'candidateTerrainVersionId', 'anchor'} if body['kind'] == 'anchor' else set()) | (({'environmentWriteVersion'} if 'environmentWriteVersion' in body else set()) | ({'sceneInfoWriteVersion'} if 'sceneInfoWriteVersion' in body else set())))
        actor, access_revision = _text(actor), _text(access_revision)
        scene_id, base_revision = _uuid(body['sceneId']), _text(body['expectedSceneRevision'])
        is_anchor = body['kind'] == 'anchor'
        snapshot = validate_snapshot(body['snapshot'], geographic=callable(geometry_check), engineering=callable(engineering_check))
        with self.library.connect() as db:
            db.execute('begin')
            scene = self._scope(db, scene_id)
            _require(scene['head_revision'] == base_revision, 'SCENE_CHANGED', 409)
            row = self._revision(db, scene_id, base_revision)
            previous = validate_snapshot(json.loads(row['snapshot']), geographic=True, engineering=callable(engineering_check))
            environment_write(body, previous)
            _information_write(body, previous)
            previous_refs = json.loads(row['resource_refs'])
            previous_provenance = self._height_provenance(db, base_revision)
            previous_validation = self._stored_validation(db, base_revision)
            if is_anchor:
                _require(callable(anchor_preview) and callable(geometry_check)
                         and previous['coordinateFrame']['mode'] == snapshot['coordinateFrame']['mode'] == 'local_plane',
                         'SCENE_SCOPE_UNSUPPORTED')
            else:
                _require(previous['coordinateFrame'] == snapshot['coordinateFrame'] and previous['terrain'] == snapshot['terrain'],
                         'SCENE_SCOPE_UNSUPPORTED')
            self._validate_changes(db, scene_id, previous, snapshot, anchor_draft=is_anchor,
                                   reject_model_changes=True)
        local_manifest = self._manifest(snapshot, validate_resources)
        self._check_model_history(previous_refs, local_manifest['models'])
        if not callable(engineering_check):
            validate_engineering(json.loads(_json(snapshot)), [], [])
        if is_anchor:
            _uuid(body['candidateTerrainVersionId']); _require(type(body['anchor']) is dict)
            result = anchor_preview(json.loads(_json(snapshot)), body['candidateTerrainVersionId'], json.loads(_json(body['anchor'])))
            _require(type(result) is dict and type(result.get('snapshot')) is dict, 'INVALID_GEOMETRY_RESULT')
            proposed = validate_snapshot(result['snapshot'], geographic=True, engineering=callable(engineering_check))
            self._anchor_result(snapshot, proposed)
            manifest = self._manifest(proposed, validate_resources)
            _require(manifest['models'] == local_manifest['models'], 'RESOURCE_CHANGED', 409)
            proposed, spatial = self._geometry(result, proposed, manifest, engineering=callable(engineering_check))
        elif snapshot['coordinateFrame']['mode'] == 'projected_site':
            _require(callable(geometry_check), 'SCENE_SCOPE_UNSUPPORTED')
            result = geometry_check(json.loads(_json(snapshot)), expected_frame=json.loads(_json(previous['coordinateFrame'])))
            manifest = local_manifest
            proposed, spatial = self._geometry(result, snapshot, manifest, engineering=callable(engineering_check))
        else:
            proposed, spatial, manifest = snapshot, self._local_spatial(), local_manifest
        if not is_anchor:
            self._retain_height_basis(previous, proposed, spatial, previous_provenance, base_revision)
        facts = None
        if callable(engineering_check):
            facts = self._engineering(engineering_check, proposed, [], [], previous, base_revision, previous_validation, 'check')
            self._merge_engineering(spatial, proposed, facts)
        else:
            validate_engineering(json.loads(_json(proposed)), [], [])
        with self.library.connect() as db:
            db.execute('begin')
            _require(self._scope(db, scene_id)['head_revision'] == base_revision, 'SCENE_CHANGED', 409)
            _require(self._manifest(proposed, validate_resources, db=db) == manifest, 'RESOURCE_CHANGED', 409)
            if facts is not None:
                _require(self._engineering(engineering_check, proposed, [], [], previous, base_revision,
                                          previous_validation, 'check') == facts, 'ENGINEERING_CHANGED', 409)
            authorize()
            receipt = self._cursor(self._receipt_context(actor, access_revision, scene_id, base_revision,
                                                         previous, proposed, manifest), self._receipt_key(db)) if is_anchor else None
        return self._engineering_preview({'sceneId': scene_id, 'baseSceneRevision': base_revision, 'proposedSnapshot': proposed,
                'validation': spatial['validation'], 'heightProvenance': spatial['heightProvenance'],
                'resourceRefs': manifest, 'spatialChange': {'kind': 'anchor', 'receipt': receipt} if is_anchor else None}, facts)

    def save(self, body, actor, authorize: Authorize, validate_resources: ValidateResources,
             validate_engineering: ValidateEngineering, *, validate_geometry=None, access_revision=None,
             terrain_replacement=None, model_details=None, engineering_check: EngineeringCheck | None = None):
        self._callbacks(authorize, validate_resources, validate_engineering)
        authorize(); _json(body)
        required = {'sceneId', 'expectedSceneRevision', 'clientRequestId', 'snapshot',
                    'reviewedEngineering', 'rootBindingChanges'}
        _require(type(body) is dict and required <= set(body) <= required | {'spatialChange','environmentWriteVersion','sceneInfoWriteVersion'})
        actor, request_id, scene_id = _text(actor), _uuid(body['clientRequestId']), _uuid(body['sceneId'])
        base_revision = _text(body['expectedSceneRevision'])
        if not callable(engineering_check):
            _require(body['reviewedEngineering'] == [] and body['rootBindingChanges'] == [], 'SCENE_SCOPE_UNSUPPORTED')
        else:
            _require(type(body['reviewedEngineering']) is list and type(body['rootBindingChanges']) is list)
        change = body.get('spatialChange')
        if change is not None:
            _fields(change, ('kind', 'receipt'))
            _require(change['kind'] in ('anchor', 'model', 'terrain') and isinstance(change['receipt'], str)
                     and 0 < len(change['receipt']) <= 8192, 'SPATIAL_PRECHECK_INVALID', 409)
            _text(access_revision)
        anchored = change is not None and change['kind'] == 'anchor'
        replacing = change is not None and change['kind'] in ('model', 'terrain')
        snapshot = validate_snapshot(body['snapshot'], geographic=callable(validate_geometry)
            or replacing and change['kind'] == 'terrain' and callable(terrain_replacement), engineering=callable(engineering_check))
        business = {**body, 'snapshot': snapshot}
        if change is None:
            business.pop('spatialChange', None)
        digest = _digest(business)
        # Read/replay and collect the old fixed state without holding a write lock.
        with self.library.connect() as db:
            db.execute('begin')
            prior = self._prior(db, actor, 'save', request_id, digest)
            if prior is not None:
                self._scope(db, scene_id); authorize()
                return prior
            scene = self._scope(db, scene_id)
            _require(scene['head_revision'] == base_revision, 'SCENE_CHANGED', 409)
            row = self._revision(db, scene_id, base_revision)
            previous = validate_snapshot(json.loads(row['snapshot']), geographic=True, engineering=callable(engineering_check))
            environment_write(body, previous)
            _information_write(body, previous)
            previous_refs = json.loads(row['resource_refs'])
            previous_provenance = self._height_provenance(db, base_revision)
            previous_validation = self._stored_validation(db, base_revision)
            if replacing:
                signed = self._replacement_receipt(db, change['receipt'])
                operation = signed['operation']
                _require(operation['kind'] == change['kind'], 'SPATIAL_PRECHECK_INVALID', 409)
            elif anchored:
                _require(previous['coordinateFrame']['mode'] == 'local_plane'
                         and snapshot['coordinateFrame']['mode'] == 'projected_site', 'SPATIAL_PRECHECK_INVALID', 409)
            else:
                _require(previous['coordinateFrame'] == snapshot['coordinateFrame'] and previous['terrain'] == snapshot['terrain'],
                         'SCENE_SCOPE_UNSUPPORTED')
            if not replacing:
                self._validate_changes(db, scene_id, previous, snapshot, anchored=anchored, reject_model_changes=True)
        manifest = self._manifest(snapshot, validate_resources)
        self._check_model_history(previous_refs, manifest['models'])
        if not callable(engineering_check):
            validate_engineering(json.loads(_json(snapshot)), [], [])
        if replacing:
            old_manifest = self._manifest(previous, validate_resources)
            self._check_model_history(previous_refs, old_manifest['models'])
            with self.library.connect() as db:
                self._verify_replacement(db, change['receipt'], self._replacement_context(actor, access_revision,
                    scene_id, base_revision, previous, snapshot, operation, old_manifest, manifest))
            normalized, spatial, computed_manifest = self._replacement_result(previous, operation, old_manifest,
                validate_resources, validate_geometry, terrain_replacement, model_details, engineering=callable(engineering_check))
            _require(computed_manifest == manifest, 'RESOURCE_CHANGED', 409)
            _require(_receipt_snapshot_digest(normalized) == _receipt_snapshot_digest(snapshot), 'SPATIAL_PRECHECK_INVALID', 409)
            snapshot = normalized
            if operation['kind'] == 'terrain':
                self._replacement_height_basis(previous, snapshot, spatial, previous_provenance, base_revision, old_manifest, manifest, operation)
        elif anchored:
            with self.library.connect() as db:
                self._verify_receipt(db, change['receipt'], self._receipt_context(
                    actor, access_revision, scene_id, base_revision, previous, snapshot, manifest))
        if not replacing and snapshot['coordinateFrame']['mode'] == 'projected_site':
            _require(callable(validate_geometry), 'SCENE_SCOPE_UNSUPPORTED')
            result = validate_geometry(json.loads(_json(snapshot)), expected_frame=None if anchored else json.loads(_json(previous['coordinateFrame'])))
            normalized, spatial = self._geometry(result, snapshot, manifest, engineering=callable(engineering_check))
            if anchored:
                _require(normalized == snapshot, 'SPATIAL_PRECHECK_INVALID', 409)
            snapshot = normalized
        elif not replacing:
            spatial = self._local_spatial()
        if not anchored and not (replacing and operation['kind'] == 'terrain'):
            self._retain_height_basis(previous, snapshot, spatial, previous_provenance, base_revision)
        facts = None
        if callable(engineering_check):
            facts = self._engineering(engineering_check, snapshot, body['reviewedEngineering'], body['rootBindingChanges'],
                                      previous, base_revision, previous_validation, 'save')
            self._merge_engineering(spatial, snapshot, facts)
        # GIS has finished. Only local compare-and-swap, fixed identities and
        # current authorization/resource callbacks run under the SQLite write lock.
        with self.library.connect() as db:
            db.execute('begin immediate')
            prior = self._prior(db, actor, 'save', request_id, digest)
            if prior is not None:
                self._scope(db, scene_id); authorize()
                return prior
            _require(self._scope(db, scene_id)['head_revision'] == base_revision, 'SCENE_CHANGED', 409)
            current = self._revision(db, scene_id, base_revision)
            _require(_digest(json.loads(current['snapshot'])) == _digest(previous), 'SCENE_CHANGED', 409)
            if replacing:
                self._verify_replacement(db, change['receipt'], self._replacement_context(actor, access_revision,
                    scene_id, base_revision, previous, snapshot, operation, old_manifest, manifest))
                _require(self._manifest(previous, validate_resources, db=db) == old_manifest, 'RESOURCE_CHANGED', 409)
            else:
                self._validate_changes(db, scene_id, previous, snapshot, anchored=anchored, reject_model_changes=True)
            if anchored:
                self._verify_receipt(db, change['receipt'], self._receipt_context(
                    actor, access_revision, scene_id, base_revision, previous, snapshot, manifest))
            _require(self._resource_refs(db, snapshot) == manifest['models'], 'RESOURCE_CHANGED', 409)
            revision, now = 'scene:' + str(uuid4()), datetime.now(timezone.utc).isoformat()
            self._insert_snapshot(db, scene_id, revision, snapshot, now, refs=manifest['models'], spatial=spatial)
            db.execute('update scenes set display_name=?,head_revision=?,updated_at=?,instance_count=? where id=?',
                       (snapshot['displayName'], revision, now, len(snapshot['instances']), scene_id))
            result = {'sceneId': scene_id, 'sceneRevision': revision, 'headRevision': revision,
                      'savedAt': now, 'validation': spatial['validation']}
            if snapshot['coordinateFrame']['mode'] == 'projected_site':
                result['heightProvenance'] = spatial['heightProvenance']
                result['terrainRefs'] = spatial['terrainRefs']
            self._finish(db, actor, 'save', request_id, digest, result)
            _require(self._manifest(snapshot, validate_resources, db=db) == manifest, 'RESOURCE_CHANGED', 409)
            if replacing:
                _require(self._manifest(previous, validate_resources, db=db) == old_manifest, 'RESOURCE_CHANGED', 409)
            if facts is not None:
                _require(self._engineering(engineering_check, snapshot, body['reviewedEngineering'], body['rootBindingChanges'],
                                          previous, base_revision, previous_validation, 'save') == facts,
                         'ENGINEERING_CHANGED', 409)
            else:
                validate_engineering(json.loads(_json(snapshot)), [], [])
            authorize()
        return result

    def open(self, scene_id, actor, authorize: Authorize, scene_revision=None, *, engineering_check: EngineeringCheck | None = None):
        _text(actor); _require(callable(authorize)); authorize()
        with self.library.connect() as db:
            db.execute('begin')
            scene = self._scope(db, scene_id)
            row = self._revision(db, scene['id'], scene['head_revision'] if scene_revision is None else scene_revision)
            snapshot = validate_snapshot(json.loads(row['snapshot']), geographic=True, engineering=callable(engineering_check))
            stored = db.execute('select * from scene_spatial_validations where revision=?', (row['revision'],)).fetchone()
            if snapshot['coordinateFrame']['mode'] == 'projected_site':
                _require(stored is not None, 'SCENE_SCOPE_UNSUPPORTED')
            spatial = json.loads(stored['validation']) if stored is not None else self._local_spatial()['validation']
            provenance = json.loads(stored['height_provenance']) if stored is not None else []
            terrains = [{'terrainVersionId': item['terrain_version_id'], 'contentRevision': item['content_revision'],
                         'sha256': item['source_sha256'], 'reportSha256': item['report_sha256']}
                        for item in db.execute('select * from scene_terrain_uses where revision=? order by terrain_version_id', (row['revision'],))]
            result = {'sceneId': scene['id'], 'projectCode': self.project_code,
                      'sceneRevision': row['revision'], 'headRevision': scene['head_revision'],
                      'savedAt': row['saved_at'], 'snapshot': snapshot,
                      'resourceRefs': json.loads(row['resource_refs']),
                      'validation': spatial, 'heightProvenance': provenance, 'terrainRefs': terrains}
        if callable(engineering_check):
            facts = self._engineering(engineering_check, snapshot, [], [], snapshot, row['revision'], spatial, 'open')
            self._merge_engineering({'validation': spatial}, snapshot, facts)
            self._engineering_preview(result, facts)
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

    def assert_terrain_unused(self, terrain_version_id, authorize: Authorize):
        """Protect both current and retained terrain references from a future cleaner."""
        _require(callable(authorize)); authorize()
        version_id = _uuid(terrain_version_id)
        with self.library.connect() as db:
            db.execute('begin')
            _require(db.execute('select 1 from scene_terrain_uses where terrain_version_id=? limit 1',
                                (version_id,)).fetchone() is None, 'RESOURCE_IN_USE', 409)
            authorize()
