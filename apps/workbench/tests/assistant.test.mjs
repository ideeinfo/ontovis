import assert from 'node:assert/strict';
import test from 'node:test';
import {WorkbenchApi,ApiError} from '../src/api.ts';
import {AssistantApi,answerNote,assistantMessage,policyChanges,policyProblems,running} from '../src/assistantApi.ts';

const policy={enabled:false,serviceRef:'ontobase-qwen-ontovis-v1',allowedKinds:['alarm','trend'],reads:8,parallel:2,seconds:120};
const view={revision:1,accessRevision:'grant',policy,service:{serviceRevision:'r'}};
test('a cancelled run explains the stop without claiming that its material versions changed',()=>{
 assert.equal(assistantMessage('ASSISTANT_CANCELLED'),'本次运行已停止，未采用模型结果。');
 assert.match(assistantMessage(new ApiError(409,'ASSISTANT_CANCELLED'),true),/stopped/);
});
test('policy differences compare source sets and still expose a same-count substitution',()=>{
 assert.deepEqual(policyChanges(policy,{...policy,allowedKinds:['trend','alarm']}),[]);
 assert.deepEqual(policyChanges(policy,{...policy,allowedKinds:['object','alarm']}),['allowedKinds']);
 assert.deepEqual(policyChanges(policy,{...policy,enabled:true}),['enabled']);
});
test('project policy only accepts the approved service, sources and upper bounds',()=>{
 assert.deepEqual(policyProblems(policy),[]);
 for(const change of [{serviceRef:'custom-endpoint'},{enabled:1},{allowedKinds:['script']},{reads:9},{parallel:3},{seconds:121},{seconds:NaN},{allowedKinds:['alarm','alarm']}])assert.ok(policyProblems({...policy,...change}).length);
});
test('applying and restoring a policy pins scope, access and the displayed revision',async()=>{
 const calls=[];const api=new AssistantApi({request:async(path,body)=>{calls.push({path,body});return {};}});
 await api.publish(view,policy);await api.publish(view,policy,1);
 assert.equal(calls[0].path,'/api/workbench/assistant/publish');assert.equal(calls[1].path,'/api/workbench/assistant/rollback');
 assert.equal(calls[0].body.expectedAccessRevision,'grant');assert.equal(calls[0].body.expectedRevision,1);
 assert.equal(calls[1].body.restoreRevision,1);assert.equal(Object.hasOwn(calls[1].body,'policy'),false);
 assert.notEqual(calls[0].body.requestId,calls[1].body.requestId);assert.equal(Object.hasOwn(calls[0].body,'apiKey'),false);
});
test('stopping a changed run refreshes its version and retries the same monotonic stop intent once',async()=>{
 let calls=[];const api=new AssistantApi({request:async(path,body)=>{calls.push({path,body});if(calls.length===1)throw new ApiError(409,'ASSISTANT_RUN_CHANGED');return {runId:'run',version:3,state:'model'};}});
 await api.cancel({runId:'run',version:1});assert.equal(calls.length,3);assert.equal(calls[1].path,'/api/workbench/assistant/status');assert.equal(calls[2].body.expectedVersion,3);
});
test('captured cancellation scope stays on the former project without changing the active project',async()=>{
 const calls=[];const api=new WorkbenchApi(async(path,options)=>{calls.push({path,body:JSON.parse(options.body)});return new Response(JSON.stringify({sessionRevision:'session'}),{headers:{'Content-Type':'application/json'}});});
 api.session('session');api.selectProject({ontobaseConnectionId:'source',projectCode:'A'});const former=api.assistantScope();
 api.selectProject({ontobaseConnectionId:'source',projectCode:'B'});await former.request('/api/workbench/assistant/cancel',{runId:'run',expectedVersion:1});
 assert.equal(calls[0].body.projectRef.projectCode,'A');assert.equal(api.project.projectCode,'B');
 assert.equal(calls[0].body.expectedSessionRevision,'session');
});
test('a capability denial in assistant settings does not discard an otherwise accessible project',async()=>{
 const api=new WorkbenchApi(async()=>new Response(JSON.stringify({code:'ASSISTANT_RUN_FORBIDDEN'}),{status:403,headers:{'Content-Type':'application/json'}}));
 api.session('session');api.selectProject({ontobaseConnectionId:'source',projectCode:'A'});let denied=0;api.onProjectDenied=()=>denied++;
 await assert.rejects(api.request('/api/workbench/assistant/start',{}),e=>e.code==='ASSISTANT_RUN_FORBIDDEN');assert.equal(denied,0);
});
const result={answer:{observations:[{text:'模拟读数偏高。',refs:['E1']}],hypotheses:[],gaps:[],nextSteps:[]},engineeringConfirmation:false};
test('only validated terminal answers become reversible notes with fixed local reference identities',()=>{
 const run={state:'complete',result,sources:[{key:'E1',availability:'available',evidenceRefId:'fixed-ref',sourceRevision:'r1'}]};
 const note=answerNote(run);assert.ok(note.includes('待人工核验'));assert.ok(note.includes('fixed-ref @ r1'));
 assert.throws(()=>answerNote({...run,state:'model'}));assert.throws(()=>answerNote({...run,sources:[]}));
 assert.equal(running({...run,state:'cancel_requested'}),true);assert.equal(running(run),false);
});
test('long model results are excerpted without truncating the fixed reference footer',()=>{
 const rows=Array.from({length:5},()=>({text:'需人工核验'.repeat(60),refs:['E1']}));
 const run={state:'complete',result:{...result,answer:{observations:rows,hypotheses:rows,gaps:rows,nextSteps:rows}},sources:[{key:'E1',availability:'available',evidenceRefId:'fixed-ref',sourceRevision:'r'.repeat(64)}]};
 const note=answerNote(run);assert.ok(note.length<4000);assert.ok(note.endsWith('r'.repeat(64)));
});
