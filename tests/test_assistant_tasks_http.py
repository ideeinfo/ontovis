import json
import time
import unittest
from unittest.mock import patch
from uuid import uuid4
from tests import test_assistant_http as fixture
from tests.test_assistant_tasks import board,action
from apps.api.assistant_tasks import PROTOCOL


class TaskHttpTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture.AssistantHttpTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.request=self.fixture.request;self.fixture.enable()
        self.body={**self.fixture.start_body(), 'analysisSessionId':str(uuid4()),'expectedAnalysisRevision':0,'evidenceRefIds':[],
            'protocol':PROTOCOL,'mode':'cockpit_query','snapshotJson':json.dumps({**board(),'ontobaseConnectionId':self.fixture.sessions.connection_id}),
            'taskId':'query','conversationId':None,'expectedConversationVersion':0,'parentRunId':None}
        self.body['expectedServiceRevision']=self.request('policy')[1]['services']['query']['serviceRevision']
    def test_query_only_cannot_prepare_or_ack_even_with_forged_mode_and_empty_canvas_queries(self):
        result=dict(plan=dict(intent='edit',queries=[],actions=[action('add_note',text='candidate')]),usage={},modelCalls=1,
                    engineeringConfirmation=False,purpose='ontovis_analysis',serviceRevision='a'*64)
        with patch('apps.api.assistant_task_api.call_source',return_value=result) as model:
            status,started=self.request('task-start',self.body);self.assertEqual(200,status,started)
            for _ in range(60):
                status,run=self.request('status',dict(runId=started['runId']))
                if run['state'] not in ('reading','model','validating'):break
                time.sleep(.01)
            self.assertEqual('complete',run['state'],run);self.assertEqual('query_only',run['result']['task']['execution'])
            operation=dict(runId=run['runId'],selectedKeys=[],snapshotJson=self.body['snapshotJson'])
            self.assertEqual(403,self.request('task-prepare',operation)[0]);self.assertEqual(403,self.request('task-prepare',{**operation,'mode':'workbench'})[0])
            self.assertEqual(403,self.request('task-ack',{**operation,'savedRevision':None})[0]);self.assertEqual(1,model.call_count)
            self.assertEqual(404,self.request('status',dict(runId=run['runId']),project='B')[0])
            self.assertEqual(run['runId'],self.request('task-start',self.body)[1]['runId']);self.assertEqual(1,model.call_count)
    def test_project_scope_and_extra_executable_fields_fail_before_model(self):
        with patch('apps.api.assistant_task_api.call_source') as model:
            self.assertEqual(422,self.request('task-start',{**self.body,'sql':'select 1'})[0])
            snapshot=json.loads(self.body['snapshotJson']);snapshot['projectCode']='B'
            self.assertEqual(404,self.request('task-start',{**self.body,'snapshotJson':json.dumps(snapshot)})[0]);model.assert_not_called()

    def test_history_scope_and_readonly_source_view_without_registration(self):
        wrong=json.loads(self.body['snapshotJson']);wrong['projectCode']='B'
        self.assertEqual(404,self.request('task-start',{**self.body,'historyJson':json.dumps(dict(undo=wrong))})[0])
        result=dict(plan=dict(intent='query',queries=[],actions=[]),usage={},modelCalls=1,
                    engineeringConfirmation=False,purpose='ontovis_analysis',serviceRevision='a'*64)
        with patch('apps.api.assistant_task_api.call_source',return_value=result):
            status,started=self.request('task-start',self.body);self.assertEqual(200,status,started)
            for _ in range(60):
                _,run=self.request('status',dict(runId=started['runId']))
                if run['state'] not in ('reading','model','validating'):break
                time.sleep(.01)
        sources=[dict(key='E1',kind='document',descriptor=dict(documentId='fixed',contentVersionId='v'),retrievalRevision='a'*64)]
        self.fixture.sessions.assistant.store.update(run['runId'],'complete',sources=sources)
        body=dict(runId=run['runId'],sourceKey='E1')
        with patch('apps.api.analysis_source_reader.AnalysisSourceReader.read',return_value=dict(title='Fixed source')) as read,\
             patch('apps.api.analysis_evidence.AnalysisEvidence.register') as register,\
             patch('apps.api.analysis_preview.preview',return_value=dict(kind='document',gaps=[])):
            status,value=self.request('task-source',body);self.assertEqual(200,status,value)
            read.assert_called_once_with('document',sources[0]['descriptor'])
            self.assertEqual(200,self.request('task-source-preview',{**body,'options':dict(nodeId='root')})[0])
            register.assert_not_called()
            self.assertEqual(404,self.request('task-source',{**body,'sourceKey':'E2'})[0])
            self.assertEqual(422,self.request('task-source',{**body,'descriptor':dict(documentId='foreign')})[0])
            self.assertEqual(404,self.request('task-source',body,project='B')[0])
            self.assertEqual(403,self.request('task-prepare',dict(runId=run['runId'],selectedKeys=[],snapshotJson=self.body['snapshotJson']))[0])
