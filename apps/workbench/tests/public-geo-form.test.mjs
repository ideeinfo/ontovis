import assert from 'node:assert/strict';
import test from 'node:test';
import {publicGeoInitialForm,scenePublicGeoCenter} from '../src/publicGeoForm.ts';
import {validPublicGeo} from '../src/publicGeoApi.ts';

const frame=(longitude,latitude)=>({mode:'projected_site',anchor:{geographicAnchor:[longitude,latitude]}});
const oldJob=state=>({state,request:{name:'Previous region',longitude:94.6284448,latitude:39.9723005,radiusKm:5,terrain:false,imagery:true}});

test('scene anchor initializes acquisition longitude and latitude without changing the frame',()=>{
 const value=frame(-2.507093,55.897659),before=structuredClone(value);
 assert.deepEqual(publicGeoInitialForm(scenePublicGeoCenter(value)),{name:'',longitude:'-2.5070930',latitude:'55.8976590',radius:'3',terrain:true,imagery:true});
 assert.deepEqual(value,before);
});
test('reopening in another scene starts from that scene rather than a completed acquisition',()=>{
 const first=publicGeoInitialForm(scenePublicGeoCenter(frame(113.183,33.455)),oldJob('ready'));
 const second=publicGeoInitialForm(scenePublicGeoCenter(frame(-2.507093,55.897659)),oldJob('ready'));
 first.longitude='1';assert.equal(second.longitude,'-2.5070930');assert.equal(second.latitude,'55.8976590');
});
test('ready, failed and cancelled jobs do not replace a fresh form or its scene location',()=>{
 const center={longitude:-2.5,latitude:55.9},expected=publicGeoInitialForm(center);
 for(const state of ['ready','failed','cancelled'])assert.deepEqual(publicGeoInitialForm(center,oldJob(state)),expected);
 assert.equal(publicGeoInitialForm(undefined,oldJob('ready')).longitude,'');
});
test('an in-flight acquisition resumes its actual locked request instead of retargeting it',()=>{
 const job=oldJob('processing'),before=structuredClone(job);
 assert.deepEqual(publicGeoInitialForm({longitude:-2.5,latitude:55.9},job),{name:'Previous region',longitude:'94.6284448',latitude:'39.9723005',radius:'5',terrain:false,imagery:true});
 assert.deepEqual(job,before);
});
test('unanchored or invalid scenes leave both coordinates blank instead of inventing a location',()=>{
 assert.equal(scenePublicGeoCenter({mode:'local_plane'}),undefined);
 for(const values of [[NaN,33],[1,Infinity],[181,40],[1,-91]])assert.equal(scenePublicGeoCenter(frame(...values)),undefined);
 assert.equal(publicGeoInitialForm({longitude:NaN,latitude:33}).latitude,'');
});
test('zero coordinates remain valid and source coverage limits never silently change a scene center',()=>{
 assert.deepEqual(scenePublicGeoCenter(frame(0,0)),{longitude:0,latitude:0});
 const center=scenePublicGeoCenter(frame(179.999,84));assert.ok(center);
 assert.equal(publicGeoInitialForm(center).latitude,'84.0000000');
 assert.equal(validPublicGeo(center.longitude,center.latitude,3),false);
});
