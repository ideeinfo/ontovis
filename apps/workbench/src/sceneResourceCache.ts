/** Per-viewport/session resources. Clones borrow shared GPU data; only this cache disposes it. */
import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {ApiError, type WorkbenchApi} from './api.ts';
import {SceneApi} from './sceneApi.ts';
import type {ModelResourceRef} from './sceneTypes';
import type {ProjectModelVersion,TerrainArtifact,TerrainVersion} from './resourceTypes';

export interface CachedModel {version:ProjectModelVersion; scene:THREE.Group}
export interface SceneResourceSource {
  model(assetId:string,versionId:string,signal?:AbortSignal):Promise<ProjectModelVersion>;
  modelContent(version:ProjectModelVersion,signal?:AbortSignal):Promise<Blob>;
  version(terrainId:string,signal?:AbortSignal):Promise<TerrainVersion>;
  content(terrainId:string,artifact:TerrainArtifact,signal?:AbortSignal):Promise<Blob>;
}
export interface SceneResourceCacheOptions {
  source?:SceneResourceSource;
  parseModel?:(bytes:ArrayBuffer)=>Promise<THREE.Group>;
}
const MAX_MODEL_BYTES=20*1024*1024;
const MAX_VERTICES=501*501;
const MAX_TRIANGLES=500_000;
const SAMPLING_RULE='mesh-triangle-tr-bl-cell-mask-v2';
const parsedScenes=new WeakMap<THREE.Object3D,THREE.Group[]>();
const sourceNodeIndices=new WeakMap<THREE.Object3D,number>();
// Only cache-created boxes may provide schematic identities; GLB extras are untrusted.
const schematicProxyKeys=new WeakMap<THREE.Object3D,string>();
const shaValid=(value:unknown):value is string=>typeof value==='string' && /^[a-f0-9]{64}$/.test(value);
const text=(value:unknown):value is string=>typeof value==='string' && value.length>0 && value.length<=200;
const integer=(value:unknown):value is number=>typeof value==='number' && Number.isSafeInteger(value);
function requireValue(value:unknown,code='RESOURCE_CHANGED',status=409):asserts value {
  if(!value)throw new ApiError(status,code);
}
function abortError() {return new DOMException('Viewport or session changed','AbortError');}
async function sha256(bytes:ArrayBuffer) {
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),value=>value.toString(16).padStart(2,'0')).join('');
}
function checkRef(ref:ModelResourceRef) {
  requireValue(text(ref.modelAssetId),'MODEL_REFERENCE_REQUIRED',422);
  requireValue(text(ref.modelVersionId) && text(ref.contentRevision) && shaValid(ref.sha256));
}

/** Refuse external GLB dependencies before the loader has any chance to request them. */
function embeddedGlb(bytes:ArrayBuffer) {
  requireValue(bytes.byteLength>=24 && bytes.byteLength<=MAX_MODEL_BYTES,'MODEL_LIMIT_EXCEEDED',413);
  const view=new DataView(bytes);
  requireValue(view.getUint32(0,true)===0x46546c67 && view.getUint32(4,true)===2
    && view.getUint32(8,true)===bytes.byteLength && view.getUint32(16,true)===0x4e4f534a,'INVALID_MODEL',422);
  const length=view.getUint32(12,true);
  requireValue(length>0 && length%4===0 && 20+length<=bytes.byteLength,'INVALID_MODEL',422);
  let document:Record<string,unknown>;
  try {document=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(new Uint8Array(bytes,20,length)));}
  catch {throw new ApiError(422,'INVALID_MODEL');}
  requireValue(document && typeof document==='object' && !Array.isArray(document),'INVALID_MODEL',422);
  const absentOrEmpty=(value:unknown)=>value===undefined || Array.isArray(value) && value.length===0;
  requireValue(['animations','skins','extensionsUsed','extensionsRequired'].every(key=>absentOrEmpty(document[key])),'UNSUPPORTED_MODEL',422);
  for(const name of ['buffers','images']) {
    const entries=document[name] || [];
    requireValue(Array.isArray(entries),'INVALID_MODEL',422);
    for(const entry of entries)requireValue(entry && typeof entry==='object' && !Object.hasOwn(entry,'uri'),'UNSUPPORTED_MODEL',422);
  }
}

