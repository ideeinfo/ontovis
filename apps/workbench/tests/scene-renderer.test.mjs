import assert from 'node:assert/strict';
import test from 'node:test';
import * as THREE from 'three';
import {prepareSceneRenderer,resizeSceneRenderer} from '../src/sceneRenderer.ts';

test('cockpit renders the visible area at display density through interface zoom and fullscreen changes',()=>{
  const buffers=[],renderer={setDrawingBufferSize:(width,height,ratio)=>buffers.push([width*ratio,height*ratio])};
  const element={clientWidth:960,clientHeight:540,getBoundingClientRect:()=>({width:1920,height:1080})};
  assert.deepEqual(resizeSceneRenderer(renderer,element,2,true),{width:1920,height:1080});
  resizeSceneRenderer(renderer,element,1,true);
  element.getBoundingClientRect=()=>({width:1600,height:900});
  resizeSceneRenderer(renderer,element,2,true);
  assert.deepEqual(buffers,[[3840,2160],[1920,1080],[3200,1800]]);
});

test('workbench viewport sizing uses layout pixels and retains its device-pixel cap',()=>{
  const calls=[],renderer={setDrawingBufferSize:(...args)=>calls.push(args)};
  const element={clientWidth:960,clientHeight:540,getBoundingClientRect:()=>({width:1920,height:1080})};
  assert.deepEqual(resizeSceneRenderer(renderer,element,2,false),{width:960,height:540});
  resizeSceneRenderer(renderer,element,1,false);
  assert.deepEqual(calls,[[960,540,1.5],[960,540,1]]);
});

const lut=()=>{const value=new THREE.DataTexture(new Uint16Array(512),16,16,THREE.RGFormat,THREE.HalfFloatType);value.name='DFG_LUT';return value;};
function fixture(texture,onRender=()=>{}){
  let allocated=false,disposed=0,released=0;
  const callback=event=>{assert.equal(event.target,texture);texture.removeEventListener('dispose',callback);allocated=false;released++;};
  const renderer={render(){if(!allocated){texture.addEventListener('dispose',callback);allocated=true;}onRender();},dispose(){disposed++;}};
  return {renderer,callback,get allocated(){return allocated;},get disposed(){return disposed;},get released(){return released;}};
}

test('a long-lived LUT retains registrations when renderer disposal alone does not remove them',()=>{
  assert.equal(THREE.REVISION,'184');
  const texture=lut(),f=fixture(texture);f.renderer.render();f.renderer.dispose();
  assert.equal(texture.hasEventListener('dispose',f.callback),true);
  texture.dispose();assert.equal(f.released,1);
});
test('scene disposal deallocates only its own shared LUT, once, and restores registration',()=>{
  const texture=lut(),f=fixture(texture),add=THREE.Texture.prototype.addEventListener;
  const renderer=prepareSceneRenderer(f.renderer);renderer.render();renderer.render();
  assert.equal(THREE.Texture.prototype.addEventListener,add);
  renderer.dispose();renderer.dispose();
  assert.equal(f.disposed,1);assert.equal(f.released,1);assert.equal(f.allocated,false);
  assert.equal(texture.hasEventListener('dispose',f.callback),false);
});
test('another live viewport and external texture observers keep their registrations and allocations',()=>{
  const texture=lut(),first=fixture(texture),second=fixture(texture);let external=0;
  texture.addEventListener('dispose',()=>external++);
  const a=prepareSceneRenderer(first.renderer),b=prepareSceneRenderer(second.renderer);
  a.render();b.render();a.dispose();
  assert.equal(first.released,1);assert.equal(second.released,0);assert.equal(second.allocated,true);
  assert.equal(texture.hasEventListener('dispose',second.callback),true);assert.equal(external,0);
  b.render();assert.equal(second.released,0);b.dispose();assert.equal(second.released,1);assert.equal(external,0);
});
test('nested viewport rendering attributes each shared texture callback to its own owner',()=>{
  const texture=lut(),inner=fixture(texture),b=prepareSceneRenderer(inner.renderer);
  const outer=fixture(texture,()=>b.render()),a=prepareSceneRenderer(outer.renderer);
  a.render();a.dispose();assert.equal(outer.released,1);assert.equal(inner.released,0);
  b.dispose();assert.equal(inner.released,1);
});
test('failed rendering restores the prototype and still releases registrations installed before failure',()=>{
  const texture=lut(),f=fixture(texture,()=>{throw Error('render failed');}),add=THREE.Texture.prototype.addEventListener;
  const renderer=prepareSceneRenderer(f.renderer);
  assert.throws(()=>renderer.render(),/render failed/);assert.equal(THREE.Texture.prototype.addEventListener,add);
  renderer.dispose();assert.equal(f.released,1);assert.equal(f.disposed,1);
});
test('ordinary material textures remain owned by their existing cache cleanup',()=>{
  const texture=new THREE.DataTexture(),f=fixture(texture),renderer=prepareSceneRenderer(f.renderer);
  renderer.render();renderer.dispose();assert.equal(f.released,0);
  texture.dispose();assert.equal(f.released,1);
  const unused=fixture(lut());prepareSceneRenderer(unused.renderer).dispose();assert.equal(unused.disposed,1);assert.equal(unused.released,0);
});
