"""Bounded resumable imagery reception; publication stays in ImageryLibrary."""
from contextlib import contextmanager
import hashlib
import json
import os
import shutil
import stat
from threading import Lock
import time
from uuid import uuid4

from .authority import PreviewError
from .imagery_library import MAX_BYTES, MAX_TOTAL_BYTES, metadata
from .terrain_library import _canonical, _require, _sync_directory, _uuid
from tools.model_probe import strict_json, ProbeError

CHUNK_BYTES = 256 * 1024
MAX_PENDING = 2
TTL_SECONDS = 24 * 60 * 60


def fingerprint(value):
    _require(type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value))
    return value


def regular(path):
    value = path.lstat()
    _require(stat.S_ISREG(value.st_mode) and value.st_nlink == 1, 'RESOURCE_CHANGED', 409)
    return value


class ImageryUploads:
    def __init__(self, imagery):
        self.imagery = imagery
        self.root = imagery.root / 'incoming'
        _require(not self.root.is_symlink(), 'RESOURCE_CHANGED', 409)
        _require(not self.root.exists() or self.root.is_dir(), 'RESOURCE_CHANGED', 409)
        self.lock = Lock()

    @contextmanager
    def guarded(self, authorize):
        authorize()
        _require(self.lock.acquire(blocking=False), 'IMAGERY_BUSY', 429)
        try:
            yield
            authorize()
        except OSError:
            raise PreviewError(503, 'IMAGERY_STORAGE_UNAVAILABLE') from None
        finally:
            self.lock.release()

    def load(self, identifier, actor=None):
        identifier = _uuid(identifier)
        folder = self.root / identifier
        _require(folder.exists(), 'NOT_FOUND_OR_FORBIDDEN', 404)
        _require(not folder.is_symlink() and folder.is_dir(), 'RESOURCE_CHANGED', 409)
        _require({p.name for p in folder.iterdir()} <= {'state.json', 'state.next', 'source.part'}, 'RESOURCE_CHANGED', 409)
        path = folder / 'state.json'
        _require(regular(path).st_size <= 16384, 'RESOURCE_CHANGED', 409)
        try:
            value = strict_json(path.read_bytes())
            _require(type(value) is dict and set(value) == {'schemaVersion', 'uploadId', 'actor', 'metadata',
                     'sha256', 'bytes', 'receivedBytes', 'uploadRevision', 'expiresAt', 'state'}, 'RESOURCE_CHANGED', 409)
            _require(type(value['schemaVersion']) is int and value['schemaVersion'] == 1 and value['uploadId'] == identifier
                     and type(value['actor']) is str and 0 < len(value['actor']) <= 200
                     and type(value['bytes']) is int and 8 <= value['bytes'] <= MAX_BYTES
                     and type(value['receivedBytes']) is int and 0 <= value['receivedBytes'] <= value['bytes']
                     and type(value['expiresAt']) is int and value['expiresAt'] > 0
                     and value['state'] in ('receiving', 'completed'), 'RESOURCE_CHANGED', 409)
            metadata(value['metadata']); fingerprint(value['sha256']); _uuid(value['uploadRevision'])
        except (ProbeError, KeyError, TypeError, ValueError):
            raise PreviewError(409, 'RESOURCE_CHANGED') from None
        if actor is not None:
            _require(value['actor'] == actor, 'NOT_FOUND_OR_FORBIDDEN', 404)
        source = folder / 'source.part'
        if source.exists() or source.is_symlink():
            size = regular(source).st_size
            _require(value['receivedBytes'] <= size <= min(value['bytes'], value['receivedBytes'] + CHUNK_BYTES),
                     'RESOURCE_CHANGED', 409)
        else:
            _require(value['state'] == 'completed', 'RESOURCE_CHANGED', 409)
        if (folder / 'state.next').exists() or (folder / 'state.next').is_symlink():
            _require(regular(folder / 'state.next').st_size <= 16384, 'RESOURCE_CHANGED', 409)
        return value

    def entries(self):
        return [self.load(folder.name) for folder in self.root.iterdir()] if self.root.exists() else []

    def save(self, value, folder=None):
        folder = self.root / value['uploadId'] if folder is None else folder
        temporary = folder / 'state.next'
        if temporary.exists() or temporary.is_symlink():
            regular(temporary); temporary.unlink()
        data = (_canonical(value) + '\n').encode()
        _require(len(data) <= 16384, 'IMAGERY_LIMIT_EXCEEDED', 413)
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as file:
            file.write(data); file.flush(); os.fsync(file.fileno())
        os.replace(temporary, folder / 'state.json')
        _sync_directory(folder)

    def public(self, value, actor, authorize):
        if value['state'] == 'completed' or value['receivedBytes'] == value['bytes']:
            result = self.imagery.upload_result(value['metadata'], value['sha256'], actor, authorize)
            if result['state'] == 'completed':
                return result
            _require(value['state'] != 'completed', 'RESOURCE_CHANGED', 409)
        return {key: value[key] for key in ('state', 'uploadId', 'metadata', 'sha256', 'bytes',
                                            'receivedBytes', 'uploadRevision', 'expiresAt')}

    def listing(self, actor, authorize):
        with self.guarded(authorize):
            result = [self.public(row, actor, authorize) for row in self.entries()
                      if row['actor'] == actor and row['state'] == 'receiving' and row['expiresAt'] > time.time()]
            return [row for row in result if row['state'] == 'receiving']

    def remove(self, value):
        # load() has checked every entry before removing this temporary copy.
        self.load(value['uploadId'], value['actor'])
        shutil.rmtree(self.root / value['uploadId'])
        _sync_directory(self.root)

    def start(self, payload, sha256, size, actor, authorize):
        payload = metadata(payload); fingerprint(sha256)
        _require(type(size) is int and 8 <= size <= MAX_BYTES, 'IMAGERY_LIMIT_EXCEEDED', 413)
        with self.guarded(authorize):
            result = self.imagery.upload_result(payload, sha256, actor, authorize)
            if result['state'] == 'completed':
                source = self.imagery.root / 'versions' / result['imageryVersionId'] / 'source.tif'
                _require(regular(source).st_size == size, 'REQUEST_CONFLICT', 409)
                return result
            rows = self.entries()
            for row in rows:
                if row['expiresAt'] <= time.time():
                    authorize(); self.remove(row)
                elif row['actor'] == actor and row['metadata']['clientRequestId'] == payload['clientRequestId']:
                    _require(row['metadata'] == payload and row['sha256'] == sha256 and row['bytes'] == size,
                             'REQUEST_CONFLICT', 409)
                    return self.public(row, actor, authorize)
                elif row['state'] == 'receiving' and row['receivedBytes'] == row['bytes']:
                    if self.public(row, row['actor'], authorize)['state'] == 'completed':
                        authorize(); row['state'] = 'completed'; self.save(row)
                        source = self.root / row['uploadId'] / 'source.part'
                        if source.exists(): source.unlink(); _sync_directory(source.parent)
            active = [row for row in rows if row['state'] == 'receiving' and row['expiresAt'] > time.time()]
            _require(len(active) < MAX_PENDING, 'IMAGERY_BUSY', 429)
            actual = sum(regular(p).st_size for p in self.imagery.root.rglob('*') if p.is_file() or p.is_symlink())
            reserved = sum(row['bytes'] - row['receivedBytes'] for row in active)
            _require(actual + reserved + size + MAX_BYTES <= MAX_TOTAL_BYTES, 'IMAGERY_LIMIT_EXCEEDED', 413)
            value = {'schemaVersion': 1, 'uploadId': str(uuid4()), 'actor': actor, 'metadata': payload,
                     'sha256': sha256, 'bytes': size, 'receivedBytes': 0, 'uploadRevision': str(uuid4()),
                     'expiresAt': int(time.time()) + TTL_SECONDS, 'state': 'receiving'}
            _require(len(_canonical(value).encode()) <= 16384 - 32, 'IMAGERY_LIMIT_EXCEEDED', 413)
            authorize()
            self.root.mkdir(mode=0o700, exist_ok=True)
            folder = self.root / value['uploadId']
            work = self.imagery.root / 'temporary' / value['uploadId']; work.mkdir(mode=0o700)
            try:
                with os.fdopen(os.open(work / 'source.part', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as file:
                    file.flush(); os.fsync(file.fileno())
                self.save(value, work); authorize()
                os.rename(work, folder); _sync_directory(self.root)
            finally:
                if work.exists(): shutil.rmtree(work)
            return self.public(value, actor, authorize)

    def current(self, identifier, actor):
        value = self.load(identifier, actor)
        _require(value['expiresAt'] > time.time(), 'IMAGERY_UPLOAD_EXPIRED', 410)
        return value

    def status(self, identifier, actor, authorize):
        with self.guarded(authorize):
            return self.public(self.current(identifier, actor), actor, authorize)

    def chunk(self, stream, length, payload, actor, authorize):
        _require(type(payload) is dict and set(payload) == {'uploadId', 'offset', 'expectedUploadRevision', 'expectedChunkSha256'})
        fingerprint(payload['expectedChunkSha256']); _uuid(payload['expectedUploadRevision'])
        offset = payload['offset']
        _require(type(offset) is int and offset >= 0 and type(length) is int and 1 <= length <= CHUNK_BYTES)
        with self.guarded(authorize):
            value = self.current(payload['uploadId'], actor)
            _require(value['state'] == 'receiving' and offset + length <= value['bytes'], 'IMAGERY_UPLOAD_CHANGED', 409)
            _require(offset <= value['receivedBytes'], 'IMAGERY_UPLOAD_CHANGED', 409)
            if offset == value['receivedBytes']:
                _require(payload['expectedUploadRevision'] == value['uploadRevision'], 'IMAGERY_UPLOAD_CHANGED', 409)
            data = bytearray()
            while len(data) < length:
                piece = stream.read(min(65536, length - len(data)))
                _require(type(piece) is bytes and 0 < len(piece) <= length - len(data), 'UNSUPPORTED_IMAGERY')
                data.extend(piece)
            _require(hashlib.sha256(data).hexdigest() == payload['expectedChunkSha256'], 'IMAGERY_CHUNK_CHANGED', 409)
            authorize()
            source = self.root / value['uploadId'] / 'source.part'
            regular(source)
            with source.open('r+b') as file:
                file.seek(offset)
                if offset < value['receivedBytes']:
                    _require(offset + length <= value['receivedBytes'] and file.read(length) == data, 'REQUEST_CONFLICT', 409)
                    return self.public(value, actor, authorize)
                # A crash before the atomic receipt leaves only an uncommitted tail.
                file.truncate(offset); file.write(data); file.flush(); os.fsync(file.fileno())
            authorize()
            value.update(receivedBytes=offset + length, uploadRevision=str(uuid4()))
            self.save(value)
            return self.public(value, actor, authorize)

    def complete(self, identifier, revision, actor, authorize):
        _uuid(revision)
        with self.guarded(authorize):
            value = self.current(identifier, actor)
            known = self.public(value, actor, authorize)
            if known['state'] == 'completed':
                return known
            _require(value['uploadRevision'] == revision, 'IMAGERY_UPLOAD_CHANGED', 409)
            _require(value['receivedBytes'] == value['bytes'], 'IMAGERY_UPLOAD_INCOMPLETE', 409)
            source = self.root / identifier / 'source.part'
            _require(regular(source).st_size == value['bytes'], 'RESOURCE_CHANGED', 409)
            _require(hashlib.sha256(source.read_bytes()).hexdigest() == value['sha256'], 'IMAGERY_CHUNK_CHANGED', 409)
            authorize()
            with source.open('rb') as stream:
                result = self.imagery.upload(stream, value['bytes'], value['metadata'], actor, authorize)
            value.update(state='completed', uploadRevision=str(uuid4()))
            self.save(value); source.unlink(); _sync_directory(source.parent)
            return {'state': 'completed', **result}

    def cancel(self, identifier, revision, actor, authorize):
        _uuid(revision)
        with self.guarded(authorize):
            value = self.current(identifier, actor)
            known = self.public(value, actor, authorize)
            if known['state'] == 'completed':
                return known
            _require(value['uploadRevision'] == revision, 'IMAGERY_UPLOAD_CHANGED', 409)
            authorize(); self.remove(value)
            return {'state': 'cancelled', 'uploadId': identifier}
