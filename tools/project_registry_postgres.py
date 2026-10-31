"""Stage and recover exact registry metadata from a verified offline backup.

Staging does not copy resources. Recovery pairs the fixed snapshot with source
files in a new SQLite backup; neither action activates PostgreSQL in the service.
"""
from __future__ import annotations

import argparse
import copy
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
from uuid import UUID

from tools import model_store_backup as paired, project_store_backup as backups

FORMAT = 'ontovis-project-registry-staging-package-v1'
SCHEMA = 'ontovis_registry_stage_v1'
MAX_PACKAGE_BYTES = 4 * 1024 * 1024
MAX_WORKSPACES = 10_000
COLUMNS = {
    'registry_meta': ('id', 'schema_version', 'connection_id'),
    'project_workspaces': ('workspace_id', 'ontobase_connection_id', 'project_code', 'storage_key',
                           'legacy_context_id', 'state', 'block_reason', 'created_at'),
    'shared_model_store': ('id', 'connection_id', 'scope_version'),
}
LOCK_KEY = int.from_bytes(hashlib.sha256(SCHEMA.encode()).digest()[:8], 'big', signed=True)


class MigrationError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _require(value, code):
    if not value:
        raise MigrationError(code)


def _text(value, limit=200):
    return (type(value) is str and 0 < len(value) <= limit and value == value.strip()
            and all(ord(character) >= 32 for character in value))


def _uuid(value):
    try:
        return type(value) is str and str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def _registry(value):
    _require(type(value) is dict and set(value) == set(COLUMNS), 'REGISTRY_PROFILE_UNSUPPORTED')
    for name, columns in COLUMNS.items():
        _require(type(value[name]) is list and all(type(row) is dict and set(row) == set(columns)
                                                 for row in value[name]), 'REGISTRY_PROFILE_UNSUPPORTED')
    meta, shared = value['registry_meta'], value['shared_model_store']
    _require(len(meta) == len(shared) == 1, 'REGISTRY_SCOPE_INVALID')
    meta, shared = meta[0], shared[0]
    _require(type(meta['id']) is int and meta['id'] == 1 and type(meta['schema_version']) is int
             and meta['schema_version'] == 1 and _text(meta['connection_id']), 'REGISTRY_SCOPE_INVALID')
    _require(type(shared['id']) is int and shared['id'] == 1 and type(shared['scope_version']) is int
             and shared['scope_version'] == 1 and shared['connection_id'] == meta['connection_id'], 'REGISTRY_SCOPE_INVALID')
    rows = value['project_workspaces']
    _require(len(rows) <= MAX_WORKSPACES, 'REGISTRY_BUDGET_EXCEEDED')
    identifiers, projects, keys = set(), set(), set()
    for row in rows:
        _require(_uuid(row['workspace_id']) and row['ontobase_connection_id'] == meta['connection_id']
                 and _text(row['project_code']) and (row['storage_key'] == 'legacy' or _uuid(row['storage_key']))
                 and (row['legacy_context_id'] is None or _uuid(row['legacy_context_id']))
                 and row['state'] in ('preparing', 'ready', 'blocked')
                 and (row['block_reason'] is None or _text(row['block_reason'], 2000))
                 and _text(row['created_at'], 100), 'REGISTRY_SCOPE_INVALID')
        try:
            _require(datetime.fromisoformat(row['created_at'].replace('Z', '+00:00')).utcoffset() is not None,
                     'REGISTRY_SCOPE_INVALID')
        except ValueError:
            raise MigrationError('REGISTRY_SCOPE_INVALID') from None
        _require(row['workspace_id'] not in identifiers and row['project_code'] not in projects
                 and row['storage_key'] not in keys, 'REGISTRY_SCOPE_INVALID')
        identifiers.add(row['workspace_id']); projects.add(row['project_code']); keys.add(row['storage_key'])
    _require([row['workspace_id'] for row in rows] == sorted(identifiers), 'REGISTRY_PACKAGE_NONCANONICAL')
    return value


