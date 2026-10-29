import copy
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
from threading import Event
import time
import unittest
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.model_library import ModelLibrary
from apps.api.assistant_store import AssistantStore, DEFAULT, validate_policy
from apps.api.assistant_service import AssistantRuntime
from apps.api.assistant_summaries import redact,summarize,validate_answer
from apps.api import simulated_faults as sim

def answer(ref='E1'):
    return {'observations':[{'text':'模拟读数偏高，不能确认故障。','refs':[ref]}],
            'hypotheses':[{'text':'测量链偏差待核验。','refs':[ref]}], 'gaps':[{'text':'缺现场测量。','refs':[]}], 'nextSteps':[]}

class Reader:
    def read(self,kind,descriptor):
        if kind=='alarm':return sim.alarms(sim.identity('13001')['datasetId'])
        if kind=='trend':
            p=sim.identity('13001');return sim.trend(p['datasetId'],'sensor_temperature',p['timeFrom'],p['timeTo'])
        return {'item':{'objectKind':'cabinet','objectScope':'installation','classification':{'code':'CB','nameZh':'柜体'}}}

class AssistantTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.library=ModelLibrary(Path(self.tmp.name)/'library','A',None)
        self.store=AssistantStore(self.library,'source');self.owner=str(uuid4())

    def publish(self,project='A',**change):
        return self.store.publish(project,self.owner,{'requestId':str(uuid4()),'expectedRevision':self.store.policy(project)['revision'],
            'expectedAccessRevision':'grant','expectedServiceRevision':'s'*64,'policy':{**DEFAULT,'enabled':True,**change}},lambda:None)

    def test_default_is_disabled_and_does_not_create_policy_rows(self):
        self.assertFalse(self.store.policy('A')['policy']['enabled'])
        with self.library.connect() as db:self.assertEqual(db.execute('select count(*) from assistant_policy_heads').fetchone()[0],0)

    def test_policy_rejects_unapproved_service_tool_budget_and_extra_fields(self):
        for change in [{'serviceRef':'custom-url'},{'allowedKinds':['script']},{'reads':9},{'parallel':3},{'seconds':121},{'seconds':True},{'enabled':1},{'extra':'x'}]:
            with self.subTest(change=change),self.assertRaises(PreviewError):validate_policy({**DEFAULT,**change})

    def test_publish_is_project_scoped_versioned_and_idempotent(self):
        body={'requestId':str(uuid4()),'expectedRevision':0,'policy':{**DEFAULT,'enabled':True}}
        first=self.store.publish('A',self.owner,body,lambda:None)
        self.assertEqual(self.store.publish('A',self.owner,body,lambda:None),first)
        self.assertEqual(self.store.policy('B')['revision'],0)
        for invalid in [{**body,'policy':DEFAULT},{**body,'requestId':str(uuid4())}]:
            with self.assertRaises(PreviewError):self.store.publish('A',self.owner,invalid,lambda:None)
        self.assertEqual(len(self.store.history('A')),1)

    def test_revocation_at_commit_rolls_back_policy_and_receipt(self):
        calls=[]
        def deny():
            calls.append(1)
            if len(calls)==2:raise PreviewError(403,'FORBIDDEN')
        with self.assertRaises(PreviewError):self.store.publish('A',self.owner,{'requestId':str(uuid4()),'expectedRevision':0,'policy':DEFAULT},deny)
        self.assertEqual(self.store.policy('A')['revision'],0)
        with self.library.connect() as db:self.assertEqual(db.execute('select count(*) from assistant_policy_requests').fetchone()[0],0)

    def test_rollback_creates_a_new_immutable_revision(self):
        first=self.publish();self.publish(reads=3)
        result=self.store.publish('A',self.owner,{'requestId':str(uuid4()),'expectedRevision':2,'restoreRevision':1},lambda:None)
        self.assertEqual(result['revision'],3);self.assertEqual(result['policy'],first['policy'])
        with self.library.connect() as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute('delete from assistant_policy_revisions')

    def body(self):return {'requestId':str(uuid4()),'analysisSessionId':str(uuid4()),'expectedAnalysisRevision':1,'evidenceRefIds':[str(uuid4())],
        'question':'项目A password=synthetic-value 联系人 a@example.test','expectedPolicyRevision':1,'expectedAccessRevision':'grant','expectedServiceRevision':'s'*64}

    def test_run_receipt_is_scoped_and_preserved_as_interrupted_after_restart(self):
        body=self.body();run,new=self.store.begin('A',self.owner,body,1,'s'*64)
        self.assertTrue(new);self.assertFalse(self.store.begin('A',self.owner,body,1,'s'*64)[1])
        for project,owner in [('B',self.owner),('A',str(uuid4()))]:
            with self.assertRaises(PreviewError):self.store.run(project,owner,run['id'])
        self.assertEqual(AssistantStore(self.library,'source').run('A',self.owner,run['id'])['state'],'interrupted')

    def test_paired_library_copy_preserves_policy_history_and_run_references(self):
        self.publish();run,_=self.store.begin('A',self.owner,self.body(),1,'s'*64)
        self.store.update(run['id'],'complete',result={'answer':answer()})
        target=Path(self.tmp.name)/'copy';shutil.copytree(self.library.root,target)
        restored=AssistantStore(ModelLibrary(target,'A',None),'source')
        self.assertEqual(restored.history('A'),self.store.history('A'))
        self.assertEqual(restored.run('A',self.owner,run['id'])['result_json'],self.store.run('A',self.owner,run['id'])['result_json'])

    def test_text_redaction_and_deterministic_trend_quality_summary(self):
        value=redact('Demo-PDS https://private.test/file a@sample.test password=secret-fixture /Users/example/a entity:11111111-1111-4111-8111-111111111111 13812345678',('Demo-PDS',))
        for private in ['Demo-PDS','private.test','sample.test','secret-fixture','/Users','11111111','13812345678']:self.assertNotIn(private,value)
        summary=json.loads(summarize(Reader(),'trend',{}));self.assertEqual(summary['badQualityCount'],1);self.assertEqual(summary['sampleCount'],181)
        self.assertEqual(summary['max'],72);self.assertEqual(summary['min'],24)

    def test_metadata_summaries_never_request_binary_content(self):
        class Meta(Reader):
            def content(self,*_):raise AssertionError('binary content requested')
        for kind in ('object','drawing','photo','model','document','work_order'):
            self.assertLessEqual(len(summarize(Meta(),kind,{})),1000)

    def test_reference_validation_rejects_unknown_citations_and_extra_actions(self):
        self.assertEqual(validate_answer(answer(),{'E1'}),answer())
        for value in [answer('E8'),{**answer(),'execute':'script'}, {**answer(),'hypotheses':[{'text':'certain','refs':[]}]}]:
            with self.assertRaises(PreviewError):validate_answer(value,{'E1'})

