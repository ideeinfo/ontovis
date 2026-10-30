import * as THREE from 'three';
import type {ProjectModelVersion} from './resourceTypes';

type MaterialChange={mesh:THREE.Mesh;original:THREE.Material|THREE.Material[];owned:THREE.Material[]};
const sourceIndex=(value:unknown):value is number=>Number.isSafeInteger(value)&&Number(value)>=0;
const shells=new Set(['tower','nacelle','rotor_cover']);

/** Temporary cabinet display for an instance clone. Shared cache materials stay untouched. */
export class SceneCabinetAppearance {
  private readonly root:THREE.Group;
  private readonly version:Pick<ProjectModelVersion,'modelVersionId'|'components'>;
  private changes:MaterialChange[]=[];
  private fadedOccluders=new Map<THREE.Mesh,Set<THREE.Material>>();
  private activeKey:string|null=null;
  private disposed=false;
  constructor(root:THREE.Group,version:Pick<ProjectModelVersion,'modelVersionId'|'components'>){this.root=root;this.version=version;}
  apply(componentKeys:readonly string[],color:string,isolate=false){
    if(this.disposed)return;
    const id=this.root.userData.sceneModelInstanceId,version=this.version.modelVersionId;
    const keys=new Set(componentKeys),components=this.version.components;
    if(!this.root.visible||typeof id!=='string'||!id||this.root.userData.ontoVisModelVersionId!==version||
      !keys.size||keys.size!==componentKeys.length||[...keys].some(key=>typeof key!=='string'||!key||
        components.filter(component=>component.componentKey===key).length!==1)){this.restore();return;}
    const key=JSON.stringify([[...keys].sort(),color,isolate]);if(key===this.activeKey)return;
    this.restore();
    const selected=new Set<THREE.Mesh>(),enclosing:THREE.Mesh[]=[],meshes:THREE.Mesh[]=[];
    this.root.traverse(node=>{
      if(node instanceof THREE.Mesh)meshes.push(node);
      if(!(node instanceof THREE.Mesh)||node.userData.sceneModelInstanceId!==id||node.userData.ontoVisModelVersionId!==version)return;
      const data=node.userData,component=components.find(item=>item.componentKey===data.ontoVisComponentKey);
      if(component&&keys.has(component.componentKey)&&(sourceIndex(data.ontoVisNodeIndex)&&component.nodeIndices.includes(data.ontoVisNodeIndex)||
        data.ontoVisProxySchematic===true&&component.geometryQuality==='proxy_schematic'&&component.nodeIndices.length===0))selected.add(node);
      // These source-node annotations are a teaching-model display hint, never engineering identity.
      if(sourceIndex(data.ontoVisNodeIndex)&&data.ontoVisProxySchematic!==true&&shells.has(data.component))enclosing.push(node);
    });
    if(!selected.size)return;
    for(const mesh of isolate?meshes:new Set([...selected,...enclosing])){
      const original=mesh.material,owned:THREE.Material[]=[],highlight=selected.has(mesh);
      const copy=(material:THREE.Material)=>{
        // Keep the surrounding assembly readable, including mesh parents of the selection.
        if(isolate&&!highlight){const value=material.clone();value.transparent=true;value.opacity=material.opacity*(shells.has(mesh.userData.component)?.11:.2);value.depthWrite=false;owned.push(value);return value;}
        if(!(material instanceof THREE.MeshStandardMaterial))return material;
        const value=material.clone();owned.push(value);
        if(highlight){value.emissive.set(color);value.emissiveIntensity=.25;}
        else {value.transparent=true;value.opacity=.2;value.depthWrite=false;}
        value.needsUpdate=true;return value;
      };
      const replacement=Array.isArray(original)?original.map(copy):copy(original);
      if(owned.length){mesh.material=replacement;this.changes.push({mesh,original,owned});if(!highlight)this.fadedOccluders.set(mesh,new Set(owned));}
    }
    this.activeKey=key;
  }
  isFadedOccluder(object:THREE.Object3D,materialIndex=0):boolean {
    if(!(object instanceof THREE.Mesh))return false;
    const material=Array.isArray(object.material)?object.material[materialIndex]:object.material;
    return this.fadedOccluders.get(object)?.has(material)===true;
  }
  restore(){
    for(const {mesh,original,owned} of this.changes){mesh.material=original;for(const material of owned)material.dispose();}
    this.changes=[];this.fadedOccluders.clear();this.activeKey=null;
  }
  dispose(){this.restore();this.disposed=true;}
}