def _package(value):
    _require(type(value) is dict and set(value) == {'format', 'schemaVersion', 'sourceManifestSha256',
             'sourceRegistrySha256', 'registry'}, 'REGISTRY_PACKAGE_INVALID')
    _require(value['format'] == FORMAT and type(value['schemaVersion']) is int and value['schemaVersion'] == 1
             and paired._sha(value['sourceManifestSha256']) and paired._sha(value['sourceRegistrySha256']),
             'REGISTRY_PACKAGE_INVALID')
    _registry(value['registry'])
    return value


def _source_registry(backup, manifest_sha256):
    try:
        report = backups.verify(backup, manifest_sha256)
    except (sqlite3.Error, KeyError, TypeError):
        raise MigrationError('REGISTRY_SOURCE_INVALID') from None
    source = backup / 'project-spaces/registry.sqlite3'
    before, identity = paired._fingerprint(source)
    _require(before == report['projects'].get('registry.sqlite3') and before['bytes'] <= 64 * 1024 * 1024,
             'REGISTRY_SOURCE_CHANGED')
    registry = {}
    try:
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as db:
            db.row_factory = sqlite3.Row
            db.execute('pragma query_only=on'); db.execute('begin')
            tables = {row[0] for row in db.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")}
            _require(tables == set(COLUMNS), 'REGISTRY_PROFILE_UNSUPPORTED')
            for name, columns in COLUMNS.items():
                _require(tuple(row[1] for row in db.execute('pragma table_info('+name+')')) == columns,
                         'REGISTRY_PROFILE_UNSUPPORTED')
                order = 'workspace_id' if name == 'project_workspaces' else 'id'
                registry[name] = [dict(row) for row in db.execute('select * from '+name+' order by '+order+' limit 10001')]
    except sqlite3.Error:
        raise MigrationError('REGISTRY_SOURCE_INVALID') from None
    _require(paired._fingerprint(source) == (before, identity), 'REGISTRY_SOURCE_CHANGED')
    return report, _registry(registry), before['sha256']


def export_package(backup_root, manifest_sha256, destination):
    backup = paired._directory(backup_root)
    destination = Path(destination).absolute()
    _require(not destination.is_relative_to(backup), 'REGISTRY_SOURCE_OUTPUT_OVERLAP')
    paired._directory(destination.parent)
    _, registry, source_sha256 = _source_registry(backup, manifest_sha256)
    value = _package(dict(format=FORMAT, schemaVersion=1, sourceManifestSha256=manifest_sha256,
                          sourceRegistrySha256=source_sha256, registry=registry))
    raw = paired._canonical(value) + b'\n'
    _require(len(raw) <= MAX_PACKAGE_BYTES, 'REGISTRY_BUDGET_EXCEEDED')
    with os.fdopen(paired._open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL), 'wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    paired._sync(destination.parent)
    return {'packageSha256': hashlib.sha256(raw).hexdigest(), 'sourceManifestSha256': manifest_sha256,
            'sourceRegistrySha256': source_sha256, 'workspaces': len(registry['project_workspaces']),
            'status': 'exported_metadata_only'}


def load_package(path, expected_sha256):
    _require(paired._sha(expected_sha256), 'REGISTRY_PACKAGE_SHA_REQUIRED')
    path = Path(path).absolute(); paired._directory(path.parent)
    with os.fdopen(paired._open(path, os.O_RDONLY), 'rb') as stream:
        info = os.fstat(stream.fileno())
        _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'REGISTRY_PACKAGE_INVALID')
        _require(info.st_size <= MAX_PACKAGE_BYTES, 'REGISTRY_BUDGET_EXCEEDED')
        raw = stream.read(MAX_PACKAGE_BYTES + 1)
    _require(len(raw) <= MAX_PACKAGE_BYTES and hashlib.sha256(raw).hexdigest() == expected_sha256,
             'REGISTRY_PACKAGE_CHANGED')
    def pairs(items):
        value = {}
        for key, item in items:
            _require(key not in value, 'REGISTRY_PACKAGE_INVALID'); value[key] = item
        return value
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError):
        raise MigrationError('REGISTRY_PACKAGE_INVALID') from None
    return _package(value)


