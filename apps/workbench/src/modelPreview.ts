import * as THREE from 'three';
import {modelSourceNode,modelSchematicKey} from './sceneResourceCache.ts';
import {previewIdentity,type PreviewNode,type PreviewSelection,type PreviewStructure} from './modelPreviewTypes.ts';
import type {ProjectModelVersion} from './resourceTypes';
import type {Bounds3,Vector3} from './sceneTypes';

type Mesh=THREE.Mesh<THREE.BufferGeometry,THREE.Material|THREE.Material[]>;
type Entry={mesh:Mesh;original:Mesh['material'];visible:boolean;copies:THREE.Material[]|null};
const materials=(value:Mesh['material'])=>Array.isArray(value)?value:[value];
const mesh=(node:THREE.Object3D):node is Mesh=>node instanceof THREE.Mesh;
const bounds=(box:THREE.Box3):Bounds3|null=>box.isEmpty()?null:[box.min.toArray() as Vector3,box.max.toArray() as Vector3];
const visibleTo=(object:THREE.Object3D,root:THREE.Object3D)=>{let node:THREE.Object3D|null=object;
  while(node){if(!node.visible)return false;if(node===root)return true;node=node.parent;}return false;};

/** Preview-local materials and source hierarchy. No geometry/texture ownership or business writes. */
export class ModelPreviewInspection {
  readonly structure:PreviewStructure;
  private readonly entries:Entry[]=[];
  private readonly nodeMeshes=new Map<string,Set<Mesh>>();
  private readonly hitIds=new WeakMap<THREE.Object3D,string>();
  private selection:string|null=null;
  private appliedKey='';
  private disposed=false;
  private readonly root:THREE.Group;
  constructor(root:THREE.Group,version:ProjectModelVersion){
    this.root=root;
    const nodes:PreviewNode[]=[],roots:string[]=[],byId=new Map<string,PreviewNode>();
    const components=version.components??[],represented=new Set<string>();
    root.updateMatrixWorld(true);
    const walk=(object:THREE.Object3D,parentId:string|null)=>{
      const source=modelSourceNode(object),proxy=modelSchematicKey(object);
      let id=parentId;
      if(source||proxy!==undefined){
        id=source?`node:${source.index}`:`proxy:${proxy}`;
        const related=components.filter(c=>source?c.nodeIndices.includes(source.index):c.componentKey===proxy);
        related.forEach(c=>represented.add(c.componentKey));
        const name=source?.name||related[0]?.displayName||object.name||`#${source?.index??proxy}`;
        const node:PreviewNode={id,parentId,children:[],name,nodeIndex:source?.index??null,
          kind:source?'source':'proxy',componentKeys:related.map(c=>c.componentKey),
          path:[...(parentId?byId.get(parentId)!.path:[]),name],bounds:null,meshes:0,vertices:0,triangles:0,materials:[],
          translation:object.position.toArray() as Vector3,rotation:[object.rotation.x,object.rotation.y,object.rotation.z].map(THREE.MathUtils.radToDeg) as Vector3,
          scale:object.scale.toArray() as Vector3,attributes:source?.attributes??{}};
        nodes.push(node);byId.set(id,node);this.nodeMeshes.set(id,new Set());
        if(parentId)byId.get(parentId)!.children.push(id);else roots.push(id);
      }
      if(mesh(object)){
        this.entries.push({mesh:object,original:object.material,visible:object.visible,copies:null});
        if(id){this.hitIds.set(object,id);let ancestor:string|null=id;
          while(ancestor){this.nodeMeshes.get(ancestor)!.add(object);ancestor=byId.get(ancestor)!.parentId;}}
      }
      for(const child of object.children)walk(child,id);
    };
    walk(root,null);
    for(const node of nodes){
      const box=new THREE.Box3(),unique=new Set<THREE.Material>();
      for(const item of this.nodeMeshes.get(node.id)!){
        if(!visibleTo(item,root))continue;
        const position=item.geometry.getAttribute('position');if(!position)continue;
        node.meshes++;node.vertices+=position.count;
        node.triangles+=Math.floor((item.geometry.index?.count??position.count)/3);
        if(!item.geometry.boundingBox)item.geometry.computeBoundingBox();
        if(item.geometry.boundingBox)box.union(item.geometry.boundingBox.clone().applyMatrix4(item.matrixWorld));
        materials(item.material).forEach(material=>unique.add(material));
      }
      node.bounds=bounds(box);
      node.materials=[...unique].map(material=>({name:material.name,type:material.type,
        color:'color' in material&&material.color instanceof THREE.Color?`#${material.color.getHexString()}`:null,
        opacity:material.opacity,textured:'map' in material&&!!material.map}));
    }
    // Keep declared entries without geometry inspectable; never fabricate meshes for them.
    for(const component of components)if(!represented.has(component.componentKey)){
      const id=`metadata:${component.componentKey}`;
      roots.push(id);nodes.push({id,parentId:null,children:[],name:component.displayName,nodeIndex:null,kind:'metadata',
        componentKeys:[component.componentKey],path:[component.displayName],bounds:null,meshes:0,vertices:0,triangles:0,
        materials:[],translation:null,rotation:null,scale:null,attributes:{}});
    }
    this.structure={identity:previewIdentity(version),roots,nodes};
  }
  apply(value:PreviewSelection|null|undefined,color:string){
    if(this.disposed)return;
    const key=JSON.stringify([value?.identity,value?.nodeId,value?.display,color]);
    if(key===this.appliedKey)return;
    this.restore();
    if(value?.identity!==this.structure.identity||!value.nodeId)return;
    const selected=this.nodeMeshes.get(value.nodeId);
    if(!selected?.size||!this.structure.nodes.find(node=>node.id===value.nodeId)?.bounds)return;
    this.selection=value.nodeId;
    this.appliedKey=key;
    for(const entry of this.entries){
      const active=selected.has(entry.mesh);
      if(!entry.copies)entry.copies=materials(entry.original).map(material=>material.clone());
      entry.copies.forEach((copy,index)=>{
        const original=materials(entry.original)[index];copy.copy(original);
        if(active){if('emissive' in copy&&copy.emissive instanceof THREE.Color){copy.emissive.set(color);
          if('emissiveIntensity' in copy)copy.emissiveIntensity=.25;}}
        else if(value.display==='isolate')copy.visible=false;
        else{copy.transparent=true;copy.opacity=original.opacity*.18;copy.depthWrite=false;
          copy.alphaTest=original.alphaTest*.18;}
        copy.needsUpdate=true;
      });
      entry.mesh.material=Array.isArray(entry.original)?entry.copies:entry.copies[0];
    }
  }
  restore(){for(const entry of this.entries){entry.mesh.material=entry.original;entry.mesh.visible=entry.visible;}this.selection=null;this.appliedKey='';}
  pick(hits:THREE.Intersection[],identity:string):string|null{
    if(this.disposed||identity!==this.structure.identity)return null;
    const candidates=hits.filter(hit=>this.hitIds.has(hit.object)&&visibleTo(hit.object,this.root)
      &&materials((hit.object as Mesh).material)[hit.face?.materialIndex??0]?.visible);
    // A deliberately ghosted enclosing shell must not block its visible internal part.
    const enclosing=(hit:THREE.Intersection)=>{
      if(!this.selection||this.nodeMeshes.get(this.selection)?.has(hit.object as Mesh))return false;
      const id=this.hitIds.get(hit.object),node=this.structure.nodes.find(row=>row.id===id);
      return ['tower','nacelle','rotor_cover'].includes(String(node?.attributes.component??''));
    };
    const hit=candidates.find(item=>this.selection&&this.nodeMeshes.get(this.selection)?.has(item.object as Mesh))
      ??candidates.find(item=>!enclosing(item))??candidates[0];
    return hit?this.hitIds.get(hit.object)??null:null;
  }
  dispose(){if(this.disposed)return;this.restore();for(const entry of this.entries)for(const copy of entry.copies??[])copy.dispose();
    this.entries.length=0;this.nodeMeshes.clear();this.disposed=true;}
}
