import test from 'node:test';
import assert from 'node:assert/strict';
import {cockpitAnalysisIndex,cockpitAnalysisDetail,cockpitAnalysisPage,cockpitAnalysisPageFor,cockpitAnalysisHistorical,cockpitSavedTurns,cockpitAnalysisTurns,cockpitNoteRecords} from '../src/cockpitAnalysisState.ts';
import {analysisEntryRequest} from '../src/analysisSources.ts';
import {cockpitRelationGraph,cockpitRelationLabels,cockpitRelationRoute} from '../src/cockpitRelationGraph.ts';
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

test('the first evidence group shows different available material types before repeated drawings',()=>{
 const cards=[card('alarm','alarm'),card('drawing1','drawing'),card('drawing2','drawing'),card('drawing3','drawing'),card('model','model3d'),card('manual','document'),card('photo','photo')];
 assert.deepEqual(cockpitAnalysisPage(cards,0,3).cards.filter(row=>row.kind!=='alarm').map(row=>row.kind),['drawing','model3d','document']);
});
test('saved structured notes keep their actual sections while ordinary notes keep their original text',()=>{
 const value={...card('note'),note:'观察：已保存观察\n\n原因假设：仍待验证\n\n反证与缺口：尚缺现场证据'};
 const original=value.note,records=cockpitNoteRecords([value]);
 assert.deepEqual(records.map(row=>row.id),['observations','hypotheses','gaps']);assert.deepEqual(records.map(row=>row.rows[0].text),['已保存观察','仍待验证','尚缺现场证据']);assert.equal(value.note,original);
 assert.equal(cockpitNoteRecords([{...card('plain'),note:'自由格式的原始记录'}])[0].rows[0].text,'自由格式的原始记录');
});

