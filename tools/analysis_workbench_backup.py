"""Offline candidate: preserve analysis drafts with the complete PG workbench.

Both schemas use one dedicated ONTOVis database. Recovery never starts a service;
filesystem and SQL cannot commit atomically, so incomplete targets are retained
without a recovery receipt and must not be reused.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from apps.api import analysis_drafts as draft, postgres_project_workspaces as registry
from apps.api.authority import PreviewError
from tools import analysis_draft_backup as analysis, model_store_backup as files
from tools import project_registry_runtime as runtime, project_registry_postgres as migration

FORMAT = 'ontovis-analysis-workbench-backup-v1'
RECOVERY_FORMAT = 'ontovis-analysis-workbench-recovery-v1'
RESTORE_LOCK = int.from_bytes(hashlib.sha256(FORMAT.encode()).digest()[:8], 'big', signed=True)


def _paired(workbench, workbench_sha, package):
    report, rows, _ = migration._source_registry(workbench, workbench_sha)
    draft.require(rows['registry_meta'][0]['connection_id'] == package['connectionId'],
                  'ANALYSIS_PAIR_SCOPE_MISMATCH', 409)
    projects = {row['project_code'] for row in rows['project_workspaces']}
    draft.require(all(row['project_code'] in projects for row in package['tables']['analysis_sessions']),
                  'ANALYSIS_PROJECT_NOT_REGISTERED', 409)
    sessions = {row['session_id']: row for row in package['tables']['analysis_sessions']}
    revisions = {(row['session_id'], row['revision']): row for row in package['tables']['analysis_revisions']}
    libraries = {row['project_code']: Path(workbench)/('workbench-library' if row['storage_key'] == 'legacy'
        else 'project-spaces/libraries/'+row['storage_key'])/'library.sqlite3' for row in rows['project_workspaces']}
    def database(path):
        return closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True))
    for source in package['tables'].get('analysis_evidence_refs', []):
        descriptor = json.loads(source['descriptor_json']); kind = source['source_kind']
        if kind == 'work_order':
            path = libraries[sessions[source['session_id']]['project_code']]
            draft.require(path.is_file(), 'ANALYSIS_PAIR_SOURCE_MISMATCH', 409)
            with database(path) as db:
                exists = db.execute("select 1 from sqlite_master where name='work_order_snapshots' and type='table'").fetchone()
                value = db.execute('select snapshot_json,content_sha256 from work_order_snapshots where order_id=? and order_revision=?',
                    (descriptor['orderId'], descriptor['orderRevision'])).fetchone() if exists else None
                draft.require(value and value[1] == descriptor['snapshotSha256']
                    and analysis.sha(value[0].encode()) == value[1], 'ANALYSIS_PAIR_SOURCE_MISMATCH', 409)
        elif kind == 'model':
            with database(Path(workbench)/'workbench-library/library.sqlite3') as db:
                value = db.execute('select p.asset_id,p.content_revision,v.sha256 from project_model_versions p join versions v on v.id=p.version_id where p.version_id=?',
                    (descriptor['modelVersionId'],)).fetchone()
                draft.require(value == (descriptor['modelAssetId'], descriptor['contentRevision'], descriptor['sha256']),
                              'ANALYSIS_PAIR_SOURCE_MISMATCH', 409)
    for project, path in libraries.items():
        if not path.is_file(): continue
        with database(path) as db:
            if not db.execute("select 1 from sqlite_master where name='work_order_analysis_links' and type='table'").fetchone(): continue
            for order, order_revision, session_id, revision, digest in db.execute('select * from work_order_analysis_links'):
                session = sessions.get(session_id); saved = revisions.get((session_id, revision))
                draft.require(session and saved and session['project_code'] == project and saved['content_sha256'] == digest,
                              'ANALYSIS_PAIR_LINK_MISMATCH', 409)
                event = db.execute('select action,actor from work_order_events where order_id=? and revision=?', (order, order_revision)).fetchone()
                draft.require(event == ('link_analysis', session['owner_id']), 'ANALYSIS_PAIR_LINK_MISMATCH', 409)
    return report


def verify(root, manifest_sha256):
    root = analysis._safe_directory(root)
    analysis.hex_digest(manifest_sha256)
    raw = analysis._read(root/'manifest.json', 4096)
    draft.require(analysis.sha(raw) == manifest_sha256, 'ANALYSIS_MANIFEST_CHANGED', 409)
    try:
        value = json.loads(raw)
    except (ValueError, TypeError, RecursionError):
        raise PreviewError(422, 'ANALYSIS_PACKAGE_INVALID') from None
    draft.require(type(value) is dict and set(value) == {'format', 'connectionId', 'sourceAnalysisStoreId',
                  'workbenchManifestSha256', 'analysisManifestSha256'} and value['format'] == FORMAT
                  and draft.canonical(value).encode() == raw, 'ANALYSIS_PACKAGE_INVALID', 409)
    draft.require({path.name for path in root.iterdir()} == {'manifest.json', 'workbench', 'analysis'},
                  'ANALYSIS_PACKAGE_INVALID', 409)
    package = analysis.verified_package(root/'analysis', value['analysisManifestSha256'])
    draft.require((value['connectionId'], value['sourceAnalysisStoreId']) ==
                  (package['connectionId'], package['sourceStoreId']), 'ANALYSIS_PAIR_SCOPE_MISMATCH', 409)
    report = _paired(root/'workbench', value['workbenchManifestSha256'], package)
    return value, report, package


def snapshot(project_root, destination, database_url, *, library_root, model_root=None, service_stopped=False):
    files._require(service_stopped, 'SERVICE_MUST_BE_STOPPED')
    roots = tuple(files._directory(path) for path in (project_root, library_root, model_root) if path is not None)
    target = files._destination(destination, roots)
    connection = draft.AnalysisConnection(database_url)
    try:
        with connection.transaction() as cursor:
            version = draft.profile(cursor)
            # These locks also block non-cooperating SQL writes while the paired
            # local files and registry are copied by the existing offline tool.
            columns = draft.V1_COLUMNS if version == 1 else draft.COLUMNS
            cursor.execute('lock table '+','.join(draft.SCHEMA+'.'+name for name in columns)+' in share mode nowait')
            original = analysis.export_package(database_url)
            analysis._safe_directory(target, new=True)
            try:
                workbench = runtime.snapshot(project_root, target/'workbench', database_url,
                    library_root=library_root, model_root=model_root, service_stopped=True,
                    _analysis_store_id=original['sourceStoreId'])
                _paired(target/'workbench', workbench['manifestSha256'], original)
                saved = analysis.snapshot(database_url, target/'analysis')
                draft.require(analysis.export_package(database_url) == original, 'ANALYSIS_SOURCE_CHANGED', 409)
                value = {'format': FORMAT, 'connectionId': original['connectionId'],
                         'sourceAnalysisStoreId': original['sourceStoreId'],
                         'workbenchManifestSha256': workbench['manifestSha256'],
                         'analysisManifestSha256': saved['manifestSha256']}
                raw = draft.canonical(value).encode()
                analysis._write_new(target/'manifest.json', raw); files._sync(target)
                verify(target, analysis.sha(raw))
                return {'manifestSha256': analysis.sha(raw), 'spaces': workbench['spaces'],
                        'fileCount': workbench['fileCount'], 'analysisCounts': saved['counts'],
                        'sourceUnchanged': True, 'serviceStarted': False}
            except BaseException:
                (target/'manifest.json').unlink(missing_ok=True)
                raise
    finally:
        connection.close()


def restore_new(root, manifest_sha256, database_url, destination, *, service_stopped=False):
    files._require(service_stopped, 'SERVICE_MUST_BE_STOPPED')
    root = analysis._safe_directory(root)
    target = files._destination(destination, (root,))
    value, _, _ = verify(root, manifest_sha256)
    original = files._inventory(root)
    connection = draft.AnalysisConnection(database_url)
    try:
        with connection.transaction() as cursor:
            cursor.execute('select pg_try_advisory_xact_lock(%s)', (RESTORE_LOCK,))
            draft.require(cursor.fetchone()[0], 'ANALYSIS_RESTORE_IN_USE', 409)
            for schema in (draft.SCHEMA, registry.SCHEMA):
                cursor.execute('select to_regnamespace(%s)', (schema,))
                draft.require(cursor.fetchone()[0] is None, 'ANALYSIS_TARGET_OCCUPIED', 409)
            analysis._safe_directory(target, new=True)
            try:
                workbench = runtime.activate_new(root/'workbench', value['workbenchManifestSha256'],
                    database_url, target/'workbench', service_stopped=True)
                restored = analysis.restore_new(root/'analysis', value['analysisManifestSha256'], database_url)
                draft.require(files._inventory(root) == original, 'ANALYSIS_SOURCE_CHANGED', 409)
                receipt = {'format': RECOVERY_FORMAT, 'status': 'recovered_not_activated',
                           'sourceManifestSha256': manifest_sha256, 'connectionId': value['connectionId'],
                           'registryStoreId': workbench['storeId'], 'analysisStoreId': restored['storeId'],
                           'analysisCounts': restored['counts'], 'spaces': workbench['spaces'],
                           'fileCount': workbench['fileCount'], 'serviceStarted': False}
                analysis._write_new(target/'recovery.json', draft.canonical(receipt).encode()); files._sync(target)
                return receipt
            except BaseException:
                (target/'recovery.json').unlink(missing_ok=True)
                raise
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('snapshot', 'verify', 'restore-new'))
    parser.add_argument('--database-env', default='ONTOVIS_REGISTRY_DSN')
    parser.add_argument('--project-root', type=Path)
    parser.add_argument('--library-root', type=Path)
    parser.add_argument('--model-root', type=Path)
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--destination', type=Path)
    parser.add_argument('--manifest-sha256')
    parser.add_argument('--service-stopped', action='store_true')
    args = parser.parse_args()
    try:
        if args.action == 'verify':
            _, report, package = verify(args.backup, args.manifest_sha256)
            result = {'verified': True, 'spaces': len(report['spaces']),
                      'analysisSessions': len(package['tables']['analysis_sessions'])}
        elif args.action == 'snapshot':
            result = snapshot(args.project_root, args.destination, os.environ.get(args.database_env),
                library_root=args.library_root, model_root=args.model_root, service_stopped=args.service_stopped)
        else:
            result = restore_new(args.backup, args.manifest_sha256, os.environ.get(args.database_env),
                                 args.destination, service_stopped=args.service_stopped)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (PreviewError, files.BackupError, migration.MigrationError, OSError, ValueError, TypeError) as error:
        print(json.dumps({'error': getattr(error, 'code', 'ANALYSIS_PAIR_IO_FAILED')}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
