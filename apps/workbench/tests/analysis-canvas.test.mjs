import assert from 'node:assert/strict';
import test from 'node:test';
import {validateSnapshot,moveCard,removeCard,addManualRelation,arrangeCards,fitViewport,zoomAt,visibleSource} from '../src/analysisCanvas.ts';
const scope={ontobaseConnectionId:'fixture-connection',projectCode:'Demo-PDS'};
const card=(id,x=0,y=0,pinned=false)=>({id,kind:'object',title:'合成对象',x,y,width:300,height:200,pinned,source:{system:'ontobase',...scope,id:'fixture-'+id,revision:'fixture-r1'}});
const initial=()=>({schemaVersion:1,...scope,title:'温度报警排查',status:'analyzing',context:{objectIds:['fixture-a'],eventId:'fixture-event',workOrderId:'fixture-order',timeFrom:'2026-10-25T00:00:00Z',timeTo:'2026-10-25T02:00:00Z',timezone:'Asia/Shanghai'},cards:[card('a'),card('b',350)],relations:[],viewport:{x:24,y:24,zoom:1}});
test('canvas references are fixed to the current project and a declared revision',()=>{
  const value=initial();assert.deepEqual(validateSnapshot(value,scope),[]);
  assert.ok(validateSnapshot(value,{...scope,projectCode:'another'}).length);
  assert.ok(validateSnapshot(value,{...scope,ontobaseConnectionId:'other-connection'}).length);
  value.cards[0].source.projectCode='another';assert.ok(validateSnapshot(value,scope).length);
  value.cards[0].source.projectCode='Demo-PDS';delete value.cards[0].source.revision;
  assert.ok(validateSnapshot(value,scope).length);
});
test('source content, unsupported fields and invalid layout cannot enter a saved snapshot',()=>{
  for(const extra of [{body:'source document text'},{url:'https://arbitrary.invalid'},{x:NaN},{height:100000},{note:'source overwrite'}]){
    const value=initial();Object.assign(value.cards[0],extra);assert.ok(validateSnapshot(value,scope).length);
  }
  const value=initial();value.cards[1].id='a';assert.ok(validateSnapshot(value,scope).length);
});
test('manual links require real endpoints and cannot claim engineering facts',()=>{
  const value=initial(),relation={id:'link',from:'a',to:'b',kind:'hypothesis',origin:'manual',reason:'待核对接线'};
  const added=addManualRelation(value,relation);assert.equal(added.relations.length,1);assert.equal(value.relations.length,0);
  for(const change of [{kind:'engineering'},{origin:'source'},{to:'missing'},{to:'a'},{reason:' '}] )assert.throws(()=>addManualRelation(value,{...relation,...change}));
  assert.throws(()=>addManualRelation(added,{...relation,id:'duplicate'}));
});
test('moving pinned cards is a no-op; card removal also removes dangling relations',()=>{
  const value=initial();value.cards[0].pinned=true;
  assert.equal(moveCard(value,'a',200,200),value);assert.equal(moveCard(value,'b',Infinity,200),value);
  const next=moveCard(value,'b',700,800);assert.equal(next.cards[1].x,700);assert.equal(value.cards[1].x,350);
  value.relations.push({id:'link',from:'a',to:'b',kind:'engineering',origin:'source',reason:'来源关系'});
  assert.equal(removeCard(value,'b').relations.length,0);
});
test('arrangement preserves pinned positions and avoids their occupied area',()=>{
  const value=initial();value.cards=[card('a',32,40,true),card('b'),card('c'),card('d')];
  const result=arrangeCards(value);assert.deepEqual(result.cards[0],value.cards[0]);
  for(let i=0;i<result.cards.length;i++)for(let j=i+1;j<result.cards.length;j++){
    const a=result.cards[i],b=result.cards[j];assert.ok(a.x+a.width<=b.x||b.x+b.width<=a.x||a.y+a.height<=b.y||b.y+b.height<=a.y);
  }
  assert.deepEqual(validateSnapshot(result,scope),[]);
});
test('zoom stays anchored and fit keeps bounded cards visible',()=>{
  const view={x:80,y:-20,zoom:.75};const next=zoomAt(view,1.25,450,300);
  assert.ok(Math.abs((450-next.x)/next.zoom-(450-view.x)/view.zoom)<1e-10);
  assert.ok(Math.abs((300-next.y)/next.zoom-(300-view.y)/view.zoom)<1e-10);
  assert.equal(zoomAt(view,100,0,0).zoom,1.5);assert.equal(zoomAt(view,-1,0,0).zoom,.25);
  const cards=initial().cards,fit=fitViewport(cards,1100,600);
  for(const c of cards){assert.ok(c.x*fit.zoom+fit.x>=0);assert.ok((c.x+c.width)*fit.zoom+fit.x<=1100);}
});
test('access withdrawal redacts the source title and identity from presentation',()=>{
  assert.deepEqual(visibleSource(card('a'),'restricted'),{title:'资料访问已撤销'});
  assert.equal(visibleSource(card('a'),'ready').source.id,'fixture-a');
});
test('context has a bounded selection and an explicit increasing UTC time window',()=>{
  for(const update of [{timeTo:'2026-10-24T02:00:00Z'},{timeFrom:'2026-10-25'},{timeFrom:'invalid'},{timeFrom:'2026-02-31T00:00:00Z'},{objectIds:Array(21).fill('same')},{timezone:'unsupported'}]){
    const value=initial();Object.assign(value.context,update);assert.ok(validateSnapshot(value,scope).length);
  }
});
test('pixel image views and historical fit-relative views have explicit, separate validation',()=>{
  for(const kind of ['photo','drawing','document']){
    const value=initial();value.schemaVersion=2;value.cards=[{...card('image'),kind}];
    for(const view of [{zoom:.0001,zoomBasis:'pixels',centerX:0,centerY:1},{zoom:16,zoomBasis:'pixels',centerX:1,centerY:0},{zoom:.1,centerX:.5,centerY:.5},{zoom:16,centerX:.2,centerY:.8}]){
      value.cards[0].view=view;assert.deepEqual(validateSnapshot(value,scope),[]);
    }
    for(const view of [{zoom:.0001,centerX:.5,centerY:.5},{zoom:1,zoomBasis:'fit',centerX:.5,centerY:.5},{zoom:17,zoomBasis:'pixels',centerX:.5,centerY:.5},{zoom:.00001,zoomBasis:'pixels',centerX:.5,centerY:.5},{zoom:NaN,zoomBasis:'pixels',centerX:.5,centerY:.5},{zoom:1,zoomBasis:'pixels',centerX:1.1,centerY:.5},{zoom:1,zoomBasis:'pixels',centerX:.5,centerY:.5,url:'injected'}]){
      value.cards[0].view=view;assert.ok(validateSnapshot(value,scope).length);
    }
  }
});
