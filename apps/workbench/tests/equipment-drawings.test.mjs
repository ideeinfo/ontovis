import test from 'node:test';
import assert from 'node:assert/strict';
import {appendDrawingPage,equipmentDrawingSelection,equipmentDrawings,equipmentDrawingContent,filterEquipmentDrawings} from '../src/equipmentDrawingState.ts';
import {EquipmentApi} from '../src/equipmentApi.ts';

const object={entityUid:'selected-cabinet',entityRevision:'selected:r2',installationContextId:'installed-1',displayName:'Cabinet'},context={installationContextId:'installed-1',hierarchyRevision:'installed-1:r3'};
const drawing={drawingUid:'protected-drawing',sourceRevision:'source:r1',contentSha256:'a'.repeat(64),availability:'available'};
test('drawing list keeps the selected object revision and installation, never its geometry host or parent',async()=>{
 const calls=[],api={request:async(...args)=>{calls.push(args);return {items:[drawing],complete:true};}},signal=new AbortController().signal;
 const selection=equipmentDrawingSelection(object,context);
 assert.deepEqual(selection,{entityUid:'selected-cabinet',expectedEntityRevision:'selected:r2',installationContextId:'installed-1',expectedHierarchyRevision:'installed-1:r3'});
 assert.equal((await equipmentDrawings(api,selection,{includeDescendants:true,limit:3,cursor:null},signal)).items[0],drawing);
 assert.deepEqual(calls[0],['/api/workbench/objects/evidence/related',{...selection,includeDescendants:true,limit:3},signal]);
});
test('project definitions do not borrow an installation context and mismatched installations are rejected',()=>{
 assert.equal(equipmentDrawingSelection({...object,installationContextId:null},context).expectedHierarchyRevision,null);
 for(const invalid of [null,{...context,installationContextId:'other'}])assert.throws(()=>equipmentDrawingSelection(object,invalid),error=>error.code==='ENGINEERING_CHANGED');
});
test('preview requests preserve the fixed drawing ref, source revision, digest and abort signal',async()=>{
 const calls=[],blob=new Blob(['synthetic-png']),api={request:async(...args)=>{calls.push(args);return blob;}},signal=new AbortController().signal,selection=equipmentDrawingSelection(object,context);
 assert.equal(await equipmentDrawingContent(api,selection,drawing,true,signal),blob);
 assert.deepEqual(calls,[['/api/workbench/objects/evidence/related/content',{...selection,includeDescendants:true,drawingUid:'protected-drawing',expectedSourceRevision:'source:r1',expectedContentSha256:'a'.repeat(64)},signal,true]]);
});
test('unavailable drawings never send a preview request or silently substitute another source',()=>{
 const api={request:()=>assert.fail('No network request expected')},selection=equipmentDrawingSelection(object,context),signal=new AbortController().signal;
 for(const invalid of [{...drawing,availability:'missing'},{...drawing,contentSha256:null}])assert.throws(()=>equipmentDrawingContent(api,selection,invalid,true,signal),error=>error.code==='SOURCE_CHANGED');
});
test('model parameter read explicitly requests current device scope and retains the legacy attribute form',async()=>{
 const calls=[],api=new EquipmentApi({request:async(...args)=>{calls.push(args);return {};}}),signal=new AbortController().signal;
 await api.deviceParameters({entityUid:'selected-cabinet',expectedEntityRevision:'selected:r2'},signal);
 await api.attributeForm('selected-cabinet',signal);
 assert.deepEqual(calls,[['/api/workbench/equipment/attribute-form',{entityUid:'selected-cabinet',expectedEntityRevision:'selected:r2',includeModel:true},signal],['/api/workbench/equipment/attribute-form',{entityUid:'selected-cabinet'},signal]]);
});

test('drawing scope and server cursor stay explicit across pages and previews',async()=>{
 const calls=[],api={request:async(...args)=>calls.push(args)},signal=new AbortController().signal,selection=equipmentDrawingSelection(object,context);
 await equipmentDrawings(api,selection,{includeDescendants:true,limit:2,cursor:'source-cursor'},signal);
 await equipmentDrawings(api,selection,{includeDescendants:false,limit:2,cursor:null},signal);
 await equipmentDrawingContent(api,selection,drawing,false,signal);
 assert.deepEqual(calls[0][1],{...selection,includeDescendants:true,limit:2,cursor:'source-cursor'});
 assert.deepEqual(calls[1][1],{...selection,includeDescendants:false,limit:2});
 assert.equal(calls[2][1].includeDescendants,false);assert.equal(calls[2][1].entityUid,object.entityUid);
});

test('drawing search matches title, drawing number, exact page and associated object across loaded pages',()=>{
 const initial={...drawing,title:'塔基690VAC供电',drawingNumber:'M0600004111',pageNumber:189,matchedObjects:[]};
 const later={...drawing,drawingUid:'later',title:'机舱动力柜供电',drawingNumber:'M0600004111',pageNumber:89,
  matchedObjects:[{displayName:'机舱动力柜',viaName:'CN1 柜内元件'}]};
 const first={items:[initial],total:2,nextCursor:'page2',snapshotRevision:'snapshot',scopeComplete:true,includeDescendants:true};
 const second={...first,items:[later],nextCursor:null};
 assert.deepEqual(filterEquipmentDrawings(first.items,'ＣＮ１ 供电'),[]);
 const all=appendDrawingPage(first,second,'page2');
 assert.deepEqual(filterEquipmentDrawings(all.items,'ＣＮ１ 供电'),[later]);
 assert.deepEqual(filterEquipmentDrawings(all.items,'第８９页'),[later]);
 assert.deepEqual(filterEquipmentDrawings(all.items,'89页'),[later]);
 assert.deepEqual(filterEquipmentDrawings(all.items,'m0600004111'),[initial,later]);
 assert.deepEqual(filterEquipmentDrawings(all.items,'  '),[initial,later]);
});

test('drawing pages cannot combine changed selection snapshots, duplicate rows or missing results',()=>{
 const page={items:[drawing],total:2,nextCursor:'page2',snapshotRevision:'snapshot',scopeComplete:true,includeDescendants:true};
 const second={...page,items:[{...drawing,drawingUid:'later'}],nextCursor:null};
 assert.deepEqual(appendDrawingPage(null,page,null),page);
 for(const invalid of [{...second,snapshotRevision:'changed'},{...second,total:3},{...second,includeDescendants:false},
  {...second,items:[drawing]},{...second,nextCursor:'page2'},{...second,items:[]}]){
  assert.throws(()=>appendDrawingPage(page,invalid,'page2'),error=>error.code==='SNAPSHOT_EXPIRED');
 }
});
