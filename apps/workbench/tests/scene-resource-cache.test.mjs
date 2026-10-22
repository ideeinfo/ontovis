import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import test from 'node:test';
import * as THREE from 'three';
import {WorkbenchApi} from '../src/api.ts';
import {SceneResourceCache,cloneModel,decodeTerrain} from '../src/sceneResourceCache.ts';
import {sceneModelHit} from '../src/sceneComponentPick.ts';

const digest=bytes=>createHash('sha256').update(new Uint8Array(bytes)).digest('hex');
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
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
const rejected=(code,callback)=>assert.rejects(callback,error=>error.code===code);
const component=(key,nodeIndices)=>({componentKey:key,displayName:key,nodeIndices,geometryQuality:'source_candidate',bounds:[[0,0,0],[1,1,1]]});
const proxyComponent=(key,bounds)=>({...component(key,[]),geometryQuality:'proxy_schematic',bounds});

test('empty-node schematic cabinets absent from GLB stay visible, pickable and independently transformed in every instance',async()=>{
  const f=modelFixture();f.version.components=[component('CN',[0]),
    proxyComponent('CT',[[-2,0,-1],[-1,2,1]]),proxyComponent('CN1',[[4,8,-1],[6,11,1]])];
  const cache=new SceneResourceCache(f.api,{source:f.source}),resource=await cache.model(f.ref);
  assert.equal(meshList(resource.scene).length,4,'The two GLB triangles need two explicit schematic boxes');
  const first=cloneModel(resource,'instance-A'),second=cloneModel(resource,'instance-B'),boundary=new THREE.Group();
  boundary.add(first,second);first.position.set(100,5,20);first.rotation.y=Math.PI/2;first.updateMatrixWorld(true);
  const proxies=root=>meshList(root).filter(mesh=>mesh.userData.ontoVisProxySchematic===true);
  assert.equal(proxies(first).length,2);assert.equal(proxies(second).length,2);
  for(const [index,mesh] of proxies(first).entries()){
    const key=index===0?'CT':'CN1';
    assert.equal(mesh.visible,true);assert.equal(mesh.material.opacity,1);assert.equal(mesh.material.transparent,false);
    assert.equal(mesh.material.color.getHex(),0x718275);assert.equal(mesh.material.roughness,.75);
    assert.equal(mesh.userData.ontoVisNodeIndex,undefined,'Schematic boxes must not forge a GLTF node');
    assert.deepEqual(sceneModelHit(mesh,boundary)?.component,{sceneModelInstanceId:'instance-A',modelVersionId:f.version.modelVersionId,componentKey:key});
    assert.equal(mesh.geometry,proxies(second)[index].geometry);assert.equal(mesh.material,proxies(second)[index].material);
  }
  assert.ok(proxies(first)[0].getWorldPosition(new THREE.Vector3()).distanceTo(new THREE.Vector3(103,4,31.5))<1e-8);
  const preview=cloneModel(resource,'preview',{calibrated:false});preview.updateMatrixWorld(true);
  const rawBox=new THREE.Box3().setFromObject(proxies(preview)[0]);
  assert.deepEqual(rawBox.min.toArray(),[-2,0,-1]);assert.deepEqual(rawBox.max.toArray(),[-1,2,1]);
  assert.equal(f.version.components[1].geometryQuality,'proxy_schematic');assert.deepEqual(f.version.components[1].nodeIndices,[]);
  first.visible=false;assert.equal(sceneModelHit(proxies(first)[0],boundary),null);
  assert.equal(sceneModelHit(proxies(second)[0],boundary)?.component?.sceneModelInstanceId,'instance-B');
  assert.equal(await cache.model(f.ref),resource);assert.equal(meshList(resource.scene).length,4);assert.equal(f.calls.modelContent,1);
  cache.dispose();
});

test('real-node proxies and empty source-candidate directories never add duplicate schematic geometry',async()=>{
  const f=modelFixture();f.version.components=[component('CN',[0]),
    {...proxyComponent('existing-proxy',[[2,0,0],[3,1,1]]),nodeIndices:[1]},component('empty-source',[])];
  const cache=new SceneResourceCache(f.api,{source:f.source}),resource=await cache.model(f.ref),clone=cloneModel(resource,'instance');
  assert.equal(meshList(resource.scene).length,2);assert.equal(meshList(clone).length,2);
  assert.ok(meshList(clone).every(mesh=>mesh.userData.ontoVisProxySchematic===undefined));cache.dispose();
});

