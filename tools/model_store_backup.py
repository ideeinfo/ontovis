"""Offline paired ModelLibrary/ModelAsset copies; never stop or switch services.

The operator must stop every writer. This tool checks source stability, but does
not detect arbitrary writers or provide an online database/files snapshot.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
from uuid import UUID


ROOTS = ('workbench-library', 'workbench-model')
FORMAT = 'ontovis-offline-paired-store-v1'
BASE_ARTIFACTS = {'heights.f64', 'mask.u8', 'positions.f32', 'triangles.u32', 'source.tif'}
ARTIFACTS = BASE_ARTIFACTS | {'cells.u8', 'cell-mask.u8'}


class BackupError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _require(value, code):
    if not value:
        raise BackupError(code)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def _uuid(value):
    return isinstance(value, str) and str(UUID(value)) == value


def _directory(value):
    path = Path(value)
    _require(path.is_absolute() and '..' not in path.parts, 'UNSAFE_PATH')
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        _require(stat.S_ISDIR(current.lstat().st_mode), 'UNSAFE_PATH')
    return path


def _open(path, flags, mode=0o600):
    """Open every component without following a link, including ancestors."""
    descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    if path == Path(path.anchor):
        return descriptor
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return os.open(path.name, flags | os.O_NOFOLLOW | os.O_NONBLOCK, mode, dir_fd=descriptor)
    finally:
        os.close(descriptor)


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _fingerprint(path):
    with os.fdopen(_open(path, os.O_RDONLY), 'rb') as file:
        before = os.fstat(file.fileno())
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, 'UNSAFE_PATH')
        digest = hashlib.sha256()
        size = 0
        for block in iter(lambda: file.read(1024 * 1024), b''):
            digest.update(block)
            size += len(block)
        after = os.fstat(file.fileno())
    _require(_identity(before) == _identity(after) == _identity(path.lstat()) and size == before.st_size, 'SOURCE_CHANGED')
    return {'kind': 'file', 'bytes': size, 'sha256': digest.hexdigest()}, _identity(after)


def _inventory(root):
    _directory(root)
    entries, identities, pending = {}, {}, [root]
    while pending:
        path = pending.pop()
        key = str(path.relative_to(root))
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            entries[key], identities[key] = {'kind': 'directory'}, _identity(info)
            descriptor = _open(path, os.O_RDONLY | os.O_DIRECTORY)
            try:
                _require(_identity(info) == _identity(os.fstat(descriptor)), 'SOURCE_CHANGED')
                pending.extend(path / name for name in sorted(os.listdir(descriptor)))
                _require(_identity(info) == _identity(os.fstat(descriptor)) ==
                         _identity(path.lstat()), 'SOURCE_CHANGED')
            finally:
                os.close(descriptor)
        else:
            _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'UNSAFE_PATH')
            entries[key], identities[key] = _fingerprint(path)
    return entries, identities


def _read_json(path):
    with os.fdopen(_open(path, os.O_RDONLY), 'rb') as file:
        return json.loads(file.read())


def _registered(entries, name, size, digest):
    _require(type(size) is int and size >= 0 and _sha(digest), 'INVALID_STORE')
    _require(entries.get(name) == {'kind': 'file', 'bytes': size, 'sha256': digest}, 'REGISTERED_FILE_CHANGED')


def _database(library, entries):
    for name in ('files', 'temporary'):
        _require(entries.get(name) == {'kind': 'directory'}, 'INVALID_STORE')
    _require(entries.get('library.sqlite3', {}).get('kind') == 'file', 'INVALID_STORE')
    _require(not any('library.sqlite3' + suffix in entries for suffix in ('-wal', '-shm', '-journal')), 'SIDECAR_UNSUPPORTED')
    database = library / 'library.sqlite3'
    with os.fdopen(_open(database, os.O_RDONLY), 'rb') as file:
        header = file.read(100)
    _require(header[:16] == b'SQLite format 3\x00' and header[18:20] == b'\x01\x01', 'STORE_FORMAT_UNSUPPORTED')
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=0.25)) as db:
        db.execute('pragma query_only=on')
        db.execute('begin')
        _require(db.execute('pragma integrity_check').fetchall() == [('ok',)], 'INVALID_DATABASE')
        _require(not db.execute('pragma foreign_key_check').fetchall(), 'INVALID_DATABASE')
        schema = db.execute('select type,name,tbl_name,sql from sqlite_master order by type,name').fetchall()
        tables = {}
        for kind, name, _, sql in schema:
            if kind != 'table':
                continue
            _require(sql is not None and not sql.lower().startswith('create virtual'), 'STORE_FORMAT_UNSUPPORTED')
            rows = db.execute('select * from "' + name.replace('"', '""') + '"')
            hashes = sorted(_digest([(type(value).__name__, value.hex() if isinstance(value, bytes) else value) for value in row]) for row in rows)
            tables[name] = {'rows': len(hashes), 'sha256': _digest(hashes)}
        scope = db.execute('select id,revision,project_code,context_id from library').fetchall()
        _require(len(scope) == 1 and scope[0][0] == 1 and type(scope[0][1]) is int and scope[0][1] >= 0, 'INVALID_STORE')
        _require(isinstance(scope[0][2], str) and scope[0][2] and _uuid(scope[0][3]), 'INVALID_STORE')
        for identifier, size, digest in db.execute('select id,bytes,sha256 from versions'):
            _require(_uuid(identifier), 'INVALID_STORE')
            _registered(entries, 'files/' + identifier + '.glb', size, digest)
        if 'terrain_versions' in tables:
            for identifier, source_sha, revision, report_text, report_sha, manifest_text, total in db.execute(
                    'select id,sha256,content_revision,report,report_sha256,manifest,total_bytes from terrain_versions'):
                _require(_uuid(identifier) and _sha(source_sha) and _sha(report_sha), 'INVALID_STORE')
                report, manifest = json.loads(report_text), json.loads(manifest_text)
                _require(type(report) is dict and type(manifest) is list, 'INVALID_STORE')
                ids = [item['artifactId'] for item in manifest]
                _require(len(ids) == len(set(ids)) and BASE_ARTIFACTS <= set(ids) <= ARTIFACTS, 'INVALID_STORE')
                _require(report.get('artifacts') == [item for item in manifest if item['artifactId'] != 'source.tif'], 'INVALID_STORE')
                base = 'terrains/versions/' + identifier + '/'
                report_name = base + 'derived/report.json'
                report_entry = entries.get(report_name, {})
                _registered(entries, report_name, report_entry.get('bytes'), report_sha)
                _require(_read_json(library / report_name) == report and revision == 'terrain-content:' + _digest(report), 'INVALID_STORE')
                for item in manifest:
                    name = base + ('' if item['artifactId'] == 'source.tif' else 'derived/') + item['artifactId']
                    _registered(entries, name, item['bytes'], item['sha256'])
                    if item['artifactId'] == 'source.tif':
                        _require(item['sha256'] == source_sha, 'INVALID_STORE')
                _require(type(total) is int and total == sum(item['bytes'] for item in manifest) + report_entry['bytes'], 'INVALID_STORE')
        registry = {'state': 'absent'}
        if 'legacy_scene_registry_state' in tables:
            rows = db.execute('select * from legacy_scene_registry_state').fetchall()
            _require(len(rows) == 1 and rows[0][0] == 1 and rows[0][1] == scope[0][2]
                     and rows[0][2] in ('unregistered', 'active'), 'INVALID_STORE')
            registry = {'state': rows[0][2], 'sha256': _digest(rows)}
        return {'schemaSha256': _digest(schema), 'tables': tables, 'registry': registry}, scope[0]


def _capture(library, model):
    try:
        libraries, library_ids = _inventory(library)
        models, model_ids = _inventory(model)
        database, scope = _database(library, libraries)
        config = _read_json(model / 'model.json')
        _require(config['schemaVersion'] == 1 and config['projectCode'] == scope[2]
                 and config['installationContextId'] == scope[3] and _sha(config['sha256']), 'INVALID_STORE')
        fixed = models.get('model.glb', {})
        _registered(models, 'model.glb', fixed.get('bytes'), config['sha256'])
        libraries_after, library_ids_after = _inventory(library)
        models_after, model_ids_after = _inventory(model)
        _require((libraries, library_ids, models, model_ids) ==
                 (libraries_after, library_ids_after, models_after, model_ids_after), 'SOURCE_CHANGED')
        return {'format': FORMAT, 'library': libraries, 'model': models, 'database': database}, (library_ids, model_ids)
    except BackupError:
        raise
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, IndexError, OverflowError):
        raise BackupError('INVALID_OR_UNSAFE_STORE') from None


def _destination(value, sources):
    destination = Path(value)
    _require(destination.is_absolute() and '..' not in destination.parts, 'UNSAFE_PATH')
    _directory(destination.parent)
    _require(not os.path.lexists(destination), 'DESTINATION_EXISTS')
    _require(all(not destination.is_relative_to(source) and not source.is_relative_to(destination) for source in sources), 'OVERLAPPING_PATHS')
    return destination


def _sync(path):
    descriptor = _open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _mkdir(path):
    descriptor = _open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.mkdir(path.name, mode=0o700, dir_fd=descriptor)
    finally:
        os.close(descriptor)


def _copy_file(source, target):
    with os.fdopen(_open(source, os.O_RDONLY), 'rb') as reader:
        _require(stat.S_ISREG(os.fstat(reader.fileno()).st_mode) and os.fstat(reader.fileno()).st_nlink == 1, 'UNSAFE_PATH')
        with os.fdopen(_open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL), 'wb') as writer:
            shutil.copyfileobj(reader, writer, 1024 * 1024)
            writer.flush()
            os.fsync(writer.fileno())


def _receipt(root, digest, report):
    return {'destination': str(root), 'manifestSha256': digest, 'database': report['database'],
            'fileCount': sum(item['kind'] == 'file' for group in ('library', 'model') for item in report[group].values()),
            'serviceStoppedDeclarationOnly': True, 'sourceChanged': False}


def _copy(library, model, destination, report, identities):
    _mkdir(destination)
    try:
        for source, name, group in zip((library, model), ROOTS, ('library', 'model')):
            target = destination / name
            _mkdir(target)
            for relative, entry in sorted(report[group].items(), key=lambda item: (len(Path(item[0]).parts), item[0])):
                if relative == '.':
                    continue
                if entry['kind'] == 'directory':
                    _mkdir(target / relative)
                else:
                    _copy_file(source / relative, target / relative)
            for relative, entry in sorted(report[group].items(), reverse=True):
                if entry['kind'] == 'directory':
                    _sync(target / relative)
        copied, _ = _capture(destination / ROOTS[0], destination / ROOTS[1])
        after, after_ids = _capture(library, model)
        _require(copied == report and after == report and after_ids == identities, 'SOURCE_CHANGED')
        data = _canonical(report)
        descriptor = _open(destination, os.O_RDONLY | os.O_DIRECTORY)
        try:
            flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
            with os.fdopen(os.open('manifest.partial', flags, 0o600, dir_fd=descriptor), 'w+b') as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
                metadata = os.fstat(file.fileno())
                os.link('manifest.partial', 'manifest.json', src_dir_fd=descriptor,
                        dst_dir_fd=descriptor, follow_symlinks=False)
                _sync(destination)
                _sync(destination.parent)
                final, final_ids = _capture(library, model)
                _require(final == report and final_ids == identities, 'SOURCE_CHANGED')
                current = destination.lstat()
                directory = os.fstat(descriptor)
                _require(stat.S_ISDIR(current.st_mode) and (current.st_dev, current.st_ino) ==
                         (directory.st_dev, directory.st_ino), 'DESTINATION_CHANGED')
                for name in ('manifest.partial', 'manifest.json'):
                    linked = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                    _require(stat.S_ISREG(linked.st_mode) and (linked.st_dev, linked.st_ino) ==
                             (metadata.st_dev, metadata.st_ino), 'DESTINATION_CHANGED')
                file.seek(0)
                _require(file.read() == data, 'DESTINATION_CHANGED')
                # Failed seals retain the partial name/two links; verify rejects
                # both. Remove only our metadata via the same pinned directory.
                os.unlink('manifest.partial', dir_fd=descriptor)
        finally:
            os.close(descriptor)
        return _receipt(destination, hashlib.sha256(data).hexdigest(), report)
    except BackupError:
        raise
    except (OSError, ValueError, TypeError):
        raise BackupError('COPY_FAILED_TARGET_INCOMPLETE') from None


def snapshot(library_root, model_root, destination, *, service_stopped=False):
    _require(service_stopped is True, 'OFFLINE_REQUIRED')
    try:
        library, model = _directory(library_root), _directory(model_root)
        _require(not library.is_relative_to(model) and not model.is_relative_to(library), 'OVERLAPPING_PATHS')
        destination = _destination(destination, (library, model))
        report, identities = _capture(library, model)
        return _copy(library, model, destination, report, identities)
    except OSError:
        raise BackupError('UNSAFE_PATH') from None


def _package(backup_root, expected_manifest_sha256):
    _require(_sha(expected_manifest_sha256), 'EXPECTED_MANIFEST_SHA_REQUIRED')
    try:
        root = _directory(backup_root)
        _require(set(os.listdir(root)) == set(ROOTS) | {'manifest.json'}, 'INCOMPLETE_OR_CHANGED_BACKUP')
        entry, _ = _fingerprint(root / 'manifest.json')
        _require(entry['sha256'] == expected_manifest_sha256, 'MANIFEST_CHANGED')
        expected = _read_json(root / 'manifest.json')
        actual, identities = _capture(root / ROOTS[0], root / ROOTS[1])
        _require(expected == actual, 'BACKUP_CHANGED')
        _require(_fingerprint(root / 'manifest.json')[0] == entry, 'MANIFEST_CHANGED')
        _require(set(os.listdir(root)) == set(ROOTS) | {'manifest.json'}, 'INCOMPLETE_OR_CHANGED_BACKUP')
        return root, actual, identities
    except BackupError:
        raise
    except (OSError, ValueError, TypeError):
        raise BackupError('INCOMPLETE_OR_UNSAFE_BACKUP') from None


def verify(backup_root, expected_manifest_sha256):
    root, report, _ = _package(backup_root, expected_manifest_sha256)
    return _receipt(root, expected_manifest_sha256, report)


def restore_new(backup_root, destination, expected_manifest_sha256, *, service_stopped=False):
    _require(service_stopped is True, 'OFFLINE_REQUIRED')
    root, report, identities = _package(backup_root, expected_manifest_sha256)
    try:
        destination = _destination(destination, (root,))
        return _copy(root / ROOTS[0], root / ROOTS[1], destination, report, identities)
    except OSError:
        raise BackupError('UNSAFE_PATH') from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('snapshot')
    create.add_argument('--library-root', required=True, type=Path)
    create.add_argument('--model-root', required=True, type=Path)
    create.add_argument('--destination', required=True, type=Path)
    create.add_argument('--service-stopped', required=True, action='store_true')
    for name in ('verify', 'restore-new'):
        command = commands.add_parser(name)
        command.add_argument('--backup-root', required=True, type=Path)
        command.add_argument('--expected-manifest-sha256', required=True)
        if name == 'restore-new':
            command.add_argument('--destination', required=True, type=Path)
            command.add_argument('--service-stopped', required=True, action='store_true')
    args = vars(parser.parse_args(argv))
    operation = args.pop('command')
    try:
        result = {'snapshot': snapshot, 'verify': verify, 'restore-new': restore_new}[operation](**args)
        print(_canonical(result).decode())
        return 0
    except BackupError as error:
        print(_canonical({'code': error.code, 'state': 'failed', 'sourceModifiedByTool': False,
                          'partialTargetMustNotBeUsed': True}).decode())
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
