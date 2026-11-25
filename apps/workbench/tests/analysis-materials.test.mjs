import test from 'node:test';
import assert from 'node:assert/strict';
import {CARD_KINDS,RESIZE_HANDLES,resizeCard,setCardFrame,validateSnapshot} from '../src/analysisCanvas.ts';
import {applyCanvasAction,conversationContext} from '../src/analysisActions.ts';
import {readNote,writeNote} from '../src/analysisNotes.ts';
import {AnalysisSources,inlinePreviewActive,setCardPreviewCollapsed} from '../src/analysisSources.ts';
const scope={projectCode:'P',ontobaseConnectionId:'source'};
const fixture=()=>({schemaVersion:2,...scope,title:'Test',status:'analyzing',context:{objectIds:[],timeFrom:'2026-10-25T00:00:00Z',timeTo:'2026-10-25T00:03:00Z',timezone:'UTC'},viewport:{x:0,y:0,zoom:1},cards:[{id:'one',kind:'analysis',title:'检查',note:'',x:100,y:100,width:340,height:260,pinned:false}],relations:[]});
test('media and model cards preview by default and collapse independently',()=>{
 const cards=['drawing','photo','document','model3d'].map(kind=>({id:kind,kind}));
 const initial=new Set();
 assert.ok(cards.every(card=>inlinePreviewActive(card,initial)));
 assert.equal(inlinePreviewActive({id:'work',kind:'work_order'},initial),false);
 const collapsed=setCardPreviewCollapsed(initial,'model3d',true);
 assert.equal(initial.size,0);
 assert.deepEqual(cards.map(card=>inlinePreviewActive(card,collapsed)),[true,true,true,false]);
 assert.equal(setCardPreviewCollapsed(collapsed,'model3d',true),collapsed);
 assert.equal(setCardPreviewCollapsed(collapsed,'absent',false),collapsed);
 assert.ok(cards.every(card=>inlinePreviewActive(card,setCardPreviewCollapsed(collapsed,'model3d',false))));
});
test('an existing group can take an ungrouped card without changing its position or references',()=>{
 const value=fixture(),[card]=value.cards;
 const source={...scope,system:'ontobase',id:'photo-source',revision:'fixed'};
 const target={...card,id:'photo',kind:'photo',title:'柜内照片',x:1200,source,note:undefined};
 const current={id:'current',title:'本次调查',x:80,y:62,width:380,height:318};
 const history={id:'history',title:'历史参考',x:3000,y:900,width:310,height:240};
 value.frames=[current,history];
 value.cards=[{...card,frameId:'current'},target];
 const assigned=setCardFrame(value,target.id,'current');
 assert.deepEqual(assigned.cards[1],{...target,frameId:'current'});
 assert.equal(assigned.cards[1].source,source);
 assert.equal(assigned.frames[0].width,1480);
 assert.equal(assigned.frames[1],history);
 assert.equal(assigned.relations,value.relations);
 assert.equal(setCardFrame(assigned,target.id,'current'),assigned);
 assert.equal(setCardFrame(assigned,target.id,'missing'),assigned);
 assert.equal(setCardFrame(assigned,'missing','current'),assigned);
 assert.deepEqual(setCardFrame(assigned,target.id),value);
});
test('all nine card kinds resize from every edge and corner without changing sources',()=>{
 for(const kind of CARD_KINDS)for(const edge of RESIZE_HANDLES){const value=fixture();Object.assign(value.cards[0],{kind,...(kind==='analysis'?{}:{source:{...scope,system:'ontobase',id:'fixed',revision:'fixed'}})});
  const resized=resizeCard(value,'one',edge,30,20);assert.notDeepEqual(resized.cards[0],value.cards[0]);assert.deepEqual(resized.cards[0].source,value.cards[0].source);
  if(edge==='n'||edge==='s')assert.equal(resized.cards[0].width,value.cards[0].width);
  if(edge==='e'||edge==='w')assert.equal(resized.cards[0].height,value.cards[0].height);
 }
});
test('resize honors ratio, opposite corner, minimum, pin and zoom-independent world deltas',()=>{
 const value=fixture(),card=value.cards[0],next=resizeCard(value,'one','nw',-80,-30,true).cards[0];
 assert.ok(Math.abs(next.width/next.height-card.width/card.height)<1e-10);assert.equal(next.x+next.width,card.x+card.width);assert.equal(next.y+next.height,card.y+card.height);
 for(const zoom of [.25,1,1.5]){value.viewport.zoom=zoom;assert.equal(resizeCard(value,'one','e',100*zoom/zoom,0).cards[0].width,440);}
 assert.equal(resizeCard(value,'one','se',-5000,-5000).cards[0].width,240);
 assert.equal(resizeCard(value,'one','se',-5000,-5000).cards[0].height,176);
 value.cards[0].pinned=true;assert.equal(resizeCard(value,'one','se',20,20),value);
});
test('actions are scoped, bounded, undoable values and never save or confirm',()=>{
 const value=fixture(),result=applyCanvasAction(value,{kind:'append-note',cardId:'one',text:'观察：偏高'},scope);
 assert.equal(value.cards[0].note,'');assert.equal(result.cards[0].note,'观察：偏高');
 assert.throws(()=>applyCanvasAction(value,{kind:'append-note',cardId:'one',text:'x'.repeat(4001)},scope));
 assert.throws(()=>applyCanvasAction(value,{kind:'arrange'},{...scope,projectCode:'OTHER'}));
 assert.throws(()=>applyCanvasAction(value,{kind:'confirm-conclusion'},scope));
 value.cards[0].historical=true;assert.throws(()=>applyCanvasAction(value,{kind:'append-note',cardId:'one',text:'changed'},scope));
});
test('future conversation receives fixed refs and current selection without replaying history',()=>{
 const value=fixture(),ctx=conversationContext(value,'session',3,['one','missing']);
 assert.deepEqual(ctx.selectedCardIds,['one']);assert.equal(ctx.analysisRevision,3);assert.equal(ctx.timezone,'UTC');assert.equal(ctx.sources.length,0);assert.equal('messages' in ctx,false);
 assert.deepEqual(validateSnapshot(value,scope),[]);
});

