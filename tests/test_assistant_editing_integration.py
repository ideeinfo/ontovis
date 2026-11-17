"""Real draft transactions and receipts, with an explicitly synthetic source/model."""
import copy
import json
import os
import time
from threading import BoundedSemaphore
from types import SimpleNamespace
import unittest
from uuid import uuid4

from apps.api.assistant_service import AssistantRuntime
from apps.api.assistant_store import DEFAULT
from apps.api.assistant_tasks import PROTOCOL
from apps.api.assistant_task_api import handle
from apps.api.analysis_evidence import AnalysisEvidence
from apps.api.authority import PreviewError
from tests import test_analysis_drafts_integration as db,test_work_orders as libraries
from tests.test_analysis_drafts import CONNECTION,PROJECT,OWNER
from tests.test_assistant_tasks import action


@unittest.skipUnless(os.environ.get('ONTOVIS_ANALYSIS_TEST_DATABASE_URL'),'Owned disposable PG connection required')
class AssistantEditingIntegrationTests(unittest.TestCase):
    setUpClass=classmethod(db.AnalysisDraftIntegrationTests.setUpClass.__func__)
    tearDownClass=classmethod(db.AnalysisDraftIntegrationTests.tearDownClass.__func__)
    consumer=db.AnalysisDraftIntegrationTests.consumer
    write=db.AnalysisDraftIntegrationTests.write
    create=db.AnalysisDraftIntegrationTests.create
    data=db.AnalysisDraftIntegrationTests.data
    def setUp(self):
        db.AnalysisDraftIntegrationTests.setUp(self)
        fixture=libraries.WorkOrderTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.runtime=AssistantRuntime(fixture.library,CONNECTION);self.addCleanup(self.runtime.close)
        self.runtime.store.publish(PROJECT,OWNER,dict(requestId=str(uuid4()),expectedRevision=0,policy={**DEFAULT,'enabled':True}),lambda:None)
        self.sessions=SimpleNamespace(connection_id=CONNECTION,analysis_store_id=self.store.store_id,
            analysis_database_url=self.urls[0],analysis_slots=BoundedSemaphore(4))
        self.service=dict(canRun=True,serviceRevision='a'*64,accessRevision='g',taskId='analysis',settings={})
        self.reader=SimpleNamespace(resolve=lambda kind,selector:dict(orderId=selector['orderId'],orderRevision=selector['expectedOrderRevision'],snapshotSha256=str(selector['expectedOrderRevision'])*64) if kind=='work_order' else copy.deepcopy(selector),read=lambda *_:{})
        self.prepare=lambda *_:([],self.reader)
        original=db.snapshot();original['schemaVersion']=2
        self.created=self.create(original);self.board=original
    def completed(self,actions,history=None,results=None):
        body=dict(protocol=PROTOCOL,mode='workbench',analysisSessionId=self.created['analysisSessionId'],expectedAnalysisRevision=self.created['analysisRevision'],
            evidenceRefIds=[],requestId=str(uuid4()),question='synthetic explicit edit',snapshotJson=json.dumps(self.board),
            taskId='analysis',historyJson=json.dumps(history or {}))
        first=self.runtime.start(dict(project=PROJECT,owner=OWNER,sid='synthetic'),body,self.runtime.store.policy(PROJECT),self.service,
            self.prepare,lambda *_:None,lambda *_:dict(plan=dict(intent='edit',queries=[],actions=actions),modelCalls=1,engineeringConfirmation=False,usage={}))
        for _ in range(100):
            record=self.runtime.store.run(PROJECT,OWNER,first['runId'])
            if record['state'] not in ('reading','model','validating'):break
            time.sleep(.01)
        self.assertEqual('complete',record['state'],record)
        if results is not None:
            value=json.loads(record['result_json']);value['task']['results']=results
            self.runtime.store.update(record['id'],'complete',result=value)
        return dict(runId=record['id'],selectedKeys=[],snapshotJson=body['snapshotJson'])
    def call(self,operation,body):
        return handle(operation,body,self.sessions,None,'synthetic',PROJECT,OWNER,dict(role='admin'),self.runtime,
            lambda *_:self.service,self.prepare,lambda *_:None,'unused')
    def test_multi_edit_save_reopen_undo_and_exact_receipt(self):
        request=self.completed([action('rename_card',['C1'],'核对记录'),action('append_note',['C1'],'\n新增待核验事项'),action('copy_card',['C1']),
            action('group_cards',['C1','C2'],'同一事件'),action('add_support',['C1','C2'],'人工判断，待核验'),action('pin_cards',['C1']),action('save')])
        prepared=self.call('task-prepare',request);value=prepared['snapshot']
        self.assertEqual(2,len(value['cards']));self.assertEqual(1,len(value['relations']));self.assertTrue(value['cards'][0]['pinned'])
        saved=self.write('save',dict(requestId=str(uuid4()),analysisSessionId=self.created['analysisSessionId'],expectedAnalysisRevision=1,snapshot=value))
        ack=self.call('task-ack',{**request,'snapshotJson':json.dumps(value),'savedRevision':saved['analysisRevision']})
        self.assertEqual('saved',ack['receipt']['state']);self.assertEqual(value,self.store.detail(OWNER,self.created['analysisSessionId'],lambda:None)['snapshot'])
        self.assertEqual(ack['receipt'],self.call('task-ack',{**request,'snapshotJson':json.dumps(value),'savedRevision':2})['receipt'])
        original=copy.deepcopy(self.board);self.created=saved;self.board=value
        undo=self.completed([action('undo')],dict(undo=original))
        result=self.call('task-prepare',undo);self.assertEqual(original,result['snapshot'])
        self.assertEqual('undo',result['receipts'][0]['historyDirection'])
        self.assertEqual(2,self.store.detail(OWNER,self.created['analysisSessionId'],lambda:None)['analysisRevision'])
    def test_retained_preparation_rechecks_saved_head_and_rejects_wrong_ack(self):
        request=self.completed([action('rename',text='prepared title')]);prepared=self.call('task-prepare',request)
        with self.assertRaises(PreviewError):self.call('task-ack',{**request,'savedRevision':None})
        self.write('save',dict(requestId=str(uuid4()),analysisSessionId=self.created['analysisSessionId'],expectedAnalysisRevision=1,snapshot={**self.board,'title':'concurrent change'}))
        with self.assertRaises(PreviewError) as error:self.call('task-prepare',request)
        self.assertEqual('ANALYSIS_CHANGED',error.exception.code)
    def test_source_replacement_preserves_card_and_rechecks_on_retry(self):
        evidence=AnalysisEvidence(self.store)
        reference=evidence.register(OWNER,dict(analysisSessionId=self.created['analysisSessionId'],expectedAnalysisRevision=1,requestId=str(uuid4()),
            sourceKind='work_order',selector=dict(orderId='SYNTHETIC-WO',expectedOrderRevision=5)),lambda:None,self.reader.resolve)
        self.board['cards'][0].update(kind='work_order',source=dict(system='ontovis',ontobaseConnectionId=CONNECTION,projectCode=PROJECT,
            id=reference['evidenceRefId'],revision=reference['sourceRevision']))
        self.board['cards'][0].pop('note',None)
        candidate=dict(key='R1',kind='work_order',identifier='SYNTHETIC-WO',version=6,title='Latest',selector=dict(orderId='SYNTHETIC-WO',expectedOrderRevision=6))
        request=self.completed([action('replace_source',['C1','R1'])],results=[candidate]);prepared=self.call('task-prepare',request)
        before=self.board['cards'][0];after=prepared['snapshot']['cards'][0]
        self.assertEqual({k:v for k,v in before.items() if k!='source'},{k:v for k,v in after.items() if k!='source'})
        self.assertNotEqual(before['source'],after['source'])
        def stale(*_):raise PreviewError(409,'WORK_ORDER_CHANGED')
        self.reader.resolve=stale
        with self.assertRaises(PreviewError) as error:self.call('task-prepare',request)
        self.assertEqual('WORK_ORDER_CHANGED',error.exception.code)
