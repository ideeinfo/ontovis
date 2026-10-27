"""Snapshot and restore the isolated manual-analysis storage candidate.

This is not the whole-workbench paired backup. Fixed source descriptors are
included; source files and the live project registry remain in the paired store.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from uuid import uuid4

from apps.api import analysis_drafts as draft
from apps.api.authority import PreviewError

MAX_PACKAGE_BYTES = 48 * 1024 * 1024
MANIFEST_FORMAT = 'ontovis-analysis-draft-snapshot-v1'


def package_profile(package):
    draft.require(type(package.get('format')) is str)
    version = {draft.FORMAT_V1: 1, draft.FORMAT: 2, draft.FORMAT_V3: 3}.get(package.get('format'))
    draft.require(version is not None)
    return version, draft.columns_for(version)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def hex_digest(value):
    draft.require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None)


def validate_package(package):
    draft.require(type(package) is dict and set(package) == {'format', 'sourceStoreId', 'connectionId', 'tables'})
    version, columns_by_table = package_profile(package)
    draft.identifier(package['sourceStoreId']); draft.text(package['connectionId'])
    tables = package['tables']
    draft.require(type(tables) is dict and set(tables) == set(columns_by_table))
    for name, columns in columns_by_table.items():
        rows = tables[name]
        draft.require(type(rows) is list and len(rows) <= 10000, 'ANALYSIS_PACKAGE_LIMIT', 413)
        draft.require(all(type(row) is dict and set(row) == set(columns) for row in rows))
    meta = tables['store_meta']
    draft.require(len(meta) == 1 and type(meta[0]['id']) is int and meta[0]['id'] == 1
                  and type(meta[0]['schema_version']) is int and meta[0]['schema_version'] == version
                  and meta[0]['connection_id'] == package['connectionId'] and meta[0]['store_id'] == package['sourceStoreId'])
    sessions, revisions, requests = {}, {}, set()
    for row in tables['analysis_sessions']:
        key = draft.identifier(row['session_id']); draft.identifier(row['owner_id'])
        draft.require(key not in sessions and row['connection_id'] == package['connectionId'])
        draft.text(row['project_code']); draft.text(row['title'])
        draft.require(type(row['head_revision']) is int and 1 <= row['head_revision'] <= 1000)
        draft.utc(row['created_at']); draft.utc(row['updated_at']); sessions[key] = row
    for row in tables['analysis_revisions']:
        draft.identifier(row['session_id'])
        owner = sessions.get(row['session_id'])
        draft.require(owner is not None and type(row['revision']) is int and 1 <= row['revision'] <= owner['head_revision'])
        key = (row['session_id'], row['revision'])
        draft.require(key not in revisions and row['actor_id'] == owner['owner_id'])
        draft.utc(row['created_at']); hex_digest(row['content_sha256'])
        draft.require(type(row['snapshot_json']) is str and len(row['snapshot_json'].encode()) <= draft.MAX_BYTES)
        try:
            snapshot = json.loads(row['snapshot_json'])
        except (TypeError, ValueError, RecursionError):
            raise PreviewError(422, 'ANALYSIS_PACKAGE_INVALID') from None
        raw = draft.validate_snapshot(snapshot, package['connectionId'], owner['project_code'])
        draft.require(raw == row['snapshot_json'] and sha(raw.encode()) == row['content_sha256'])
        draft.require(row['operation'] in ('create', 'save', 'restore'))
        draft.require((row['revision'] == 1) == (row['operation'] == 'create'))
        if row['operation'] == 'restore':
            draft.require(type(row['restored_from']) is int and 1 <= row['restored_from'] < row['revision'])
        else:
            draft.require(row['restored_from'] is None)
        revisions[key] = row
    for key, row in revisions.items():
        if row['operation'] == 'restore':
            source = revisions.get((row['session_id'], row['restored_from']))
            draft.require(source is not None and source['snapshot_json'] == row['snapshot_json'])
    draft.require(sum(len(row['snapshot_json'].encode()) for row in revisions.values()) <= draft.MAX_STORE_BYTES,
                  'ANALYSIS_PACKAGE_LIMIT', 413)
    for key, row in sessions.items():
        draft.require(all((key, revision) in revisions for revision in range(1, row['head_revision'] + 1)))
        head = json.loads(revisions[(key, row['head_revision'])]['snapshot_json'])
        draft.require(head['title'] == row['title'] and head['status'] == row['status'])
    lifecycle_events, lifecycle_receipts = {}, set()
    if version >= 3:
        for row in tables['analysis_lifecycle_events']:
            owner = sessions.get(row['session_id'])
            draft.require(owner is not None and row['actor_id'] == owner['owner_id'])
            draft.identifier(row['request_id']); draft.utc(row['created_at'])
            revision = row['lifecycle_revision']
            draft.require(type(revision) is int and 1 <= revision <= 1000)
            draft.require(type(row['analysis_revision']) is int and (row['session_id'], row['analysis_revision']) in revisions)
            key = (row['session_id'], revision)
            draft.require(key not in lifecycle_events and row['state'] == ('trashed' if revision % 2 else 'active'))
            lifecycle_events[key] = row
        for (session_id, revision), row in lifecycle_events.items():
            draft.require(all((session_id, n) in lifecycle_events for n in range(1, revision)))
            if revision > 1:
                draft.require(lifecycle_events[(session_id, revision-1)]['analysis_revision'] <= row['analysis_revision'])
    seen_receipts = set()
    for row in tables['analysis_requests']:
        draft.require(row['connection_id'] == package['connectionId'])
        draft.identifier(row['request_id']); draft.identifier(row['actor_id']); draft.text(row['project_code'])
        draft.utc(row['created_at']); hex_digest(row['fingerprint'])
        key = (row['connection_id'], row['project_code'], row['actor_id'], row['request_id'])
        draft.require(key not in requests); requests.add(key)
        draft.require(type(row['result_json']) is str and len(row['result_json'].encode()) <= 2048)
        try:
            result = json.loads(row['result_json'])
        except (TypeError, ValueError, RecursionError):
            raise PreviewError(422, 'ANALYSIS_PACKAGE_INVALID') from None
        if version >= 3 and isinstance(result, dict) and result.get('operation') in ('trash', 'untrash'):
            draft.require(set(result) == {'analysisSessionId', 'analysisRevision', 'lifecycle', 'lifecycleRevision', 'operation'}
                          and draft.canonical(result) == row['result_json'])
            draft.require(type(result['lifecycleRevision']) is int and type(result['analysisRevision']) is int)
            key = (result['analysisSessionId'], result['lifecycleRevision'])
            event = lifecycle_events.get(key); owner = sessions.get(result['analysisSessionId'])
            draft.require(event and owner and key not in lifecycle_receipts
                and owner['owner_id'] == row['actor_id'] and owner['project_code'] == row['project_code']
                and event['request_id'] == row['request_id'] and event['analysis_revision'] == result['analysisRevision']
                and event['state'] == result['lifecycle']
                and result['operation'] == ('trash' if event['state'] == 'trashed' else 'untrash'))
            lifecycle_receipts.add(key)
            continue
        if version>=2 and isinstance(result,dict) and result.get('operation')=='evidence/register':
            draft.require(set(result)=={'analysisSessionId','operation','evidenceRefId','sourceKind','sourceRevision'}
                and draft.canonical(result)==row['result_json'])
            owner=sessions.get(result['analysisSessionId'])
            source=next((r for r in tables['analysis_evidence_refs'] if r['evidence_ref_id']==result['evidenceRefId']),None)
            draft.require(owner and source and owner['owner_id']==row['actor_id'] and owner['project_code']==row['project_code']
                and source['session_id']==result['analysisSessionId'] and source['actor_id']==row['actor_id']
                and source['source_kind']==result['sourceKind'] and source['descriptor_sha256']==result['sourceRevision'])
            continue
        draft.require(type(result) is dict and set(result) == {'analysisSessionId', 'analysisRevision',
                      'contentSha256', 'operation', 'restoredFromRevision'} and draft.canonical(result) == row['result_json'])
        draft.require(type(result['analysisSessionId']) is str and type(result['analysisRevision']) is int)
        owner = sessions.get(result['analysisSessionId'])
        version_key = (result['analysisSessionId'], result['analysisRevision'])
        revision = revisions.get(version_key)
        draft.require(owner is not None and revision is not None and version_key not in seen_receipts)
        draft.require(owner['owner_id'] == row['actor_id'] and owner['project_code'] == row['project_code'])
        draft.require(result['contentSha256'] == revision['content_sha256'] and result['operation'] == revision['operation']
                      and result['restoredFromRevision'] == revision['restored_from'])
        seen_receipts.add(version_key)
    draft.require(seen_receipts == set(revisions))
    draft.require(lifecycle_receipts == set(lifecycle_events))
    if version >= 2:
        from apps.api.analysis_evidence import validate_descriptor, MAX_SOURCE_BYTES
        ids, source_requests, counts = set(), set(), {}
        used = 0
        for row in tables['analysis_evidence_refs']:
            key = draft.identifier(row['evidence_ref_id']); draft.identifier(row['request_id'])
            owner = sessions.get(row['session_id'])
            draft.require(owner is not None and owner['owner_id'] == row['actor_id'])
            request = (row['session_id'], row['request_id'])
            draft.require(key not in ids and request not in source_requests)
            ids.add(key); source_requests.add(request)
            counts[row['session_id']] = counts.get(row['session_id'], 0) + 1
            draft.require(counts[row['session_id']] <= 100, 'ANALYSIS_SOURCE_LIMIT', 413)
            draft.utc(row['created_at']); hex_digest(row['request_fingerprint']); hex_digest(row['descriptor_sha256'])
            try:
                raw = validate_descriptor(row['source_kind'], json.loads(row['descriptor_json']))
            except (ValueError, TypeError, RecursionError):
                raise PreviewError(422, 'ANALYSIS_PACKAGE_INVALID') from None
            draft.require(raw == row['descriptor_json'] and sha(raw.encode()) == row['descriptor_sha256'])
            used += len(raw.encode())
        draft.require(used <= MAX_SOURCE_BYTES, 'ANALYSIS_PACKAGE_LIMIT', 413)
        from apps.api.analysis_canvas import validate_registered
        references = {}
        for row in tables['analysis_evidence_refs']:
            references.setdefault(row['session_id'],{})[row['evidence_ref_id']] = (
                row['evidence_ref_id'],row['source_kind'],row['descriptor_sha256'],row['descriptor_json'])
        for (session_id,_), row in revisions.items():
            snapshot=json.loads(row['snapshot_json'])
            if snapshot['schemaVersion']!=2:continue
            origin=snapshot.get('inheritedFrom'); original=None
            if origin:
                owner=sessions[session_id]; source=sessions.get(origin['analysisSessionId'])
                saved=revisions.get((origin['analysisSessionId'],origin['analysisRevision']))
                draft.require(source and saved and source['owner_id']==owner['owner_id']
                    and source['project_code']==owner['project_code'] and saved['content_sha256']==origin['contentSha256'],
                    'ANALYSIS_PAIR_SOURCE_MISMATCH',409)
                original=json.loads(saved['snapshot_json'])
            validate_registered(snapshot,references.get(session_id,{}),original)
    raw = draft.canonical(package).encode()
    draft.require(len(raw) <= MAX_PACKAGE_BYTES, 'ANALYSIS_PACKAGE_LIMIT', 413)
    return raw


def export_package(database_url):
    connection = draft.AnalysisConnection(database_url)
    try:
        with connection.transaction(readonly=True) as cursor:
            version = draft.profile(cursor)
            columns_by_table = draft.columns_for(version)
            tables = {}
            for name in columns_by_table:
                cursor.execute(f'select count(*) from {draft.SCHEMA}.{name}')
                draft.require(cursor.fetchone()[0] <= 10000, 'ANALYSIS_PACKAGE_LIMIT', 413)
            cursor.execute(f'select coalesce(sum(octet_length(snapshot_json)),0) from {draft.SCHEMA}.analysis_revisions')
            draft.require(cursor.fetchone()[0] <= draft.MAX_STORE_BYTES, 'ANALYSIS_PACKAGE_LIMIT', 413)
            for name in columns_by_table:
                cursor.execute(f'select to_jsonb(t) from {draft.SCHEMA}.{name} t order by to_jsonb(t)::text')
                tables[name] = [row[0] for row in cursor.fetchall()]
            draft.require(len(tables['store_meta']) == 1, 'ANALYSIS_STORAGE_INVALID', 409)
            meta = tables['store_meta'][0]
            package = {'format': {1: draft.FORMAT_V1, 2: draft.FORMAT, 3: draft.FORMAT_V3}[version], 'sourceStoreId': meta['store_id'], 'connectionId': meta['connection_id'], 'tables': tables}
            validate_package(package)
            return package
    finally:
        connection.close()


def _safe_directory(path, new=False):
    path = Path(path).absolute()
    draft.require(not any(parent.is_symlink() for parent in (path, *path.parents)), 'ANALYSIS_PATH_INVALID', 409)
    if new:
        draft.require(not path.exists(), 'ANALYSIS_TARGET_OCCUPIED', 409)
        path.mkdir(mode=0o700)
    draft.require(path.is_dir(), 'ANALYSIS_PATH_INVALID', 409)
    return path


def _write_new(path, raw):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())


def _read(path, limit):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
        info = os.fstat(stream.fileno())
        draft.require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= limit, 'ANALYSIS_PACKAGE_INVALID', 409)
        raw = stream.read(limit + 1)
    draft.require(len(raw) <= limit, 'ANALYSIS_PACKAGE_LIMIT', 413)
    return raw


def snapshot(database_url, destination):
    package = export_package(database_url)
    raw = validate_package(package)
    root = _safe_directory(destination, new=True)
    _write_new(root/'analysis.json', raw)
    manifest = {'format': MANIFEST_FORMAT, 'contentSha256': sha(raw), 'bytes': len(raw),
                'sourceStoreId': package['sourceStoreId'], 'connectionId': package['connectionId'],
                'counts': {name: len(rows) for name, rows in package['tables'].items()}}
    encoded = draft.canonical(manifest).encode()
    _write_new(root/'manifest.json', encoded)
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)
    return {'manifestSha256': sha(encoded), **manifest}


def verified_package(root, expected_manifest_sha256):
    hex_digest(expected_manifest_sha256)
    root = _safe_directory(root)
    manifest_raw, raw = _read(root/'manifest.json', 4096), _read(root/'analysis.json', MAX_PACKAGE_BYTES)
    draft.require(sha(manifest_raw) == expected_manifest_sha256, 'ANALYSIS_MANIFEST_CHANGED', 409)
    try:
        manifest, package = json.loads(manifest_raw), json.loads(raw)
    except (ValueError, TypeError, RecursionError):
        raise PreviewError(422, 'ANALYSIS_PACKAGE_INVALID') from None
    draft.require(type(manifest) is dict and set(manifest) == {'format', 'contentSha256', 'bytes', 'sourceStoreId', 'connectionId', 'counts'})
    draft.require(manifest['format'] == MANIFEST_FORMAT and draft.canonical(manifest).encode() == manifest_raw)
    draft.require(type(manifest['bytes']) is int and manifest['bytes'] == len(raw) and manifest['contentSha256'] == sha(raw), 'ANALYSIS_CONTENT_CHANGED', 409)
    draft.require(type(manifest['counts']) is dict and all(type(value) is int for value in manifest['counts'].values()))
    checked = validate_package(package)
    draft.require(checked == raw and manifest['sourceStoreId'] == package['sourceStoreId']
                  and manifest['connectionId'] == package['connectionId']
                  and manifest['counts'] == {name: len(rows) for name, rows in package['tables'].items()})
    return package


def restore_new(root, expected_manifest_sha256, database_url):
    package = verified_package(root, expected_manifest_sha256)
    connection = draft.AnalysisConnection(database_url)
    try:
        with connection.transaction() as cursor:
            cursor.execute('select to_regnamespace(%s)', (draft.SCHEMA,))
            draft.require(cursor.fetchone()[0] is None, 'ANALYSIS_TARGET_OCCUPIED', 409)
            version, columns_by_table = package_profile(package)
            cursor.execute({1: draft.DDL_V1, 2: draft.DDL, 3: draft.DDL_V3}[version])
            store_id = str(uuid4())
            cursor.execute(f'insert into {draft.SCHEMA}.store_meta values(1,%s,%s,%s)', (version, package['connectionId'], store_id))
            for name in tuple(columns_by_table)[1:]:
                columns = columns_by_table[name]
                for row in package['tables'][name]:
                    cursor.execute(f'insert into {draft.SCHEMA}.{name} ('+','.join(columns)+') values ('+','.join(['%s']*len(columns))+')', tuple(row[column] for column in columns))
            draft.profile(cursor)
            # Verify actual rows, preserving canonical JSON text and fixed IDs.
            for name in tuple(columns_by_table)[1:]:
                cursor.execute(f'select to_jsonb(t) from {draft.SCHEMA}.{name} t order by to_jsonb(t)::text')
                actual = sorted((draft.canonical(row[0]) for row in cursor.fetchall()))
                draft.require(actual == sorted(draft.canonical(row) for row in package['tables'][name]), 'ANALYSIS_RESTORE_MISMATCH', 409)
        return {'storeId': store_id, 'sourceStoreId': package['sourceStoreId'], 'connectionId': package['connectionId'],
                'manifestSha256': expected_manifest_sha256, 'counts': {name: len(rows) for name, rows in package['tables'].items()}}
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-env', default='ONTOVIS_ANALYSIS_DSN')
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init'); init.add_argument('--connection-id', required=True)
    snap = sub.add_parser('snapshot'); snap.add_argument('--destination', required=True)
    restore = sub.add_parser('restore'); restore.add_argument('--source', required=True); restore.add_argument('--manifest-sha256', required=True)
    args = parser.parse_args()
    try:
        dsn = os.environ.get(args.database_env)
        draft.require(bool(dsn), 'ANALYSIS_DATABASE_REQUIRED', 503)
        if args.command == 'init': result = draft.provision(dsn, args.connection_id)
        elif args.command == 'snapshot': result = snapshot(dsn, args.destination)
        else: result = restore_new(args.source, args.manifest_sha256, dsn)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (PreviewError, OSError) as error:
        print(json.dumps({'error': getattr(error, 'code', 'ANALYSIS_IO_FAILED')}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