test('saved image and model views accept only bounded display coordinates',()=>{
 const value=fixture(),card=value.cards[0];delete card.note;card.kind='photo';card.source={...scope,system:'ontobase',id:'fixed',revision:'v1'};
 card.view={zoom:3,centerX:.6,centerY:.2};assert.deepEqual(validateSnapshot(value,scope),[]);
 card.view.centerX=2;assert.ok(validateSnapshot(value,scope).length);
 card.kind='model3d';card.source.system='ontovis';card.view={eye:[1,2,3],target:[0,1,0],componentId:'cabinet'};assert.deepEqual(validateSnapshot(value,scope),[]);
 card.view.url='https://example.invalid';assert.ok(validateSnapshot(value,scope).length);
});

test('structured notes retain legacy text and independent multiline findings',()=>{
 const legacy=readNote('旧观察\n保留第二行');assert.equal(legacy['观察'],'旧观察\n保留第二行');
 legacy['原因假设']='测量偏差';legacy['检查步骤']='检查传感器\n对照独立测点';legacy['检查结果']='仍待现场检查';legacy['反证与缺口']='跨页源点未闭合';
 assert.deepEqual(readNote(writeNote(legacy)),legacy);
});

test('two photo regions share bytes while every metadata open remains authorized',async()=>{
 const calls=[];const api={request:async(path,body)=>{calls.push({path,body});return path.endsWith('/content')?new Blob(['image']):{items:body.evidenceRefIds.map(id=>({evidenceRefId:id,availability:'available'}))};}};
 const sources=new AnalysisSources(api,'session'),one={id:'region-1',revision:'r1'},two={id:'region-2',revision:'r2'},source={contentVersionId:'fixed',selector:{displayRevision:'display'}};
 const [a,b]=await Promise.all([sources.file(one,source),sources.file(two,source)]);assert.equal(a,b);
 await sources.detail(one);await sources.detail(two);await sources.file(two,source);
 assert.equal(calls.filter(call=>call.path.endsWith('/content')).length,1);assert.equal(calls.filter(call=>call.path.endsWith('/batch')).length,2);
 sources.dispose();await assert.rejects(sources.file(one,source),{name:'AbortError'});
});

