import test from 'node:test';import assert from 'node:assert/strict';import * as THREE from 'three';
import {cloudNoise,SceneClouds} from '../src/sceneClouds.ts';
import {environmentPreset} from '../src/sceneEnvironment.ts';
import {SceneEnvironmentRuntime} from '../src/sceneEnvironmentRuntime.ts';

test('cloud noise is seeded, seamless and varied at several spatial scales',()=>{
  const a=cloudNoise(1437),b=cloudNoise(1437),c=cloudNoise(1438);assert.deepEqual(a.image.data,b.image.data);assert.notDeepEqual(a.image.data,c.image.data);
  const data=a.image.data,values=new Set();let seam=0,near=0,far=0;
  for(let y=0;y<256;y++){seam+=Math.abs(data[y*1024]-data[y*1024+1020]);for(let x=0;x<224;x++){const i=(y*256+x)*4;values.add(data[i]);near+=Math.abs(data[i]-data[i+4]);far+=Math.abs(data[i]-data[i+128]);}}
  assert.ok(values.size>80);assert.ok(seam/256<8);assert.ok(far>near*4);
  assert.equal(a.wrapS,THREE.RepeatWrapping);assert.equal(a.minFilter,THREE.LinearMipmapLinearFilter);assert.equal(a.colorSpace,THREE.NoColorSpace);assert.equal(a.image.data.byteLength,262144);
  [a,b,c].forEach(t=>t.dispose());
});
test('cloud sky is a bounded independent non-pickable layer and never edits source geometry',()=>{
  const scene=new THREE.Scene(),source=new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshBasicMaterial()),e=environmentPreset('land-day-v1'),layer=new SceneClouds(scene);scene.add(source);
  const before=source.geometry.getAttribute('position').array.slice();layer.configure(e,.5,1);const sky=scene.getObjectByName('visual-clouds-not-placement');
  assert.ok(sky);assert.equal(sky.geometry.index.count/3,528);assert.equal(sky.material.depthWrite,false);assert.equal(sky.material.depthTest,true);assert.equal(sky.userData.excludeFromBounds,true);assert.equal(sky.userData.visualOnly,true);assert.equal(sky.frustumCulled,false);
  assert.equal(new THREE.Raycaster(new THREE.Vector3(0,0,2),new THREE.Vector3(0,0,-1)).intersectObject(sky).length,0);
  layer.update(0);const p=sky.material.uniforms.cloudTravel.value.clone();layer.update(4);assert.ok(p.distanceTo(sky.material.uniforms.cloudTravel.value)>0);
  const other=new SceneClouds(new THREE.Scene());other.configure(e,.5);let disposed=0;for(const item of [sky.geometry,sky.material,sky.material.uniforms.cloudNoise.value])item.addEventListener('dispose',()=>disposed++);
  layer.configure(e,.5);assert.equal(scene.getObjectByName(sky.name),sky);assert.equal(disposed,0);
  layer.configure(null,0);layer.dispose();assert.equal(disposed,3);assert.equal(other.active(),true);assert.deepEqual(source.geometry.getAttribute('position').array,before);
  other.dispose();source.geometry.dispose();source.material.dispose();
});
test('cloud seed replacement releases only its own texture; disabled and omitted configurations release the sky',()=>{
  const scene=new THREE.Scene(),e=environmentPreset('land-day-v1'),layer=new SceneClouds(scene);layer.configure(e,0);const mesh=scene.children[0],texture=mesh.material.uniforms.cloudNoise.value;let released=0;texture.addEventListener('dispose',()=>released++);
  e.atmosphere.clouds.seed++;layer.configure(e,0);assert.equal(released,1);assert.equal(scene.children[0],mesh);assert.notEqual(mesh.material.uniforms.cloudNoise.value,texture);
  e.atmosphere.clouds.enabled=false;layer.configure(e,0);assert.equal(scene.children.length,0);delete e.atmosphere.clouds;layer.configure(e,0);assert.equal(scene.children.length,0);layer.dispose();
});
test('cloud animation runs without water, pauses independently and restores preview and hidden clocks',()=>{
  const priorDocument=globalThis.document,priorPmrem=THREE.PMREMGenerator.prototype.fromEquirectangular;globalThis.document={hidden:false};
  // Only GPU prefiltering is stubbed here; the UI suite compiles and renders the actual shader.
  THREE.PMREMGenerator.prototype.fromEquirectangular=()=>new THREE.WebGLRenderTarget(1,1);
  const scene=new THREE.Scene(),sun=new THREE.DirectionalLight(),light=new THREE.HemisphereLight(),ground=new THREE.MeshStandardMaterial(),grass=new THREE.Texture();
  const renderer={shadowMap:{enabled:false},toneMapping:THREE.NoToneMapping,toneMappingExposure:1},r=new SceneEnvironmentRuntime(scene,renderer,sun,light,ground,grass),e=environmentPreset('land-day-v1');e.shadows.mode='off';
  const frame={mode:'local_plane',frameRevision:'local',origin:[0,0,0],unit:'m',axes:'X_EAST_Y_UP_Z_SOUTH'},target=new THREE.Vector3();
  try{
    r.configure(e,frame,null,[],null,true);assert.equal(r.playing(null,false),false);assert.equal(r.cloudsPlaying(null,false),true);assert.equal(r.cloudsPlaying(null,true),false);assert.equal(r.cloudsPlaying(true,true),true);
    assert.equal(r.beforeRender(0,target,false,true),true);assert.equal(r.beforeRender(10,target,false,true),false);r.beforeRender(40,target,false,true);assert.equal(r.status().phase,0);assert.equal(r.status().cloudPhase,.04);
    r.beforeRender(50,target,false,false);r.beforeRender(10000,target,false,true);assert.equal(r.status().cloudPhase,.04);
    r.preview(true);r.beforeRender(10040,target,false,true);r.beforeRender(10080,target,false,true);assert.equal(r.status().cloudPhase,.08);r.preview(false);r.beforeRender(20000,target,false,true);assert.equal(r.status().cloudPhase,.04);
    r.suspend();r.beforeRender(320000,target,false,true);assert.equal(r.status().cloudPhase,.04);r.beforeRender(320040,target,false,true);assert.equal(r.status().cloudPhase,.08);
    e.atmosphere.clouds.speedMps=0;r.configure(e,frame,null,[],null,true);assert.equal(r.cloudsPlaying(true,false),false);
    r.configure(null,frame,null,[],null,true);assert.equal(r.status().clouds,false);assert.equal(scene.getObjectByName('visual-clouds-not-placement'),undefined);
  }finally{r.dispose();ground.dispose();grass.dispose();globalThis.document=priorDocument;THREE.PMREMGenerator.prototype.fromEquirectangular=priorPmrem;}
});
