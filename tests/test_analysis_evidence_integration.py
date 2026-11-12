"""Real PG evidence references, immutable recovery and explicit schema upgrade."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import os
from threading import Barrier
import unittest
from unittest.mock import Mock
from uuid import uuid4

from apps.api import analysis_drafts as draft
from apps.api.analysis_evidence import AnalysisEvidence
from apps.api.authority import PreviewError
from apps.api.storage_lease import storage_lease, StorageInUse
from tests import test_analysis_drafts_integration as base
from tests.test_analysis_drafts import OWNER, OTHER, CONNECTION, PROJECT, create_body
from tools import analysis_draft_backup as backup
from tools.analysis_sources_upgrade import upgrade


@unittest.skipUnless(os.environ.get('ONTOVIS_ANALYSIS_TEST_DATABASE_URL'), 'Set an owned disposable PG test connection')
class AnalysisEvidenceIntegrationTests(unittest.TestCase):
    setUpClass=classmethod(base.AnalysisDraftIntegrationTests.setUpClass.__func__)
    tearDownClass=classmethod(base.AnalysisDraftIntegrationTests.tearDownClass.__func__)
    setUp=base.AnalysisDraftIntegrationTests.setUp
    consumer=base.AnalysisDraftIntegrationTests.consumer
    write=base.AnalysisDraftIntegrationTests.write
    create=base.AnalysisDraftIntegrationTests.create
    data=base.AnalysisDraftIntegrationTests.data

    def body(self, created=None, **changes):
        created=created or self.create()
        return {'analysisSessionId':created['analysisSessionId'],'expectedAnalysisRevision':created['analysisRevision'],
            'requestId':str(uuid4()),'sourceKind':'model','selector':{'chosen':'fixed-model'},**changes}

    def descriptor(self):
        return {'modelAssetId':str(uuid4()),'modelVersionId':str(uuid4()),'contentRevision':'fixed:1','sha256':'a'*64}

    def test_reference_replay_owner_scope_and_immutable_descriptor_roundtrip(self):
        sources=AnalysisEvidence(self.store);body=self.body();value=self.descriptor();resolve=Mock(return_value=value)
        first=sources.register(OWNER,body,lambda:None,resolve)
        self.assertEqual(sources.register(OWNER,body,lambda:None,resolve),first);self.assertEqual(resolve.call_count,1)
        request={'analysisSessionId':body['analysisSessionId'],'evidenceRefId':first['evidenceRefId']}
        self.assertEqual(sources.descriptor(OWNER,request,lambda:None)[1],value)
        for actor,store in ((OTHER,self.store),(OWNER,self.consumer(project='OTHER'))):
            with self.assertRaises(PreviewError):AnalysisEvidence(store).descriptor(actor,request,lambda:None)
        with self.store.connection.transaction() as cursor:
            for action in ('update '+draft.SCHEMA+'.analysis_evidence_refs set created_at=created_at','delete from '+draft.SCHEMA+'.analysis_evidence_refs'):
                with self.assertRaises(self.driver.Error),self.driver.connect(self.urls[0]) as db:db.execute(action)

    def test_reused_request_conflicting_selection_and_stale_analysis_are_refused(self):
        sources=AnalysisEvidence(self.store);body=self.body();resolve=lambda *_:self.descriptor()
        sources.register(OWNER,body,lambda:None,resolve)
        with self.assertRaises(PreviewError) as error:sources.register(OWNER,{**body,'selector':{'chosen':'different'}},lambda:None,resolve)
        self.assertEqual(error.exception.code,'ANALYSIS_REQUEST_CONFLICT')
        with self.assertRaises(PreviewError) as error:sources.register(OWNER,{**body,'requestId':str(uuid4()),'expectedAnalysisRevision':2},lambda:None,resolve)
        self.assertEqual(error.exception.code,'ANALYSIS_CHANGED')

    def test_source_permission_failure_and_final_denial_do_not_leave_reference(self):
        sources=AnalysisEvidence(self.store);body=self.body();before=self.data();calls=[]
        def guard():
            calls.append(1)
            if len(calls)==2:raise PreviewError(403,'SOURCE_FORBIDDEN')
        with self.assertRaises(PreviewError):sources.register(OWNER,body,guard,lambda *_:self.descriptor())
        self.assertEqual(self.data(),before)
        with self.assertRaises(PreviewError):sources.register(OWNER,body,lambda:None,lambda *_:(_ for _ in ()).throw(PreviewError(403,'SOURCE_FORBIDDEN')))
        self.assertEqual(self.data(),before)

    def test_concurrent_same_request_creates_one_reference(self):
        body=self.body();value=self.descriptor();barrier=Barrier(2);stores=[self.consumer(),self.consumer()]
        def run(store):
            def resolve(*_):barrier.wait(timeout=10);return value
            return AnalysisEvidence(store).register(OWNER,body,lambda:None,resolve)
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,stores))
        self.assertEqual(results[0],results[1]);self.assertEqual(len(self.data()['tables']['analysis_evidence_refs']),1)

    def test_new_source_table_survives_restore_and_tampering_or_owner_mismatch_fails(self):
        sources=AnalysisEvidence(self.store);body=self.body();value=self.descriptor()
        reference=sources.register(OWNER,body,lambda:None,lambda *_:value)
        receipt=backup.snapshot(self.urls[0],self.root/'sources');original=self.data()
        recovered=backup.restore_new(self.root/'sources',receipt['manifestSha256'],self.urls[1])
        other=self.consumer(self.urls[1]);self.assertEqual(other.schema_version,2)
        self.assertEqual(AnalysisEvidence(other).descriptor(OWNER,{'analysisSessionId':body['analysisSessionId'],'evidenceRefId':reference['evidenceRefId']},lambda:None)[1],value)
        self.assertEqual(recovered['counts']['analysis_evidence_refs'],1)
        for field,bad in (('actor_id',OTHER),('descriptor_sha256','b'*64),('descriptor_json','{}')):
            changed=deepcopy(original);changed['tables']['analysis_evidence_refs'][0][field]=bad
            with self.assertRaises(PreviewError):backup.validate_package(changed)

    def test_v1_package_still_restores_then_offline_upgrade_preserves_all_old_rows(self):
        self.store.close()
        with self.driver.connect(self.urls[0]) as db:db.execute('drop schema '+draft.SCHEMA+' cascade')
        metadata=draft.provision(self.urls[0],CONNECTION,version=1);self.store=self.consumer()
        created=self.create();before=self.data();self.assertEqual(before['format'],draft.FORMAT_V1)
        receipt=backup.snapshot(self.urls[0],self.root/'legacy')
        backup.restore_new(self.root/'legacy',receipt['manifestSha256'],self.urls[1]);legacy=self.consumer(self.urls[1])
        self.assertEqual(legacy.schema_version,1)
        with self.assertRaises(PreviewError):AnalysisEvidence(legacy).register(OWNER,self.body(created),lambda:None,lambda *_:self.descriptor())
        self.store.close();result=upgrade(self.urls[0],metadata['storeId'],[self.root],service_stopped=True)
        self.assertTrue(result['changed']);self.store=self.consumer();after=self.data()
        for table in ('analysis_sessions','analysis_revisions','analysis_requests'):self.assertEqual(before['tables'][table],after['tables'][table])
        self.assertEqual(after['sourceStoreId'],before['sourceStoreId']);self.assertEqual(after['tables']['analysis_evidence_refs'],[])
        self.assertFalse(upgrade(self.urls[0],metadata['storeId'],[self.root],service_stopped=True)['changed'])

    def test_migration_rejects_active_storage_wrong_identity_and_missing_stop(self):
        for stopped,identifier in ((False,self.store.store_id),(True,str(uuid4()))):
            with self.assertRaises(PreviewError):upgrade(self.urls[0],identifier,[self.root],service_stopped=stopped)
        with storage_lease([self.root]):
            with self.assertRaises(StorageInUse):upgrade(self.urls[0],self.store.store_id,[self.root],service_stopped=True)
