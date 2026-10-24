import test from 'node:test';import assert from 'node:assert/strict';import * as THREE from 'three';
import {SceneSurroundings,surroundingGeometry} from '../src/sceneSurroundings.ts';
import {environmentPreset} from '../src/sceneEnvironment.ts';
const source=()=>{const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute([100,12,200,120,12,200,120,12,220,100,12,220,-1e9,999,-1e9],3));g.setIndex([0,2,1,0,3,2]);return g;};
const terrain=()=>{const t=new THREE.Mesh(source(),new THREE.MeshBasicMaterial({side:THREE.DoubleSide}));t.position.set(300,40,500);t.updateMatrixWorld(true);return t;};
test('new presets opt in with a stable sea/land basis while omitted old environments stay off',()=>{
 for(const id of ['land-day-v1','dusk-v1','offshore-overview-v1'])assert.deepEqual(environmentPreset(id).surroundings,{mode:'auto',profile:id==='offshore-overview-v1'?'offshore':'land'});
 const e=environmentPreset('offshore-overview-v1');e.presetId='custom-v1';e.water.enabled=false;assert.equal(e.surroundings.profile,'offshore');
 const layer=new SceneSurroundings(new THREE.Scene()),t=terrain();delete e.surroundings;layer.configure(e,t,null,true);assert.equal(layer.status(),null);t.geometry.dispose();t.material.dispose();
});
test('coarse background excludes masked unreferenced vertices and never changes source arrays or bounds',()=>{
 const s=source(),before=s.getAttribute('position').array.slice(),indices=s.index.array.slice(),g=surroundingGeometry(s,true);assert.ok(g);assert.equal(g.getAttribute('position').count,129*9);assert.equal(g.index.count/3,2048);
 const p=g.getAttribute('position');for(let i=0;i<p.count;i++){assert.ok(Number.isFinite(p.getX(i))&&Math.abs(p.getX(i)-110)<800000);assert.equal(p.getY(i),12);}
 assert.deepEqual(s.getAttribute('position').array,before);assert.deepEqual(s.index.array,indices);assert.equal(s.boundingBox,null);g.dispose();s.dispose();
});
test('display mesh borrows placement transform but is non-pickable, opaque and behind the original surface without writing depth',()=>{
 const scene=new THREE.Scene(),t=terrain(),layer=new SceneSurroundings(scene),e=environmentPreset('land-day-v1');scene.add(t);layer.configure(e,t,null,true);const bg=scene.getObjectByName('visual-surroundings-not-placement');assert.ok(bg);assert.deepEqual(bg.matrix.elements,t.matrixWorld.elements);assert.ok(bg.renderOrder<t.renderOrder);assert.equal(bg.material.depthWrite,false);assert.equal(bg.material.transparent,false);assert.equal(bg.castShadow,false);assert.equal(bg.receiveShadow,false);
 const ray=new THREE.Raycaster(new THREE.Vector3(1000,10000,1000),new THREE.Vector3(0,-1,0));scene.updateMatrixWorld(true);assert.equal(ray.intersectObject(bg,true).length,0);assert.deepEqual(t.position.toArray(),[300,40,500]);layer.dispose();t.geometry.dispose();t.material.dispose();
});
test('off, original display, terrain hiding and resource preview release only owned background resources',()=>{
 for(const mode of ['off','legacy','hidden','preview']){const scene=new THREE.Scene(),t=terrain(),layer=new SceneSurroundings(scene),e=environmentPreset('offshore-overview-v1'),normal=new THREE.DataTexture(new Uint8Array(16),2,2);let original=0,textures=0,disposed=0;t.geometry.addEventListener('dispose',()=>original++);normal.addEventListener('dispose',()=>textures++);layer.configure(e,t,normal,true);const bg=scene.children[0];bg.geometry.addEventListener('dispose',()=>disposed++);bg.material.addEventListener('dispose',()=>disposed++);
 if(mode==='off')e.surroundings.mode='off';layer.configure(mode==='legacy'||mode==='preview'?null:e,t,normal,mode!=='hidden');layer.dispose();layer.dispose();assert.equal(scene.children.length,0);assert.equal(disposed,2);assert.equal(original,0);assert.equal(textures,0);t.geometry.dispose();t.material.dispose();normal.dispose();}
});
test('repeated preview changes reuse bounded geometry; two viewports own independent display resources',()=>{
 const a=new THREE.Scene(),b=new THREE.Scene(),t=terrain(),e=environmentPreset('land-day-v1'),x=new SceneSurroundings(a),y=new SceneSurroundings(b);x.configure(e,t,null,true);y.configure(e,t,null,true);const mesh=a.children[0],other=b.children[0];assert.notEqual(mesh.geometry,other.geometry);assert.notEqual(mesh.material,other.material);e.color.exposure=1.3;x.configure(e,t,null,true);assert.equal(a.children.length,1);assert.equal(a.children[0],mesh);x.dispose();assert.equal(b.children.length,1);assert.equal(y.status(),'land');y.dispose();t.geometry.dispose();t.material.dispose();
});
test('missing or degenerate original geometry never invents a positioning area',()=>{
 const g=new THREE.BufferGeometry();assert.equal(surroundingGeometry(g,false),null);g.setAttribute('position',new THREE.Float32BufferAttribute([0,0,0,1,0,0],3));assert.equal(surroundingGeometry(g,false),null);g.dispose();const layer=new SceneSurroundings(new THREE.Scene());layer.configure(environmentPreset('land-day-v1'),null,null,true);assert.equal(layer.status(),null);layer.dispose();
});

test('a replaced water normal is adopted by the surrounding sea without disposing either borrowed texture',()=>{
 const scene=new THREE.Scene(),t=terrain(),e=environmentPreset('offshore-overview-v1'),layer=new SceneSurroundings(scene),a=new THREE.DataTexture(new Uint8Array(16),2,2),b=new THREE.DataTexture(new Uint8Array(16),2,2);let borrowed=0,released=0;
 a.addEventListener('dispose',()=>borrowed++);b.addEventListener('dispose',()=>borrowed++);layer.configure(e,t,a,true);const before=scene.children[0];before.material.addEventListener('dispose',()=>released++);layer.configure(e,t,b,true);const after=scene.children[0];assert.notEqual(before,after);assert.equal(released,1);assert.equal(after.material.normalMap,b);layer.dispose();assert.equal(borrowed,0);a.dispose();b.dispose();t.geometry.dispose();t.material.dispose();
});
test('both source-colored land and water surroundings participate in scene fog',()=>{
 const scene=new THREE.Scene(),t=terrain(),layer=new SceneSurroundings(scene),normal=new THREE.DataTexture(new Uint8Array(16),2,2);
 for(const profile of ['land-day-v1','offshore-overview-v1']){layer.configure(environmentPreset(profile),t,normal,true);assert.equal(scene.children[0].material.fog,true);}
 layer.dispose();t.geometry.dispose();t.material.dispose();normal.dispose();
});
