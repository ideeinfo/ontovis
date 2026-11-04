"""Concrete project search, bounded orchestration and atomic draft actions."""
import copy
import json
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4
from tests import test_work_orders as orders_fixture
from tests.test_assistant import answer
from apps.api.assistant_service import AssistantRuntime
from apps.api.assistant_store import DEFAULT,digest
from apps.api.assistant_tasks import PROTOCOL,ProjectTools,validate_plan,snapshot
from apps.api.assistant_canvas_tasks import build,load,retain,acknowledge
from apps.api.authority import PreviewError


def board():return dict(schemaVersion=2,ontobaseConnectionId='source',projectCode='Demo-PDS',title='Synthetic acceptance',status='analyzing',
    context=dict(objectIds=[],timeFrom='2026-01-01T00:00:00Z',timeTo='2026-01-02T00:00:00Z',timezone='UTC'),
    cards=[],relations=[],viewport=dict(x=0,y=0,zoom=1))


def action(kind,targets=None,text=''):return dict(kind=kind,targets=targets or [],text=text,x=None,y=None)


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.fixture=orders_fixture.WorkOrderTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups);self.fixture.seed()
        self.orders=self.fixture.orders;self.library=self.fixture.library;self.actor=str(uuid4())
        self.reader=SimpleNamespace(orders=self.orders,reader=SimpleNamespace(prefix='/api/v1/projects/Demo-PDS'))
    def search(self,fault='13001',cursor=0,revision=None):
        return self.orders.assistant_search(dict(q='',faultCode=fault,cursor=cursor,limit=2,snapshotRevision=revision))
    def test_exact_filter_before_paging_and_snapshot_rejects_change(self):
        first=self.search();self.assertEqual(3,first['total']);self.assertTrue(all(r['faultCode']=='13001' for r in first['items']))
        second=self.search(cursor=first['nextCursor'],revision=first['snapshotRevision']);self.assertEqual(1,len(second['items']))
        self.assertFalse(set(r['orderId'] for r in first['items'])&set(r['orderId'] for r in second['items']))
        self.assertEqual(0,self.search('130')['total'])
        with self.assertRaises(PreviewError):self.search(cursor=2,revision='changed')
        row=first['items'][0]
        one=self.orders.assistant_search(dict(q='',faultCode='13001',orderId=row['orderId'],cursor=0,limit=6,snapshotRevision=None))
        self.assertEqual(1,one['total']);self.assertEqual(row['orderId'],one['items'][0]['orderId'])

    def test_model_prose_does_not_narrow_an_exact_fault_or_order_filter(self):
        tools=ProjectTools(self.reader,lambda:None,8,DEFAULT['allowedKinds'],())
        tools.query(dict(tool='work_orders',query='查找本项目所有故障代码为13001的历史工单，仅限模拟记录，不限制历史时间，不确认相同根因。',faultCode='13001',orderId=''))
        self.assertEqual(3,len(tools.results));self.assertEqual('',tools.trace[0]['filters']['query'])
        selected=tools.results[0]['identifier'];other=ProjectTools(self.reader,lambda:None,8,DEFAULT['allowedKinds'],())
        other.query(dict(tool='work_orders',query='只加入这一个编号，不确认同根因',faultCode='13001',orderId=selected))
        self.assertEqual([selected],[r['identifier'] for r in other.results])
    def test_removed_card_still_found_fixed_identity_and_duplicate_are_preserved(self):
        tools=ProjectTools(self.reader,lambda:None,8,DEFAULT['allowedKinds'],())
        tools.query(dict(tool='work_orders',query='',faultCode='13001'))
        self.assertEqual(3,len(tools.results));self.assertEqual(3,tools.reads)
        self.assertIn('orderId',tools.sources[1]['summary']);self.assertIn('模拟',tools.sources[1]['summary'])
        target=tools.results[0];calls=[]
        def register(row,index):calls.append(row);return dict(evidenceRefId=str(uuid4()),sourceRevision='a'*64)
        plan=dict(actions=[action('add_results',[target['key']])])
        original=board();added,receipts,_=build(original,plan,tools.results,register,str(uuid4()),'source','Demo-PDS')
        self.assertFalse(original['cards']);self.assertEqual('added',receipts[0]['status']);self.assertTrue(receipts[0]['simulated'])
        same,receipts,_=build(added,plan,tools.results,register,str(uuid4()),'source','Demo-PDS')
        self.assertEqual(1,len(same['cards']));self.assertEqual('already_present',receipts[0]['status'])
        removed=copy.deepcopy(added);removed['cards']=[]
        restored,_,_=build(removed,plan,tools.results,register,str(uuid4()),'source','Demo-PDS');self.assertEqual(1,len(restored['cards']))
    def test_bad_action_is_atomic_and_historical_notes_not_editable(self):
        original=board();plan=dict(actions=[action('add_note',text='kept only in candidate'),action('remove_cards',['invented'])])
        with self.assertRaises(PreviewError):build(original,plan,[],None,str(uuid4()),'source','Demo-PDS')
        self.assertFalse(original['cards'])
        original['cards']=[dict(id='old',kind='analysis',title='old',note='n',x=0,y=0,width=300,height=200,pinned=False,historical=True)]
        with self.assertRaises(PreviewError):build(original,dict(actions=[action('remove_cards',['C1'])]),[],None,str(uuid4()),'source','Demo-PDS')
    def test_foreign_scope_query_write_injection_and_arbitrary_tools_rejected(self):
        with self.assertRaises(PreviewError):snapshot(dict(snapshotJson=json.dumps(board())),'other','Demo-PDS')
        for plan in [dict(intent='query',queries=[],actions=[action('save')]),dict(intent='edit',queries=[dict(tool='http',query='x',faultCode='')],actions=[]),
                     dict(intent='edit',queries=[],actions=[action('run_sql')])]:
            with self.assertRaises(PreviewError):validate_plan(plan)

    def test_project_knowledge_enters_fixed_release_and_keeps_pages_and_edge_provenance(self):
        from tests.test_assistant_knowledge import response
        from apps.api.analysis_preview import OB
        graph=dict(project_code='P',nodes=[dict(kind='FaultDefinition',payload=dict(properties={OB+'fault_code':[dict(value='13002')],
            OB+'title':[dict(value='机舱柜温度低')]}),source=dict(document=dict(id='document'),version=dict(id='version'),release_id='release',local_id='root'))],relations=[],next_cursor=None)
        reader=SimpleNamespace(reader=SimpleNamespace(prefix='/api/v1/projects/P',project_code='P',_request=lambda *_:graph))
        tools=ProjectTools(reader,lambda:None,8,['document'],())
        with patch('apps.api.fixed_documents.FixedDocuments.metadata',return_value=dict(sourceSha256='a'*64)),\
             patch('apps.api.analysis_preview.node_evidence',return_value=dict(items=[dict(selector=dict(page=49))])),\
             patch('apps.api.assistant_knowledge.read_neighborhood',return_value=response()):
            tools.query(dict(tool='knowledge',query='',faultCode='13002'))
        self.assertEqual(4,tools.reads);self.assertIn('检查',tools.sources[-1]['summary'])
        edge=tools.graphs[-1]['graph']['relations'][0]
        self.assertEqual(49,edge['provenance']['pageNumber']);self.assertEqual('release/a',edge['provenance']['recordId'])
    def test_operation_receipt_replays_and_rejects_different_ack(self):
        run=str(uuid4());self.assertIsNone(load(self.library,run,'s'))
        retain(self.library,run,'s','base',dict(snapshot=board()))
        self.assertEqual('base',load(self.library,run,'s')['base_digest'])
        receipt=dict(state='applied_draft');self.assertEqual(receipt,acknowledge(self.library,run,'s',receipt))
        self.assertEqual(receipt,acknowledge(self.library,run,'s',receipt))
        with self.assertRaises(PreviewError):acknowledge(self.library,run,'s',dict(state='saved'))
    def test_empty_unsaved_canvas_runs_real_search_without_evidence_and_two_calls(self):
        runtime=AssistantRuntime(self.library,'source');self.addCleanup(runtime.close)
        runtime.store.publish('Demo-PDS',self.actor,dict(requestId=str(uuid4()),expectedRevision=0,policy={**DEFAULT,'enabled':True}),lambda:None)
        b=dict(protocol=PROTOCOL,mode='workbench',analysisSessionId=str(uuid4()),expectedAnalysisRevision=0,evidenceRefIds=[],
            requestId=str(uuid4()),question='查找同故障工单',snapshotJson=json.dumps(board()),taskId='analysis')
        calls=[]
        def source(data,*_):
            calls.append(data);common=dict(usage=dict(total_tokens=10),modelCalls=1,engineeringConfirmation=False)
            if data['workflow']['phase']=='plan':return dict(**common,plan=dict(intent='query',queries=[dict(tool='work_orders',query='',faultCode='13001')],actions=[]))
            return dict(**common,answer=answer())
        initial=runtime.start(dict(project='Demo-PDS',owner=self.actor,sid='s'),b,runtime.store.policy('Demo-PDS'),
            dict(serviceRevision='a'*64,accessRevision='g',taskId='analysis',settings=dict()),lambda _: ([],self.reader),lambda *_:None,source)
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            result=runtime.store.public(runtime.store.run('Demo-PDS',self.actor,initial['runId']))
            if result['state'] not in ('reading','model','validating'):break
            time.sleep(.01)
        self.assertEqual('complete',result['state'],result);self.assertEqual(3,len(result['result']['task']['results']))
        self.assertEqual(2,len(calls));self.assertEqual([],calls[0]['evidence']);self.assertEqual(20,result['result']['usage']['total_tokens'])
        self.assertEqual(initial['runId'],runtime.start(dict(project='Demo-PDS',owner=self.actor,sid='s'),b,runtime.store.policy('Demo-PDS'),
            dict(serviceRevision='a'*64),None,None,None)['runId']);self.assertEqual(2,len(calls))

        from tests.test_assistant import Reader
        reader=Reader();reader.orders=self.orders;reader.reader=self.reader.reader
        fixed=[(dict(evidenceRefId=str(uuid4()),sourceKind='alarm',sourceRevision='a'*64),{}) for _ in range(8)]
        second={**b,'requestId':str(uuid4()),'analysisSessionId':str(uuid4()),'evidenceRefIds':[r['evidenceRefId'] for r,_ in fixed]}
        started=runtime.start(dict(project='Demo-PDS',owner=self.actor,sid='s'),second,runtime.store.policy('Demo-PDS'),
            dict(serviceRevision='a'*64,accessRevision='g',taskId='analysis',settings={}),lambda _:(fixed,reader),lambda *_:None,source)
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            result=runtime.store.public(runtime.store.run('Demo-PDS',self.actor,started['runId']))
            if result['state'] not in ('reading','model','validating'):break
            time.sleep(.01)
        self.assertEqual('partial',result['state'],result)
        limited=[t for t in result['result']['task']['trace'] if t['state']=='budget_limited']
        self.assertEqual(3,limited[0]['count']);self.assertEqual(8,result['result']['task']['reads'])
