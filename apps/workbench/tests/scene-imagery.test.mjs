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
test('pending terrain or imagery metadata waits without content reads and attaches when both arrive',async()=>{
  const previous=globalThis.createImageBitmap;let reads=0,closed=0;
  globalThis.createImageBitmap=async()=>({width:4,height:4,close(){closed++;}});
  const terrain=mesh(),layer=new SceneImageryLayer({async imageryContent(){reads++;return new Blob();}}),signal=new AbortController().signal;
  try{
    await layer.sync(null,null,imagery,ref,signal);
    await layer.sync(terrain,null,imagery,ref,signal);
    await layer.sync(terrain,terrainVersion,null,ref,signal);
    assert.equal(reads,0);assert.equal(terrain.children.length,0);
    await layer.sync(terrain,terrainVersion,imagery,ref,signal);
    assert.equal(reads,1);assert.equal(terrain.children.length,1);
    layer.dispose();assert.equal(closed,1);
  }finally{globalThis.createImageBitmap=previous;layer.dispose();terrain.geometry.dispose();terrain.material.dispose();}
});
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

const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
test('matching projected CRS uses exact grid coordinates for a rotated affine and keeps coverage outside intact',()=>{
  const r={...report,pixelCornerAffine:[10,2,500000,3,-10,3700000]};
  const uv=imageryUvs(points([24,0,14,48,0,28,-12,0,-7]),frame,r);
  assert.deepEqual([...uv],[.5,.5,1,0,-.25,1.25]);
});
test('image preparation begins before terrain is ready, shares one authorized read/decode, and attaches only during sync',async()=>{
  const previous=globalThis.createImageBitmap,gate=deferred();let reads=0,decoded=0,closed=0;
  globalThis.createImageBitmap=async()=>{decoded++;return {width:4,height:4,close(){closed++;}};};
  const terrain=mesh(),layer=new SceneImageryLayer({async imageryContent(){reads++;return gate.promise;}});
  try{
    const first=layer.prepare(imagery,ref),second=layer.prepare(imagery,ref);
    assert.equal(reads,1);assert.equal(terrain.children.length,0);gate.resolve(new Blob());
    assert.equal(await first,await second);assert.equal(decoded,1);assert.equal(terrain.children.length,0);
    await layer.sync(terrain,terrainVersion,imagery,ref,new AbortController().signal);
    assert.equal(reads,1);assert.equal(decoded,1);assert.equal(terrain.children.length,1);
    layer.dispose();assert.equal(closed,1);
  }finally{globalThis.createImageBitmap=previous;layer.dispose();terrain.geometry.dispose();terrain.material.dispose();}
});
test('snapshot cancellation does not restart the same fixed image or let a cancelled consumer attach it',async()=>{
  const previous=globalThis.createImageBitmap,gate=deferred();let reads=0,decoded=0,closed=0,requestSignal;
  globalThis.createImageBitmap=async()=>{decoded++;return {width:4,height:4,close(){closed++;}};};
  const terrain=mesh(),layer=new SceneImageryLayer({async imageryContent(_value,signal){reads++;requestSignal=signal;return gate.promise;}}),abort=new AbortController();
  try{
    const cancelled=layer.sync(terrain,terrainVersion,imagery,ref,abort.signal);abort.abort();
    await assert.rejects(cancelled,e=>e.name==='AbortError');assert.equal(requestSignal.aborted,false);
    const current=layer.sync(terrain,terrainVersion,imagery,ref,new AbortController().signal);gate.resolve(new Blob());await current;
    assert.equal(reads,1);assert.equal(decoded,1);assert.equal(terrain.children.length,1);layer.dispose();assert.equal(closed,1);
  }finally{globalThis.createImageBitmap=previous;layer.dispose();terrain.geometry.dispose();terrain.material.dispose();}
});
test('changing image during decode closes the old bitmap, preserves the new layer and aborts only the old source read',async()=>{
  const previous=globalThis.createImageBitmap,gate=deferred(),started=deferred();let decoded=0,closed=0;const signals=[];
  globalThis.createImageBitmap=async()=>{const id=++decoded;if(id===1){started.resolve();await gate.promise;}return {width:4,height:4,close(){closed++;}};};
  const terrain=mesh(),layer=new SceneImageryLayer({async imageryContent(_value,signal){signals.push(signal);return new Blob();}}),signal=new AbortController().signal;
  try{
    const old=layer.prepare(imagery,ref);await started.promise;
    const changed={...imagery,imageryVersionId:'image-2'},changedRef={...ref,imageryVersionId:changed.imageryVersionId};
    await layer.sync(terrain,terrainVersion,changed,changedRef,signal);const attached=terrain.children[0];
    gate.resolve();await assert.rejects(old,e=>e.name==='AbortError');
    assert.equal(signals[0].aborted,true);assert.equal(signals[1].aborted,false);assert.equal(closed,1);
    assert.equal(terrain.children[0],attached);layer.dispose();assert.equal(closed,2);
  }finally{globalThis.createImageBitmap=previous;layer.dispose();terrain.geometry.dispose();terrain.material.dispose();}
});
test('failed prepared reads can retry and invalid decoded dimensions never attach or remain owned',async()=>{
  const previous=globalThis.createImageBitmap;let reads=0,closed=0;
  globalThis.createImageBitmap=async()=>({width:reads===2?5:4,height:4,close(){closed++;}});
  const terrain=mesh(),layer=new SceneImageryLayer({async imageryContent(){if(++reads===1)throw new Error('Synthetic unavailable');return new Blob();}}),signal=new AbortController().signal;
  try{
    await assert.rejects(layer.prepare(imagery,ref),/Synthetic unavailable/);
    await assert.rejects(layer.sync(terrain,terrainVersion,imagery,ref,signal),e=>e.code==='RESOURCE_CHANGED');
    assert.equal(terrain.children.length,0);assert.equal(closed,1);
    await layer.sync(terrain,terrainVersion,imagery,ref,signal);assert.equal(reads,3);assert.equal(terrain.children.length,1);
    layer.dispose();assert.equal(closed,2);
  }finally{globalThis.createImageBitmap=previous;layer.dispose();terrain.geometry.dispose();terrain.material.dispose();}
});
test('viewport disposal during preparation aborts its read and refuses a late blob before decoding',async()=>{
  const previous=globalThis.createImageBitmap,gate=deferred();let decoded=0,signal;
  globalThis.createImageBitmap=async()=>{decoded++;throw new Error('must not decode');};
  const layer=new SceneImageryLayer({async imageryContent(_value,value){signal=value;return gate.promise;}});
  try{
    const prepared=layer.prepare(imagery,ref);layer.dispose();assert.equal(signal.aborted,true);gate.resolve(new Blob());
    await assert.rejects(prepared,e=>e.name==='AbortError');assert.equal(decoded,0);
  }finally{globalThis.createImageBitmap=previous;layer.dispose();}
});
test('a prepared bitmap cleared between readiness and attachment is never displayed',async()=>{
  const previous=globalThis.createImageBitmap;let closed=0;
  globalThis.createImageBitmap=async()=>({width:4,height:4,close(){closed++;}});
  const terrain=mesh(),layer=new SceneImageryLayer({async imageryContent(){return new Blob();}}),signal=new AbortController().signal;
  try{
    await layer.prepare(imagery,ref);const pending=layer.sync(terrain,terrainVersion,imagery,ref,signal);
    await layer.prepare(null,null);await assert.rejects(pending,e=>e.name==='AbortError');
    assert.equal(terrain.children.length,0);assert.equal(closed,1);
  }finally{globalThis.createImageBitmap=previous;layer.dispose();terrain.geometry.dispose();terrain.material.dispose();}
});
test('prepared private reads keep the real API session guard and refuse a late response after logout',async()=>{
  const previous=globalThis.createImageBitmap,gate=deferred();let reads=0,decoded=0;
  globalThis.createImageBitmap=async()=>{decoded++;throw Error('must not decode');};
  const api=new WorkbenchApi(async()=>{reads++;return gate.promise;});api.session('session:1');
  const layer=new SceneImageryLayer(new SceneApi(api));
  try{
    const pending=layer.prepare({...imagery,texture:{...imagery.texture,bytes:32}},ref);assert.equal(reads,1);
    api.session('');gate.resolve(new Response('private',{headers:{'Content-Type':'image/png'}}));
    await assert.rejects(pending,e=>e.name==='AbortError');assert.equal(decoded,0);
  }finally{globalThis.createImageBitmap=previous;layer.dispose();}
});
