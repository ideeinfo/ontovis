import assert from 'node:assert/strict';
import test from 'node:test';
import * as THREE from 'three';
import {SceneCabinetAppearance} from '../src/sceneCabinetAppearance.ts';

const component=(key,nodeIndices,quality='source_candidate')=>({componentKey:key,nodeIndices,
  geometryQuality:quality,bounds:[[0,0,0],[1,1,1]],displayName:key,keyStability:'version_local'});
const version=()=>({modelVersionId:'fixed-model',components:[component('CT',[1]),component('CN',[],'proxy_schematic')]});
const theme='#007e6d';
function fixture(id='instance-A',material=new THREE.MeshStandardMaterial({color:0x718275})) {
  const root=new THREE.Group();root.userData={sceneModelInstanceId:id,ontoVisModelVersionId:'fixed-model'};
  const geometry=new THREE.BoxGeometry(1,1,1);
  const mesh=(name,data)=>{
    const value=new THREE.Mesh(geometry,material);value.name=name;
    value.userData={sceneModelInstanceId:id,ontoVisModelVersionId:'fixed-model',...data};root.add(value);return value;
  };
  const cabinet=mesh('source-cabinet',{ontoVisComponentKey:'CT',ontoVisNodeIndex:1});
  const proxy=mesh('proxy-cabinet',{ontoVisComponentKey:'CN',ontoVisProxySchematic:true});
  const shell=mesh('source-shell',{ontoVisNodeIndex:10,component:'tower'});
  const interior=mesh('source-interior',{ontoVisNodeIndex:11,component:'generator'});
  return {root,geometry,material,cabinet,proxy,shell,interior,effect:new SceneCabinetAppearance(root,version())};
}
const disposed=value=>{
  const state={count:0};value.addEventListener('dispose',()=>state.count++);return state;
};

test('one instance borrows cache data while its material effects leave another instance unchanged',()=>{
  const shared=new THREE.MeshStandardMaterial({color:0x87968a,emissive:0x102030,emissiveIntensity:.1});
  const a=fixture('instance-A',shared),b=fixture('instance-B',shared);
  a.effect.apply(['CT'],theme);
  assert.notEqual(a.cabinet.material,shared);assert.notEqual(a.shell.material,shared);
  assert.equal(a.cabinet.material.emissive.getHex(),new THREE.Color(theme).getHex());
  assert.equal(a.shell.material.opacity,.2);
  assert.equal(b.cabinet.material,shared);assert.equal(b.shell.material,shared);
  assert.equal(shared.emissive.getHex(),0x102030);assert.equal(shared.emissiveIntensity,.1);
  assert.equal(shared.opacity,1);assert.equal(shared.transparent,false);
  a.effect.restore();assert.equal(a.cabinet.material,shared);assert.equal(a.shell.material,shared);
  b.effect.dispose();a.effect.dispose();
});

test('a material shared by a cabinet, shell and interior gets separate display roles only where needed',()=>{
  const f=fixture();f.effect.apply(['CT'],theme);
  assert.notEqual(f.cabinet.material,f.shell.material);
  assert.equal(f.cabinet.material.transparent,false);assert.equal(f.cabinet.material.opacity,1);
  assert.equal(f.cabinet.material.emissiveIntensity,.25);
  assert.equal(f.shell.material.transparent,true);assert.equal(f.shell.material.depthWrite,false);
  assert.equal(f.shell.material.opacity,.2);
  assert.equal(f.interior.material,f.material);assert.equal(f.proxy.material,f.material);
  assert.equal(f.interior.material.opacity,1);assert.equal(f.interior.material.emissiveIntensity,1);
  f.effect.dispose();
});

test('restore recovers the exact original material with nondefault alpha and lighting properties',()=>{
  const alpha=new THREE.Texture(),map=new THREE.Texture();
  const original=new THREE.MeshStandardMaterial({transparent:true,opacity:.63,depthWrite:false,
    alphaTest:.27,alphaMap:alpha,map,emissive:0x213243,emissiveIntensity:.73,side:THREE.DoubleSide});
  const f=fixture('instance-A',original);f.effect.apply(['CT'],theme);
  assert.equal(f.cabinet.material.alphaMap,alpha);assert.equal(f.cabinet.material.map,map);
  f.effect.restore();assert.equal(f.cabinet.material,original);assert.equal(f.shell.material,original);
  assert.equal(original.transparent,true);assert.equal(original.opacity,.63);assert.equal(original.depthWrite,false);
  assert.equal(original.alphaTest,.27);assert.equal(original.alphaMap,alpha);assert.equal(original.map,map);
  assert.equal(original.emissive.getHex(),0x213243);assert.equal(original.emissiveIntensity,.73);
  assert.equal(original.side,THREE.DoubleSide);f.effect.dispose();
});

