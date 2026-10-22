import assert from 'node:assert/strict';
import test from 'node:test';
import {bindComponentKeys,changeRootBinding,engineeringReviews,refKey,reviewedForSave,reviewSelectedObject,
  rootChangesForSave,SceneEngineeringStateError} from '../src/sceneEngineeringState.ts';

const ref=(uid='CT-A',connection='connection-A',project='project-A')=>({ontobaseConnectionId:connection,projectCode:project,entityUid:uid});
const expectation=(object=ref(),entity='entity:1',hierarchy='hierarchy:1',context='installation-A')=>({
  ref:object,expectedEntityRevision:entity,installationContextId:context,expectedHierarchyRevision:hierarchy});
const selection=value=>({objectRef:value.ref,expectation:value,bindingEligible:true});
const validation=(expectations=[],issues=[])=>({engineeringExpectations:expectations,bindingIssues:issues});
const issue=(object=ref(),changes={})=>({sceneModelInstanceId:'instance-A',objectRef:object,installationContextId:'installation-A',
  blocking:true,kind:'engineering_changed',expectedEntityRevision:'entity:1',expectedHierarchyRevision:'hierarchy:1',code:'ENTITY_CHANGED',...changes});
const rootChange=(changes={})=>({sceneModelInstanceId:'instance-A',from:ref('root-A'),to:ref('root-B'),
  clearOldComponentBindings:true,reviewedRemovedBindingsDigest:'a'.repeat(64),...changes});
const item=(id='instance-A',object=ref('root-A'),bindings=[{objectRef:ref(),componentKeys:['ct']}])=>({
  sceneModelInstanceId:id,displayName:id,modelVersionId:'fixed-model',
  placement:{position:{mode:'local',xM:10,zM:20},height:{mode:'local_relative',relativeHeightM:2},headingDeg:30},
  visible:true,positionLocked:false,rootBinding:object===null?null:{objectRef:object},componentBindings:bindings});
const snapshot=(instances=[item()])=>({displayName:'合成布置',coordinateFrame:{mode:'local_plane',frameRevision:'frame:1',origin:[0,0,0],unit:'m',axes:'X_EAST_Y_UP_Z_SOUTH'},
  terrain:null,instances,initialView:{eye:[20,30,40],target:[0,0,0]},defaults:{background:'sky',lighting:'neutral',terrainMaterial:'solid'}});
const throws=(run,code)=>assert.throws(run,error=>error instanceof SceneEngineeringStateError&&error.code===code);

