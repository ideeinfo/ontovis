import assert from 'node:assert/strict';
import test from 'node:test';
import {ApiError,WorkbenchApi} from '../src/api.ts';
import {EventStreamDecoder,readServerEvents} from '../src/eventStream.ts';
import {applySimulationEvent,emptySimulationStream} from '../src/simulationStream.ts';
import {receiveSimulation,streamDelay} from '../src/useSimulationStream.ts';

const profile={datasetId:'SIM-PDS-13001',datasetRevision:'b'.repeat(64),sourceKind:'simulated',sourceConnectionId:'simulated',epoch:'epoch',timeFrom:'2026-10-25T00:00:00Z',timeTo:'2026-10-25T00:03:00Z',engineeringConfirmation:false};
const stamp=s=>new Date(Date.parse(profile.timeFrom)+s*1000).toISOString();
const alarms=[{sourceEventId:'event',sourceRevision:'1',state:'active',severity:'warning',sourceTime:stamp(30)},
  {sourceEventId:'event',sourceRevision:'2',state:'cleared',severity:'warning',sourceTime:stamp(150)}];
const baseline={dataset:profile,alarms,trends:[{metricId:'temperature',unit:'degC',timeFrom:profile.timeFrom,timeTo:profile.timeTo,
  samples:Array.from({length:181},(_,i)=>({sourceTime:stamp(i),value:i===90?null:24,quality:i===90?'bad':'good'}))}]};
const journal='a'.repeat(64),cursor=s=>`s1:${journal}:1793232000000:${s}`;
const frame=(event,body,id='')=>({event,id,data:JSON.stringify(body)});
const ready=()=>frame('ready',{sessionRevision:'r1',dataset:profile,journalRevision:journal,sourceMode:'simulated_stream',accessCheckSeconds:5,staleAfterSeconds:5});
const payload=(s,extra={})=>({sessionRevision:'r1',datasetId:profile.datasetId,datasetRevision:profile.datasetRevision,epoch:profile.epoch,
  journalRevision:journal,sequence:s,sourceTime:stamp(s),sourceWatermark:s,deliveredAt:1793232000000,...extra});
const snapshot=s=>frame('snapshot',payload(s,{detail:{...baseline,alarms:alarms.filter(a=>Date.parse(a.sourceTime)<=Date.parse(stamp(s))),trends:baseline.trends.map(t=>({...t,samples:t.samples.slice(0,s+1)}))}}),cursor(s));
const sample=(s,extra={})=>frame('sample',payload(s,{samples:[{...baseline.trends[0].samples[s],metricId:'temperature',unit:'degC'}],alarms:alarms.filter(a=>a.sourceTime===stamp(s)),...extra}),cursor(s));
const stateAt=s=>applySimulationEvent(applySimulationEvent(emptySimulationStream(),ready(),baseline,'r1'),snapshot(s),baseline,'r1');
const wire=events=>events.map(e=>`event: ${e.event}\nid: ${e.id}\ndata: ${e.data}\n\n`).join('');
const response=events=>new Response(wire(events),{headers:{'Content-Type':'text/event-stream; charset=utf-8','X-Session-Revision':'r1'}});