async function parseModel(bytes:ArrayBuffer) {
  const manager=new THREE.LoadingManager();
  manager.setURLModifier(url=>{requireValue(url.startsWith('blob:'),'UNSUPPORTED_MODEL',422);return url;});
  const loader=new GLTFLoader(manager);
  loader.register(parser=>({name:'ONTOVisNodeIndexCapture',loadNode(index){
    return parser.loadNode(index).then(node=>{
      // loadScene later prunes parser.associations, including nodes from other
      // scenes. Capture the actual association before that pruning takes place.
      const actual=parser.associations.get(node)?.nodes;
      requireValue(integer(actual)&&actual===index,'INVALID_MODEL',422);
      sourceNodeIndices.set(node,actual);return node;
    });
  }}));
  const gltf=await loader.parseAsync(bytes,'');
  parsedScenes.set(gltf.scene,gltf.scenes);return gltf.scene;
}

function calibrationMatrix(version:ProjectModelVersion) {
  const calibration=version.calibration;
  requireValue(version.canPlace && version.calibrationState===calibration.state && (calibration.state==='verified'||calibration.state==='legacy_display'),
    'MODEL_CALIBRATION_REQUIRED',422);
  requireValue(calibration.unit==='m' && calibration.axes==='Y_UP_RIGHT_HANDED','UNSUPPORTED_CALIBRATION',422);
  if(calibration.state==='legacy_display') {
    const identity=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1],matrix=calibration.modelToCalibrated;
    requireValue(version.canPlaceGeographic===false && Array.isArray(matrix) && matrix.length===16 && matrix.every((value,index)=>value===identity[index]),'INVALID_CALIBRATION',422);
    return new THREE.Matrix4().fromArray(matrix);
  }
  const base=calibration.basePoint,forward=calibration.forward,matrix=calibration.modelToCalibrated;
  requireValue(Array.isArray(base) && base.length===3 && Array.isArray(forward) && forward.length===3
    && [...base,...forward].every(value=>typeof value==='number' && Number.isFinite(value) && Math.abs(value)<=1e6)
    && forward[1]===0 && Math.hypot(forward[0],forward[2])>0,'INVALID_CALIBRATION',422);
  const length=Math.hypot(forward[0],forward[2]),cosine=-forward[2]/length,sine=forward[0]/length;
  const expected=[cosine,0,-sine,0,0,1,0,0,sine,0,cosine,0,
    -(cosine*base[0]+sine*base[2]),-base[1],sine*base[0]-cosine*base[2],1];
  requireValue(Array.isArray(matrix) && matrix.length===16 && matrix.every((value,index)=>
    typeof value==='number' && Number.isFinite(value) && Math.abs(value-expected[index])<=1e-8),'INVALID_CALIBRATION',422);
  return new THREE.Matrix4().fromArray(matrix);
}

function addSchematicProxies(scene:THREE.Group,version:ProjectModelVersion) {
  const components=version.components??[];requireValue(Array.isArray(components));
  const proxies=components.filter(component=>component?.geometryQuality==='proxy_schematic'
    &&Array.isArray(component.nodeIndices)&&component.nodeIndices.length===0).map(component=>{
    requireValue(typeof component.componentKey==='string'&&component.componentKey.length>0&&component.componentKey.length<=512);
    const box=component.bounds;
    requireValue(Array.isArray(box)&&box.length===2&&box.every(point=>Array.isArray(point)&&point.length===3
      &&point.every(value=>typeof value==='number'&&Number.isFinite(value)&&Math.abs(value)<=1e6))
      &&box[0].every((value,index)=>value<=box[1][index]));
    return {key:component.componentKey,box:new THREE.Box3(new THREE.Vector3(...box[0]),new THREE.Vector3(...box[1]))};
  });
  if(!proxies.length)return;
  const material=new THREE.MeshStandardMaterial({color:0x718275,roughness:.75});
  for(const {key,box} of proxies){
    const size=box.getSize(new THREE.Vector3()),mesh=new THREE.Mesh(new THREE.BoxGeometry(size.x,size.y,size.z),material);
    mesh.name=`schematic:${key}`;mesh.position.copy(box.getCenter(new THREE.Vector3()));
    schematicProxyKeys.set(mesh,key);scene.add(mesh);
  }
}