test('invalid schematic bounds reject before attachment and release parsed source resources',async()=>{
  for(const bounds of [[[0,0,0],[Infinity,1,1]],[[0,0,0],[NaN,1,1]],[[1,0,0],[0,1,1]],
    [[0,0],[1,1,1]],[[0,0,0],[1e6+1,1,1]]]){
    const f=modelFixture();f.version.components=[proxyComponent('CT',bounds)];
    const source=new THREE.Group(),mesh=new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshStandardMaterial());source.add(mesh);
    let geometries=0,materials=0;mesh.geometry.addEventListener('dispose',()=>geometries++);mesh.material.addEventListener('dispose',()=>materials++);
    const cache=new SceneResourceCache(f.api,{source:f.source,parseModel:async()=>source});
    await rejected('RESOURCE_CHANGED',()=>cache.model(f.ref));assert.equal(meshList(source).length,1);
    cache.dispose();assert.equal(geometries,1);assert.equal(materials,1);
  }
});

test('cache owns schematic GPU resources once across clones, removal and repeated disposal',async()=>{
  const f=modelFixture();f.version.components=[proxyComponent('CT',[[-2,0,-1],[-1,2,1]]),proxyComponent('CN1',[[4,8,-1],[6,11,1]])];
  const cache=new SceneResourceCache(f.api,{source:f.source}),resource=await cache.model(f.ref);
  const geometries=new Set(meshList(resource.scene).map(mesh=>mesh.geometry)),materials=new Set(meshList(resource.scene).map(mesh=>mesh.material));
  const counts=new Map([...geometries,...materials].map(value=>[value,0]));
  for(const value of counts.keys())value.addEventListener('dispose',()=>counts.set(value,counts.get(value)+1));
  const clones=Array.from({length:20},(_,index)=>cloneModel(resource,`instance-${index}`));
  assert.equal(geometries.size,3);assert.equal(materials.size,2);
  clones.forEach(clone=>clone.removeFromParent());assert.ok([...counts.values()].every(count=>count===0));
  cache.dispose();cache.dispose();assert.ok([...counts.values()].every(count=>count===1));
});

test('20 actual GLB instances share one source decode and GPU data but preserve transform/pick identity',async()=>{
  const f=modelFixture(),cache=new SceneResourceCache(f.api,{source:f.source});
  f.version.components=[component('fixed-A',[0]),component('fixed-B',[1])];
  const resources=await Promise.all(Array.from({length:20},()=>cache.model(f.ref)));
  assert.ok(resources.every(value=>value===resources[0]));assert.equal(f.calls.model,1);assert.equal(f.calls.modelContent,1);
  const instances=resources.map((value,index)=>cloneModel(value,`instance-${index}`));
  const sourceMeshes=meshList(resources[0].scene),meshes=instances.map(meshList);
  assert.equal(sourceMeshes.length,2);assert.ok(sourceMeshes[0].geometry===sourceMeshes[1].geometry);
  for(let index=0;index<20;index++) {
    assert.equal(instances[index].userData.sceneModelInstanceId,`instance-${index}`);
    assert.equal(meshes[index][0].userData.sceneModelInstanceId,`instance-${index}`);
    assert.equal(meshes[index][0].userData.ontoVisComponentKey,'fixed-A');
    assert.equal(meshes[index][1].userData.ontoVisComponentKey,'fixed-B');
    assert.equal(meshes[index][0].userData.ontoVisModelVersionId,f.version.modelVersionId);
    assert.equal(meshes[index][0].geometry,sourceMeshes[0].geometry);assert.equal(meshes[index][0].material,sourceMeshes[0].material);
    instances[index].position.x=index*5;
  }
  assert.equal(instances[0].position.x,0);assert.equal(instances[19].position.x,95);assert.equal(resources[0].scene.position.x,0);
  assert.equal(sourceMeshes[0].userData.sceneModelInstanceId,undefined);
  instances[0].position.set(100,0,0);instances[0].rotation.y=Math.PI/2;instances[0].updateMatrixWorld(true);
  const actual=new THREE.Vector3(0,0,0).applyMatrix4(meshes[0][0].matrixWorld);
  assert.ok(actual.distanceTo(new THREE.Vector3(103,-2,10))<1e-8,'Calibration must precede independent instance yaw/position');
  cache.dispose();
});

