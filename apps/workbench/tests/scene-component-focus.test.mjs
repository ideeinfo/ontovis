import assert from 'node:assert/strict';
import test from 'node:test';
import * as THREE from 'three';
import {componentFocusCurrent,componentFocusKey,componentFocusView,prepareComponentFocus} from '../src/sceneComponentFocus.ts';

const item=(id='instance-A',model='model-A')=>({sceneModelInstanceId:id,displayName:id,modelVersionId:model,
  placement:{position:{mode:'local',xM:30,zM:40},height:{mode:'local_relative',relativeHeightM:2},headingDeg:30},
  visible:true,positionLocked:false,rootBinding:null,componentBindings:[]});
const snapshot=()=>({displayName:'synthetic',coordinateFrame:{mode:'local_plane',frameRevision:'frame-A',origin:[0,0,0],unit:'m',axes:'X_EAST_Y_UP_Z_SOUTH'},
  terrain:null,instances:[item(),item('instance-B')],initialView:{eye:[0,50,80],target:[0,0,0]},defaults:{background:'sky',lighting:'neutral',terrainMaterial:'solid'}});
const context=()=>({snapshot:snapshot(),selectedId:'instance-A',modelRefs:[{modelVersionId:'model-A',modelAssetId:'asset-A',contentRevision:'content-A',sha256:'a'.repeat(64)}],
  personalVisibility:{},previewActive:false});
const request=(token=1)=>({token,instanceId:'instance-A',bounds:[[10,20,30],[14,24,34]]});
const view={eye:[40,25,65],target:[0,5,0]};