/** Selection helpers/material effects must stay outside this shared clone tree. */
export function cloneModel(resource:CachedModel,id:string,options:{calibrated?:boolean}={}) {
  requireValue(text(id),'INVALID_REQUEST',422);
  const wrapper=new THREE.Group();wrapper.name=`instance:${id}`;wrapper.userData.sceneModelInstanceId=id;
  wrapper.userData.ontoVisModelVersionId=resource.version.modelVersionId;
  const coordinate=new THREE.Group();coordinate.name='model-calibration';
  if(options.calibrated!==false) {coordinate.matrix.copy(calibrationMatrix(resource.version));coordinate.matrixAutoUpdate=false;}
  const clone=resource.scene.clone(true);
  const components=resource.version.components??[],byNode=new Map<number,string>(),keys=new Set<string>();
  requireValue(Array.isArray(components));
  for(const component of components){
    requireValue(component&&typeof component.componentKey==='string'&&component.componentKey.length>0
      &&component.componentKey.length<=512&&!keys.has(component.componentKey)&&Array.isArray(component.nodeIndices));
    keys.add(component.componentKey);
    for(const index of component.nodeIndices){
      requireValue(integer(index)&&index>=0&&(!byNode.has(index)||byNode.get(index)===component.componentKey));
      byNode.set(index,component.componentKey);
    }
  }
  const originals:THREE.Object3D[]=[],copies:THREE.Object3D[]=[];
  resource.scene.traverse(node=>originals.push(node));clone.traverse(node=>copies.push(node));
  requireValue(originals.length===copies.length);
  copies.forEach((node,index)=>{
    node.userData.sceneModelInstanceId=id;node.userData.ontoVisModelVersionId=resource.version.modelVersionId;
    delete node.userData.ontoVisComponentKey;delete node.userData.ontoVisNodeIndex;delete node.userData.ontoVisProxySchematic;
    const proxyKey=schematicProxyKeys.get(originals[index]);
    if(proxyKey!==undefined){node.userData.ontoVisComponentKey=proxyKey;node.userData.ontoVisProxySchematic=true;return;}
    let original:THREE.Object3D|null=originals[index];
    while(original){
      const sourceIndex=sourceNodeIndices.get(original);
      if(sourceIndex!==undefined){
        node.userData.ontoVisNodeIndex=sourceIndex;
        const key=byNode.get(sourceIndex);
        if(key!==undefined)node.userData.ontoVisComponentKey=key;
        break;
      }
      original=original.parent;
    }
  });
  coordinate.add(clone);wrapper.add(coordinate);return wrapper;
}

function terrainArtifacts(version:TerrainVersion) {
  requireValue(version.state==='ready' && text(version.terrainVersionId) && text(version.contentRevision)
    && shaValid(version.sha256) && shaValid(version.expectedReportSha256));
  const report=version.report,mesh=report?.mesh,frame=mesh?.frame;
  requireValue(report?.state==='ready' && report.schemaVersion===1 && report.source?.sha256===version.sha256
    && report.source.heightUnit==='m' && mesh.heightExaggeration===1 && mesh.placementSamplingRule===SAMPLING_RULE);
  requireValue(integer(mesh.rows) && integer(mesh.columns) && mesh.rows>=2 && mesh.rows<=501
    && mesh.columns>=2 && mesh.columns<=501 && mesh.vertices===mesh.rows*mesh.columns && mesh.vertices<=MAX_VERTICES
    && integer(mesh.triangles) && mesh.triangles>0 && mesh.triangles<=MAX_TRIANGLES && mesh.triangles%2===0,
    'TERRAIN_LIMIT_EXCEEDED',413);
  requireValue(frame?.mode==='projected_site' && frame.isStrictEnu===false && frame.displayAxes==='X_GRID_EAST_Y_UP_Z_GRID_SOUTH'
    && frame.verticalDatum===report.source.verticalDatum && [frame.originEasting,frame.originNorthing,frame.originHeight].every(Number.isFinite));
  const match=/^EPSG:(326|327)(\d{2})$/.exec(frame.horizontalCrs);
  requireValue(match && Number(match[2])>=1 && Number(match[2])<=60,'UNSUPPORTED_CRS',422);
  requireValue(Array.isArray(report.artifacts) && Array.isArray(version.artifacts));
  const fixed=new Map<string,TerrainArtifact>(),publicEntries=new Map<string,TerrainArtifact>();
  for(const item of report.artifacts) {
    requireValue(item && text(item.artifactId) && !fixed.has(item.artifactId) && shaValid(item.sha256) && integer(item.bytes) && item.bytes>0);
    fixed.set(item.artifactId,item);
  }
  for(const item of version.artifacts) {
    requireValue(item && text(item.artifactId) && !publicEntries.has(item.artifactId));publicEntries.set(item.artifactId,item);
  }
  const sizes:Record<string,number>={'heights.f64':mesh.vertices*8,'mask.u8':mesh.vertices,
    'cells.u8':(mesh.rows-1)*(mesh.columns-1),'positions.f32':mesh.vertices*12,'triangles.u32':mesh.triangles*12};
  requireValue(fixed.size===5 && Object.entries(sizes).every(([id,bytes])=>fixed.get(id)?.bytes===bytes));
  requireValue(publicEntries.size===6 && publicEntries.get('source.tif')?.sha256===version.sha256
    && publicEntries.get('source.tif')?.bytes===report.source.bytes);
  const positions=fixed.get('positions.f32'),triangles=fixed.get('triangles.u32');
  requireValue(positions && triangles && positions.bytes===mesh.vertices*12 && triangles.bytes===mesh.triangles*12);
  for(const item of fixed.values()) {
    const publicItem=publicEntries.get(item.artifactId);
    requireValue(publicItem && publicItem.bytes===item.bytes && publicItem.sha256===item.sha256);
  }
  return {positions,triangles};
}