test('actual node associations distinguish identical names and one mesh used by different GLTF nodes',async()=>{
  const f=modelFixture(glb(document=>{document.nodes.forEach(node=>node.name='same name');}));
  f.version.components=[component('fixed-zero',[0]),component('fixed-one',[1])];
  const cache=new SceneResourceCache(f.api,{source:f.source}),resource=await cache.model(f.ref),root=cloneModel(resource,'instance-A');
  const boundary=new THREE.Group();boundary.add(root);const meshes=meshList(root);
  assert.equal(meshes[0].geometry,meshes[1].geometry);assert.equal(meshes[0].material,meshes[1].material);
  assert.deepEqual(meshes.map(mesh=>sceneModelHit(mesh,boundary)?.component?.componentKey),['fixed-zero','fixed-one']);
  assert.ok(meshes.every(mesh=>sceneModelHit(mesh,boundary)?.component?.sceneModelInstanceId==='instance-A'));
  cache.dispose();
});

test('multi-scene default scene keeps real associations captured before loader pruning',async()=>{
  const f=modelFixture(glb(document=>{document.scenes=[{nodes:[0]},{nodes:[1]}];document.scene=0;}));
  f.version.components=[component('active-first-scene',[0])];
  const cache=new SceneResourceCache(f.api,{source:f.source}),resource=await cache.model(f.ref),clone=cloneModel(resource,'first-scene');
  assert.equal(meshList(clone).length,1);
  assert.equal(meshList(clone)[0].userData.ontoVisComponentKey,'active-first-scene');
  assert.equal(meshList(clone)[0].userData.ontoVisNodeIndex,0);
  cache.dispose();
});

test('all primitive meshes use their actual containing GLTF node and directory grouping can cover several nodes',async()=>{
  const f=modelFixture(glb(document=>{document.meshes[0].primitives.push({...document.meshes[0].primitives[0]});}));
  f.version.components=[component('fixed-group',[0,1])];
  const cache=new SceneResourceCache(f.api,{source:f.source}),resource=await cache.model(f.ref),root=cloneModel(resource,'group');
  const meshes=meshList(root);assert.equal(meshes.length,4);
  assert.deepEqual(meshes.map(mesh=>mesh.userData.ontoVisNodeIndex),[0,0,1,1]);
  assert.ok(meshes.every(mesh=>mesh.userData.ontoVisComponentKey==='fixed-group'));cache.dispose();
});

test('asset extras cannot forge a pick and an explicitly unmapped child never inherits a mapped ancestor',async()=>{
  const f=modelFixture(glb(document=>{
    document.scenes=[{nodes:[0]}];document.nodes[0].children=[1];
    document.nodes.forEach(node=>node.extras={ontoVisComponentKey:'forged-key',ontoVisNodeIndex:0,ontoVisModelVersionId:'forged-version',ontoVisProxySchematic:true});
  }));
  f.version.components=[component('parent-only',[0])];
  const cache=new SceneResourceCache(f.api,{source:f.source}),resource=await cache.model(f.ref),root=cloneModel(resource,'checked');
  const boundary=new THREE.Group();boundary.add(root);const meshes=meshList(root);
  assert.equal(sceneModelHit(meshes[0],boundary)?.component?.componentKey,'parent-only');
  assert.equal(meshes[1].userData.ontoVisNodeIndex,1);
  assert.equal(meshes[1].userData.ontoVisComponentKey,undefined);
  assert.ok(meshes.every(mesh=>mesh.userData.ontoVisProxySchematic===undefined));
  assert.equal(sceneModelHit(meshes[1],boundary)?.component,null);cache.dispose();
});