test('ref identity contains connection, project and UID without separator collisions',()=>{
  const keys=[ref(),ref('CT-A','connection-B'),ref('CT-A','connection-A','project-B'),ref('x|y','z'),ref('y','z|x')].map(refKey);
  assert.equal(new Set(keys).size,keys.length);
  assert.equal(refKey(ref()),refKey({entityUid:'CT-A',projectCode:'project-A',ontobaseConnectionId:'connection-A'}));
  throws(()=>refKey({entityUid:'CT-A'}),'INVALID_REQUEST');
});
test('saved validation creates detached explicit review records',()=>{
  const saved=expectation(),state=engineeringReviews(validation([saved]));saved.expectedEntityRevision='caller-mutation';
  assert.equal(state.get(refKey(ref())).expectedEntityRevision,'entity:1');
  const request=reviewedForSave([expectation()],state);request[0].ref.entityUid='caller-mutation';
  assert.equal(state.get(refKey(ref())).ref.entityUid,'CT-A');
});
test('fresh open does not accept newer entity or hierarchy revisions over an old blocking issue',()=>{
  const fresh=expectation(ref(),'entity:2','hierarchy:2'),state=engineeringReviews(validation([fresh],[issue()]));
  assert.deepEqual(state.get(refKey(ref())),expectation());
  throws(()=>reviewedForSave([fresh],state),'ENGINEERING_CHANGED');
  assert.deepEqual(reviewedForSave([expectation()],state),[expectation()]);
});
test('identity drift retains the old installation context until explicit reselection',()=>{
  const fresh=expectation(ref(),'entity:2','hierarchy:2','installation-B');
  const state=engineeringReviews(validation([fresh],[issue(ref(),{code:'IDENTITY_CHANGED'})]));
  assert.equal(state.get(refKey(ref())).installationContextId,'installation-A');
  throws(()=>reviewedForSave([fresh],state),'ENGINEERING_CHANGED');
  const reviewed=reviewSelectedObject(state,selection(fresh));
  assert.deepEqual(reviewedForSave([fresh],reviewed),[fresh]);
  assert.equal(state.get(refKey(ref())).installationContextId,'installation-A');
});
test('conflicting old bases for one ref fail instead of choosing whichever issue came last',()=>{
  const issues=[issue(),issue(ref(),{sceneModelInstanceId:'instance-B',expectedEntityRevision:'entity:0'})];
  throws(()=>engineeringReviews(validation([expectation()],issues)),'ENGINEERING_CHANGED');
  assert.equal(engineeringReviews(validation([],[issue(),issue(ref(),{sceneModelInstanceId:'instance-B'})])).size,1);
});
test('model version issues do not manufacture an engineering review or overwrite its current basis',()=>{
  const modelIssue={sceneModelInstanceId:'instance-A',objectRef:ref(),installationContextId:'installation-A',blocking:true,
    kind:'model_version_changed',previousModelVersionId:'old-model',previousComponentKeys:['ct'],sourceSceneRevision:'old-scene',code:'MIGRATION_REQUIRED'};
  assert.equal(engineeringReviews(validation([],[modelIssue])).size,0);
  assert.deepEqual(engineeringReviews(validation([expectation()],[modelIssue])).get(refKey(ref())),expectation());
});
test('explicit selection updates only the selected object and keeps other reviews independent',()=>{
  const other=expectation(ref('CN-A')),state=engineeringReviews(validation([expectation(),other]));
  const fresh=expectation(ref(),'entity:2'),next=reviewSelectedObject(state,selection(fresh));
  assert.deepEqual(next.get(refKey(ref())),fresh);assert.deepEqual(next.get(refKey(ref('CN-A'))),other);
  state.get(refKey(ref('CN-A'))).expectedEntityRevision='caller-mutation';
  assert.equal(next.get(refKey(ref('CN-A'))).expectedEntityRevision,'entity:1');
});
test('ineligible or mismatched selection cannot add current review facts',()=>{
  const state=engineeringReviews(validation());
  throws(()=>reviewSelectedObject(state,{...selection(expectation()),bindingEligible:false}),'ENGINEERING_CHANGED');
  throws(()=>reviewSelectedObject(state,{objectRef:ref(),expectation:null,bindingEligible:true}),'ENGINEERING_CHANGED');
  throws(()=>reviewSelectedObject(state,{...selection(expectation()),objectRef:ref('CN-A')}),'ENGINEERING_CHANGED');
  assert.equal(state.size,0);
});
test('save reviews require every required ref and compare every expectation field',()=>{
  const old=expectation(),state=engineeringReviews(validation([old,expectation(ref('unused'))]));
  assert.deepEqual(reviewedForSave([old],state),[old]);assert.deepEqual(reviewedForSave([],state),[]);
  for(const fresh of [expectation(ref(),'entity:2'),expectation(ref(),'entity:1','hierarchy:2'),
    expectation(ref(),'entity:1','hierarchy:1','installation-B'),expectation(ref('missing')),
    expectation(ref('CT-A','connection-B')),expectation(ref('CT-A','connection-A','project-B'))]) {
    throws(()=>reviewedForSave([fresh],state),'ENGINEERING_CHANGED');
  }
  throws(()=>reviewedForSave([old,old],state),'ENGINEERING_CHANGED');
});
test('ordinary check with fresh values never mutates or fills the reviewed map',()=>{
  const old=expectation(),fresh=expectation(ref(),'entity:2'),state=engineeringReviews(validation([old]));
  throws(()=>reviewedForSave([fresh],state),'ENGINEERING_CHANGED');
  assert.deepEqual(state.get(refKey(ref())),old);
  const empty=engineeringReviews(validation());throws(()=>reviewedForSave([fresh],empty),'ENGINEERING_CHANGED');assert.equal(empty.size,0);
});
test('root approvals compare all five fields independently of object field or list ordering',()=>{
  const first=rootChange(),second=rootChange({sceneModelInstanceId:'instance-B',from:null,to:ref('root-C')});
  const result=rootChangesForSave([first,second],[second,{to:first.to,from:first.from,sceneModelInstanceId:first.sceneModelInstanceId,
    reviewedRemovedBindingsDigest:first.reviewedRemovedBindingsDigest,clearOldComponentBindings:true}]);
  assert.deepEqual(result,[first,second]);result[0].to.entityUid='caller-mutation';assert.equal(first.to.entityUid,'root-B');
  for(const altered of [{from:null},{to:null},{sceneModelInstanceId:'instance-B'},
    {reviewedRemovedBindingsDigest:'b'.repeat(64)},{to:ref('root-B','connection-B')},{to:ref('root-B','connection-A','project-B')}]) {
    throws(()=>rootChangesForSave([first],[rootChange(altered)]),'ENGINEERING_CHANGED');
  }
});
test('missing, duplicate, stale extra or malformed root approvals are never silently accepted',()=>{
  const change=rootChange();
  for(const [required,approved] of [[[change],[]],[[],[change]],[[change],[change,change]],[[change,change],[change]]]) {
    throws(()=>rootChangesForSave(required,approved),'ENGINEERING_CHANGED');
  }
  throws(()=>rootChangesForSave([change],[rootChange({clearOldComponentBindings:false})]),'INVALID_REQUEST');
  throws(()=>rootChangesForSave([change],[{...change,removedBindings:[]}]),'INVALID_REQUEST');
});
test('changing root clears internal links, while equal refs with different field order preserve them',()=>{
  const original=snapshot(),changed=changeRootBinding(original,'instance-A',ref('root-B'));
  assert.deepEqual(changed.instances[0].componentBindings,[]);
  assert.equal(original.instances[0].componentBindings.length,1);
  const same=changeRootBinding(original,'instance-A',{entityUid:'root-A',projectCode:'project-A',ontobaseConnectionId:'connection-A'});
  assert.deepEqual(same.instances[0].componentBindings,original.instances[0].componentBindings);
  assert.deepEqual(changeRootBinding(original,'instance-A',null).instances[0].componentBindings,[]);
});
test('same UID on another connection or project is a different root and clears internal links',()=>{
  for(const next of [ref('root-A','connection-B'),ref('root-A','connection-A','project-B')]) {
    assert.deepEqual(changeRootBinding(snapshot(),'instance-A',next).instances[0].componentBindings,[]);
  }
});
test('locked placement is preserved while editing engineering associations',()=>{
  const original=snapshot();original.instances[0].positionLocked=true;
  const changed=bindComponentKeys(original,'instance-A',ref(),['ct','ct-secondary']);
  assert.deepEqual(changed.instances[0].placement,original.instances[0].placement);
  assert.equal(changed.instances[0].positionLocked,true);
  assert.deepEqual(changeRootBinding(changed,'instance-A',ref('root-B')).instances[0].placement,original.instances[0].placement);
});
test('component update replaces only the selected object row and an empty selection removes it',()=>{
  const original=snapshot([item('instance-A',ref('root-A'),[{objectRef:ref(),componentKeys:['ct']},{objectRef:ref('CN-A'),componentKeys:['cn']}])]);
  const changed=bindComponentKeys(original,'instance-A',ref(),['ct-2','ct-1']);
  assert.deepEqual(changed.instances[0].componentBindings,[{objectRef:ref(),componentKeys:['ct-1','ct-2']},{objectRef:ref('CN-A'),componentKeys:['cn']}]);
  assert.deepEqual(original.instances[0].componentBindings[0].componentKeys,['ct']);
  const removed=bindComponentKeys(changed,'instance-A',ref(),[]);
  assert.deepEqual(removed.instances[0].componentBindings,[{objectRef:ref('CN-A'),componentKeys:['cn']}]);
});
test('one instance cannot give a component key to two objects, but independent instances can reuse it',()=>{
  const original=snapshot([item(),item('instance-B',ref('root-B'),[{objectRef:ref('CT-B'),componentKeys:['ct']}])]);
  throws(()=>bindComponentKeys(original,'instance-A',ref('CN-A'),['ct']),'COMPONENT_ALREADY_BOUND');
  const changed=bindComponentKeys(original,'instance-B',ref('CT-B'),['ct','another']);
  assert.deepEqual(changed.instances[0],original.instances[0]);assert.equal(changed.instances[1].componentBindings.length,1);
});
test('new component binding needs a root in the same connection and project',()=>{
  throws(()=>bindComponentKeys(snapshot([item('instance-A',null,[])]),'instance-A',ref(),['ct']),'ENGINEERING_CHANGED');
  throws(()=>bindComponentKeys(snapshot(),'instance-A',ref('CT-A','connection-B'),['another']),'ENGINEERING_CHANGED');
  throws(()=>bindComponentKeys(snapshot(),'instance-A',ref('CT-A','connection-A','project-B'),['another']),'ENGINEERING_CHANGED');
  throws(()=>bindComponentKeys(snapshot(),'missing',ref(),['ct']),'INVALID_REQUEST');
  throws(()=>bindComponentKeys(snapshot(),'instance-A',ref(),['ct','ct']),'INVALID_REQUEST');
});
test('global component-key and binding-row budgets apply across all instances',()=>{
  const many=Array.from({length:1000},(_,index)=>'key-'+index),original=snapshot([item('instance-A',ref('root-A'),[]),item('instance-B',ref('root-B'),[])]);
  const full=bindComponentKeys(original,'instance-A',ref(),many);
  throws(()=>bindComponentKeys(full,'instance-B',ref('CT-B'),['one-more']),'SCENE_LIMIT_EXCEEDED');
  throws(()=>bindComponentKeys(original,'instance-A',ref(),[...many,'one-more']),'SCENE_LIMIT_EXCEEDED');
  const rows=snapshot([item('instance-A',ref('root-A'),many.map((key,index)=>({objectRef:ref('object-'+index),componentKeys:[key]}))),item('instance-B',ref('root-B'),[])]);
  throws(()=>bindComponentKeys(rows,'instance-B',ref('CT-B'),['one-more']),'SCENE_LIMIT_EXCEEDED');
});
