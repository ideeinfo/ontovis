"""One bounded private terrain queue in the existing project's SQLite library.

The HTTP caller supplies real-user authorization guards. No credentials/session
identifiers are persisted. This is a single-process test worker, not a scheduler.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import time
from threading import Condition, RLock, Thread
from uuid import UUID, uuid4

from .authority import PreviewError
from .terrain_validation import MAX_BYTES, MAX_PIXELS, MAX_TRIANGLES
from .terrain_coordinates import VERTICAL_DATUMS
from tools.model_probe import strict_json

MAX_VERSIONS = 20
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
DERIVED_RESERVE_BYTES = 16 * 1024 * 1024
MAX_STDOUT_BYTES = 65536
TERMINAL = frozenset(('ready','failed','cancelled'))
BASE_ARTIFACTS = frozenset(('heights.f64','mask.u8','positions.f32','triangles.u32'))
OPTIONAL_ARTIFACTS = frozenset(('cells.u8','cell-mask.u8'))


def _require(value, code='INVALID_REQUEST', status=422):
    if not value: raise PreviewError(status,code)


def _text(value,limit=200):
    _require(isinstance(value,str) and 0<len(value.strip())<=limit and all(ord(c)>=32 for c in value))
    return value.strip()


def _uuid(value):
    try: result=str(UUID(value))
    except (ValueError,TypeError,AttributeError): raise PreviewError(422,'INVALID_REQUEST') from None
    _require(result==value)
    return result


def _sync_directory(path):
    descriptor=os.open(path,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
    try: os.fsync(descriptor)
    finally: os.close(descriptor)


def _now(): return datetime.now(timezone.utc).isoformat()
def _revision(): return 'terrain-job:'+uuid4().hex

def _hash(path):
    value=hashlib.sha256()
    with path.open('rb') as file:
        for chunk in iter(lambda:file.read(65536),b''): value.update(chunk)
    return value.hexdigest()


def _canonical(value): return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)


def _metadata(value):
    required={'clientRequestId','displayName','sourceNote','licenseNote','rightsDeclared','verticalDatum','heightUnit'}
    optional={'expectedSessionRevision','relativeReferenceId','aoi'}
    _require(type(value) is dict and required<=set(value) and set(value)<=required|optional)
    result={key:item for key,item in value.items() if key!='expectedSessionRevision'}
    _uuid(result['clientRequestId'])
    for key,limit in (('displayName',200),('sourceNote',2000),('licenseNote',2000)): result[key]=_text(result[key],limit)
    _require(result['rightsDeclared'] is True,'TERRAIN_RIGHTS_REQUIRED')
    _require(isinstance(result['verticalDatum'],str) and result['verticalDatum'] in VERTICAL_DATUMS,'VERTICAL_DATUM_CONFLICT')
    _require(result['heightUnit']=='m','UNSUPPORTED_TERRAIN')
    if result['verticalDatum']=='UNKNOWN_RELATIVE': _text(result.get('relativeReferenceId'))
    elif 'relativeReferenceId' in result: _require(result['relativeReferenceId'] is None)
    if 'aoi' in result:
        import math
        box=result['aoi']
        _require(type(box) is list and len(box)==4 and all(type(x) in (int,float) and math.isfinite(x) for x in box))
        _require(-180<=box[0]<box[2]<=180 and -80<=box[1]<box[3]<=84)
    return result


class TerrainLibrary:
    """Authorization guards must recheck current session/member/admin as needed.

    Do not call this library while holding a service-wide session mutex: its
    worker invokes the same guard before processing and at the commit boundary.
    max_queue bounds all unfinished uploads (including the one processing).
    """
    def __init__(self, library, *, python_executable, process_timeout=65, max_queue=2, start_worker=True):
        self.library=library
        self.python=Path(python_executable)
        _require(self.python.is_absolute() and self.python.is_file(),'PROCESSING_UNAVAILABLE',503)
        _require(type(max_queue) is int and 1<=max_queue<=2 and 1<=process_timeout<=65)
        self.timeout=process_timeout; self.max_queue=max_queue
        self.root=library.root/'terrains'
        for path in (self.root,self.root/'temporary',self.root/'versions'):
            if path.is_symlink(): raise ValueError('Private terrain paths must not be symlinks')
            path.mkdir(mode=0o700,exist_ok=True)
        self.lock=RLock(); self.condition=Condition(self.lock)
        self.callbacks={}; self.processes={}; self.receiving=0; self.receiving_bytes=0; self.stopping=False
        with library.connect() as db:
            self.project_code=db.execute('select project_code from library where id=1').fetchone()[0]
            db.executescript('''
                create table if not exists terrain_versions (
                    id text primary key, sha256 text not null, content_revision text not null,
                    name text not null, metadata text not null, report text not null, report_sha256 text not null,
                    manifest text not null, total_bytes integer not null, created_at text not null);
                create table if not exists terrain_jobs (
                    id text primary key, actor text not null, request_id text not null,
                    payload text not null, input_sha256 text not null, input_bytes integer not null,
                    state text not null, revision text not null, created_at text not null, updated_at text not null,
                    version_id text references terrain_versions(id), error_code text,
                    unique(actor,request_id));
                create table if not exists terrain_requests (
                    actor text not null, action text not null, request_id text not null,
                    payload text not null, job_id text not null references terrain_jobs(id),
                    primary key(actor,action,request_id));
                create table if not exists terrain_audit (
                    id integer primary key, actor text not null, job_id text not null,
                    action text not null, code text, created_at text not null);
            ''')
            rows=db.execute("select * from terrain_jobs where state in ('queued','processing')").fetchall()
            for row in rows:
                db.execute("update terrain_jobs set state='failed',revision=?,updated_at=?,error_code='PROCESSING_INTERRUPTED' where id=?",(_revision(),_now(),row['id']))
                db.execute('insert into terrain_audit(actor,job_id,action,code,created_at) values (?,?,?,?,?)',(row['actor'],row['id'],'failed','PROCESSING_INTERRUPTED',_now()))
            retained={row[0] for row in db.execute('select id from terrain_versions')}
        # Recovery never resumes an in-memory identity or adopts partial output.
        for path in (self.root/'temporary').iterdir():
            if path.is_dir() and not path.is_symlink(): shutil.rmtree(path)
        for path in (self.root/'versions').iterdir():
            if path.is_dir() and not path.is_symlink() and path.name not in retained: shutil.rmtree(path)
        self.thread=Thread(target=self._run,name='ontovis-terrain-worker',daemon=True) if start_worker else None
        if self.thread: self.thread.start()

    @staticmethod
    def _public(row):
        metadata=json.loads(row['payload'])
        return {'jobId':row['id'],'jobRevision':row['revision'],'state':row['state'],
                'displayName':metadata['displayName'],'createdAt':row['created_at'],'updatedAt':row['updated_at'],
                'terrainVersionId':row['version_id'],'errorCode':row['error_code']}

    def _row(self,db,identifier):
        row=db.execute('select * from terrain_jobs where id=?',(_uuid(identifier),)).fetchone()
        _require(row is not None,'NOT_FOUND_OR_FORBIDDEN',404)
        return row

    def _disk_bytes(self):
        total=0
        for path in self.root.rglob('*'):
            _require(not path.is_symlink(),'RESOURCE_CHANGED',409)
            if path.is_file(): total+=path.stat().st_size
        return total

    def _capacity(self,db,length):
        count,total=db.execute('select count(*),coalesce(sum(total_bytes),0) from terrain_versions').fetchone()
        pending,bytes_pending=db.execute("select count(*),coalesce(sum(input_bytes),0) from terrain_jobs where state in ('queued','processing')").fetchone()
        _require(pending+self.receiving<self.max_queue,'TERRAIN_BUSY',429)
        _require(count+pending+self.receiving<MAX_VERSIONS,'TERRAIN_LIBRARY_FULL',413)
        planned=total+bytes_pending+pending*DERIVED_RESERVE_BYTES
        _require(max(planned,self._disk_bytes())+self.receiving_bytes+length+DERIVED_RESERVE_BYTES<=MAX_TOTAL_BYTES,'TERRAIN_LIBRARY_FULL',413)

    @staticmethod
    def _receive(stream,length,sink=None):
        digest=hashlib.sha256(); remaining=length
        while remaining:
            chunk=stream.read(min(65536,remaining))
            _require(type(chunk) is bytes and 0<len(chunk)<=min(65536,remaining),'INVALID_TERRAIN')
            remaining-=len(chunk); digest.update(chunk)
            if sink: sink.write(chunk)
        return digest.hexdigest()

    def upload(self,stream,length,metadata,actor,authorize):
        metadata=_metadata(metadata); actor=_text(actor)
        _require(type(length) is int and 8<=length<=MAX_BYTES,'TERRAIN_LIMIT_EXCEEDED',413)
        payload=_canonical(metadata); authorize()
        with self.condition:
            _require(not self.stopping,'PROCESSING_UNAVAILABLE',503)
            with self.library.connect() as db:
                prior=db.execute('select * from terrain_jobs where actor=? and request_id=?',(actor,metadata['clientRequestId'])).fetchone()
                if prior:
                    _require(prior['payload']==payload and prior['input_bytes']==length,'REQUEST_CONFLICT',409)
                else:
                    self._capacity(db,length)
                    self.receiving+=1; self.receiving_bytes+=length+DERIVED_RESERVE_BYTES
        if prior:
            digest=self._receive(stream,length)
            authorize()
            _require(digest==prior['input_sha256'],'REQUEST_CONFLICT',409)
            return self.job(prior['id'],authorize)
        identifier=str(uuid4()); work=self.root/'temporary'/identifier; published=False
        try:
            work.mkdir(mode=0o700)
            with (work/'source.tif').open('xb') as sink:
                digest=self._receive(stream,length,sink); sink.flush(); os.fsync(sink.fileno())
            os.chmod(work/'source.tif',0o600)
            _sync_directory(work); _sync_directory(work.parent)
            with self.condition:
                authorize(); _require(not self.stopping,'PROCESSING_UNAVAILABLE',503)
                with self.library.connect() as db:
                    db.execute('begin immediate')
                    duplicate=db.execute('select * from terrain_jobs where actor=? and request_id=?',(actor,metadata['clientRequestId'])).fetchone()
                    if duplicate:
                        _require(duplicate['payload']==payload and duplicate['input_sha256']==digest,'REQUEST_CONFLICT',409)
                        return self._public(duplicate)
                    now=_now()
                    db.execute('insert into terrain_jobs values (?,?,?,?,?,?,?,?,?,?,?,?)',(identifier,actor,metadata['clientRequestId'],payload,digest,length,'queued',_revision(),now,now,None,None))
                    db.execute('insert into terrain_audit(actor,job_id,action,created_at) values (?,?,?,?)',(actor,identifier,'queued',now))
                    authorize()
                self.callbacks[identifier]=authorize; published=True
                value=self.job(identifier,authorize)
                self.condition.notify_all()
                return value
        except OSError:
            raise PreviewError(503,'TERRAIN_STORAGE_UNAVAILABLE') from None
        finally:
            with self.condition:
                self.receiving-=1; self.receiving_bytes-=length+DERIVED_RESERVE_BYTES
                self.condition.notify_all()
            if not published: shutil.rmtree(work,ignore_errors=True)

    def job(self,job_id,authorize):
        authorize()
        with self.library.connect() as db: result=self._public(self._row(db,job_id))
        authorize(); return result

    def cancel(self,job_id,expected_job_revision,actor,authorize,client_request_id):
        job_id=_uuid(job_id); _uuid(client_request_id); actor=_text(actor); _text(expected_job_revision,128)
        authorize(); payload=_canonical({'jobId':job_id,'expectedJobRevision':expected_job_revision})
        with self.condition:
            with self.library.connect() as db:
                db.execute('begin immediate')
                row=self._row(db,job_id)
                prior=db.execute('select * from terrain_requests where actor=? and action=? and request_id=?',(actor,'cancel',client_request_id)).fetchone()
                if prior: _require(prior['payload']==payload,'REQUEST_CONFLICT',409)
                else:
                    if row['state'] not in TERMINAL:
                        _require(row['revision']==expected_job_revision,'JOB_CHANGED',409)
                        db.execute("update terrain_jobs set state='cancelled',revision=?,updated_at=? where id=?",(_revision(),_now(),job_id))
                    db.execute('insert into terrain_requests values (?,?,?,?,?)',(actor,'cancel',client_request_id,payload,job_id))
                    db.execute('insert into terrain_audit(actor,job_id,action,created_at) values (?,?,?,?)',(actor,job_id,'cancel_requested',_now()))
                authorize()
            process=self.processes.get(job_id)
            if process and process.poll() is None:
                try: process.terminate()
                except ProcessLookupError: pass
            if job_id not in self.processes:
                self.callbacks.pop(job_id,None)
                shutil.rmtree(self.root/'temporary'/job_id,ignore_errors=True)
            self.condition.notify_all()
        return self.job(job_id,authorize)

    def _transition_failed(self,job_id,code):
        with self.condition:
            with self.library.connect() as db:
                row=self._row(db,job_id)
                if row['state'] not in TERMINAL:
                    db.execute("update terrain_jobs set state='failed',revision=?,updated_at=?,error_code=? where id=?",(_revision(),_now(),code,job_id))
                    db.execute('insert into terrain_audit(actor,job_id,action,code,created_at) values (?,?,?,?,?)',(row['actor'],job_id,'failed',code,_now()))
            self.condition.notify_all()

    def _run(self):
        while True:
            with self.condition:
                if self.stopping: return
                with self.library.connect() as db: row=db.execute("select * from terrain_jobs where state='queued' order by created_at,id limit 1").fetchone()
                if row is None:
                    self.condition.wait(.2); continue
                identifier=row['id']; guard=self.callbacks.get(identifier)
            try:
                _require(guard is not None,'PROCESSING_INTERRUPTED',503); guard()
                with self.condition:
                    with self.library.connect() as db:
                        db.execute('begin immediate'); current=self._row(db,identifier)
                        if current['state']!='queued': continue
                        db.execute("update terrain_jobs set state='processing',revision=?,updated_at=? where id=?",(_revision(),_now(),identifier))
                report=self._process(row)
                self._commit(row,report,guard)
            except PreviewError as error:
                self._transition_failed(identifier,error.code)
            except Exception:
                self._transition_failed(identifier,'PROCESSING_FAILED')
            finally:
                with self.condition:
                    self.processes.pop(identifier,None); self.callbacks.pop(identifier,None)
                    shutil.rmtree(self.root/'temporary'/identifier,ignore_errors=True)
                    self.condition.notify_all()

    def _process(self,row):
        metadata=json.loads(row['payload']); work=self.root/'temporary'/row['id']
        args=[str(self.python),'-m','apps.api.terrain_validation',str(work/'source.tif'),str(work/'derived'),
              '--vertical-datum='+metadata['verticalDatum'],'--source='+metadata['sourceNote'],
              '--license='+metadata['licenseNote'],'--height-unit='+metadata['heightUnit']]
        if metadata.get('relativeReferenceId'): args+=['--relative-reference-id',metadata['relativeReferenceId']]
        if metadata.get('aoi') is not None: args+=['--aoi',*map(str,metadata['aoi'])]
        environment={key:os.environ[key] for key in ('PATH','LANG','LC_ALL','PYTHONPATH','PYTHONHOME','SYSTEMROOT','LD_LIBRARY_PATH','GDAL_DATA','PROJ_DATA') if key in os.environ}
        environment.update({'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','PROJ_NETWORK':'OFF'})
        process=subprocess.Popen(args,cwd=Path(__file__).resolve().parents[2],env=environment,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        output=bytearray(); selector=selectors.DefaultSelector(); deadline=time.monotonic()+self.timeout
        try:
            with self.condition:
                self.processes[row['id']]=process
                with self.library.connect() as db: current=self._row(db,row['id'])
                if self.stopping or current['state']!='processing': process.terminate()
            os.set_blocking(process.stdout.fileno(),False); selector.register(process.stdout,selectors.EVENT_READ)
            while process.poll() is None or selector.get_map():
                _require(time.monotonic()<deadline,'TERRAIN_LIMIT_EXCEEDED')
                for key,_ in selector.select(.05):
                    chunk=os.read(key.fd,8192)
                    if not chunk: selector.unregister(key.fileobj)
                    else:
                        output.extend(chunk)
                        _require(len(output)<=MAX_STDOUT_BYTES,'TERRAIN_LIMIT_EXCEEDED')
            code=process.wait(timeout=1)
            _require(code in (0,2),'TERRAIN_LIMIT_EXCEEDED')
            try: report=strict_json(bytes(output))
            except Exception: raise PreviewError(422,'INVALID_TERRAIN') from None
            _require(type(report) is dict,'INVALID_TERRAIN')
            if code: raise PreviewError(422,report.get('code') if report.get('code') in ('NO_DATA','INVALID_TERRAIN','UNSUPPORTED_TERRAIN','UNSUPPORTED_CRS','CRS_REQUIRED','VERTICAL_DATUM_CONFLICT','OUTSIDE_COVERAGE','OUTSIDE_PROJECTION_AREA','TERRAIN_LIMIT_EXCEEDED','PROCESSING_UNAVAILABLE') else 'INVALID_TERRAIN')
            return report
        finally:
            selector.close()
            if process.poll() is None:
                process.kill()
            process.wait(timeout=3)
            if process.stdout: process.stdout.close()

    def _verify_output(self,row,report):
        work=self.root/'temporary'/row['id']; derived=work/'derived'
        _require(type(report) is dict and report.get('state')=='ready' and report.get('schemaVersion')==1,'INVALID_TERRAIN')
        _require(not derived.is_symlink() and derived.is_dir(),'INVALID_TERRAIN')
        report_file=derived/'report.json'
        _require(not report_file.is_symlink() and report_file.is_file() and report_file.stat().st_size<=MAX_STDOUT_BYTES,'INVALID_TERRAIN')
        saved=strict_json(report_file.read_bytes())
        _require(saved=={key:value for key,value in report.items() if key!='processLimits'},'INVALID_TERRAIN')
        source=report.get('source',{}); mesh=report.get('mesh',{})
        _require(source.get('sha256')==row['input_sha256'] and source.get('bytes')==row['input_bytes'] and source.get('width',MAX_PIXELS)*source.get('height',MAX_PIXELS)<=MAX_PIXELS,'INVALID_TERRAIN')
        _require(type(mesh.get('triangles')) is int and 0<mesh['triangles']<=MAX_TRIANGLES,'INVALID_TERRAIN')
        artifacts=report.get('artifacts'); _require(type(artifacts) is list,'INVALID_TERRAIN')
        ids=[item.get('artifactId') for item in artifacts if type(item) is dict]
        _require(len(ids)==len(artifacts) and len(ids)==len(set(ids)) and BASE_ARTIFACTS<=set(ids)<=BASE_ARTIFACTS|OPTIONAL_ARTIFACTS,'INVALID_TERRAIN')
        _require({path.name for path in derived.iterdir()}==set(ids)|{'report.json'},'INVALID_TERRAIN')
        manifest=[]; total=row['input_bytes']+report_file.stat().st_size
        for item in artifacts:
            path=derived/item['artifactId']
            _require(not path.is_symlink() and path.is_file() and type(item.get('bytes')) is int and 0<item['bytes']<=DERIVED_RESERVE_BYTES and path.stat().st_size==item['bytes'] and _hash(path)==item.get('sha256'),'RESOURCE_CHANGED',409)
            total+=item['bytes']; manifest.append(dict(item))
        _require(total-row['input_bytes']<=DERIVED_RESERVE_BYTES,'TERRAIN_LIMIT_EXCEEDED')
        _require(not (work/'source.tif').is_symlink() and _hash(work/'source.tif')==row['input_sha256'],'RESOURCE_CHANGED',409)
        manifest.append({'artifactId':'source.tif','bytes':row['input_bytes'],'sha256':row['input_sha256'],'format':'geotiff'})
        return saved,manifest,total,_hash(report_file)

    def _commit(self,row,report,authorize):
        saved,manifest,total,report_sha=self._verify_output(row,report)
        identifier=str(uuid4()); work=self.root/'temporary'/row['id']; target=self.root/'versions'/identifier
        with self.condition:
            with self.library.connect() as db:
                db.execute('begin immediate'); current=self._row(db,row['id'])
                if current['state']!='processing': return
                authorize(); _require(not self.stopping,'PROCESSING_INTERRUPTED',503)
                count,occupied=db.execute('select count(*),coalesce(sum(total_bytes),0) from terrain_versions').fetchone()
                _require(count<MAX_VERSIONS and occupied+total<=MAX_TOTAL_BYTES,'TERRAIN_LIBRARY_FULL',413)
                revision='terrain-content:'+hashlib.sha256(_canonical(saved).encode()).hexdigest()
                try:
                    os.replace(work,target)
                    _sync_directory(target.parent); _sync_directory(work.parent)
                    db.execute('insert into terrain_versions values (?,?,?,?,?,?,?,?,?,?)',(identifier,row['input_sha256'],revision,json.loads(row['payload'])['displayName'],row['payload'],_canonical(saved),report_sha,_canonical(manifest),total,_now()))
                    db.execute("update terrain_jobs set state='ready',revision=?,updated_at=?,version_id=?,error_code=null where id=?",(_revision(),_now(),identifier,row['id']))
                    db.execute('insert into terrain_audit(actor,job_id,action,created_at) values (?,?,?,?)',(row['actor'],row['id'],'ready',_now()))
                    authorize(); db.commit()
                except BaseException:
                    if db.in_transaction:
                        db.rollback(); shutil.rmtree(target,ignore_errors=True)
                    raise

    def version(self,version_id,authorize):
        authorize(); version_id=_uuid(version_id)
        with self.library.connect() as db: row=db.execute('select * from terrain_versions where id=?',(version_id,)).fetchone()
        _require(row is not None,'NOT_FOUND_OR_FORBIDDEN',404)
        directory=self.root/'versions'/row['id']
        report_file=directory/'derived'/'report.json'
        _require(not any(path.is_symlink() for path in (self.root,self.root/'versions',directory,directory/'derived')),'RESOURCE_CHANGED',409)
        _require(not report_file.is_symlink() and report_file.is_file() and report_file.stat().st_size<=MAX_STDOUT_BYTES and _hash(report_file)==row['report_sha256'],'RESOURCE_CHANGED',409)
        result={'terrainVersionId':row['id'],'contentRevision':row['content_revision'],'displayName':row['name'],
                'sha256':row['sha256'],'expectedReportSha256':row['report_sha256'],'state':'ready','createdAt':row['created_at'],'report':json.loads(row['report']),
                'artifacts':json.loads(row['manifest'])}
        authorize(); return result

    def content(self,version_id,artifact_id,expected_sha,authorize):
        value=self.version(version_id,authorize)
        item=next((item for item in value['artifacts'] if item['artifactId']==artifact_id),None)
        _require(item is not None,'NOT_FOUND_OR_FORBIDDEN',404)
        _require(expected_sha==item['sha256'],'RESOURCE_CHANGED',409)
        directory=self.root/'versions'/value['terrainVersionId']
        path=directory/'source.tif' if artifact_id=='source.tif' else directory/'derived'/artifact_id
        _require(not directory.is_symlink() and not (directory/'derived').is_symlink() and not path.is_symlink() and path.is_file() and path.stat().st_size==item['bytes'],'RESOURCE_CHANGED',409)
        content=path.read_bytes()
        _require(hashlib.sha256(content).hexdigest()==expected_sha,'RESOURCE_CHANGED',409)
        authorize(); return content

    def close(self):
        with self.condition:
            self.stopping=True
            for process in self.processes.values():
                if process.poll() is None:
                    try: process.terminate()
                    except ProcessLookupError: pass
            self.condition.notify_all()
        if self.thread: self.thread.join(timeout=self.timeout+4)
        with self.condition:
            with self.library.connect() as db: pending=[row[0] for row in db.execute("select id from terrain_jobs where state in ('queued','processing')")]
            for identifier in pending:
                self._transition_failed(identifier,'PROCESSING_INTERRUPTED')
                shutil.rmtree(self.root/'temporary'/identifier,ignore_errors=True)
            self.callbacks.clear()
