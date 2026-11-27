"""Concrete PostgreSQL project registry; project libraries still use local SQLite.

Provisioning is offline. Runtime never creates schemas or falls back to SQLite.
One session lock protects the registry and its paired local stores until close.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
from threading import RLock
from uuid import UUID, uuid4

from .authority import PreviewError
from .project_workspaces import ProjectWorkspaces, text

SCHEMA = 'ontovis_registry_runtime_v1'
MARKER = 'registry-postgres.json'
FORMAT = 'ontovis-postgres-registry-runtime-v1'
MAX_WORKSPACES = 10000
LOCK_KEY = int.from_bytes(hashlib.sha256(SCHEMA.encode()).digest()[:8], 'big', signed=True)
COLUMNS = {
    'registry_meta': ('id', 'schema_version', 'connection_id'),
    'project_workspaces': ('workspace_id', 'ontobase_connection_id', 'project_code', 'storage_key',
                           'legacy_context_id', 'state', 'block_reason', 'created_at'),
    'shared_model_store': ('id', 'connection_id', 'scope_version'),
    'runtime_binding': ('id', 'store_id', 'root_identity', 'source_manifest_sha256'),
}
DDL = f'''
create schema {SCHEMA};
create table {SCHEMA}.registry_meta (
    id integer primary key check(id=1), schema_version integer not null check(schema_version=1),
    connection_id text not null unique);
create table {SCHEMA}.project_workspaces (
    workspace_id uuid primary key, ontobase_connection_id text not null references {SCHEMA}.registry_meta(connection_id),
    project_code text not null, storage_key text not null unique, legacy_context_id uuid,
    state text not null check(state in ('preparing','ready','blocked')), block_reason text, created_at text not null,
    unique(ontobase_connection_id,project_code));
create table {SCHEMA}.shared_model_store (
    id integer primary key check(id=1), connection_id text not null references {SCHEMA}.registry_meta(connection_id),
    scope_version integer not null check(scope_version=1));
create table {SCHEMA}.runtime_binding (
    id integer primary key check(id=1), store_id uuid not null unique,
    root_identity text not null, source_manifest_sha256 text not null);
'''


def require(condition, code):
    if not condition:
        raise PreviewError(409, code)


def root_identity(projects, library, model=None):
    values = []
    for path in ((projects, library, model) if model is not None else (projects, library)):
        require(path is not None, 'REGISTRY_PAIRED_LIBRARY_REQUIRED')
        path = Path(path).absolute()
        require(not any(p.is_symlink() for p in (path, *path.parents)), 'REGISTRY_ROOT_INVALID')
        info = path.stat()
        require(stat.S_ISDIR(info.st_mode), 'REGISTRY_ROOT_INVALID')
        values.append([str(path), info.st_dev, info.st_ino])
    return hashlib.sha256(json.dumps(values, separators=(',', ':')).encode()).hexdigest()


def read_marker(root):
    path = Path(root) / MARKER
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= 1024,
                    'REGISTRY_MARKER_INVALID')
            value = json.loads(stream.read(1025).decode('utf-8'))
        require(type(value) is dict and set(value) == {'format', 'storeId', 'connectionId'}
                and value['format'] == FORMAT and str(UUID(value['storeId'])) == value['storeId'],
                'REGISTRY_MARKER_INVALID')
        text(value['connectionId'])
        return value
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise PreviewError(409, 'REGISTRY_MARKER_INVALID') from None


class RegistryConnection:
    """The same connection holds ownership and performs every registry operation.

    Losing it fails requests closed; reconnecting behind the ownership lock would
    allow a second process to start while the old process still writes files.
    """
    def __init__(self, database_url):
        require(isinstance(database_url, str) and database_url, 'REGISTRY_DATABASE_CONFIG_REQUIRED')
        try:
            import psycopg
        except ImportError:
            raise PreviewError(503, 'REGISTRY_POSTGRES_DRIVER_REQUIRED') from None
        self.driver = psycopg
        self.db = None
        self.lock = RLock()
        try:
            self.db = psycopg.connect(database_url, connect_timeout=5, autocommit=True)
            self.db.execute("set statement_timeout='15s'")
            self.db.execute("set lock_timeout='5s'")
            name = self.db.execute('select current_database()').fetchone()[0]
            require(name == 'ontovis' or name.startswith('ontovis_'), 'REGISTRY_DEDICATED_DATABASE_REQUIRED')
            require(self.db.execute('select pg_try_advisory_lock(%s)', (LOCK_KEY,)).fetchone()[0],
                    'REGISTRY_IN_USE')
        except BaseException as error:
            self.close()
            if isinstance(error, psycopg.Error):
                raise PreviewError(503, 'REGISTRY_POSTGRES_UNAVAILABLE') from None
            raise

    @contextmanager
    def transaction(self, *, readonly=False):
        with self.lock:
            require(self.db is not None and not self.db.closed, 'REGISTRY_CONNECTION_CLOSED')
            try:
                with self.db.transaction(), self.db.cursor() as cursor:
                    if readonly:
                        cursor.execute('set transaction isolation level repeatable read, read only')
                    yield cursor
            except self.driver.Error as error:
                code = 'REGISTRY_BUSY' if error.sqlstate in ('55P03', '57014') else 'REGISTRY_POSTGRES_UNAVAILABLE'
                raise PreviewError(503, code) from None

    def close(self):
        with self.lock:
            if self.db is not None:
                self.db.close()


def profile(cursor):
    cursor.execute('select table_name,column_name from information_schema.columns where table_schema=%s order by table_name,ordinal_position', (SCHEMA,))
    actual = {}
    for table, column in cursor.fetchall():
        actual.setdefault(table, []).append(column)
    require(actual == {name: list(columns) for name, columns in COLUMNS.items()}, 'REGISTRY_PROFILE_CHANGED')


def rows(cursor):
    result = {}
    versions = {}
    for name, columns in COLUMNS.items():
        select = [column+'::text' if column in ('workspace_id', 'legacy_context_id', 'store_id') else column for column in columns]
        cursor.execute('select '+','.join(select)+',xmin::text from '+SCHEMA+'.'+name+' order by '
                       + ('workspace_id' if name == 'project_workspaces' else 'id'))
        values = cursor.fetchall()
        result[name] = [dict(zip(columns, row[:-1])) for row in values]
        versions[name] = [row[-1] for row in values]
    return result, versions


WORKSPACE_SELECT = ','.join(c+'::text' if c in ('workspace_id', 'legacy_context_id') else c
                            for c in COLUMNS['project_workspaces']) + ',xmin::text'


def workspace_row(value):
    return dict(zip((*COLUMNS['project_workspaces'], 'registry_revision'), value)) if value else None


class PostgresProjectWorkspaces(ProjectWorkspaces):
    def __init__(self, root, connection_id, *, database_url, legacy_root=None, legacy_project=None, legacy_context=None,
                 model_root=None):
        identity = root_identity(root, legacy_root, model_root)
        self._storage(root, connection_id, legacy_root)
        marker = read_marker(self.root)
        require(marker['connectionId'] == self.connection_id, 'REGISTRY_SCOPE_MISMATCH')
        require(not (self.root / 'registry.sqlite3').exists(), 'REGISTRY_AMBIGUOUS_BACKEND')
        self.connection = RegistryConnection(database_url)
        try:
            with self.connection.transaction(readonly=True) as cursor:
                profile(cursor)
                cursor.execute('select store_id::text,root_identity from '+SCHEMA+'.runtime_binding where id=1')
                require(cursor.fetchone() == (marker['storeId'], identity),
                        'REGISTRY_ROOT_MISMATCH')
                cursor.execute('select schema_version,connection_id from '+SCHEMA+'.registry_meta')
                require(cursor.fetchall() == [(1, self.connection_id)], 'REGISTRY_SCOPE_MISMATCH')
            self.ensure_shared_model_store()
            # A configured legacy project must already have been migrated.
            if legacy_project:
                workspace = self.lookup(legacy_project)
                require(workspace and workspace['storage_key'] == 'legacy'
                        and workspace['legacy_context_id'] == legacy_context, 'REGISTRY_LEGACY_MISMATCH')
                self.validate_existing(workspace)
        except BaseException:
            self.close()
            raise

    def connect(self):
        raise RuntimeError('REGISTRY_SQLITE_CONNECTION_UNAVAILABLE')

    def ensure_shared_model_store(self):
        with self.connection.transaction(readonly=True) as cursor:
            cursor.execute('select connection_id,scope_version from '+SCHEMA+'.shared_model_store')
            require(cursor.fetchall() == [(self.connection_id, 1)], 'REGISTRY_SCOPE_MISMATCH')

    def lookup(self, project_code):
        with self.connection.transaction(readonly=True) as cursor:
            cursor.execute('select '+WORKSPACE_SELECT+' from '+SCHEMA+'.project_workspaces '
                           'where ontobase_connection_id=%s and project_code=%s', (self.connection_id, text(project_code)))
            return workspace_row(cursor.fetchone())

    def prepare(self, project_code, *, storage_key=None, legacy_context=None):
        project_code = text(project_code)
        # Legacy roots can only enter via the verified offline migration.
        require(storage_key is None and legacy_context is None, 'REGISTRY_OFFLINE_LEGACY_REQUIRED')
        identifier = str(uuid4())
        with self.lock, self.connection.transaction() as cursor:
            cursor.execute('select '+WORKSPACE_SELECT+' from '+SCHEMA+'.project_workspaces '
                           'where ontobase_connection_id=%s and project_code=%s', (self.connection_id, project_code))
            existing = cursor.fetchone()
            if existing:
                return workspace_row(existing)
            cursor.execute('select count(*) from '+SCHEMA+'.project_workspaces')
            require(cursor.fetchone()[0] < MAX_WORKSPACES, 'REGISTRY_CAPACITY_REACHED')
            cursor.execute('insert into '+SCHEMA+'.project_workspaces values(%s,%s,%s,%s,null,\'preparing\',null,%s) '
                           'on conflict(ontobase_connection_id,project_code) do nothing',
                           (identifier, self.connection_id, project_code, identifier, datetime.now(timezone.utc).isoformat()))
            cursor.execute('select '+WORKSPACE_SELECT+' from '+SCHEMA+'.project_workspaces '
                           'where ontobase_connection_id=%s and project_code=%s', (self.connection_id, project_code))
            return workspace_row(cursor.fetchone())

    def mark(self, workspace, state, reason=None):
        require(state in ('preparing', 'ready', 'blocked') and (reason is None or isinstance(reason, str) and len(reason) <= 2000),
                'REGISTRY_STATE_INVALID')
        with self.lock, self.connection.transaction() as cursor:
            cursor.execute('select '+WORKSPACE_SELECT+' from '+SCHEMA+'.project_workspaces '
                           'where workspace_id=%s and ontobase_connection_id=%s for update',
                           (workspace['workspace_id'], self.connection_id))
            current = workspace_row(cursor.fetchone())
            require(current == workspace, 'REGISTRY_REVISION_CHANGED')
            if (state, reason) != (current['state'], current['block_reason']):
                cursor.execute('update '+SCHEMA+'.project_workspaces set state=%s,block_reason=%s '
                               'where workspace_id=%s and xmin::text=%s returning '+WORKSPACE_SELECT,
                               (state, reason, workspace['workspace_id'], workspace['registry_revision']))
                current = workspace_row(cursor.fetchone())
                require(current is not None, 'REGISTRY_REVISION_CHANGED')
        workspace.update(current)

    def close(self):
        self.connection.close()
