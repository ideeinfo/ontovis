"""One connection's project spaces. Source projects and access remain in OntoBase."""
from __future__ import annotations

from contextlib import contextmanager, closing
from datetime import datetime, timezone
from pathlib import Path
import os
import sqlite3
from threading import RLock
from uuid import UUID, uuid4

from .authority import PreviewError


def text(value):
    if (not isinstance(value, str) or not 0 < len(value) <= 200 or value != value.strip()
            or any(ord(ch) < 32 for ch in value)):
        raise PreviewError(422, 'INVALID_REQUEST')
    return value


def real_directory(value):
    path = Path(value).absolute()
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ValueError('Project storage must not contain symlinks')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path.resolve()


class ProjectWorkspaces:
    def __init__(self, root, connection_id, *, legacy_root=None, legacy_project=None, legacy_context=None):
        self.root = real_directory(root)
        self.connection_id = text(connection_id)
        self.legacy_root = Path(legacy_root).resolve() if legacy_root else None
        if self.legacy_root and (self.root.is_relative_to(self.legacy_root) or self.legacy_root.is_relative_to(self.root)):
            raise ValueError('Project registry and legacy storage must be disjoint')
        self.lock = RLock()
        if (self.root / 'registry.sqlite3').is_symlink():
            raise ValueError('Invalid project registry')
        with self.connect() as db:
            db.executescript('''
                create table if not exists registry_meta (
                    id integer primary key check(id=1), schema_version integer not null,
                    connection_id text not null);
                create table if not exists project_workspaces (
                    workspace_id text primary key, ontobase_connection_id text not null,
                    project_code text not null, storage_key text not null unique,
                    legacy_context_id text, state text not null check(state in ('preparing','ready','blocked')),
                    block_reason text, created_at text not null,
                    unique(ontobase_connection_id,project_code));
            ''')
            db.execute('insert or ignore into registry_meta values(1,1,?)', (self.connection_id,))
            if tuple(db.execute('select schema_version,connection_id from registry_meta').fetchone()) != (1, self.connection_id):
                raise ValueError('Registry belongs to a different connection or schema')
        os.chmod(self.root / 'registry.sqlite3', 0o600)
        if legacy_project and self.legacy_root and (self.legacy_root / 'library.sqlite3').is_file():
            with closing(sqlite3.connect(self.legacy_root / 'library.sqlite3')) as db:
                scope = db.execute('select project_code,context_id from library where id=1').fetchone()
                if scope != (legacy_project, legacy_context):
                    raise ValueError('Legacy project scope does not match the configured source')
            self.prepare(legacy_project, storage_key='legacy', legacy_context=legacy_context)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / 'registry.sqlite3', timeout=5)
        try:
            db.row_factory = sqlite3.Row
            with db:
                yield db
        finally:
            db.close()

    def validate_existing(self, workspace):
        path = self.path(workspace) / 'library.sqlite3'
        if path.is_symlink() or self.path(workspace).is_symlink():
            raise PreviewError(409, 'WORKSPACE_SCOPE_INVALID')
        if not path.exists():
            if workspace['state'] == 'ready':
                raise PreviewError(409, 'WORKSPACE_SCOPE_INVALID')
            return
        db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
        try:
            tables = {row[0] for row in db.execute("select name from sqlite_master where type='table'")}
            if not tables and workspace['state'] == 'preparing':
                return
            scope = db.execute('select project_code,context_id from library where id=1').fetchone()
            if scope is None and workspace['state'] == 'preparing':
                if all(db.execute('select count(*) from "'+name.replace('"','""')+'"').fetchone()[0] == 0
                       for name in tables if not name.startswith('sqlite_')):
                    return
            if scope != (workspace['project_code'], workspace['legacy_context_id']):
                raise PreviewError(409, 'WORKSPACE_SCOPE_INVALID')
            if db.execute("select 1 from sqlite_master where name='workspace_scope'").fetchone():
                expected = (workspace['workspace_id'], self.connection_id, workspace['project_code'])
                if db.execute('select workspace_id,ontobase_connection_id,project_code from workspace_scope where id=1').fetchone() != expected:
                    raise PreviewError(409, 'WORKSPACE_SCOPE_INVALID')
        finally:
            db.close()

    def lookup(self, project_code):
        with self.connect() as db:
            row = db.execute('select * from project_workspaces where ontobase_connection_id=? and project_code=?',
                             (self.connection_id, text(project_code))).fetchone()
            return dict(row) if row else None

    def prepare(self, project_code, *, storage_key=None, legacy_context=None):
        project_code = text(project_code)
        with self.lock, self.connect() as db:
            identifier = str(uuid4())
            db.execute('insert or ignore into project_workspaces values(?,?,?,?,?,\'preparing\',null,?)',
                       (identifier, self.connection_id, project_code, storage_key or identifier,
                        legacy_context, datetime.now(timezone.utc).isoformat()))
        return self.lookup(project_code)

    def path(self, workspace):
        key = workspace['storage_key']
        if key == 'legacy' and self.legacy_root is not None:
            return self.legacy_root
        if str(UUID(key)) != key:
            raise PreviewError(409, 'WORKSPACE_SCOPE_INVALID')
        return self.root / 'libraries' / key

    def mark(self, workspace, state, reason=None):
        with self.connect() as db:
            db.execute('update project_workspaces set state=?,block_reason=? where workspace_id=?',
                       (state, reason, workspace['workspace_id']))

    def bind(self, workspace, library):
        """Backfill only scene ownership. Retained snapshots and business revisions stay intact."""
        if workspace['state'] == 'blocked':
            raise PreviewError(409, 'WORKSPACE_SCOPE_INVALID')
        expected = (workspace['workspace_id'], self.connection_id, workspace['project_code'])
        with library.connect() as db:
            db.execute('begin immediate')
            db.execute('''create table if not exists workspace_scope (
                id integer primary key check(id=1), workspace_id text not null unique,
                ontobase_connection_id text not null, project_code text not null,
                scope_version integer not null, unique(workspace_id,project_code))''')
            row = db.execute('select workspace_id,ontobase_connection_id,project_code from workspace_scope where id=1').fetchone()
            if row and tuple(row) != expected:
                raise PreviewError(409, 'WORKSPACE_SCOPE_INVALID')
            if db.execute('select 1 from scenes where project_code!=? limit 1', (workspace['project_code'],)).fetchone():
                raise PreviewError(409, 'WORKSPACE_SCOPE_INVALID')
            db.execute('insert or ignore into workspace_scope values(1,?,?,?,1)', expected)
            if 'workspace_id' not in {r[1] for r in db.execute('pragma table_info(scenes)')}:
                db.execute('alter table scenes add column workspace_id text references workspace_scope(workspace_id)')
            db.execute('update scenes set workspace_id=? where workspace_id is null', (expected[0],))
            if db.execute('select 1 from scenes where workspace_id!=? limit 1', (expected[0],)).fetchone():
                raise PreviewError(409, 'WORKSPACE_SCOPE_INVALID')
            # Triggers enforce the compound scope and NOT NULL on upgraded SQLite tables.
            for operation in ('insert', 'update'):
                db.execute(f'''create trigger if not exists scene_workspace_{operation}
                    before {operation} on scenes when new.workspace_id is null or not exists (
                        select 1 from workspace_scope where id=1 and workspace_id=new.workspace_id
                        and project_code=new.project_code)
                    begin select raise(abort,'scene workspace scope mismatch'); end''')
            if db.execute('pragma foreign_key_check').fetchone():
                raise PreviewError(409, 'WORKSPACE_SCOPE_INVALID')
        library.workspace_scope = expected
        self.mark(workspace, 'ready')

    def summary(self, project_code):
        workspace = self.lookup(project_code)
        if workspace is None:
            return {'workspaceState': 'unconfigured', 'sceneCount': 0}
        path = self.path(workspace) / 'library.sqlite3'
        count = 0
        if workspace['state'] == 'ready' and path.is_file() and not path.is_symlink():
            with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
                count = db.execute('select count(*) from scenes where project_code=?', (project_code,)).fetchone()[0]
        return {'workspaceId': workspace['workspace_id'], 'workspaceState': workspace['state'], 'sceneCount': count}