test('one actual GLTF node cannot be claimed by two directory keys',async()=>{
  const f=modelFixture();f.version.components=[component('one',[0]),component('two',[0])];
  const cache=new SceneResourceCache(f.api,{source:f.source}),resource=await cache.model(f.ref);
  assert.throws(()=>cloneModel(resource,'ambiguous'),error=>error.code==='RESOURCE_CHANGED');cache.dispose();
});

test('custom parse injection remains cloneable but cannot manufacture trusted component associations',async()=>{
  const f=modelFixture();f.version.components=[component('fixed-zero',[0])];
  const group=new THREE.Group(),mesh=new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshStandardMaterial());group.add(mesh);
  mesh.userData={ontoVisComponentKey:'fixed-zero',ontoVisNodeIndex:0,ontoVisModelVersionId:f.version.modelVersionId,ontoVisProxySchematic:true};
  const cache=new SceneResourceCache(f.api,{source:f.source,parseModel:async()=>group}),resource=await cache.model(f.ref);
  const root=cloneModel(resource,'custom'),boundary=new THREE.Group();boundary.add(root);
  const hit=sceneModelHit(meshList(root)[0],boundary);
  assert.deepEqual(hit,{sceneModelInstanceId:'custom',component:null});cache.dispose();
});

test('shared geometry/material/texture dispose only once across clones and repeated cache disposal',async()=>{
  const f=modelFixture(),cache=new SceneResourceCache(f.api,{source:f.source});
  const resource=await cache.model(f.ref),mesh=meshList(resource.scene)[0],texture=new THREE.Texture();mesh.material.map=texture;
  const counts={geometry:0,material:0,texture:0,image:0},image={close(){counts.image++;}};
  texture.image=image;const secondTexture=new THREE.Texture(image);mesh.material.normalMap=secondTexture;
  mesh.geometry.addEventListener('dispose',()=>counts.geometry++);mesh.material.addEventListener('dispose',()=>counts.material++);
  texture.addEventListener('dispose',()=>counts.texture++);
  secondTexture.addEventListener('dispose',()=>counts.texture++);
  const clones=Array.from({length:20},(_,index)=>cloneModel(resource,`instance-${index}`));
  clones.forEach(clone=>clone.removeFromParent());assert.deepEqual(counts,{geometry:0,material:0,texture:0,image:0});
  cache.dispose();cache.dispose();assert.deepEqual(counts,{geometry:1,material:1,texture:2,image:1});
});

test('inactive GLTF scenes are not displayed but their decoded materials are also released',async()=>{
  const f=modelFixture(glb(document=>{
    document.scenes=[{nodes:[0]},{nodes:[1]}];document.nodes[1].mesh=1;
    document.materials.push({pbrMetallicRoughness:{baseColorFactor:[.9,.4,.2,1]}});
    document.meshes.push({primitives:[{attributes:{POSITION:0},material:1}]});
  }));
  const cache=new SceneResourceCache(f.api,{source:f.source}),resource=await cache.model(f.ref);
  assert.equal(meshList(resource.scene).length,1);
  const original=THREE.Material.prototype.dispose,released=new Set();
  THREE.Material.prototype.dispose=function(){released.add(this.uuid);return original.call(this);};
  try {cache.dispose();assert.equal(released.size,2);} finally {THREE.Material.prototype.dispose=original;}
});

test('unverified versions allow raw preview but never calibrated placement or arbitrary scale',async()=>{
  const f=modelFixture();f.version.calibration={state:'unverified'};f.version.canPlace=false;f.version.calibrationState='unverified';
  const cache=new SceneResourceCache(f.api,{source:f.source}),resource=await cache.model(f.ref);
  assert.throws(()=>cloneModel(resource,'placement'),error=>error.code==='MODEL_CALIBRATION_REQUIRED');
  assert.equal(meshList(cloneModel(resource,'preview',{calibrated:false})).length,2);cache.dispose();
  const calibrated=modelFixture(),other=new SceneResourceCache(calibrated.api,{source:calibrated.source});
  const ready=await other.model(calibrated.ref);ready.version.calibration.modelToCalibrated[0]=2;
  assert.throws(()=>cloneModel(ready,'scaled'),error=>error.code==='INVALID_CALIBRATION');other.dispose();
});

