"""Recover a fixed image's original upload metadata after a display-name rewrite."""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3

from apps.api.authority import PreviewError
from apps.api.imagery_library import MAX_BYTES, metadata
from apps.api.storage_lease import StorageInUse, storage_lease
from tools import model_store_backup as store
from tools.model_store_backup import _require


GUARDS = {
    'imagery_no_update': 'create trigger imagery_no_update before update on imagery_versions '
                         "begin select raise(abort, 'immutable imagery'); end",
    'imagery_no_delete': 'create trigger imagery_no_delete before delete on imagery_versions '
                         "begin select raise(abort, 'retained imagery'); end",
}


def _scope(db):
    library = db.execute('select project_code,context_id from library where id=1').fetchone()
    _require(library is not None, 'REPAIR_SCOPE_MISMATCH')
    has_workspace = db.execute("select 1 from sqlite_master where type='table' and name='workspace_scope'").fetchone()
    workspace = None
    if has_workspace:
        workspace = db.execute('select workspace_id,ontobase_connection_id,project_code,scope_version from workspace_scope where id=1').fetchone()
        _require(workspace is not None, 'REPAIR_SCOPE_MISMATCH')
    return library, workspace


def _image_and_request(db, version_id):
    image = db.execute('select * from imagery_versions where id=?', (version_id,)).fetchone()
    requests = db.execute('select * from imagery_requests where version_id=?', (version_id,)).fetchall()
    _require(image is not None and len(requests) == 1, 'REPAIR_ORIGINAL_UPLOAD_REQUIRED')
    request = dict(requests[0])
    payload = metadata(json.loads(image['metadata']))
    _require(store._canonical(payload).decode() == image['metadata'] == request['payload']
             and payload['clientRequestId'] == request['request_id']
             and image['sha256'] == request['input_sha256'], 'REPAIR_UPLOAD_MISMATCH')
    return dict(image), request, payload


def _guards(db):
    return dict(db.execute("select name,sql from sqlite_master where type='trigger' and tbl_name in ('imagery_versions','imagery_requests')"))


def _check_artifacts(library, image):
    texture = json.loads(image['manifest'])
    _require(type(texture) is dict and set(texture) == {'bytes', 'sha256', 'mediaType'}
             and texture['mediaType'] == 'image/png' and type(texture['bytes']) is int
             and 0 < texture['bytes'] <= MAX_BYTES and type(image['total_bytes']) is int
             and 8 <= image['total_bytes'] - texture['bytes'] <= MAX_BYTES, 'REPAIR_ARTIFACT_MISMATCH')
    directory = library / 'imagery' / 'versions' / image['id']
    for name, size, digest in (
        ('source.tif', image['total_bytes'] - texture['bytes'], image['sha256']),
        ('texture.png', texture['bytes'], texture['sha256']),
    ):
        info, _ = store._fingerprint(directory / name)
        store._registered({name: info}, name, size, digest)
    return texture


