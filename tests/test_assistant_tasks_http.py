import json
import time
import unittest
from unittest.mock import patch
from uuid import uuid4
from tests import test_assistant_http as fixture
from tests.test_assistant import answer
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
            self.body['preferSelectedEvidence']=True
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
            self.assertEqual(422,self.request('task-start',{**self.body,'preferSelectedEvidence':'yes'})[0])
            snapshot=json.loads(self.body['snapshotJson']);snapshot['projectCode']='B'
            self.assertEqual(404,self.request('task-start',{**self.body,'snapshotJson':json.dumps(snapshot)})[0]);model.assert_not_called()

    def test_same_canvas_restores_only_the_current_mode_and_rejects_cross_mode_followups(self):
        body = {**self.body, 'analysisSessionId': self.fixture.analysis, 'expectedAnalysisRevision': 1}
        history = {k: body[k] for k in ('analysisSessionId', 'expectedAnalysisRevision')}
        result = dict(plan=dict(intent='edit', queries=[], actions=[action('add_note', text='synthetic note')]),
                      usage={}, modelCalls=1, engineeringConfirmation=False, purpose='ontovis_analysis',
                      serviceRevision='a'*64)
        def complete(mode):
            status, started = self.request('task-start', {**body, 'requestId': str(uuid4()), 'mode': mode})
            self.assertEqual(200, status, started)
            for _ in range(60):
                _, run = self.request('status', {'runId': started['runId']})
                if run['state'] not in ('reading', 'model', 'validating'):
                    break
                time.sleep(.01)
            self.assertEqual('complete', run['state'], run)
            return run

        with (patch('apps.api.assistant_task_api.call_source', return_value=result) as model,
              patch('apps.api.assistant_task_api.analysis_store') as open_store):
            store = open_store.return_value.__enter__.return_value
            store.detail.return_value = {'lifecycle': 'active'}
            store.schema_version = 2
            workbench = complete('workbench')
            cockpit = complete('cockpit_query')
            for mode, run, foreign in [('workbench', workbench, cockpit), ('cockpit_query', cockpit, workbench)]:
                status, listing = self.request('conversations', {**history, 'mode': mode})
                self.assertEqual(200, status, listing)
                self.assertEqual([(run['conversationId'], mode)], [(item['conversationId'], item['mode']) for item in listing['items']])
                status, blocked = self.request('task-start', {**body, 'requestId': str(uuid4()), 'mode': mode,
                    'conversationId': foreign['conversationId'], 'expectedConversationVersion': foreign['conversationVersion'],
                    'parentRunId': foreign['runId']})
                self.assertEqual((409, 'ASSISTANT_CONVERSATION_MODE_CHANGED'), (status, blocked['code']))
            self.assertEqual(2, model.call_count)
        self.assertEqual({workbench['conversationId'], cockpit['conversationId']},
                         {item['conversationId'] for item in self.request('conversations', history)[1]['items']})
        self.assertEqual(422, self.request('conversations', {**history, 'mode': 'invalid'})[0])

    def test_processing_catalogue_retains_source_state_and_skips_answer_generation(self):
        plan=dict(intent='query',queries=[dict(tool='processing_tasks',query='',faultCode='',orderId='')],actions=[])
        model_reply=dict(plan=plan,usage={'total_tokens':31},modelCalls=1,engineeringConfirmation=False,
                         purpose='ontovis_analysis',serviceRevision='a'*64)
        task=dict(id=str(uuid4()),title='Fixed source task',kind='drawing_recognition',
                  state='unknown',result_state='not_formed',source_available=True)
        authority=fixture.ProjectsAuthority.request
        def request(instance,method,path,body=None):
            if path=='/api/v1/projects/Demo-PDS/processing-tasks?q=&cursor=0&limit=6':
                self.assertEqual('GET',method)
                return dict(items=[task],next_cursor=6)
            return authority(instance,method,path,body)

        with patch.object(fixture.ProjectsAuthority,'request',request), \
             patch('apps.api.assistant_task_api.call_source',return_value=model_reply) as model:
            status,started=self.request('task-start',self.body)
            self.assertEqual(200,status,started)
            for _ in range(60):
                _,run=self.request('status',dict(runId=started['runId']))
                if run['state'] not in ('reading','model','validating'):
                    break
                time.sleep(.01)
            self.assertEqual('partial',run['state'],run)
            self.assertEqual(1,model.call_count)
        result=run['result']
        self.assertEqual(1,result['modelCalls'])
        self.assertEqual({'total_tokens':31},result['usage'])
        self.assertEqual(('unknown','not_formed'),tuple(result['task']['results'][0][key] for key in ('state','resultState')))
        self.assertEqual([],result['answer']['hypotheses'])
        self.assertEqual([],result['answer']['nextSteps'])
        self.assertEqual(['E1'],result['answer']['observations'][0]['refs'])
        self.assertTrue(result['answer']['gaps'])

    def test_scene_candidate_cannot_create_a_draft_or_cross_project_scope(self):
        scene = dict(sceneId=str(uuid4()), displayName='Crystal Rig', headRevision='scene:' + str(uuid4()), instanceCount=91)
        self.body['mode'] = 'workbench'
        common = dict(usage={}, modelCalls=1, engineeringConfirmation=False, purpose='ontovis_analysis', serviceRevision='a'*64)
        plan = dict(intent='query', queries=[dict(tool='scenes',query='Crystal Rig',faultCode='',orderId='')], actions=[])
        listing = dict(items=[scene], snapshotRevision='list:3', nextCursor=None)
        with patch('apps.api.assistant_task_api.call_source', side_effect=[{**common, 'plan':plan},{**common, 'answer':answer()}]) as model,\
             patch('apps.api.scene_library.SceneLibrary.listing', return_value=listing) as scenes:
            status, started = self.request('task-start', self.body)
            self.assertEqual(200, status, started)
            for _ in range(60):
                _, run = self.request('status', dict(runId=started['runId']))
                if run['state'] not in ('reading','model','validating'):
                    break
                time.sleep(.01)
            self.assertEqual('complete', run['state'], run)
            self.assertTrue(json.loads(model.call_args_list[0].args[2]['workflow']['context'])['sceneDirectory'])
            self.assertEqual('Demo-PDS:admin', scenes.call_args.kwargs['access_revision'])
            self.assertEqual('Crystal Rig', scenes.call_args.kwargs['q'])
            self.assertEqual(91, run['result']['task']['results'][0]['instanceCount'])
            self.assertEqual(404, self.request('status', dict(runId=run['runId']), project='B')[0])
        selection = dict(runId=run['runId'], selectedKeys=['R1'], snapshotJson=self.body['snapshotJson'])
        with patch('apps.api.assistant_task_api.analysis_store') as store:
            status, rejected = self.request('task-prepare', selection)
            self.assertEqual((403, 'ASSISTANT_TOOL_NOT_ALLOWED'), (status, rejected['code']))
            store.assert_not_called()

    def test_adopted_models_use_the_selected_project_and_remain_read_only(self):
        self.body['mode'] = 'workbench'
        version = str(uuid4())
        listing = dict(items=[dict(configuration='Project choice',title='Exterior',identifier=str(uuid4()),
            version=version,representation='appearance',state='active',instanceCount=0,scenes=[],moreScenes=False)],
            snapshotRevision='fixed-models',total=1,truncated=False,sceneUsageTruncated=False)
        plan = dict(intent='query',queries=[dict(tool='adopted_models',query='',faultCode='',orderId='')],actions=[])
        response = dict(usage={},modelCalls=1,engineeringConfirmation=False,purpose='ontovis_analysis',serviceRevision='a'*64)
        with (
            patch('apps.api.assistant_task_api.call_source',side_effect=[{**response,'plan':plan},{**response,'answer':answer()}]) as model,
            patch('apps.api.assistant_project_models.catalogue',return_value=listing) as directory,
        ):
            status, started = self.request('task-start',self.body)
            self.assertEqual(200,status,started)
            for _ in range(60):
                _,run = self.request('status',dict(runId=started['runId']))
                if run['state'] not in ('reading','model','validating'):
                    break
                time.sleep(.01)
        self.assertEqual('complete',run['state'],run)
        self.assertTrue(json.loads(model.call_args_list[0].args[2]['workflow']['context'])['adoptedModelDirectory'])
        self.assertEqual('Demo-PDS',directory.call_args.args[2].project_code)
        self.assertEqual('Demo-PDS:admin',directory.call_args.args[6])
        self.assertEqual(version,run['result']['task']['results'][0]['version'])
        selection = dict(runId=run['runId'],selectedKeys=['R1'],snapshotJson=self.body['snapshotJson'])
        with patch('apps.api.assistant_task_api.analysis_store') as store:
            status,error = self.request('task-prepare',selection)
            self.assertEqual((403,'ASSISTANT_TOOL_NOT_ALLOWED'),(status,error['code']))
            store.assert_not_called()

    def test_explicit_device_configuration_uses_project_directory_without_a_generated_plan(self):
        hit=dict(title='示例风机',identifier='fixed-device',version='fixed-device:1',
                 configurationId=str(uuid4()),configurationRevision=str(uuid4()),modelCount=2)
        with (
            patch('apps.api.assistant_project_models.device_catalogue',return_value=dict(items=[hit],
                snapshotRevision='fixed',truncated=False)) as directory,
            patch('apps.api.assistant_task_api.call_source') as model,
        ):
            status,started=self.request('task-start',{**self.body,'question':'查询示例风机的设备配置'})
            self.assertEqual(200,status,started)
            for _ in range(60):
                _,run=self.request('status',dict(runId=started['runId']))
                if run['state'] not in ('reading','model','validating'):
                    break
                time.sleep(.01)
            model.assert_not_called()
        self.assertEqual('complete',run['state'],run)
        self.assertEqual(0,run['result']['modelCalls'])
        self.assertEqual('Demo-PDS',directory.call_args.args[0].project_code)
        self.assertEqual('示例风机',directory.call_args.args[3])
        self.assertEqual('query_only',run['result']['task']['execution'])
        self.assertEqual(hit['configurationRevision'],run['result']['task']['results'][0]['configurationRevision'])
        self.assertFalse(run['result']['task']['plan']['actions'])

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
