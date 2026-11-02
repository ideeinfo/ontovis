from pathlib import Path
import json
import os
import sqlite3
import tempfile
from threading import Event
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from uuid import uuid4

from apps.api.assistant_models import AssistantModels,validate_backup_credentials
from apps.api.llm_providers import PROVIDERS,endpoint,infer,catalogue,request_json
from apps.api.model_library import ModelLibrary
from apps.api.authority import PreviewError
from tests.test_assistant import answer
from tests import test_assistant_http as http_fixture

KEY='synthetic-only-key-never-a-real-credential'

class ModelConfigurationTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.library=ModelLibrary(self.root/'library','A',None)
        self.models=AssistantModels(self.library,'source')
    def save(self,change,revision=None,guard=lambda:None,project='A',request=None):
        body={'requestId':request or str(uuid4()),'expectedRevision':self.models.read(project)['revision'] if revision is None else revision,
            'expectedAccessRevision':'grant','change':change}
        return self.models.save(project,'owner',body,guard)
    def provider(self,provider='openai',**changes):
        return dict(kind='provider',provider=provider,baseUrl=PROVIDERS[provider]['baseUrl'],mode='managed',keyAction='replace',apiKey=KEY,**changes)
    def test_defaults_preserve_the_existing_source_and_do_not_create_keys_or_rows(self):
        value=self.models.public(self.models.read('A'));self.assertEqual(len(value['providers']),4)
        self.assertEqual(len(value['tasks']),3);self.assertEqual(value['revision'],0)
        self.assertFalse((self.library.root/'llm-credentials.key').exists())
        inherited=Mock(return_value={'enabled':True,'canRun':True,'serviceRevision':'a'*64,'modelId':'original'})
        profile=self.models.profile('A','analysis',inherited)
        self.assertEqual(profile['serviceRevision'],'a'*64);self.assertEqual(profile['modelId'],'original')
        self.assertNotEqual(self.models.profile('A','query',inherited)['serviceRevision'],'a'*64)
    def test_keys_are_encrypted_scope_bound_and_never_returned_or_audited(self):
        value=self.save(self.provider());self.assertTrue(value['providers'][0]['keyConfigured'])
        self.assertEqual(self.models.credentials('A','openai')[1],KEY)
        self.assertEqual(os.stat(self.library.root/'llm-credentials.key').st_mode&0o777,0o600)
        self.assertNotIn(KEY,(self.library.root/'library.sqlite3').read_bytes().decode('latin1'))
        with self.library.connect() as db:
            for table in ('assistant_model_configs','assistant_model_config_requests','assistant_model_config_events'):
                self.assertNotIn(KEY,repr([tuple(row) for row in db.execute('select * from '+table)]))
            validate_backup_credentials(db,self.library.root)
        self.assertNotIn(KEY,json.dumps(value));self.assertEqual(self.models.read('B')['revision'],0)
        token=self.models.read('A')['config']['providers']['openai']['credential']
        with self.assertRaises(PreviewError):self.models._secret('B','openai',token)
        with self.assertRaises(PreviewError):self.models._secret('A','gemini',token)
    def test_keep_clear_address_change_and_stale_revision(self):
        self.save(self.provider());keep=self.provider()|{'keyAction':'keep','apiKey':None}
        self.save(keep);self.assertEqual(self.models.credentials('A','openai')[1],KEY)
        with self.assertRaises(PreviewError):self.save(keep,revision=0)
        self.save(self.provider('deepseek'))
        with self.assertRaises(PreviewError):self.save(self.provider('deepseek')|{'baseUrl':'https://api.deepseek.com/v1','keyAction':'keep','apiKey':None})
        self.save(keep|{'keyAction':'clear'})
        with self.assertRaises(PreviewError):self.models.credentials('A','openai')
    def test_idempotent_save_and_revocation_before_commit(self):
        request=str(uuid4());change=self.provider();first=self.save(change,revision=0,request=request)
        self.assertEqual(self.save(change,revision=0,request=request),first)
        with self.assertRaises(PreviewError):self.save(change|{'apiKey':KEY+'changed'},revision=0,request=request)
        calls=[]
        def guard():
            calls.append(1)
            if len(calls)==2:raise PreviewError(403,'FORBIDDEN')
        with self.assertRaises(PreviewError):self.save(self.provider('gemini'),guard=guard)
        self.assertEqual(self.models.read('A')['revision'],1)
        self.assertIsNone(self.models.read('A')['config']['providers']['gemini']['credential'])
    def test_task_routes_are_independent_and_credentials_cannot_be_borrowed_across_providers(self):
        self.save(self.provider());self.save(self.provider('deepseek'))
        self.save(dict(kind='task',taskId='analysis',provider='openai',modelId='synthetic-a',enabled=True))
        self.save(dict(kind='task',taskId='query',provider='deepseek',modelId='synthetic-b',enabled=True))
        inherited=Mock(side_effect=AssertionError('No source fallback for configured tasks'))
        a=self.models.profile('A','analysis',inherited);b=self.models.profile('A','query',inherited)
        self.assertEqual((a['provider'],a['modelId']),('openai','synthetic-a'))
        self.assertEqual((b['provider'],b['modelId']),('deepseek','synthetic-b'))
        self.assertNotEqual(a['serviceRevision'],b['serviceRevision'])
        with self.assertRaises(PreviewError):self.save(dict(kind='task',taskId='work_order',provider='gemini',modelId='synthetic-c',enabled=True))
        self.save(dict(kind='task',taskId='analysis',provider='openai',modelId='synthetic-a',enabled=False))
        self.assertFalse(self.models.profile('A','analysis',inherited)['canRun'])
    def test_copy_restores_encrypted_credentials_and_missing_or_unsafe_key_fails_closed(self):
        import shutil
        self.save(self.provider());copy=self.root/'recovered';shutil.copytree(self.library.root,copy)
        restored=AssistantModels(ModelLibrary(copy,'A',None),'source')
        self.assertEqual(restored.credentials('A','openai')[1],KEY)
        (copy/'llm-credentials.key').chmod(0o644)
        with self.assertRaises(PreviewError):restored.credentials('A','openai')
        (copy/'llm-credentials.key').unlink();(copy/'llm-credentials.key').symlink_to(self.library.root/'llm-credentials.key')
        with self.assertRaises(PreviewError):restored.credentials('A','openai')