/** Decode only the server's fixed visible faces. Never fill a missing cell. */
export async function decodeTerrain(version:TerrainVersion,positionsBytes:ArrayBuffer,triangleBytes:ArrayBuffer) {
  const artifacts=terrainArtifacts(version),mesh=version.report.mesh;
  requireValue(positionsBytes.byteLength===artifacts.positions.bytes && triangleBytes.byteLength===artifacts.triangles.bytes);
  requireValue(await sha256(positionsBytes)===artifacts.positions.sha256 && await sha256(triangleBytes)===artifacts.triangles.sha256);
  const positions=new Float32Array(mesh.vertices*3),indices=new Uint32Array(mesh.triangles*3);
  const points=new DataView(positionsBytes),faces=new DataView(triangleBytes);
  for(let index=0;index<positions.length;index++) {
    const value=points.getFloat32(index*4,true);requireValue(Number.isFinite(value),'INVALID_TERRAIN',422);positions[index]=value;
  }
  for(let index=0;index<indices.length;index++) {
    const value=faces.getUint32(index*4,true);requireValue(value<mesh.vertices,'INVALID_TERRAIN',422);indices[index]=value;
  }
  for(let index=0;index<indices.length;index+=3)requireValue(indices[index]!==indices[index+1] && indices[index]!==indices[index+2]
    && indices[index+1]!==indices[index+2],'INVALID_TERRAIN',422);
  const geometry=new THREE.BufferGeometry();
  geometry.setAttribute('position',new THREE.BufferAttribute(positions,3));geometry.setIndex(new THREE.BufferAttribute(indices,1));
  geometry.computeVertexNormals();
  // Missing vertices can carry a zero placeholder; only indexed surface points affect fitting/culling.
  const bounds=new THREE.Box3(),point=new THREE.Vector3();
  for(const index of indices)bounds.expandByPoint(point.fromArray(positions,index*3));
  geometry.boundingBox=bounds;
  const sphere=new THREE.Sphere(bounds.getCenter(new THREE.Vector3()),0);
  for(const index of indices)sphere.radius=Math.max(sphere.radius,sphere.center.distanceTo(point.fromArray(positions,index*3)));
  geometry.boundingSphere=sphere;return geometry;
}

