import test from 'node:test';
import assert from 'node:assert/strict';
import {cockpitAnalysisIndex,cockpitAnalysisDetail,cockpitAnalysisPage,cockpitAnalysisPageFor,cockpitAnalysisHistorical,cockpitSavedTurns,cockpitAnalysisTurns} from '../src/cockpitAnalysisState.ts';
import {analysisEntryRequest} from '../src/analysisSources.ts';
const scope={ontobaseConnectionId:'source',projectCode:'project'},signal=()=>new AbortController().signal;
const dataset={datasetId:'fault-a',datasetRevision:'v1'},item={analysisSessionId:'canvas-a',analysisRevision:3,title:'Related canvas',reason:'Same fault',eventId:'fault-a-event-1'};
const ref={system:'ontovis',...scope,id:'evidence',revision:'r1'};
const card=(id,kind='analysis')=>({id,kind,title:id,x:40,y:60,width:300,height:240,pinned:false,...(kind==='analysis'?{note:'Saved note'}:{source:{...ref,id:'evidence-'+id}})});
const detail=(overrides={})=>({analysisSessionId:'canvas-a',analysisRevision:3,contentSha256:'fixed',snapshot:{schemaVersion:2,...scope,title:'Fault investigation',status:'analyzing',context:{objectIds:[],faultCode:'13001',...dataset,eventId:'fault-a-event-1',timeFrom:'2026-10-25T00:00:00Z',timeTo:'2026-10-25T00:03:00Z',timezone:'UTC'},cards:[card('alarm','alarm'),card('note')],relations:[],viewport:{x:10,y:20,zoom:.8}},...overrides});
const api=(request)=>({...scope,project:scope,revision:'session',epoch:1,request});

