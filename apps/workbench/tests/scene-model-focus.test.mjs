import assert from 'node:assert/strict';
import test from 'node:test';
import {Box3,BoxGeometry,Group,Mesh,MeshBasicMaterial,PerspectiveCamera,Raycaster,Vector3} from 'three';
import {SceneModelSelectionBoxes,selectedModelBounds,selectedModelView,terrainSafeView} from '../src/sceneModelFocus.ts';
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
test('multi-selection keeps an individual visible position box for each selected model',()=>{
  const scene=new Group(),entries=new Map([['a',model(-20,0,0)],['b',model(30,10,20)]]),selection=new SceneModelSelectionBoxes(scene);
  selection.update(entries,['a','b']);assert.equal(selection.helpers.size,2);
  for(const [id,helper] of selection.helpers){
    assert.deepEqual(helper.box,new Box3().setFromObject(entries.get(id).root));
    assert.equal(helper.material.depthTest,false);assert.equal(helper.material.depthWrite,false);
  }
  const first=selection.helpers.get('a');entries.get('a').root.position.x=40;selection.update(entries,['a','b']);
  assert.equal(selection.helpers.get('a'),first);assert.equal(first.box.getCenter(new Vector3()).x,40);
  selection.dispose();assert.equal(scene.children.length,0);
});
test('hidden/deselected model boxes are released once without touching shared source geometry',()=>{
  const scene=new Group(),entries=new Map([['a',model(0,0,0)],['b',model(30,0,0)]]),selection=new SceneModelSelectionBoxes(scene);
  let sourceDisposed=0,boxDisposed=0;entries.get('a').root.children[0].geometry.addEventListener('dispose',()=>sourceDisposed++);
  selection.update(entries,['a','b']);const first=selection.helpers.get('a');first.geometry.addEventListener('dispose',()=>boxDisposed++);
  entries.get('a').root.visible=false;selection.update(entries,['a','b']);assert.equal(selection.helpers.size,1);assert.equal(boxDisposed,1);
  selection.update(entries,[]);selection.dispose();selection.dispose();assert.equal(selection.helpers.size,0);assert.equal(sourceDisposed,0);assert.equal(boxDisposed,1);
});
test('single selection and missing model ids never allocate an unrelated multi-selection outline',()=>{
  const scene=new Group(),entries=new Map([['a',model(0,0,0)]]),selection=new SceneModelSelectionBoxes(scene);
  selection.update(entries,['a']);assert.equal(selection.helpers.size,0);
  selection.update(entries,['missing','missing']);assert.equal(selection.helpers.size,0);selection.dispose();
});

test('arrival frames the central three assets at a low angle without hiding the wider scene',async()=>{
 const {arrivalModelView}=await import('../src/sceneModelFocus.ts');
 const entries=new Map();
 for(let i=0;i<7;i++){const root=new Group();root.add(new Mesh(new BoxGeometry(10,80,10)));root.position.set(i*100,40,0);entries.set(String(i),{root});}
 const camera=new PerspectiveCamera(42,16/9,.1,100000),ids=[...entries.keys()];
 const all=selectedModelView(camera,selectedModelBounds(entries,ids),new Vector3(1,1,1));
 const close=arrivalModelView(camera,entries,ids,new Vector3(1,1,1));
 assert.ok(new Vector3(...close.eye).distanceTo(new Vector3(...close.target))<new Vector3(...all.eye).distanceTo(new Vector3(...all.target)));
 assert.deepEqual(close.target,[300,40,0]);
 const direction=new Vector3(...close.eye).sub(new Vector3(...close.target));assert.ok(Math.abs(direction.y/Math.hypot(direction.x,direction.z)-.35)<1e-12);
 assert.ok([...entries.values()].every(item=>item.root.visible));assert.equal(arrivalModelView(camera,entries,[],direction),null);
});

test('inspection cameras rise above original terrain and clear a foreground ridge without moving the terrain or target',()=>{
 const terrain=new Mesh(new BoxGeometry(4,12,4),new MeshBasicMaterial());terrain.position.y=6;terrain.updateMatrixWorld(true);
 const source={eye:[0,2,10],target:[0,1,-10]},before=structuredClone(source),matrix=terrain.matrixWorld.clone();
 const safe=terrainSafeView(source,terrain),eye=new Vector3(...safe.eye),target=new Vector3(...safe.target),ray=new Raycaster(eye,target.clone().sub(eye).normalize(),0,eye.distanceTo(target)-.5);
 assert.ok(safe.eye[1]>source.eye[1]);assert.equal(ray.intersectObject(terrain,false).length,0);
 assert.deepEqual(safe.target,source.target);assert.deepEqual(source,before);assert.deepEqual(terrain.matrixWorld.elements,matrix.elements);
 const below={eye:[0,-3,0],target:[0,20,-10]},raised=terrainSafeView(below,terrain);assert.ok(raised.eye[1]>=14);
 terrain.visible=false;assert.equal(terrainSafeView(source,terrain),source);assert.equal(terrainSafeView(source,null),source);
 terrain.geometry.dispose();terrain.material.dispose();
});