export class SceneResourceCache {
  private readonly api:WorkbenchApi;
  private readonly source:SceneResourceSource;
  private readonly parse:(bytes:ArrayBuffer)=>Promise<THREE.Group>;
  private readonly epoch:number;
  private readonly revision:string;
  private readonly abort=new AbortController();
  private readonly models=new Map<string,Promise<CachedModel>>();
  private readonly terrains=new Map<string,Promise<THREE.BufferGeometry>>();
  private readonly roots=new Set<THREE.Group>();
  private readonly geometries=new Set<THREE.BufferGeometry>();
  private readonly released=new Set<object>();
  constructor(api:WorkbenchApi,options:SceneResourceCacheOptions={}) {
    this.api=api;this.source=options.source || new SceneApi(api);this.parse=options.parseModel || parseModel;
    this.epoch=api.epoch;this.revision=api.revision;
  }
  private guard(signal?:AbortSignal) {
    if(this.api.epoch!==this.epoch || this.api.revision!==this.revision)this.dispose();
    if(this.abort.signal.aborted || signal?.aborted)throw abortError();
  }
  private consume<T>(promise:Promise<T>,signal?:AbortSignal):Promise<T> {
    this.guard(signal);
    return new Promise((resolve,reject)=>{
      const cancelled=()=>{signal?.removeEventListener('abort',cancelled);reject(abortError());};
      signal?.addEventListener('abort',cancelled,{once:true});
      promise.then(value=>{signal?.removeEventListener('abort',cancelled);try {this.guard(signal);resolve(value);} catch(error) {reject(error);}},
        error=>{signal?.removeEventListener('abort',cancelled);reject(error);});
    });
  }
  model(ref:ModelResourceRef,signal?:AbortSignal):Promise<CachedModel> {
    try {this.guard(signal);checkRef(ref);} catch(error) {return Promise.reject(error);}
    const key=JSON.stringify([ref.modelAssetId,ref.modelVersionId,ref.contentRevision,ref.sha256]);
    let pending=this.models.get(key);
    if(!pending) {
      pending=this.loadModel(ref).catch(error=>{this.models.delete(key);throw error;});this.models.set(key,pending);
    }
    return this.consume(pending,signal);
  }
  private async loadModel(ref:ModelResourceRef):Promise<CachedModel> {
    const version=await this.source.model(ref.modelAssetId!,ref.modelVersionId,this.abort.signal);this.guard();
    requireValue(version.modelAssetId===ref.modelAssetId && version.modelVersionId===ref.modelVersionId
      && version.contentRevision===ref.contentRevision && version.sha256===ref.sha256 && version.state==='ready'
      && integer(version.bytes) && version.bytes>=24 && version.bytes<=MAX_MODEL_BYTES);
    const blob=await this.source.modelContent(version,this.abort.signal);this.guard();
    const bytes=await blob.arrayBuffer();this.guard();
    requireValue(bytes.byteLength===version.bytes && await sha256(bytes)===ref.sha256);this.guard();embeddedGlb(bytes);
    const scene=await this.parse(bytes);
    try {this.guard();addSchematicProxies(scene,version);} catch(error) {this.releaseObject(scene);throw error;}
    this.roots.add(scene);return {version,scene};
  }
  terrain(version:TerrainVersion,signal?:AbortSignal):Promise<THREE.BufferGeometry> {
    try {this.guard(signal);terrainArtifacts(version);} catch(error) {return Promise.reject(error);}
    const key=JSON.stringify([version.terrainVersionId,version.contentRevision,version.sha256,version.expectedReportSha256]);
    let pending=this.terrains.get(key);
    if(!pending) {
      pending=this.loadTerrain(version).catch(error=>{this.terrains.delete(key);throw error;});this.terrains.set(key,pending);
    }
    return this.consume(pending,signal);
  }
  private async loadTerrain(reference:TerrainVersion) {
    const version=await this.source.version(reference.terrainVersionId,this.abort.signal);this.guard();
    requireValue(version.terrainVersionId===reference.terrainVersionId && version.contentRevision===reference.contentRevision
      && version.sha256===reference.sha256 && version.expectedReportSha256===reference.expectedReportSha256);
    const artifacts=terrainArtifacts(version);
    const blobs=await Promise.all([this.source.content(version.terrainVersionId,artifacts.positions,this.abort.signal),
      this.source.content(version.terrainVersionId,artifacts.triangles,this.abort.signal)]);this.guard();
    const bytes=await Promise.all(blobs.map(blob=>blob.arrayBuffer()));this.guard();
    const geometry=await decodeTerrain(version,bytes[0],bytes[1]);
    try {this.guard();} catch(error) {this.release(geometry);throw error;}
    this.geometries.add(geometry);return geometry;
  }
  private release(value:{dispose:()=>void}) {if(!this.released.has(value)) {this.released.add(value);value.dispose();}}
  private releaseObject(root:THREE.Object3D) {
    for(const source of parsedScenes.get(root) || [root])source.traverse(node=>{
      if(!(node instanceof THREE.Mesh || node instanceof THREE.Line || node instanceof THREE.Points))return;
      this.release(node.geometry);
      for(const material of Array.isArray(node.material)?node.material:[node.material]) {
        for(const value of Object.values(material))if(value instanceof THREE.Texture) {
          const image=value.image as {close?:()=>void}|null;
          if(image && typeof image.close==='function' && !this.released.has(image)) {this.released.add(image);image.close();}
          this.release(value);
        }
        this.release(material);
      }
    });
  }
  dispose() {
    this.abort.abort();
    for(const root of this.roots)this.releaseObject(root);
    for(const geometry of this.geometries)this.release(geometry);
    this.roots.clear();this.geometries.clear();this.models.clear();this.terrains.clear();
  }
}