test('changing from source cabinet to its schematic host releases the old highlight and reuses no child geometry',()=>{
  const f=fixture(),meshCount=f.root.children.length;f.effect.apply(['CT'],theme);
  const old=f.cabinet.material,oldDisposed=disposed(old);
  f.effect.apply(['CN'],theme);
  assert.equal(f.cabinet.material,f.material);assert.equal(oldDisposed.count,1);
  assert.notEqual(f.proxy.material,f.material);assert.equal(f.proxy.material.emissiveIntensity,.25);
  assert.equal(f.proxy.userData.ontoVisComponentKey,'CN');assert.equal(f.root.children.length,meshCount);
  f.effect.dispose();
});

test('the same focus is stable and repeated restore or disposal releases each owned material once',()=>{
  const f=fixture();f.effect.apply(['CT'],theme);
  const cabinet=f.cabinet.material,shell=f.shell.material;
  const cabinetDisposed=disposed(cabinet),shellDisposed=disposed(shell);
  f.effect.apply(['CT'],theme);
  assert.equal(f.cabinet.material,cabinet);assert.equal(f.shell.material,shell);
  assert.equal(cabinetDisposed.count,0);assert.equal(shellDisposed.count,0);
  f.effect.restore();f.effect.restore();f.effect.dispose();f.effect.dispose();
  assert.equal(cabinetDisposed.count,1);assert.equal(shellDisposed.count,1);
  assert.equal(f.cabinet.material,f.material);assert.equal(f.shell.material,f.material);
  f.effect.apply(['CT'],theme);assert.equal(f.cabinet.material,f.material);assert.equal(f.shell.material,f.material);
});

test('unknown, mixed or ambiguous catalog keys clear an earlier effect without fading any shell',()=>{
  const f=fixture();
  for(const keys of [[],['missing'],['CT','missing']]) {
    f.effect.apply(['CT'],theme);f.effect.apply(keys,theme);
    assert.equal(f.cabinet.material,f.material);assert.equal(f.shell.material,f.material);
  }
  const ambiguous=new SceneCabinetAppearance(f.root,{...version(),components:[component('CT',[1]),component('CT',[2])]});
  ambiguous.apply(['CT'],theme);assert.equal(f.cabinet.material,f.material);assert.equal(f.shell.material,f.material);
  ambiguous.dispose();f.effect.dispose();
});

test('a catalog entry without an actual trusted instance mesh never opens surrounding shells',()=>{
  for(const changed of [{ontoVisNodeIndex:undefined},{ontoVisNodeIndex:2},
    {ontoVisNodeIndex:undefined,ontoVisProxySchematic:true},{sceneModelInstanceId:'other-instance'},
    {ontoVisModelVersionId:'other-model'}]) {
    const f=fixture();Object.assign(f.cabinet.userData,changed);f.effect.apply(['CT'],theme);
    assert.equal(f.cabinet.material,f.material);assert.equal(f.shell.material,f.material);f.effect.dispose();
  }
});

test('shell names are display hints only on confirmed source nodes and never on proxy or untagged extras',()=>{
  const f=fixture();
  f.proxy.userData.component='tower';
  const untagged=new THREE.Mesh(f.geometry,f.material);untagged.userData={component:'nacelle'};f.root.add(untagged);
  f.shell.userData.ontoVisNodeIndex=undefined;f.effect.apply(['CT'],theme);
  assert.equal(f.shell.material,f.material);assert.equal(f.proxy.material,f.material);assert.equal(untagged.material,f.material);
  f.effect.restore();f.effect.apply(['CN'],theme);
  assert.notEqual(f.proxy.material,f.material);assert.equal(f.proxy.material.opacity,1);
  assert.equal(f.proxy.material.transparent,false);assert.equal(untagged.material,f.material);f.effect.dispose();
});

