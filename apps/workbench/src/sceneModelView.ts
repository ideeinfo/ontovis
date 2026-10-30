import * as THREE from 'three';
import {modelSourceNode,modelSchematicKey} from './sceneResourceCache.ts';
import {MOTION_MERGED_SHA} from './simulatedMotion.ts';
import type {ProjectModelVersion} from './resourceTypes.ts';
export type ModelViewRequest={instanceId:string;modelVersionId:string;contentRevision:string;sha256:string;mode:'xray'|'exploded'};
export type ModelViewStatus='loading'|'ready'|'unavailable';
const range=(from:number,to:number)=>Array.from({length:to-from+1},(_,i)=>i+from);
const shell=[12,13,14,75,...range(115,125),134,135];
const explodedGroups:{nodes:number[];offset:[number,number,number]}[]=[
 {nodes:[2],offset:[0,10,35]},{nodes:[15,16,...range(17,24)],offset:[0,10,18]},
 {nodes:range(25,31),offset:[0,20,0]},{nodes:range(45,52),offset:[0,20,-16]},
 {nodes:range(53,60),offset:[-12,10,-18]},{nodes:range(61,66),offset:[12,10,-26]},
 {nodes:shell,offset:[0,35,0]},
];
/** A reversible teaching-model inspection. No disassembly procedure is inferred. */
export class SceneModelView {
 private positions:{node:THREE.Object3D;position:THREE.Vector3}[]=[];
 private materials:{mesh:THREE.Mesh;original:THREE.Material|THREE.Material[]}[]=[];
 private owned=new Map<THREE.Material,THREE.Material>();private disposed=false;
 readonly request:ModelViewRequest;
 private focusNodes:THREE.Object3D[]=[];
 static create(root:THREE.Group,version:ProjectModelVersion,request:ModelViewRequest){
  if(!['xray','exploded'].includes(request.mode)||version.sha256!==MOTION_MERGED_SHA||request.sha256!==version.sha256||request.modelVersionId!==version.modelVersionId
   ||request.contentRevision!==version.contentRevision||root.userData.sceneModelInstanceId!==request.instanceId||version.calibration.state!=='verified')return null;
  const nodes=new Map<number,THREE.Object3D>();let duplicate=false;root.traverse(node=>{const source=modelSourceNode(node);if(source){if(nodes.has(source.index))duplicate=true;nodes.set(source.index,node);}});
  if(duplicate||nodes.size!==184||nodes.get(1)?.parent!==nodes.get(0)||nodes.get(2)?.parent!==nodes.get(0))return null;
  for(let i=3;i<184;i++)if(nodes.get(i)?.parent!==nodes.get(i>=143&&i<=175?2:1))return null;
  return new SceneModelView(root,nodes,request);
 }
 private constructor(root:THREE.Group,nodes:Map<number,THREE.Object3D>,request:ModelViewRequest){
  this.request={...request};this.focusNodes=range(12,135).map(id=>nodes.get(id)!);
  const fade=(node:THREE.Object3D)=>node.traverse(mesh=>{if(!(mesh instanceof THREE.Mesh))return;
   this.materials.push({mesh,original:mesh.material});
   const copy=(source:THREE.Material)=>{let value=this.owned.get(source);if(!value){value=source.clone();value.transparent=true;value.opacity=.14;value.depthWrite=false;this.owned.set(source,value);}return value;};
   mesh.material=Array.isArray(mesh.material)?mesh.material.map(copy):copy(mesh.material);
  });
  if(request.mode==='xray')for(const id of shell)fade(nodes.get(id)!);
  else {for(const group of explodedGroups)for(const id of group.nodes){const node=nodes.get(id)!;this.positions.push({node,position:node.position.clone()});node.position.add(new THREE.Vector3(...group.offset));}
   root.traverse(node=>{if(modelSchematicKey(node)==='proxy:CN1'){this.positions.push({node,position:node.position.clone()});node.position.add(new THREE.Vector3(16,0,-5));}});
  }
  root.updateMatrixWorld(true);
 }
 focusBounds(){const box=new THREE.Box3();for(const node of this.focusNodes){node.updateWorldMatrix(true,true);box.union(new THREE.Box3().setFromObject(node));}return box;}
 matches(request:ModelViewRequest){return JSON.stringify(this.request)===JSON.stringify(request);}
 dispose(){if(this.disposed)return;this.disposed=true;for(const {node,position} of this.positions){node.position.copy(position);node.updateMatrix();}
  for(const {mesh,original} of this.materials)mesh.material=original;for(const material of this.owned.values())material.dispose();this.owned.clear();}
}