test('event decoder handles split CRLF, BOM, comments and multiline UTF8 fields',()=>{
  const value='\uFEFF: keepalive\r\nevent: snapshot\r\nid: cursor\r\ndata: 中文\r\ndata: 第二行\r\n\r\n';
  const parser=new EventStreamDecoder(),result=[];for(const char of value)result.push(...parser.push(char));
  assert.deepEqual(result,[{event:'snapshot',id:'cursor',data:'中文\n第二行'}]);
  assert.deepEqual(parser.push('data: unfinished'),[]);
});
test('decoder accepts multiple bounded frames in a large chunk and rejects an oversized event',()=>{
  const parser=new EventStreamDecoder();assert.equal(parser.push(('data: '+'x'.repeat(50000)+'\n\n').repeat(6)).length,6);
  assert.throws(()=>new EventStreamDecoder().push('data: '+'x'.repeat(262145)),/STREAM_PROTOCOL_INVALID/);
  assert.throws(()=>new EventStreamDecoder().push('data: x\n\n'.repeat(401)),/STREAM_PROTOCOL_INVALID/);
});
test('stream reader bounds bytes, rejects malformed UTF8 and cancels on timeout or context change',async()=>{
  let cancelled=0;
  const silent=new ReadableStream({cancel(){cancelled++;}});
  await assert.rejects(readServerEvents(silent,()=>{},()=>{},5),/STREAM_STALLED/);assert.equal(cancelled,1);
  const oversized=new ReadableStream({start(c){c.enqueue(new Uint8Array(1048577));},cancel(){cancelled++;}});
  await assert.rejects(readServerEvents(oversized,()=>{},()=>{}),/STREAM_PROTOCOL_INVALID/);
  const invalid=new ReadableStream({start(c){c.enqueue(new Uint8Array([255]));c.close();}});
  await assert.rejects(readServerEvents(invalid,()=>{},()=>{}),TypeError);
  const changed=new ReadableStream({start(c){c.enqueue(new TextEncoder().encode('data: x\n\n'));},cancel(){cancelled++;}});
  await assert.rejects(readServerEvents(changed,()=>assert.fail('late data'),()=>{throw new DOMException('changed','AbortError');}),{name:'AbortError'});
});
test('initial stream snapshot contains only reached history and ordered samples preserve bad gaps',()=>{
  let state=stateAt(87);assert.equal(state.detail.trends[0].samples.length,88);assert.equal(state.detail.alarms.length,1);
  for(let i=88;i<=91;i++)state=applySimulationEvent(state,sample(i,{sourceWatermark:93}),baseline,'r1',i);
  assert.equal(state.sequence,91);assert.equal(state.watermark,93);
  assert.equal(state.detail.trends[0].samples[90].quality,'bad');assert.equal(state.detail.trends[0].samples[90].value,null);
  assert.equal(state.detail.trends[0].samples.length,92);
});
test('duplicates and old sequences do not overwrite newer state or advance its cursor',()=>{
  const state=stateAt(60);
  assert.equal(applySimulationEvent(state,sample(60),baseline,'r1'),state);
  assert.equal(applySimulationEvent(state,sample(59),baseline,'r1'),state);
  assert.throws(()=>applySimulationEvent(state,sample(62),baseline,'r1'),/STREAM_SEQUENCE_GAP/);
});
test('dataset, source epoch, cursor anchor, timestamps and units cannot cross a stream',()=>{
  const state=stateAt(60);
  for(const changed of [sample(61,{epoch:'different'}),sample(61,{datasetId:'other'}),sample(61,{sourceTime:stamp(62)}),
    {...sample(61),id:cursor(61).replace('1793232000000','1793232000001')},
    sample(61,{samples:[{...baseline.trends[0].samples[61],metricId:'temperature',unit:'V'}]})]){
    assert.throws(()=>applySimulationEvent(state,changed,baseline,'r1'));
  }
  assert.throws(()=>applySimulationEvent(state,ready(),baseline,'other'));
  assert.throws(()=>applySimulationEvent(state,frame('ready',{...JSON.parse(ready().data),journalRevision:'c'.repeat(64)}),baseline,'r1'),/STREAM_SOURCE_CHANGED/);
});
test('complete requires the actual end position and never changes work-order status',()=>{
  assert.throws(()=>applySimulationEvent(stateAt(60),frame('complete',payload(180)),baseline,'r1'));
  const state=applySimulationEvent(stateAt(180),frame('complete',payload(180)),baseline,'r1');
  assert.equal(state.complete,true);assert.equal(state.detail.trends[0].samples.length,181);
  assert.equal(state.detail.alarms.at(-1).state,'cleared');assert.equal(Object.hasOwn(state,'workOrder'),false);
});
test('simulation API uses a fixed POST path, scoped body and cookies without URL credentials',async()=>{
  let sent,seen=[];const api=new WorkbenchApi(async(path,options)=>{sent={path,options};return response([ready(),snapshot(180),frame('complete',payload(180))]);});
  api.session('r1');api.selectProject({ontobaseConnectionId:'source',projectCode:'Demo-PDS'});
  await api.subscribeSimulation({datasetId:profile.datasetId,datasetRevision:profile.datasetRevision,fromSecond:180},e=>seen.push(e),new AbortController().signal);
  assert.equal(sent.path,'/api/workbench/analysis-sessions/simulation/stream');assert.equal(sent.options.method,'POST');
  assert.equal(sent.options.credentials,'same-origin');assert.equal(sent.options.cache,'no-store');
  const body=JSON.parse(sent.options.body);assert.equal(body.expectedSessionRevision,'r1');assert.deepEqual(body.projectRef,api.project);
  assert.equal(sent.options.headers.Authorization,undefined);assert.equal(seen.length,3);
});
test('wrong MIME or session revision cannot feed private stream state',async()=>{
  for(const headers of [{'Content-Type':'application/json','X-Session-Revision':'r1'},{'Content-Type':'text/event-stream','X-Session-Revision':'old'}]){
    const api=new WorkbenchApi(async()=>new Response('data: invalid\n\n',{headers}));api.session('r1');api.selectProject({ontobaseConnectionId:'source',projectCode:'A'});
    await assert.rejects(api.subscribeSimulation({},()=>assert.fail('invalid response'),new AbortController().signal),e=>e.code==='STREAM_PROTOCOL_INVALID');
  }
});
test('mid-stream revocation removes project access and cancels before another business frame',async()=>{
  let denied=0,seen=[];const api=new WorkbenchApi(async()=>response([ready(),frame('stream-error',{sessionRevision:'r1',status:403,code:'FORBIDDEN'}),snapshot(60)]));
  api.session('r1');api.selectProject({ontobaseConnectionId:'source',projectCode:'Demo-PDS'});api.onProjectDenied=()=>denied++;
  await assert.rejects(api.subscribeSimulation({},e=>seen.push(e),new AbortController().signal),e=>e.status===403);
  assert.equal(denied,1);assert.deepEqual(seen.map(e=>e.event),['ready']);
});
test('project changes invalidate a delayed stream response before applying its frames',async()=>{
  let resolve;const api=new WorkbenchApi(()=>new Promise(r=>resolve=r));api.session('r1');api.selectProject({ontobaseConnectionId:'source',projectCode:'A'});
  const pending=api.subscribeSimulation({},()=>assert.fail('late frame'),new AbortController().signal);
  api.selectProject({ontobaseConnectionId:'source',projectCode:'B'});resolve(response([ready(),snapshot(60)]));
  await assert.rejects(pending,{name:'AbortError'});
});
test('reconnect resumes only after the last applied cursor and uses bounded backoff',async()=>{
  const bodies=[],delays=[],updates=[];let calls=0;
  const api={revision:'r1',epoch:0,async subscribeSimulation(body,onEvent){bodies.push(body);calls++;
    onEvent(ready());if(calls===1){onEvent(snapshot(179));throw new TypeError('network');}
    onEvent(sample(180));onEvent(frame('complete',payload(180)));
  }};
  await receiveSimulation(api,baseline,emptySimulationStream(),179,new AbortController().signal,(s,status)=>updates.push(status),async ms=>delays.push(ms));
  assert.deepEqual(delays,[1000]);assert.equal(bodies[0].fromSecond,179);assert.equal(bodies[1].cursor,cursor(179));
  assert.equal(Object.hasOwn(bodies[1],'fromSecond'),false);assert.ok(updates.includes('reconnecting'));assert.equal(updates.at(-1),'complete');
});
test('repeated empty EOF stops after five retries and permission errors do not retry',async()=>{
  for(const forbidden of [false,true]){
    let count=0;const delays=[],updates=[];
    const api={revision:'r1',epoch:0,async subscribeSimulation(){count++;if(forbidden)throw new ApiError(403,'FORBIDDEN');}};
    await receiveSimulation(api,baseline,emptySimulationStream(),0,new AbortController().signal,(_,status)=>updates.push(status),async ms=>delays.push(ms));
    assert.equal(count,forbidden?1:6);assert.deepEqual(delays,forbidden?[]:[1000,2000,4000,8000,15000]);assert.equal(updates.at(-1),'stopped');
  }
});
test('cancelling backoff returns promptly without another connection',async()=>{
  const controller=new AbortController(),pending=streamDelay(100000,controller.signal);controller.abort();
  await assert.rejects(pending,{name:'AbortError'});
  await assert.rejects(streamDelay(100000,controller.signal),{name:'AbortError'});
});
