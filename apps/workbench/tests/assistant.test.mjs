import assert from 'node:assert/strict';
import test from 'node:test';
import {WorkbenchApi,ApiError} from '../src/api.ts';
import {AssistantApi,answerNote,assistantEvidenceKey,assistantMessage,filterEngineeringGraph,mergeConversationTurns,policyChanges,policyProblems,running,watchAssistantRun} from '../src/assistantApi.ts';

const policy={enabled:false,serviceRef:'ontobase-qwen-ontovis-v1',allowedKinds:['alarm','trend'],reads:8,parallel:2,seconds:120};
const view={revision:1,accessRevision:'grant',policy,service:{serviceRevision:'r'}};
test('material E labels follow the submitted selection order, including removal and re-selection',()=>{
 assert.equal(assistantEvidenceKey('alarm',['manual','alarm']),'E2');
 assert.equal(assistantEvidenceKey('manual',['manual','alarm']),'E1');
 assert.equal(assistantEvidenceKey('photo',['manual','alarm']),null);
 assert.equal(assistantEvidenceKey('alarm',['alarm']),'E1');
 assert.equal(assistantEvidenceKey('manual',['alarm','manual']),'E2');
});
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

const settle=()=>new Promise(resolve=>setImmediate(resolve));
test('conversation pages and UID graph use only the fixed owned analysis endpoints',async()=>{
 const calls=[],service=new AssistantApi({request:async(path,body,signal)=>{calls.push({path,body,signal});return {};}}),abort=new AbortController();
 await service.conversations('analysis',3,abort.signal);await service.conversation('conversation',4,abort.signal);await service.graph('analysis',3,'fixed-object',abort.signal);
 assert.deepEqual(calls.map(c=>c.path),['/api/workbench/assistant/conversations','/api/workbench/assistant/conversation','/api/workbench/assistant/graph']);
 assert.deepEqual(calls[1].body,{conversationId:'conversation',beforeTurn:4});assert.deepEqual(calls[2].body,{analysisSessionId:'analysis',expectedAnalysisRevision:3,evidenceRefIds:['fixed-object']});
 assert.ok(calls.every(c=>c.signal===abort.signal));assert.ok(calls.every(c=>!c.path.includes('start')));
});
test('new turn receipts replace by run identity and preserve earlier conversation order',()=>{
 const before=[{runId:'second',conversationVersion:2,state:'model'},{runId:'first',conversationVersion:1,state:'complete'}];
 const merged=mergeConversationTurns(before,{runId:'second',conversationVersion:2,state:'complete'});
 assert.deepEqual(merged.map(v=>v.runId),['first','second']);assert.equal(merged[1].state,'complete');assert.equal(before[0].state,'model');
});
test('graph filtering operates only on returned associations and preserves candidate status',()=>{
 const graph={nodes:[{id:'sensor',title:'温度变送器'},{id:'terminal',title:'X91端子排'},{id:'drawing',title:'机舱传感器图纸'}],relations:[
  {id:'one',source:'sensor',target:'terminal',type:'CANDIDATE_CONNECTION',status:'needs_review'},
  {id:'two',source:'sensor',target:'drawing',type:'DRAWING_LOCATION',status:'recorded'}]};
 assert.equal(filterEngineeringGraph(graph,'','X91')[0].status,'needs_review');assert.equal(filterEngineeringGraph(graph,'DRAWING_LOCATION','温度').length,1);
 assert.equal(filterEngineeringGraph(graph,'KNOWLEDGE_MAPPING','').length,0);assert.equal(graph.relations.length,2);
});
test('temporary status failures recover the same saved run without starting or calling a model',async t=>{
 t.mock.timers.enable({apis:['setTimeout']});const calls=[],updates=[],errors=[],abort=new AbortController();
 const api=new AssistantApi({request:async(path,body)=>{calls.push({path,body});if(calls.length===1)throw new ApiError(502,'SOURCE_UNAVAILABLE');return {runId:'saved',state:'complete',version:8};}});
 const stop=watchAssistantRun(api,{runId:'saved',state:'model',version:5},abort.signal,r=>updates.push(r),(e,retry)=>errors.push(retry));
 t.mock.timers.tick(500);await settle();assert.deepEqual(errors,[true]);assert.equal(updates.length,0);
 t.mock.timers.tick(1000);await settle();assert.equal(updates[0].state,'complete');
 t.mock.timers.tick(60000);await settle();assert.equal(calls.length,2);
 assert.ok(calls.every(c=>c.path==='/api/workbench/assistant/status'&&c.body.runId==='saved'));stop();
});
test('status retries stop after three retries and leave manual recovery available',async t=>{
 t.mock.timers.enable({apis:['setTimeout']});let reads=0;const errors=[],abort=new AbortController();
 const stop=watchAssistantRun({status:async()=>{reads++;throw new TypeError('network');}},{runId:'saved',state:'model'},abort.signal,()=>assert.fail(),(e,retry)=>errors.push(retry));
 for(const delay of [500,1000,2500,5000]){t.mock.timers.tick(delay);await settle();}
 t.mock.timers.tick(60000);await settle();assert.equal(reads,4);assert.deepEqual(errors,[true,true,true,false]);stop();
});
test('permission and version failures do not retry automatically',async t=>{
 t.mock.timers.enable({apis:['setTimeout']});
 for(const status of [401,403,404,409,422]){
  let reads=0;const errors=[],abort=new AbortController();
  const stop=watchAssistantRun({status:async()=>{reads++;throw new ApiError(status,'FORBIDDEN');}},{runId:'saved',state:'model'},abort.signal,()=>assert.fail(),(e,retry)=>errors.push(retry));
  t.mock.timers.tick(500);await settle();t.mock.timers.tick(60000);await settle();assert.equal(reads,1);assert.deepEqual(errors,[false]);stop();
 }
});
test('changing context cancels pending reads and ignores late responses',async t=>{
 t.mock.timers.enable({apis:['setTimeout']});let resolve,reads=0;const abort=new AbortController();
 const stop=watchAssistantRun({status:()=>{reads++;return new Promise(done=>{resolve=done;});}},{runId:'old',state:'model'},abort.signal,()=>assert.fail('late update'),()=>assert.fail('late error'));
 t.mock.timers.tick(500);await settle();abort.abort();resolve({runId:'old',state:'complete'});await settle();t.mock.timers.tick(60000);await settle();assert.equal(reads,1);stop();
});
test('a changed terminal receipt remains changed and never resumes polling or shows its hidden answer',async t=>{
 t.mock.timers.enable({apis:['setTimeout']});let reads=0;const updates=[],abort=new AbortController();
 const stop=watchAssistantRun({status:async()=>{reads++;return {runId:'saved',state:'changed',result:null};}},{runId:'saved',state:'model'},abort.signal,r=>updates.push(r),()=>assert.fail());
 t.mock.timers.tick(500);await settle();t.mock.timers.tick(60000);await settle();assert.equal(reads,1);assert.equal(updates[0].state,'changed');assert.equal(updates[0].result,null);stop();
});
