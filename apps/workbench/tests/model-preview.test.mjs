import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import test from 'node:test';
import * as THREE from 'three';
import {WorkbenchApi} from '../src/api.ts';
import {SceneResourceCache,cloneModel,modelSourceNode} from '../src/sceneResourceCache.ts';
import {ModelPreviewInspection} from '../src/modelPreview.ts';
import {previewIdentity} from '../src/modelPreviewTypes.ts';

const digest=bytes=>createHash('sha256').update(new Uint8Array(bytes)).digest('hex');
function glb(change=()=>{}) {
  const positions=new Float32Array([0,0,0,1,0,0,0,1,0]);
  const document={asset:{version:'2.0'},scene:0,scenes:[{nodes:[0,1]}],
    nodes:[{name:'A',mesh:0},{name:'B',mesh:0,translation:[2,0,0]}],
    meshes:[{primitives:[{attributes:{POSITION:0},material:0}]}],materials:[{pbrMetallicRoughness:{baseColorFactor:[.4,.5,.4,1]}}],
    buffers:[{byteLength:positions.byteLength}],bufferViews:[{buffer:0,byteLength:positions.byteLength}],
    accessors:[{bufferView:0,componentType:5126,type:'VEC3',count:3,min:[0,0,0],max:[1,1,0]}],animations:[],skins:[]};
  change(document);
  let json=new TextEncoder().encode(JSON.stringify(document));
  const padded=new Uint8Array(Math.ceil(json.length/4)*4);padded.fill(32);padded.set(json);json=padded;
  const result=new ArrayBuffer(12+8+json.length+8+positions.byteLength),view=new DataView(result);
  view.setUint32(0,0x46546c67,true);view.setUint32(4,2,true);view.setUint32(8,result.byteLength,true);
  view.setUint32(12,json.length,true);view.setUint32(16,0x4e4f534a,true);new Uint8Array(result,20,json.length).set(json);
  const offset=20+json.length;view.setUint32(offset,positions.byteLength,true);view.setUint32(offset+4,0x004e4942,true);
  new Uint8Array(result,offset+8).set(new Uint8Array(positions.buffer));return result;
}
function modelFixture(bytes=glb()) {
  const version={modelAssetId:'fixture-asset',modelVersionId:'fixture-version',contentRevision:'content:1',
    displayName:'Synthetic GLB',sha256:digest(bytes),bytes:bytes.byteLength,state:'ready',calibrationState:'verified',canPlace:true,
    calibration:{state:'verified',unit:'m',axes:'Y_UP_RIGHT_HANDED',basePoint:[10,2,-3],forward:[0,0,-1],
      modelToCalibrated:[1,0,0,0,0,1,0,0,0,0,1,0,-10,-2,3,1],verifiedBy:'fixture',verifiedAt:'fixture'},
    report:{animations:0,externalResourcesFetched:0}};
  const ref={modelAssetId:version.modelAssetId,modelVersionId:version.modelVersionId,contentRevision:version.contentRevision,sha256:version.sha256};
  const calls={model:0,modelContent:0,version:0,content:0};
  const source={async model(){calls.model++;return version;},async modelContent(){calls.modelContent++;return new Blob([bytes]);},
    async version(){throw Error('Unused terrain metadata');},async content(){throw Error('Unused terrain bytes');}};
  const api=new WorkbenchApi();api.session('fixture-session');return {bytes,version,ref,source,calls,api};
}
const meshList=root=>{const result=[];root.traverse(node=>{if(node instanceof THREE.Mesh)result.push(node);});return result;};
const component=(key,nodeIndices,quality='source_candidate')=>({componentKey:key,displayName:key,nodeIndices,
  geometryQuality:quality,bounds:[[0,0,0],[1,1,1]]});
const choice=(inspection,id,display='context')=>({identity:inspection.structure.identity,nodeId:id,display,focusToken:1});
async function fixture(change=()=>{}){
  const f=modelFixture(glb(change)),cache=new SceneResourceCache(f.api,{source:f.source});
  const resource=await cache.model(f.ref),root=cloneModel(resource,'preview',{calibrated:false});
  return {...f,cache,resource,root,inspection:new ModelPreviewInspection(root,f.version)};
}

