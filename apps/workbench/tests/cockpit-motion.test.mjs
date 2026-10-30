import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import * as THREE from 'three';
import {MOTION_MODEL_SHA,MOTION_MERGED_SHA,MOTION_SOURCE,SimulatedMotionClock,yawDelta} from '../src/simulatedMotion.ts';
import {SceneMotion} from '../src/sceneMotion.ts';
import {WorkbenchApi} from '../src/api.ts';
import {SceneResourceCache,cloneModel,modelSourceNode} from '../src/sceneResourceCache.ts';
const sample=(overrides={})=>({sourceId:MOTION_SOURCE,epoch:'demo',seq:1,issuedAt:0,validUntil:2500,rpm:10,yawDeg:90,rpmUnit:'rpm',yawUnit:'deg',quality:'good',...overrides});
test('10 rpm rotates 60 degrees in one second; yaw slews 30 degrees without moving by frame count',()=>{
 for(const step of [10,20,50,100]){const clock=new SimulatedMotionClock('demo');clock.accept(sample(),0);clock.step(0,true);
  for(let now=step;now<=1000;now+=step)clock.step(now,true);
  assert.ok(Math.abs(clock.rotor-Math.PI/3)<1e-9);assert.ok(Math.abs(clock.yaw-30)<1e-9);}
});
test('yaw crosses north by the short path, zero rpm stays stopped, paused intervals never catch up',()=>{
 assert.equal(yawDelta(359,1),2);assert.equal(yawDelta(1,359),-2);
 const clock=new SimulatedMotionClock('demo');clock.yaw=359;clock.accept(sample({rpm:0,yawDeg:1}),0);clock.step(0,true);clock.step(100,true);
 assert.equal(clock.yaw,1);assert.equal(clock.rotor,0);clock.accept(sample({seq:2,rpm:10,yawDeg:1}),100);clock.step(200,true);
 const prior=clock.rotor;clock.step(300,false);clock.step(1800,true);assert.equal(clock.rotor,prior);clock.step(1900,true);assert.ok(clock.rotor>prior);
});
test('bad, expired, disconnected and invalid values freeze; later fresh values resume without catch-up',()=>{
 for(const override of [{quality:'bad'},{quality:'offline'},{quality:'stale'},{rpm:-1},{rpm:NaN},{rpm:21},{yawDeg:360},{yawDeg:Infinity},{rpmUnit:'m/s'},{yawUnit:'rad'},{issuedAt:201},{validUntil:200},{validUntil:3001}]){
  const clock=new SimulatedMotionClock('demo');clock.accept(sample(),0);clock.step(0,true);clock.step(100,true);const prior=clock.rotor;
  assert.equal(clock.accept(sample({seq:2,...override}),200),false);assert.equal(clock.step(300,true),false);assert.equal(clock.rotor,prior);
  assert.equal(clock.accept(sample({seq:3,issuedAt:1000,validUntil:3500}),1000),true);clock.step(1000,true);assert.equal(clock.rotor,prior);clock.step(1100,true);assert.ok(clock.rotor>prior);
 }
});
test('wrong source, epoch, duplicate and out-of-order samples cannot replace accepted data; timeout is enforced',()=>{
 const clock=new SimulatedMotionClock('demo');clock.accept(sample({seq:5,rpm:0,yawDeg:0}),0);
 for(const override of [{sourceId:'weather'},{epoch:'other'},{seq:5},{seq:4}])assert.equal(clock.accept(sample({seq:6,...override}),0),false);
 clock.step(0,true);clock.step(100,true);assert.equal(clock.rotor,0);assert.equal(clock.yaw,0);
 clock.accept(sample({seq:7}),100);clock.step(200,true);const prior=clock.rotor;assert.equal(clock.step(2500,true),false);assert.equal(clock.rotor,prior);
 clock.accept(sample({seq:8,issuedAt:6000,validUntil:8500}),6000);clock.step(6000,true);assert.equal(clock.rotor,prior);clock.step(8000,true);assert.ok(clock.rotor-prior<=Math.PI/30+.00001);
});
async function fixture(merged=false){
 const positions=new Float32Array([0,0,0,1,0,0,0,1,0]),nodes=Array.from({length:merged?184:20},(_,i)=>({name:'untrusted-name-'+i}));
 nodes[0].children=[1,2];nodes[1].children=Array.from({length:12},(_,i)=>i+3);nodes[2].children=[15,16,17,18,19];nodes[2].translation=[0,90,6.67];
 if(merged){nodes[1].children=[...Array.from({length:140},(_,i)=>i+3),...Array.from({length:8},(_,i)=>i+176)];nodes[2].children=Array.from({length:33},(_,i)=>i+143);}
 for(let i=3;i<nodes.length;i++)nodes[i].mesh=0;
 const doc={asset:{version:'2.0'},scene:0,scenes:[{nodes:[0]}],nodes,meshes:[{primitives:[{attributes:{POSITION:0}}]}],
  buffers:[{byteLength:positions.byteLength}],bufferViews:[{buffer:0,byteLength:positions.byteLength}],accessors:[{bufferView:0,componentType:5126,type:'VEC3',count:3,min:[0,0,0],max:[1,1,0]}]};
 const raw=new TextEncoder().encode(JSON.stringify(doc)),json=new Uint8Array(Math.ceil(raw.length/4)*4);json.fill(32);json.set(raw);
 const bytes=new ArrayBuffer(28+json.length+positions.byteLength),v=new DataView(bytes);
 [0x46546c67,2,bytes.byteLength,json.length,0x4e4f534a].forEach((x,i)=>v.setUint32(i*4,x,true));new Uint8Array(bytes,20,json.length).set(json);
 v.setUint32(20+json.length,positions.byteLength,true);v.setUint32(24+json.length,0x004e4942,true);new Uint8Array(bytes,28+json.length).set(new Uint8Array(positions.buffer));
 const version={state:'ready',canPlace:true,calibrationState:'verified',modelVersionId:'v1',modelAssetId:'a1',contentRevision:'content:1',sha256:createHash('sha256').update(new Uint8Array(bytes)).digest('hex'),bytes:bytes.byteLength,
  calibration:{state:'verified',unit:'m',axes:'Y_UP_RIGHT_HANDED',basePoint:[0,0,0],forward:[0,0,-1],modelToCalibrated:new THREE.Matrix4().toArray()},components:[],report:{animations:0,externalResourcesFetched:0}};
 const api=new WorkbenchApi();api.session('fixture');const cache=new SceneResourceCache(api,{source:{model:async()=>version,modelContent:async()=>new Blob([bytes])}});
 const resource=await cache.model(version),a=cloneModel(resource,'a'),b=cloneModel(resource,'b');
 // Synthetic geometry exercises the reviewed profile without distributing third-party model bytes.
 const adapted={...version,sha256:merged?MOTION_MERGED_SHA:MOTION_MODEL_SHA};const now=performance.now();
 const request={instanceId:'a',modelVersionId:'v1',contentRevision:'content:1',sha256:merged?MOTION_MERGED_SHA:MOTION_MODEL_SHA,epoch:'demo',playing:true,axes:true,sample:sample({issuedAt:now,validUntil:now+2500,yawDeg:90,rpm:10})};
 return {cache,resource,a,b,adapted,request,now};
}
const node=(root,i)=>{let match;root.traverse(n=>{if(modelSourceNode(n)?.index===i)match=n;});return match;};
const snapshot=root=>{root.updateWorldMatrix(true,true);const rows=[];root.traverse(n=>rows.push({uuid:n.uuid,parent:n.parent?.uuid,position:n.position.toArray(),rotation:n.quaternion.toArray(),scale:n.scale.toArray(),world:n.matrixWorld.toArray()}));return rows;};
test('yaw and rotor compose under installation transforms; tower and another instance remain fixed; reset exactly restores clone',async()=>{
 const f=await fixture();f.a.position.set(100,5,200);f.a.rotation.y=.8;const baseline=snapshot(f.a),other=snapshot(f.b),source=snapshot(f.resource.scene);
 const towerBefore=node(f.a,3).getWorldPosition(new THREE.Vector3()),rig=SceneMotion.create(f.a,f.adapted,f.request);assert.ok(rig);
 rig.step(f.now);for(let i=1;i<=10;i++)rig.step(f.now+i*100);
 const rotor=node(f.a,2),rotorPoint=rotor.getWorldPosition(new THREE.Vector3());
 const expected=new THREE.Vector3(0,0,6.67).applyAxisAngle(new THREE.Vector3(0,1,0),-Math.PI/6).add(new THREE.Vector3(0,90,0)).applyAxisAngle(new THREE.Vector3(0,1,0),.8).add(f.a.position);
 assert.ok(rotorPoint.distanceTo(expected)<1e-7);assert.ok(Math.abs(rotor.rotation.z-Math.PI/3)<1e-7);
 assert.ok(node(f.a,3).getWorldPosition(new THREE.Vector3()).distanceTo(towerBefore)<1e-8);
 assert.deepEqual(snapshot(f.b),other);assert.deepEqual(snapshot(f.resource.scene),source);rig.dispose();rig.dispose();assert.deepEqual(snapshot(f.a),baseline);f.cache.dispose();
});
test('wrong fixed content, version, instance, calibration or hierarchy is refused before any mutation',async()=>{
 const f=await fixture(),before=snapshot(f.a);
 for(const change of [{sha256:'other'},{contentRevision:'content:2'},{modelVersionId:'v2'},{calibration:{state:'unverified'}}])assert.equal(SceneMotion.create(f.a,{...f.adapted,...change},f.request),null);
 assert.equal(SceneMotion.create(f.b,f.adapted,f.request),null);assert.deepEqual(snapshot(f.a),before);
 node(f.a,1).add(node(f.a,2));const changed=snapshot(f.a);assert.equal(SceneMotion.create(f.a,f.adapted,f.request),null);assert.deepEqual(snapshot(f.a),changed);f.cache.dispose();
});

test('184-node production layout drives nacelle internals and leaves upper tower groups fixed',async()=>{
 const f=await fixture(true),base=snapshot(f.a),tower=node(f.a,180).getWorldPosition(new THREE.Vector3());
 const rig=SceneMotion.create(f.a,f.adapted,f.request);assert.ok(rig);assert.equal(node(f.a,91).parent,node(f.a,2).parent);
 assert.notEqual(node(f.a,180).parent,node(f.a,2).parent);rig.step(f.now);rig.step(f.now+100);
 assert.ok(node(f.a,180).getWorldPosition(new THREE.Vector3()).distanceTo(tower)<1e-8);rig.dispose();assert.deepEqual(snapshot(f.a),base);f.cache.dispose();
});