DDL = '''
create schema ontovis_registry_stage_v1;
create table ontovis_registry_stage_v1.registry_meta (
 id integer primary key check(id=1), schema_version integer not null check(schema_version=1),
 connection_id text not null unique);
create table ontovis_registry_stage_v1.project_workspaces (
 workspace_id uuid primary key, ontobase_connection_id text not null references ontovis_registry_stage_v1.registry_meta(connection_id),
 project_code text not null, storage_key text not null unique, legacy_context_id uuid,
 state text not null check(state in ('preparing','ready','blocked')), block_reason text, created_at text not null,
 unique(ontobase_connection_id,project_code));
create table ontovis_registry_stage_v1.shared_model_store (
 id integer primary key check(id=1), connection_id text not null references ontovis_registry_stage_v1.registry_meta(connection_id),
 scope_version integer not null check(scope_version=1));
create table ontovis_registry_stage_v1.migration_receipt (
 id integer primary key check(id=1), request_id uuid not null unique, package_sha256 text not null,
 registry_digest text not null, source_manifest_sha256 text not null, source_registry_sha256 text not null,
 staged_at text not null);
'''


def _target_guard(cur):
    cur.execute('select current_database()')
    name = cur.fetchone()[0]
    _require(name == 'ontovis' or name.startswith('ontovis_'), 'REGISTRY_DEDICATED_DATABASE_REQUIRED')


def _write_rows(cur, registry):
    for name, columns in COLUMNS.items():
        for row in registry[name]:
            cur.execute('insert into '+SCHEMA+'.'+name+' ('+','.join(columns)+') values ('
                        + ','.join(['%s']*len(columns))+')', tuple(row[column] for column in columns))


def _read_rows(cur):
    result = {}
    for name, columns in COLUMNS.items():
        select = [column+'::text as '+column if column in ('workspace_id','legacy_context_id') else column for column in columns]
        cur.execute('select '+','.join(select)+' from '+SCHEMA+'.'+name+' order by '
                    + ('workspace_id' if name == 'project_workspaces' else 'id'))
        result[name] = [dict(zip(columns, row)) for row in cur.fetchall()]
    return _registry(result)


def _verified(cur, value, package_sha256, request_id, *, capture_rows=False):
    cur.execute('select table_name from information_schema.tables where table_schema=%s', (SCHEMA,))
    _require({row[0] for row in cur.fetchall()} == set(COLUMNS) | {'migration_receipt'}, 'REGISTRY_TARGET_PROFILE_CHANGED')
    cur.execute('select request_id::text,package_sha256,registry_digest,source_manifest_sha256,source_registry_sha256,staged_at from '
                +SCHEMA+'.migration_receipt where id=1')
    row = cur.fetchone()
    _require(row is not None, 'REGISTRY_TARGET_OCCUPIED')
    _require(row[0] == request_id, 'REGISTRY_TARGET_OCCUPIED')
    _require(row[1] == package_sha256, 'REGISTRY_REQUEST_CONFLICT')
    registry = _read_rows(cur)
    _require(registry == value['registry'] and paired._digest(registry) == row[2]
             and row[3] == value['sourceManifestSha256'] and row[4] == value['sourceRegistrySha256'], 'REGISTRY_TARGET_CHANGED')
    receipt = {'status': 'staged_metadata_only', 'stageReceiptId': row[0], 'packageSha256': row[1],
            'registryDigest': row[2], 'sourceManifestSha256': row[3], 'sourceRegistrySha256': row[4],
            'stagedAt': row[5], 'tables': {name: len(rows) for name, rows in registry.items()},
            'runtimeActivated': False, 'resourceFilesCopied': False, 'engineeringAuthorityChanged': False}
    return (receipt, registry) if capture_rows else receipt


def postgres_package(path, package_sha256, request_id, database_url, *, verify_only=False):
    return _postgres_result(path, package_sha256, request_id, database_url, verify_only=verify_only)


