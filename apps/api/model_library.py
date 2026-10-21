"""Private ONTOVis model versions and demonstration links; never an OntoBase DB."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from threading import BoundedSemaphore
from uuid import UUID, uuid4
from .authority import PreviewError
from .model_validation import MAX_BYTES


class ModelLibrary:
    def __init__(self, root: Path, project_code: str, context_id: str):
        if root.is_symlink(): raise ValueError('Private library must be a real directory')
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root = root.resolve()
        for name in ('files','temporary'): (self.root/name).mkdir(mode=0o700, exist_ok=True)
        if any((self.root/name).is_symlink() for name in ('files','temporary','library.sqlite3')):
            raise ValueError('Private library paths must not be symlinks')
        self.slots = BoundedSemaphore(1)
        with self.connect() as db:
            db.executescript('''
                create table if not exists library (id integer primary key check(id=1), revision integer not null, project_code text not null, context_id text not null);
                create table if not exists versions (
                    id text primary key, request_id text not null unique, actor text not null,
                    name text not null, source_note text not null, sha256 text not null,
                    bytes integer not null, created_at text not null, revision integer not null,
                    components text not null, report text not null);
                create table if not exists bindings (
                    version_id text not null references versions(id), entity_uid text not null,
                    entity_revision text not null, hierarchy_revision text not null,
                    component_key text not null, primary key(version_id, entity_uid),
                    unique(version_id, component_key));
                create table if not exists audit (
                    id integer primary key, request_id text not null unique, actor text not null,
                    action text not null, version_id text not null, payload text not null, created_at text not null);
            ''')
            db.execute('insert or ignore into library values (1,0,?,?)',(project_code,context_id))
            scope=db.execute('select project_code,context_id from library where id=1').fetchone()
            if tuple(scope)!=(project_code,context_id): raise ValueError('Library belongs to a different project or equipment context')
        os.chmod(self.root/'library.sqlite3',0o600)
        for path in (self.root/'temporary').glob('upload-*.glb'):
            if path.is_file() and not path.is_symlink(): path.unlink()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root/'library.sqlite3', timeout=3)
        db.row_factory = sqlite3.Row
        db.execute('pragma foreign_keys=on')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback(); raise
        finally: db.close()

    @staticmethod
    def revision(db): return 'library:' + str(db.execute('select revision from library where id=1').fetchone()[0])

    def listing(self):
        with self.connect() as db:
            rows = db.execute('select v.*, (select count(*) from bindings b where b.version_id=v.id) as binding_count from versions v order by created_at desc').fetchall()
            return {'libraryRevision':self.revision(db), 'items':[self.public(row) for row in rows],
                    'maxBytes':MAX_BYTES, 'maxModels':20}

    @staticmethod
    def public(row):
        return {'versionId':row['id'], 'displayName':row['name'], 'sourceNote':row['source_note'],
                'sha256':row['sha256'], 'bytes':row['bytes'], 'createdAt':row['created_at'],
                'modelRevision':row['revision'], 'state':'ready', 'report':json.loads(row['report']),
                'bindingCount':row['binding_count'] if 'binding_count' in row.keys() else 0}

    def version(self, identifier):
        try: identifier = str(UUID(identifier))
        except (ValueError, TypeError, AttributeError): raise PreviewError(422,'INVALID_REQUEST') from None
        with self.connect() as db:
            row = db.execute('select * from versions where id=?',(identifier,)).fetchone()
            if not row: raise PreviewError(404,'MODEL_NOT_FOUND')
            value = self.public(row)
            value['components'] = json.loads(row['components'])
            value['bindings'] = [dict(row) for row in db.execute('select * from bindings where version_id=? order by entity_uid',(identifier,))]
            return value

    def content(self, version):
        path = self.root/'files'/(version['versionId']+'.glb')
        if path.is_symlink() or not path.is_file() or path.stat().st_size != version['bytes']: raise PreviewError(409,'MODEL_CHANGED')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != version['sha256']: raise PreviewError(409,'MODEL_CHANGED')
        return data

    @staticmethod
    def upload_metadata(body):
        if set(body) != {'expectedSessionRevision','expectedLibraryRevision','clientRequestId','displayName','sourceNote','rightsDeclared'}:
            raise PreviewError(422,'INVALID_REQUEST')
        try: UUID(body['clientRequestId'])
        except (TypeError, ValueError, AttributeError): raise PreviewError(422,'INVALID_REQUEST') from None
        for key,limit in (('displayName',200),('sourceNote',2000),('expectedLibraryRevision',100)):
            if not isinstance(body[key],str) or not 0 < len(body[key].strip()) <= limit or any(ord(c)<32 for c in body[key]): raise PreviewError(422,'INVALID_REQUEST')
        if body['rightsDeclared'] is not True: raise PreviewError(422,'MODEL_RIGHTS_REQUIRED')

    def process(self, path):
        try:
            result = subprocess.run([sys.executable,'-m','apps.api.model_validation',str(path)],
                cwd=Path(__file__).resolve().parents[2], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=12)
        except subprocess.TimeoutExpired: raise PreviewError(422,'MODEL_LIMIT_EXCEEDED') from None
        if len(result.stdout)>512*1024 or result.returncode not in (0,2): raise PreviewError(422,'MODEL_LIMIT_EXCEEDED')
        try: value = json.loads(result.stdout)
        except (ValueError,UnicodeError): raise PreviewError(422,'INVALID_MODEL') from None
        if result.returncode: raise PreviewError(422,value.get('code','INVALID_MODEL'))
        return value

    def save_upload(self, path, body, actor, result, authorize):
        self.upload_metadata(body)
        identifier = str(uuid4()); target = self.root/'files'/(identifier+'.glb')
        with self.connect() as db:
            db.execute('begin immediate')
            prior = db.execute('select * from versions where request_id=?',(body['clientRequestId'],)).fetchone()
            if prior:
                if any(prior[key] != value for key,value in (('actor',actor),('sha256',result['sha256']),('name',body['displayName']),('source_note',body['sourceNote']))): raise PreviewError(409,'REQUEST_CONFLICT')
                authorize(); return self.public(prior)
            if self.revision(db) != body['expectedLibraryRevision']: raise PreviewError(409,'MODEL_LIBRARY_CHANGED')
            size = path.stat().st_size
            count,total = db.execute('select count(*),coalesce(sum(bytes),0) from versions').fetchone()
            total=max(total,sum(file.stat().st_size for file in (self.root/'files').glob('*.glb') if file.is_file()))
            if count>=20 or total+size>200*1024*1024: raise PreviewError(413,'MODEL_LIBRARY_FULL')
            authorize()
            now = datetime.now(timezone.utc).isoformat()
            try:
                with path.open('rb') as file: os.fsync(file.fileno())
                os.replace(path,target); os.chmod(target,0o600)
                directory = os.open(target.parent,os.O_RDONLY)
                try: os.fsync(directory)
                finally: os.close(directory)
                db.execute('insert into versions values (?,?,?,?,?,?,?,?,?,?,?)',
                    (identifier,body['clientRequestId'],actor,body['displayName'],body['sourceNote'],result['sha256'],size,now,1,json.dumps(result['components']),json.dumps(result['report'])))
                db.execute('insert into audit(request_id,actor,action,version_id,payload,created_at) values (?,?,?,?,?,?)',
                    (body['clientRequestId'],actor,'model_uploaded',identifier,json.dumps({'sha256':result['sha256'],'rightsDeclared':True}),now))
                db.execute('update library set revision=revision+1 where id=1')
                authorize()
                db.commit()
            except BaseException:
                if db.in_transaction:
                    db.rollback(); target.unlink(missing_ok=True)
                raise
        return self.version(identifier)

    def bind(self, body, actor, authorize):
        allowed = {'modelVersionId','componentKey','entityUid','expectedEntityRevision','expectedHierarchyRevision','expectedModelRevision','clientRequestId'}
        if set(body)!=allowed or type(body['expectedModelRevision']) is not int: raise PreviewError(422,'INVALID_REQUEST')
        for key in ('componentKey','entityUid','expectedEntityRevision','expectedHierarchyRevision'):
            if not isinstance(body[key],str) or not 0<len(body[key])<=512: raise PreviewError(422,'INVALID_REQUEST')
        try: UUID(body['clientRequestId'])
        except (ValueError,TypeError,AttributeError): raise PreviewError(422,'INVALID_REQUEST') from None
        value = self.version(body['modelVersionId'])
        if not any(row['componentKey']==body['componentKey'] for row in value['components']): raise PreviewError(422,'INVALID_COMPONENT')
        canonical = json.dumps(body,sort_keys=True)
        with self.connect() as db:
            db.execute('begin immediate')
            prior = db.execute('select * from audit where request_id=?',(body['clientRequestId'],)).fetchone()
            if prior:
                if prior['actor']!=actor or prior['action']!='binding_saved' or prior['payload']!=canonical: raise PreviewError(409,'REQUEST_CONFLICT')
                authorize(); return
            row = db.execute('select revision from versions where id=?',(value['versionId'],)).fetchone()
            if row[0]!=body['expectedModelRevision']: raise PreviewError(409,'MODEL_CHANGED')
            authorize()
            try:
                db.execute('insert into bindings values (?,?,?,?,?) on conflict(version_id,entity_uid) do update set entity_revision=excluded.entity_revision,hierarchy_revision=excluded.hierarchy_revision,component_key=excluded.component_key',
                    (value['versionId'],body['entityUid'],body['expectedEntityRevision'],body['expectedHierarchyRevision'],body['componentKey']))
            except sqlite3.IntegrityError: raise PreviewError(409,'COMPONENT_ALREADY_LINKED') from None
            db.execute('update versions set revision=revision+1 where id=?',(value['versionId'],))
            db.execute('update library set revision=revision+1 where id=1')
            db.execute('insert into audit(request_id,actor,action,version_id,payload,created_at) values (?,?,?,?,?,?)',
                (body['clientRequestId'],actor,'binding_saved',value['versionId'],canonical,datetime.now(timezone.utc).isoformat()))
            authorize()