class RuntimeTests(unittest.TestCase):
    publish=AssistantTests.publish
    body=AssistantTests.body
    def setUp(self):
        AssistantTests.setUp(self);self.runtime=AssistantRuntime(self.library,'source');self.store=self.runtime.store;self.addCleanup(self.runtime.close)
        self.policy=self.publish();self.service={'serviceRevision':'s'*64,'accessRevision':'grant'}

    def start(self,body=None,source=None,owner=None,prepare=None,authorize=lambda *_:None):
        body=body or self.body()
        def prepared(guard):
            guard();return [({'sourceKind':'alarm','evidenceRefId':body['evidenceRefIds'][0],'sourceRevision':'r'}, {})],Reader()
        return self.runtime.start({'project':'A','owner':owner or self.owner,'sid':'sid'},body,self.policy,self.service,prepare or prepared,authorize,
            source or (lambda *_:{'answer':answer(),'usage':{'total_tokens':100},'purpose':'ontovis_analysis','serviceRevision':'s'*64,'modelCalls':1,'engineeringConfirmation':False}))

    def finish(self,run,owner=None):
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            row=self.store.run('A',owner or self.owner,run['runId'])
            if row['state'] not in ('reading','model','validating','cancel_requested'):return row
            time.sleep(.01)
        self.fail('run did not terminate')

    def test_one_model_call_with_redacted_bounded_sources_and_replayed_receipt(self):
        calls=[];body=self.body()
        def source(data,*_):
            calls.append(copy.deepcopy(data));return {'answer':answer(),'usage':{},'purpose':'ontovis_analysis','serviceRevision':'s'*64,'modelCalls':1,'engineeringConfirmation':False}
        run=self.start(body,source);result=self.finish(run)
        self.assertEqual(result['state'],'complete');self.assertEqual(len(calls),1)
        self.assertNotIn('synthetic-value',json.dumps(calls));self.assertNotIn('evidenceRefId',calls[0]['evidence'][0])
        self.start(body,source);self.assertEqual(len(calls),1)

    def test_cancel_discards_late_model_answer_and_keeps_receipt(self):
        entered=Event()
        def source(_body,cancelled,_deadline):
            entered.set();cancelled.wait(2);return {'answer':answer(),'usage':{},'purpose':'ontovis_analysis','serviceRevision':'s'*64,'modelCalls':1,'engineeringConfirmation':False}
        run=self.start(source=source);self.assertTrue(entered.wait(2))
        record=self.store.run('A',self.owner,run['runId']);self.store.cancel('A',self.owner,run['runId'],record['version'])
        with self.runtime.lock:self.runtime.jobs[run['runId']].cancelled.set()
        result=self.finish(run);self.assertEqual(result['state'],'cancelled');self.assertIsNone(result['result_json'])

    def test_policy_tightening_refuses_result_without_overwriting_canvas(self):
        entered=Event();release=Event()
        def source(*_):
            entered.set();release.wait(2);return {'answer':answer(),'usage':{},'purpose':'ontovis_analysis','serviceRevision':'s'*64,'modelCalls':1,'engineeringConfirmation':False}
        run=self.start(source=source);self.assertTrue(entered.wait(2));self.publish(enabled=False);release.set()
        result=self.finish(run);self.assertEqual(result['state'],'changed');self.assertIsNone(result['result_json'])

    def test_missing_materials_never_call_provider(self):
        class Missing(Reader):
            def read(self,*_):raise PreviewError(404,'SOURCE_MISSING')
        body=self.body()
        run=self.start(body,source=lambda *_:self.fail('provider called'),prepare=lambda _:
            ([({'sourceKind':'alarm','evidenceRefId':body['evidenceRefIds'][0],'sourceRevision':'r'}, {})],Missing()))
        result=self.finish(run);self.assertEqual(result['error_code'],'ASSISTANT_NO_EVIDENCE')

    def test_owner_limit_rejects_another_active_run(self):
        entered=Event();release=Event()
        def source(*_):entered.set();release.wait(2);return {'answer':answer(),'usage':{},'purpose':'ontovis_analysis','serviceRevision':'s'*64,'modelCalls':1,'engineeringConfirmation':False}
        run=self.start(source=source);self.assertTrue(entered.wait(2))
        with self.assertRaises(PreviewError) as error:self.start()
        self.assertEqual(error.exception.code,'ASSISTANT_BUSY');release.set();self.finish(run)

    def test_invalid_model_citation_is_not_persisted_as_a_result(self):
        run=self.start(source=lambda *_:{'answer':answer('E8'),'usage':{},'purpose':'ontovis_analysis','serviceRevision':'s'*64,'modelCalls':1,'engineeringConfirmation':False})
        row=self.finish(run);self.assertEqual(row['error_code'],'ASSISTANT_REFERENCE_INVALID');self.assertIsNone(row['result_json'])
