import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import * as THREE from 'three';
import {imageryUvs,SceneImageryLayer} from '../src/sceneImagery.ts';
import {WorkbenchApi} from '../src/api.ts';
import {SceneApi} from '../src/sceneApi.ts';

const report={width:4,height:4,horizontalCrs:'EPSG:32649',pixelCornerAffine:[10,0,500000,0,-10,3700000]};
const frame={horizontalCrs:'EPSG:32649',originEasting:500000,originNorthing:3700000};
const points=values=>new THREE.BufferAttribute(new Float32Array(values),3);
test('native pixel corners, centres, north-up orientation and outside coverage never stretch to an AOI box',()=>{
  const uv=imageryUvs(points([0,0,0,40,0,40,5,0,5,-10,0,-10]),frame,report);
  const expected=[0,1,1,0,.125,.875,-.25,1.25];
  assert.ok(uv.every((value,index)=>Math.abs(value-expected[index])<1e-6));
});
test('WGS84 imagery UV agrees with existing independent GDAL geographic/display references',()=>{
  const fixture=JSON.parse(readFileSync(new URL('./fixtures/scene-transforms-gdal.json',import.meta.url)));
  for(const sample of fixture.cases){
    const r={...report,width:100,height:100,horizontalCrs:'EPSG:4326',pixelCornerAffine:[.001,0,sample.position.longitude-.05,0,-.001,sample.position.latitude+.05]};
    const uv=imageryUvs(points(sample.expectedDisplay),sample.frame,r);
    assert.ok(Math.abs(uv[0]-.5)<1e-5,sample.name);assert.ok(Math.abs(uv[1]-.5)<1e-5,sample.name);
  }
});
test('invalid affine, nonfinite positions and untrusted CRS definitions are refused',()=>{
  for(const bad of [{...report,pixelCornerAffine:[0,0,0,0,0,0]},{...report,horizontalCrs:'https://invalid.example/crs'},{...report,width:8192}])assert.throws(()=>imageryUvs(points([0,0,0]),frame,bad));
  assert.throws(()=>imageryUvs(points([NaN,0,0]),frame,report));
});
const imagery={imageryVersionId:'image-1',contentRevision:'revision-1',expectedReportSha256:'a'.repeat(64),texture:{sha256:'b'.repeat(64)},report};
const ref={imageryVersionId:imagery.imageryVersionId,expectedContentRevision:imagery.contentRevision,expectedReportSha256:imagery.expectedReportSha256,visible:true};
const terrainVersion={terrainVersionId:'terrain-1',expectedReportSha256:'c'.repeat(64),report:{mesh:{frame}}};
function mesh(){const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',points([0,2,0,40,2,0,0,2,40]));geometry.setIndex([0,2,1]);return new THREE.Mesh(geometry,new THREE.MeshBasicMaterial());}
test('real Three overlay reuses fixed vertex values, preserves base geometry and disposes owned material/texture/bitmap once',async()=>{
  let closed=0,reads=0;const previous=globalThis.createImageBitmap;globalThis.createImageBitmap=async()=>({width:4,height:4,close(){closed++;}});
  const terrain=mesh(),base=terrain.geometry.getAttribute('position');let baseDisposed=0;terrain.geometry.addEventListener('dispose',()=>baseDisposed++);
  const layer=new SceneImageryLayer({async imageryContent(){reads++;return new Blob();}});
  try{
    await layer.sync(terrain,terrainVersion,imagery,ref,new AbortController().signal);
    const overlay=terrain.children[0];assert.notEqual(overlay.geometry,terrain.geometry);assert.notEqual(overlay.geometry.getAttribute('position'),base);
    assert.deepEqual([...overlay.geometry.getAttribute('position').array],[...base.array]);assert.equal(terrain.geometry.getAttribute('uv'),undefined);
    const disposed={geometry:0,material:0,texture:0};for(const [key,item] of Object.entries({geometry:overlay.geometry,material:overlay.material,texture:overlay.material.map}))item.addEventListener('dispose',()=>disposed[key]++);
    await layer.sync(terrain,terrainVersion,imagery,ref,new AbortController().signal);assert.equal(reads,1);
    layer.visible(false);assert.equal(overlay.visible,false);layer.dispose();layer.dispose();
    assert.deepEqual(disposed,{geometry:1,material:1,texture:1});assert.equal(closed,1);assert.equal(baseDisposed,0);assert.equal(terrain.children.length,0);
  }finally{globalThis.createImageBitmap=previous;layer.dispose();terrain.geometry.dispose();terrain.material.dispose();}
});
test('late decode after viewport disposal closes the bitmap and never attaches a layer',async()=>{
  const previous=globalThis.createImageBitmap;let resolve,started,closed=0;
  const gate=new Promise(yes=>resolve=yes),ready=new Promise(yes=>started=yes);
  globalThis.createImageBitmap=async()=>{started();await gate;return {width:4,height:4,close(){closed++;}};};
  const terrain=mesh(),layer=new SceneImageryLayer({async imageryContent(){return new Blob();}});
  try{const pending=layer.sync(terrain,terrainVersion,imagery,ref,new AbortController().signal);await ready;layer.dispose();resolve();await assert.rejects(pending,e=>e.name==='AbortError');assert.equal(closed,1);assert.equal(terrain.children.length,0);}
  finally{globalThis.createImageBitmap=previous;terrain.geometry.dispose();terrain.material.dispose();}
});
test('mismatched pinned revision is rejected before any content request',async()=>{
  const terrain=mesh(),layer=new SceneImageryLayer({async imageryContent(){throw Error('must not fetch');}});
  try{await assert.rejects(layer.sync(terrain,terrainVersion,imagery,{...ref,expectedContentRevision:'different'},new AbortController().signal),e=>e.code==='RESOURCE_CHANGED');}
  finally{layer.dispose();terrain.geometry.dispose();terrain.material.dispose();}
});
test('imagery upload uses the fixed private route, TIFF metadata header and real session revision',async()=>{
  let call;const api=new WorkbenchApi(async(path,options)=>{call={path,options};return new Response(JSON.stringify({sessionRevision:'session:1'}),{headers:{'Content-Type':'application/json'}});});
  api.session('session:1');const client=new SceneApi(api);await client.uploadImagery(new Blob([new Uint8Array(8)]),{displayName:'Synthetic'});
  assert.equal(call.path,'/api/workbench/imagery/upload');assert.equal(call.options.headers['Content-Type'],'image/tiff');
  assert.deepEqual(JSON.parse(Buffer.from(call.options.headers['X-Imagery-Metadata'],'base64').toString()),{displayName:'Synthetic',expectedSessionRevision:'session:1'});
  assert.equal(call.options.credentials,'same-origin');assert.equal(call.options.cache,'no-store');
});
test('read-only imagery upload refusal preserves the reading session',async()=>{
  const api=new WorkbenchApi(async()=>new Response(JSON.stringify({code:'IMAGERY_WRITE_FORBIDDEN'}),{status:403,headers:{'Content-Type':'application/json'}}));api.session('session:1');
  const epoch=api.epoch;let denied=0;api.onDenied=()=>denied++;
  await assert.rejects(new SceneApi(api).uploadImagery(new Blob([new Uint8Array(8)]),{}),e=>e.code==='IMAGERY_WRITE_FORBIDDEN');
  assert.equal(api.epoch,epoch);assert.equal(api.revision,'session:1');assert.equal(denied,0);
});
