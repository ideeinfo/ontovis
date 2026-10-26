"""Project resources over the existing private versions/files and SQLite store.

This core does not authenticate users. HTTP callers must supply current project
authorization guards. Legacy engineering bindings are neither adopted nor copied.
"""
from __future__ import annotations

import base64
from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
import hmac
import itertools
import json
import math
import os
from pathlib import Path
import secrets
import tempfile
from uuid import UUID, uuid4

from .authority import PreviewError
from .model_validation import MAX_BYTES
from tools.model_probe import strict_json

MAX_VERSIONS = 100
MAX_TOTAL_BYTES = 200 * 1024 * 1024
PURPOSES = frozenset(('equipment', 'simplified_scene', 'environment'))
CALIBRATION_METHOD = 'm-y-up-forward-negative-z-v1'
IDENTITY_MATRIX = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def _require(condition, code='INVALID_REQUEST', status=422):
    if not condition: raise PreviewError(status, code)


def _text(value, limit=200):
    _require(isinstance(value, str) and 0 < len(value.strip()) <= limit
             and all(ord(character) >= 32 for character in value))
    try: value.encode('utf-8')
    except UnicodeError: raise PreviewError(422, 'INVALID_REQUEST') from None
    return value.strip()


def _uuid(value):
    try: result = str(UUID(value))
    except (ValueError, TypeError, AttributeError): raise PreviewError(422, 'INVALID_REQUEST') from None
    _require(result == value)
    return result


def _canonical(value):
    try:
        result = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
        result.encode('utf-8')
        return result
    except (ValueError, TypeError, OverflowError, UnicodeError): raise PreviewError(422, 'INVALID_REQUEST') from None


def _fields(value, required, optional=()):
    _require(type(value) is dict and set(required) <= set(value) <= set(required) | set(optional))


def _now(): return datetime.now(timezone.utc).isoformat()


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try: os.fsync(descriptor)
    finally: os.close(descriptor)


def _vector(value):
    _require(type(value) is list and len(value) == 3)
    _require(all(type(number) in (int, float) and abs(number) <= 1_000_000 and math.isfinite(number)
                 for number in value))
    return list(value)


def _calibration(value, actor, now):
    _fields(value, ('unit', 'axes', 'basePoint', 'forward'))
    _require(value['unit'] == 'm' and value['axes'] == 'Y_UP_RIGHT_HANDED', 'UNSUPPORTED_CALIBRATION')
    base, forward = _vector(value['basePoint']), _vector(value['forward'])
    scale = max(abs(forward[0]), abs(forward[2]))
    _require(forward[1] == 0 and scale > 0, 'INVALID_CALIBRATION')
    length = math.hypot(forward[0] / scale, forward[2] / scale)
    forward = [forward[0] / scale / length, 0, forward[2] / scale / length]
    cosine, sine = -forward[2], forward[0]
    # Three.js column-major, rigid Y rotation followed by translated base origin.
    matrix = [cosine, 0, -sine, 0, 0, 1, 0, 0, sine, 0, cosine, 0,
              -(cosine * base[0] + sine * base[2]), -base[1],
              sine * base[0] - cosine * base[2], 1]
    return {'state': 'verified', 'unit': 'm', 'axes': 'Y_UP_RIGHT_HANDED', 'basePoint': base,
            'forward': forward, 'modelToCalibrated': matrix, 'verifiedBy': actor, 'verifiedAt': now}


def _calibrated_bounds(bounds, matrix):
    _require(type(bounds) is dict and 'min' in bounds and 'max' in bounds, 'INVALID_MODEL')
    low, high = _vector(bounds['min']), _vector(bounds['max'])
    _require(all(a <= b for a, b in zip(low, high)), 'INVALID_MODEL')
    points = []
    for point in itertools.product(*zip(low, high)):
        points.append([sum(matrix[4 * column + row] * point[column] for column in range(3))
                       + matrix[12 + row] for row in range(3)])
    return [[min(point[index] for point in points) for index in range(3)],
            [max(point[index] for point in points) for index in range(3)]]


