import * as THREE from 'three';
import {modelSourceNode,modelSchematicKey} from './sceneResourceCache.ts';
import {motionProfile,SimulatedMotionClock,type MotionRequest} from './simulatedMotion.ts';
import type {ProjectModelVersion} from './resourceTypes.ts';

type Saved={node:THREE.Object3D;parent:THREE.Object3D;order:number;position:THREE.Vector3;quaternion:THREE.Quaternion;scale:THREE.Vector3;matrix:THREE.Matrix4;auto:boolean};
/** Operates on one clone only; fixed source-node identity comes from the GLTF parser. */
export class SceneMotion {
 private yaw=new THREE.Group();private helpers=new THREE.Group();private rotor:THREE.Object3D;
 private saved:Saved[]=[];private clock:SimulatedMotionClock;private request:MotionRequest;
 private disposed=false;private lastSeq=-1;
 static create(root:THREE.Group,version:ProjectModelVersion,request:MotionRequest):SceneMotion|null {
  const profile=motionProfile(version.sha256);
  if(!profile||request.sha256!==version.sha256||request.modelVersionId!==version.modelVersionId||request.contentRevision!==version.contentRevision
   ||root.userData.sceneModelInstanceId!==request.instanceId||version.calibration.state!=='verified')return null;
  const nodes=new Map<number,THREE.Object3D>();let duplicate=false;
  root.traverse(node=>{const source=modelSourceNode(node);if(source){if(nodes.has(source.index))duplicate=true;nodes.set(source.index,node);}});
  if(duplicate||nodes.size!==profile.nodes)return null;
  const base=nodes.get(0),fixed=nodes.get(1),rotor=nodes.get(2);
  if(!base||!fixed||!rotor||fixed.parent!==base||rotor.parent!==base
   ||rotor.position.distanceTo(new THREE.Vector3(0,90,6.67))>1e-5)return null;
  for(let i=3;i<profile.nodes;i++)if(nodes.get(i)?.parent!==(i>=profile.rotorStart&&i<=profile.rotorEnd?rotor:fixed))return null;
  const schematic:THREE.Object3D[]=[];
  root.traverse(node=>{if(modelSchematicKey(node)==='proxy:CN1')schematic.push(node);});
  return new SceneMotion(base,rotor,[...Array.from({length:profile.movingEnd-11},(_,i)=>nodes.get(i+12)!),...schematic,rotor],request);
 }
 private constructor(base:THREE.Object3D,rotor:THREE.Object3D,moving:THREE.Object3D[],request:MotionRequest){
  this.rotor=rotor;this.request=request;this.clock=new SimulatedMotionClock(request.epoch);
  this.saved=moving.map(node=>({node,parent:node.parent!,order:node.parent!.children.indexOf(node),position:node.position.clone(),
   quaternion:node.quaternion.clone(),scale:node.scale.clone(),matrix:node.matrix.clone(),auto:node.matrixAutoUpdate}));
  this.yaw.name='ONTOVis simulated yaw';this.yaw.position.set(0,90,0);base.add(this.yaw);base.updateWorldMatrix(true,true);
  for(const node of moving)this.yaw.attach(node);
  const y=new THREE.ArrowHelper(new THREE.Vector3(0,1,0),new THREE.Vector3(),20,0x35dcc9,4,2);
  const z=new THREE.ArrowHelper(new THREE.Vector3(0,0,1),new THREE.Vector3(0,0,6.67),22,0xffc66d,4,2);
  for(const arrow of [y,z]){arrow.traverse(node=>{if(node instanceof THREE.Mesh||node instanceof THREE.Line){
   const materials=Array.isArray(node.material)?node.material:[node.material];for(const material of materials){material.depthTest=false;material.transparent=true;}node.renderOrder=10;
  }});this.helpers.add(arrow);}
  this.yaw.add(this.helpers);this.update(request,performance.now());
 }
 matches(request:MotionRequest){return request.instanceId===this.request.instanceId&&request.modelVersionId===this.request.modelVersionId
  &&request.contentRevision===this.request.contentRevision&&request.sha256===this.request.sha256&&request.epoch===this.request.epoch;}
 update(request:MotionRequest,now:number){
  this.request=request;this.helpers.visible=request.axes;
  if(request.sample.seq!==this.lastSeq){this.clock.accept(request.sample,now);this.lastSeq=request.sample.seq;}
  if(!request.playing)this.clock.suspend();
 }
 step(now:number){
  const keepGoing=this.clock.step(now,this.request.playing);
  this.yaw.rotation.y=-THREE.MathUtils.degToRad(this.clock.yaw);
  this.rotor.quaternion.copy(this.saved[this.saved.length-1].quaternion).multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,0,1),this.clock.rotor));
  return keepGoing;
 }
 suspend(){this.clock.suspend();}
 dispose(){
  if(this.disposed)return;this.disposed=true;
  for(const saved of this.saved){const {node}=saved;saved.parent.add(node);node.position.copy(saved.position);node.quaternion.copy(saved.quaternion);
   node.scale.copy(saved.scale);node.matrix.copy(saved.matrix);node.matrixAutoUpdate=saved.auto;node.matrixWorldNeedsUpdate=true;}
  for(const saved of [...this.saved].sort((a,b)=>a.order-b.order)){const children=saved.parent.children;children.splice(children.indexOf(saved.node),1);children.splice(saved.order,0,saved.node);}
  this.yaw.removeFromParent();
  // ArrowHelper shares built-in geometries; only its per-instance materials are owned here.
  this.helpers.traverse(node=>{if(node instanceof THREE.Mesh||node instanceof THREE.Line){for(const material of Array.isArray(node.material)?node.material:[node.material])material.dispose();}});
 }
}
