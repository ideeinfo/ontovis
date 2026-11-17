"""Private derived model pictures. Geometry versions and scene data are never changed."""
from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sqlite3
import struct
import subprocess
import tempfile
from threading import Condition, RLock, Thread
from uuid import uuid4
import zlib

from .authority import PreviewError
from .project_model_library import _canonical, _fields, _require, _sync_directory, _text, _uuid

RENDERER_VERSION = 'model-thumbnail-v1'
SIDE = 256
MAX_PNG_BYTES = 384 * 1024
MAX_THUMBNAILS = 100
MAX_TOTAL_BYTES = MAX_THUMBNAILS * MAX_PNG_BYTES
REFERENCE_FIELDS = ('modelVersionId', 'expectedContentRevision', 'expectedSha256')


def png_info(data):
    """Check the bounded, non-animated RGBA PNG emitted by canvas, including its stream."""
    _require(isinstance(data, bytes) and 57 <= len(data) <= MAX_PNG_BYTES
             and data[:8] == b'\x89PNG\r\n\x1a\n', 'THUMBNAIL_INVALID_IMAGE')
    offset, chunks, compressed, ended = 8, [], bytearray(), False
    while offset + 12 <= len(data):
        size = struct.unpack_from('>I', data, offset)[0]
        _require(offset + 12 + size <= len(data), 'THUMBNAIL_INVALID_IMAGE')
        kind = data[offset + 4:offset + 8]
        body = data[offset + 8:offset + 8 + size]
        crc = struct.unpack_from('>I', data, offset + 8 + size)[0]
        _require(zlib.crc32(kind + body) & 0xffffffff == crc
                 and kind not in (b'acTL', b'fcTL', b'fdAT'), 'THUMBNAIL_INVALID_IMAGE')
        chunks.append(kind)
        if kind == b'IHDR':
            _require(len(chunks) == 1 and body == struct.pack('>IIBBBBB', SIDE, SIDE, 8, 6, 0, 0, 0),
                     'THUMBNAIL_INVALID_IMAGE')
        elif kind == b'IDAT': compressed.extend(body)
        elif kind == b'IEND':
            _require(not size and offset + 12 == len(data), 'THUMBNAIL_INVALID_IMAGE')
            ended = True
        else:
            _require(kind[:1].islower(), 'THUMBNAIL_INVALID_IMAGE')
        offset += 12 + size
    _require(ended and chunks.count(b'IHDR') == 1 and b'IDAT' in chunks and offset == len(data), 'THUMBNAIL_INVALID_IMAGE')
    try:
        decoder = zlib.decompressobj()
        expected = SIDE * (SIDE * 4 + 1)
        pixels = decoder.decompress(compressed, expected + 1)
        _require(len(pixels) == expected and decoder.eof and not decoder.unused_data
                 and not decoder.unconsumed_tail
                 and all(pixels[row * (SIDE * 4 + 1)] <= 4 for row in range(SIDE)), 'THUMBNAIL_INVALID_IMAGE')
    except zlib.error: raise PreviewError(422, 'THUMBNAIL_INVALID_IMAGE') from None
    return {'width': SIDE, 'height': SIDE, 'bytes': len(data), 'imageSha256': hashlib.sha256(data).hexdigest()}