test('canceling one shared image consumer leaves the other alive; closing cancels queued work',async()=>{
 let resolve,signal,calls=0;const api={request:async(_path,_body,abort)=>{calls++;signal=abort;return await new Promise(done=>{resolve=done;});}};
 const sources=new AnalysisSources(api,'session'),ref={id:'image',revision:'fixed'},abort=new AbortController();
 const canceled=sources.file(ref,undefined,abort.signal),survivor=sources.file(ref);await Promise.resolve();abort.abort();
 await assert.rejects(canceled,{name:'AbortError'});assert.equal(signal.aborted,false);resolve(new Blob(['image']));await survivor;assert.equal(calls,1);
 sources.dispose();assert.equal(signal.aborted,false);
 const pendingSources=new AnalysisSources(api,'other');const pending=pendingSources.file(ref);await Promise.resolve();pendingSources.dispose();assert.equal(signal.aborted,true);
 resolve(new Blob(['late']));await assert.rejects(pending,{name:'AbortError'});
});

test('opening a queued original promotes its shared transfer ahead of other thumbnails',async()=>{
 const requests=[];
 const sources=new AnalysisSources({request:(_path,body)=>new Promise(resolve=>requests.push({id:body.evidenceRefId,resolve}))},'session');
 const load=id=>sources.file({id,revision:'fixed'});
 const release=i=>requests[i].resolve(new Blob([requests[i].id]));
 const left=load('left'),right=load('right');
 const thumbnail=load('thumbnail'),automatic=load('original');
 const opened=sources.file({id:'original',revision:'fixed'},undefined,undefined,'original',undefined,'foreground');
 const pending=Promise.allSettled([left,right,thumbnail,automatic,opened]);
 try{
  await Promise.resolve();
  assert.deepEqual(requests.map(row=>row.id),['left','right']);
  release(0);await left;await Promise.resolve();
  assert.deepEqual(requests.map(row=>row.id),['left','right','original']);
  release(1);await right;await Promise.resolve();
  assert.deepEqual(requests.map(row=>row.id),['left','right','original','thumbnail']);
  release(2);release(3);
  assert.equal(await opened,await automatic);
  await thumbnail;
 }finally{sources.dispose();requests.forEach((_,i)=>release(i));void pending;}
});

test('reopening immediately after cancellation starts a new shared original transfer',async()=>{
 const requests=[];
 const sources=new AnalysisSources({request:(_path,_body,signal)=>new Promise(resolve=>requests.push({signal,resolve}))},'session');
 const ref={id:'original',revision:'fixed'},controller=new AbortController();
 const canceled=sources.file(ref,undefined,controller.signal);
 const canceledResult=assert.rejects(canceled,{name:'AbortError'});
 await Promise.resolve();
 controller.abort();
 const reopened=sources.file(ref);
 const outcome=reopened.catch(error=>error);
 try{
  await canceledResult;
  assert.equal(requests.length,2);
  assert.equal(requests[0].signal.aborted,true);
  assert.equal(requests[1].signal.aborted,false);
  requests[0].resolve(new Blob(['stale']));await Promise.resolve();await Promise.resolve();
  const shared=sources.file(ref);
  requests[1].resolve(new Blob(['current']));
  assert.equal(await shared,await reopened);
  assert.equal(requests.length,2);
 }finally{sources.dispose();requests.forEach(row=>row.resolve(new Blob(['closed'])));void outcome;}
});

