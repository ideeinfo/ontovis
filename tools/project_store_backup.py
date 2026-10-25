"""Offline project registry and every private project store, with optional legacy pair."""
from __future__ import annotations

from contextlib import closing
import argparse
from pathlib import Path
import os
import json
import sqlite3
from uuid import UUID

from tools import model_store_backup as paired
from apps.api.storage_lease import storage_lease, StorageInUse

FORMAT = 'ontovis-offline-project-stores-v1'


def _capture(projects, library=None, model=None):
    entries, identities = paired._inventory(projects)
    paired._require('registry.sqlite3' in entries, 'INVALID_PROJECT_REGISTRY')
    db = sqlite3.connect((projects / 'registry.sqlite3').as_uri() + '?mode=ro', uri=True)
    try:
        paired._require(db.execute('pragma quick_check').fetchall() == [('ok',)], 'INVALID_PROJECT_REGISTRY')
        meta = db.execute('select schema_version,connection_id from registry_meta').fetchall()
        paired._require(len(meta) == 1 and meta[0][0] == 1 and meta[0][1], 'INVALID_PROJECT_REGISTRY')
        rows = db.execute('select workspace_id,ontobase_connection_id,project_code,storage_key,legacy_context_id,state from project_workspaces order by workspace_id').fetchall()
        shared_registered = db.execute("select 1 from sqlite_master where name='shared_model_store'").fetchone() is not None
        if shared_registered:
            paired._require(library is not None and db.execute('select connection_id,scope_version from shared_model_store').fetchall()
                            == [(meta[0][1], 1)], 'SHARED_MODEL_STORE_REQUIRED')
    finally:
        db.close()
    spaces, keys, legacy, roots = {}, set(), None, []
    for identifier, connection, code, key, context, state in rows:
        paired._require(str(UUID(identifier)) == identifier and connection == meta[0][1]
                         and code and key not in keys and state in ('ready','preparing','blocked'), 'INVALID_PROJECT_REGISTRY')
        keys.add(key)
        if state != 'ready':
            # Preserve incomplete/conflicted spaces as evidence, without declaring them usable.
            if key == 'legacy':
                paired._require(library is not None and model is not None, 'LEGACY_PAIR_REQUIRED')
                legacy = {'format': paired.FORMAT, 'library': paired._inventory(library)[0],
                          'model': paired._inventory(model)[0], 'database': None}
            else:
                paired._require(str(UUID(key)) == key, 'INVALID_PROJECT_REGISTRY')
            spaces[identifier] = {'projectRef': {'ontobaseConnectionId': connection, 'projectCode': code},
                'storageKey': key, 'state': state, 'database': None}
            continue
        if key == 'legacy':
            paired._require(library is not None and model is not None and legacy is None, 'LEGACY_PAIR_REQUIRED')
            legacy, _ = paired._capture(library, model)
            root = library
        else:
            paired._require(str(UUID(key)) == key, 'INVALID_PROJECT_REGISTRY')
            root = projects / 'libraries' / key
        files, _ = paired._inventory(root)
        database, scope = paired._database(root, files)
        roots.append(root)
        paired._require((scope[2], scope[3]) == (code, context), 'PROJECT_SCOPE_MISMATCH')
        conn = sqlite3.connect((root / 'library.sqlite3').as_uri() + '?mode=ro', uri=True)
        try:
            actual = conn.execute('select workspace_id,ontobase_connection_id,project_code from workspace_scope').fetchall()
            paired._require(actual == [(identifier, connection, code)], 'PROJECT_SCOPE_MISMATCH')
        finally:
            conn.close()
        spaces[identifier] = {'projectRef': {'ontobaseConnectionId': connection, 'projectCode': code},
                              'storageKey': key, 'state': state, 'database': database}
    if 'libraries' in entries:
        actual = {p.name for p in (projects / 'libraries').iterdir()}
        ready = {space['storageKey'] for space in spaces.values() if space['state'] == 'ready' and space['storageKey'] != 'legacy'}
        paired._require(ready <= actual <= keys - {'legacy'}, 'UNREGISTERED_PROJECT_STORE')
    shared = None
    if library is not None:
        with closing(sqlite3.connect((library / 'library.sqlite3').as_uri() + '?mode=ro', uri=True)) as db:
            if db.execute("select 1 from sqlite_master where name='shared_model_scope'").fetchone():
                paired._require(db.execute('select connection_id,scope_version from shared_model_scope').fetchall()
                                == [(meta[0][1], 1)], 'SHARED_MODEL_SCOPE_MISMATCH')
                shared = {'root': 'legacy' if legacy is not None else 'library', 'connectionId': meta[0][1]}
                models = {r[0]: (r[1], r[2] or 'sha256:' + r[1], r[3]) for r in db.execute('''select v.id,v.sha256,p.content_revision,p.asset_id
                    from versions v left join project_model_versions p on p.version_id=v.id''')}
        if shared is not None and legacy is None:
            files, _ = paired._inventory(library)
            shared['library'] = files
            shared['database'], _ = paired._database(library, files)
    paired._require(not shared_registered or shared is not None, 'SHARED_MODEL_STORE_REQUIRED')
    for root in roots:
        with closing(sqlite3.connect((root / 'library.sqlite3').as_uri() + '?mode=ro', uri=True)) as db:
            if not db.execute("select 1 from sqlite_master where name='scene_model_scope'").fetchone():
                continue
            paired._require(shared is not None, 'SHARED_MODEL_STORE_REQUIRED')
            paired._require(db.execute('select connection_id,scope_version from scene_model_scope').fetchall()
                            == [(shared['connectionId'], 1)], 'SHARED_MODEL_SCOPE_MISMATCH')
            for snapshot, references in db.execute('select snapshot,resource_refs from scene_revisions'):
                refs = json.loads(references)
                paired._require({item['modelVersionId'] for item in json.loads(snapshot)['instances']}
                                == {ref['modelVersionId'] for ref in refs}, 'INVALID_SHARED_MODEL_REFERENCE')
                for ref in refs:
                    paired._require(models.get(ref['modelVersionId']) == (ref['sha256'], ref['contentRevision'], ref.get('modelAssetId')),
                                    'INVALID_SHARED_MODEL_REFERENCE')
    after, after_ids = paired._inventory(projects)
    paired._require((entries, identities) == (after, after_ids), 'SOURCE_CHANGED')
    result = {'format': FORMAT, 'projects': entries, 'spaces': spaces, 'legacy': legacy}
    if shared is not None:
        result['sharedModels'] = shared
    return result, identities


