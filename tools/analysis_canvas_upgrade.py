"""Offline Q23 query-index installation; business rows and store identity stay intact."""
from __future__ import annotations
import argparse
import json
import os
from apps.api import analysis_drafts as draft
from apps.api.storage_lease import storage_lease


def upgrade(database_url, expected_store_id, roots, *, service_stopped=False):
    draft.require(service_stopped,'SERVICE_MUST_BE_STOPPED',409)
    draft.identifier(expected_store_id)
    with storage_lease(roots,shared=False):
        connection=draft.AnalysisConnection(database_url)
        try:
            with connection.transaction() as cursor:
                cursor.execute('select pg_advisory_xact_lock(%s)',(draft.WRITE_LOCK,))
                version=draft.profile(cursor)
                draft.require(version>=2,'ANALYSIS_SOURCES_NOT_ENABLED',409)
                cursor.execute(f'select store_id::text from {draft.SCHEMA}.store_meta where id=1')
                draft.require(cursor.fetchone()[0]==expected_store_id,'ANALYSIS_STORE_SCOPE_MISMATCH',409)
                cursor.execute('select to_regclass(%s)',(draft.SCHEMA+'.analysis_fault_context',))
                changed=cursor.fetchone()[0] is None
                cursor.execute(draft.CANVAS_INDEX_DDL)
                return {'storeId':expected_store_id,'schemaVersion':version,'indexReady':True,'changed':changed}
        finally:connection.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-env',default='ONTOVIS_REGISTRY_DSN')
    parser.add_argument('--expected-store-id',required=True)
    parser.add_argument('--private-root',action='append',required=True)
    parser.add_argument('--service-stopped',action='store_true')
    args=parser.parse_args()
    try:print(json.dumps(upgrade(os.environ.get(args.database_env),args.expected_store_id,args.private_root,service_stopped=args.service_stopped)));return 0
    except Exception as error:print(json.dumps({'error':getattr(error,'code','ANALYSIS_UPGRADE_FAILED')}));return 1

if __name__=='__main__':raise SystemExit(main())
