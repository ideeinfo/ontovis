"""Private GLB processing state, using the existing model store and processing slot."""
from __future__ import annotations

import hmac
from threading import Event, Lock, Thread
from typing import Callable

from .authority import PreviewError
from .model_validation import MAX_BYTES
from .project_model_library import _require, _text, _uuid

ACTIVE = ('queued', 'processing')
TABLE = 'project_model_upload_jobs'


class ModelUploadJobs:
    def __init__(self, models):
        self.models = models
        self.library = models.library
        self._workers = {}
        self._lock = Lock()
        self._closed = False
        with self.library.connect() as db:
            db.execute('''create table if not exists project_model_upload_jobs (
                actor text not null, request_id text not null, payload_sha256 text not null,
                state text not null check(state in ('queued','processing','ready','failed','cancelled')),
                revision integer not null check(revision > 0), error_code text,
                primary key(actor,request_id))''')
            db.execute(f"""update {TABLE} set state='failed', revision=revision+1,
                error_code='PROCESSING_INTERRUPTED' where state in ('queued','processing')""")
        for item in (self.library.root / 'temporary').glob('model-job-*.glb'):
            item.unlink(missing_ok=True)

    @staticmethod
    def _find(db, actor, identifier):
        return db.execute(f'select * from {TABLE} where actor=? and request_id=?', (actor, identifier)).fetchone()

    def _public(self, db, row):
        result = None
        if row['state'] == 'ready':
            result = self.models._prior(db, row['actor'], 'upload', row['request_id'], row['payload_sha256'])
            _require(result is not None, 'MODEL_STORAGE_UNAVAILABLE', 503)
            self.models._content(result)
        return {'jobId': row['request_id'], 'jobRevision': row['revision'], 'state': row['state'],
                'errorCode': row['error_code'], 'result': result}

    def status(self, identifier, actor, authorize):
        _uuid(identifier)
        authorize()
        with self.library.connect() as db:
            row = self._find(db, actor, identifier)
            if row is None:
                raise PreviewError(404, 'MODEL_JOB_NOT_FOUND')
            value = self._public(db, row)
        authorize()
        return value

    def require_unclaimed(self, db, actor, identifier):
        _require(self._find(db, actor, identifier) is None, 'REQUEST_CONFLICT', 409)

    def start(self, stream, length, metadata, actor, authorize, on_ready: Callable):
        metadata = self.models.upload_metadata(metadata)
        actor, identifier = _text(actor), metadata['clientRequestId']
        authorize()
        _require(type(length) is int and 24 <= length <= MAX_BYTES, 'MODEL_LIMIT_EXCEEDED', 413)
        if not self.library.slots.acquire(blocking=False):
            raise PreviewError(429, 'MODEL_BUSY')
        path = None
        handed_off = False
        key = (actor, identifier)
        try:
            path, digest, payload = self.models._stage_upload(stream, length, metadata, prefix='model-job-')
            authorize()
            with self.library.connect() as db:
                db.execute('begin immediate')
                old = self._find(db, actor, identifier)
                if old is not None:
                    _require(hmac.compare_digest(old['payload_sha256'], payload), 'REQUEST_CONFLICT', 409)
                    return self._public(db, old)
                existing = self.models._prior(db, actor, 'upload', identifier, payload)
                initial = 'ready' if existing is not None else 'queued'
                db.execute(f'insert into {TABLE} values (?,?,?,?,1,null)', (actor, identifier, payload, initial))
                value = self._public(db, self._find(db, actor, identifier))
            if initial == 'ready':
                return value
            interruption = Event()
            thread = Thread(target=self._run, args=(path, digest, length, metadata, actor, payload, authorize, interruption, on_ready),
                            name='ontovis-model-upload', daemon=True)
            with self._lock:
                if self._closed:
                    self._change(key, 'failed', 'PROCESSING_INTERRUPTED')
                    raise PreviewError(503, 'PROCESSING_INTERRUPTED')
                self._workers[key] = (interruption, thread)
                try:
                    thread.start()
                except RuntimeError:
                    self._workers.pop(key, None)
                    self._change(key, 'failed', 'MODEL_PROCESSING_UNAVAILABLE')
                    raise PreviewError(503, 'MODEL_PROCESSING_UNAVAILABLE') from None
            handed_off = True
            return value
        except OSError:
            raise PreviewError(503, 'MODEL_STORAGE_UNAVAILABLE') from None
        finally:
            if not handed_off:
                try:
                    if path:
                        path.unlink(missing_ok=True)
                finally:
                    self.library.slots.release()

    def _change(self, key, state, code=None):
        with self.library.connect() as db:
            from_states = ('queued',) if state == 'processing' else ACTIVE
            markers = ','.join('?' for _ in from_states)
            return db.execute(f"""update {TABLE} set state=?, revision=revision+1, error_code=?
                where actor=? and request_id=? and state in ({markers})""", (state, code, *key, *from_states)).rowcount == 1

    def _run(self, path, digest, length, metadata, actor, payload, authorize, interruption, on_ready):
        key = (actor, metadata['clientRequestId'])
        def guard():
            _require(not interruption.is_set(), 'MODEL_JOB_CANCELLED', 409)
            authorize()
        def ready(db, _result):
            saved = db.execute(f"""update {TABLE} set state='ready', revision=revision+1
                where actor=? and request_id=? and state='processing'""", key)
            _require(saved.rowcount == 1, 'MODEL_JOB_CANCELLED', 409)
        try:
            if not self._change(key, 'processing'):
                return
            guard()
            result = self.library.process(path, cancelled=interruption.is_set)
            _require(result['sha256'] == digest and result['report']['bytes'] == length, 'RESOURCE_CHANGED', 409)
            value = self.models._commit(path, metadata, actor, guard, result, action='upload',
                                        payload_digest=payload, record_ready=ready)
            on_ready(value)
        except PreviewError as error:
            self._change(key, 'failed', 'PROCESSING_INTERRUPTED' if self._closed else error.code)
        except Exception:
            self._change(key, 'failed', 'MODEL_PROCESSING_UNAVAILABLE')
        finally:
            try:
                path.unlink(missing_ok=True)
            finally:
                with self._lock:
                    self._workers.pop(key, None)
                self.library.slots.release()

    def cancel(self, identifier, expected_revision, actor, authorize):
        _uuid(identifier)
        _require(type(expected_revision) is int and expected_revision > 0)
        authorize()
        key = (actor, identifier)
        cancelled = False
        with self.library.connect() as db:
            db.execute('begin immediate')
            row = self._find(db, *key)
            if row is None:
                raise PreviewError(404, 'MODEL_JOB_NOT_FOUND')
            if row['state'] in ACTIVE:
                _require(row['revision'] == expected_revision, 'JOB_CHANGED', 409)
                authorize()
                db.execute(f"""update {TABLE} set state='cancelled', revision=revision+1
                    where actor=? and request_id=?""", key)
                row = self._find(db, *key)
                cancelled = True
            value = self._public(db, row)
        if cancelled:
            with self._lock:
                worker = self._workers.get(key)
                if worker is not None:
                    worker[0].set()
        authorize()
        return value

    def close(self):
        with self._lock:
            self._closed = True
            workers = list(self._workers.values())
            for interruption, _ in workers:
                interruption.set()
        for _, thread in workers:
            thread.join(timeout=5)