def _copy_tree(source, target, entries):
    paired._mkdir(target)
    for name, info in sorted(entries.items(), key=lambda pair: (len(Path(pair[0]).parts), pair[0])):
        if name == '.':
            continue
        if info['kind'] == 'directory':
            paired._mkdir(target / name)
        else:
            paired._copy_file(source / name, target / name)
    paired._sync(target)


def _copy(projects, library, model, destination, report, identities):
    paired._mkdir(destination)
    _copy_tree(projects, destination / 'project-spaces', report['projects'])
    if report['legacy'] is not None:
        _copy_tree(library, destination / 'workbench-library', report['legacy']['library'])
        _copy_tree(model, destination / 'workbench-model', report['legacy']['model'])
    elif report.get('sharedModels'):
        _copy_tree(library, destination / 'workbench-library', report['sharedModels']['library'])
    actual, after_ids = _capture(projects, library, model)
    paired._require(report == actual and identities == after_ids, 'SOURCE_CHANGED')
    restored, _ = _capture(destination / 'project-spaces',
        destination / 'workbench-library' if report['legacy'] or report.get('sharedModels') else None,
        destination / 'workbench-model' if report['legacy'] else None)
    paired._require(restored == report, 'COPY_MISMATCH')
    raw = paired._canonical(report)
    with os.fdopen(paired._open(destination / 'manifest.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL), 'wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    paired._sync(destination)
    return {'manifestSha256': __import__('hashlib').sha256(raw).hexdigest(), 'spaces': len(report['spaces']),
            'fileCount': sum(v['kind'] == 'file' for v in report['projects'].values())
                + sum(v['kind'] == 'file' for group in ('library', 'model') for v in (report['legacy'] or {}).get(group, {}).values())
                + sum(v['kind'] == 'file' for v in (report.get('sharedModels') or {}).get('library', {}).values())}


def snapshot(project_root, destination, *, library_root=None, model_root=None, service_stopped=False):
    paired._require(service_stopped, 'SERVICE_MUST_BE_STOPPED')
    projects = paired._directory(project_root)
    library = paired._directory(library_root) if library_root else None
    model = paired._directory(model_root) if model_root else None
    roots = tuple(p for p in (projects, library, model) if p is not None)
    paired._require(all(not a.is_relative_to(b) for a in roots for b in roots if a != b), 'OVERLAPPING_PATHS')
    destination = paired._destination(destination, roots)
    try:
        with storage_lease(tuple(path for path in (projects, library) if path is not None), shared=True):
            report, identities = _capture(projects, library, model)
            return _copy(projects, library, model, destination, report, identities)
    except StorageInUse:
        raise paired.BackupError('SERVICE_MUST_BE_STOPPED') from None


def verify(backup_root, expected_manifest_sha256):
    backup = paired._directory(backup_root)
    paired._require(paired._sha(expected_manifest_sha256), 'INVALID_MANIFEST_SHA256')
    data = (backup / 'manifest.json').read_bytes()
    paired._require(__import__('hashlib').sha256(data).hexdigest() == expected_manifest_sha256, 'MANIFEST_MISMATCH')
    report = paired._read_json(backup / 'manifest.json')
    paired._require(report.get('format') == FORMAT, 'STORE_FORMAT_UNSUPPORTED')
    actual, _ = _capture(backup / 'project-spaces', backup / 'workbench-library' if report['legacy'] or report.get('sharedModels') else None,
                         backup / 'workbench-model' if report['legacy'] else None)
    paired._require(actual == report, 'COPY_MISMATCH')
    return report


def restore_new(backup_root, destination, expected_manifest_sha256, *, service_stopped=False):
    paired._require(service_stopped, 'SERVICE_MUST_BE_STOPPED')
    backup = paired._directory(backup_root)
    report = verify(backup, expected_manifest_sha256)
    target = paired._destination(destination, (backup,))
    projects = backup / 'project-spaces'
    library = backup / 'workbench-library' if report['legacy'] or report.get('sharedModels') else None
    model = backup / 'workbench-model' if report['legacy'] else None
    _, identities = _capture(projects, library, model)
    return _copy(projects, library, model, target, report, identities)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('snapshot', 'verify', 'restore-new'))
    parser.add_argument('--project-root', type=Path)
    parser.add_argument('--library-root', type=Path)
    parser.add_argument('--model-root', type=Path)
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--destination', type=Path)
    parser.add_argument('--manifest-sha256')
    parser.add_argument('--service-stopped', action='store_true')
    args = parser.parse_args()
    if args.action == 'snapshot':
        result = snapshot(args.project_root, args.destination, library_root=args.library_root,
                          model_root=args.model_root, service_stopped=args.service_stopped)
    elif args.action == 'restore-new':
        result = restore_new(args.backup, args.destination, args.manifest_sha256, service_stopped=args.service_stopped)
    else:
        report = verify(args.backup, args.manifest_sha256)
        result = {'verified': True, 'spaces': len(report['spaces'])}
    print(__import__('json').dumps(result))


if __name__ == '__main__':
    main()
