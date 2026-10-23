import test from 'node:test';import assert from 'node:assert/strict';import * as THREE from 'three';
import {EnvironmentClock,environmentPreset,waterSurfaceSupported} from '../src/sceneEnvironment.ts';
import {rippleNormals,shadowCandidates,SceneEnvironmentRuntime} from '../src/sceneEnvironmentRuntime.ts';
import {commitScene,sceneHistory,duplicateAt} from '../src/sceneState.ts';
const frame={mode:'local_plane',frameRevision:'local',origin:[0,0,0],unit:'m',axes:'X_EAST_Y_UP_Z_SOUTH'};
test('environment presets are independent and only offshore requests visual water',()=>{
  const land=environmentPreset('land-day-v1'),sea=environmentPreset('offshore-overview-v1');sea.color.exposure=2;
  assert.equal(land.color.exposure,1);assert.equal(land.water.enabled,false);assert.equal(sea.water.enabled,true);assert.equal(sea.water.amplitudeM,0);
  assert.equal(environmentPreset('dusk-v1').lighting.sun.elevationDeg,12);
  assert.equal(environmentPreset('offshore-overview-v1').atmosphere.fog.mode,'off');
});
test('preview cancellation restores the original visible clock; allocation failure keeps static display usable',()=>{
  const prior=globalThis.document;globalThis.document={hidden:true};
  const scene=new THREE.Scene(),sun=new THREE.DirectionalLight(),light=new THREE.HemisphereLight(),ground=new THREE.MeshStandardMaterial(),grass=new THREE.Texture();
  const renderer={shadowMap:{enabled:false},toneMapping:THREE.NoToneMapping,toneMappingExposure:1};
  const runtime=new SceneEnvironmentRuntime(scene,renderer,sun,light,ground,grass),e=environmentPreset('land-day-v1');e.shadows.mode='off';
  try{
    runtime.configure(e,frame,null,[],null,true);runtime.beforeRender(0,new THREE.Vector3(),true);runtime.beforeRender(40,new THREE.Vector3(),true);
    runtime.preview(true);runtime.beforeRender(10000,new THREE.Vector3(),true);runtime.beforeRender(10040,new THREE.Vector3(),true);assert.equal(runtime.status().phase,.08);
    runtime.preview(false);runtime.beforeRender(50000,new THREE.Vector3(),true);assert.equal(runtime.status().phase,.04);
    globalThis.document.hidden=false;assert.doesNotThrow(()=>runtime.configure(e,frame,null,[],null,true));assert.equal(runtime.status().fallback,true);
    assert.equal(renderer.shadowMap.enabled,false);assert.equal(scene.environment,null);assert.equal(runtime.playing(true,false),false);
    runtime.configure(null,frame,null,[],null,true);assert.equal(renderer.toneMapping,THREE.NoToneMapping);assert.equal(renderer.toneMappingExposure,1);
    runtime.dispose();runtime.dispose();assert.equal(sun.target.parent,null);
  }finally{runtime.dispose();ground.dispose();grass.dispose();globalThis.document=prior;}
});
test('visible-time clock excludes pause, hidden intervals and the first recovery sample',()=>{
  const c=new EnvironmentClock(4);assert.equal(c.step(100,true),4);assert.equal(c.step(140,true),4.04);
  c.suspend();assert.equal(c.step(300140,true),4.04);assert.equal(c.step(300180,true),4.08);
  c.step(300200,false);assert.equal(c.step(400000,true),4.08);assert.equal(c.step(400050,true),4.13);
});
test('water availability uses the fixed relative source, not names or sea-colored imagery',()=>{
  const terrain={displayName:'ocean',report:{source:{heightRangeM:[0,0]}}};
  assert.equal(waterSurfaceSupported(frame,terrain),false);
  assert.equal(waterSurfaceSupported({...frame,mode:'projected_site',verticalDatum:'EGM2008'},terrain),false);
  const relative={...frame,mode:'projected_site',verticalDatum:'UNKNOWN_RELATIVE'};
  assert.equal(waterSurfaceSupported(relative,terrain),true);terrain.report.source.heightRangeM=[0,1];assert.equal(waterSurfaceSupported(relative,terrain),false);
});
test('normal texture is deterministic data, uses no color transform and owns no geometry',()=>{
  const a=rippleNormals(771),b=rippleNormals(771),c=rippleNormals(772);assert.deepEqual(a.image.data,b.image.data);assert.notDeepEqual(a.image.data,c.image.data);
  assert.equal(a.colorSpace,THREE.NoColorSpace);assert.equal(a.image.width,256);[a,b,c].forEach(v=>v.dispose());
});
test('one local shadow budget bounds both instance and triangle cost',()=>{
  const roots=Array.from({length:20},(_,i)=>{const root=new THREE.Group();root.position.x=i*10;root.add(new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshStandardMaterial()));root.updateMatrixWorld(true);return root;});
  const r=shadowCandidates(roots,new THREE.Vector3(),500,roots[15]);assert.equal(r.roots.length,8);assert.equal(r.roots[0],roots[15]);assert.ok(r.triangles<=250000);
  const huge=new THREE.Group(),g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.BufferAttribute(new Float32Array(250001*9),3));huge.add(new THREE.Mesh(g,new THREE.MeshStandardMaterial()));
  assert.equal(shadowCandidates([huge],new THREE.Vector3(),500,huge).roots.length,0);
  [...roots,huge].forEach(root=>root.traverse(o=>{if(o instanceof THREE.Mesh){o.geometry.dispose();o.material.dispose();}}));
});
test('environment-only history preserves instance and geometry identities and legacy omission',()=>{
  const old={displayName:'test',coordinateFrame:frame,terrain:null,instances:[],initialView:{eye:[3,4,5],target:[0,0,0]},defaults:{background:'plain',lighting:'neutral',terrainMaterial:'solid'}};
  const e=environmentPreset('land-day-v1'),h=commitScene(sceneHistory(old),{...old,environment:e});assert.deepEqual(h.present.coordinateFrame,old.coordinateFrame);assert.deepEqual(h.present.instances,[]);assert.ok(!('environment'in h.past[0]));
});
