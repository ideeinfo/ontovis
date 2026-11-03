from pathlib import Path
import json
import tempfile
from threading import Event
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from uuid import uuid4
from apps.api.assistant_models import AssistantModels,defaults,source_configuration,validate_backup_credentials
from apps.api.llm_providers import PROVIDERS,endpoint,infer,catalogue,request_json
from apps.api.model_library import ModelLibrary
from apps.api.authority import PreviewError
from tests.test_assistant import answer
from tests import test_assistant_http as http_fixture

KEY='synthetic-only-key-never-a-real-credential'
CONNECTION=str(uuid4())

class ModelConfigurationTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.library=ModelLibrary(Path(temp.name)/'library','A',None);self.models=AssistantModels(self.library,'source')
    def body(self,settings=None,task='analysis',request=None,revision=None):
        return dict(requestId=request or str(uuid4()),expectedRevision=self.models.read('A')['revision'] if revision is None else revision,
            expectedAccessRevision='grant',change=dict(kind='capability',taskId=task,settings=settings or defaults(task),expectedConnectionVersion=None))
    def save(self,body=None,guard=lambda:None,source=lambda *_:None):return self.models.save('A','owner',body or self.body(),guard,source)
    def test_defaults_do_not_create_rows_or_credentials_and_preserve_legacy_analysis_revision(self):
        value=self.models.public(self.models.read('A'))
        self.assertNotIn('providers',value);self.assertEqual(len(value['tasks']),3)
        self.assertFalse((self.library.root/'llm-credentials.key').exists())
        source=lambda _:{'enabled':True,'canRun':True,'serviceRevision':'a'*64,'modelId':'original'}
        self.assertEqual(self.models.profile('A','analysis',source)['serviceRevision'],'a'*64)
        self.assertNotEqual(self.models.profile('A','query',source)['serviceRevision'],'a'*64)
    def test_capabilities_reuse_connections_and_keep_parameters_independent(self):
        settings={**defaults('query'),'connectionId':CONNECTION,'modelId':'team-model','goal':'仅回答资料问题','tools':['selected_sources']}
        seen=[];body=self.body(settings,'query');body['change']['expectedConnectionVersion']=2
        self.save(body,source=lambda *args:seen.append(args))
        self.assertEqual(seen,[(source_configuration('query',settings),2)])
        public=self.models.public(self.models.read('A'));self.assertEqual(public['tasks'][0]['configured'],False)
        self.assertEqual(next(t for t in public['tasks'] if t['id']=='query')['modelId'],'team-model')
        profiles=[]
        def source(configuration):
            profiles.append(configuration);return dict(enabled=True,canRun=True,serviceRevision='b'*64,provider='future-provider',modelId='team-model')
        profile=self.models.profile('A','query',source)
        self.assertEqual(profile['provider'],'future-provider');self.assertEqual(profiles,[source_configuration('query',settings)])
        self.assertNotIn('apiKey',json.dumps(public));self.assertFalse((self.library.root/'llm-credentials.key').exists())
    def test_only_explicit_capability_fields_and_supported_tools_are_accepted(self):
        for change in ({'apiKey':KEY},{'provider':'openai'},{'endpoint':'http://private'},{'execution':'ontovis'},
                       {'tools':['selected_sources','write']},{'tools':[]},{'timeoutSeconds':51},{'concurrency':3},{'readLimit':9},{'readParallel':True},{'goal':' '}):
            with self.subTest(change=change),self.assertRaises(PreviewError):self.save(self.body({**defaults('analysis'),**change}))
        with self.assertRaises(PreviewError):self.save({**self.body(),'change':{'kind':'provider','apiKey':KEY}})
    def test_stale_source_or_permission_rolls_back_and_replay_does_not_validate_again(self):
        body=self.body();seen=[]
        def fail(*_):raise PreviewError(409,'LLM_CONFIGURATION_CHANGED')
        with self.assertRaises(PreviewError):self.save(body,source=fail)
        self.assertEqual(self.models.read('A')['revision'],0)
        value=self.save(body,source=lambda *_:seen.append(True));self.assertEqual(self.save(body,source=fail),value);self.assertEqual(len(seen),1)
        with self.assertRaises(PreviewError):self.save(self.body(revision=0))
        calls=[]
        def revoke():
            calls.append(True)
            if len(calls)>1:raise PreviewError(403,'FORBIDDEN')
        with self.assertRaises(PreviewError):self.save(self.body(),guard=revoke)
        self.assertEqual(self.models.read('A')['revision'],1)
    def test_disabled_capability_can_be_saved_while_source_is_unavailable(self):
        def unavailable(*_):raise AssertionError('disabled settings should not need a model')
        self.save(self.body({**defaults('analysis'),'enabled':False}),source=unavailable)
        self.assertFalse(self.models.public(self.models.read('A'))['tasks'][0]['enabled'])
    def test_legacy_local_provider_is_inactive_and_preserved_without_rewriting(self):
        self.save()
        with self.library.connect() as db:
            value=json.loads(db.execute('select config_json from assistant_model_configs').fetchone()[0]);value.pop('capabilities')
            value['tasks']['query']=dict(execution='ontovis',provider='openai',modelId='old-model',enabled=True)
            raw=json.dumps(value);db.execute('update assistant_model_configs set config_json=?',(raw,))
        value=self.models.public(self.models.read('A'));task=next(t for t in value['tasks'] if t['id']=='query')
        self.assertTrue(task['legacyNeedsReview']);self.assertFalse(task['enabled'])
        profile=self.models.profile('A','query',lambda _:dict(enabled=True,canRun=True,serviceRevision='a'*64))
        self.assertFalse(profile['canRun']);self.assertEqual(profile['reason'],'LLM_CONNECTION_REVIEW_REQUIRED')
        with self.library.connect() as db:self.assertEqual(db.execute('select config_json from assistant_model_configs').fetchone()[0],raw)
    def test_source_configuration_changes_invalidate_a_configured_capability(self):
        self.save();current=dict(enabled=True,canRun=True,serviceRevision='a'*64)
        first=self.models.profile('A','analysis',lambda _:current);current['serviceRevision']='b'*64
        second=self.models.profile('A','analysis',lambda _:current);self.assertNotEqual(first['serviceRevision'],second['serviceRevision'])

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
    def setUp(self):
        super().setUp();self.source_profiles=[];self.connection_version=2
        original=http_fixture.ProjectsAuthority.request
        def authority(instance,method,path,body=None):
            if path.endswith('/ontovis-assistant/connections'):
                return dict(items=[dict(id=CONNECTION,name='Shared connection',provider='future-provider',version=self.connection_version,keyConfigured=True)],accessRevision='Demo-PDS:admin',modelCalls=0)
            if path.endswith('/ontovis-assistant/profile'):
                self.source_profiles.append(body)
                from apps.api.assistant_store import digest
                return dict(serviceRef='ontobase-qwen-ontovis-v1',purpose='ontovis_analysis',serviceRevision=digest([body,self.connection_version]),
                    accessRevision='Demo-PDS:admin',enabled=True,canRun=True,modelId=body['modelId'] or 'source-default',provider='future-provider',connectionVersion=self.connection_version)
            if path.endswith('/ontovis-assistant/models'):
                return dict(items=['source-text'],reasoningOptions={'source-text':['default']},modelCalls=0)
            return original(instance,method,path,body)
        p=patch.object(http_fixture.ProjectsAuthority,'request',authority);p.start();self.addCleanup(p.stop)
    def save_settings(self,settings=None,task='analysis',revision=0):
        return self.request('model-config-save',dict(requestId=str(uuid4()),expectedRevision=revision,expectedAccessRevision='Demo-PDS:admin',
            change=dict(kind='capability',taskId=task,settings=settings or defaults(task),expectedConnectionVersion=self.connection_version)))
    def test_connection_catalogue_uses_source_refs_and_viewers_cannot_save_or_fetch_models(self):
        status,view=self.request('model-config');self.assertEqual(status,200,view);self.assertEqual(view['connections'][0]['provider'],'future-provider');self.assertNotIn('providers',view)
        body=dict(connectionId=CONNECTION,expectedConnectionVersion=2,expectedRevision=0,expectedAccessRevision='Demo-PDS:admin')
        self.assertEqual(self.request('model-catalogue',body)[1]['items'],['source-text'])
        http_fixture.ProjectsAuthority.permissions['member']['Demo-PDS']='viewer'
        status,view=self.request('model-config');self.assertEqual(status,200,view);self.assertFalse(view['canManage']);self.assertEqual(view['connections'],[])
        self.assertEqual(self.save_settings()[0],403);self.assertEqual(self.request('model-catalogue',body)[0],403)
    def test_saved_capability_uses_source_configuration_for_real_start_and_rechecks_revisions(self):
        self.enable();settings={**defaults('query'),'connectionId':CONNECTION,'modelId':'source-text','goal':'只查所选资料','focus':'保留模拟标签','tools':['selected_sources']}
        self.assertEqual(self.save_settings(settings,'query')[0],200)
        selected=self.request('policy')[1]['services']['query'];body={**self.start_body(),'taskId':'query','expectedServiceRevision':selected['serviceRevision']}
        def model(_authority,_path,data,*_):
            self.assertEqual(data['configuration'],source_configuration('query',settings));self.assertNotIn('apiKey',data);self.assertNotIn('provider',data)
            return dict(answer=answer(),usage={},serviceRevision=selected['sourceServiceRevision'] if 'sourceServiceRevision' in selected else data['expectedServiceRevision'],purpose='ontovis_analysis',modelCalls=1,engineeringConfirmation=False)
        with patch('apps.api.assistant_service.call_source',side_effect=model) as invoke:
            status,run=self.request('start',body);self.assertEqual(status,200,run)
            for _ in range(60):
                _,run=self.request('status',dict(runId=run['runId']))
                if run['state'] not in ('reading','model','validating'):break
                time.sleep(.01)
            self.assertEqual(run['state'],'complete',run);self.assertEqual(invoke.call_count,1)
            self.connection_version=3
            _,changed=self.request('status',dict(runId=run['runId']));self.assertEqual(changed['state'],'changed');self.assertIsNone(changed['result'])
    def test_capability_read_limit_is_enforced_before_start(self):
        self.enable();settings={**defaults('analysis'),'readLimit':1}
        self.assertEqual(self.save_settings(settings)[0],200)
        selected=self.request('policy')[1]['services']['analysis'];body={**self.start_body(),'evidenceRefIds':[self.evidence,str(uuid4())],'expectedServiceRevision':selected['serviceRevision']}
        self.assertEqual(self.request('start',body)[1]['code'],'ASSISTANT_READ_LIMIT')