test('source hierarchy, original names, transforms, groups and safe identities survive parsing and cloning',async()=>{
  const f=await fixture(d=>{d.scenes[0].nodes=[2];d.nodes.push({name:'Assembly [source]',children:[0,1],translation:[0,5,0]});
    d.nodes[0].name='Rotor #A';d.nodes[0].extras={component:'rotor',manufacturer:'Source example',ontoVisNodeIndex:99};});
  const {nodes,roots,identity}=f.inspection.structure;
  assert.equal(identity,previewIdentity(f.version));assert.deepEqual(roots,['node:2']);
  const group=nodes.find(n=>n.id==='node:2'),a=nodes.find(n=>n.id==='node:0');
  assert.equal(group.name,'Assembly [source]');assert.deepEqual(group.children,['node:0','node:1']);
  assert.deepEqual(group.translation,[0,5,0]);assert.equal(group.meshes,2);assert.equal(group.triangles,2);
  assert.deepEqual(group.bounds,[[0,5,0],[3,6,0]]);assert.equal(a.nodeIndex,0);
  assert.deepEqual(a.path,['Assembly [source]','Rotor #A']);assert.deepEqual(a.bounds,[[0,5,0],[1,6,0]]);
  assert.equal(a.attributes.manufacturer,'Source example');assert.equal(a.materials.length,1);
  assert.equal(meshList(f.root)[0].userData.ontoVisNodeIndex,0,'Forged extras cannot supply preview identity');
  assert.equal(modelSourceNode(meshList(f.resource.scene)[0]).index,0);
  f.inspection.dispose();f.cache.dispose();
});

test('ghosting every other part leaves source, textures and other instances untouched; exact originals restore',async()=>{
  const f=await fixture(),parts=meshList(f.root),originals=parts.map(m=>m.material),other=cloneModel(f.resource,'second',{calibrated:false});
  const texture=new THREE.Texture();originals[0].map=texture;originals[0].alphaTest=.5;
  f.inspection.apply(choice(f.inspection,'node:1'),'#007e6d');
  assert.notEqual(parts[0].material,originals[0]);assert.equal(parts[0].material.opacity,.18);
  assert.equal(parts[0].material.depthWrite,false);assert.equal(parts[0].material.alphaTest,.09);
  assert.equal(parts[0].material.map,texture);assert.equal(parts[1].material.emissiveIntensity,.25);
  assert.ok(meshList(other).every((m,i)=>m.material===originals[i]));
  assert.ok(meshList(f.resource.scene).every(m=>m.material.opacity===1));
  f.inspection.apply(choice(f.inspection,'node:0'),'#007e6d');
  assert.equal(parts[0].material.opacity,1);assert.equal(parts[1].material.opacity,.18);
  f.inspection.restore();assert.ok(parts.every((m,i)=>m.material===originals[i]&&m.visible));
  assert.equal(f.calls.modelContent,1);f.inspection.dispose();f.cache.dispose();
});

test('isolation suppresses parent mesh geometry while preserving a selected child mesh and visible picking',async()=>{
  const f=await fixture(d=>{d.scenes[0].nodes=[0];d.nodes[0].children=[1];}),parts=meshList(f.root);
  f.inspection.apply(choice(f.inspection,'node:1','isolate'),'#007e6d');
  assert.equal(parts[0].visible,true,'Hiding the parent Object3D would also hide the selected child');
  assert.equal(parts[0].material.visible,false);assert.equal(parts[1].material.visible,true);
  const hits=[{object:parts[0],distance:1},{object:parts[1],distance:2}];
  assert.equal(f.inspection.pick(hits,f.inspection.structure.identity),'node:1');
  f.inspection.restore();assert.equal(parts[0].material.visible,true);
  assert.equal(f.inspection.pick(hits,f.inspection.structure.identity),'node:0');
  f.inspection.dispose();f.cache.dispose();
});

