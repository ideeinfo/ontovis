import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {modelSimulation,simulationRequests} from '../src/cockpitSimulation.ts';
import {SceneMotion,SceneMotionBatch} from '../src/sceneMotion.ts';
import {SceneCabinetAppearance} from '../src/sceneCabinetAppearance.ts';
import {componentFocusView} from '../src/sceneComponentFocus.ts';
import {MOTION_MERGED_SHA,motionProfile} from '../src/simulatedMotion.ts';
import {fixture,node,snapshot} from './helpers/fixed-model.mjs';
const shafts=[
 ['e5fecd93d0fe846883be50fd6b8b89cede9f6739d4fe7a83d3f9e918f4348c7d',74,6.214,17],
 ['40aa13d46bc60f3c7ba4120ed900d591ded5c120ac08833dab4e9df71e96bcfe',120,8.2,33],
 ['e1c6381f7307d8e607d85a5b665f9ba5a0d882484ed85625206210d221c0a24c',73.5,5.248,17],
 ['f20a7d1af9ca22e937fea7ed3144f7889139556a97add866bb5f2ee4c8e90cf1',80,6.7,32],
 ['4eff3bb556859105e5f9e44930a6aba8bd4c1e91d6871473534fdcc63b983488',60,5.09,14],
 ['cca1b148de90c066aaab914d2e5cf152772c14615bee3ac64cb7a2beb44605bb',68.5,6.7,20],
 ['a23e4a7ff9782c673047fefbb3a1b65f1e025cef697994458c9f4d10464b29fa',83.5,5.55,32],
 ['8ea2286721fe0cdabbce0d108bc4017d5a5a502c552e438620bd5ea0560c036f',113,9.75,72],
 ['eef5021e574fa340d89872882cae4502b6ed793a58c42200a2cedf2458258cc0',150,10.58,30],
 ['a66c18148339ea3d1a4d1f0852a2c8201e48df05a9e2f2df8e4a65acb75886bb',170,12.58,77],
];
test('deterministic per-model presets differ, remain bounded, and include static assets',()=>{
 const a=modelSimulation('instance-a',MOTION_MERGED_SHA,'balanced'),b=modelSimulation('instance-b',MOTION_MERGED_SHA,'balanced');
 assert.deepEqual(a,modelSimulation('instance-a',MOTION_MERGED_SHA,'balanced'));assert.notDeepEqual(a,b);
 for(const [sha] of shafts)for(let i=0;i<100;i++){const v=modelSimulation('id'+i,sha,'balanced');assert.ok(v.rpm>0&&v.rpm<=20&&v.yaw>=0&&v.yaw<360&&v.phase>=0&&v.phase<2*Math.PI);}
 assert.equal(modelSimulation('id','unknown','balanced').rpm,0);assert.equal(modelSimulation('id','unknown','balanced').dynamic,false);
 assert.ok(modelSimulation('instance-a',MOTION_MERGED_SHA,'slow').rpm<a.rpm);assert.equal(modelSimulation('instance-a',MOTION_MERGED_SHA,'stopped').rpm,0);
});
test('scene load produces all visible adapted requests; inspection, visibility, presets and overrides are local',()=>{
 const instances=['a','b','c','sample'].map(id=>({sceneModelInstanceId:id,modelVersionId:id==='sample'?'static':'v',visible:true}));
 const refs=[{modelVersionId:'v',sha256:MOTION_MERGED_SHA,contentRevision:'r'},{modelVersionId:'static',sha256:'triangle',contentRevision:'r'}],before=structuredClone({instances,refs});
 const options={epoch:'e',seq:1,now:1000,elapsed:0,preset:'balanced',playing:true,visibility:{},overrides:{}};
 const all=simulationRequests(instances,refs,options);assert.deepEqual(all.map(r=>r.instanceId),['a','b','c']);assert.ok(all.every(r=>r.playing&&r.sample.rpm>0));
 const limited=simulationRequests(instances,refs,{...options,excludedId:'a',visibility:{b:false}});assert.deepEqual(limited.map(r=>r.instanceId),['c']);
 const custom=simulationRequests(instances,refs,{...options,overrides:{b:{rpm:0,yaw:359,axes:true}}});
 assert.equal(custom[1].sample.rpm,0);assert.equal(custom[1].sample.yawDeg,359);assert.equal(custom[1].axes,true);assert.deepEqual(custom[0],all[0]);
 assert.ok(simulationRequests(instances,refs,{...options,playing:false}).every(r=>!r.playing));
 assert.ok(simulationRequests(instances,refs,{...options,preset:'stopped'}).every(r=>!r.playing&&r.sample.rpm===0));assert.deepEqual({instances,refs},before);
});
test('baked model rotors use source shaft centers; foundations and upper towers stay fixed and restore exactly',async()=>{
 for(const [sha,height,z,fixedIndex] of shafts){
  const f=await fixture(false,sha),profile=motionProfile(sha),before=snapshot(f.a),source=snapshot(f.resource.scene),other=snapshot(f.b);
  const request={...f.request,initialYaw:0,initialPhase:0,sample:{...f.request.sample,yawDeg:0}};
  const tower=node(f.a,fixedIndex).getWorldPosition(new THREE.Vector3()),rig=SceneMotion.create(f.a,f.adapted,request);assert.ok(rig,sha);
  const part=node(f.a,profile.rotorStart),pivot=part.parent;assert.deepEqual(pivot.getWorldPosition(new THREE.Vector3()).toArray(),[0,height,z]);
  rig.step(f.now);for(let i=1;i<=10;i++)rig.step(f.now+i*100);
  const expected=new THREE.Vector3(0,-height,-z).applyAxisAngle(new THREE.Vector3(0,0,1),Math.PI/3).add(new THREE.Vector3(0,height,z));
  assert.ok(part.getWorldPosition(new THREE.Vector3()).distanceTo(expected)<1e-7,sha);
  assert.deepEqual(node(f.a,fixedIndex).getWorldPosition(new THREE.Vector3()),tower);assert.deepEqual(snapshot(f.b),other);assert.deepEqual(snapshot(f.resource.scene),source);
  rig.dispose();assert.deepEqual(snapshot(f.a),before);f.cache.dispose();
 }
});
test('independent drivers run together; explicitly excluding one restores it while others continue, and stale samples freeze',async()=>{
 const f=await fixture(true),beforeA=snapshot(f.a),beforeB=snapshot(f.b),batch=new SceneMotionBatch();
 const a=f.request,b={...a,instanceId:'b',sample:{...a.sample,rpm:4,yawDeg:10}};
 const entries=new Map([['a',{root:f.a,version:f.adapted}],['b',{root:f.b,version:f.adapted}]]);
 assert.deepEqual(batch.sync(entries,[a,b],f.now),{a:'ready',b:'ready'});batch.step(f.now);batch.step(f.now+100);
 assert.notEqual(node(f.a,2).quaternion.z,node(f.b,2).quaternion.z);
 batch.sync(entries,[b],f.now+100);assert.deepEqual(snapshot(f.a),beforeA);const angle=node(f.b,2).quaternion.z;
 batch.step(f.now+200);assert.ok(node(f.b,2).quaternion.z>angle);const held=snapshot(f.b);
 assert.equal(batch.step(f.now+3000),false);assert.deepEqual(snapshot(f.b),held);
 batch.clear();assert.deepEqual(snapshot(f.b),beforeB);assert.equal(batch.size,0);f.cache.dispose();
});

