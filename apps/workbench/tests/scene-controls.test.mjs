import assert from 'node:assert/strict';
import test from 'node:test';
import {PerspectiveCamera} from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {createSceneControls} from '../src/sceneControls.ts';

class ListenerTarget extends EventTarget {
  listeners=new Map();
  addEventListener(type,listener,options){
    super.addEventListener(type,listener,options);
    if(!listener)return;
    const capture=typeof options==='boolean'?options:!!options?.capture;
    const entries=this.listeners.get(type)??[];
    if(!entries.some(row=>row.listener===listener&&row.capture===capture))entries.push({listener,capture});
    this.listeners.set(type,entries);
  }
  removeEventListener(type,listener,options){
    super.removeEventListener(type,listener,options);
    const capture=typeof options==='boolean'?options:!!options?.capture;
    this.listeners.set(type,(this.listeners.get(type)??[]).filter(row=>row.listener!==listener||row.capture!==capture));
  }
  count(type){return (this.listeners.get(type)??[]).length;}
  key(type,key){const event=new Event(type);Object.defineProperty(event,'key',{value:key});this.dispatchEvent(event);}
}
class CanvasTarget extends ListenerTarget {
  style={};
  constructor(root){super();this.root=root;this.ownerDocument=root;}
  getRootNode(){return this.root;}
  detach(){this.root=this;}
}
const fixture=()=>{const root=new ListenerTarget();return {root,canvas:new CanvasTarget(root),camera:new PerspectiveCamera()};};
const keyboardCount=root=>root.count('keydown')+root.count('keyup');

test('the pinned OrbitControls really installs root keyboard listeners and leaves one after detached disposal',()=>{
  const f=fixture(),orbit=new OrbitControls(f.camera,f.canvas);
  assert.equal(typeof orbit._interceptControlDown,'function');assert.equal(typeof orbit._interceptControlUp,'function');
  assert.equal(f.root.count('keydown'),1);
  f.canvas.detach();orbit.dispose();
  assert.equal(f.root.count('keydown'),1,'The unpatched dependency must reproduce the detached-root cleanup gap');
  f.root.removeEventListener('keydown',orbit._interceptControlDown,{capture:true});
});
test('normal scene disposal removes keyboard and canvas input listeners and is repeatable',()=>{
  const f=fixture(),controls=createSceneControls(f.camera,f.canvas);
  assert.ok(controls.orbit instanceof OrbitControls);assert.equal(f.root.count('keydown'),1);
  assert.equal(f.canvas.count('pointerdown'),1);assert.equal(f.canvas.style.touchAction,'none');
  controls.dispose();controls.dispose();
  assert.equal(keyboardCount(f.root),0);assert.equal(f.canvas.style.touchAction,'');
  for(const type of ['pointerdown','pointercancel','wheel','contextmenu'])assert.equal(f.canvas.count(type),0);
});
test('passive cleanup still removes listeners from the original root after the host subtree is detached',()=>{
  const f=fixture(),controls=createSceneControls(f.camera,f.canvas);
  f.canvas.detach();controls.dispose();
  assert.equal(keyboardCount(f.root),0);assert.equal(keyboardCount(f.canvas),0);
  f.root.key('keydown','Control');assert.equal(f.root.count('keyup'),0,'A disposed orbit must not reinstall a keyup listener');
});
test('leaving a scene while Control is held removes the pending keyup listener even after detachment',()=>{
  const f=fixture(),controls=createSceneControls(f.camera,f.canvas);
  f.root.key('keydown','Control');assert.equal(f.root.count('keyup'),1);
  f.canvas.detach();controls.dispose();controls.dispose();
  assert.equal(keyboardCount(f.root),0);
  f.root.key('keyup','Control');f.root.key('keydown','Control');
  assert.equal(keyboardCount(f.root),0);assert.equal(keyboardCount(f.canvas),0);
});
test('disposing one viewport preserves another viewport on the same root',()=>{
  const f=fixture(),first=createSceneControls(f.camera,f.canvas),otherCanvas=new CanvasTarget(f.root);
  const second=createSceneControls(new PerspectiveCamera(),otherCanvas);
  assert.equal(f.root.count('keydown'),2);
  f.root.key('keydown','Control');assert.equal(f.root.count('keyup'),2);
  f.canvas.detach();first.dispose();
  assert.equal(f.root.count('keydown'),1);assert.equal(f.root.count('keyup'),1);
  f.root.key('keyup','Control');assert.equal(f.root.count('keyup'),0);
  f.root.key('keydown','Control');assert.equal(f.root.count('keyup'),1,'The other viewport remains connected');
  second.dispose();assert.equal(keyboardCount(f.root),0);
});
