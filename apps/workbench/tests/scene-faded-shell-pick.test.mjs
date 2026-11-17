import assert from 'node:assert/strict';
import test from 'node:test';
import * as THREE from 'three';
import {SceneCabinetAppearance} from '../src/sceneCabinetAppearance.ts';
import {sceneModelRayHit} from '../src/sceneComponentPick.ts';

const component=(key,indices,quality='source_candidate')=>({componentKey:key,nodeIndices:indices,geometryQuality:quality});
function fixture({id='instance-A',proxy=false}={}){
  const models=new THREE.Group(),root=new THREE.Group(),modelVersionId='fixed-model';models.add(root);
  root.userData={sceneModelInstanceId:id,ontoVisModelVersionId:modelVersionId};
  const tags={sceneModelInstanceId:id,ontoVisModelVersionId:modelVersionId};
  const shell=new THREE.Mesh(new THREE.BoxGeometry(4,4,.4),new THREE.MeshStandardMaterial());shell.position.z=2;
  shell.userData={...tags,ontoVisNodeIndex:0,ontoVisComponentKey:'source-tower',component:'tower'};
  const cabinet=new THREE.Mesh(new THREE.BoxGeometry(1,1,1),new THREE.MeshStandardMaterial());
  cabinet.userData={...tags,ontoVisComponentKey:'CT',...(proxy?{ontoVisProxySchematic:true}:{ontoVisNodeIndex:1})};
  root.add(shell,cabinet);
  const appearance=new SceneCabinetAppearance(root,{modelVersionId,components:[component('source-tower',[0]),component('CT',proxy?[]:[1],proxy?'proxy_schematic':'source_candidate')]});
  const ray=new THREE.Raycaster(new THREE.Vector3(0,0,10),new THREE.Vector3(0,0,-1));
  const hits=()=>{models.updateMatrixWorld(true);return ray.intersectObject(models,true);};
  const picking={instanceId:id,isFadedOccluder:(object,index)=>appearance.isFadedOccluder(object,index)};
  return {models,root,shell,cabinet,appearance,hits,picking};
}

test('a real ray reaches the source or proxy cabinet behind the deliberately faded enclosing shell',()=>{
  for(const proxy of [false,true]){
    const f=fixture({proxy});
    assert.equal(f.hits()[0].object,f.shell);
    assert.equal(sceneModelRayHit(f.hits(),f.models,f.picking).component.componentKey,'source-tower');
    f.appearance.apply(['CT'],'#007e6d');
    assert.equal(f.hits()[0].object,f.shell,'Transparency changes appearance; the raw ray still hits the shell first');
    const result=sceneModelRayHit(f.hits(),f.models,f.picking);
    assert.deepEqual(result.component,{sceneModelInstanceId:'instance-A',modelVersionId:'fixed-model',componentKey:'CT'});
    f.appearance.dispose();
  }
});

test('ordinary instance selection and another instance retain their shell intersections',()=>{
  const a=fixture(),b=fixture({id:'instance-B'});a.appearance.apply(['CT'],'#007e6d');b.appearance.apply(['CT'],'#007e6d');
  assert.equal(sceneModelRayHit(a.hits(),a.models).component.componentKey,'source-tower');
  assert.equal(sceneModelRayHit(b.hits(),b.models,a.picking).component.componentKey,'source-tower');
  assert.equal(a.appearance.isFadedOccluder(b.shell),false);
  assert.equal(sceneModelRayHit(a.hits(),a.models,{...a.picking,instanceId:'other-instance'}).component.componentKey,'source-tower');
  a.appearance.dispose();b.appearance.dispose();
});

test('restoring or disposing the temporary display immediately restores normal component picking',()=>{
  const f=fixture();
  for(const clear of [()=>f.appearance.restore(),()=>f.appearance.dispose()]){
    f.appearance.apply(['CT'],'#007e6d');assert.equal(sceneModelRayHit(f.hits(),f.models,f.picking).component.componentKey,'CT');
    clear();assert.equal(f.appearance.isFadedOccluder(f.shell),false);
    assert.equal(sceneModelRayHit(f.hits(),f.models,f.picking).component.componentKey,'source-tower');
  }
});

test('selecting the shell itself highlights it without making it pass through the ray',()=>{
  const f=fixture();f.appearance.apply(['CT'],'#007e6d');f.appearance.apply(['source-tower'],'#007e6d');
  assert.equal(f.appearance.isFadedOccluder(f.shell),false);assert.equal(f.shell.material.emissiveIntensity,.25);
  assert.equal(sceneModelRayHit(f.hits(),f.models,f.picking).component.componentKey,'source-tower');f.appearance.dispose();
});

test('generic transparency or a replaced material cannot be mistaken for an owned faded occluder',()=>{
  const f=fixture(),original=f.shell.material;original.opacity=.2;original.transparent=true;original.depthWrite=false;
  assert.equal(f.appearance.isFadedOccluder(f.shell),false);
  assert.equal(sceneModelRayHit(f.hits(),f.models,f.picking).component.componentKey,'source-tower');
  f.appearance.apply(['CT'],'#007e6d');assert.equal(f.appearance.isFadedOccluder(f.shell),true);
  f.shell.material=original;assert.equal(f.appearance.isFadedOccluder(f.shell),false);
  assert.equal(sceneModelRayHit(f.hits(),f.models,f.picking).component.componentKey,'source-tower');f.appearance.dispose();
});

test('a ray hitting an unchanged opaque face of a material array does not pass through that face',()=>{
  const f=fixture(),standard=new THREE.MeshStandardMaterial(),basic=new THREE.MeshBasicMaterial();
  f.shell.material=[standard,standard,standard,standard,basic,standard];f.appearance.apply(['CT'],'#007e6d');
  const hit=f.hits()[0];assert.equal(hit.object,f.shell);assert.equal(hit.face.materialIndex,4);
  assert.equal(f.appearance.isFadedOccluder(f.shell,0),true);
  assert.equal(f.appearance.isFadedOccluder(f.shell,hit.face.materialIndex),false);
  assert.equal(sceneModelRayHit(f.hits(),f.models,f.picking).component.componentKey,'source-tower');f.appearance.dispose();
});
