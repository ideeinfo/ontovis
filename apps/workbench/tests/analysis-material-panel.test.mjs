import test from 'node:test';
import assert from 'node:assert/strict';
import {MATERIAL_CATEGORIES,materialCategories,materialPosition,relatedMaterialSection,withPrimaryAlarm} from '../src/analysisMaterials.ts';
import {validateSnapshot} from '../src/analysisCanvas.ts';

test('all nine material types are reachable and type search stays local',()=>{
 assert.equal(new Set(MATERIAL_CATEGORIES.map(row=>row.kind)).size,9);
 assert.deepEqual(materialCategories('当前设备适用资料').map(row=>row.id),['device_materials']);
 assert.deepEqual(materialCategories('本项目文档库').map(row=>row.id),['project_documents']);
 assert.deepEqual(materialCategories('报警事件').map(row=>row.id),['alarms']);
 assert.deepEqual(materialCategories('fault alarms').map(row=>row.id),['alarms']);
 assert.deepEqual(materialCategories('不存在'),[]);
});
test('installed equipment opens source-resolved materials while shared definitions retain old located evidence',()=>{
 assert.equal(relatedMaterialSection('installation'),'device_materials');
 for(const scope of ['definition','unclassified',undefined])assert.equal(relatedMaterialSection(scope),'materials');
});
test('drops resolve to canvas coordinates at different pan and zoom without leaving layout limits',()=>{
 const point={x:725,y:420};for(const zoom of [.25,.43,1,1.5]){
  const view={x:-120,y:50,zoom},location=materialPosition(view,point);
  assert.ok(Math.abs(location.x*zoom+view.x-point.x)<=zoom/2);
  assert.ok(Math.abs(location.y*zoom+view.y-point.y)<=zoom/2);
 }
 assert.deepEqual(materialPosition({x:-50000,y:50000,zoom:.25},{x:1000,y:0}),{x:20000,y:-20000});
});
test('the first alarm establishes recommendations without replacing a later analysis context',()=>{
 const snapshot={schemaVersion:2,projectCode:'P',ontobaseConnectionId:'source',title:'Analysis',status:'analyzing',context:{objectIds:[],timeFrom:'2026-10-25T00:00:00Z',timeTo:'2026-10-25T01:00:00Z',timezone:'UTC'},cards:[],relations:[],viewport:{x:0,y:0,zoom:1}};
 const dataset={datasetId:'simulation-1',datasetRevision:'a'.repeat(64),branch:'sensor_bias_high',faultCode:'13001',sourceConnectionId:'simulation',timeFrom:'2026-10-25T00:00:00Z',timeTo:'2026-10-25T00:03:00Z'};
 const item={kind:'alarm',selector:{eventId:'simulation-1-event-1'},preview:{dataset}};
 const next=withPrimaryAlarm(snapshot,item);assert.notEqual(next,snapshot);assert.equal(snapshot.context.datasetId,undefined);
 assert.equal(next.context.datasetId,dataset.datasetId);assert.equal(next.context.eventId,item.selector.eventId);assert.equal(next.context.timeTo,dataset.timeTo);
 assert.deepEqual(validateSnapshot(next,{projectCode:'P',ontobaseConnectionId:'source'}),[]);
 assert.equal(withPrimaryAlarm(next,{...item,preview:{dataset:{...dataset,datasetId:'different'}}}),next);
 assert.equal(withPrimaryAlarm(snapshot,{kind:'object',selector:{}}),snapshot);
 assert.equal(withPrimaryAlarm(snapshot,{...item,preview:{dataset:{...dataset,branch:undefined}}}),snapshot);
});
