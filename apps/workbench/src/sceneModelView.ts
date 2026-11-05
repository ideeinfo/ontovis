import * as THREE from 'three';
import {modelSourceNode,modelSchematicKey} from './sceneResourceCache.ts';
import {MOTION_MERGED_SHA,MOTION_MODEL_SHA} from './simulatedMotion.ts';
import type {ProjectModelVersion} from './resourceTypes.ts';

export type ModelViewRequest={instanceId:string;modelVersionId:string;contentRevision:string;sha256:string;mode:'xray'|'exploded'};
export type ModelViewStatus='loading'|'ready'|'unavailable';

const range=(from:number,to:number)=>Array.from({length:to-from+1},(_,i)=>i+from);
const tu3000Shell=[12,13,14,75,...range(115,125),134,135];
const tu3000ExplodedGroups:{nodes:number[];offset:[number,number,number]}[]=[
  {nodes:[2],offset:[0,2,12]},{nodes:[15,16,...range(17,24)],offset:[0,3,5]},
  {nodes:range(25,31),offset:[0,5,0]},{nodes:range(45,52),offset:[0,5,-5]},
  {nodes:range(53,60),offset:[-4,3,-6]},{nodes:range(61,66),offset:[4,3,-9]},
  {nodes:tu3000Shell,offset:[0,10,0]},
];

function localMeshBounds(root:THREE.Object3D,mesh:THREE.Mesh) {
  mesh.geometry.computeBoundingBox();
  return (mesh.geometry.boundingBox||new THREE.Box3()).clone().applyMatrix4(
    new THREE.Matrix4().copy(root.matrixWorld).invert().multiply(mesh.matrixWorld));
}

/** Generic reversible model inspection (Forge-like bounding box dispersion). */
export class SceneModelView {
  private positions:{node:THREE.Object3D;position:THREE.Vector3}[]=[];
  private materials:{mesh:THREE.Mesh;original:THREE.Material|THREE.Material[]}[]=[];
  private owned=new Map<THREE.Material,THREE.Material>();
  private disposed=false;
  readonly request:ModelViewRequest;
  private focusNodes:THREE.Object3D[]=[];

  static create(root:THREE.Group,version:ProjectModelVersion,request:ModelViewRequest):SceneModelView|null{
    if(!['xray','exploded'].includes(request.mode)||version.sha256!==request.sha256||version.modelVersionId!==request.modelVersionId
      ||version.contentRevision!==request.contentRevision||root.userData.sceneModelInstanceId!==request.instanceId
      ||version.calibration?.state!=='verified'||version.sha256===MOTION_MODEL_SHA)return null;

    // Special exact mapping and hierarchy validation for TU-3000
    if(version.sha256===MOTION_MERGED_SHA){
      const nodes=new Map<number,THREE.Object3D>();let duplicate=false;
      root.traverse(node=>{const source=modelSourceNode(node);if(source){if(nodes.has(source.index))duplicate=true;nodes.set(source.index,node);}});
      if(duplicate||nodes.size!==184)return null;
      if(request.mode==='exploded'){
        if(nodes.get(1)?.parent!==nodes.get(0)||nodes.get(2)?.parent!==nodes.get(0))return null;
        for(let i=3;i<184;i++)if(nodes.get(i)?.parent!==nodes.get(i>=143&&i<=175?2:1))return null;
      }
      return new SceneModelView(root,version,request,nodes);
    }

    // A declared detailed representation permits a visual schematic, not an engineering mapping.
    if(version.representationType!=='detailed')return null;
    root.updateWorldMatrix(true,true);
    const totalBox=new THREE.Box3();
    root.traverse(node=>{if(node instanceof THREE.Mesh)totalBox.union(localMeshBounds(root,node));});
    if(totalBox.isEmpty())return null;
    const totalSize=totalBox.getSize(new THREE.Vector3());
    const hubThresholdY=totalBox.min.y+totalSize.y*0.62;

    const shellMeshes:THREE.Mesh[]=[];
    const rotorMeshes:THREE.Mesh[]=[];
    const internalMeshes:THREE.Mesh[]=[];
    const focusList:THREE.Object3D[]=[];

    root.traverse(node=>{
      if(!(node instanceof THREE.Mesh))return;
      const b=localMeshBounds(root,node);
      const c=b.getCenter(new THREE.Vector3());
      const s=b.getSize(new THREE.Vector3());
      const name=node.name.toLowerCase();

      // Tower / Base check: lower 62% of wind turbine
      if(c.y<hubThresholdY&&/tower|pole|base|ground|foundation/i.test(name)){
        return; // Fixed, do not disperse
      }
      focusList.push(node);

      // Nacelle Shell / Cover check
      if(/nacelle|shell|housing|cover|case|hood|canopy|cowl/i.test(name)||
         (c.y>=hubThresholdY&&s.x>totalSize.x*0.25&&s.z>totalSize.z*0.25&&!/blade|rotor|hub/i.test(name))){
        shellMeshes.push(node);
      } else if(/blade|rotor|hub|spinner|impeller/i.test(name)){
        rotorMeshes.push(node);
      } else if(c.y>=totalBox.min.y+totalSize.y*0.558){
        internalMeshes.push(node);
      }
    });

    // Exterior-only models without internal components cannot be exploded or inspected internally
    if(internalMeshes.length===0)return null;

    return new SceneModelView(root,version,request,undefined,{shellMeshes,rotorMeshes,internalMeshes,focusList,totalBox});
  }

