import test from 'node:test';
import assert from 'node:assert/strict';
import {cockpitAnalysisIndex,cockpitAnalysisDetail,cockpitAnalysisHistorical,cockpitSavedTurns,cockpitAnalysisTurns,cockpitNoteRecords} from '../src/cockpitAnalysisState.ts';
import {cockpitAnalysisLayout,cockpitCardMove,cockpitCardOutsideFrame,cockpitCanvasFit,cockpitCanvasZoom,cockpitCanvasPan,cockpitCanvasFocus,cockpitCanvasReveal,cockpitCanvasWheel,COCKPIT_CANVAS_MIN_ZOOM,COCKPIT_CANVAS_MAX_ZOOM} from '../src/cockpitAnalysisCanvas.ts';
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
 const cards=Array.from({length:50},(_,i)=>({...card('card-'+i,i===7?'alarm':['photo','document','model3d','analysis','trend'][i%5]),
  x:i%7*370-1100,y:Math.floor(i/7)*290-800,width:300+i,height:240+i/2,pinned:i%2===0,view:{zoom:.9,centerX:.3,centerY:.7}}));
 const saved=JSON.stringify(cards),layout=cockpitAnalysisLayout({cards});
 assert.equal(layout.cards.length,50);assert.deepEqual(layout.cards,cards);assert.deepEqual(layout.frames,[]);
 assert.equal(layout.bounds.x,-1100);assert.equal(layout.bounds.y,-800);
 assert.equal(JSON.stringify(cards),saved);
});
test('empty and single-card canvases have a valid fit and the initial fault position can be moved',()=>{
 const empty=cockpitAnalysisLayout();assert.deepEqual(empty.cards,[]);
 assert.deepEqual(cockpitCanvasFit(empty.bounds,{width:800,height:600}),{x:24,y:24,zoom:1});
 const alarm=card('alarm','alarm'),one=cockpitAnalysisLayout({cards:[alarm]},{alarm:{x:0,y:0}});
 assert.deepEqual(one.cards,[{...alarm,x:0,y:0}]);assert.deepEqual(one.bounds,{x:0,y:0,width:alarm.width,height:alarm.height});
});
test('card movement accounts for rendered world zoom and interface density exactly once',()=>{
 const value=card('drawing','drawing');
 for(const scale of [.25,.5,1,1.5,2]){
  const position=cockpitCardMove(value,{x:300*scale,y:70*scale},{width:value.width*scale,height:value.height*scale});
  assert.deepEqual(position,{x:340,y:130});
 }
});
test('drag can leave the saved bounds on either side and invalid movement keeps the saved position',()=>{
 const value=card('drawing','drawing');
 assert.deepEqual(cockpitCardMove(value,{x:-900,y:2000},value),{x:-860,y:2060});
 assert.deepEqual(cockpitCardMove(value,{x:1200,y:-1000},value),{x:1240,y:-940});
 for(const rendered of [{width:0,height:700},{width:1000,height:0},{width:NaN,height:700}])assert.deepEqual(cockpitCardMove(value,{x:40,y:60},rendered),{x:40,y:60});
 assert.deepEqual(cockpitCardMove(value,{x:NaN,y:60},value),{x:40,y:60});
 assert.deepEqual(cockpitAnalysisLayout({cards:[value]},{drawing:{x:Infinity,y:NaN}}).cards,[value]);
});
test('only the frame whose members move expands or shrinks around their temporary positions',()=>{
 const frames=[{id:'current',title:'本次调查',x:-520,y:-160,width:680,height:510},
  {id:'history',title:'历史参考',x:-310,y:722,width:740,height:390}];
 const cards=[{...card('alarm','alarm'),frameId:'current',x:-500,y:-80},
  {...card('drawing','drawing'),frameId:'history',x:-290,y:760,width:405,view:{zoom:.7,centerX:.3,centerY:.4}},
  {...card('photo','photo'),frameId:'history',x:140,y:760,width:260}];
 const snapshot={cards,frames},saved=JSON.stringify(snapshot),initial=cockpitAnalysisLayout(snapshot);
 assert.deepEqual(initial.frames,frames);assert.deepEqual(initial.cards,cards);
 assert.deepEqual(initial.bounds,{x:-520,y:-160,width:950,height:1272});
 const moved=cockpitAnalysisLayout(snapshot,{drawing:{x:-930,y:1400}});
 assert.deepEqual(moved.frames,[frames[0],{...frames[1],x:-950,width:1370,height:938}]);
 assert.deepEqual(moved.cards,[cards[0],{...cards[1],x:-930,y:1400},cards[2]]);
 assert.equal(cockpitCardOutsideFrame(moved.cards[1],frames[1]),true);
 assert.equal(cockpitCardOutsideFrame(moved.cards[1],moved.frames[1]),false);
 assert.equal(cockpitCardOutsideFrame(moved.cards[2],moved.frames[1]),false);
 assert.deepEqual(moved.bounds,{x:-950,y:-160,width:1370,height:1820});
 const narrowed=cockpitAnalysisLayout(snapshot,{drawing:{x:-120,y:1050}});
 assert.deepEqual(narrowed.frames[1],{...frames[1],x:-140,width:560,height:588});
 assert.deepEqual(cockpitAnalysisLayout(snapshot,{drawing:{x:-290,y:760}}),initial);
 const far=cockpitAnalysisLayout(snapshot,{drawing:{x:-24000,y:20100}});
 assert.equal(cockpitCardOutsideFrame(far.cards[1],far.frames[1]),false);
 assert.equal(JSON.stringify(snapshot),saved);assert.deepEqual(cockpitAnalysisLayout(snapshot),initial);
});
test('relationship geometry follows the moved current alarm and evidence while retaining registered edges',()=>{
 const cards=[card('alarm','alarm'),card('drawing','drawing')],saved=JSON.stringify(cards),original=cockpitAnalysisLayout({cards}),moved=cockpitAnalysisLayout({cards},{alarm:{x:-240,y:-20},drawing:{x:100,y:50}});
 const edge={id:'source',fromRef:cards[0].source.id,toRef:cards[1].source.id,kind:'reference',label:'Drawing source',reason:'Fixed evidence',origin:'source',anchor:null,from:cards[0],to:cards[1]};
 const graph=cockpitRelationGraph(cards,moved.cards,[edge],[],{[cards[0].source.id]:'available',[cards[1].source.id]:'available'},[]);
 assert.equal(graph.length,1);assert.equal(graph[0].from.x,-240);assert.equal(graph[0].from.y,-20);assert.equal(graph[0].to.x,100);assert.equal(graph[0].label,'Drawing source');
 const route=cockpitRelationRoute(graph[0].from,graph[0].to);assert.equal(route.y,-32);
 assert.notDeepEqual(route,cockpitRelationRoute(...original.cards));assert.equal(JSON.stringify(cards),saved);
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
 const cards=[alarm,object,cabinet,drawing,photo,model,manual,card('trend','trend')],saved=JSON.stringify(cards),visible=cards.filter(c=>!['sensor','cabinet'].includes(c.id));
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
test('source matches between different saved groups cannot produce direct or indirect cross-group links',()=>{
 const alarm={...card('alarm','alarm'),frameId:'group-a'},object={...card('object','object'),frameId:'group-a'};
 const otherAlarm={...alarm,id:'other-alarm',frameId:'group-b'},drawing={...card('drawing','drawing'),frameId:'group-b'};
 const cards=[alarm,object,otherAlarm,drawing];
 const edges=[sourceLink(alarm,object),sourceLink(otherAlarm,object),sourceLink(object,drawing),sourceLink(otherAlarm,drawing)];
 assert.deepEqual(cockpitRelationGraph(cards,[alarm,otherAlarm,drawing],edges,[],ready(cards),[]).map(link=>link.id),['other-alarm-drawing']);
 const saved=[{id:'authored',from:alarm.id,to:drawing.id,kind:'supports',origin:'manual',reason:'Explicit comparison'}];
 assert.deepEqual(cockpitRelationGraph(cards,cards,edges,saved,ready(cards),[]).map(link=>link.id),['alarm-object','other-alarm-drawing','authored']);
});
test('saved manual support and contradiction labels retain their exact meaning without source promotion',()=>{
 const a=card('a'),b=card('b'),saved=[{id:'manual',from:a.id,to:b.id,kind:'contradicts',origin:'manual',reason:'Saved counter-evidence'}];
 const graph=cockpitRelationGraph([a,b],[a,b],[],saved,{},[]);
 assert.equal(graph[0].label,'反证');assert.equal(graph[0].origin,'manual');assert.equal(graph[0].reason,'Saved counter-evidence');assert.equal(graph[0].via.length,0);
});
test('uniform world-space labels remain outside cards and do not overlap on the complete diagram',()=>{
 const cards=['alarm','drawing','model3d','document','photo','trend'].map((kind,i)=>({...card(kind,kind),x:i%3*432-980,y:Math.floor(i/3)*344-900}));
 const layout=cockpitAnalysisLayout({cards}),[alarm,...targets]=layout.cards,links=targets.map(target=>({id:target.id,route:cockpitRelationRoute(alarm,target)}));
 const sizes=Object.fromEntries(links.map(link=>[link.id,{width:105,height:22}])),positions=cockpitRelationLabels(links,layout.cards,sizes,layout.bounds),boxes=[];
 const overlap=(a,b)=>a.x<b.x+b.width&&a.x+a.width>b.x&&a.y<b.y+b.height&&a.y+a.height>b.y;
 for(const link of links){const point=positions[link.id],box={x:point.x-52.5,y:point.y-11,width:105,height:22};assert.ok(point.x<0&&point.y<0);assert.ok(!layout.cards.some(c=>overlap(box,c)),link.id);assert.ok(!boxes.some(other=>overlap(box,other)),link.id);boxes.push(box);}
});
test('fit all includes saved frames and moved cards past the original bounds on compact viewports',()=>{
 const cards=Array.from({length:50},(_,i)=>({...card(String(i),i?'drawing':'alarm'),x:i%7*340,y:Math.floor(i/7)*280}));
 const frames=[{id:'empty-frame',title:'Empty frame',x:-300,y:-2100,width:800,height:700}];
 const layout=cockpitAnalysisLayout({cards,frames},{0:{x:-420,y:2940}});
 for(const size of [{width:1464,height:718},{width:942,height:375.5}]){const view=cockpitCanvasFit(layout.bounds,size);for(const c of [...layout.cards,...frames]){assert.ok(view.x+c.x*view.zoom>=23);assert.ok(view.y+c.y*view.zoom>=23);assert.ok(view.x+(c.x+c.width)*view.zoom<=size.width-23);assert.ok(view.y+(c.y+c.height)*view.zoom<=size.height-23);}}
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

test('keyboard movement keeps an off-screen card visible without hidden scrolling or needless camera changes',()=>{
 const size={width:1464,height:712},value={...card('photo','photo'),x:1336,y:32,width:320,height:264},view={x:-324,y:-152,zoom:1};
 const revealed=cockpitCanvasReveal(view,value,size);assert.notEqual(revealed,view);assert.ok(revealed.x+value.x*revealed.zoom>=4);assert.ok(revealed.y+value.y*revealed.zoom>=4);assert.ok(revealed.x+(value.x+value.width)*revealed.zoom<=size.width-4);assert.ok(revealed.y+(value.y+value.height)*revealed.zoom<=size.height-4);
 assert.equal(cockpitCanvasReveal(revealed,value,size),revealed);assert.equal(cockpitCanvasReveal(revealed,{...value,x:value.x+8},size),revealed);
});

test('cockpit analysis assistant supports collapse, expand launcher, and floating drag with boundary protection',async()=>{
 const fs=await import('node:fs/promises');
 const css=await fs.readFile(new URL('../src/cockpitAnalysis.css',import.meta.url),'utf8');
 const tsx=await fs.readFile(new URL('../src/CockpitAnalysis.tsx',import.meta.url),'utf8');
 assert.ok(css.includes('.pa-workspace .pa-content[data-assistant-collapsed]'));
 assert.ok(css.includes('.pa-workspace .pa-content[data-assistant-floating]'));
 assert.ok(css.includes('.pa-assistant[data-floating]'));
 assert.ok(css.includes('.pa-assistant[data-dragging]'));
 assert.ok(css.includes('.pa-assistant-launcher'));
 assert.ok(css.includes('.pa-assistant-controls'));
 assert.ok(tsx.includes('startAssistantDrag'));
 assert.ok(tsx.includes('toggleAssistantCollapse'));
 assert.ok(tsx.includes('pa-assistant-launcher'));
 assert.ok(tsx.includes('data-assistant-collapsed'));
 assert.ok(tsx.includes('data-assistant-floating'));
});
