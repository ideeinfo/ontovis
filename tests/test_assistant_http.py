from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from threading import Thread
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api import simulated_faults as sim
from apps.api.assistant_store import DEFAULT
from apps.api.session_http import handler_type
from tests import test_project_workspaces as project_tests
ProjectsAuthority=project_tests.ProjectsAuthority
from tests.test_assistant import answer

ROOT='/api/workbench/assistant/'
class AssistantHttpTests(unittest.TestCase):
    def setUp(self):
        self.fixture=project_tests.ProjectWorkspaceTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.sessions=self.fixture.sessions;self.sid=self.fixture.sid
        p=patch.dict(ProjectsAuthority.projects,{'Demo-PDS':'Demo project'});p.start();self.addCleanup(p.stop)
        ProjectsAuthority.permissions['member']['Demo-PDS']='admin'
        self.sessions.rows[self.sid].subject_id=str(uuid4());self.fixture.create('Demo-PDS')
        self.sessions.analysis_store_id=str(uuid4());self.sessions.analysis_database_url='synthetic-only'
        self.analysis=str(uuid4());self.evidence=str(uuid4());self.event=sim.identity('13001')
        original=ProjectsAuthority.request
        def authority(instance,method,path,body=None):
            if path.endswith('/ontovis-assistant/service'):
                code=path.split('/')[4];role=ProjectsAuthority.permissions[instance.username].get(code)
                if not role:raise PreviewError(403,'FORBIDDEN')
                return {'serviceRef':DEFAULT['serviceRef'],'purpose':'ontovis_analysis','serviceRevision':'a'*64,
                    'accessRevision':code+':'+role,'enabled':True,'canRun':role=='admin','modelId':'synthetic-model'}
            return original(instance,method,path,body)
        self.patcher=patch.object(ProjectsAuthority,'request',authority);self.patcher.start();self.addCleanup(self.patcher.stop)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler_type(self.sessions,'http://127.0.0.1:4180',development=True));self.server.daemon_threads=True
        self.thread=Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.thread.join);self.addCleanup(self.server.shutdown)
        store_id=self.sessions.analysis_store_id
        class Store:
            def __init__(inner,*_):inner.store_id=store_id
            def close(inner):pass
            def detail(inner,actor,session,guard,revision=None):
                guard()
                if session!=self.analysis:raise PreviewError(404,'NOT_FOUND_OR_FORBIDDEN')
                return {'lifecycle':'active'}
        p=patch('apps.api.analysis_drafts.AnalysisDrafts',Store);p.start();self.addCleanup(p.stop)
        def descriptor(_self,actor,body,guard):
            guard()
            if body['evidenceRefId']!=self.evidence:raise PreviewError(404,'NOT_FOUND_OR_FORBIDDEN')
            return {'evidenceRefId':self.evidence,'sourceKind':'alarm','sourceRevision':'r'}, {
                'datasetId':self.event['datasetId'],'datasetRevision':self.event['datasetRevision'],
                'eventId':sim.alarms(self.event['datasetId'])['items'][0]['sourceEventId']}
        p=patch('apps.api.analysis_evidence.AnalysisEvidence.descriptor',descriptor);p.start();self.addCleanup(p.stop)

    def request(self,action,body=None,project='Demo-PDS',origin=True):
        data=self.fixture.payload(project,**(body or {}))
        conn=HTTPConnection(*self.server.server_address,timeout=5)
        headers={'Host':'127.0.0.1:4180','Content-Type':'application/json','Cookie':'ontovis_development_session='+self.sid}
        if origin:headers['Origin']='http://127.0.0.1:4180'
        conn.request('POST',ROOT+action,json.dumps(data),headers);r=conn.getresponse();value=json.loads(r.read());conn.close()
        return r.status,value

    def enable(self):
        return self.request('publish',{'requestId':str(uuid4()),'expectedRevision':0,'expectedAccessRevision':'Demo-PDS:admin',
            'expectedServiceRevision':'a'*64,'policy':{**DEFAULT,'enabled':True}})

    def start_body(self):return {'requestId':str(uuid4()),'analysisSessionId':self.analysis,'expectedAnalysisRevision':1,'evidenceRefIds':[self.evidence],
        'question':'仅比较所选模拟资料','expectedPolicyRevision':1,'expectedAccessRevision':'Demo-PDS:admin','expectedServiceRevision':'a'*64}

    def test_origin_scope_and_policy_permission_are_enforced(self):
        self.assertEqual(self.request('policy',origin=False)[0],403)
        self.assertEqual(self.request('policy',project=None)[0],422)
        self.assertEqual(self.request('policy')[0],200)
        self.assertEqual(self.request('policy',project='B')[1]['revision'],0)
        ProjectsAuthority.permissions['member']['Demo-PDS']='viewer'
        self.assertFalse(self.request('policy')[1]['canManage']);self.assertEqual(self.enable()[0],403)

    def test_publish_preview_history_and_stale_version(self):
        self.assertEqual(self.request('preview',{'policy':{**DEFAULT,'reads':9}})[0],422)
        self.assertEqual(self.enable()[0],200);self.assertEqual(self.enable()[0],409)
        self.assertEqual(len(self.request('history')[1]['items']),1)
        self.assertEqual(self.request('policy',project='B')[1]['revision'],0)

    def test_summary_reads_only_selected_fixed_sources_without_model_call(self):
        with patch('apps.api.assistant_service.call_source') as model:
            status,value=self.request('summary',{k:v for k,v in self.start_body().items() if k in ('analysisSessionId','expectedAnalysisRevision','evidenceRefIds')})
            self.assertEqual(status,200,value);self.assertEqual(value['modelCalls'],0);model.assert_not_called()
            self.assertIn('模拟',value['items'][0]['summary'])

    def test_start_result_receipt_and_cross_project_refusal(self):
        self.assertEqual(self.enable()[0],200)
        result={'answer':answer(),'usage':{'total_tokens':100},'serviceRevision':'a'*64,'purpose':'ontovis_analysis','modelCalls':1,'engineeringConfirmation':False}
        with patch('apps.api.assistant_service.call_source',return_value=result) as model:
            body=self.start_body();status,started=self.request('start',body);self.assertEqual(status,200,started)
            for _ in range(60):
                status,run=self.request('status',{'runId':started['runId']})
                if run['state'] not in ('reading','model','validating'):break
                time.sleep(.01)
            self.assertEqual(status,200);self.assertEqual(run['state'],'complete',run);self.assertEqual(model.call_count,1)
            self.assertEqual(self.request('start',body)[1]['runId'],started['runId']);self.assertEqual(model.call_count,1)
            self.assertEqual(self.request('status',{'runId':started['runId']},project='B')[0],404)
            self.assertEqual(self.request('status',{'requestId':body['requestId']})[1]['state'],'complete')

    def test_missing_fixed_reference_never_reaches_the_model(self):
        self.enable();body={**self.start_body(),'evidenceRefIds':[str(uuid4())]}
        with patch('apps.api.assistant_service.call_source') as model:
            status,started=self.request('start',body);self.assertEqual(status,200,started)
            for _ in range(60):
                status,run=self.request('status',{'runId':started['runId']})
                if run['state'] not in ('reading','model','validating'):break
                time.sleep(.01)
            self.assertEqual(run['state'],'failed',run);model.assert_not_called()

    def test_live_revocation_prevents_cached_result_disclosure(self):
        self.enable()
        result={'answer':answer(),'usage':{},'serviceRevision':'a'*64,'purpose':'ontovis_analysis','modelCalls':1,'engineeringConfirmation':False}
        with patch('apps.api.assistant_service.call_source',return_value=result):
            _,started=self.request('start',self.start_body())
            time.sleep(.05)
            ProjectsAuthority.permissions['member'].pop('Demo-PDS')
            status,value=self.request('status',{'runId':started['runId']});self.assertEqual(status,403);self.assertNotIn('result',value)
