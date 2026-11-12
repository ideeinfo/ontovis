import assert from 'node:assert/strict';
import test from 'node:test';
import {cursorZoomView,visibleZoomHit} from '../src/sceneZoom.ts';
import * as THREE from 'three';
const distance=(a,b)=>Math.hypot(...a.map((v,i)=>v-b[i]));
const forward=v=>v.target.map((x,i)=>(x-v.eye[i])/distance(v.eye,v.target));
const close=(a,b)=>a.forEach((v,i)=>assert.ok(Math.abs(v-b[i])<1e-8,`${a} != ${b}`));

test('zoom reaches terrain beyond the old orbit center instead of converging in empty air',()=>{
 const start={eye:[0,10,10],target:[0,10,0]},surface=[0,10,-190];let view=start;
 for(let i=0;i<30;i++)view=cursorZoomView(view,[0,0,-1],.95,distance(view.eye,surface));
 assert.ok(view.eye[2]<start.target[2]);assert.ok(distance(view.eye,surface)<45);
 close(forward(view),[0,0,-1]);assert.deepEqual(start.eye,[0,10,10]);
});
test('off-center hit stays on the pointer ray and view orientation is preserved',()=>{
 const view={eye:[0,0,20],target:[0,0,0]},ray=[.6,0,-.8],hit=ray.map((v,i)=>view.eye[i]+v*100);
 const next=cursorZoomView(view,ray,.5,100);
 close(next.eye,[30,0,-20]);close(hit.map((v,i)=>(v-next.eye[i])/distance(hit,next.eye)),ray);
 close(forward(next),forward(view));
});
test('zoom out reverses a surface-directed zoom without jumping to the old orbit radius',()=>{
 const view={eye:[0,0,20],target:[0,0,0]},ray=[.6,0,-.8];
 const next=cursorZoomView(view,ray,.5,100),back=cursorZoomView(next,ray,2,50);
 close(back.eye,view.eye);close(forward(back),forward(view));
});
test('surface distance sets speed across overview, turbine and component scales',()=>{
 const view={eye:[0,0,20],target:[0,0,0]};
 for(const scale of [50_000,100,1]){
  const next=cursorZoomView(view,[0,0,-1],.9,scale);
  assert.ok(Math.abs(distance(next.eye,view.eye)-scale*.1)<1e-8);
 }
});
test('empty space, near limit and far limit stay finite and bounded',()=>{
 const view={eye:[0,0,20],target:[0,0,0]};
 const empty=cursorZoomView(view,[0,0,-1],.5);close(empty.eye,[0,0,10]);
 assert.equal(distance(cursorZoomView(view,[0,0,-1],.001,.1).eye,view.eye),0);
 assert.equal(distance(cursorZoomView(view,[0,0,-1],2,300_000).eye,view.eye),0);
 assert.equal(cursorZoomView(view,[0,0,-1],NaN),view);
});
test('actual raycasts ignore hidden ancestors and isolated material surfaces when zooming',()=>{
 const root=new THREE.Group(),hidden=new THREE.Group();root.add(hidden);
 const near=new THREE.Mesh(new THREE.PlaneGeometry(2,2),new THREE.MeshBasicMaterial());near.position.z=2;hidden.add(near);hidden.visible=false;
 const middle=new THREE.Mesh(near.geometry,new THREE.MeshBasicMaterial({visible:false}));middle.position.z=1;root.add(middle);
 const far=new THREE.Mesh(near.geometry,new THREE.MeshBasicMaterial());root.add(far);root.updateMatrixWorld(true);
 const hits=new THREE.Raycaster(new THREE.Vector3(0,0,3),new THREE.Vector3(0,0,-1)).intersectObject(root,true);
 assert.equal(hits[0].object,near);assert.equal(visibleZoomHit(hits)?.object,far);
 far.visible=false;assert.equal(visibleZoomHit(hits),undefined);
 near.geometry.dispose();for(const mesh of [near,middle,far])mesh.material.dispose();
});
test('zoom respects the material of the hit face rather than an unrelated visible material',()=>{
 const visible=new THREE.MeshBasicMaterial(),hidden=new THREE.MeshBasicMaterial({visible:false});
 const mesh=new THREE.Mesh(new THREE.BufferGeometry(),[hidden,visible]);
 const first={object:mesh,face:{materialIndex:0}},second={object:mesh,face:{materialIndex:1}};
 assert.equal(visibleZoomHit([first,second]),second);mesh.geometry.dispose();visible.dispose();hidden.dispose();
});
test('a hidden parent surface does not hide the selected child geometry from zoom',()=>{
 const parent=new THREE.Mesh(new THREE.BufferGeometry(),new THREE.MeshBasicMaterial({visible:false}));
 const child=new THREE.Mesh(parent.geometry,new THREE.MeshBasicMaterial());parent.add(child);
 const hit={object:child};assert.equal(visibleZoomHit([{object:parent},hit]),hit);
 parent.geometry.dispose();parent.material.dispose();child.material.dispose();
});
