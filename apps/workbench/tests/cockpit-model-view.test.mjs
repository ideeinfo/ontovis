import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {SceneModelView} from '../src/sceneModelView.ts';
import {fixture,node,snapshot} from './helpers/fixed-model.mjs';
const request=(f,mode)=>({instanceId:'a',modelVersionId:'v1',contentRevision:'content:1',sha256:f.adapted.sha256,mode});
test('X-ray clones only shell materials, preserving shared source, another instance and internals; reset disposes owned materials only',async()=>{
 const f=await fixture(true),before=snapshot(f.a),other=snapshot(f.b),source=snapshot(f.resource.scene);
 const shell=node(f.a,12),internal=node(f.a,50),original=shell.material;let originalDisposed=0;original.addEventListener('dispose',()=>originalDisposed++);
 const rig=SceneModelView.create(f.a,f.adapted,request(f,'xray'));assert.ok(rig);
 assert.notEqual(shell.material,original);assert.equal(shell.material.opacity,.14);assert.equal(shell.material.depthWrite,false);assert.equal(internal.material,original);
 assert.equal(node(f.b,12).material,original);assert.equal(node(f.resource.scene,12).material,original);
 assert.equal(rig.focusBounds().isEmpty(),false);let ownedDisposed=0;shell.material.addEventListener('dispose',()=>ownedDisposed++);
 assert.deepEqual(snapshot(f.b),other);assert.deepEqual(snapshot(f.resource.scene),source);rig.dispose();rig.dispose();assert.equal(ownedDisposed,1);assert.equal(originalDisposed,0);assert.equal(shell.material,original);assert.deepEqual(snapshot(f.a),before);f.cache.dispose();
});
test('Exploded groups remain below calibrated installation transforms; tower stays fixed; every transform and parent restores exactly',async()=>{
 const f=await fixture(true);f.a.position.set(100,5,200);f.a.rotation.y=.8;const before=snapshot(f.a),other=snapshot(f.b),source=snapshot(f.resource.scene),tower=node(f.a,180).getWorldPosition(new THREE.Vector3()),rotor=node(f.a,2).position.clone();
 const rig=SceneModelView.create(f.a,f.adapted,request(f,'exploded'));assert.ok(rig);
 assert.deepEqual(node(f.a,2).position.toArray(),rotor.add(new THREE.Vector3(0,2,12)).toArray());assert.deepEqual(node(f.a,50).position.toArray(),[0,5,-5]);
 assert.ok(node(f.a,180).getWorldPosition(new THREE.Vector3()).distanceTo(tower)<1e-8);assert.deepEqual(snapshot(f.b),other);assert.deepEqual(snapshot(f.resource.scene),source);
 rig.dispose();rig.dispose();assert.deepEqual(snapshot(f.a),before);f.cache.dispose();
});
test('Unknown content, revision, instance, mode, calibration and hierarchy are rejected before mutation',async()=>{
 const f=await fixture(true),before=snapshot(f.a),req=request(f,'exploded');
 for(const change of [{sha256:'other'},{modelVersionId:'other'},{contentRevision:'other'},{calibration:{state:'unverified'}}])assert.equal(SceneModelView.create(f.a,{...f.adapted,...change},req),null);
 assert.equal(SceneModelView.create(f.b,f.adapted,req),null);assert.equal(SceneModelView.create(f.a,f.adapted,{...req,mode:'unknown'}),null);assert.deepEqual(snapshot(f.a),before);
 node(f.a,1).add(node(f.a,2));const changed=snapshot(f.a);assert.equal(SceneModelView.create(f.a,f.adapted,req),null);assert.deepEqual(snapshot(f.a),changed);f.cache.dispose();
 const exterior=await fixture();assert.equal(SceneModelView.create(exterior.a,exterior.adapted,request(exterior,'xray')),null);exterior.cache.dispose();
});