test('fixed metadata/content digest, explicit asset reference and embedded-only GLB are enforced',async()=>{
  const f=modelFixture(),cache=new SceneResourceCache(f.api,{source:f.source});
  await rejected('MODEL_REFERENCE_REQUIRED',()=>cache.model({...f.ref,modelAssetId:undefined}));assert.equal(f.calls.model,0);
  await rejected('RESOURCE_CHANGED',()=>cache.model({...f.ref,contentRevision:'other'}));assert.equal(f.calls.modelContent,0);
  f.source.modelContent=async()=>new Blob([new Uint8Array(f.bytes.byteLength)]);
  await rejected('RESOURCE_CHANGED',()=>cache.model(f.ref));cache.dispose();
  const external=modelFixture(glb(document=>{document.buffers[0].uri='https://invalid.example/model.bin';}));
  const restricted=new SceneResourceCache(external.api,{source:external.source});
  await rejected('UNSUPPORTED_MODEL',()=>restricted.model(external.ref));restricted.dispose();
});

test('one cancelled consumer does not poison the shared request or later cache reuse',async()=>{
  const f=modelFixture(),metadata=deferred(),sourceSignal=[];
  f.source.model=async(_asset,_version,signal)=>{f.calls.model++;sourceSignal.push(signal);return metadata.promise;};
  const cache=new SceneResourceCache(f.api,{source:f.source}),abort=new AbortController();
  const old=cache.model(f.ref,abort.signal),current=cache.model(f.ref);abort.abort();
  await assert.rejects(old,error=>error.name==='AbortError');assert.equal(sourceSignal[0].aborted,false);
  metadata.resolve(f.version);const result=await current;assert.equal(await cache.model(f.ref),result);
  assert.equal(f.calls.model,1);cache.dispose();assert.equal(sourceSignal[0].aborted,true);
});

test('late decoded results are disposed after viewport teardown instead of being attached',async()=>{
  const f=modelFixture(),parsed=deferred(),started=deferred();
  const geometry=new THREE.BoxGeometry(1,1,1),material=new THREE.MeshStandardMaterial(),group=new THREE.Group();
  group.add(new THREE.Mesh(geometry,material));let disposed=0;geometry.addEventListener('dispose',()=>disposed++);
  const cache=new SceneResourceCache(f.api,{source:f.source,parseModel:async()=>{started.resolve();return parsed.promise;}});
  const pending=cache.model(f.ref);await started.promise;cache.dispose();parsed.resolve(group);
  await assert.rejects(pending,error=>error.name==='AbortError');assert.equal(disposed,1);cache.dispose();assert.equal(disposed,1);
});

test('session epoch/revision invalidation rejects stale metadata and aborts shared network work',async()=>{
  const f=modelFixture(),metadata=deferred();let signal;
  f.source.model=async(_asset,_version,value)=>{signal=value;return metadata.promise;};
  const cache=new SceneResourceCache(f.api,{source:f.source}),pending=cache.model(f.ref);
  f.api.invalidate();metadata.resolve(f.version);await assert.rejects(pending,error=>error.name==='AbortError');
  assert.equal(signal.aborted,true);await assert.rejects(cache.model(f.ref),error=>error.name==='AbortError');cache.dispose();
});

test('failed entries are removed and a new request can retry within the same viewport',async()=>{
  const f=modelFixture();let calls=0;
  f.source.model=async()=>{calls++;if(calls===1)throw Error('Synthetic read failure');return f.version;};
  const cache=new SceneResourceCache(f.api,{source:f.source});await assert.rejects(cache.model(f.ref),/Synthetic/);
  assert.equal((await cache.model(f.ref)).version.modelVersionId,f.ref.modelVersionId);assert.equal(calls,2);cache.dispose();
});

