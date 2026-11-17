"""One bounded public overview acquisition worker beside the existing libraries.

Jobs retain request/progress/result identities, never session IDs or credentials.
Only a live in-memory authorization guard may finish an import; restart fails
unfinished jobs rather than resuming with a stale identity.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import shutil
import sqlite3
import subprocess
from threading import Event, RLock, Thread
import time
from uuid import UUID, uuid4, uuid5

from .authority import PreviewError
from .public_geo_sources import region
from .terrain_library import _canonical, _now, _require, _uuid

TERMINAL = frozenset(('ready', 'failed', 'cancelled'))
STAGES = frozenset(('queued', 'terrain_source', 'imagery_source', 'terrain_read', 'imagery_read', 'terrain_import', 'imagery_import'))


class PublicGeoData:
    def __init__(self, library, terrains, imagery):
        self.library, self.terrains, self.imagery = library, terrains, imagery
        self.lock = RLock()
        self.active = None
        from threading import BoundedSemaphore
        self.fetch_budget=BoundedSemaphore(1)
        self.process = None
        self.cancelled = Event()
        self.stopping = False
        self.thread = None
        with library.connect() as db:
            db.executescript('''
                create table if not exists public_geo_jobs (
                    id text primary key, actor text not null, request_id text not null,
                    payload text not null, state text not null, stage text not null, revision text not null,
                    results text not null, error_code text, created_at text not null, updated_at text not null,
                    unique(actor,request_id));
            ''')
            interrupted = db.execute("select * from public_geo_jobs where state not in ('ready','failed','cancelled')").fetchall()
        for row in interrupted:
            results = self._committed_results(row['id'], row['actor'], json.loads(row['results']))
            self._change(row['id'], state='failed', results=results, error='PUBLIC_PROCESSING_INTERRUPTED')
        # Partial bytes are not adopted after restart. Committed normal library
        # versions remain addressable through the stored result identities.
        for path in (library.root/'temporary').glob('public-geodata-*'):
            _require(not path.is_symlink(), 'RESOURCE_CHANGED', 409)
            if path.is_dir(): shutil.rmtree(path)

    @staticmethod
    def public(row):
        return {'jobId': row['id'], 'jobRevision': row['revision'], 'state': row['state'], 'stage': row['stage'],
                'request': json.loads(row['payload']), 'results': json.loads(row['results']),
                'errorCode': row['error_code'], 'createdAt': row['created_at'], 'updatedAt': row['updated_at']}

    def job(self, identifier, actor, authorize):
        authorize()
        if identifier is not None: identifier = _uuid(identifier)
        with self.library.connect() as db:
            row = (db.execute('select * from public_geo_jobs where id=? and actor=?', (identifier, actor)).fetchone()
                   if identifier is not None else db.execute('select * from public_geo_jobs where actor=? order by created_at desc,id desc limit 1', (actor,)).fetchone())
        _require(row is not None, 'NOT_FOUND_OR_FORBIDDEN', 404)
        authorize()
        return self.public(row)

    def start(self, payload, actor, authorize):
        request = region(payload)
        _uuid(request['clientRequestId'])
        encoded = _canonical(request)
        authorize()
        with self.lock:
            _require(not self.stopping, 'PROCESSING_UNAVAILABLE', 503)
            with self.library.connect() as db:
                prior = db.execute('select * from public_geo_jobs where actor=? and request_id=?', (actor, request['clientRequestId'])).fetchone()
                if prior:
                    _require(prior['payload'] == encoded, 'REQUEST_CONFLICT', 409)
                    return self.public(prior)
                _require(self.active is None, 'PUBLIC_ACQUISITION_BUSY', 429)
                _require(db.execute('select count(*) from public_geo_jobs').fetchone()[0] < 200, 'PUBLIC_LIMIT_EXCEEDED', 413)
                identifier, now = str(uuid4()), _now()
                db.execute('begin immediate'); authorize()
                db.execute('insert into public_geo_jobs values (?,?,?,?,?,?,?,?,?,?,?)',
                           (identifier, actor, request['clientRequestId'], encoded, 'processing', 'queued',
                            'public-job:'+uuid4().hex, '{}', None, now, now))
                authorize()
            self.active = identifier
            self.cancelled.clear()
            self.thread = Thread(target=self._run, args=(identifier, request, actor, authorize), name='ontovis-public-overview', daemon=True)
            self.thread.start()
        return self.job(identifier, actor, authorize)

    def _change(self, identifier, *, stage=None, state=None, results=None, error=None):
        with self.lock, self.library.connect() as db:
            row = db.execute('select * from public_geo_jobs where id=?', (identifier,)).fetchone()
            if row['state'] in TERMINAL: return
            db.execute('update public_geo_jobs set stage=?,state=?,results=?,error_code=?,revision=?,updated_at=? where id=?',
                       (stage or row['stage'], state or row['state'], _canonical(results) if results is not None else row['results'],
                        error, 'public-job:'+uuid4().hex, _now(), identifier))

    def cancel(self, identifier, revision, actor, authorize):
        with self.lock:
            current = self.job(identifier, actor, authorize)
            if current['state'] in TERMINAL: return current
            _require(current['jobRevision'] == revision, 'PUBLIC_JOB_CHANGED', 409)
            _require(self.active == identifier, 'PUBLIC_PROCESSING_INTERRUPTED', 409)
            authorize(); self.cancelled.set()
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()
        return self.job(identifier, actor, authorize)

    def _committed_results(self, identifier, actor, results):
        # A cancellation/logout can race the last post-commit guard. Recover
        # only identities already committed by this job's deterministic request
        # IDs, so an interrupted job never conceals its successfully saved part.
        with self.library.connect() as db:
            terrain = db.execute("select version_id from terrain_jobs where actor=? and request_id=? and state='ready'",
                (actor, str(uuid5(UUID(identifier), 'terrain')))).fetchone()
            image = db.execute('select version_id from imagery_requests where actor=? and request_id=?',
                (actor, str(uuid5(UUID(identifier), 'imagery')))).fetchone()
        if terrain: results['terrainVersionId'] = terrain[0]
        if image: results['imageryVersionId'] = image[0]
        return results

    def _run(self, identifier, request, actor, authorize):
        work = self.library.root/'temporary'/('public-geodata-'+identifier)
        results = {}
        terrain_job = None
        def guard():
            if self.cancelled.is_set() or self.stopping: raise PreviewError(409, 'PUBLIC_CANCELLED')
            authorize()
        try:
            guard(); work.mkdir(mode=0o700)
            (work/'request.json').write_text(_canonical(request))
            os.chmod(work/'request.json', 0o600)
            while not self.fetch_budget.acquire(timeout=.25):
                guard()
            try:
                guard(); report = self._fetch(work, identifier, guard)
            finally:
                self.fetch_budget.release()
            for kind in ('terrain', 'imagery'):
                if not request[kind]: continue
                guard(); self._change(identifier, stage=kind+'_import')
                facts = report[kind]
                source = '; '.join(record['itemId'] for record in facts['records'])
                source_note = ('Earth Search public COG; center WGS84 '+str([request['longitude'], request['latitude']])+
                               ', radius '+str(request['radiusKm'])+' km; circular mask; '+source+'; '+facts['resampling'])
                metadata = {'clientRequestId': str(uuid5(UUID(identifier), kind)), 'displayName': request['name']+(' · GLO-30 DSM' if kind == 'terrain' else ' · Sentinel-2'),
                            'sourceNote': source_note, 'licenseNote': ('Copernicus DEM GLO-30 public license; produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved' if kind == 'terrain' else 'Copernicus Sentinel data free, full and open; attribution required'),
                            'rightsDeclared': True}
                path = work/(kind+'.tif')
                _require(path.is_file() and not path.is_symlink() and 8 <= path.stat().st_size <= 32*1024*1024, 'PUBLIC_LIMIT_EXCEEDED', 413)
                with path.open('rb') as stream:
                    if kind == 'terrain':
                        metadata.update(verticalDatum='EGM2008', heightUnit='m')
                        job = self.terrains.upload(stream, path.stat().st_size, metadata, actor, guard)
                        terrain_job = job['jobId']
                        deadline = time.monotonic()+75
                        while job['state'] not in ('ready', 'failed', 'cancelled'):
                            guard()
                            _require(time.monotonic() < deadline, 'PUBLIC_LIMIT_EXCEEDED', 413)
                            self.cancelled.wait(.3)
                            job = self.terrains.job(job['jobId'], guard)
                        _require(job['state'] == 'ready', job.get('errorCode') or 'PUBLIC_SOURCE_UNAVAILABLE')
                        terrain_job = None
                        results['terrainVersionId'] = job['terrainVersionId']
                    else:
                        metadata.update(acquiredAt=facts['acquiredAt'], attribution='Contains modified Copernicus Sentinel data ('+facts['acquiredAt'][:4]+')',
                                        qualityNote='20 m overview derived from 10 m RGB; SCL 0/1/3/7/8/9/10/11 transparent; valid circle fraction '+str(round(facts['validFractionOfCircle'], 5))+'; not engineering positioning accuracy.')
                        value = self.imagery.upload(stream, path.stat().st_size, metadata, actor, guard)
                        results['imageryVersionId'] = value['imageryVersionId']
                results[kind] = facts
                self._change(identifier, results=results)
            guard(); self._change(identifier, state='ready', results=results)
        except PreviewError as error:
            self._change(identifier, state='cancelled' if error.code == 'PUBLIC_CANCELLED' else 'failed', results=self._committed_results(identifier, actor, results), error=error.code)
        except (OSError, ValueError, TypeError, KeyError, OverflowError, MemoryError, RecursionError, sqlite3.Error):
            self._change(identifier, state='failed', results=self._committed_results(identifier, actor, results), error='PUBLIC_SOURCE_UNAVAILABLE')
        finally:
            if terrain_job is not None:
                # A queued/processing terrain callback observes cancellation too.
                # Cancellation never deletes a version already committed.
                try:
                    job = self.terrains.job(terrain_job, lambda:None)
                    if job['state'] not in ('ready', 'failed', 'cancelled'):
                        self.terrains.cancel(terrain_job, job['jobRevision'], actor, lambda:None, str(uuid4()))
                except PreviewError: pass
            shutil.rmtree(work, ignore_errors=True)
            with self.lock:
                self.active = None; self.process = None

    def _fetch(self, work, identifier, guard):
        environment = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL', 'PYTHONPATH', 'PYTHONHOME', 'SYSTEMROOT', 'LD_LIBRARY_PATH', 'GDAL_DATA', 'PROJ_DATA') if key in os.environ}
        environment.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', PROJ_NETWORK='OFF', GDAL_HTTP_NETRC='NO', GDAL_CONFIG_FILE=os.devnull)
        output, result, total = bytearray(), None, 0
        with subprocess.Popen([str(self.terrains.python), '-m', 'apps.api.public_geo_process', str(work)],
                              cwd=Path(__file__).resolve().parents[2], env=environment, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
            with self.lock: self.process = process
            selector = selectors.DefaultSelector()
            try:
                os.set_blocking(process.stdout.fileno(), False)
                selector.register(process.stdout, selectors.EVENT_READ)
                deadline, last_guard = time.monotonic()+245, 0
                while process.poll() is None or selector.get_map():
                    if self.cancelled.is_set() or self.stopping: raise PreviewError(409, 'PUBLIC_CANCELLED')
                    _require(time.monotonic() < deadline, 'PUBLIC_LIMIT_EXCEEDED', 413)
                    if time.monotonic()-last_guard >= 2:
                        guard(); last_guard = time.monotonic()
                    for key, _ in selector.select(.1):
                        chunk = os.read(key.fd, 65536)
                        if not chunk: selector.unregister(key.fileobj)
                        else:
                            total += len(chunk); _require(total <= 65536, 'PUBLIC_LIMIT_EXCEEDED', 413)
                            output.extend(chunk)
                            while b'\n' in output:
                                raw, _, rest = output.partition(b'\n'); output = bytearray(rest)
                                event = json.loads(raw)
                                if event.get('stage') in STAGES: self._change(identifier, stage=event['stage'])
                                if 'result' in event: result = event['result']
                                if 'code' in event: raise PreviewError(422, event['code'] if event['code'] in ('PUBLIC_LIMIT_EXCEEDED','PUBLIC_COVERAGE_UNAVAILABLE','PUBLIC_SOURCE_UNAVAILABLE') else 'PUBLIC_SOURCE_UNAVAILABLE')
                guard(); _require(process.wait(timeout=1) == 0 and type(result) is dict, 'PUBLIC_SOURCE_UNAVAILABLE', 502)
                return result
            finally:
                selector.close()
                if process.poll() is None: process.kill()
                process.wait(timeout=3)

    def close(self):
        with self.lock:
            self.stopping = True; self.cancelled.set()
            if self.process is not None and self.process.poll() is None: self.process.terminate()
        if self.thread: self.thread.join(timeout=60)
