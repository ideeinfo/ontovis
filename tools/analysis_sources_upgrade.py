"""Offline v1-to-v2 analysis migration, preserving every existing analysis row."""
from __future__ import annotations

import argparse
import os

from apps.api import analysis_drafts as draft
from apps.api.storage_lease import storage_lease


def upgrade(database_url, expected_store_id, roots, *, service_stopped=False):
    draft.require(service_stopped, 'SERVICE_MUST_BE_STOPPED', 409)
    draft.identifier(expected_store_id)
    with storage_lease(roots, shared=False):
        connection = draft.AnalysisConnection(database_url)
        try:
            with connection.transaction() as cursor:
                cursor.execute('select pg_advisory_xact_lock(%s)', (draft.WRITE_LOCK,))
                version = draft.profile(cursor)
                cursor.execute(f'select store_id::text from {draft.SCHEMA}.store_meta where id=1')
                draft.require(cursor.fetchone()[0] == expected_store_id, 'ANALYSIS_STORE_SCOPE_MISMATCH', 409)
                if version == 2:
                    return {'schemaVersion': 2, 'changed': False, 'storeId': expected_store_id}
                cursor.execute('lock table '+','.join(draft.SCHEMA+'.'+n for n in draft.V1_COLUMNS)+' in access exclusive mode nowait')
                cursor.execute(draft.EVIDENCE_DDL)
                cursor.execute(f'alter table {draft.SCHEMA}.store_meta drop constraint store_meta_schema_version_check')
                cursor.execute(f'drop trigger immutable_analysis_meta on {draft.SCHEMA}.store_meta')
                cursor.execute(f'update {draft.SCHEMA}.store_meta set schema_version=2 where id=1')
                cursor.execute(f'alter table {draft.SCHEMA}.store_meta add constraint store_meta_schema_version_check check(schema_version=2)')
                cursor.execute(f'create trigger immutable_analysis_meta before update or delete on {draft.SCHEMA}.store_meta for each row execute function {draft.SCHEMA}.immutable_record()')
                draft.require(draft.profile(cursor) == 2)
                return {'schemaVersion': 2, 'changed': True, 'storeId': expected_store_id}
        finally:
            connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-env', default='ONTOVIS_REGISTRY_DSN')
    parser.add_argument('--expected-store-id', required=True)
    parser.add_argument('--private-root', action='append', required=True)
    parser.add_argument('--service-stopped', action='store_true')
    args = parser.parse_args()
    try:
        import json
        print(json.dumps(upgrade(os.environ.get(args.database_env), args.expected_store_id, args.private_root,
                                 service_stopped=args.service_stopped)))
        return 0
    except Exception as error:
        print('{"error":"'+getattr(error, 'code', 'ANALYSIS_UPGRADE_FAILED')+'"}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
