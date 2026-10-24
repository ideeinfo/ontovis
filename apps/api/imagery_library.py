"""Append-only private overview imagery in the existing project library."""
from __future__ import annotations

from datetime import date
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
from threading import Lock
from uuid import uuid4

from .authority import PreviewError
from .imagery_validation import MAX_BYTES, MAX_SIDE
from .terrain_library import _canonical, _hash, _now, _require, _sqlite_busy, _sync_directory, _text, _uuid

MAX_VERSIONS = 20
MAX_TOTAL_BYTES = 1024 * 1024 * 1024


def metadata(value):
    fields = {'clientRequestId', 'displayName', 'sourceNote', 'licenseNote', 'attribution', 'acquiredAt', 'qualityNote', 'rightsDeclared'}
    _require(type(value) is dict and set(value) == fields)
    result = dict(value)
    _uuid(result['clientRequestId'])
    for key, limit in (('displayName', 200), ('sourceNote', 2000), ('licenseNote', 2000), ('attribution', 500), ('qualityNote', 2000)):
        result[key] = _text(result[key], limit)
    _require(result['rightsDeclared'] is True, 'IMAGERY_RIGHTS_REQUIRED')
    try:
        _require(type(result['acquiredAt']) is str and date.fromisoformat(result['acquiredAt']).isoformat() == result['acquiredAt'])
    except (TypeError, ValueError):
        raise PreviewError(422, 'INVALID_REQUEST') from None
    return result


