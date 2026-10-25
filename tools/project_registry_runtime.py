"""Offline PG registry provisioning and paired snapshots into new directories only."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api import postgres_project_workspaces as runtime
from apps.api.storage_lease import storage_lease, StorageInUse
from tools import model_store_backup as paired, project_store_backup as backups
from tools import project_registry_postgres as migration


def _write(path, value):
    raw = paired._canonical(value)
    with os.fdopen(paired._open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL), 'wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    paired._sync(path.parent)
    return hashlib.sha256(raw).hexdigest()


def activate_new(backup_root, manifest_sha256, database_url, destination, *, service_stopped=False):
    """Provision a fresh runtime schema and a new paired copy of a verified backup.

    Filesystem/PG cannot commit atomically. The marker is written before PG commit;
    an interrupted attempt fails closed and must use a new directory/database.
    Existing schemas and directories are never replaced, even on retry.
    """
    paired._require(service_stopped, 'SERVICE_MUST_BE_STOPPED')
    backup = paired._directory(backup_root)
    target = paired._destination(destination, (backup,))
    before = paired._inventory(backup)
    report, registry, _ = migration._source_registry(backup, manifest_sha256)
    runtime.require(registry['shared_model_store'], 'REGISTRY_PAIRED_LIBRARY_REQUIRED')
    connection = runtime.RegistryConnection(database_url)
    try:
        with connection.transaction() as cursor:
            cursor.execute('select to_regnamespace(%s)', (runtime.SCHEMA,))
            runtime.require(cursor.fetchone()[0] is None, 'REGISTRY_TARGET_OCCUPIED')
            copied = backups.restore_new(backup, target, manifest_sha256, service_stopped=True)
            # The destination is now a runtime candidate, never a published backup.
            (target / 'manifest.json').unlink()
            projects, library = target / 'project-spaces', target / 'workbench-library'
            with storage_lease((projects, library)):
                store_id = str(uuid4())
                cursor.execute(runtime.DDL)
                for name, columns in migration.COLUMNS.items():
                    for row in registry[name]:
                        cursor.execute('insert into '+runtime.SCHEMA+'.'+name+' ('+','.join(columns)+') values ('
                                       + ','.join(['%s']*len(columns))+')', tuple(row[column] for column in columns))
                cursor.execute('insert into '+runtime.SCHEMA+'.runtime_binding values(1,%s,%s,%s)',
                               (store_id, runtime.root_identity(projects, library,
                                target / 'workbench-model' if report['legacy'] else None), manifest_sha256))
                runtime.profile(cursor)
                actual, _ = runtime.rows(cursor)
                runtime.require({name: actual[name] for name in migration.COLUMNS} == registry,
                                'REGISTRY_RESTORE_MISMATCH')
                paired._require(paired._inventory(backup) == before, 'SOURCE_CHANGED')
                _write(projects / runtime.MARKER, {'format': runtime.FORMAT, 'storeId': store_id,
                       'connectionId': registry['registry_meta'][0]['connection_id']})
                (projects / 'registry.sqlite3').unlink()
                paired._sync(projects)
        return {'status': 'postgres_registry_candidate', 'storeId': store_id,
                'sourceManifestSha256': manifest_sha256, 'registryDigest': paired._digest(registry),
                'spaces': copied['spaces'], 'fileCount': copied['fileCount'],
                'sourceBackupUnchanged': True, 'businessStorage': 'sqlite', 'serviceStarted': False}
    finally:
        connection.close()


def _runtime_rows(registry):
    with registry.connection.transaction(readonly=True) as cursor:
        runtime.profile(cursor)
        result, versions = runtime.rows(cursor)
    migration._registry({name: result[name] for name in migration.COLUMNS})
    return result, versions


def snapshot(project_root, destination, database_url, *, library_root, model_root=None, service_stopped=False):
    """Hold local and PG ownership while materializing a complete SQLite backup.

    Runtime's marker never enters the portable backup. Every non-registry file
    must match before/after and the existing verifier checks all scope/references.
    """
    paired._require(service_stopped, 'SERVICE_MUST_BE_STOPPED')
    projects, library = paired._directory(project_root), paired._directory(library_root)
    model = paired._directory(model_root) if model_root else None
    roots = tuple(path for path in (projects, library, model) if path is not None)
    paired._require(len(set(roots)) == len(roots) and all(not a.is_relative_to(b) for a in roots for b in roots if a != b),
                    'OVERLAPPING_PATHS')
    target = paired._destination(destination, roots)
    marker = runtime.read_marker(projects)
    try:
        with storage_lease((projects, library), shared=True):
            registry = runtime.PostgresProjectWorkspaces(projects, marker['connectionId'],
                legacy_root=library, model_root=model, database_url=database_url)
            try:
                original, versions = _runtime_rows(registry)
                fixed = {name: original[name] for name in migration.COLUMNS}
                legacy = any(row['storage_key'] == 'legacy' for row in fixed['project_workspaces'])
                paired._require(not legacy or model is not None, 'LEGACY_PAIR_REQUIRED')
                paired._require(legacy or model is None, 'UNREGISTERED_MODEL_STORE')
                before = {path: paired._inventory(path) for path in roots}
                paired._mkdir(target)
                for source, name in ((projects, 'project-spaces'), (library, 'workbench-library'), (model, 'workbench-model')):
                    if source is not None:
                        backups._copy_tree(source, target / name, before[source][0])
                copied_projects = target / 'project-spaces'
                (copied_projects / runtime.MARKER).unlink()
                migration._sqlite_registry(copied_projects / 'registry.sqlite3', fixed)
                expected = {key: value for key, value in before[projects][0].items() if key != runtime.MARKER}
                expected['registry.sqlite3'] = paired._fingerprint(copied_projects / 'registry.sqlite3')[0]
                paired._require(paired._inventory(copied_projects)[0] == expected, 'COPY_MISMATCH')
                for source, name in ((library, 'workbench-library'), (model, 'workbench-model')):
                    if source is not None:
                        paired._require(paired._inventory(target / name)[0] == before[source][0], 'COPY_MISMATCH')
                report, _ = backups._capture(copied_projects, target / 'workbench-library',
                                             target / 'workbench-model' if model else None)
                paired._require({path: paired._inventory(path) for path in roots} == before, 'SOURCE_CHANGED')
                runtime.require(_runtime_rows(registry) == (original, versions), 'REGISTRY_SOURCE_CHANGED')
                try:
                    digest = _write(target / 'manifest.json', report)
                    backups.verify(target, digest)
                except BaseException:
                    (target / 'manifest.json').unlink(missing_ok=True)
                    raise
                return {'status': 'paired_snapshot_from_postgres', 'manifestSha256': digest,
                        'storeId': marker['storeId'], 'registryDigest': paired._digest(fixed),
                        'spaces': len(report['spaces']), 'registryMaterializedAs': 'sqlite',
                        'fileCount': sum(info['kind'] == 'file' for entries, _ in before.values() for info in entries.values()),
                        'postgresWrites': 0, 'sourceUnchanged': True}
            finally:
                registry.close()
    except StorageInUse:
        raise paired.BackupError('SERVICE_MUST_BE_STOPPED') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('activate-new', 'snapshot'))
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--manifest-sha256')
    parser.add_argument('--project-root', type=Path)
    parser.add_argument('--library-root', type=Path)
    parser.add_argument('--model-root', type=Path)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--service-stopped', action='store_true')
    args = parser.parse_args()
    try:
        if args.action == 'activate-new':
            result = activate_new(args.backup, args.manifest_sha256, os.environ.get('ONTOVIS_REGISTRY_DSN'),
                                  args.destination, service_stopped=args.service_stopped)
        else:
            result = snapshot(args.project_root, args.destination, os.environ.get('ONTOVIS_REGISTRY_DSN'),
                library_root=args.library_root, model_root=args.model_root, service_stopped=args.service_stopped)
        print(json.dumps(result, ensure_ascii=False))
    except (PreviewError, paired.BackupError, migration.MigrationError) as error:
        parser.exit(2, error.code + '\n')
    except (OSError, ValueError, TypeError):
        parser.exit(2, 'REGISTRY_INPUT_UNAVAILABLE\n')


if __name__ == '__main__':
    main()
