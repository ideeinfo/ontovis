import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {sanitizeModelLogos,modelLogoRetiredResources} from '../src/sceneResourceCache.ts';
import {MOTION_MODEL_SHA} from '../src/motionProfiles.ts';
const tu22kSha='91b36e5bf0c5829cd77b1917a3e69a7f8c52fe8c39bbc7b42874e24ba98b6634';
function installImage(t,Image){
  const prior=Object.getOwnPropertyDescriptor(globalThis,'Image');
  Object.defineProperty(globalThis,'Image',{configurable:true,writable:true,value:Image});
  t.after(()=>{if(prior)Object.defineProperty(globalThis,'Image',prior);else delete globalThis.Image;});
}
function fixture(name){
  const root=new THREE.Group(),texture=new THREE.Texture({close(){throw Error('live texture must not be closed');}});
  const material=new THREE.MeshStandardMaterial({map:texture}),geometry=new THREE.BufferGeometry();
  geometry.setAttribute('position',new THREE.Float32BufferAttribute([
    2,91.56,3.15,2,91.56,-1.75,2,90.34,3.15,2,90.34,-1.75,
    -2,91.56,-1.75,-2,91.56,3.15,-2,90.34,-1.75,-2,90.34,3.15],3));
  const logo=new THREE.Mesh(geometry,material),body=new THREE.Mesh(geometry,material);
  logo.name=name;body.name='shell';root.add(logo,body);return {root,logo,body,material,geometry,texture};
}
test('unknown files with matching node names or texture labels are preserved',async()=>{
  const f=fixture('Static:nacelle:20');f.texture.name='terraursa';
  await sanitizeModelLogos(f.root,'a'.repeat(64));
  assert.equal(f.logo.visible,true);assert.equal(f.body.material,f.material);assert.equal(f.material.visible,true);
});
test('hiding a known TU-22K decal never hides the shared shell material',async()=>{
  const f=fixture('Static:nacelle:20');f.texture.name='terraursa-structure';
  await sanitizeModelLogos(f.root,tu22kSha);
  assert.equal(f.logo.visible,false);assert.equal(f.body.visible,true);
  assert.equal(f.material.visible,true);assert.equal(f.material.opacity,1);assert.equal(f.material.map,f.texture);
});
test('a failed logo image load preserves the existing texture, geometry and materials',async t=>{
  const f=fixture('Static:nacelle:10');
  installImage(t,class {set src(_){queueMicrotask(()=>this.onerror());}});
  await sanitizeModelLogos(f.root,MOTION_MODEL_SHA);
  assert.equal(f.logo.material,f.material);assert.equal(f.logo.geometry,f.geometry);assert.equal(f.material.map,f.texture);
});
test('successful replacement owns cloned decal resources and leaves shared resources alive',async t=>{
  const f=fixture('Static:nacelle:10');let disposed=0;
  f.texture.addEventListener('dispose',()=>disposed++);
  installImage(t,class {set src(_){queueMicrotask(()=>this.onload());}});
  await sanitizeModelLogos(f.root,MOTION_MODEL_SHA);
  assert.notEqual(f.logo.material,f.material);assert.notEqual(f.logo.geometry,f.geometry);
  assert.equal(f.body.material,f.material);assert.equal(f.body.geometry,f.geometry);
  assert.equal(f.material.map,f.texture);assert.equal(disposed,0);
  assert.ok(modelLogoRetiredResources(f.root).has(f.material));
  f.logo.geometry.computeBoundingBox();const box=f.logo.geometry.boundingBox;
  assert.ok(Math.abs((box.max.z-box.min.z)/(box.max.y-box.min.y)-2170/725)<1e-5);
  assert.ok(Math.abs(box.max.y-box.min.y-1.6)<1e-5);
});
