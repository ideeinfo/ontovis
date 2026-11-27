import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {SceneModelView} from '../src/sceneModelView.ts';
function fixture(){
  const root=new THREE.Group();root.userData.sceneModelInstanceId='instance';
  const parts=new THREE.Group();parts.rotation.y=.35;root.add(parts);
  const material=new THREE.MeshStandardMaterial();
  const add=(name,size,position,parent=parts)=>{const mesh=new THREE.Mesh(new THREE.BoxGeometry(...size),material);mesh.name=name;mesh.position.set(...position);parent.add(mesh);return mesh;};
  add('tower',[2,80,2],[0,40,0]);
  const shell=add('shell',[8,8,18],[0,90,0]);
  add('generator',[2,3,4],[2,0,0],shell);
  add('rotor',[4,45,2],[0,90,-12]);
  const version={modelVersionId:'version',contentRevision:'rev',sha256:'a'.repeat(64),calibration:{state:'verified'},representationType:'detailed'};
  const request={instanceId:'instance',modelVersionId:'version',contentRevision:'rev',sha256:version.sha256,mode:'exploded'};
  const meshes=[];root.traverse(node=>{if(node.isMesh)meshes.push(node);});
  return {root,meshes,shell,material,version,request};
}
const localCentres=f=>{f.root.updateWorldMatrix(true,true);return f.meshes.map(mesh=>f.root.worldToLocal(mesh.getWorldPosition(new THREE.Vector3())).toArray());};
test('schematic explosion is invariant under installation translation, rotation and scale, including nested meshes',()=>{
  const a=fixture(),b=fixture(),before=a.meshes.map(mesh=>mesh.position.toArray());
  b.root.position.set(1200,600,300);b.root.rotation.y=1.8;b.root.scale.set(2,3,2);
  const ra=SceneModelView.create(a.root,a.version,a.request),rb=SceneModelView.create(b.root,b.version,b.request);
  assert.ok(ra);assert.ok(rb);
  const pa=localCentres(a),pb=localCentres(b);
  for(let i=0;i<pa.length;i++)for(let j=0;j<3;j++)assert.ok(Math.abs(pa[i][j]-pb[i][j])<1e-8);
  assert.deepEqual(a.meshes[0].position.toArray(),before[0]);
  ra.dispose();rb.dispose();assert.deepEqual(a.meshes.map(mesh=>mesh.position.toArray()),before);
});
test('nested shell fading restores every original material once and keeps borrowed material intact',()=>{
  const f=fixture();f.meshes[2].name='inner-shell';
  const internal=new THREE.Mesh(new THREE.BoxGeometry(1,1,1),f.material);internal.name='gearbox';internal.position.y=90;f.root.add(internal);
  const rig=SceneModelView.create(f.root,f.version,{...f.request,mode:'xray'});
  assert.ok(rig);const view=rig;
  assert.notEqual(f.shell.material,f.material);assert.equal(f.material.opacity,1);
  view.dispose();for(const mesh of f.meshes)assert.equal(mesh.material,f.material);
});
test('appearance or undeclared models cannot infer internals from bounding boxes',()=>{
  const f=fixture(),before=localCentres(f);
  for(const representationType of ['appearance',null,undefined])assert.equal(SceneModelView.create(f.root,{...f.version,representationType},f.request),null);
  assert.deepEqual(localCentres(f),before);
});