class ThumbnailRenderer:
    def __init__(self, renderer_path, node, browser, *, timeout=30):
        self.renderer, self.node, self.browser = [Path(value).resolve(strict=True) for value in (renderer_path, node, browser)]
        if not all(path.is_file() for path in (self.renderer, self.node, self.browser)):
            raise ValueError('Thumbnail renderer, Node and browser must be regular files')
        self.timeout = timeout
        self.lock, self.process, self.stopping = RLock(), None, False
        from threading import BoundedSemaphore
        self.process_budget=BoundedSemaphore(1)

    @staticmethod
    def _kill(process):
        try: os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError: pass

    def __call__(self, content, work):
        with self.process_budget:
            return self._call_locked(content, work)

    def _call_locked(self, content, work):
        # Chromium's Linux singleton socket must fit the short AF_UNIX path limit.
        with tempfile.TemporaryDirectory(prefix='ov-thumb-', dir='/tmp') as runtime:
            return self._render(content, work, runtime)

    def _render(self, content, work, runtime):
        source, output = work / 'model.glb', work / 'thumbnail.png'
        source.write_bytes(content)
        with self.lock:
            _require(not self.stopping, 'THUMBNAIL_INTERRUPTED', 503)
            self.process = subprocess.Popen([str(self.node), str(Path(__file__).with_name('render_model_thumbnail.mjs')),
                str(source), str(output), str(self.renderer), str(self.browser), str(work)],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True,
                env={'PATH': os.defpath, 'LANG': 'C.UTF-8', 'TZ': 'UTC', 'TMPDIR': runtime})
            process = self.process
        try:
            try: stdout, _ = process.communicate(timeout=self.timeout)
            except subprocess.TimeoutExpired: raise PreviewError(503, 'THUMBNAIL_TIMEOUT') from None
            _require(len(stdout) <= 4096, 'THUMBNAIL_RENDER_FAILED', 503)
            try: result = json.loads(stdout)
            except (ValueError, UnicodeError): raise PreviewError(503, 'THUMBNAIL_RENDER_FAILED') from None
            _require(process.returncode == 0 and result.get('state') == 'ready'
                     and result.get('coveredPixels', 0) >= 16, 'THUMBNAIL_RENDER_FAILED', 503)
            _require(output.is_file() and not output.is_symlink()
                     and output.stat().st_size <= MAX_PNG_BYTES, 'THUMBNAIL_INVALID_IMAGE')
            return output.read_bytes()
        finally:
            self._kill(process)
            process.wait(timeout=5)
            with self.lock: self.process = None

    def close(self):
        with self.lock:
            self.stopping = True
            if self.process is not None: self._kill(self.process)


