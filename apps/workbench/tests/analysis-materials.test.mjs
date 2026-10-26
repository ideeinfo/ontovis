import test from 'node:test';
import assert from 'node:assert/strict';
import {CARD_KINDS,RESIZE_HANDLES,resizeCard,validateSnapshot} from '../src/analysisCanvas.ts';
import {applyCanvasAction,conversationContext} from '../src/analysisActions.ts';
import {readNote,writeNote} from '../src/analysisNotes.ts';
import {AnalysisSources} from '../src/analysisSources.ts';
const scope={projectCode:'P',ontobaseConnectionId:'source'};
const fixture=()=>({schemaVersion:2,...scope,title:'Test',status:'analyzing',context:{objectIds:[],timeFrom:'2026-10-25T00:00:00Z',timeTo:'2026-10-25T00:03:00Z',timezone:'UTC'},viewport:{x:0,y:0,zoom:1},cards:[{id:'one',kind:'analysis',title:'检查',note:'',x:100,y:100,width:340,height:260,pinned:false}],relations:[]});
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

test('decoded image retention is bounded to two sources and released on close',async()=>{
 const original=globalThis.Image,images=[];
 globalThis.Image=class{constructor(){this.src='';images.push(this);}async decode(){}};
 const sources=new AnalysisSources({request:async()=>new Blob(['image'],{type:'image/jpeg'})},'session');
 try{for(let i=0;i<3;i++)await sources.file({id:'image-'+i,revision:'fixed'});assert.equal(images.filter(i=>i.src).length,2);assert.equal(images[0].src,'');
  sources.dispose();assert.equal(images.filter(i=>i.src).length,0);
 }finally{globalThis.Image=original;sources.dispose();}
});