function terrainFixture() {
  const positions=new Float32Array([0,100,0,1,100,0,2,0,0,0,100,1,1,100,1,2,0,1]).buffer;
  const triangles=new Uint32Array([0,3,1,1,3,4]).buffer;
  const fixed=[['heights.f64',48],['mask.u8',6],['cells.u8',2],['positions.f32',positions.byteLength],['triangles.u32',triangles.byteLength]]
    .map(([artifactId,bytes])=>({artifactId,bytes,sha256:artifactId==='positions.f32'?digest(positions):artifactId==='triangles.u32'?digest(triangles):'c'.repeat(64)}));
  const version={terrainVersionId:'terrain-fixture',contentRevision:'terrain-content:1',sha256:'a'.repeat(64),expectedReportSha256:'b'.repeat(64),state:'ready',
    report:{schemaVersion:1,state:'ready',source:{sha256:'a'.repeat(64),bytes:44,heightUnit:'m',verticalDatum:'EGM2008'},
      mesh:{rows:2,columns:3,vertices:6,validVertices:4,triangles:2,validCells:1,heightExaggeration:1,placementSamplingRule:'mesh-triangle-tr-bl-cell-mask-v2',
        frame:{mode:'projected_site',horizontalCrs:'EPSG:32649',verticalDatum:'EGM2008',originEasting:500000,originNorthing:3700000,originHeight:0,isStrictEnu:false,displayAxes:'X_GRID_EAST_Y_UP_Z_GRID_SOUTH'}},artifacts:fixed},
    artifacts:[{artifactId:'source.tif',bytes:44,sha256:'a'.repeat(64)},...fixed]};
  return {positions,triangles,version};
}

test('fixed terrain decoder retains only supplied faces and excludes missing placeholder vertices from bounds',async()=>{
  const f=terrainFixture(),geometry=await decodeTerrain(f.version,f.positions,f.triangles);
  assert.equal(geometry.getAttribute('position').count,6);assert.deepEqual(Array.from(geometry.index.array),[0,3,1,1,3,4]);
  assert.equal(geometry.index.count,6,'The omitted right quad must not be filled');
  assert.equal(geometry.boundingBox.min.y,100);assert.equal(geometry.boundingBox.max.y,100);geometry.dispose();
});

test('terrain fixed SHA/bytes/index/vertex budgets and manifest duplicates are rejected',async()=>{
  const f=terrainFixture(),badBytes=f.positions.slice(0);new Uint8Array(badBytes)[1]^=1;
  await rejected('RESOURCE_CHANGED',()=>decodeTerrain(f.version,badBytes,f.triangles));
  await rejected('RESOURCE_CHANGED',()=>decodeTerrain(f.version,f.positions.slice(4),f.triangles));
  const tooLarge=structuredClone(f.version);tooLarge.report.mesh.rows=502;
  await rejected('TERRAIN_LIMIT_EXCEEDED',()=>decodeTerrain(tooLarge,f.positions,f.triangles));
  const duplicate=structuredClone(f.version);duplicate.report.artifacts.push(duplicate.report.artifacts[0]);
  await rejected('RESOURCE_CHANGED',()=>decodeTerrain(duplicate,f.positions,f.triangles));
  const invalidIndex=new Uint32Array([0,3,1,1,3,99]).buffer,indexVersion=structuredClone(f.version);
  for(const artifact of [...indexVersion.artifacts,...indexVersion.report.artifacts])if(artifact.artifactId==='triangles.u32')artifact.sha256=digest(invalidIndex);
  await rejected('INVALID_TERRAIN',()=>decodeTerrain(indexVersion,f.positions,invalidIndex));
  const nonFinite=f.positions.slice(0);new DataView(nonFinite).setFloat32(0,NaN,true);const nonFiniteVersion=structuredClone(f.version);
  for(const artifact of [...nonFiniteVersion.artifacts,...nonFiniteVersion.report.artifacts])if(artifact.artifactId==='positions.f32')artifact.sha256=digest(nonFinite);
  await rejected('INVALID_TERRAIN',()=>decodeTerrain(nonFiniteVersion,nonFinite,f.triangles));
});