test('decoded image retention is bounded to two sources and released on close',async()=>{
 const original=globalThis.Image,images=[];
 globalThis.Image=class{constructor(){this.src='';images.push(this);}async decode(){}};
 const sources=new AnalysisSources({request:async()=>new Blob(['image'],{type:'image/jpeg'})},'session');
 try{for(let i=0;i<3;i++)await sources.file({id:'image-'+i,revision:'fixed'});assert.equal(images.filter(i=>i.src).length,2);assert.equal(images[0].src,'');
  sources.dispose();assert.equal(images.filter(i=>i.src).length,0);
 }finally{globalThis.Image=original;sources.dispose();}
});

test('screen previews, originals and document pages never share the wrong byte cache',async()=>{
 const calls=[];const sources=new AnalysisSources({request:async(path,body)=>{calls.push({path,body});return new Blob([JSON.stringify(body)]);}},'session');
 const ref={id:'photo',revision:'fixed'},source={contentVersionId:'version',selector:{displayRevision:'display'}};
 const a=await sources.file(ref,source,undefined,'preview'),b=await sources.file(ref,source,undefined,'original',undefined,'foreground',{});
 assert.notEqual(a,b);assert.equal(await sources.file(ref,source,undefined,'preview'),a);
 const first=await sources.file({id:'doc',revision:'fixed'},undefined,undefined,'original',48),second=await sources.file({id:'doc',revision:'fixed'},undefined,undefined,'original',49);
 assert.notEqual(first,second);assert.equal(calls.length,4);assert.ok(calls[0].path.endsWith('/preview-content'));assert.ok(calls[1].path.endsWith('/content'));
 assert.equal(calls[0].body.representation,undefined);assert.equal(calls[1].body.representation,'full_resolution');
 assert.deepEqual(calls.slice(2).map(c=>c.body.options.pageNumber),[48,49]);sources.dispose();
});

test('a canceled original leaves the preview available and the retry reads the original again',async()=>{
 const originals=[];
 let previews=0;
 const sources=new AnalysisSources({request:(path,_body,signal)=>{
  if(path.endsWith('/preview-content')){previews++;return Promise.resolve(new Blob(['preview']));}
  return new Promise(resolve=>originals.push({resolve,signal}));
 }},'session');
 const ref={id:'photo',revision:'fixed'};
 const controller=new AbortController();
 try{
  const preview=await sources.file(ref,undefined,undefined,'preview');
  const pending=sources.file(ref,undefined,controller.signal,'original',undefined,'foreground');
  const canceled=assert.rejects(pending,{name:'AbortError'});
  await Promise.resolve();
  controller.abort();
  await canceled;
  assert.equal(originals[0].signal.aborted,true);
  assert.equal(await sources.file(ref,undefined,undefined,'preview'),preview);
  originals[0].resolve(new Blob(['late original']));
  const retry=sources.file(ref,undefined,undefined,'original',undefined,'foreground');
  await Promise.resolve();
  assert.equal(originals.length,2);
  originals[1].resolve(new Blob(['current original']));
  const original=await retry;
  assert.notEqual(original,preview);
  assert.equal(await sources.file(ref),original);
  assert.equal(previews,1);
 }finally{
  originals.forEach(row=>row.resolve(new Blob(['closed'])));
  sources.dispose();
 }
});

test('relationship lookup uses owned fixed handles and deduplicates copied card views',async()=>{
 const calls=[];const sources=new AnalysisSources({request:async(path,body)=>{calls.push({path,body});return {items:[],gaps:[]};}},'session');
 await sources.relationships([{id:'one',revision:'r1'},{id:'one',revision:'r1'},{id:'two',revision:'r2'}]);
 assert.deepEqual(calls[0].body,{analysisSessionId:'session',evidenceRefIds:['one','two']});sources.dispose();
});
