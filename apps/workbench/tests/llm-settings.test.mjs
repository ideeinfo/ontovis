import test from 'node:test';
import assert from 'node:assert/strict';
import {llmTaskNames,llmProviderNames,modelTaskState,modelChoices,providerChange,modelConfigurationApi} from '../src/llmSettings.ts';
import {WorkbenchApi,ApiError} from '../src/api.ts';
import {assistantMessage} from '../src/assistantApi.ts';

test('four providers and three actual task choices are exposed without invented model IDs',()=>{
 assert.deepEqual(Object.keys(llmProviderNames),['openai','gemini','qwen','deepseek']);
 assert.deepEqual(Object.keys(llmTaskNames),['analysis','query','work_order']);
 assert.deepEqual(modelChoices(['B-text','a-text','B-text'],' TEXT '),['B-text','a-text']);
 assert.deepEqual(modelChoices(['alpha','beta'],'unavailable'),[]);
});
test('leaving the key blank keeps it, replacement is explicit, and clear never submits a typed secret',()=>{
 const original={id:'openai',baseUrl:'https://api.openai.com/v1',mode:'managed',keyConfigured:true};
 assert.deepEqual(providerChange(original,original.baseUrl,'managed','',false),{kind:'provider',provider:'openai',baseUrl:original.baseUrl,mode:'managed',keyAction:'keep',apiKey:null});
 assert.equal(providerChange(original,original.baseUrl,'managed','synthetic-only',false).keyAction,'replace');
 const cleared=providerChange(original,original.baseUrl,'managed','synthetic-only',true);
 assert.equal(cleared.keyAction,'clear');assert.equal(cleared.apiKey,null);
});
test('save and catalogue pin the displayed access and configuration revision without generating content',async()=>{
 const calls=[],client=modelConfigurationApi({request:async(path,body)=>{calls.push({path,body});return {};}}),view={revision:4,accessRevision:'project-grant'};
 await client.save(view,{kind:'task',taskId:'query',provider:'gemini',modelId:'synthetic-text',enabled:true},'fixed-request');
 await client.catalogue(view,'gemini','https://generativelanguage.googleapis.com/v1beta/openai',null);
 assert.equal(calls[0].body.expectedRevision,4);assert.equal(calls[0].body.expectedAccessRevision,'project-grant');
 assert.equal(calls[0].body.requestId,'fixed-request');assert.equal(calls[0].body.change.taskId,'query');
 assert.ok(calls[1].path.endsWith('/model-catalogue'));assert.equal(calls[1].body.apiKey,null);
 assert.equal('question' in calls[1].body,false);
});
test('a captured model settings request cannot save a key to the next selected project',async()=>{
 const calls=[];const api=new WorkbenchApi(async(path,options)=>{calls.push(JSON.parse(options.body));return new Response(JSON.stringify({sessionRevision:'session'}),{headers:{'Content-Type':'application/json'}});});
 api.session('session');api.selectProject({ontobaseConnectionId:'source',projectCode:'A'});const service=modelConfigurationApi(api);
 api.selectProject({ontobaseConnectionId:'source',projectCode:'B'});
 await service.save({revision:0,accessRevision:'A:admin'},{kind:'provider',provider:'openai',baseUrl:'https://api.openai.com/v1',mode:'managed',keyAction:'replace',apiKey:'synthetic-not-real'});
 assert.equal(calls[0].projectRef.projectCode,'A');assert.equal(api.project.projectCode,'B');
});
test('provider errors explain the required action and never claim that credentials were verified',()=>{
 assert.match(assistantMessage(new ApiError(502,'LLM_AUTH_FAILED')),/密钥/);
 assert.match(assistantMessage('LLM_CONFIGURATION_CHANGED',true),/refresh/);
 assert.match(assistantMessage('LLM_CONVERSATION_TASK_CHANGED'),/新建对话/);
 assert.match(assistantMessage('LLM_NEW_ENDPOINT_KEY_REQUIRED'),/重新填写/);
});

test('an unavailable inherited source is distinct from missing settings and a viewer can see configured models',()=>{
 const task={enabled:true},inherited={mode:'inherited'},managed={mode:'managed'};
 assert.equal(modelTaskState(task,inherited,{enabled:false,canRun:false}),'unavailable');
 assert.equal(modelTaskState(task,inherited,{enabled:true,canRun:false}),'ready');
 assert.equal(modelTaskState(task,managed,{enabled:false,canRun:false}),'missing');
 assert.equal(modelTaskState({enabled:false},inherited,{enabled:false,canRun:false}),'off');
});
