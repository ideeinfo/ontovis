"""Recoverable, owner-scoped Canvas deletion without changing content history."""
from __future__ import annotations

import hashlib
import json

from . import analysis_drafts as draft


def active_condition(store, alias='s'):
    if store.schema_version < 3:
        return 'true'
    return f"""coalesce((select state from {draft.SCHEMA}.analysis_lifecycle_events
        where session_id={alias}.session_id order by lifecycle_revision desc limit 1),'active')='active'"""


def change(store, actor_id, project_role, action, body, authorize):
    draft.identifier(actor_id); authorize()
    draft.require(project_role == 'admin', 'ANALYSIS_WRITE_FORBIDDEN', 403)
    draft.require(store.schema_version >= 3, 'ANALYSIS_LIFECYCLE_NOT_ENABLED', 503)
    draft.require(action in ('trash', 'untrash') and type(body) is dict and set(body) == {
        'analysisSessionId', 'expectedAnalysisRevision', 'expectedLifecycleRevision', 'requestId'})
    session_id = draft.identifier(body['analysisSessionId']); request_id = draft.identifier(body['requestId'])
    draft.require(type(body['expectedAnalysisRevision']) is int and 1 <= body['expectedAnalysisRevision'] <= 1000)
    draft.require(type(body['expectedLifecycleRevision']) is int and 0 <= body['expectedLifecycleRevision'] <= 1000)
    scope = (store.connection_id, store.project_code, actor_id, request_id)
    fingerprint = draft.digest({'action': action, 'body': body})
    timestamp = store.clock(); draft.utc(timestamp)
    with store.connection.transaction() as cursor:
        key = int.from_bytes(hashlib.sha256(draft.canonical(scope).encode()).digest()[:8], 'big', signed=True)
        cursor.execute('select pg_advisory_xact_lock(%s)', (key,))
        cursor.execute('select pg_advisory_xact_lock(%s)', (draft.WRITE_LOCK,))
        head = store._session(cursor, session_id, actor_id, lock=True)[0]
        cursor.execute(f'''select fingerprint,result_json from {draft.SCHEMA}.analysis_requests
            where connection_id=%s and project_code=%s and actor_id=%s and request_id=%s''', scope)
        replay = cursor.fetchone()
        if replay:
            draft.require(replay[0] == fingerprint, 'ANALYSIS_REQUEST_CONFLICT', 409)
            authorize(); return json.loads(replay[1])
        current = store.lifecycle(cursor, session_id)
        draft.require(head == body['expectedAnalysisRevision'], 'ANALYSIS_CHANGED', 409)
        draft.require(current['lifecycleRevision'] == body['expectedLifecycleRevision'], 'ANALYSIS_LIFECYCLE_CHANGED', 409)
        draft.require(current['lifecycle'] == ('active' if action == 'trash' else 'trashed'), 'ANALYSIS_LIFECYCLE_CHANGED', 409)
        draft.require(current['lifecycleRevision'] < 1000, 'ANALYSIS_LIFECYCLE_LIMIT', 413)
        cursor.execute(f'select count(*) from {draft.SCHEMA}.analysis_lifecycle_events')
        draft.require(cursor.fetchone()[0] < draft.MAX_STORE_REVISIONS, 'ANALYSIS_STORE_LIMIT', 413)
        cursor.execute(f'select count(*) from {draft.SCHEMA}.analysis_requests')
        draft.require(cursor.fetchone()[0] < draft.MAX_STORE_REVISIONS, 'ANALYSIS_STORE_LIMIT', 413)
        state = 'trashed' if action == 'trash' else 'active'
        revision = current['lifecycleRevision'] + 1
        cursor.execute(f'insert into {draft.SCHEMA}.analysis_lifecycle_events values(%s,%s,%s,%s,%s,%s,%s)',
            (session_id, revision, state, head, actor_id, request_id, timestamp))
        result = {'analysisSessionId': session_id, 'analysisRevision': head, 'lifecycle': state,
                  'lifecycleRevision': revision, 'operation': action}
        cursor.execute(f'insert into {draft.SCHEMA}.analysis_requests values(%s,%s,%s,%s,%s,%s,%s)',
            (*scope, fingerprint, draft.canonical(result), timestamp))
        authorize()
        return result