  private constructor(root:THREE.Group,version:ProjectModelVersion,request:ModelViewRequest,nodesMap?:Map<number,THREE.Object3D>,genericData?:{shellMeshes:THREE.Mesh[];rotorMeshes:THREE.Mesh[];internalMeshes:THREE.Mesh[];focusList:THREE.Object3D[];totalBox:THREE.Box3}){
    this.request={...request};

    const faded=new Set<THREE.Mesh>();
    const fade=(node:THREE.Object3D)=>node.traverse(mesh=>{
      if(!(mesh instanceof THREE.Mesh)||faded.has(mesh))return;
      faded.add(mesh);
      this.materials.push({mesh,original:mesh.material});
      const copy=(source:THREE.Material)=>{
        let value=this.owned.get(source);
        if(!value){
          value=source.clone();
          value.transparent=true;
          value.opacity=.14;
          value.depthWrite=false;
          this.owned.set(source,value);
        }
        return value;
      };
      mesh.material=Array.isArray(mesh.material)?mesh.material.map(copy):copy(mesh.material);
    });

    if(version.sha256===MOTION_MERGED_SHA&&nodesMap){
      this.focusNodes=range(12,135).map(id=>nodesMap.get(id)!);
      if(request.mode==='xray'){
        for(const id of tu3000Shell){const n=nodesMap.get(id);if(n)fade(n);}
      } else {
        for(const group of tu3000ExplodedGroups){
          for(const id of group.nodes){
            const node=nodesMap.get(id)!;
            this.positions.push({node,position:node.position.clone()});
            node.position.add(new THREE.Vector3(...group.offset));
          }
        }
        root.traverse(node=>{
          if(modelSchematicKey(node)==='proxy:CN1'){
            this.positions.push({node,position:node.position.clone()});
            node.position.add(new THREE.Vector3(5,0,-2));
          }
        });
      }
      root.updateMatrixWorld(true);
      return;
    }

    if(genericData){
      const {shellMeshes,rotorMeshes,internalMeshes,focusList,totalBox}=genericData;
      const totalCenter=totalBox.getCenter(new THREE.Vector3());
      const totalSize=totalBox.getSize(new THREE.Vector3());
      this.focusNodes=focusList.length>0?focusList:[root];

      if(request.mode==='xray'){
        for(const mesh of shellMeshes)fade(mesh);
      } else {
        const offsets=new Map<THREE.Mesh,THREE.Vector3>();
        const liftY=Math.max(6,Math.min(12,totalSize.y*0.12));
        for(const mesh of shellMeshes)offsets.set(mesh,new THREE.Vector3(0,liftY,0));
        const pushZ=Math.max(8,Math.min(16,totalSize.z*0.15));
        for(const mesh of rotorMeshes)offsets.set(mesh,new THREE.Vector3(0,0,pushZ));
        const nacelleCenter=new THREE.Vector3(totalCenter.x,totalBox.max.y-totalSize.y*0.15,totalCenter.z);
        internalMeshes.forEach((mesh,index)=>{
          const c=localMeshBounds(root,mesh).getCenter(new THREE.Vector3());
          const dir=new THREE.Vector3(c.x-nacelleCenter.x,0,c.z-nacelleCenter.z);
          if(dir.lengthSq()<0.01)dir.set(Math.sin(index+1),0,Math.cos(index+1));
          offsets.set(mesh,dir.normalize().multiplyScalar(4.5).setY(((index%3)-1)*1.5));
        });
        // Capture world destinations before moving parents; then convert each into its parent's frame.
        const moves=[...offsets].map(([mesh,offset])=>({mesh,
          destination:root.localToWorld(root.worldToLocal(mesh.getWorldPosition(new THREE.Vector3())).add(offset)),
          depth:(()=>{let n:THREE.Object3D|null=mesh,d=0;while(n){d++;n=n.parent;}return d;})()}));
        moves.sort((a,b)=>a.depth-b.depth);
        for(const {mesh,destination} of moves){
          this.positions.push({node:mesh,position:mesh.position.clone()});
          mesh.parent?.updateWorldMatrix(true,false);
          mesh.position.copy(mesh.parent?mesh.parent.worldToLocal(destination):destination);
          mesh.updateWorldMatrix(false,true);
        }
      }
      root.updateMatrixWorld(true);
    }
  }

  focusBounds(){
    const box=new THREE.Box3();
    for(const node of this.focusNodes){
      node.updateWorldMatrix(true,true);
      box.union(new THREE.Box3().setFromObject(node));
    }
    return box;
  }

  matches(request:ModelViewRequest){return JSON.stringify(this.request)===JSON.stringify(request);}

  dispose(){
    if(this.disposed)return;
    this.disposed=true;
    for(const {node,position} of this.positions){
      node.position.copy(position);
      node.updateMatrix();
    }
    for(const {mesh,original} of this.materials)mesh.material=original;
    for(const material of this.owned.values())material.dispose();
    this.owned.clear();
    for(const {node} of this.positions)node.updateWorldMatrix(true,true);
  }
}