test('fault recommendations are read only and never open the unfiltered canvas list or start an analysis',async()=>{
 const calls=[],service=api(async(path,body)=>{calls.push({path,body});if(path.endsWith('/history-candidates'))return {items:[item]};if(path.endsWith('/detail'))return detail();throw Error('Unexpected operation');});
 const index=await cockpitAnalysisIndex(service,dataset,signal());
 assert.deepEqual(index.items,[item]);assert.equal(index.initial,null);
 await cockpitAnalysisDetail(service,index.items[0],signal(),'13001');
 assert.deepEqual(calls,[{path:'/api/workbench/analysis-sessions/history-candidates',body:{entry:dataset}},{path:'/api/workbench/analysis-sessions/detail',body:{analysisSessionId:'canvas-a',analysisRevision:3}}]);
});
test('missing fault context stays empty without substituting the latest unrelated canvas',async()=>{
 const service=api(async()=>{throw Error('No request expected');});
 for(const entry of [null,{entityUid:'device',expectedEntityRevision:'r1',timeTo:'2026-10-25T00:03:00Z'},{projectOnly:true}]){
  assert.deepEqual(await cockpitAnalysisIndex(service,entry,signal()),{entry:null,items:[],initial:null});
 }
});
test('explicit fixed revision remains selected when the head advances and only related recommendations accompany it',async()=>{
 const calls=[],fixed=detail(),head={...item,analysisRevision:4},other={...item,analysisSessionId:'history-b'};
 const service=api(async(path,body)=>{calls.push(body);return path.endsWith('/detail')?fixed:{items:[head,other,other]};});
 const value=await cockpitAnalysisIndex(service,{analysisSessionId:'canvas-a',analysisRevision:3},signal());
 assert.equal(value.initial,fixed);assert.equal(value.items[0].analysisRevision,3);assert.equal(value.items[0].title,'Fault investigation');
 assert.deepEqual(value.items.map(row=>row.analysisSessionId),['canvas-a','history-b']);assert.deepEqual(calls[0],{analysisSessionId:'canvas-a',analysisRevision:3});assert.deepEqual(calls[1],{entry:dataset});
});
test('cross-project, different revision and wrong fault responses are blocked',async()=>{
 for(const invalid of [detail({analysisRevision:4}),detail({analysisSessionId:'other'}),detail({snapshot:{...detail().snapshot,projectCode:'other'}})]){
  await assert.rejects(cockpitAnalysisDetail(api(async()=>invalid),item,signal(),'13001'),/ANALYSIS_CHANGED/);
 }
 await assert.rejects(cockpitAnalysisDetail(api(async()=>detail()),item,signal(),'13002'),/ANALYSIS_CONTEXT_MISMATCH/);
});
test('authorization and unavailable recommendations never fall back to another query or create a draft',async()=>{
 const calls=[],failure=new Error('Access removed');
 await assert.rejects(cockpitAnalysisIndex(api(async(path)=>{calls.push(path);throw failure;}),dataset,signal()),error=>error===failure);
 assert.deepEqual(calls,['/api/workbench/analysis-sessions/history-candidates']);
});
test('display pagination covers every saved card and leaves all source views, positions, pins and input order untouched',()=>{
 const cards=Array.from({length:49},(_,i)=>({...card('card-'+i,['photo','document','model3d','analysis','trend'][i%5]),pinned:i%2===0,view:{zoom:.9,centerX:.3,centerY:.7}}));
 cards.splice(7,0,card('alarm','alarm'));const saved=JSON.stringify(cards);
 for(const capacity of [3,5]){
  const first=cockpitAnalysisPage(cards,0,capacity),visited=new Set();
  for(let p=0;p<first.count;p++){
   const layout=cockpitAnalysisPage(cards,p,capacity);assert.ok(layout.cards.length<=capacity+1);assert.equal(layout.center.id,'alarm');
   for(const placed of layout.cards){visited.add(placed.id);assert.ok(placed.x>=0&&placed.y>=0&&placed.x+placed.width<=1000&&placed.y+placed.height<=700);}
  }
  assert.equal(visited.size,50);const id=first.others.at(-1).id,target=cockpitAnalysisPageFor(cards,id,capacity);
  assert.ok(cockpitAnalysisPage(cards,target,capacity).cards.some(c=>c.id===id));
 }
 assert.equal(JSON.stringify(cards),saved);
});
test('empty, single-card and out-of-range page layouts are bounded and readable',()=>{
 assert.deepEqual(cockpitAnalysisPage([],99).cards,[]);assert.equal(cockpitAnalysisPage([card('one')],20).cards.length,1);
 assert.equal(cockpitAnalysisPage([card('one')],-20).page,0);
});
test('independent recurrence and fixed dataset revisions retain historical status even with the same fault code',()=>{
 assert.equal(cockpitAnalysisHistorical(detail(),dataset),false);
 assert.equal(cockpitAnalysisHistorical(detail(),{...dataset,datasetId:'recurrence'}),true);
 assert.equal(cockpitAnalysisHistorical(detail(),{...dataset,datasetRevision:'v2'}),true);
});
test('saved assistant records are read without any model operation and cannot cross fixed analysis revisions',async()=>{
 const receipt=detail(),valid={runId:'run',analysisSessionId:'canvas-a',analysisRevision:3,state:'complete'},wrong={...valid,runId:'wrong',analysisRevision:2};
 assert.deepEqual(cockpitSavedTurns([wrong,valid,{...valid,analysisSessionId:'other'}],receipt),[valid]);
 const calls=[],service=api(async(path,body)=>{calls.push({path,body});if(path.endsWith('/conversations'))return {items:[{conversationId:'thread'}]};if(path.endsWith('/conversation'))return {items:[wrong,valid]};throw Error('No model operations allowed');});
 assert.deepEqual(await cockpitAnalysisTurns(service,receipt,signal()),[valid]);
 assert.deepEqual(calls,[{path:'/api/workbench/assistant/conversations',body:{analysisSessionId:'canvas-a',expectedAnalysisRevision:3}},{path:'/api/workbench/assistant/conversation',body:{conversationId:'thread'}}]);
});
test('backend new intent is local; edit reads the latest head while fixed links retain their exact revision',()=>{
 assert.equal(analysisEntryRequest({newDraft:true},'request'),null);
 assert.deepEqual(analysisEntryRequest({...item,openLatest:true},'request'),{path:'/api/workbench/analysis-sessions/detail',body:{analysisSessionId:'canvas-a'},fixed:false});
 assert.deepEqual(analysisEntryRequest(item,'request'),{path:'/api/workbench/analysis-sessions/detail',body:{analysisSessionId:'canvas-a',analysisRevision:3},fixed:true});
 assert.deepEqual(analysisEntryRequest(dataset,'request'),{path:'/api/workbench/analysis-sessions/start',body:{entry:dataset,requestId:'request'},fixed:false});
});