test('terrain loads fixed metadata and two artifacts once, retries failures and disposes shared geometry once',async()=>{
  const f=terrainFixture(),api=new WorkbenchApi(),calls={version:0,content:0};let broken=true;
  const source={async model(){throw Error('unused');},async modelContent(){throw Error('unused');},
    async version(){calls.version++;return f.version;},async content(_id,artifact){calls.content++;
      return new Blob([artifact.artifactId==='positions.f32'?(broken?new ArrayBuffer(f.positions.byteLength):f.positions):f.triangles]);}};
  const cache=new SceneResourceCache(api,{source});await rejected('RESOURCE_CHANGED',()=>cache.terrain(f.version));
  broken=false;const [one,two]=await Promise.all([cache.terrain(f.version),cache.terrain(f.version)]);
  assert.equal(one,two);assert.equal(calls.version,2);assert.equal(calls.content,4);
  let disposed=0;one.addEventListener('dispose',()=>disposed++);cache.dispose();cache.dispose();assert.equal(disposed,1);
});

test('terrain report/source fixed identities cannot be replaced between selected metadata and load',async()=>{
  const f=terrainFixture(),api=new WorkbenchApi();
  const source={async model(){throw Error('unused');},async modelContent(){throw Error('unused');},
    async version(){return {...f.version,expectedReportSha256:'d'.repeat(64)};},async content(){throw Error('Must reject before bytes');}};
  const cache=new SceneResourceCache(api,{source});await rejected('RESOURCE_CHANGED',()=>cache.terrain(f.version));cache.dispose();
});

test('legacy display clones preserve original coordinates and shared resources without a fabricated forward',async()=>{
  const f=modelFixture(),cache=new SceneResourceCache(f.api,{source:f.source});
  f.version.components=[component('CN',[0]),proxyComponent('CT',[[-2,0,-1],[-1,2,1]]),proxyComponent('CN1',[[4,8,-1],[6,11,1]])];
  Object.assign(f.version,{calibrationState:'legacy_display',canPlaceGeographic:false,
    calibration:{state:'legacy_display',unit:'m',axes:'Y_UP_RIGHT_HANDED',
      modelToCalibrated:[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1],sourceModelVersionId:'legacy-source',sourceSha256:f.version.sha256,
      sourceNote:'Synthetic previous display coordinates',preservedBy:'fixture',preservedAt:'fixture'}});
  const resource=await cache.model(f.ref),first=cloneModel(resource,'legacy-A'),second=cloneModel(resource,'legacy-B');
  first.updateMatrixWorld(true);second.updateMatrixWorld(true);
  const sourceBox=new THREE.Box3().setFromObject(resource.scene),cloneBox=new THREE.Box3().setFromObject(first);
  assert.deepEqual(cloneBox.min.toArray(),sourceBox.min.toArray());assert.deepEqual(cloneBox.max.toArray(),sourceBox.max.toArray());
  assert.equal(meshList(first)[0].geometry,meshList(second)[0].geometry);
  const proxy=meshList(first).find(mesh=>mesh.userData.ontoVisComponentKey==='CT'),box=new THREE.Box3().setFromObject(proxy);
  assert.deepEqual(box.min.toArray(),[-2,0,-1]);assert.deepEqual(box.max.toArray(),[-1,2,1]);
  assert.equal(proxy.userData.ontoVisProxySchematic,true);assert.equal(proxy.userData.ontoVisNodeIndex,undefined);
  assert.equal(f.version.calibration.basePoint,undefined);assert.equal(f.version.calibration.forward,undefined);
  assert.equal(f.calls.model,1);assert.equal(f.calls.modelContent,1);cache.dispose();
});
test('legacy display cannot smuggle a transform or geographic permission through a shared clone',async()=>{
  for(const change of [v=>v.calibration.modelToCalibrated[12]=.01,v=>v.calibration.modelToCalibrated[0]=NaN,v=>v.canPlaceGeographic=true]) {
    const f=modelFixture(),cache=new SceneResourceCache(f.api,{source:f.source});
    Object.assign(f.version,{calibrationState:'legacy_display',canPlaceGeographic:false,
      calibration:{state:'legacy_display',unit:'m',axes:'Y_UP_RIGHT_HANDED',modelToCalibrated:[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]}});
    change(f.version);const resource=await cache.model(f.ref);
    assert.throws(()=>cloneModel(resource,'forged-legacy'),error=>error.code==='INVALID_CALIBRATION');cache.dispose();
  }
});