test('real raycasting cross-selects source parts, selected internals through ghost shells, with version and visibility fences',async()=>{
  const f=await fixture(d=>{d.nodes[0].extras={component:'nacelle'};d.nodes[1].translation=[0,0,-1];});
  const ray=new THREE.Raycaster(new THREE.Vector3(.2,.2,3),new THREE.Vector3(0,0,-1));
  f.root.updateMatrixWorld(true);let hits=ray.intersectObject(f.root,true);
  assert.equal(f.inspection.pick(hits,f.inspection.structure.identity),'node:0');
  f.inspection.apply(choice(f.inspection,'node:1'),'#007e6d');
  assert.equal(f.inspection.pick(hits,f.inspection.structure.identity),'node:1');
  assert.equal(f.inspection.pick(hits,'different-version'),null);
  f.root.visible=false;assert.equal(f.inspection.pick(hits,f.inspection.structure.identity),null);f.root.visible=true;
  const unrelated=new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshBasicMaterial());unrelated.userData.ontoVisNodeIndex=0;
  assert.equal(f.inspection.pick([{object:unrelated}],f.inspection.structure.identity),null);
  unrelated.geometry.dispose();unrelated.material.dispose();f.inspection.dispose();f.cache.dispose();
});

test('empty source nodes and unrepresented component metadata retain properties without ghosting or fabricated geometry',async()=>{
  const f=modelFixture(glb(d=>{d.nodes.push({name:'Empty directory'});d.scenes[0].nodes.push(2);}));
  f.version.components=[component('real',[0]),component('metadata',[]),component('schematic',[],'proxy_schematic')];
  const cache=new SceneResourceCache(f.api,{source:f.source}),resource=await cache.model(f.ref),root=cloneModel(resource,'preview',{calibrated:false});
  const inspection=new ModelPreviewInspection(root,f.version),nodes=inspection.structure.nodes;
  assert.equal(nodes.find(n=>n.id==='proxy:schematic').kind,'proxy');
  assert.equal(nodes.find(n=>n.id==='metadata:metadata').bounds,null);
  assert.equal(nodes.find(n=>n.id==='node:2').name,'Empty directory');
  assert.equal(nodes.find(n=>n.id==='node:2').bounds,null);
  const parts=meshList(root),originals=parts.map(m=>m.material);
  inspection.apply(choice(inspection,'metadata:metadata'),'#007e6d');assert.ok(parts.every((m,i)=>m.material===originals[i]));
  assert.equal(parts.length,3);inspection.dispose();cache.dispose();
});

test('material arrays and original hidden state restore; disposal releases owned clones once, never borrowed GPU data',async()=>{
  const f=await fixture(),parts=meshList(f.root),extra=new THREE.MeshBasicMaterial({transparent:true,opacity:.4});
  f.inspection.dispose();parts[0].material=[parts[0].material,extra];parts[1].visible=false;
  const inspection=new ModelPreviewInspection(f.root,f.version),original=parts[0].material;
  let sourceDisposed=0,geometryDisposed=0,copyDisposed=0;
  original.forEach(m=>m.addEventListener('dispose',()=>sourceDisposed++));
  parts[0].geometry.addEventListener('dispose',()=>geometryDisposed++);
  inspection.apply(choice(inspection,'node:0'),'#007e6d');
  const copies=parts[0].material;assert.ok(Array.isArray(copies));assert.equal(copies[1].opacity,.4);
  const versions=copies.map(copy=>copy.version);
  inspection.apply({...choice(inspection,'node:0'),focusToken:2},'#007e6d');
  assert.deepEqual(copies.map(copy=>copy.version),versions,'Refocusing does not recompile unchanged preview materials');
  copies.forEach(m=>m.addEventListener('dispose',()=>copyDisposed++));
  inspection.apply(choice(inspection,'node:0','isolate'),'#007e6d');assert.equal(parts[0].material,copies,'Selection changes reuse material clones');
  inspection.dispose();inspection.dispose();assert.equal(copyDisposed,2);
  assert.equal(parts[0].material,original);assert.equal(parts[1].visible,false);
  assert.equal(sourceDisposed,0);assert.equal(geometryDisposed,0);
  assert.equal(inspection.pick([{object:parts[0]}],inspection.structure.identity),null);
  extra.dispose();f.cache.dispose();
});
