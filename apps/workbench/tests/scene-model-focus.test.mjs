import assert from 'node:assert/strict';
import test from 'node:test';
import {Box3,BoxGeometry,Group,Mesh,MeshBasicMaterial,PerspectiveCamera,Vector3} from 'three';
import {selectedModelBounds,selectedModelView} from '../src/sceneModelFocus.ts';
import {selectSceneScope} from '../src/sceneOrganization.ts';

function model(x,y,z){const root=new Group();root.add(new Mesh(new BoxGeometry(20,145,30),new MeshBasicMaterial()));root.position.set(x,y,z);return {root};}
test('model family selection supports mixed/all/clear states while retaining other families',()=>{
  const selection=['other','a'],scope=['a','b','c'];
  assert.deepEqual(selectSceneScope(selection,scope,true),['other','a','b','c']);
  assert.deepEqual(selectSceneScope(['other','a','b','c'],scope,false),['other']);
  assert.deepEqual(selectSceneScope(['other'],[],true),['other']);
  assert.deepEqual(selection,['other','a']);assert.deepEqual(scope,['a','b','c']);
});
test('selected framing includes every instance world transform and excludes unselected regional content',()=>{
  const entries=new Map([['a',model(-1500,30,0)],['b',model(1200,80,700)],['far',model(100000,0,0)]]);
  const parent=new Group();parent.position.set(20,10,40);parent.rotation.y=.2;
  for(const entry of entries.values())parent.add(entry.root);
  const before=entries.get('a').root.position.clone();
  const actual=selectedModelBounds(entries,['a','b','missing','a']);
  assert.deepEqual(actual,new Box3().setFromObject(entries.get('a').root).union(new Box3().setFromObject(entries.get('b').root)));
  assert.ok(actual.max.x<10000);assert.deepEqual(entries.get('a').root.position,before);
});
test('hidden and unavailable instances cannot send framing to a remote placeholder or terrain',()=>{
  const hidden=model(50000,0,0);hidden.root.visible=false;
  const entries=new Map([['hidden',hidden]]),box=selectedModelBounds(entries,['hidden','missing']);
  assert.ok(box.isEmpty());assert.equal(selectedModelView(new PerspectiveCamera(),box,new Vector3()),null);
});
for(const aspect of [2,.45])test(`all selected bounds remain in the camera at aspect ${aspect}`,()=>{
  const box=new Box3(new Vector3(-1700,-20,-800),new Vector3(1300,240,900)),camera=new PerspectiveCamera(42,aspect,.05,2000000);
  const view=selectedModelView(camera,box,new Vector3(.9,.6,1.2));
  camera.position.fromArray(view.eye);camera.lookAt(new Vector3(...view.target));camera.updateMatrixWorld(true);camera.updateProjectionMatrix();
  for(const x of [box.min.x,box.max.x])for(const y of [box.min.y,box.max.y])for(const z of [box.min.z,box.max.z]){
    const projected=new Vector3(x,y,z).project(camera);assert.ok(Math.abs(projected.x)<1);assert.ok(Math.abs(projected.y)<1);assert.ok(projected.z<1&&projected.z>-1);
  }
});
test('degenerate camera direction and point bounds still produce a finite usable view',()=>{
  const box=new Box3(new Vector3(10,20,30),new Vector3(10,20,30));
  const view=selectedModelView(new PerspectiveCamera(42,1,.05,2000000),box,new Vector3());
  assert.deepEqual(view.target,[10,20,30]);assert.ok(view.eye.every(Number.isFinite));
  assert.ok(new Vector3(...view.eye).distanceTo(new Vector3(...view.target))>=2.99);
});