class ImageryLibrary:
    @contextmanager
    def _database(self):
        try:
            with self.library.connect() as db:
                yield db
        except sqlite3.Error as error:
            raise PreviewError(503, 'IMAGERY_STORAGE_BUSY' if _sqlite_busy(error) else 'IMAGERY_STORAGE_UNAVAILABLE') from None

    def __init__(self, library, *, python_executable):
        self.library = library
        self.python = Path(python_executable)
        _require(self.python.is_absolute() and self.python.is_file(), 'PROCESSING_UNAVAILABLE', 503)
        self.root = library.root / 'imagery'
        self.lock = Lock()
        for path in (self.root, self.root / 'temporary', self.root / 'versions'):
            _require(not path.is_symlink(), 'RESOURCE_CHANGED', 409)
            path.mkdir(mode=0o700, exist_ok=True)
        with self._database() as db:
            db.executescript('''
                create table if not exists imagery_versions (
                    id text primary key, sha256 text not null, content_revision text not null, name text not null,
                    metadata text not null, report text not null, report_sha256 text not null,
                    manifest text not null, total_bytes integer not null, created_at text not null);
                create table if not exists imagery_requests (
                    actor text not null, request_id text not null, payload text not null, input_sha256 text not null,
                    version_id text not null references imagery_versions(id), primary key(actor,request_id));
                create table if not exists imagery_audit (
                    id integer primary key, actor text not null, version_id text not null references imagery_versions(id),
                    action text not null, created_at text not null);
                create trigger if not exists imagery_no_update before update on imagery_versions
                    begin select raise(abort, 'immutable imagery'); end;
                create trigger if not exists imagery_no_delete before delete on imagery_versions
                    begin select raise(abort, 'retained imagery'); end;
            ''')
            retained = {row[0] for row in db.execute('select id from imagery_versions')}
        for folder in ('temporary', 'versions'):
            for path in (self.root / folder).iterdir():
                _require(not path.is_symlink(), 'RESOURCE_CHANGED', 409)
                if path.is_dir() and (folder == 'temporary' or path.name not in retained):
                    shutil.rmtree(path)

    @staticmethod
    def public(row):
        return {'imageryVersionId': row['id'], 'contentRevision': row['content_revision'], 'displayName': row['name'],
                'sha256': row['sha256'], 'expectedReportSha256': row['report_sha256'], 'createdAt': row['created_at'],
                'metadata': json.loads(row['metadata']), 'report': json.loads(row['report']), 'texture': json.loads(row['manifest'])}

    def _row(self, db, identifier):
        row = db.execute('select * from imagery_versions where id=?', (_uuid(identifier),)).fetchone()
        _require(row is not None, 'NOT_FOUND_OR_FORBIDDEN', 404)
        return row

    def version(self, identifier, authorize):
        authorize()
        with self._database() as db:
            result = self.public(self._row(db, identifier))
        authorize()
        return result

    def listing(self, authorize, *, q=''):
        _require(type(q) is str and len(q) <= 200 and all(ord(c) >= 32 for c in q))
        authorize()
        with self._database() as db:
            rows = db.execute('select * from imagery_versions order by created_at desc,id').fetchall()
            result = [self.public(row) for row in rows if q.casefold() in row['name'].casefold()]
        authorize()
        return {'items': result}

    def upload_result(self, payload, fingerprint, actor, authorize):
        payload = metadata(payload)
        _require(type(fingerprint) is str and len(fingerprint) == 64
                 and all(c in '0123456789abcdef' for c in fingerprint))
        actor = _text(actor)
        authorize()
        with self._database() as db:
            prior = db.execute('select * from imagery_requests where actor=? and request_id=?',
                               (actor, payload['clientRequestId'])).fetchone()
            if prior is None:
                result = {'state': 'unknown'}
            else:
                _require(prior['payload'] == _canonical(payload) and prior['input_sha256'] == fingerprint,
                         'REQUEST_CONFLICT', 409)
                result = {'state': 'completed', **self.public(self._row(db, prior['version_id']))}
        authorize()
        return result

    def content(self, identifier, revision, fingerprint, authorize):
        value = self.version(identifier, authorize)
        _require(value['contentRevision'] == revision and value['texture']['sha256'] == fingerprint, 'RESOURCE_CHANGED', 409)
        folder = self.root / 'versions' / identifier
        path = folder / 'texture.png'
        _require(not folder.is_symlink() and not path.is_symlink() and path.is_file(), 'RESOURCE_CHANGED', 409)
        _require(path.stat().st_size == value['texture']['bytes'] <= MAX_BYTES, 'RESOURCE_CHANGED', 409)
        content = path.read_bytes()
        _require(hashlib.sha256(content).hexdigest() == fingerprint, 'RESOURCE_CHANGED', 409)
        authorize()
        return content

    def validate_scene(self, reference, terrain, authorize):
        value = self.version(reference['imageryVersionId'], authorize)
        _require(value['contentRevision'] == reference['expectedContentRevision']
                 and value['expectedReportSha256'] == reference['expectedReportSha256'], 'RESOURCE_CHANGED', 409)
        a, b = value['report']['coverageWgs84'], terrain['report']['source']['samplingCentreCoverageWgs84']
        _require(max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3]), 'IMAGERY_OUTSIDE_TERRAIN', 409)
        self.content(value['imageryVersionId'], value['contentRevision'], value['texture']['sha256'], authorize)
        return value

    def upload(self, stream, length, payload, actor, authorize):
        payload = metadata(payload)
        actor = _text(actor)
        _require(type(length) is int and 8 <= length <= MAX_BYTES, 'IMAGERY_LIMIT_EXCEEDED', 413)
        authorize()
        _require(self.lock.acquire(blocking=False), 'IMAGERY_BUSY', 429)
        work = None
        published = False
        identifier = str(uuid4())
        try:
            with self._database() as db:
                prior = db.execute('select * from imagery_requests where actor=? and request_id=?', (actor, payload['clientRequestId'])).fetchone()
                if not prior:
                    count, total = db.execute('select count(*),coalesce(sum(total_bytes),0) from imagery_versions').fetchone()
                    actual = 0
                    for path in self.root.rglob('*'):
                        _require(not path.is_symlink(), 'RESOURCE_CHANGED', 409)
                        if path.is_file(): actual += path.stat().st_size
                    _require(count < MAX_VERSIONS and max(total, actual) + length + MAX_BYTES <= MAX_TOTAL_BYTES, 'IMAGERY_LIMIT_EXCEEDED', 413)
            work = self.root / 'temporary' / identifier
            work.mkdir(mode=0o700)
            digest = hashlib.sha256()
            with (work / 'source.tif').open('xb') as sink:
                remaining = length
                while remaining:
                    chunk = stream.read(min(65536, remaining))
                    _require(type(chunk) is bytes and 0 < len(chunk) <= min(65536, remaining), 'UNSUPPORTED_IMAGERY')
                    remaining -= len(chunk)
                    digest.update(chunk)
                    if not prior: sink.write(chunk)
                sink.flush(); os.fsync(sink.fileno())
            encoded = _canonical(payload)
            source_sha = digest.hexdigest()
            authorize()
            if prior:
                _require(prior['payload'] == encoded and prior['input_sha256'] == source_sha, 'REQUEST_CONFLICT', 409)
                return self.version(prior['version_id'], authorize)
            environment = {key: os.environ[key] for key in ('PATH','LANG','LC_ALL','PYTHONPATH','PYTHONHOME','SYSTEMROOT','LD_LIBRARY_PATH','GDAL_DATA','PROJ_DATA') if key in os.environ}
            environment.update({'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','PROJ_NETWORK':'OFF'})
            try:
                result = subprocess.run([str(self.python), '-m', 'apps.api.imagery_validation', str(work/'source.tif'), str(work/'texture.png')],
                    cwd=Path(__file__).resolve().parents[2], env=environment, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=50)
                _require(len(result.stdout) <= 16384, 'IMAGERY_LIMIT_EXCEEDED', 413)
                report = json.loads(result.stdout)
                _require(result.returncode == 0, report.get('code', 'UNSUPPORTED_IMAGERY'))
                _require(type(report) is dict and report.get('schemaVersion') == 1, 'UNSUPPORTED_IMAGERY')
            except subprocess.TimeoutExpired:
                raise PreviewError(413, 'IMAGERY_LIMIT_EXCEEDED') from None
            except (ValueError, UnicodeError):
                raise PreviewError(422, 'UNSUPPORTED_IMAGERY') from None
            authorize()
            texture = work / 'texture.png'
            manifest = {'bytes': texture.stat().st_size, 'sha256': _hash(texture), 'mediaType':'image/png'}
            report_sha = hashlib.sha256(_canonical(report).encode()).hexdigest()
            revision = 'imagery:' + hashlib.sha256(_canonical([source_sha, payload, report_sha, manifest]).encode()).hexdigest()
            for path in (work/'source.tif', texture):
                os.chmod(path, 0o600)
                with path.open('rb') as file: os.fsync(file.fileno())
            _sync_directory(work)
            with self._database() as db:
                db.execute('begin immediate')
                authorize()
                target = self.root / 'versions' / identifier
                os.rename(work, target)
                work = target
                _sync_directory(target.parent)
                now = _now()
                db.execute('insert into imagery_versions values (?,?,?,?,?,?,?,?,?,?)', (identifier, source_sha, revision,
                    payload['displayName'], encoded, _canonical(report), report_sha, _canonical(manifest), length + manifest['bytes'], now))
                db.execute('insert into imagery_requests values (?,?,?,?,?)', (actor, payload['clientRequestId'], encoded, source_sha, identifier))
                db.execute('insert into imagery_audit(actor,version_id,action,created_at) values (?,?,?,?)', (actor, identifier, 'uploaded', now))
                authorize()
            published = True
            return self.version(identifier, authorize)
        except OSError:
            raise PreviewError(503, 'IMAGERY_STORAGE_UNAVAILABLE') from None
        finally:
            if work is not None and not published: shutil.rmtree(work, ignore_errors=True)
            self.lock.release()