def _postgres_result(path, package_sha256, request_id, database_url, *, verify_only=False, capture_rows=False):
    _require(not capture_rows or verify_only, 'REGISTRY_READ_ONLY_REQUIRED')
    value = load_package(path, package_sha256)
    _require(_uuid(request_id), 'REGISTRY_REQUEST_ID_REQUIRED')
    _require(type(database_url) is str and database_url, 'REGISTRY_DATABASE_CONFIG_REQUIRED')
    try:
        import psycopg
    except ImportError:
        raise MigrationError('REGISTRY_POSTGRES_DRIVER_REQUIRED') from None
    try:
        with psycopg.connect(database_url, connect_timeout=5) as connection:
            with connection.transaction(), connection.cursor() as cur:
                if verify_only:
                    cur.execute('set transaction isolation level repeatable read, read only')
                cur.execute("set local statement_timeout='15s'")
                cur.execute("set local lock_timeout='5s'")
                _target_guard(cur)
                if not verify_only:
                    cur.execute('select pg_advisory_xact_lock(%s)', (LOCK_KEY,))
                cur.execute('select to_regnamespace(%s)', (SCHEMA,))
                exists = cur.fetchone()[0] is not None
                if not exists:
                    _require(not verify_only, 'REGISTRY_TARGET_EMPTY')
                    cur.execute(DDL)
                    _write_rows(cur, value['registry'])
                    cur.execute('insert into '+SCHEMA+'.migration_receipt values (1,%s,%s,%s,%s,%s,%s)',
                                (request_id, package_sha256, paired._digest(value['registry']), value['sourceManifestSha256'],
                                 value['sourceRegistrySha256'], datetime.now(timezone.utc).isoformat()))
                if capture_rows:
                    return _verified(cur, value, package_sha256, request_id, capture_rows=True)
                return _verified(cur, value, package_sha256, request_id)
    except MigrationError:
        raise
    except psycopg.Error as error:
        raise MigrationError('REGISTRY_TARGET_BUSY' if error.sqlstate in ('55P03','57014') else 'REGISTRY_POSTGRES_UNAVAILABLE') from None


def _sqlite_registry(path, registry):
    """Rebuild just the fixed registry in a newly owned restore, never the source."""
    _registry(registry)
    os.close(paired._open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL))
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript('''
            create table registry_meta (
                id integer primary key check(id=1), schema_version integer not null,
                connection_id text not null);
            create table project_workspaces (
                workspace_id text primary key, ontobase_connection_id text not null,
                project_code text not null, storage_key text not null unique,
                legacy_context_id text, state text not null check(state in ('preparing','ready','blocked')),
                block_reason text, created_at text not null,
                unique(ontobase_connection_id,project_code));
            create table shared_model_store (
                id integer primary key check(id=1), connection_id text not null, scope_version integer not null);
        ''')
        for name, columns in COLUMNS.items():
            db.executemany('insert into '+name+' ('+','.join(columns)+') values ('
                           + ','.join(['?']*len(columns))+')',
                           [tuple(row[column] for column in columns) for row in registry[name]])
        db.row_factory = sqlite3.Row
        restored = {name: [dict(row) for row in db.execute('select * from '+name+' order by '
                    + ('workspace_id' if name == 'project_workspaces' else 'id'))] for name in COLUMNS}
        _require(restored == registry and [tuple(row) for row in db.execute('pragma quick_check')] == [('ok',)],
                 'REGISTRY_RESTORE_MISMATCH')
    with os.fdopen(paired._open(path, os.O_RDONLY), 'rb') as stream:
        os.fsync(stream.fileno())


