"""Read-only preparation for the existing seven-unit preview's scene migration.

No apply operation, network, ModelLibrary initialization or engineering writes.
Plans contain private engineering identities; write them only to private output.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apps.api.model_validation import MAX_BYTES, validate
from tools.model_probe import ProbeError, strict_json

MAX_JSON_BYTES = 1024 * 1024
ROLES = ('CT', 'CN1', 'CN')
QUALITY = {'CT': 'proxy_schematic', 'CN1': 'proxy_schematic', 'CN': 'source_candidate'}
COLUMNS = {
    'library': ('id', 'revision', 'project_code', 'context_id'),
    'versions': ('id', 'request_id', 'actor', 'name', 'source_note', 'sha256', 'bytes',
                 'created_at', 'revision', 'components', 'report'),
    'bindings': ('version_id', 'entity_uid', 'entity_revision', 'hierarchy_revision', 'component_key'),
    'audit': ('id', 'request_id', 'actor', 'action', 'version_id', 'payload', 'created_at')}
TYPES = {'library': ('INTEGER', 'INTEGER', 'TEXT', 'TEXT'),
    'versions': ('TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'INTEGER', 'TEXT', 'INTEGER', 'TEXT', 'TEXT'),
    'bindings': ('TEXT',) * 5, 'audit': ('INTEGER',) + ('TEXT',) * 6}


class MigrationError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _require(value, code='INVALID_INPUT'):
    if not value: raise MigrationError(code)


def _canonical(value):
    try: return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, UnicodeError, OverflowError): raise MigrationError('INVALID_INPUT') from None


def _digest(value): return hashlib.sha256(_canonical(value)).hexdigest()


def _fields(value, names):
    _require(type(value) is dict and set(value) == set(names))


def _text(value, limit=512):
    _require(type(value) is str and 0 < len(value) <= limit and value == value.strip()
             and all(ord(character) >= 32 for character in value))
    _canonical(value)
    return value


def _uuid(value):
    _text(value)
    try: _require(str(UUID(value)) == value)
    except (TypeError, ValueError, AttributeError): raise MigrationError('INVALID_INPUT') from None
    return value


def _sha(value):
    _require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None)
    return value


def _path(value, *, directory=False):
    try: path = Path(value)
    except (TypeError, ValueError): raise MigrationError('UNSAFE_PATH') from None
    _require(path.is_absolute() and '..' not in path.parts, 'UNSAFE_PATH')
    try:
        current = Path(path.anchor)
        for part in path.parts[1:]:
            current = current / part
            _require(not current.is_symlink(), 'UNSAFE_PATH')
        info = path.lstat()
        _require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode), 'UNSAFE_PATH')
    except OSError: raise MigrationError('UNSAFE_PATH') from None
    return path


def _identity(info): return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _read(path, limit):
    path = _path(path)
    try:
        before = path.lstat()
        _require(0 <= before.st_size <= limit, 'INPUT_LIMIT_EXCEEDED')
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as file:
            opened = os.fstat(file.fileno())
            _require(_identity(before) == _identity(opened) and stat.S_ISREG(opened.st_mode), 'INPUT_CHANGED')
            value = file.read(limit + 1)
            _require(len(value) == opened.st_size and _identity(opened) == _identity(os.fstat(file.fileno())), 'INPUT_CHANGED')
        _path(path)
        _require(_identity(opened) == _identity(path.lstat()), 'INPUT_CHANGED')
        return value
    except OSError: raise MigrationError('INPUT_CHANGED') from None


def _json(value):
    try:
        if type(value) is str:
            _require(len(value.encode('utf-8')) <= MAX_JSON_BYTES, 'INPUT_LIMIT_EXCEEDED')
            value = strict_json(value.encode('utf-8'))
        _require(len(_canonical(value)) <= MAX_JSON_BYTES, 'INPUT_LIMIT_EXCEEDED')
        def visit(item, depth=0):
            _require(depth <= 20, 'INPUT_LIMIT_EXCEEDED')
            if type(item) is dict:
                for key, child in item.items(): _require(type(key) is str); visit(child, depth+1)
            elif type(item) is list:
                _require(len(item) <= 10000, 'INPUT_LIMIT_EXCEEDED')
                for child in item: visit(child, depth+1)
            elif type(item) is float: _require(math.isfinite(item))
            else: _require(item is None or type(item) in (str, bool, int))
        visit(value)
        return value
    except MigrationError: raise
    except (ProbeError, ValueError, TypeError, UnicodeError, RecursionError): raise MigrationError('INVALID_INPUT') from None


def read_json(path):
    try: return _json(strict_json(_read(path, MAX_JSON_BYTES)))
    except MigrationError: raise
    except (ProbeError, ValueError, UnicodeError, RecursionError): raise MigrationError('INVALID_INPUT') from None


def _vector(value):
    _require(type(value) is list and len(value) == 3 and all(type(n) in (int, float)
             and math.isfinite(n) and abs(n) <= 1000000 for n in value), 'INVALID_CALIBRATION')


def _box(value):
    if type(value) is dict:
        _require({'min', 'max'} <= set(value) <= {'min', 'max', 'basis'}, 'INVALID_DIRECTORY')
        if 'basis' in value: _text(value['basis'], 2000)
        value = [value['min'], value['max']]
    _require(type(value) is list and len(value) == 2, 'INVALID_DIRECTORY')
    for point in value:
        try: _vector(point)
        except MigrationError: raise MigrationError('INVALID_DIRECTORY') from None
    _require(all(low <= high for low, high in zip(*value)), 'INVALID_DIRECTORY')


def _inputs(value, version_id):
    value = _json(value)
    _fields(value, ('schemaVersion', 'projectCode', 'installationContextId', 'rootEntityUid',
        'childEntityUid', 'cabinetRefs', 'defaultSource', 'calibration', 'calibrationSourceNote'))
    _require(type(value['schemaVersion']) is int and value['schemaVersion'] == 1)
    _text(value['projectCode'], 200); _uuid(value['installationContextId'])
    _fields(value['cabinetRefs'], ROLES)
    identities = [value['rootEntityUid'], value['childEntityUid'], *value['cabinetRefs'].values()]
    for uid in identities: _text(uid)
    _require(len(set(identities)) == 5, 'AMBIGUOUS_IDENTITY')
    default = value['defaultSource']
    _require(type(default) is dict)
    if default.get('kind') == 'uploaded_version':
        _fields(default, ('kind', 'legacyModelVersionId'))
        _require(_uuid(default['legacyModelVersionId']) == version_id, 'SOURCE_MISMATCH')
    else:
        _fields(default, ('kind', 'sha256'))
        _require(default['kind'] == 'fixed_model'); _sha(default['sha256'])
    calibration, note = value['calibration'], value['calibrationSourceNote']
    if calibration is None:
        _require(note is None)
    else:
        _text(note, 2000)
        if type(calibration) is dict and calibration.get('mode') == 'preserve_legacy_display':
            _fields(calibration, ('mode',))
        else:
            _fields(calibration, ('unit', 'axes', 'basePoint', 'forward'))
            _require(calibration['unit'] == 'm' and calibration['axes'] == 'Y_UP_RIGHT_HANDED', 'INVALID_CALIBRATION')
            _vector(calibration['basePoint']); _vector(calibration['forward'])
            _require(calibration['forward'][1] == 0 and any(calibration['forward'][i] != 0 for i in (0, 2)), 'INVALID_CALIBRATION')
    return json.loads(_canonical(value))


def _schema(db):
    for table, columns in COLUMNS.items():
        item = db.execute('select type,sql from sqlite_master where name=?', (table,)).fetchone()
        _require(item is not None and item[0] == 'table' and item[1].lstrip().lower().startswith('create table'), 'INVALID_STORE')
        info = db.execute('pragma table_xinfo('+table+')').fetchall()
        _require(tuple(row[1] for row in info) == columns and tuple(row[2].upper() for row in info) == TYPES[table]
                 and all(row[6] == 0 for row in info), 'INVALID_STORE')
    _require(db.execute('pragma foreign_key_check').fetchone() is None, 'INVALID_STORE')


def _store(root, version_id):
    root = _path(root, directory=True); _path(root/'files', directory=True)
    database = root/'library.sqlite3'
    raw = _read(database, 64*1024*1024)
    _require(raw[:16] == b'SQLite format 3\0' and len(raw) >= 100, 'INVALID_STORE')
    _require(raw[18:20] == b'\x01\x01', 'STORE_FORMAT_UNSUPPORTED')
    _require(not any(Path(str(database)+suffix).exists() or Path(str(database)+suffix).is_symlink()
                     for suffix in ('-journal', '-wal', '-shm')), 'STORE_BUSY')
    try:
        with closing(sqlite3.connect(database.as_uri()+'?mode=ro', uri=True, timeout=.25)) as db:
            db.row_factory = sqlite3.Row
            db.execute('pragma query_only=on'); db.execute('pragma busy_timeout=250'); db.execute('begin')
            _schema(db)
            scope = db.execute('select * from library').fetchall()
            _require(len(scope) == 1 and scope[0]['id'] == 1 and type(scope[0]['revision']) is int
                     and scope[0]['revision'] >= 0, 'INVALID_STORE')
            source = db.execute('select * from versions where id=?', (version_id,)).fetchone()
            _require(source is not None, 'VERSION_NOT_FOUND')
            project_table = db.execute("select type from sqlite_master where name='project_model_versions'").fetchone()
            if project_table is not None:
                _require(project_table[0] == 'table', 'INVALID_STORE')
                _require(db.execute('select 1 from project_model_versions where version_id=?', (version_id,)).fetchone() is None, 'NOT_LEGACY_VERSION')
            bindings = db.execute('select * from bindings where version_id=? order by entity_uid', (version_id,)).fetchall()
            audits = db.execute('select * from audit where version_id=? order by id limit 1001', (version_id,)).fetchall()
            _require(len(audits) <= 1000, 'INPUT_LIMIT_EXCEEDED')
            result = dict(scope[0]), dict(source), [dict(row) for row in bindings], [dict(row) for row in audits]
    except sqlite3.Error as error:
        code = 'STORE_BUSY' if getattr(error, 'sqlite_errorcode', 0) & 255 in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) else 'INVALID_STORE'
        raise MigrationError(code) from None
    _require(_read(database, 64*1024*1024) == raw, 'INPUT_CHANGED')
    return root, hashlib.sha256(raw).hexdigest(), result


def _directory(source, artifact, inputs, bindings):
    components, report = _json(source['components']), _json(source['report'])
    _require(type(components) is list and 1 <= len(components) <= 2002 and type(report) is dict, 'INVALID_DIRECTORY')
    _box(report.get('bounds'))
    try: probe = validate(artifact)
    except (ProbeError, ValueError, KeyError, TypeError, IndexError, OverflowError, MemoryError, RecursionError):
        raise MigrationError('INVALID_MODEL') from None
    _require(probe['sha256'] == source['sha256'] and probe['report']['bounds'] == report['bounds'], 'INVALID_DIRECTORY')
    generated = {item['componentKey']: item for item in probe['components']}
    catalog, used_nodes = {}, set()
    for item in components:
        _fields(item, ('componentKey', 'displayName', 'nodeIndices', 'keyStability', 'geometryQuality', 'bounds'))
        key = _text(item['componentKey']); _text(item['displayName'], 200)
        _require(key not in catalog and item['keyStability'] == 'version_local', 'INVALID_DIRECTORY')
        _box(item['bounds'])
        nodes = item['nodeIndices']
        _require(type(nodes) is list and len(nodes) <= 2000 and all(type(index) is int and 0 <= index < probe['report']['nodes'] for index in nodes)
                 and len(nodes) == len(set(nodes)) and not used_nodes.intersection(nodes), 'INVALID_DIRECTORY')
        used_nodes.update(nodes)
        if item['geometryQuality'] == 'source_candidate':
            _require(key in generated and item == generated[key], 'INVALID_DIRECTORY')
        else:
            _require(item['geometryQuality'] == 'proxy_schematic' and key in ('proxy:CT', 'proxy:CN1') and nodes == [], 'INVALID_DIRECTORY')
        catalog[key] = item
    _require(set(generated) <= catalog.keys() and set(catalog) == set(generated) | {'proxy:CT', 'proxy:CN1'}, 'INVALID_DIRECTORY')
    _require(len(bindings) == 3 and {row['entity_uid'] for row in bindings} == set(inputs['cabinetRefs'].values())
             and len({row['component_key'] for row in bindings}) == 3, 'AMBIGUOUS_BINDING')
    role_bindings = []
    by_uid = {row['entity_uid']: row for row in bindings}
    for role in ROLES:
        row = by_uid[inputs['cabinetRefs'][role]]
        _text(row['entity_revision']); _text(row['hierarchy_revision'])
        prefix = inputs['installationContextId'] + ':'
        revision = row['hierarchy_revision'].removeprefix(prefix)
        _require(row['hierarchy_revision'].startswith(prefix) and revision.isascii()
                 and revision.isdecimal() and int(revision) > 0, 'SOURCE_MISMATCH')
        key = row['component_key']; _require(key in catalog, 'INVALID_DIRECTORY')
        component = catalog[key]
        _require(component['geometryQuality'] == QUALITY[role], 'SOURCE_MISMATCH')
        if role != 'CN': _require(key == 'proxy:'+role, 'SOURCE_MISMATCH')
        role_bindings.append({'role': role, 'entityUid': row['entity_uid'], 'componentKey': key,
            'geometryQuality': component['geometryQuality'], 'bounds': component['bounds'],
            'expectedEntityRevision': row['entity_revision'], 'expectedHierarchyRevision': row['hierarchy_revision']})
    return components, report, role_bindings


def _history(path, inputs, source, role_bindings, *, fixed=False):
    if path is None: return None
    config_path = _path(path, directory=True)/'model.json' if fixed else _path(path)
    raw = _read(config_path, MAX_JSON_BYTES)
    try: value = _json(strict_json(raw))
    except ProbeError: raise MigrationError('INVALID_INPUT') from None
    fields = ('schemaVersion', 'projectCode', 'installationContextId', 'rootEntityUid', 'sha256', 'bindings') if fixed else (
        'schemaVersion', 'projectCode', 'installationContextId', 'rootEntityUid', 'childEntityUid',
        'unitLabel', 'sourceModelSha256', 'derivedModelSha256', 'bindings')
    if fixed:
        _require(type(value) is dict and set(fields) <= set(value)
                 <= set(fields) | {'licenceBasis', 'sourceModelSha256'})
        if 'licenceBasis' in value: _text(value['licenceBasis'], 2000)
        if 'sourceModelSha256' in value: _sha(value['sourceModelSha256'])
    else:
        _fields(value, fields)
    _require(type(value['schemaVersion']) is int and value['schemaVersion'] == 1 and value['projectCode'] == inputs['projectCode']
             and value['installationContextId'] == inputs['installationContextId']
             and value['rootEntityUid'] == inputs['rootEntityUid'], 'SOURCE_MISMATCH')
    _require(type(value['bindings']) is list and len(value['bindings']) == 3, 'AMBIGUOUS_BINDING')
    seen = set(); roles = {item['role']: item for item in role_bindings}
    for binding in value['bindings']:
        _fields(binding, ('entityUid', 'entityRevision', 'componentKey', 'geometryQuality', 'bounds') if fixed else ('entityUid', 'componentKey', 'geometryQuality'))
        role = binding['componentKey']
        _require(role in ROLES and role not in seen, 'AMBIGUOUS_BINDING'); seen.add(role)
        _require(binding['entityUid'] == inputs['cabinetRefs'][role] and binding['geometryQuality'] == QUALITY[role], 'SOURCE_MISMATCH')
        if fixed:
            _require(binding['entityRevision'] == roles[role]['expectedEntityRevision'] and binding['bounds'] == roles[role]['bounds'], 'SOURCE_MISMATCH')
    if fixed:
        _require(value['sha256'] == source['sha256'], 'SOURCE_MISMATCH')
        artifact = _read(config_path.parent/'model.glb', MAX_BYTES)
        _require(len(artifact) == source['bytes'] and hashlib.sha256(artifact).hexdigest() == source['sha256'], 'SOURCE_MISMATCH')
    else:
        _require(value['childEntityUid'] == inputs['childEntityUid'] and value['unitLabel'] == '7'
                 and value['derivedModelSha256'] == source['sha256'], 'SOURCE_MISMATCH')
        _sha(value['sourceModelSha256'])
    _require(_read(config_path, MAX_JSON_BYTES) == raw, 'INPUT_CHANGED')
    return {'configSha256': hashlib.sha256(raw).hexdigest(), 'modelSha256': source['sha256']}


def _historical_fingerprints(fixed_model_root, session_manifest):
    paths = []
    if fixed_model_root is not None:
        root = _path(fixed_model_root, directory=True)
        paths.extend(((root/'model.json', MAX_JSON_BYTES), (root/'model.glb', MAX_BYTES)))
    if session_manifest is not None:
        paths.append((_path(session_manifest), MAX_JSON_BYTES))
    fingerprints = []
    for path, limit in paths:
        path = _path(path)
        try:
            before = _identity(path.lstat())
            raw = _read(path, limit)
            _require(_identity(path.lstat()) == before, 'INPUT_CHANGED')
        except OSError:
            raise MigrationError('INPUT_CHANGED') from None
        fingerprints.append((before, hashlib.sha256(raw).hexdigest()))
    return fingerprints


def plan(library_root, version_id, inputs, *, fixed_model_root=None, session_manifest=None):
    """Validate exact local inputs; always retain the absent current-reader proof."""
    version_id = _uuid(version_id); inputs = _inputs(inputs, version_id)
    root, database_sha, (scope, source, bindings, audits) = _store(library_root, version_id)
    _require(scope['project_code'] == inputs['projectCode'] and scope['context_id'] == inputs['installationContextId'], 'SOURCE_MISMATCH')
    _require(type(source['revision']) is int and source['revision'] >= 1 and source['id'] == version_id, 'INVALID_STORE')
    _uuid(source['request_id']); _text(source['actor'], 200); _text(source['name'], 200)
    _text(source['source_note'], 2000); _text(source['created_at'], 200)
    _sha(source['sha256']); _require(type(source['bytes']) is int and 24 <= source['bytes'] <= MAX_BYTES, 'INVALID_MODEL')
    artifact_path = root/'files'/(version_id+'.glb')
    artifact = _read(artifact_path, MAX_BYTES)
    _require(len(artifact) == source['bytes'] and hashlib.sha256(artifact).hexdigest() == source['sha256'], 'MODEL_CHANGED')
    components, report, role_bindings = _directory(source, artifact_path, inputs, bindings)
    matching = [row for row in audits if row['action'] == 'model_uploaded' and row['request_id'] == source['request_id'] and row['actor'] == source['actor']]
    _require(len(matching) == 1, 'SOURCE_RIGHTS_REQUIRED')
    rights = _json(matching[0]['payload'])
    _require(type(rights) is dict and rights.get('rightsDeclared') is True and rights.get('sha256') == source['sha256'], 'SOURCE_RIGHTS_REQUIRED')
    for row in audits: row['payload'] = _json(row['payload'])
    for binding in bindings:
        _require(any(row['action'] == 'binding_saved' and type(row['payload']) is dict and all(row['payload'].get(key) == value for key, value in (
            ('modelVersionId', version_id), ('entityUid', binding['entity_uid']), ('componentKey', binding['component_key']),
            ('expectedEntityRevision', binding['entity_revision']), ('expectedHierarchyRevision', binding['hierarchy_revision']))) for row in audits), 'INVALID_SOURCE_AUDIT')
    historical_inputs = _historical_fingerprints(fixed_model_root, session_manifest)
    fixed = _history(fixed_model_root, inputs, source, role_bindings, fixed=True)
    manifest = _history(session_manifest, inputs, source, role_bindings)
    if inputs['defaultSource']['kind'] == 'fixed_model':
        _require(fixed is not None and inputs['defaultSource']['sha256'] == source['sha256'], 'SOURCE_MISMATCH')
    calibration = inputs['calibration']
    state = 'missing' if calibration is None else 'legacy_display_only' if 'mode' in calibration else 'input_provided'
    blockers = ['CURRENT_ENGINEERING_PROOF_REQUIRED']
    if state != 'input_provided': blockers.append('CALIBRATION_REQUIRED')
    _require(_read(artifact_path, MAX_BYTES) == artifact, 'INPUT_CHANGED')
    _, final_database_sha, _ = _store(root, version_id)
    _require(final_database_sha == database_sha, 'INPUT_CHANGED')
    try:
        final_historical_inputs = _historical_fingerprints(fixed_model_root, session_manifest)
    except (MigrationError, OSError):
        raise MigrationError('INPUT_CHANGED') from None
    _require(final_historical_inputs == historical_inputs, 'INPUT_CHANGED')
    result = {'schemaVersion': 1, 'kind': 'legacy_scene_migration_plan', 'scope': {
        'projectCode': scope['project_code'], 'installationContextId': scope['context_id']},
        'legacyModelVersionId': version_id, 'libraryRevision': 'library:'+str(scope['revision']),
        'versionRevision': source['revision'], 'databaseSha256': database_sha,
        'content': {'sha256': source['sha256'], 'bytes': source['bytes']},
        'componentCount': len(components), 'directorySha256': _digest(components), 'reportSha256': _digest(report),
        'bindingCount': len(bindings), 'bindingSha256': _digest(bindings), 'auditCount': len(audits), 'auditSha256': _digest(audits),
        'sourceRightsDeclared': True, 'inputs': inputs, 'roleBindings': role_bindings,
        'historicalSources': {'fixedModel': fixed, 'sessionManifest': manifest},
        'oldEngineeringExpectations': [{'entityUid': row['entity_uid'], 'expectedEntityRevision': row['entity_revision'],
            'installationContextId': scope['context_id'], 'expectedHierarchyRevision': row['hierarchy_revision']} for row in bindings],
        'currentEngineeringProof': {'state': 'not_obtained', 'blocking': True},
        'calibrationState': state, 'canPlace': False, 'geographicPlacementAllowed': False,
        'ready': False, 'blockers': sorted(blockers), 'applySupported': False}
    return {**result, 'planSha256': _digest(result)}


def verify(library_root, version_id, inputs, expected_plan, *, fixed_model_root=None, session_manifest=None):
    _require(type(expected_plan) is dict and type(expected_plan.get('planSha256')) is str, 'PLAN_CHANGED')
    body = {key: value for key, value in expected_plan.items() if key != 'planSha256'}
    _require(_digest(body) == expected_plan['planSha256'], 'PLAN_CHANGED')
    current = plan(library_root, version_id, inputs, fixed_model_root=fixed_model_root, session_manifest=session_manifest)
    _require(current == expected_plan, 'PLAN_CHANGED')
    return {'schemaVersion': 1, 'kind': 'legacy_scene_migration_verification', 'planSha256': current['planSha256'],
        'inputsUnchanged': True, 'ready': False, 'applySupported': False,
        'currentEngineeringProof': current['currentEngineeringProof'], 'blockers': current['blockers']}


def write_report(output, value, *, protected=()):
    path = Path(output)
    _require(path.is_absolute() and '..' not in path.parts, 'UNSAFE_OUTPUT')
    _path(path.parent, directory=True)
    for source in protected:
        if source is not None:
            item = Path(source)
            _require(path != item and item not in path.parents, 'UNSAFE_OUTPUT')
    data = _canonical(value)+b'\n'
    _require(len(data) <= MAX_JSON_BYTES, 'INPUT_LIMIT_EXCEEDED')
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'wb') as file:
            file.write(data); file.flush(); os.fsync(file.fileno())
    except OSError: raise MigrationError('UNSAFE_OUTPUT') from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('plan', 'verify'))
    parser.add_argument('--library-root', required=True); parser.add_argument('--version-id', required=True)
    parser.add_argument('--inputs', required=True); parser.add_argument('--fixed-model-root')
    parser.add_argument('--session-manifest'); parser.add_argument('--plan'); parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        _require((args.operation == 'verify') == (args.plan is not None))
        inputs = read_json(args.inputs)
        options = {'fixed_model_root': args.fixed_model_root, 'session_manifest': args.session_manifest}
        result = verify(args.library_root, args.version_id, inputs, read_json(args.plan), **options) if args.operation == 'verify' else plan(args.library_root, args.version_id, inputs, **options)
        write_report(args.output, result, protected=(args.library_root, args.inputs, args.fixed_model_root, args.session_manifest, args.plan))
        return 0
    except MigrationError as error:
        print(json.dumps({'code': error.code}), file=sys.stderr)
        return 2


if __name__ == '__main__': sys.exit(main())
