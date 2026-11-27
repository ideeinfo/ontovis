import test from 'node:test';
import assert from 'node:assert/strict';
import {MATERIAL_CATEGORIES,addedMaterialCard,groupMaterialRecommendations,materialCategories,materialPosition,relatedMaterialSection,withPrimaryAlarm,mergeRecommendations,recommendationRelevanceLabel} from '../src/analysisMaterials.ts';
import {validateSnapshot} from '../src/analysisCanvas.ts';

test('all nine material types are reachable and type search stays local',()=>{
 assert.equal(new Set(MATERIAL_CATEGORIES.map(row=>row.kind)).size,9);
 assert.deepEqual(materialCategories('本项目文档库').map(row=>row.id),['project_documents']);
 assert.deepEqual(materialCategories('报警事件').map(row=>row.id),['alarms']);
 assert.deepEqual(materialCategories('fault alarms').map(row=>row.id),['alarms']);
 assert.deepEqual(materialCategories('不存在'),[]);
});
test('fault alarms come first and model applicability is included in related materials',()=>{
 assert.equal(materialCategories('')[0].id,'alarms');
 assert.equal(MATERIAL_CATEGORIES.some(row=>row.id==='device_materials'),false);
 assert.deepEqual(materialCategories('型号适用资料').map(row=>row.id),['materials']);
 for(const scope of ['installation','definition','unclassified',undefined])assert.equal(relatedMaterialSection(scope),'materials');
});
test('alarm recommendations distinguish the target from suggested checks',()=>{
 const target={relevance:'simulation_mapping'},check={relevance:'simulation_rule'};
 assert.equal(recommendationRelevanceLabel(target,false),'报警对象');
 assert.equal(recommendationRelevanceLabel(target,true),'Alarm target');
 assert.equal(recommendationRelevanceLabel(check,false),'建议检查');
 assert.equal(recommendationRelevanceLabel(check,true),'Suggested check');
});
test('related pages sort by evidence strength and preserve the original located fixed source',()=>{
 const direct={key:'region',assetKey:'photo:one:v1',kind:'photo',title:'Located',selector:{evidenceRef:'original'},relevance:'object_association',relevancePriority:10,availability:'available'};
 const whole={...direct,key:'whole',title:'Whole',selector:{documentId:'one'},relevance:'shared_photos',relevancePriority:30};
 const drawing={key:'drawing',kind:'drawing',title:'Drawing',selector:{},relevancePriority:10};
 const model={key:'model',kind:'document',title:'Applicable',selector:{},relevancePriority:40};
 const values=mergeRecommendations([direct,model],[whole,drawing]);
 assert.deepEqual(values,[direct,drawing,model]);assert.equal(values[0],direct);
 assert.equal(recommendationRelevanceLabel(direct,false),'本对象关联');assert.equal(recommendationRelevanceLabel(whole,true),'Shared photos');
});
test('fixed file deduplication prefers readable sources and never merges different versions by name',()=>{
 const a={key:'old',assetKey:'photo:one:v1',kind:'photo',title:'Same name',selector:{},relevancePriority:10,availability:'unavailable'};
 const b={...a,key:'readable',availability:'available',relevancePriority:30},c={...a,key:'new',assetKey:'photo:one:v2',availability:'available'};
 assert.deepEqual(mergeRecommendations([a],[b,c]),[c,b]);
 assert.deepEqual(mergeRecommendations([a],[a]),[a]);assert.equal(recommendationRelevanceLabel({matchType:'name_candidate'},false),'名称候选');
});
test('an added material needs a current card with the matching fixed reference',()=>{
 const historical={kind:'object',historical:true,source:{revision:'old'}};
 const object={kind:'object',source:{revision:'current'}};
 const model={kind:'model3d',source:{revision:'model-version'}};
 const cards=[historical,object,model];
 assert.equal(addedMaterialCard(cards,'object',['current']),object);
 assert.equal(addedMaterialCard(cards,'object',['old']),undefined);
 assert.equal(addedMaterialCard(cards,'object',['another version']),undefined);
 assert.equal(addedMaterialCard([historical,model],'object',['current']),undefined);
 assert.equal(addedMaterialCard(cards,'model',['model-version']),model);
 assert.equal(addedMaterialCard(cards,'document',['model-version']),undefined);
});
test('merging paged drawing recommendations keeps registered references for both representations',()=>{
 const direct={key:'location',assetKey:'drawing:89:digest',kind:'drawing',relevancePriority:10,registeredSourceRevisions:['located']};
 const whole={...direct,key:'page',relevancePriority:30,registeredSourceRevisions:['whole-page']};
 assert.deepEqual(mergeRecommendations([direct],[whole]),[{...direct,registeredSourceRevisions:['located','whole-page']}]);
});
test('canvas recommendations display each object once and retain its other card associations',()=>{
 const alarm={key:'one',kind:'object',relatedSourceRefs:['alarm']};
 const drawing={key:'two',kind:'object',relatedSourceRefs:['drawing']};
 const merged=mergeRecommendations([alarm],[{...alarm,relatedSourceRefs:['drawing']},drawing]);
 const titles=new Map([['alarm','报警'],['drawing','图纸']]);
 assert.deepEqual(groupMaterialRecommendations(merged,titles),{
   groups:[['alarm',[{...alarm,relatedSourceRefs:['alarm','drawing']}]],['drawing',[drawing]]],ungrouped:[]
 });
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