test('finite ordered nonempty world bounds are required before any focus target is prepared',()=>{
  for(const bounds of [[[2,0,0],[1,1,1]],[[0,0,0],[0,0,0]],[[NaN,0,0],[1,1,1]],
    [[0,0,0],[Infinity,1,1]],[[0,0],[1,1,1]],[[-1e308,0,0],[1e308,1,1]]]) {
    const value={...request(),bounds};assert.equal(componentFocusKey(value),null);assert.equal(prepareComponentFocus(value,context()),null);
  }
  assert.ok(prepareComponentFocus({...request(),bounds:[[0,0,0],[0,2,3]]},context()));
  assert.equal(componentFocusKey({...request(),token:NaN}),null);
  assert.equal(componentFocusKey({...request(),token:1.5}),null);
});
test('only the selected visible matching instance receives a component focus',()=>{
  const state=context();
  assert.ok(prepareComponentFocus(request(),state));
  assert.equal(prepareComponentFocus({...request(),instanceId:'missing'},state),null);
  assert.equal(prepareComponentFocus({...request(),instanceId:'instance-B'},state),null);
  assert.equal(prepareComponentFocus(request(),{...state,selectedId:null}),null);
  assert.equal(prepareComponentFocus(request(),{...state,previewActive:true}),null);
  assert.equal(prepareComponentFocus(request(),{...state,personalVisibility:{'instance-A':false}}),null);
  state.snapshot.instances[0].visible=false;
  assert.equal(prepareComponentFocus(request(),state),null);
  assert.ok(prepareComponentFocus(request(),{...state,personalVisibility:{'instance-A':true}}));
});
test('prepared focus pins exact bounds and source identity without applying a second calibration transform',()=>{
  const state=context(),value=request(),target=prepareComponentFocus(value,state);
  assert.deepEqual(target.bounds,value.bounds);
  assert.equal(target.modelKey,JSON.stringify(['model-A','content-A','a'.repeat(64)]));
  value.bounds[0][0]=999;
  assert.equal(target.bounds[0][0],10);
  assert.equal(componentFocusCurrent(target,value,state),false);
});
test('clearing, cancelling or superseding the request invalidates an old pending target',()=>{
  const state=context(),value=request(),target=prepareComponentFocus(value,state);
  assert.equal(componentFocusCurrent(target,undefined,state),false);
  assert.equal(componentFocusCurrent(target,request(2),state),false);
  assert.equal(componentFocusCurrent(target,{...request(),instanceId:'instance-B'},state),false);
  assert.equal(componentFocusCurrent(target,request(),structuredClone(state)),true);
});
test('host component keys travel with the focus and a different key selection invalidates the previous display',()=>{
  const state=context(),value={...request(),componentKeys:['mapped-CN-host']},target=prepareComponentFocus(value,state);
  assert.deepEqual(target.componentKeys,['mapped-CN-host']);
  value.componentKeys.push('later-key');assert.deepEqual(target.componentKeys,['mapped-CN-host']);
  assert.equal(componentFocusCurrent(target,value,state),false);
  assert.equal(componentFocusCurrent(target,{...request(),componentKeys:['child-without-geometry']},state),false);
  assert.notEqual(componentFocusKey({...request(),componentKeys:['mapped-CN-host']}),componentFocusKey({...request(),componentKeys:['mapped-CT']}));
});
test('malformed or repeated component keys never create a focus display',()=>{
  for(const componentKeys of [null,'mapped-CN',[''],['mapped-CN','mapped-CN'],['x'.repeat(513)],[42]]){
    assert.equal(componentFocusKey({...request(),componentKeys}),null);
    assert.equal(prepareComponentFocus({...request(),componentKeys},context()),null);
  }
});
test('loading completion cannot reuse bounds after selected instance, model or fixed resource identity changes',()=>{
  const state=context(),target=prepareComponentFocus(request(),state);
  const variants=[];
  variants.push({...state,selectedId:'instance-B'});
  for(const [field,value] of [['modelVersionId','model-B'],['contentRevision','content-B'],['sha256','b'.repeat(64)],['modelAssetId','asset-B']]) {
    const changed=structuredClone(state);changed.modelRefs[0][field]=value;variants.push(changed);
  }
  const model=structuredClone(state);model.snapshot.instances[0].modelVersionId='model-B';variants.push(model);
  variants.push({...state,modelRefs:[]});
  variants.push({...state,modelRefs:[state.modelRefs[0],state.modelRefs[0]]});
  for(const changed of variants)assert.equal(componentFocusCurrent(target,request(),changed),false);
});
test('pending bounds expire when placement, height, heading or coordinate frame changes',()=>{
  const state=context(),target=prepareComponentFocus(request(),state);
  const variants=[];
  for(const change of [item=>item.placement.position.xM++,item=>item.placement.position.zM++,
    item=>item.placement.height.relativeHeightM++,item=>item.placement.headingDeg++]) {
    const changed=structuredClone(state);change(changed.snapshot.instances[0]);variants.push(changed);
  }
  const frame=structuredClone(state);frame.snapshot.coordinateFrame.frameRevision='frame-B';variants.push(frame);
  for(const changed of variants)assert.equal(componentFocusCurrent(target,request(),changed),false);
  const named=structuredClone(state);named.snapshot.displayName='renamed';named.snapshot.instances[0].displayName='renamed';
  assert.equal(componentFocusCurrent(target,request(),named),true);
});
test('hidden instances and resource previews invalidate pending work rather than unhiding a model',()=>{
  const state=context(),target=prepareComponentFocus(request(),state);
  assert.equal(componentFocusCurrent(target,request(),{...state,personalVisibility:{'instance-A':false}}),false);
  assert.equal(componentFocusCurrent(target,request(),{...state,previewActive:true}),false);
  assert.equal(state.snapshot.instances[0].visible,true);assert.deepEqual(state.personalVisibility,{});
});
test('component fitting keeps the current camera direction and directly targets the component center',()=>{
  const destination=componentFocusView(request().bounds,view,42,1.5);
  assert.deepEqual(destination.target,[12,22,32]);
  const from=new THREE.Vector3(...view.eye).sub(new THREE.Vector3(...view.target)).normalize();
  const to=new THREE.Vector3(...destination.eye).sub(new THREE.Vector3(...destination.target)).normalize();
  assert.ok(from.distanceTo(to)<1e-12);
  assert.deepEqual(view,{eye:[40,25,65],target:[0,5,0]});
});
test('the fitted component corners remain inside both wide and narrow perspective viewports',()=>{
  const bounds=[[-12,15,-30],[22,24,54]];
  for(const aspect of [.35,1,2.5]) {
    const destination=componentFocusView(bounds,view,42,aspect);
    const camera=new THREE.PerspectiveCamera(42,aspect,.05,2_000_000);
    camera.position.fromArray(destination.eye);camera.lookAt(new THREE.Vector3(...destination.target));camera.updateMatrixWorld(true);
    for(const x of [bounds[0][0],bounds[1][0]])for(const y of [bounds[0][1],bounds[1][1]])for(const z of [bounds[0][2],bounds[1][2]]) {
      const projected=new THREE.Vector3(x,y,z).project(camera);
      assert.ok(Math.abs(projected.x)<1&&Math.abs(projected.y)<1&&Math.abs(projected.z)<1);
    }
  }
});
test('invalid view inputs hold the camera and a coincident eye uses a finite fallback direction',()=>{
  for(const [camera,fov,aspect] of [{eye:[NaN,0,0],target:[0,0,0]},view].map((value,index)=>[value,index?0:42,1])) {
    assert.equal(componentFocusView(request().bounds,camera,fov,aspect),null);
  }
  assert.equal(componentFocusView(request().bounds,view,42,0),null);
  assert.equal(componentFocusView(request().bounds,view,42,NaN),null);
  assert.ok(componentFocusView(request().bounds,{eye:[0,0,0],target:[0,0,0]},42,1).eye.every(Number.isFinite));
});

test('changing isolation invalidates only the temporary component display request',()=>{
 const state=context(),value={...request(),isolate:true},target=prepareComponentFocus(value,state);
 assert.equal(target.isolate,true);assert.equal(componentFocusCurrent(target,{...value,isolate:false},state),false);
 assert.equal(componentFocusKey({...value,isolate:'yes'}),null);
});