def restore_staged_new(backup_root, manifest_sha256, path, package_sha256, request_id, database_url,
                       destination, *, service_stopped=False):
    """Recover an immutable staging snapshot into a full, new SQLite backup."""
    paired._require(service_stopped, 'SERVICE_MUST_BE_STOPPED')
    value = load_package(path, package_sha256)
    packet_before = paired._fingerprint(Path(path).absolute())
    backup = paired._directory(backup_root)
    target = paired._destination(destination, (backup,))
    _require(value['sourceManifestSha256'] == manifest_sha256, 'REGISTRY_PACKAGE_SOURCE_MISMATCH')
    before = paired._inventory(backup)
    report, registry, source_sha256 = _source_registry(backup, manifest_sha256)
    _require(source_sha256 == value['sourceRegistrySha256'] and registry == value['registry'],
             'REGISTRY_PACKAGE_SOURCE_MISMATCH')
    staged, snapshot = _postgres_result(path, package_sha256, request_id, database_url,
                                       verify_only=True, capture_rows=True)
    copied = backups.restore_new(backup, target, manifest_sha256, service_stopped=True)
    manifest = target / 'manifest.json'
    # A partial reconstruction must not retain the copied source manifest.
    manifest.unlink()
    try:
        candidate = target / 'project-spaces/.registry-from-postgres.sqlite3'
        try:
            _sqlite_registry(candidate, snapshot)
        except sqlite3.Error:
            raise MigrationError('REGISTRY_RESTORE_FAILED') from None
        os.replace(candidate, target / 'project-spaces/registry.sqlite3')
        paired._sync(target / 'project-spaces')
        expected = copy.deepcopy(report)
        expected['projects']['registry.sqlite3'] = paired._fingerprint(target / 'project-spaces/registry.sqlite3')[0]
        actual, _ = backups._capture(target / 'project-spaces',
            target / 'workbench-library' if report['legacy'] or report.get('sharedModels') else None,
            target / 'workbench-model' if report['legacy'] else None)
        _require(actual == expected, 'REGISTRY_RESTORE_MISMATCH')
        _require(paired._inventory(backup) == before, 'REGISTRY_SOURCE_CHANGED')
        _require(paired._fingerprint(Path(path).absolute()) == packet_before, 'REGISTRY_PACKAGE_CHANGED')
        raw = paired._canonical(actual)
        with os.fdopen(paired._open(manifest, os.O_WRONLY | os.O_CREAT | os.O_EXCL), 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        paired._sync(target)
        digest = hashlib.sha256(raw).hexdigest()
        _require(backups.verify(target, digest) == expected, 'REGISTRY_RESTORE_MISMATCH')
    except BaseException:
        manifest.unlink(missing_ok=True)
        raise
    return {'status': 'restored_sqlite_from_staged_metadata', 'manifestSha256': digest,
            'sourceManifestSha256': manifest_sha256, 'sourceRegistrySha256': source_sha256,
            'restoredRegistrySha256': expected['projects']['registry.sqlite3']['sha256'],
            'packageSha256': package_sha256, 'registryDigest': paired._digest(snapshot),
            'stageReceiptId': staged['stageReceiptId'], 'spaces': copied['spaces'], 'fileCount': copied['fileCount'],
            'registryRebuiltFromPostgres': True, 'sourceBackupUnchanged': True, 'postgresWrites': 0,
            'resourceFilesCopied': True, 'runtimeActivated': False, 'engineeringAuthorityChanged': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('export', 'stage', 'verify', 'restore-new'))
    parser.add_argument('--backup', type=Path); parser.add_argument('--manifest-sha256')
    parser.add_argument('--package', type=Path, required=True); parser.add_argument('--package-sha256')
    parser.add_argument('--request-id')
    parser.add_argument('--destination', type=Path)
    parser.add_argument('--service-stopped', action='store_true')
    args = parser.parse_args()
    try:
        if args.action == 'export':
            result = export_package(args.backup, args.manifest_sha256, args.package)
        elif args.action == 'restore-new':
            result = restore_staged_new(args.backup, args.manifest_sha256, args.package, args.package_sha256,
                args.request_id, os.environ.get('ONTOVIS_REGISTRY_STAGE_DSN'), args.destination,
                service_stopped=args.service_stopped)
        else:
            result = postgres_package(args.package, args.package_sha256, args.request_id,
                                      os.environ.get('ONTOVIS_REGISTRY_STAGE_DSN'), verify_only=args.action == 'verify')
        print(json.dumps(result, ensure_ascii=False))
    except (MigrationError, paired.BackupError) as error:
        print(error.code, file=sys.stderr); raise SystemExit(2) from None
    except (OSError, TypeError, ValueError):
        print('REGISTRY_INPUT_UNAVAILABLE', file=sys.stderr); raise SystemExit(2) from None


if __name__ == '__main__':
    main()
