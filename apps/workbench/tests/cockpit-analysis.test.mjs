import test from 'node:test';
import assert from 'node:assert/strict';
import {cockpitAnalysisIndex,cockpitAnalysisDetail,cockpitAnalysisHistorical,cockpitSavedTurns,cockpitAnalysisTurns,cockpitNoteRecords} from '../src/cockpitAnalysisState.ts';
import {cockpitAnalysisLayout,cockpitCardMove,cockpitCardPosition,cockpitCanvasFit,cockpitCanvasZoom,cockpitCanvasPan,cockpitCanvasFocus,cockpitCanvasWheel,COCKPIT_CANVAS_MIN_ZOOM,COCKPIT_CANVAS_MAX_ZOOM} from '../src/cockpitAnalysisCanvas.ts';
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
test('one complete canvas includes every saved card without pagination or mutation of fixed views and coordinates',()=>{
 const cards=Array.from({length:49},(_,i)=>({...card('card-'+i,['photo','document','model3d','analysis','trend'][i%5]),pinned:i%2===0,view:{zoom:.9,centerX:.3,centerY:.7}}));
 cards.splice(7,0,card('alarm','alarm'));const saved=JSON.stringify(cards),layout=cockpitAnalysisLayout(cards);
 assert.equal(layout.cards.length,50);assert.equal(layout.total,50);assert.equal(layout.center.id,'alarm');assert.equal(new Set(layout.cards.map(c=>c.id)).size,50);assert.equal('page' in layout,false);
 const overlap=(a,b)=>a.x<b.x+b.width&&a.x+a.width>b.x&&a.y<b.y+b.height&&a.y+a.height>b.y;
 for(const placed of layout.cards){assert.ok(placed.x>=0&&placed.y>=0&&placed.x+placed.width<=layout.width&&placed.y+placed.height<=layout.height);assert.ok(!layout.cards.some(c=>c.id!==placed.id&&overlap(c,placed)));assert.deepEqual(placed.view,cards.find(c=>c.id===placed.id).view);}
 assert.equal(JSON.stringify(cards),saved);
});
test('empty and single-card canvases have a valid fit and retain a central alarm anchor',()=>{
 assert.deepEqual(cockpitAnalysisLayout([]).cards,[]);assert.equal(cockpitAnalysisLayout([card('one')]).cards.length,1);
 assert.deepEqual(cockpitCanvasFit([], {width:800,height:600}),{x:24,y:24,zoom:1});
 const cards=[card('alarm','alarm'),card('drawing','drawing')],original=cockpitAnalysisLayout(cards),moved=cockpitAnalysisLayout(cards,{alarm:{x:0,y:0}});
 assert.deepEqual(moved.cards.find(c=>c.kind==='alarm'),original.cards.find(c=>c.kind==='alarm'));
});
test('card movement accounts for rendered world zoom and interface density exactly once',()=>{
 const value=card('drawing','drawing'),size={width:2000,height:1000};
 const position=cockpitCardMove(value,{x:150,y:35},{width:1000,height:500},size);assert.deepEqual(position,{x:340,y:130});
 assert.deepEqual(cockpitCardMove(value,{x:300,y:70},{width:2000,height:1000},size),position);
 assert.deepEqual(cockpitCardMove(value,{x:75,y:17.5},{width:500,height:250},size),position);
});
test('dragged cards remain in the complete logical canvas, independently of the visible viewport',()=>{
 const value=card('drawing','drawing'),size={width:2000,height:1000};
 assert.deepEqual(cockpitCardMove(value,{x:-9999,y:9999},size,size),{x:0,y:760});assert.deepEqual(cockpitCardPosition(value,{x:Infinity,y:NaN},size),{x:40,y:60});
 for(const rendered of [{width:0,height:700},{width:1000,height:0},{width:NaN,height:700}])assert.deepEqual(cockpitCardMove(value,{x:40,y:60},rendered,size),{x:40,y:60});
 assert.deepEqual(cockpitCardMove(value,{x:NaN,y:60},size,size),{x:40,y:60});
});
test('temporary card positions do not alter saved views, source identities or the fault anchor',()=>{
 const cards=[card('alarm','alarm'),...Array.from({length:13},(_,i)=>({...card('drawing-'+i,'drawing'),view:{zoom:.7,centerX:.3,centerY:.4}}))],saved=JSON.stringify(cards);
 const positions={'drawing-0':{x:600,y:500},alarm:{x:0,y:0},'drawing-8':{x:240,y:90}},moved=cockpitAnalysisLayout(cards,positions),original=cockpitAnalysisLayout(cards);
 assert.deepEqual(moved.cards.find(c=>c.id==='alarm'),original.cards.find(c=>c.id==='alarm'));
 assert.deepEqual([moved.cards.find(c=>c.id==='drawing-8').x,moved.cards.find(c=>c.id==='drawing-8').y],[240,90]);
 assert.deepEqual(moved.cards.find(c=>c.id==='drawing-0').view,cards[1].view);assert.equal(JSON.stringify(cards),saved);
 assert.deepEqual(cockpitAnalysisLayout(cards,positions),moved);assert.deepEqual(cockpitAnalysisLayout(cards,{}),original);
});
test('relationship geometry follows moved cards while retaining all direct registered edges',()=>{
 const cards=[card('alarm','alarm'),card('drawing','drawing')],saved=JSON.stringify(cards),original=cockpitAnalysisLayout(cards),moved=cockpitAnalysisLayout(cards,{drawing:{x:100,y:50}});
 const edge={id:'source',fromRef:cards[0].source.id,toRef:cards[1].source.id,kind:'reference',label:'Drawing source',reason:'Fixed evidence',origin:'source',anchor:null,from:cards[0],to:cards[1]};
 const graph=cockpitRelationGraph(cards,moved.cards,[edge],[],{[cards[0].source.id]:'available',[cards[1].source.id]:'available'},[]);
 assert.equal(graph.length,1);assert.equal(graph[0].to.x,100);assert.equal(graph[0].label,'Drawing source');assert.notDeepEqual(cockpitRelationRoute(graph[0].from,graph[0].to),cockpitRelationRoute(original.cards[1],original.cards[0]));assert.equal(JSON.stringify(cards),saved);
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

test('the complete initial layout places varied material types before repeated drawings',()=>{
 const cards=[card('alarm','alarm'),card('drawing1','drawing'),card('drawing2','drawing'),card('drawing3','drawing'),card('model','model3d'),card('manual','document'),card('photo','photo')];
 assert.deepEqual(cockpitAnalysisLayout(cards).cards.filter(row=>row.kind!=='alarm').map(row=>row.kind).slice(0,3),['drawing','model3d','document']);
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
 const cards=[alarm,object,cabinet,drawing,photo,model,manual,card('trend','trend')],saved=JSON.stringify(cards),visible=cockpitAnalysisLayout(cards).cards.filter(c=>!['sensor','cabinet'].includes(c.id));
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
test('uniform world-space labels remain outside cards and do not overlap on the complete diagram',()=>{
 const cards=[card('alarm','alarm'),card('drawing','drawing'),card('model','model3d'),card('manual','document'),card('photo','photo'),card('trend','trend')];
 const layout=cockpitAnalysisLayout(cards),alarm=layout.cards.find(c=>c.kind==='alarm'),links=layout.cards.filter(c=>c!==alarm).map(target=>({id:target.id,route:cockpitRelationRoute(alarm,target)}));
 const sizes=Object.fromEntries(links.map(link=>[link.id,{width:105,height:22}])),positions=cockpitRelationLabels(links,layout.cards,sizes,layout.width,layout.height,layout),boxes=[];
 const overlap=(a,b)=>a.x<b.x+b.width&&a.x+a.width>b.x&&a.y<b.y+b.height&&a.y+a.height>b.y;
 for(const link of links){const point=positions[link.id],box={x:point.x-52.5,y:point.y-11,width:105,height:22};assert.ok(!layout.cards.some(c=>overlap(box,c)),link.id);assert.ok(!boxes.some(other=>overlap(box,other)),link.id);boxes.push(box);}
});
test('fit all includes every one of 50 cards at large and compact viewport sizes',()=>{
 const layout=cockpitAnalysisLayout(Array.from({length:50},(_,i)=>card(String(i),i?'drawing':'alarm')));
 for(const size of [{width:1464,height:718},{width:942,height:375.5}]){const view=cockpitCanvasFit(layout.cards,size);for(const c of layout.cards){assert.ok(view.x+c.x*view.zoom>=23);assert.ok(view.y+c.y*view.zoom>=23);assert.ok(view.x+(c.x+c.width)*view.zoom<=size.width-23);assert.ok(view.y+(c.y+c.height)*view.zoom<=size.height-23);}}
});
test('zoom preserves the world point under the pointer, including clamp boundaries and reset to 100%',()=>{
 const view={x:-220,y:75,zoom:.7},point={x:411,y:199},before={x:(point.x-view.x)/view.zoom,y:(point.y-view.y)/view.zoom};
 for(const next of [.01,.4,1,3]){const after=cockpitCanvasZoom(view,next,point);assert.ok(Math.abs((point.x-after.x)/after.zoom-before.x)<1e-8);assert.ok(Math.abs((point.y-after.y)/after.zoom-before.y)<1e-8);assert.ok(after.zoom>=COCKPIT_CANVAS_MIN_ZOOM&&after.zoom<=COCKPIT_CANVAS_MAX_ZOOM);}
 assert.equal(cockpitCanvasZoom(view,NaN,point),view);assert.equal(cockpitCanvasZoom(view,1,{x:Infinity,y:1}),view);
});
test('canvas pan preserves scale and card focus centers a readable target without changing source data',()=>{
 const view={x:20,y:40,zoom:.4},value=card('d','drawing'),saved=JSON.stringify(value),size={width:942,height:375};
 assert.deepEqual(cockpitCanvasPan(view,{x:100,y:-10}),{x:120,y:30,zoom:.4});assert.equal(cockpitCanvasPan(view,{x:NaN,y:0}),view);
 const focus=cockpitCanvasFocus(view,value,size);assert.ok(focus.zoom>=.85);assert.ok(Math.abs(focus.x+(value.x+value.width/2)*focus.zoom-size.width/2)<1e-8);assert.ok(Math.abs(focus.y+(value.y+value.height/2)*focus.zoom-size.height/2)<1e-8);assert.equal(JSON.stringify(value),saved);
});
test('plain media gestures stay local, while modified wheel and the pan tool navigate the whole canvas',()=>{
 assert.equal(cockpitCanvasWheel(true,false,false),false);assert.equal(cockpitCanvasWheel(true,true,false),true);assert.equal(cockpitCanvasWheel(true,false,true),true);assert.equal(cockpitCanvasWheel(false,false,false),true);
});