const sourceLink=(from,to,label='Registered relation',origin='source')=>({id:from.id+'-'+to.id,fromRef:from.source.id,toRef:to.source.id,kind:'reference',label,reason:'Existing fixed source relationship',origin,anchor:{entityUid:'fixed-object'},from,to});
const ready=cards=>Object.fromEntries(cards.filter(c=>c.source).map(c=>[c.source.id,'available']));
test('off-page engineering objects retain their existing relationship paths between visible media',()=>{
 const alarm=card('alarm','alarm'),object=card('sensor','object'),cabinet=card('cabinet','object'),drawing=card('drawing','drawing'),photo=card('photo','photo'),model=card('model','model3d'),manual=card('manual','document');
 const cards=[alarm,object,cabinet,drawing,photo,model,manual,card('trend','trend')],saved=JSON.stringify(cards),visible=cockpitAnalysisPage(cards).cards;
 const edges=[sourceLink(alarm,object,'Alarm object'),sourceLink(object,cabinet,'Parent equipment'),sourceLink(object,drawing,'Drawing location'),sourceLink(object,photo,'Photo location'),sourceLink(cabinet,model,'Model candidate','candidate'),sourceLink(alarm,manual,'Fault manual')];
 const graph=cockpitRelationGraph(cards,visible,edges,[],ready(visible),[]);
 assert.equal(graph.length,4);assert.equal(graph.filter(edge=>edge.via.length>0).length,3);
 assert.deepEqual(graph.find(edge=>edge.to.id==='model').via.map(c=>c.id),['sensor','cabinet']);
 assert.equal(graph.find(edge=>edge.to.id==='model').origin,'candidate');
 assert.ok(graph.find(edge=>edge.to.id==='photo').label.includes('经对象'));assert.equal(JSON.stringify(cards),saved);
});
test('unavailable or changed hidden objects cannot produce a shortcut, while candidate notices remain explicit',()=>{
 const alarm=card('alarm','alarm'),object=card('object','object'),model=card('model','model3d'),cards=[alarm,object,model],edges=[sourceLink(alarm,object),sourceLink(object,model,'Same-name candidate','candidate')],visible=[alarm,model];
 assert.equal(cockpitRelationGraph(cards,visible,edges,[],ready(visible),[{evidenceRefId:object.source.id,reason:'ENGINEERING_CHANGED'}]).length,0);
 assert.equal(cockpitRelationGraph(cards,visible,edges,[],{...ready(visible),[object.source.id]:'restricted'},[]).length,0);
 assert.equal(cockpitRelationGraph(cards,visible,edges,[],ready(visible),[{evidenceRefId:object.source.id,reason:'MODEL_NAME_CANDIDATE_ONLY'}])[0].origin,'candidate');
 assert.equal(cockpitRelationGraph(cards,visible,edges,[],{[alarm.source.id]:'available'},[]).length,0);
});
test('the projection keeps direct links and avoids an inferred complete graph between all cards sharing an object',()=>{
 const alarm=card('alarm','alarm'),object=card('object','object'),a=card('a','photo'),b=card('b','drawing'),c=card('c','model3d'),cards=[alarm,object,a,b,c],edges=[sourceLink(alarm,object),sourceLink(object,a),sourceLink(object,b),sourceLink(object,c),sourceLink(a,b,'Direct drawing reference')],visible=[alarm,a,b,c];
 const graph=cockpitRelationGraph(cards,visible,edges,[],ready(visible),[]);
 assert.equal(graph.length,3);assert.ok(graph.some(edge=>edge.label==='Direct drawing reference'&&!edge.via.length));
 assert.equal(graph.filter(edge=>edge.via.length).length,2);
});
test('projection never crosses a historical boundary or treats unregistered common context as a relation',()=>{
 const alarm=card('alarm','alarm'),object=card('object','object'),photo={...card('photo','photo'),historical:true},trend=card('trend','trend'),cards=[alarm,object,photo,trend],edges=[sourceLink(alarm,object),sourceLink(object,photo)];
 assert.deepEqual(cockpitRelationGraph(cards,[alarm,photo,trend],edges,[],ready(cards),[]),[]);
 assert.deepEqual(cockpitRelationGraph(cards,[alarm,trend],[],[],ready(cards),[]),[]);
});
test('saved manual support and contradiction labels retain their exact meaning without source promotion',()=>{
 const a=card('a'),b=card('b'),saved=[{id:'manual',from:a.id,to:b.id,kind:'contradicts',origin:'manual',reason:'Saved counter-evidence'}];
 const graph=cockpitRelationGraph([a,b],[a,b],[],saved,{},[]);
 assert.equal(graph[0].label,'反证');assert.equal(graph[0].origin,'manual');assert.equal(graph[0].reason,'Saved counter-evidence');assert.equal(graph[0].via.length,0);
});
test('relationship label anchors stay in the gaps between the displayed cards at both capacities',()=>{
 const cards=[card('alarm','alarm'),card('drawing','drawing'),card('model','model3d'),card('manual','document'),card('photo','photo'),card('trend','trend')];
 for(const capacity of [3,5]){
  const layout=cockpitAnalysisPage(cards,0,capacity),alarm=layout.cards.find(c=>c.kind==='alarm');
  for(const target of layout.cards.filter(c=>c!==alarm)){
   const route=cockpitRelationRoute(alarm,target);
   assert.ok(Number.isFinite(route.x)&&Number.isFinite(route.y));assert.ok(route.d.startsWith('M'));
   assert.ok(!layout.cards.some(c=>route.x>c.x&&route.x<c.x+c.width&&route.y>c.y&&route.y<c.y+c.height));
  }
 }
});
test('natural-sized relation labels avoid cards and each other at actual large and compact board dimensions',()=>{
 const cards=[card('alarm','alarm'),card('drawing','drawing'),card('model','model3d'),card('manual','document'),card('photo','photo'),card('trend','trend')];
 for(const [capacity,width,height] of [[5,1464,718],[3,942,375.5]]){
  const layout=cockpitAnalysisPage(cards,0,capacity),alarm=layout.cards.find(c=>c.kind==='alarm');
  const links=layout.cards.filter(c=>c!==alarm).map(target=>({id:target.id,route:cockpitRelationRoute(alarm,target)}));
  const sizes=Object.fromEntries(links.map((link,i)=>[link.id,{width:[105,127,81,105,105][i],height:22}]));
  const positions=cockpitRelationLabels(links,layout.cards,sizes,width,height),boxes=[];
  const overlap=(a,b)=>a.x<b.x+b.width&&a.x+a.width>b.x&&a.y<b.y+b.height&&a.y+a.height>b.y;
  for(const link of links){const point=positions[link.id],w=sizes[link.id].width/width*1000,h=22/height*700,box={x:point.x-w/2,y:point.y-h/2,width:w,height:h};
   assert.ok(!layout.cards.some(c=>overlap(box,c)),link.id);assert.ok(!boxes.some(other=>overlap(box,other)),link.id);boxes.push(box);
   const route=cockpitRelationRoute(alarm,layout.cards.find(c=>c.id===link.id),point);assert.equal(route.x,point.x);assert.equal(route.y,point.y);
  }
 }
});
