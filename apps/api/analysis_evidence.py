"""Immutable, owner-scoped source handles prepared for Canvas source cards."""
from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from . import analysis_drafts as draft

KINDS = ('object', 'drawing', 'document', 'photo', 'model', 'work_order', 'alarm', 'trend')
MAX_SOURCE_BYTES = 8 * 1024 * 1024
SELECTION = {'entityUid', 'installationContextId', 'expectedEntityRevision', 'expectedHierarchyRevision'}
PHOTO = {'evidenceRef', 'expectedSourceRevision', 'expectedContentVersionId', 'expectedSourceSha256', 'expectedDisplayRevision'}
DRAWING = {'evidenceRef', 'expectedSourceRevision', 'expectedContentSha256'}


def sha(value):
    draft.require(type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value))
    return value


def validate_descriptor(kind, value):
    draft.require(kind in KINDS and type(value) is dict)
    fields = {
        'object': SELECTION, 'drawing': SELECTION | DRAWING,
        'document': {'documentId', 'contentVersionId', 'sourceSha256', 'pageNumber'},
        'photo': SELECTION | PHOTO,
        'model': {'modelAssetId', 'modelVersionId', 'contentRevision', 'sha256'},
        'work_order': {'orderId', 'orderRevision', 'snapshotSha256'},
        'alarm': {'datasetId', 'datasetRevision', 'eventId'},
        'trend': {'datasetId', 'datasetRevision', 'metricId', 'timeFrom', 'timeTo'},
    }[kind]
    if kind == 'drawing' and 'drawingUid' in value:
        fields = {'drawingUid', 'expectedContentSha256'}
    if kind == 'photo' and 'photoPurpose' in value:
        fields |= {'photoPurpose'}
        draft.require(value['photoPurpose'] in ('object_location', 'field_record'))
        if value['photoPurpose'] == 'field_record':
            draft.require(value.get('installationContextId') is not None, 'EQUIPMENT_REQUIRED', 422)
    if kind == 'document' and 'knowledgeReleaseId' in value:
        fields |= {'knowledgeReleaseId', 'knowledgeNodeId'}
    if kind == 'model' and 'configurationRefs' in value:
        fields |= {'configurationRefs'}
        refs=value['configurationRefs']
        draft.require(type(refs) is list and len(refs)<=50)
        for ref in refs:
            draft.require(type(ref) is dict and set(ref)=={'configurationId','configurationRevision','equipmentEntityUids'})
            draft.identifier(ref['configurationId']);draft.text(ref['configurationRevision'],100)
            draft.require(type(ref['equipmentEntityUids']) is list and len(ref['equipmentEntityUids'])<=500)
            draft.require(all(type(uid) is str for uid in ref['equipmentEntityUids']))
            draft.require(len(set(ref['equipmentEntityUids']))==len(ref['equipmentEntityUids']))
            for uid in ref['equipmentEntityUids']:draft.text(uid,512)
    draft.require(set(value) == fields)
    for key, item in value.items():
        if key == 'configurationRefs':continue
        if key in ('installationContextId', 'expectedHierarchyRevision') and item is None:
            continue
        if key == 'pageNumber':
            draft.require(type(item) is int and 1 <= item <= 10000)
        elif key == 'orderRevision':
            draft.require(type(item) is int and 1 <= item <= 100)
        elif key in ('sha256', 'sourceSha256', 'snapshotSha256', 'expectedSourceRevision', 'expectedSourceSha256', 'expectedDisplayRevision', 'expectedContentSha256'):
            sha(item)
        else:
            draft.text(item, 512)
    if kind in ('object', 'photo') or kind == 'drawing' and 'drawingUid' not in value:
        draft.require((value['installationContextId'] is None) == (value['expectedHierarchyRevision'] is None))
    if kind == 'model':
        draft.identifier(value['modelAssetId']); draft.identifier(value['modelVersionId'])
    if kind == 'document':
        draft.identifier(value['documentId']); draft.identifier(value['contentVersionId'])
        if 'knowledgeReleaseId' in value: draft.identifier(value['knowledgeReleaseId'])
    if kind == 'trend':
        draft.require(draft.utc(value['timeFrom']) < draft.utc(value['timeTo']))
    raw = draft.canonical(value)
    draft.require(len(raw.encode()) <= 16384, 'ANALYSIS_SIZE_LIMIT', 413)
    return raw