class ProviderProtocolTests(unittest.TestCase):
    def test_transport_sends_only_to_the_fixed_destination_and_never_echoes_errors_or_retries(self):
        connection=Mock();response=connection.getresponse.return_value
        response.status=200;response.read.return_value=b'{"data":[]}'
        with patch('apps.api.llm_providers.http.client.HTTPSConnection',return_value=connection) as factory:
            self.assertEqual(request_json('openai',PROVIDERS['openai']['baseUrl'],KEY,'GET','/models',None,Event(),time.monotonic()+5),{'data':[]})
            self.assertEqual(factory.call_args.args,('api.openai.com',))
            self.assertEqual(connection.request.call_args.args,('GET','/v1/models'))
            self.assertEqual(connection.request.call_args.kwargs['headers']['Authorization'],'Bearer '+KEY)
            self.assertIsNone(connection.request.call_args.kwargs['body'])
            for status,code in ((302,'LLM_PROVIDER_UNAVAILABLE'),(401,'LLM_AUTH_FAILED'),(429,'LLM_RATE_LIMITED'),(500,'LLM_PROVIDER_UNAVAILABLE')):
                response.status=status;response.read.return_value=KEY.encode();connection.request.reset_mock()
                with self.subTest(status=status),self.assertRaises(PreviewError) as error:
                    request_json('openai',PROVIDERS['openai']['baseUrl'],KEY,'GET','/models',None,Event(),time.monotonic()+5)
                self.assertEqual(error.exception.code,code);self.assertNotIn(KEY,str(error.exception));connection.request.assert_called_once()
    def test_cancelled_or_expired_transport_never_sends_and_cancel_during_io_discards_the_result(self):
        cancelled=Event();cancelled.set()
        with patch('apps.api.llm_providers.http.client.HTTPSConnection') as factory:
            for signal,deadline,code in ((cancelled,time.monotonic()+5,'ASSISTANT_CANCELLED'),(Event(),time.monotonic()-1,'ASSISTANT_TIMEOUT')):
                with self.assertRaises(PreviewError) as error:request_json('openai',PROVIDERS['openai']['baseUrl'],KEY,'GET','/models',None,signal,deadline)
                self.assertEqual(error.exception.code,code)
            factory.assert_not_called()
        signal=Event();connection=Mock();response=connection.getresponse.return_value;response.status=200
        def read(_):signal.set();return b'{"data":[]}'
        response.read.side_effect=read
        with patch('apps.api.llm_providers.http.client.HTTPSConnection',return_value=connection),self.assertRaises(PreviewError) as error:
            request_json('openai',PROVIDERS['openai']['baseUrl'],KEY,'GET','/models',None,signal,time.monotonic()+5)
        self.assertEqual(error.exception.code,'ASSISTANT_CANCELLED');connection.close.assert_called()
    def test_endpoints_reject_arbitrary_hosts_credentials_ports_queries_and_cross_provider_keys(self):
        for provider,p in PROVIDERS.items():self.assertEqual(endpoint(provider,p['baseUrl']),p['baseUrl'])
        self.assertIn('.cn-beijing.maas.aliyuncs.com',endpoint('qwen','https://workspace-demo.cn-beijing.maas.aliyuncs.com/compatible-mode/v1'))
        for url in ('http://api.openai.com/v1','https://127.0.0.1/v1','https://api.openai.com.evil.invalid/v1',
                    'https://user@api.openai.com/v1','https://api.openai.com:444/v1','https://api.openai.com:bad/v1',
                    'https://api.openai.com/v1?key=unsafe','https://api.openai.com/v1#secret','https://api.deepseek.com/v1'):
            with self.subTest(url=url),self.assertRaises(PreviewError):endpoint('openai',url)
    def test_each_provider_receives_its_own_model_and_bounded_protocol(self):
        for provider,p in PROVIDERS.items():
            profile={'taskId':'query','provider':provider,'modelId':'synthetic-model','baseUrl':p['baseUrl'],'serviceRevision':'a'*64}
            response={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(answer())}}],'usage':{'total_tokens':12}}
            with patch('apps.api.llm_providers.request_json',return_value=response) as request:
                result=infer(profile,KEY,{'question':'Synthetic','evidence':[{'key':'E1'}],'history':[]},Event(),time.monotonic()+10)
                payload=request.call_args.args[5]
                self.assertEqual(payload['model'],'synthetic-model');self.assertEqual(result['modelCalls'],1)
                self.assertNotIn('tools',payload);self.assertNotIn('temperature',payload)
                self.assertEqual(payload['max_completion_tokens' if provider=='openai' else 'max_tokens'],1800)
                self.assertEqual('enable_thinking' in payload,provider=='qwen');self.assertEqual('thinking' in payload,provider=='deepseek')
    def test_untrusted_output_incomplete_answers_and_bad_references_are_rejected(self):
        profile={'taskId':'analysis','provider':'openai','modelId':'synthetic','baseUrl':PROVIDERS['openai']['baseUrl'],'serviceRevision':'a'*64}
        for row in ({'finish_reason':'length','message':{'content':'{}'}}, {'finish_reason':'stop','message':{'content':'{}','tool_calls':[{}]}},
                    {'finish_reason':'stop','message':{'content':json.dumps(answer('E8'))}}, {'finish_reason':'stop','message':{'content':'not JSON'}}):
            with patch('apps.api.llm_providers.request_json',return_value={'choices':[row]}),self.assertRaises(PreviewError):
                infer(profile,KEY,{'question':'x','evidence':[{'key':'E1'}],'history':[]},Event(),time.monotonic()+5)
    def test_catalogue_is_a_read_only_account_list_and_does_not_call_generation(self):
        with patch('apps.api.llm_providers.request_json',return_value={'data':[{'id':'b'},{'id':'a'},{'id':'b'},{'id':'bad id'}]}) as request:
            value=catalogue('openai',PROVIDERS['openai']['baseUrl'],KEY)
            self.assertEqual(value,{'items':['a','b'],'modelCalls':0,'verified':'catalogue_only'})
            self.assertEqual(request.call_args.args[3:6],('GET','/models',None))