class ModelThumbnails:
    def __init__(self, models, renderer, *, start_worker=True):
        self.models, self.library, self.renderer = models, models.library, renderer
        self.root = self.library.root / 'thumbnails'
        for path in (self.root, self.root / 'files', self.root / 'temporary'):
            if path.is_symlink(): raise ValueError('Private thumbnail directories must not be symlinks')
            path.mkdir(mode=0o700, exist_ok=True)
        self.lock = RLock()
        self.condition = Condition(self.lock)
        self.pending, self.stopping = OrderedDict(), False
        with self.library.connect() as db:
            db.executescript('''
                create table if not exists model_thumbnails (
                    source_sha256 text primary key, model_version_id text not null references versions(id),
                    renderer_version text not null, revision text not null, state text not null,
                    image_sha256 text, bytes integer, width integer, height integer,
                    error_code text, actor text not null, created_at text not null, updated_at text not null);
                create table if not exists model_thumbnail_requests (
                    actor text not null, request_id text not null, payload_sha256 text not null,
                    source_sha256 text not null references model_thumbnails(source_sha256), created_at text not null,
                    primary key(actor,request_id));
                create trigger if not exists model_thumbnail_request_no_update before update on model_thumbnail_requests
                    begin select raise(abort,'immutable thumbnail request'); end;
                create trigger if not exists model_thumbnail_request_no_delete before delete on model_thumbnail_requests
                    begin select raise(abort,'retained thumbnail request'); end;
                create trigger if not exists model_thumbnail_ready_no_update before update on model_thumbnails
                    when old.state='ready' begin select raise(abort,'immutable thumbnail image'); end;
            ''')
            db.execute("update model_thumbnails set state='failed',revision=?,error_code='THUMBNAIL_INTERRUPTED',updated_at=? where state in ('queued','processing')",
                       (self._revision(), self._now()))
        for path in (self.root / 'temporary').iterdir():
            if path.is_symlink() or not path.is_dir(): raise ValueError('Unsafe thumbnail temporary path')
            shutil.rmtree(path)
        with self.library.connect() as db:
            failed = [row[0] for row in db.execute("select source_sha256 from model_thumbnails where state='failed'")]
        for fingerprint in failed:
            if not re.fullmatch('[a-f0-9]{64}', fingerprint): raise ValueError('Invalid thumbnail source hash')
            path = self.root / 'files' / (fingerprint + '.png')
            if path.is_symlink(): raise ValueError('Unsafe thumbnail image path')
            if path.exists():
                if not path.is_file(): raise ValueError('Unsafe thumbnail image path')
                path.unlink()
        self.thread = Thread(target=self._run, name='ontovis-model-thumbnails', daemon=True) if start_worker else None
        if self.thread: self.thread.start()

    @staticmethod
    def _now(): return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _revision(): return 'model-thumbnail:' + uuid4().hex

    @staticmethod
    def _public(row):
        if row is None: return {'state': 'missing', 'thumbnailRevision': None, 'rendererVersion': RENDERER_VERSION}
        return {'state': row['state'], 'thumbnailRevision': row['revision'], 'rendererVersion': row['renderer_version'],
                'imageSha256': row['image_sha256'], 'bytes': row['bytes'], 'width': row['width'],
                'height': row['height'], 'errorCode': row['error_code']}

    def _identity(self, body, authorize):
        authorize()
        _uuid(body['modelVersionId']); _text(body['expectedContentRevision'])
        with self.library.connect() as db: value = self.models.content_identity(body['modelVersionId'], db)
        _require(value['sha256'] == body['expectedSha256']
                 and value['contentRevision'] == body['expectedContentRevision'], 'RESOURCE_CHANGED', 409)
        return value

    def describe(self, fingerprint):
        with self.library.connect() as db:
            return self._public(db.execute('select * from model_thumbnails where source_sha256=?', (fingerprint,)).fetchone())

    def attach(self, value):
        targets = [value]
        for item in value.get('items', []): targets.extend(item.get('versions', [item]))
        with self.library.connect() as db:
            for target in targets:
                if 'modelVersionId' in target and 'sha256' in target:
                    target['thumbnail'] = self._public(db.execute('select * from model_thumbnails where source_sha256=?', (target['sha256'],)).fetchone())
        return value

    def status(self, body, authorize):
        _fields(body, REFERENCE_FIELDS)
        value = self._identity(body, authorize)
        result = self.describe(value['sha256']); authorize()
        return result

    def ensure(self, body, actor, authorize):
        _fields(body, (*REFERENCE_FIELDS, 'expectedThumbnailRevision', 'clientRequestId'))
        actor = _text(actor); _uuid(body['clientRequestId'])
        _require(body['expectedThumbnailRevision'] is None or isinstance(body['expectedThumbnailRevision'], str))
        identity = self._identity(body, authorize)
        digest = hashlib.sha256(_canonical(body).encode()).hexdigest()
        fingerprint = identity['sha256']
        with self.condition, self.library.connect() as db:
            db.execute('begin immediate'); authorize()
            prior = db.execute('select * from model_thumbnail_requests where actor=? and request_id=?', (actor, body['clientRequestId'])).fetchone()
            if prior:
                _require(prior['payload_sha256'] == digest, 'REQUEST_CONFLICT', 409)
                return self._public(db.execute('select * from model_thumbnails where source_sha256=?', (prior['source_sha256'],)).fetchone())
            row = db.execute('select * from model_thumbnails where source_sha256=?', (fingerprint,)).fetchone()
            schedule = row is None or row['state'] == 'failed'
            if schedule:
                _require(not self.stopping, 'THUMBNAIL_INTERRUPTED', 503)
                _require(body['expectedThumbnailRevision'] == (row['revision'] if row else None), 'RESOURCE_CHANGED', 409)
                _require(row is not None or db.execute('select count(*) from model_thumbnails').fetchone()[0] < MAX_THUMBNAILS,
                         'THUMBNAIL_LIBRARY_FULL', 413)
                now, revision = self._now(), self._revision()
                if row is None:
                    db.execute('insert into model_thumbnails values (?,?,?,?,?,null,null,null,null,null,?,?,?)',
                        (fingerprint, identity['modelVersionId'], RENDERER_VERSION, revision, 'queued', actor, now, now))
                else:
                    db.execute("update model_thumbnails set model_version_id=?,revision=?,state='queued',error_code=null,actor=?,updated_at=? where source_sha256=?",
                        (identity['modelVersionId'], revision, actor, now, fingerprint))
            db.execute('insert into model_thumbnail_requests values (?,?,?,?,?)',
                (actor, body['clientRequestId'], digest, fingerprint, self._now()))
            authorize(); db.commit()
            if schedule:
                self.pending[fingerprint] = (dict(body), authorize)
                self.condition.notify_all()
            return self._public(db.execute('select * from model_thumbnails where source_sha256=?', (fingerprint,)).fetchone())

    def automatic(self, value, actor, authorize):
        identity = self.models.content_identity(value.get('modelVersionId') or value['versionId'])
        return self.ensure({'modelVersionId': identity['modelVersionId'], 'expectedContentRevision': identity['contentRevision'],
            'expectedSha256': identity['sha256'], 'expectedThumbnailRevision': self.describe(identity['sha256'])['thumbnailRevision'],
            'clientRequestId': str(uuid4())}, actor, authorize)

    def _process(self, fingerprint, body, authorize):
        work = self.root / 'temporary' / uuid4().hex
        work.mkdir(mode=0o700)
        target = self.root / 'files' / (fingerprint + '.png')
        published = False
        try:
            identity = self._identity(body, authorize)
            with self.library.connect() as db:
                db.execute('begin immediate'); authorize()
                row = db.execute('select * from model_thumbnails where source_sha256=?', (fingerprint,)).fetchone()
                _require(row is not None and row['state'] == 'queued', 'RESOURCE_CHANGED', 409)
                claimed_revision = self._revision()
                db.execute("update model_thumbnails set state='processing',revision=?,updated_at=? where source_sha256=?",
                           (claimed_revision, self._now(), fingerprint))
            with self.library.connect() as db:
                source = dict(db.execute('select id as modelVersionId,sha256,bytes from versions where id=?', (identity['modelVersionId'],)).fetchone())
            content = self.models._content(source)
            png = self.renderer(content, work)
            info = png_info(png)
            authorize()
            temporary = work / 'published.png'
            with temporary.open('xb') as stream:
                stream.write(png); stream.flush(); os.fsync(stream.fileno())
            with self.condition, self.library.connect() as db:
                db.execute('begin immediate'); authorize()
                _require(not self.stopping, 'THUMBNAIL_INTERRUPTED', 503)
                self._identity(body, authorize)
                _require(not target.exists() and not target.is_symlink(), 'THUMBNAIL_FILE_CHANGED', 409)
                os.replace(temporary, target); published = True; _sync_directory(target.parent)
                changed = db.execute("update model_thumbnails set state='ready',revision=?,image_sha256=?,bytes=?,width=?,height=?,error_code=null,updated_at=? where source_sha256=? and state='processing' and revision=?",
                    (self._revision(), info['imageSha256'], info['bytes'], SIDE, SIDE, self._now(), fingerprint, claimed_revision)).rowcount
                _require(changed == 1, 'RESOURCE_CHANGED', 409)
                authorize(); db.commit(); published = False
        finally:
            if published: target.unlink(missing_ok=True)
            shutil.rmtree(work)

    def _run(self):
        while True:
            with self.condition:
                while not self.pending and not self.stopping: self.condition.wait()
                if self.stopping: return
                fingerprint, (body, authorize) = self.pending.popitem(last=False)
            try: self._process(fingerprint, body, authorize)
            except Exception as error:
                code = error.code if isinstance(error, PreviewError) else 'THUMBNAIL_RENDER_FAILED'
                while True:
                    try:
                        with self.library.connect() as db:
                            db.execute("update model_thumbnails set state='failed',revision=?,error_code=?,updated_at=? where source_sha256=? and state in ('queued','processing')",
                                       (self._revision(), code, self._now(), fingerprint))
                        break
                    except sqlite3.OperationalError:
                        with self.condition:
                            if self.stopping: return
                            self.condition.wait(.25)

    def content(self, body, authorize):
        _fields(body, (*REFERENCE_FIELDS, 'expectedThumbnailRevision', 'expectedImageSha256'))
        identity = self._identity(body, authorize)
        value = self.describe(identity['sha256'])
        _require(value['state'] == 'ready' and value['thumbnailRevision'] == body['expectedThumbnailRevision']
                 and value['imageSha256'] == body['expectedImageSha256'], 'RESOURCE_CHANGED', 409)
        path = self.root / 'files' / (identity['sha256'] + '.png')
        _require(not self.root.is_symlink() and not path.parent.is_symlink() and not path.is_symlink()
                 and path.is_file() and path.stat().st_size == value['bytes'], 'RESOURCE_CHANGED', 409)
        data = path.read_bytes()
        _require(hashlib.sha256(data).hexdigest() == value['imageSha256'], 'RESOURCE_CHANGED', 409)
        png_info(data)
        authorize()
        return {'content': data, 'sha256': value['imageSha256']}

    def close(self):
        with self.condition: self.stopping = True; self.condition.notify_all()
        if hasattr(self.renderer, 'close'): self.renderer.close()
        if self.thread: self.thread.join(5)