test('isolating a mapped component keeps rotor motion and frames its actual simulated pose while preserving source geometry',async()=>{
 const f=await fixture(true),source=snapshot(f.resource.scene),other=snapshot(f.b),before=snapshot(f.a),batch=new SceneMotionBatch();
 const mesh=node(f.a,91);mesh.userData.ontoVisComponentKey='yaw';mesh.position.set(6,90,2);
 f.adapted.components=[{componentKey:'yaw',nodeIndices:[91],geometryQuality:'source_candidate'}];
 const appearance=new SceneCabinetAppearance(f.a,f.adapted),request={...f.request,axes:false,initialYaw:18},entries=new Map([['a',{root:f.a,version:f.adapted}]]);
 assert.deepEqual(batch.sync(entries,[request],f.now),{a:'ready'});batch.step(f.now);appearance.apply(['yaw'],'#007e6d',true);
 const first=appearance.selectionBounds(),rotor=node(f.a,2).quaternion.clone();
 batch.step(f.now+100);batch.sync(entries,[request],f.now+100);appearance.apply(['yaw'],'#007e6d',true);batch.step(f.now+200);
 assert.ok(!node(f.a,2).quaternion.equals(rotor));assert.deepEqual(appearance.selectionBounds(),new THREE.Box3().setFromObject(mesh));
 assert.notDeepEqual(appearance.selectionBounds(),first);
 const box=appearance.selectionBounds(),view=componentFocusView([box.min.toArray(),box.max.toArray()],{eye:[20,-5,20],target:[0,0,0]},42,16/9,true);
 assert.ok(new THREE.Vector3(...view.target).distanceTo(box.getCenter(new THREE.Vector3()))<1e-10);
 assert.deepEqual(snapshot(f.resource.scene),source);assert.deepEqual(snapshot(f.b),other);
 appearance.dispose();batch.clear();mesh.position.fromArray(before.find(item=>item.uuid===mesh.uuid).position);assert.deepEqual(snapshot(f.a),before);f.cache.dispose();
});
