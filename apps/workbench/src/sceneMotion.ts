import * as THREE from 'three';
import {modelSourceNode,modelSchematicKey} from './sceneResourceCache.ts';
import {motionProfile,SimulatedMotionClock,type MotionRequest} from './simulatedMotion.ts';
import type {ProjectModelVersion} from './resourceTypes.ts';
import type {MotionProfile} from './motionProfiles.ts';

type Saved={node:THREE.Object3D;parent:THREE.Object3D;order:number;position:THREE.Vector3;quaternion:THREE.Quaternion;scale:THREE.Vector3;matrix:THREE.Matrix4;auto:boolean};
/** Operates on one clone only; fixed source-node identity comes from the GLTF parser. */
export class SceneMotion {
 private yaw=new THREE.Group();private helpers=new THREE.Group();private rotor:THREE.Object3D;
 private saved:Saved[]=[];private clock:SimulatedMotionClock;private request:MotionRequest;
 private disposed=false;private lastSeq=-1;
 private rotorQuaternion:THREE.Quaternion;private ownedRotor:boolean;
 private turn=new THREE.Quaternion();private axis=new THREE.Vector3(0,0,1);
 static create(root:THREE.Group,version:ProjectModelVersion,request:MotionRequest):SceneMotion|null {
  const profile=motionProfile(version.sha256);
  if(!profile||request.sha256!==version.sha256||request.modelVersionId!==version.modelVersionId||request.contentRevision!==version.contentRevision
   ||root.userData.sceneModelInstanceId!==request.instanceId||version.calibration.state!=='verified')return null;
  const nodes=new Map<number,THREE.Object3D>();let duplicate=false;
  root.traverse(node=>{const source=modelSourceNode(node);if(source){if(nodes.has(source.index))duplicate=true;nodes.set(source.index,node);}});
  if(duplicate||nodes.size!==profile.nodes)return null;
  const base=nodes.get(0),fixed=nodes.get(1),rotor=nodes.get(2);
  if(!base||!fixed||!rotor||fixed.parent!==base||rotor.parent!==base
   ||rotor.position.distanceTo(profile.layout==='grouped'?new THREE.Vector3(0,profile.hubHeight,profile.rotorZ):new THREE.Vector3())>1e-5)return null;
  for(let i=3;i<profile.nodes;i++)if(nodes.get(i)?.parent!==(profile.layout==='grouped'&&i>=profile.rotorStart&&i<=profile.rotorEnd?rotor:fixed))return null;
  const schematic:THREE.Object3D[]=[];
  root.traverse(node=>{if(modelSchematicKey(node)==='proxy:CN1')schematic.push(node);});
  const moving=Array.from({length:profile.movingEnd-profile.movingStart+1},(_,i)=>nodes.get(i+profile.movingStart)!);
  const rotorParts=profile.layout==='baked'?Array.from({length:profile.rotorEnd-profile.rotorStart+1},(_,i)=>nodes.get(i+profile.rotorStart)!):[];
  return new SceneMotion(base,rotor,[...moving,...schematic],rotorParts,profile,request);
 }
 private constructor(base:THREE.Object3D,rotor:THREE.Object3D,moving:THREE.Object3D[],rotorParts:THREE.Object3D[],profile:MotionProfile,request:MotionRequest){
  this.ownedRotor=profile.layout==='baked';this.rotor=this.ownedRotor?new THREE.Group():rotor;this.rotorQuaternion=this.rotor.quaternion.clone();
  this.request=request;this.clock=new SimulatedMotionClock(request.epoch);this.clock.rotor=request.initialPhase??0;this.clock.yaw=request.initialYaw??0;
  this.saved=[...moving,...(this.ownedRotor?rotorParts:[rotor])].map(node=>({node,parent:node.parent!,order:node.parent!.children.indexOf(node),position:node.position.clone(),
   quaternion:node.quaternion.clone(),scale:node.scale.clone(),matrix:node.matrix.clone(),auto:node.matrixAutoUpdate}));
  this.yaw.name='ONTOVis simulated yaw';this.yaw.position.set(0,profile.hubHeight,0);base.add(this.yaw);base.updateWorldMatrix(true,true);
  for(const node of moving)this.yaw.attach(node);
  if(this.ownedRotor){this.rotor.name='ONTOVis simulated rotor';this.rotor.position.set(0,0,profile.rotorZ);this.yaw.add(this.rotor);this.yaw.updateWorldMatrix(true,true);for(const node of rotorParts)this.rotor.attach(node);}
  else this.yaw.attach(rotor);
  const y=new THREE.ArrowHelper(new THREE.Vector3(0,1,0),new THREE.Vector3(),20,0x35dcc9,4,2);
  const z=new THREE.ArrowHelper(new THREE.Vector3(0,0,1),new THREE.Vector3(0,0,profile.rotorZ),22,0xffc66d,4,2);
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
  const keepGoing=this.clock.step(now,this.request.playing,this.request.yawRate??30);
  this.yaw.rotation.y=-THREE.MathUtils.degToRad(this.clock.yaw);
  this.rotor.quaternion.copy(this.rotorQuaternion).multiply(this.turn.setFromAxisAngle(this.axis,this.clock.rotor));
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

/** Independent clone drivers: inspecting one model never stops the rest of the scene. */
export class SceneMotionBatch {
 private drivers=new Map<string,{root:THREE.Group;driver:SceneMotion}>();
 private refused=new Map<string,string>();
 clear(id?:string){
  for(const [key,value] of this.drivers)if(!id||key===id){value.driver.dispose();this.drivers.delete(key);}
  if(id)this.refused.delete(id);else this.refused.clear();
 }
 sync(entries:Map<string,{root:THREE.Group;version:ProjectModelVersion}>,requests:MotionRequest[],now:number){
  const wanted=new Set(requests.map(r=>r.instanceId)),status:Record<string,'ready'|'unavailable'|'loading'>={};
  for(const id of this.drivers.keys())if(!wanted.has(id))this.clear(id);
  for(const request of requests){
   const id=request.instanceId,entry=entries.get(id);if(!entry?.root.visible){this.clear(id);status[id]='loading';continue;}
   const existing=this.drivers.get(id);if(existing&&(existing.root!==entry.root||!existing.driver.matches(request)))this.clear(id);
   if(!this.drivers.has(id)){
    const key=JSON.stringify([entry.root.uuid,request.modelVersionId,request.sha256,request.contentRevision,request.epoch]);
    const driver=this.refused.get(id)===key?null:SceneMotion.create(entry.root,entry.version,request);
    if(!driver){this.refused.set(id,key);status[id]='unavailable';continue;}
    this.drivers.set(id,{root:entry.root,driver});
   }
   this.drivers.get(id)!.driver.update(request,now);status[id]='ready';
  }
  return status;
 }
 step(now:number){let playing=false;for(const {driver} of this.drivers.values())playing=driver.step(now)||playing;return playing;}
 get size(){return this.drivers.size;}
 has(id:string){return this.drivers.has(id);}
}