test('material arrays preserve unsupported materials and release no borrowed texture, geometry or cache material',()=>{
  const alpha=new THREE.Texture(),standard=new THREE.MeshStandardMaterial({alphaMap:alpha}),basic=new THREE.MeshBasicMaterial();
  const f=fixture(),original=[standard,basic];f.cabinet.material=original;f.shell.material=original;
  const textureDisposed=disposed(alpha),geometryDisposed=disposed(f.geometry),standardDisposed=disposed(standard),basicDisposed=disposed(basic);
  f.effect.apply(['CT'],theme);
  assert.notEqual(f.cabinet.material,original);assert.equal(f.cabinet.material[1],basic);
  assert.equal(f.cabinet.material[0].alphaMap,alpha);assert.equal(f.shell.material[0].opacity,.2);
  const cabinetDisposed=disposed(f.cabinet.material[0]),shellDisposed=disposed(f.shell.material[0]);
  f.effect.dispose();
  assert.equal(f.cabinet.material,original);assert.equal(f.shell.material,original);
  assert.equal(cabinetDisposed.count,1);assert.equal(shellDisposed.count,1);
  for(const state of [textureDisposed,geometryDisposed,standardDisposed,basicDisposed])assert.equal(state.count,0);
});

test('only the three existing source shell display hints fade while other source geometry retains its depth',()=>{
  const f=fixture(),shells=[f.shell];
  for(const [index,hint] of ['nacelle','rotor_cover','blade'].entries()) {
    const mesh=new THREE.Mesh(f.geometry,f.material);
    mesh.userData={sceneModelInstanceId:'instance-A',ontoVisModelVersionId:'fixed-model',ontoVisNodeIndex:12+index,component:hint};
    f.root.add(mesh);if(hint==='blade')assert.equal(mesh.material,f.material);else shells.push(mesh);
  }
  const nodes=[...f.root.children],blade=nodes.at(-1);f.effect.apply(['CT'],theme);
  for(const mesh of shells){assert.equal(mesh.material.opacity,.2);assert.equal(mesh.material.depthWrite,false);}
  assert.equal(blade.material,f.material);assert.equal(blade.material.depthWrite,true);
  f.effect.restore();for(const mesh of shells)assert.equal(mesh.material,f.material);
  assert.deepEqual(f.root.children,nodes);assert.equal(f.cabinet.geometry,f.geometry);f.effect.dispose();
});

test('isolating a mapped part ghosts its assembly without hiding descendants or touching other instances',()=>{
 const f=fixture(),other=fixture('instance-B',f.material);
 f.shell.add(f.cabinet);
 f.effect.apply(['CT'],theme,true);
 assert.equal(f.shell.visible,true);assert.equal(f.shell.material.visible,true);assert.equal(f.shell.material.opacity,.32);assert.equal(f.shell.material.depthWrite,false);
 assert.equal(f.cabinet.material.visible,true);assert.equal(f.interior.material.visible,true);assert.equal(f.interior.material.opacity,.5);
 assert.equal(f.effect.isFadedOccluder(f.shell),true);
 assert.equal(other.shell.material,f.material);assert.equal(f.material.visible,true);
 const hidden=f.shell.material,cleanup=disposed(hidden);
 f.effect.apply(['CT'],theme,false);
 assert.equal(cleanup.count,1);assert.equal(f.shell.material.visible,true);assert.equal(f.shell.material.opacity,.2);
 f.effect.restore();assert.equal(f.shell.material,f.material);assert.equal(f.cabinet.material,f.material);
 f.effect.dispose();other.effect.dispose();
});
test('unknown isolated selection restores all materials and does not leave a blank model',()=>{
 const f=fixture();f.effect.apply(['CT'],theme,true);f.effect.apply(['missing'],theme,true);
 for(const mesh of [f.cabinet,f.proxy,f.shell,f.interior])assert.equal(mesh.material,f.material);
 f.effect.dispose();
});

test('isolation ghosts basic materials and respects source opacity and hidden state',()=>{
 const material=new THREE.MeshBasicMaterial({transparent:true,opacity:.5}),f=fixture('instance-A',material);
 f.interior.material=material.clone();f.interior.material.visible=false;
 const original=f.interior.material;f.effect.apply(['CT'],theme,true);
 assert.equal(f.shell.material.opacity,.16);assert.equal(f.proxy.material.opacity,.25);
 assert.equal(f.interior.material.visible,false);assert.equal(f.cabinet.material.opacity,.5);
 assert.equal(f.effect.isFadedOccluder(f.proxy),true);assert.equal(f.effect.isFadedOccluder(f.cabinet),false);
 f.effect.restore();assert.equal(f.interior.material,original);assert.equal(f.shell.material,material);
});