class ModelConfigurationHttpTests(http_fixture.AssistantHttpTests):
    def finished(self,run_id):
        for _ in range(150):
            status,value=self.request('status',{'runId':run_id})
            self.assertEqual(status,200,value)
            if value['state'] not in ('reading','model','validating','cancel_requested'):return value
            time.sleep(.01)
        self.fail('run did not finish')

    def test_configuration_change_cancels_an_active_provider_call_and_hides_late_answers(self):
        self.enable();self.save_provider()
        task_change=dict(requestId=str(uuid4()),expectedRevision=1,expectedAccessRevision='Demo-PDS:admin',change=dict(
            kind='task',taskId='query',provider='openai',modelId='synthetic-query',enabled=True))
        self.assertEqual(self.request('model-config-save',task_change)[0],200)
        profile=self.request('policy')[1]['services']['query'];entered=Event();cancelled_seen=Event()
        signal=[]
        def slow(_profile,_key,_body,cancelled,_deadline):
            signal.append(cancelled)
            entered.set();self.assertTrue(cancelled.wait(3));cancelled_seen.set()
            return {'answer':answer(),'usage':{},'purpose':'ontovis_analysis','serviceRevision':profile['serviceRevision'],'modelCalls':1,'engineeringConfirmation':False}
        with patch('apps.api.llm_providers.infer',side_effect=slow) as model:
            status,started=self.request('start',self.start_body()|{'taskId':'query','expectedServiceRevision':profile['serviceRevision']})
            self.assertEqual(status,200,started);self.assertTrue(entered.wait(3))
            self.assertEqual(self.request('model-config-save',task_change)[0],200)
            self.assertFalse(signal[0].is_set(),'Replayed saves cannot cancel a later run')
            self.assertEqual(self.save_provider(revision=2,apiKey=KEY+'new')[0],200)
            run=self.finished(started['runId']);self.assertTrue(cancelled_seen.is_set());self.assertEqual(run['state'],'changed',run)
            self.assertIsNone(run['result']);model.assert_called_once()

    def test_a_conversation_keeps_its_task_and_cannot_silently_change_provider_intent(self):
        self.enable();result={'answer':answer(),'usage':{},'purpose':'ontovis_analysis','serviceRevision':'a'*64,'modelCalls':1,'engineeringConfirmation':False}
        with patch('apps.api.assistant_service.call_source',return_value=result):
            status,first=self.request('start',self.start_body()|dict(conversationId=None,expectedConversationVersion=0,parentRunId=None))
            self.assertEqual(status,200);first=self.finished(first['runId'])
            profile=self.request('policy')[1]['services']['query']
            body=self.start_body()|dict(taskId='query',expectedServiceRevision=profile['serviceRevision'],conversationId=first['conversationId'],expectedConversationVersion=1,parentRunId=first['runId'])
            status,value=self.request('start',body);self.assertEqual(status,409,value)
            self.assertEqual(value['code'],'LLM_CONVERSATION_TASK_CHANGED')
    def save_provider(self,provider='openai',revision=0,**changes):
        body=dict(kind='provider',provider=provider,baseUrl=PROVIDERS[provider]['baseUrl'],mode='managed',keyAction='replace',apiKey=KEY)|changes
        return self.request('model-config-save',dict(requestId=str(uuid4()),expectedRevision=revision,expectedAccessRevision='Demo-PDS:admin',change=body))
    def test_model_permissions_scope_stale_changes_and_key_redaction(self):
        status,first=self.request('model-config');self.assertEqual(status,200)
        self.assertEqual(self.save_provider()[0],200);self.assertEqual(self.save_provider()[0],409)
        self.assertNotIn(KEY,json.dumps(self.request('model-config')[1]))
        self.assertEqual(self.request('model-config',project='B')[1]['revision'],0)
        self.assertEqual(self.request('model-config',origin=False)[0],403)
        http_fixture.ProjectsAuthority.permissions['member']['Demo-PDS']='viewer'
        self.assertFalse(self.request('model-config')[1]['canManage']);self.assertEqual(self.save_provider(revision=1)[0],403)
        self.assertEqual(self.request('model-catalogue',{})[0],403)
    def test_catalogue_cannot_reuse_another_endpoint_or_survive_revocation(self):
        self.assertEqual(self.save_provider('deepseek')[0],200)
        body=dict(provider='deepseek',baseUrl=PROVIDERS['deepseek']['baseUrl'],apiKey=None,expectedRevision=1,expectedAccessRevision='Demo-PDS:admin')
        with patch('apps.api.llm_providers.catalogue',return_value={'items':['synthetic'],'modelCalls':0,'verified':'catalogue_only'}) as call:
            status,value=self.request('model-catalogue',body);self.assertEqual(status,200,value);self.assertNotIn(KEY,json.dumps(value))
            self.assertEqual(call.call_args.args[2],KEY)
            self.assertEqual(self.request('model-catalogue',body|{'baseUrl':'https://api.deepseek.com/v1'})[0],422)
        def revoke(*_):
            http_fixture.ProjectsAuthority.permissions['member']['Demo-PDS']='viewer'
            return {'items':['must-not-be-returned'],'modelCalls':0,'verified':'catalogue_only'}
        with patch('apps.api.llm_providers.catalogue',side_effect=revoke):
            status,value=self.request('model-catalogue',body)
            self.assertEqual(status,409,value);self.assertNotIn('must-not-be-returned',json.dumps(value))
    def test_an_actual_run_uses_the_configured_task_model_and_old_default_still_runs(self):
        self.assertEqual(self.enable()[0],200);self.assertEqual(self.save_provider()[0],200)
        status,_=self.request('model-config-save',dict(requestId=str(uuid4()),expectedRevision=1,expectedAccessRevision='Demo-PDS:admin',change=dict(
            kind='task',taskId='query',provider='openai',modelId='synthetic-query',enabled=True)))
        self.assertEqual(status,200);profile=self.request('policy')[1]['services']['query']
        result={'answer':answer(),'usage':{},'purpose':'ontovis_analysis','serviceRevision':profile['serviceRevision'],'modelCalls':1,'engineeringConfirmation':False}
        with patch('apps.api.llm_providers.infer',return_value=result) as model,patch('apps.api.assistant_service.call_source') as legacy:
            body=self.start_body()|{'taskId':'query','expectedServiceRevision':profile['serviceRevision']}
            status,started=self.request('start',body);self.assertEqual(status,200,started)
            for _ in range(100):
                _,run=self.request('status',{'runId':started['runId']})
                if run['state'] not in ('reading','model','validating'):break
                time.sleep(.01)
            self.assertEqual(run['state'],'complete',run);self.assertEqual(model.call_args.args[0]['modelId'],'synthetic-query');legacy.assert_not_called()
            self.assertEqual(run['taskId'],'query');self.assertEqual(run['result']['model']['provider'],'openai')