class AnalysisEvidence:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def public(row):
        return {'evidenceRefId': row[0], 'sourceKind': row[3], 'sourceRevision': row[5]}

    def _row(self, cursor, session_id, actor_id, *, evidence_id=None, request_id=None):
        self.store._session(cursor, session_id, actor_id)
        condition, value = ('evidence_ref_id', evidence_id) if evidence_id else ('request_id', request_id)
        draft.identifier(value)
        cursor.execute(f'''select evidence_ref_id::text,request_id::text,request_fingerprint,source_kind,
            descriptor_json,descriptor_sha256 from {draft.SCHEMA}.analysis_evidence_refs
            where session_id=%s and {condition}=%s''', (session_id, value))
        return cursor.fetchone()

    def register(self, actor_id, body, authorize, resolve):
        draft.require(self.store.schema_version >= 2, 'ANALYSIS_SOURCES_NOT_ENABLED', 503)
        draft.require(type(body) is dict and set(body) == {'analysisSessionId', 'expectedAnalysisRevision', 'requestId', 'sourceKind', 'selector'})
        session_id = draft.identifier(body['analysisSessionId']); request_id = draft.identifier(body['requestId'])
        draft.require(type(body['expectedAnalysisRevision']) is int and 1 <= body['expectedAnalysisRevision'] <= 1000)
        draft.require(body['sourceKind'] in KINDS and type(body['selector']) is dict)
        fingerprint = draft.digest(body); authorize()
        scope=(self.store.connection_id,self.store.project_code,actor_id,request_id)
        def alias(cursor):
            cursor.execute(f'select fingerprint,result_json from {draft.SCHEMA}.analysis_requests where connection_id=%s and project_code=%s and actor_id=%s and request_id=%s',scope)
            row=cursor.fetchone()
            if row:
                draft.require(row[0]==fingerprint,'ANALYSIS_REQUEST_CONFLICT',409)
                result=json.loads(row[1]);draft.require(result.get('operation')=='evidence/register' and result.get('analysisSessionId')==session_id,'ANALYSIS_REQUEST_CONFLICT',409)
                self.store._session(cursor,session_id,actor_id)
                return {k:result[k] for k in ('evidenceRefId','sourceKind','sourceRevision')}
        with self.store.connection.transaction(readonly=True) as cursor:
            self.store._session(cursor, session_id, actor_id, active=True)
            repeated=alias(cursor)
            if repeated:authorize();return repeated
            prior = self._row(cursor, session_id, actor_id, request_id=request_id)
            if prior:
                draft.require(prior[2] == fingerprint, 'ANALYSIS_REQUEST_CONFLICT', 409)
                authorize(); return self.public(prior)
        # Resolve before acquiring the write lock; fixed source descriptors do not
        # assert that their source remains current after this observation.
        descriptor = resolve(body['sourceKind'], body['selector'])
        raw = validate_descriptor(body['sourceKind'], descriptor); digest = hashlib.sha256(raw.encode()).hexdigest()
        with self.store.connection.transaction() as cursor:
            cursor.execute('select pg_advisory_xact_lock(%s)', (draft.WRITE_LOCK,))
            head = self.store._session(cursor, session_id, actor_id, lock=True, active=True)[0]
            repeated=alias(cursor)
            if repeated:authorize();return repeated
            prior = self._row(cursor, session_id, actor_id, request_id=request_id)
            if prior:
                draft.require(prior[2] == fingerprint, 'ANALYSIS_REQUEST_CONFLICT', 409)
                authorize(); return self.public(prior)
            draft.require(head == body['expectedAnalysisRevision'], 'ANALYSIS_CHANGED', 409)
            cursor.execute(f'''select evidence_ref_id::text,request_id::text,request_fingerprint,source_kind,
                descriptor_json,descriptor_sha256 from {draft.SCHEMA}.analysis_evidence_refs
                where session_id=%s and source_kind=%s and descriptor_sha256=%s order by created_at limit 1''',
                (session_id,body['sourceKind'],digest))
            same = cursor.fetchone()
            if same:
                result=self.public(same)
                cursor.execute(f'select count(*) from {draft.SCHEMA}.analysis_requests')
                draft.require(cursor.fetchone()[0]<draft.MAX_STORE_REVISIONS,'ANALYSIS_STORE_LIMIT',413)
                cursor.execute(f'insert into {draft.SCHEMA}.analysis_requests values(%s,%s,%s,%s,%s,%s,%s)',
                    (*scope,fingerprint,draft.canonical({**result,'operation':'evidence/register','analysisSessionId':session_id}),self.store.clock()))
                authorize(); return result
            cursor.execute(f'select count(*),coalesce(sum(octet_length(descriptor_json)),0) from {draft.SCHEMA}.analysis_evidence_refs')
            count, used = cursor.fetchone()
            draft.require(count < 10000 and used + len(raw.encode()) <= MAX_SOURCE_BYTES, 'ANALYSIS_STORE_LIMIT', 413)
            cursor.execute(f'select count(*) from {draft.SCHEMA}.analysis_evidence_refs where session_id=%s', (session_id,))
            draft.require(cursor.fetchone()[0] < 100, 'ANALYSIS_SOURCE_LIMIT', 413)
            evidence_id = str(uuid4())
            cursor.execute(f'insert into {draft.SCHEMA}.analysis_evidence_refs values(%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (evidence_id, session_id, request_id, fingerprint, body['sourceKind'], raw, digest, actor_id, self.store.clock()))
            authorize()
            return {'evidenceRefId': evidence_id, 'sourceKind': body['sourceKind'], 'sourceRevision': digest}

    def descriptor(self, actor_id, body, authorize):
        draft.require(self.store.schema_version >= 2, 'ANALYSIS_SOURCES_NOT_ENABLED', 503)
        draft.require(type(body) is dict and set(body) == {'analysisSessionId', 'evidenceRefId'})
        authorize()
        with self.store.connection.transaction(readonly=True) as cursor:
            row = self._row(cursor, body['analysisSessionId'], actor_id, evidence_id=body['evidenceRefId'])
            draft.require(row is not None, 'NOT_FOUND_OR_FORBIDDEN', 404)
            descriptor = json.loads(row[4]); raw = validate_descriptor(row[3], descriptor)
            draft.require(raw == row[4] and hashlib.sha256(raw.encode()).hexdigest() == row[5], 'ANALYSIS_STORAGE_INVALID', 409)
            authorize()
            return self.public(row), descriptor
