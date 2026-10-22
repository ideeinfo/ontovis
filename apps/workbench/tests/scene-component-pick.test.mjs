import assert from 'node:assert/strict';
import test from 'node:test';
import * as THREE from 'three';
import {pendingComponentPick,sceneModelHit} from '../src/sceneComponentPick.ts';

const ref={ontobaseConnectionId:'synthetic-connection',projectCode:'synthetic-project',entityUid:'selected-device'};
function selection(){return {objectRef:{...ref},item:{entityUid:ref.entityUid,entityRevision:'entity:1'},
  context:{installationContextId:'context-A',hierarchyRevision:'hierarchy:1'},bindingEligible:true,
  expectation:{ref:{...ref},expectedEntityRevision:'entity:1',installationContextId:'context-A',expectedHierarchyRevision:'hierarchy:1'}};}
function request(){return {token:3,sceneModelInstanceId:'instance-A',modelVersionId:'model-A',componentKey:'part-A',
  objectRef:{...ref},expectedEntityRevision:'entity:1',installationContextId:'context-A',expectedHierarchyRevision:'hierarchy:1'};}
function context(){return {instanceId:'instance-A',modelVersionId:'model-A',selectedObject:selection(),
  components:[{componentKey:'part-A'},{componentKey:'part-B'}],componentBindings:[],enabled:true,lastToken:2};}

test('an exact current pick replaces the pending checkbox set with one key without mutating the scene or approval',()=>{
  const picked=request(),state=context(),before=structuredClone({picked,state});
  assert.deepEqual(pendingComponentPick(picked,state),{status:'selected',keys:['part-A']});
  assert.deepEqual({picked,state},before);
});

test('old tokens, inactive editing and mismatched instance/model/object/context/revisions are ignored',()=>{
  for(const alter of [pick=>{pick.token=2;},pick=>{pick.token=NaN;},pick=>{pick.token=2.5;},
    pick=>{pick.sceneModelInstanceId='instance-B';},pick=>{pick.modelVersionId='model-B';},
    pick=>{pick.objectRef.entityUid='other';},pick=>{pick.objectRef.projectCode='other';},
    pick=>{pick.objectRef.ontobaseConnectionId='other';},pick=>{pick.expectedEntityRevision='old';},
    pick=>{pick.installationContextId='other';},pick=>{pick.expectedHierarchyRevision='old';},
    pick=>{pick.componentKey='not-in-directory';}]){
    const pick=request();alter(pick);assert.deepEqual(pendingComponentPick(pick,context()),{status:'ignored'});
  }
  assert.deepEqual(pendingComponentPick(request(),{...context(),enabled:false}),{status:'ignored'});
  assert.deepEqual(pendingComponentPick(null,context()),{status:'ignored'});
});

test('current source expectation must match selected identity and the selection must remain linkable',()=>{
  for(const mutate of [state=>{state.selectedObject.bindingEligible=false;},state=>{state.selectedObject.expectation=null;},
    state=>{state.selectedObject=null;},state=>{state.selectedObject.expectation.ref.entityUid='other';},
    state=>{state.selectedObject.item.entityRevision='new';},state=>{state.selectedObject.context.hierarchyRevision='new';},
    state=>{state.selectedObject.context.installationContextId='other';}]){
    const state=context();mutate(state);assert.deepEqual(pendingComponentPick(request(),state),{status:'ignored'});
  }
});

test('components held by another object cannot be silently stolen, while current-object components remain selectable',()=>{
  const state=context();state.componentBindings=[{objectRef:{...ref,entityUid:'another-object'},componentKeys:['part-A']}];
  assert.deepEqual(pendingComponentPick(request(),state),{status:'occupied'});
  state.componentBindings[0].objectRef={...ref};
  assert.deepEqual(pendingComponentPick(request(),state),{status:'selected',keys:['part-A']});
});

test('ambiguous directory keys are ignored and only a later explicit Update can call the parent binding action',()=>{
  const state=context();state.components.push({componentKey:'part-A'});
  assert.deepEqual(pendingComponentPick(request(),state),{status:'ignored'});
  // The pure pick result contains only checkbox keys; no snapshot or review is returned.
  assert.deepEqual(Object.keys(pendingComponentPick(request(),context())).sort(),['keys','status']);
});

function tree(){
  const boundary=new THREE.Group(),root=new THREE.Group(),mesh=new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshBasicMaterial());
  boundary.add(root);root.add(mesh);
  root.userData={sceneModelInstanceId:'instance-A',ontoVisModelVersionId:'model-A'};
  mesh.userData={sceneModelInstanceId:'instance-A',ontoVisModelVersionId:'model-A',ontoVisNodeIndex:2,ontoVisComponentKey:'part-A'};
  return {boundary,root,mesh};
}

test('a visible actual component carries independent fixed instance/version/key identity',()=>{
  const {boundary,mesh}=tree();
  assert.deepEqual(sceneModelHit(mesh,boundary),{sceneModelInstanceId:'instance-A',component:{sceneModelInstanceId:'instance-A',modelVersionId:'model-A',componentKey:'part-A'}});
});

test('cache schematic tags remain pickable without pretending to be GLTF nodes',()=>{
  const {boundary,root,mesh}=tree();delete mesh.userData.ontoVisNodeIndex;mesh.userData.ontoVisProxySchematic=true;
  assert.deepEqual(sceneModelHit(mesh,boundary)?.component,{sceneModelInstanceId:'instance-A',modelVersionId:'model-A',componentKey:'part-A'});
  for(const marker of [false,'true',1,undefined]){
    mesh.userData.ontoVisProxySchematic=marker;assert.equal(sceneModelHit(mesh,boundary)?.component,null);
  }
  mesh.userData.ontoVisProxySchematic=true;root.visible=false;assert.equal(sceneModelHit(mesh,boundary),null);
});

test('hidden parents, external objects and inconsistent clone tags do not produce a hit',()=>{
  for(const mutate of [value=>{value.root.visible=false;},value=>{value.mesh.visible=false;},value=>{value.boundary.visible=false;},
    value=>{value.mesh.removeFromParent();},value=>{value.mesh.userData.sceneModelInstanceId='different-instance';},
    value=>{value.mesh.userData.ontoVisModelVersionId='different-version';}]){
    const value=tree();mutate(value);assert.equal(sceneModelHit(value.mesh,value.boundary),null);
  }
});

test('unmapped actual child node stays unmapped and cannot inherit a parent component key',()=>{
  const {boundary,root,mesh}=tree();root.userData.ontoVisNodeIndex=1;root.userData.ontoVisComponentKey='parent-part';
  delete mesh.userData.ontoVisComponentKey;
  assert.equal(sceneModelHit(mesh,boundary)?.component,null);
});

test('a primitive without a node association may use its containing mapped GLTF group',()=>{
  const {boundary,root,mesh}=tree();delete mesh.userData.ontoVisNodeIndex;delete mesh.userData.ontoVisComponentKey;
  root.userData.ontoVisNodeIndex=1;root.userData.ontoVisComponentKey='group-part';
  assert.equal(sceneModelHit(mesh,boundary)?.component?.componentKey,'group-part');
});