class ProjectModelLibrary:
    def __init__(self, library):
        self.library = library
        with library.connect() as db:
            self.project_code = db.execute('select project_code from library where id=1').fetchone()[0]
            db.executescript('''
                create table if not exists project_model_assets (
                    id text primary key, project_code text not null, name text not null,
                    purpose text not null, revision integer not null, created_at text not null);
                create table if not exists project_model_versions (
                    version_id text primary key references versions(id),
                    asset_id text not null references project_model_assets(id),
                    content_revision text not null, calibration text,
                    source_version_id text references versions(id));
                create table if not exists project_model_requests (
                    project_code text not null, actor text not null, action text not null,
                    request_id text not null, payload_sha256 text not null, result text not null,
                    primary key(project_code,actor,action,request_id));
                create table if not exists project_model_audit (
                    id integer primary key, project_code text not null, actor text not null,
                    action text not null, request_id text not null, version_id text not null references versions(id),
                    payload_sha256 text not null, created_at text not null);
                create table if not exists project_model_catalog (
                    id integer primary key check(id=1), cursor_secret text not null);
                create table if not exists project_model_info_revisions (
                    id text primary key, asset_id text not null references project_model_assets(id),
                    asset_revision integer not null, name text not null, purpose text not null,
                    description text not null, previous_info text not null,
                    actor text not null, created_at text not null,
                    unique(asset_id,asset_revision));
                create trigger if not exists project_model_info_no_update before update on project_model_info_revisions
                    begin select raise(abort, 'immutable model information'); end;
                create trigger if not exists project_model_info_no_delete before delete on project_model_info_revisions
                    begin select raise(abort, 'retained model information'); end;
                create trigger if not exists project_model_version_no_update before update on project_model_versions
                    begin select raise(abort, 'immutable project model version'); end;
                create trigger if not exists project_model_version_no_delete before delete on project_model_versions
                    begin select raise(abort, 'retained project model version'); end;
                create trigger if not exists project_model_fixed_content before update of
                    id,request_id,actor,name,source_note,sha256,bytes,created_at,components,report on versions
                    when exists (select 1 from project_model_versions where version_id=old.id)
                    begin select raise(abort, 'immutable project model content'); end;
            ''')
            db.execute('insert or ignore into project_model_catalog values (1,?)', (secrets.token_hex(32),))

    @staticmethod
    def capabilities():
        return {'storageScope': 'project_static_glb', 'formats': ['glb'], 'unit': 'm',
                'axes': 'Y_UP_RIGHT_HANDED', 'calibrationMethod': CALIBRATION_METHOD,
                'supportsLegacyAdoption': False, 'supportsDelete': False,
                'maxCalibrationComponentMagnitude': 1_000_000,
                'maxUploadBytes': MAX_BYTES, 'maxVersions': MAX_VERSIONS, 'maxLibraryBytes': MAX_TOTAL_BYTES}

    def _asset(self, db, identifier):
        row = db.execute('select * from project_model_assets where id=? and project_code=?',
                         (_uuid(identifier), self.project_code)).fetchone()
        _require(row is not None, 'NOT_FOUND_OR_FORBIDDEN', 404)
        return row

    def _version(self, db, identifier):
        row = db.execute('''select v.*, p.asset_id, p.content_revision, p.calibration, p.source_version_id
            from versions v join project_model_versions p on p.version_id=v.id
            join project_model_assets a on a.id=p.asset_id where v.id=? and a.project_code=?''',
            (_uuid(identifier), self.project_code)).fetchone()
        _require(row is not None, 'NOT_FOUND_OR_FORBIDDEN', 404)
        value = self._public(row)
        return {**value, 'versionDisplayName': value['displayName'],
                **self._info(db, self._asset(db, value['modelAssetId']))}

    @staticmethod
    def _info(db, asset):
        latest = db.execute('''select description from project_model_info_revisions
            where asset_id=? order by asset_revision desc limit 1''', (asset['id'],)).fetchone()
        return {'displayName': asset['name'], 'purpose': asset['purpose'],
                'description': latest['description'] if latest else '',
                'assetRevision': 'asset:' + asset['id'] + ':' + str(asset['revision'])}

    def save_info(self, body, actor, authorize):
        _fields(body, ('modelAssetId', 'modelVersionId', 'expectedAssetRevision', 'clientRequestId',
                       'displayName', 'purpose', 'description'))
        actor = _text(actor); _require(callable(authorize)); authorize()
        for key in ('modelAssetId', 'modelVersionId', 'clientRequestId'): _uuid(body[key])
        _text(body['expectedAssetRevision']); name = _text(body['displayName'], 200)
        _require(isinstance(body['purpose'], str) and body['purpose'] in PURPOSES)
        description = body['description']
        _require(isinstance(description, str) and len(description) <= 2000
                 and all(ord(char) >= 32 or char in '\n\r\t' for char in description))
        digest = hashlib.sha256(_canonical(body).encode()).hexdigest()
        with self.library.connect() as db:
            db.execute('begin immediate')
            prior = self._prior(db, actor, 'update_info', body['clientRequestId'], digest)
            if prior is not None:
                authorize()
                return prior
            asset = self._asset(db, body['modelAssetId'])
            version = self._version(db, body['modelVersionId'])
            _require(version['modelAssetId'] == asset['id'], 'NOT_FOUND_OR_FORBIDDEN', 404)
            previous = self._info(db, asset)
            _require(previous['assetRevision'] == body['expectedAssetRevision'], 'MODEL_ASSET_CHANGED', 409)
            authorize()
            now = _now()
            db.execute('''insert into project_model_info_revisions values (?,?,?,?,?,?,?,?,?)''',
                (str(uuid4()), asset['id'], asset['revision'] + 1, name, body['purpose'], description,
                 _canonical(previous), actor, now))
            db.execute('update project_model_assets set name=?,purpose=?,revision=revision+1 where id=?',
                       (name, body['purpose'], asset['id']))
            db.execute('update library set revision=revision+1 where id=1')
            value = {**self._version(db, body['modelVersionId']), 'libraryRevision': self.library.revision(db)}
            db.execute('insert into project_model_requests values (?,?,?,?,?,?)',
                (self.project_code, actor, 'update_info', body['clientRequestId'], digest, _canonical(value)))
            db.execute('''insert into project_model_audit
                (project_code,actor,action,request_id,version_id,payload_sha256,created_at) values (?,?,?,?,?,?,?)''',
                (self.project_code, actor, 'update_info', body['clientRequestId'], body['modelVersionId'], digest, now))
            authorize()
            db.commit()
            return value

    @staticmethod
    def _public(row):
        calibration = json.loads(row['calibration']) if row['calibration'] else {'state': 'unverified'}
        return {'modelAssetId': row['asset_id'], 'modelVersionId': row['id'],
                'contentRevision': row['content_revision'], 'displayName': row['name'],
                'sourceNote': row['source_note'], 'sha256': row['sha256'], 'bytes': row['bytes'],
                'createdAt': row['created_at'], 'state': 'ready', 'calibration': calibration,
                'calibrationState': calibration['state'], 'canPlace': calibration['state'] in ('verified', 'legacy_display'),
                'canPlaceGeographic': calibration['state'] == 'verified',
                'report': json.loads(row['report']), 'components': json.loads(row['components']),
                'sourceModelVersionId': row['source_version_id']}

    def content_identity(self, version_id, db=None):
        """Trusted transaction helper; authenticates nobody and never adopts legacy data."""
        with self.library.connect() if db is None else nullcontext(db) as connection:
            row = connection.execute('''select v.id,v.sha256,p.asset_id,p.content_revision,p.calibration,a.project_code
                from versions v left join project_model_versions p on p.version_id=v.id
                left join project_model_assets a on a.id=p.asset_id where v.id=?''',
                (_uuid(version_id),)).fetchone()
            _require(row is not None and (row['content_revision'] is None or row['project_code'] == self.project_code),
                     'NOT_FOUND_OR_FORBIDDEN', 404)
            state = json.loads(row['calibration'])['state'] if row['calibration'] else (
                'unverified' if row['content_revision'] else 'legacy_unverified')
            return {'modelVersionId': row['id'], 'modelAssetId': row['asset_id'], 'sha256': row['sha256'],
                    'contentRevision': row['content_revision'] or 'sha256:' + row['sha256'],
                    'calibrationState': state, 'canPlace': state in ('verified', 'legacy_display'),
                    'canPlaceGeographic': state == 'verified',
                    'isProjectResource': row['content_revision'] is not None}

    def _content(self, value):
        root = self.library.root
        path = root / 'files' / (value['modelVersionId'] + '.glb')
        _require(not root.is_symlink() and not path.parent.is_symlink() and not path.is_symlink()
                 and path.is_file() and path.stat().st_size == value['bytes'], 'RESOURCE_CHANGED', 409)
        content = path.read_bytes()
        _require(hashlib.sha256(content).hexdigest() == value['sha256'], 'RESOURCE_CHANGED', 409)
        return content

    def model(self, asset_id, version_id, authorize):
        _require(callable(authorize)); authorize()
        with self.library.connect() as db:
            self._asset(db, asset_id)
            value = self._version(db, version_id)
            _require(value['modelAssetId'] == asset_id, 'NOT_FOUND_OR_FORBIDDEN', 404)
        self._content(value); authorize()
        return value

    def content(self, version_id, expected_content_revision, expected_sha, authorize):
        _require(callable(authorize)); authorize()
        _text(expected_content_revision)
        _require(isinstance(expected_sha, str) and len(expected_sha) == 64
                 and all(character in '0123456789abcdef' for character in expected_sha))
        with self.library.connect() as db: value = self._version(db, version_id)
        _require(value['contentRevision'] == expected_content_revision and value['sha256'] == expected_sha,
                 'RESOURCE_CHANGED', 409)
        content = self._content(value); authorize()
        return content

    def _cursor(self, db, payload):
        data = _canonical(payload).encode()
        secret = bytes.fromhex(db.execute('select cursor_secret from project_model_catalog where id=1').fetchone()[0])
        return base64.urlsafe_b64encode(data + hmac.digest(secret, data, 'sha256')).decode()

    def listing(self, actor, authorize, *, access_revision, q='', purpose=None, cursor=None,
                expected_library_revision=None, limit=50):
        _text(actor); _text(access_revision); _require(callable(authorize)); authorize()
        _require(isinstance(q, str) and len(q) <= 200 and all(ord(character) >= 32 for character in q))
        if q: _text(q)
        _require(purpose is None or isinstance(purpose, str) and purpose in PURPOSES)
        _require(type(limit) is int and 1 <= limit <= 100)
        if expected_library_revision is not None: _text(expected_library_revision)
        with self.library.connect() as db:
            db.execute('begin')
            revision = self.library.revision(db)
            if expected_library_revision is not None:
                _require(expected_library_revision == revision, 'SNAPSHOT_EXPIRED', 409)
            expected = {'actor': actor, 'accessRevision': access_revision, 'project': self.project_code,
                        'q': q, 'purpose': purpose, 'revision': revision, 'limit': limit}
            offset = 0
            if cursor is not None:
                _require(isinstance(cursor, str) and len(cursor) <= 4096)
                try:
                    raw = base64.b64decode(cursor, altchars=b'-_', validate=True)
                    payload = json.loads(raw[:-32])
                    _require(hmac.compare_digest(self._cursor(db, payload), cursor))
                    _require(type(payload) is dict and set(payload) == set(expected) | {'offset'})
                    _require(payload['revision'] == revision, 'SNAPSHOT_EXPIRED', 409)
                    _require(all(payload[key] == item for key, item in expected.items()))
                    offset = payload['offset']
                    _require(type(offset) is int and 0 <= offset <= MAX_VERSIONS)
                except (ValueError, TypeError, UnicodeError, RecursionError):
                    raise PreviewError(422, 'INVALID_REQUEST') from None
            rows = db.execute('''select * from project_model_assets where project_code=?
                and instr(lower(name),lower(?))>0 and (? is null or purpose=?)
                order by created_at desc,id limit ? offset ?''',
                (self.project_code, q, purpose, purpose, limit + 1, offset)).fetchall()
            items = []
            for row in rows[:limit]:
                versions = db.execute('''select v.*,p.asset_id,p.content_revision,p.calibration,p.source_version_id
                    from versions v join project_model_versions p on p.version_id=v.id where p.asset_id=?
                    order by v.created_at desc,v.id''', (row['id'],)).fetchall()
                items.append({'modelAssetId': row['id'], **self._info(db, row),
                    'versions': [{key: item for key, item in {**self._public(version), 'displayName': row['name']}.items()
                                  if key not in ('report', 'components', 'calibration', 'sourceNote')}
                                 for version in versions]})
            next_cursor = self._cursor(db, {**expected, 'offset': offset + limit}) if len(rows) > limit else None
        authorize()
        return {'items': items, 'libraryRevision': revision, 'nextCursor': next_cursor,
                'capabilities': self.capabilities()}

    def legacy_candidates(self, authorize):
        _require(callable(authorize)); authorize()
        with self.library.connect() as db:
            db.execute('begin')
            rows = db.execute('''select v.*,
                (select count(*) from bindings b where b.version_id=v.id) as binding_count
                from versions v left join project_model_versions p on p.version_id=v.id
                where p.version_id is null order by v.created_at,v.id''').fetchall()
            items = []
            for row in rows:
                imported = self._legacy_import(db, row['id'])
                rights = self._source_rights(db, row)
                item = {'modelVersionId': row['id'], 'displayName': row['name'], 'modelRevision': row['revision'],
                    'sourceNote': row['source_note'], 'sha256': row['sha256'], 'bytes': row['bytes'],
                    'legacyBindingCount': row['binding_count'], 'calibrationState': 'legacy_unverified',
                    'canPlace': False, 'sourceRightsDeclared': rights, 'canImport': rights and imported is None}
                if imported is not None: item['importedResource'] = dict(imported)
                items.append(item)
            result = {'adoptionPerformed': False, 'libraryRevision': self.library.revision(db), 'items': items}
        authorize()
        return result

    @staticmethod
    def _source_rights(db, source):
        audit = db.execute('''select payload from audit where action='model_uploaded'
            and version_id=? and request_id=? and actor=?''',
            (source['id'], source['request_id'], source['actor'])).fetchone()
        if audit is None: return False
        try: payload = strict_json(audit['payload'].encode('utf-8'))
        except (ValueError, TypeError, UnicodeError): return False
        return type(payload) is dict and payload.get('rightsDeclared') is True and payload.get('sha256') == source['sha256']

    @staticmethod
    def _legacy_import(db, identifier):
        return db.execute('''select asset_id as modelAssetId,version_id as modelVersionId
            from project_model_versions where source_version_id=? order by version_id limit 1''', (identifier,)).fetchone()

    def _legacy_source(self, db, metadata):
        row = db.execute('''select v.* from versions v left join project_model_versions p on p.version_id=v.id
            where v.id=? and p.version_id is null''', (metadata['legacyModelVersionId'],)).fetchone()
        _require(row is not None, 'NOT_FOUND_OR_FORBIDDEN', 404)
        _require(self._legacy_import(db, row['id']) is None, 'MODEL_ALREADY_IMPORTED', 409)
        _require(row['revision'] == metadata['expectedModelRevision'] and row['sha256'] == metadata['expectedSha256'],
                 'RESOURCE_CHANGED', 409)
        _require(self._source_rights(db, row), 'MODEL_SOURCE_RIGHTS_REQUIRED', 422)
        return row

    def import_existing(self, body, actor, authorize):
        _fields(body, ('legacyModelVersionId', 'expectedModelRevision', 'expectedSha256',
                       'expectedLibraryRevision', 'purpose', 'clientRequestId'))
        _require(callable(authorize)); actor = _text(actor); authorize()
        _uuid(body['legacyModelVersionId']); _uuid(body['clientRequestId']); _text(body['expectedLibraryRevision'])
        _require(type(body['expectedModelRevision']) is int and body['expectedModelRevision'] >= 1)
        _require(isinstance(body['expectedSha256'], str) and len(body['expectedSha256']) == 64
                 and all(character in '0123456789abcdef' for character in body['expectedSha256']))
        _require(isinstance(body['purpose'], str) and body['purpose'] in PURPOSES)
        digest = hashlib.sha256(_canonical(body).encode()).hexdigest()
        with self.library.connect() as db:
            prior = self._prior(db, actor, 'import_existing', body['clientRequestId'], digest)
            if prior is None: source = dict(self._legacy_source(db, body))
        if prior is not None:
            self._content(prior); authorize(); return prior
        if not self.library.slots.acquire(blocking=False): raise PreviewError(429, 'MODEL_BUSY')
        path = None
        try:
            content = self._content({'modelVersionId': source['id'], 'bytes': source['bytes'], 'sha256': source['sha256']})
            authorize()
            with tempfile.NamedTemporaryFile(dir=self.library.root / 'temporary', prefix='project-upload-', suffix='.glb', delete=False) as file:
                path = Path(file.name); file.write(content); file.flush(); os.fsync(file.fileno())
            metadata = {**body, 'displayName': source['name'], 'sourceNote': source['source_note']}
            result = {'sha256': source['sha256'], 'report': json.loads(source['report']), 'components': json.loads(source['components'])}
            return self._commit(path, metadata, actor, authorize, result, action='import_existing', payload_digest=digest,
                source_version_id=source['id'], legacy_source=True)
        except OSError:
            raise PreviewError(503, 'MODEL_STORAGE_UNAVAILABLE') from None
        finally:
            try:
                if path: path.unlink(missing_ok=True)
            except OSError:
                raise PreviewError(503, 'MODEL_STORAGE_UNAVAILABLE') from None
            finally: self.library.slots.release()

    @staticmethod
    def upload_metadata(value):
        required = ('expectedLibraryRevision', 'clientRequestId', 'displayName', 'purpose', 'sourceNote', 'rightsDeclared')
        _fields(value, required, ('modelAssetId', 'expectedSessionRevision'))
        result = {key: item for key, item in value.items() if key != 'expectedSessionRevision'}
        _uuid(result['clientRequestId']); _text(result['expectedLibraryRevision'])
        for key, maximum in (('displayName', 200), ('sourceNote', 2000)): result[key] = _text(result[key], maximum)
        _require(isinstance(result['purpose'], str) and result['purpose'] in PURPOSES)
        _require(result['rightsDeclared'] is True, 'MODEL_RIGHTS_REQUIRED')
        if 'modelAssetId' in result: _uuid(result['modelAssetId'])
        return result

    def _prior(self, db, actor, action, request_id, digest):
        row = db.execute('''select payload_sha256,result from project_model_requests
            where project_code=? and actor=? and action=? and request_id=?''',
            (self.project_code, actor, action, request_id)).fetchone()
        if row is not None:
            _require(hmac.compare_digest(row['payload_sha256'], digest), 'REQUEST_CONFLICT', 409)
            return json.loads(row['result'])
        return None

    def _capacity(self, db, length):
        count, total = db.execute('select count(*),coalesce(sum(bytes),0) from versions').fetchone()
        physical = 0
        for path in (self.library.root / 'files').glob('*.glb'):
            _require(not path.is_symlink(), 'RESOURCE_CHANGED', 409)
            if path.is_file(): physical += path.stat().st_size
        _require(count < MAX_VERSIONS and max(total, physical) + length <= MAX_TOTAL_BYTES,
                 'MODEL_LIBRARY_FULL', 413)

    def _commit(self, path, metadata, actor, authorize, result, *, action, payload_digest,
                calibration=None, source_version_id=None, legacy_source=False):
        identifier, asset_id, now = str(uuid4()), metadata.get('modelAssetId') or str(uuid4()), _now()
        target = self.library.root / 'files' / (identifier + '.glb')
        committed = published = False
        try:
            with self.library.connect() as db:
                db.execute('begin immediate')
                prior = self._prior(db, actor, action, metadata['clientRequestId'], payload_digest)
                if prior is not None:
                    authorize(); self._content(prior)
                    return prior
                if legacy_source: self._legacy_source(db, metadata)
                _require(self.library.revision(db) == metadata['expectedLibraryRevision'], 'MODEL_LIBRARY_CHANGED', 409)
                if 'modelAssetId' in metadata:
                    asset = self._asset(db, asset_id)
                    _require(asset['purpose'] == metadata['purpose'] and asset['name'] == metadata['displayName'],
                             'MODEL_ASSET_CHANGED', 409)
                self._capacity(db, path.stat().st_size)
                authorize()
                if source_version_id is not None:
                    if legacy_source:
                        source = self._legacy_source(db, metadata)
                        _require(source['name'] == metadata['displayName'] and source['source_note'] == metadata['sourceNote']
                                 and json.loads(source['report']) == result['report']
                                 and json.loads(source['components']) == result['components'], 'RESOURCE_CHANGED', 409)
                        self._content({'modelVersionId': source['id'], 'bytes': source['bytes'], 'sha256': source['sha256']})
                    else:
                        source = self._version(db, source_version_id)
                        _require(source['contentRevision'] == metadata['expectedContentRevision'], 'RESOURCE_CHANGED', 409)
                        self._content(source)
                        if action == 'preserve_legacy_display':
                            legacy = self._preservation_source(db, source)
                            _require(calibration['sourceModelVersionId'] == legacy['id']
                                     and calibration['sourceSha256'] == legacy['sha256'], 'RESOURCE_CHANGED', 409)
                _require(not target.exists() and not target.parent.is_symlink(), 'RESOURCE_CHANGED', 409)
                _require(hashlib.sha256(path.read_bytes()).hexdigest() == result['sha256'], 'RESOURCE_CHANGED', 409)
                os.replace(path, target); published = True
                os.chmod(target, 0o600)
                _sync_directory(target.parent); _sync_directory(path.parent)
                if 'modelAssetId' not in metadata:
                    db.execute('insert into project_model_assets values (?,?,?,?,?,?)',
                        (asset_id, self.project_code, metadata['displayName'], metadata['purpose'], 0, now))
                db.execute('''insert into versions values (?,?,?,?,?,?,?,?,?,?,?)''',
                    (identifier, str(uuid4()), actor, metadata['displayName'], metadata['sourceNote'], result['sha256'],
                     target.stat().st_size, now, 1, _canonical(result['components']), _canonical(result['report'])))
                content_revision = 'model-content:' + hashlib.sha256(_canonical({'sha256': result['sha256'],
                    'components': result['components'], 'report': result['report'], 'calibration': calibration}).encode()).hexdigest()
                db.execute('insert into project_model_versions values (?,?,?,?,?)',
                    (identifier, asset_id, content_revision, _canonical(calibration) if calibration else None, source_version_id))
                db.execute('update project_model_assets set revision=revision+1 where id=?', (asset_id,))
                db.execute('update library set revision=revision+1 where id=1')
                value = self._version(db, identifier)
                value['libraryRevision'] = self.library.revision(db)
                value['assetRevision'] = 'asset:' + asset_id + ':' + str(self._asset(db, asset_id)['revision'])
                db.execute('insert into project_model_requests values (?,?,?,?,?,?)',
                    (self.project_code, actor, action, metadata['clientRequestId'], payload_digest, _canonical(value)))
                db.execute('''insert into project_model_audit(project_code,actor,action,request_id,version_id,payload_sha256,created_at)
                    values (?,?,?,?,?,?,?)''', (self.project_code, actor, action, metadata['clientRequestId'], identifier, payload_digest, now))
                authorize(); self._content(value)
                if legacy_source:
                    source = db.execute('select * from versions where id=?', (source_version_id,)).fetchone()
                    _require(source['revision'] == metadata['expectedModelRevision']
                             and self._source_rights(db, source), 'RESOURCE_CHANGED', 409)
                    self._content({'modelVersionId': source['id'], 'bytes': source['bytes'], 'sha256': metadata['expectedSha256']})
                elif action == 'preserve_legacy_display':
                    legacy = self._preservation_source(db, self._version(db, source_version_id))
                    _require(calibration['sourceModelVersionId'] == legacy['id']
                             and calibration['sourceSha256'] == legacy['sha256'], 'RESOURCE_CHANGED', 409)
                db.commit(); committed = True
                return value
        except OSError:
            raise PreviewError(503, 'MODEL_STORAGE_UNAVAILABLE') from None
        finally:
            if published and not committed: target.unlink(missing_ok=True)

    def upload(self, stream, length, metadata, actor, authorize):
        metadata = self.upload_metadata(metadata); actor = _text(actor)
        _require(callable(authorize)); authorize()
        _require(type(length) is int and 24 <= length <= MAX_BYTES, 'MODEL_LIMIT_EXCEEDED', 413)
        if not self.library.slots.acquire(blocking=False): raise PreviewError(429, 'MODEL_BUSY')
        path = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.library.root / 'temporary', prefix='project-upload-', suffix='.glb', delete=False) as file:
                path = Path(file.name); remaining, digest = length, hashlib.sha256()
                while remaining:
                    chunk = stream.read(min(65536, remaining))
                    _require(type(chunk) is bytes and 0 < len(chunk) <= min(65536, remaining), 'INVALID_MODEL')
                    file.write(chunk); digest.update(chunk); remaining -= len(chunk)
                file.flush(); os.fsync(file.fileno())
            payload_digest = hashlib.sha256(_canonical({'metadata': metadata, 'sha256': digest.hexdigest(), 'bytes': length}).encode()).hexdigest()
            authorize()
            with self.library.connect() as db:
                prior = self._prior(db, actor, 'upload', metadata['clientRequestId'], payload_digest)
            if prior is not None:
                self._content(prior); authorize()
                return prior
            authorize()
            result = self.library.process(path)
            _require(result['sha256'] == digest.hexdigest() and result['report']['bytes'] == length, 'RESOURCE_CHANGED', 409)
            return self._commit(path, metadata, actor, authorize, result, action='upload', payload_digest=payload_digest)
        except OSError:
            raise PreviewError(503, 'MODEL_STORAGE_UNAVAILABLE') from None
        finally:
            try:
                if path: path.unlink(missing_ok=True)
            except OSError:
                raise PreviewError(503, 'MODEL_STORAGE_UNAVAILABLE') from None
            finally:
                self.library.slots.release()

    def calibrate(self, body, actor, authorize):
        _fields(body, ('modelVersionId', 'expectedContentRevision', 'expectedLibraryRevision', 'calibration', 'clientRequestId'),
                ('expectedSessionRevision',))
        body = {key: item for key, item in body.items() if key != 'expectedSessionRevision'}
        actor = _text(actor); _require(callable(authorize)); authorize()
        _uuid(body['modelVersionId']); _uuid(body['clientRequestId'])
        _text(body['expectedContentRevision']); _text(body['expectedLibraryRevision'])
        calibration = _calibration(body['calibration'], actor, _now())
        payload_digest = hashlib.sha256(_canonical(body).encode()).hexdigest()
        with self.library.connect() as db:
            prior = self._prior(db, actor, 'calibrate', body['clientRequestId'], payload_digest)
            if prior is None:
                source = self._version(db, body['modelVersionId'])
                asset = dict(self._asset(db, source['modelAssetId']))
        if prior is not None:
            self._content(prior); authorize()
            return prior
        _require(source['contentRevision'] == body['expectedContentRevision'], 'RESOURCE_CHANGED', 409)
        content = self._content(source); authorize()
        if not self.library.slots.acquire(blocking=False): raise PreviewError(429, 'MODEL_BUSY')
        path = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.library.root / 'temporary', prefix='project-calibration-', suffix='.glb', delete=False) as file:
                path = Path(file.name); file.write(content); file.flush(); os.fsync(file.fileno())
            report = dict(source['report'])
            report['coordinateVerification'] = 'operator_calibrated'
            report['calibrationVerification'] = {'method': CALIBRATION_METHOD,
                'calibratedBounds': _calibrated_bounds(report['bounds'], calibration['modelToCalibrated'])}
            metadata = {'modelAssetId': asset['id'], 'displayName': asset['name'], 'purpose': asset['purpose'],
                'sourceNote': source['sourceNote'], 'clientRequestId': body['clientRequestId'],
                'expectedLibraryRevision': body['expectedLibraryRevision'], 'expectedContentRevision': body['expectedContentRevision']}
            return self._commit(path, metadata, actor, authorize, {'sha256': source['sha256'],
                'components': source['components'], 'report': report}, action='calibrate', payload_digest=payload_digest,
                calibration=calibration, source_version_id=source['modelVersionId'])
        except OSError:
            raise PreviewError(503, 'MODEL_STORAGE_UNAVAILABLE') from None
        finally:
            try:
                if path: path.unlink(missing_ok=True)
            except OSError:
                raise PreviewError(503, 'MODEL_STORAGE_UNAVAILABLE') from None
            finally:
                self.library.slots.release()

    def _preservation_source(self, db, source):
        _require(source['calibration'] == {'state': 'unverified'})
        identifier = _uuid(source.get('sourceModelVersionId'))
        legacy = db.execute('''select v.* from versions v left join project_model_versions p on p.version_id=v.id
            where v.id=? and p.version_id is null''', (identifier,)).fetchone()
        audit = db.execute('''select 1 from project_model_audit where project_code=?
            and version_id=? and action='import_existing' ''', (self.project_code, source['modelVersionId'])).fetchone()
        _require(legacy is not None and audit is not None)
        _require(self._source_rights(db, legacy), 'MODEL_SOURCE_RIGHTS_REQUIRED')
        _require(source['sha256'] == legacy['sha256'] and source['bytes'] == legacy['bytes']
                 and source['components'] == json.loads(legacy['components'])
                 and source['report'] == json.loads(legacy['report']), 'RESOURCE_CHANGED', 409)
        self._content(source)
        self._content({'modelVersionId': legacy['id'], 'bytes': legacy['bytes'], 'sha256': legacy['sha256']})
        return legacy

    def preserve_legacy_display(self, body, actor, authorize):
        _fields(body, ('modelVersionId', 'expectedContentRevision', 'expectedLibraryRevision',
                       'clientRequestId', 'preservationBasis'))
        actor = _text(actor); _require(callable(authorize)); authorize()
        _uuid(body['modelVersionId']); _uuid(body['clientRequestId'])
        _text(body['expectedContentRevision']); _text(body['expectedLibraryRevision'])
        _fields(body['preservationBasis'], ('mode', 'sourceNote'))
        _require(body['preservationBasis']['mode'] == 'preserve_legacy_display')
        note = _text(body['preservationBasis']['sourceNote'], 2000)
        digest = hashlib.sha256(_canonical(body).encode()).hexdigest()
        with self.library.connect() as db:
            prior = self._prior(db, actor, 'preserve_legacy_display', body['clientRequestId'], digest)
            if prior is None:
                source = self._version(db, body['modelVersionId'])
                _require(source['contentRevision'] == body['expectedContentRevision'], 'RESOURCE_CHANGED', 409)
                legacy = self._preservation_source(db, source)
                asset = dict(self._asset(db, source['modelAssetId']))
        if prior is not None:
            self._content(prior); authorize(); return prior
        calibration = {'state': 'legacy_display', 'unit': 'm', 'axes': 'Y_UP_RIGHT_HANDED',
            'modelToCalibrated': list(IDENTITY_MATRIX), 'sourceModelVersionId': legacy['id'],
            'sourceSha256': legacy['sha256'], 'sourceNote': note, 'preservedBy': actor, 'preservedAt': _now()}
        if not self.library.slots.acquire(blocking=False): raise PreviewError(429, 'MODEL_BUSY')
        path = None
        try:
            content = self._content(source); authorize()
            with tempfile.NamedTemporaryFile(dir=self.library.root / 'temporary', prefix='project-calibration-', suffix='.glb', delete=False) as file:
                path = Path(file.name); file.write(content); file.flush(); os.fsync(file.fileno())
            report = {**source['report'], 'coordinateVerification': 'legacy_display_preserved'}
            metadata = {'modelAssetId': asset['id'], 'displayName': asset['name'], 'purpose': asset['purpose'],
                'sourceNote': source['sourceNote'], 'clientRequestId': body['clientRequestId'],
                'expectedLibraryRevision': body['expectedLibraryRevision'], 'expectedContentRevision': body['expectedContentRevision']}
            return self._commit(path, metadata, actor, authorize, {'sha256': source['sha256'],
                'components': source['components'], 'report': report}, action='preserve_legacy_display', payload_digest=digest,
                calibration=calibration, source_version_id=source['modelVersionId'])
        except OSError:
            raise PreviewError(503, 'MODEL_STORAGE_UNAVAILABLE') from None
        finally:
            try:
                if path: path.unlink(missing_ok=True)
            except OSError:
                raise PreviewError(503, 'MODEL_STORAGE_UNAVAILABLE') from None
            finally:
                self.library.slots.release()