def repair(library_root, original_database, version_id, expected_revision, expected_metadata_sha256,
           *, apply=False, service_stopped=False):
    """Check one title-only change against its upload and commit both fields together."""
    _require(service_stopped, 'SERVICE_MUST_BE_STOPPED')
    _require(store._uuid(version_id) and store._sha(expected_metadata_sha256), 'REPAIR_EXPECTATION_REQUIRED')
    library = store._directory(library_root)
    target = library / 'library.sqlite3'
    original = Path(original_database)
    store._directory(original.parent)
    with storage_lease((library,)):
        for path in (target, original):
            store._fingerprint(path)
            _require(not any(os.path.lexists(path.with_name(path.name + suffix)) for suffix in ('-wal', '-shm', '-journal')),
                     'SIDECAR_UNSUPPORTED')
        _require(not target.samefile(original), 'REPAIR_ORIGINAL_UPLOAD_REQUIRED')
        mode = 'rw' if apply else 'ro'
        with (
            closing(sqlite3.connect(original.as_uri() + '?mode=ro', uri=True, timeout=0.25)) as saved,
            closing(sqlite3.connect(target.as_uri() + '?mode=' + mode, uri=True, timeout=0.25)) as db,
            db,
        ):
            saved.row_factory = db.row_factory = sqlite3.Row
            _require(all(connection.execute('pragma journal_mode').fetchone()[0] != 'wal'
                         for connection in (saved, db)), 'SIDECAR_UNSUPPORTED')
            saved.execute('begin')
            db.execute('pragma foreign_keys=on')
            db.execute('begin immediate' if apply else 'begin')
            _require(_scope(db) == _scope(saved), 'REPAIR_SCOPE_MISMATCH')
            image, request, current = _image_and_request(db, version_id)
            old_image, old_request, original_payload = _image_and_request(saved, version_id)
            _require(image['content_revision'] == expected_revision
                     and all(image[key] == old_image[key] for key in image if key not in ('name', 'metadata'))
                     and all(request[key] == old_request[key] for key in request if key != 'payload'), 'REPAIR_VERSION_MISMATCH')
            texture = _check_artifacts(library, image)
            report_sha = store._digest(json.loads(image['report']))
            original_revision = 'imagery:' + store._digest([image['sha256'], original_payload, report_sha, texture])
            _require(report_sha == image['report_sha256'] and original_revision == expected_revision,
                     'REPAIR_ORIGINAL_DIGEST_MISMATCH')
            guards = _guards(db)
            _require({name: ' '.join(sql.lower().split()) for name, sql in guards.items()} == GUARDS,
                     'REPAIR_IMMUTABILITY_GUARD_MISMATCH')
            current_sha = store._digest(current)
            status = 'already_repaired'
            if current != original_payload:
                _require(current_sha == expected_metadata_sha256, 'REPAIR_METADATA_CHANGED')
                _require(current['displayName'] == image['name'] and original_payload['displayName'] == old_image['name']
                         and {key for key in current if current[key] != original_payload[key]} == {'displayName'},
                         'REPAIR_NOT_A_TITLE_CHANGE')
                status = 'ready'
                if apply:
                    # SQLite DDL participates in this transaction. Failure restores the guard and both rows.
                    db.execute('drop trigger imagery_no_update')
                    db.execute('update imagery_versions set metadata=? where id=?', (old_image['metadata'], version_id))
                    db.execute(guards['imagery_no_update'])
                    db.execute('update imagery_requests set payload=? where actor=? and request_id=?',
                               (old_request['payload'], request['actor'], request['request_id']))
                    updated, replay, _ = _image_and_request(db, version_id)
                    _require(updated == dict(image, metadata=old_image['metadata']) and replay == old_request
                             and _guards(db) == guards and not db.execute('pragma foreign_key_check').fetchone(),
                             'REPAIR_VERIFICATION_FAILED')
                    status = 'repaired'
            return {'status': status, 'imageryVersionId': version_id, 'contentRevision': expected_revision,
                    'displayName': image['name'], 'previousMetadataSha256': current_sha,
                    'originalMetadataSha256': store._digest(original_payload)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library-root', required=True, type=Path)
    parser.add_argument('--original-database', required=True, type=Path)
    parser.add_argument('--version-id', required=True)
    parser.add_argument('--expected-revision', required=True)
    parser.add_argument('--expected-metadata-sha256', required=True)
    parser.add_argument('--service-stopped', action='store_true')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        result = repair(args.library_root, args.original_database, args.version_id, args.expected_revision,
                        args.expected_metadata_sha256, apply=args.apply, service_stopped=args.service_stopped)
    except (PreviewError, StorageInUse, sqlite3.Error, OSError, TypeError, ValueError) as error:
        print(json.dumps({'error': getattr(error, 'code', 'IMAGERY_REPAIR_FAILED')}))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
