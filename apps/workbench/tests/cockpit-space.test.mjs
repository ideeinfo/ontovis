import test from 'node:test';
import assert from 'node:assert/strict';
import {globeVector,globeDriftRadians,sceneGlobePoint,clusterGlobePoints,preparedNavigation,mayFinishNavigation} from '../src/cockpitSpace.ts';
const point=(id,longitude,latitude)=>({sceneId:id,revision:'rev:1',name:id,longitude,latitude});
const row=(longitude,latitude)=>({summary:{sceneId:'s',displayName:'Scene'},opened:{sceneRevision:'r1',snapshot:{coordinateFrame:{mode:'projected_site',anchor:{geographicAnchor:[longitude,latitude]}}}}});
test('globe drift is frame-rate independent, ramps in, stops when disabled and cannot leap after a stall',()=>{
 const at30=globeDriftRadians(1000/30,2000,true)*30,at60=globeDriftRadians(1000/60,2000,true)*60;
 assert.ok(Math.abs(at30-at60)<1e-12);assert.ok(Math.abs(at60*600-2*Math.PI)<1e-12);
 assert.equal(globeDriftRadians(16,2000,false),0);assert.equal(globeDriftRadians(16,-4500,true),0);assert.equal(globeDriftRadians(16,0,true),0);
 assert.ok(globeDriftRadians(16,700,true)<globeDriftRadians(16,1400,true));assert.equal(globeDriftRadians(60000,2000,true),globeDriftRadians(100,2000,true));
 assert.equal(globeDriftRadians(NaN,2000,true),0);assert.equal(globeDriftRadians(-16,2000,true),0);
});
test('Only valid authorized projected scene anchors become reference points; local and failed rows stay list-only',()=>{
 assert.deepEqual(sceneGlobePoint(row(113,34)),{...point('s',113,34),name:'Scene',revision:'r1'});
 for(const coords of [[NaN,34],[113,Infinity],[181,0],[0,91]])assert.equal(sceneGlobePoint(row(...coords)),null);
 assert.equal(sceneGlobePoint({summary:{},error:new Error(),opened:row(113,34).opened}),null);
 assert.equal(sceneGlobePoint({summary:{},opened:{snapshot:{coordinateFrame:{mode:'local_plane'}}}}),null);assert.equal(sceneGlobePoint({summary:{}}),null);
});
test('Equirectangular coordinates preserve latitude and handedness; date-line clusters never jump to Greenwich',()=>{
 assert.deepEqual(globeVector(0,0),[1,0,-0]);assert.ok(Math.abs(globeVector(90,0)[2]+1)<1e-12);assert.ok(Math.abs(globeVector(0,90)[1]-1)<1e-12);
 const result=clusterGlobePoints([point('a',179,10),point('b',-179,10),point('c',113,34)]);assert.equal(result.length,2);assert.equal(result[0].points.length,2);assert.ok(Math.abs(Math.abs(result[0].longitude)-180)<1e-9);assert.equal(result[1].points[0].sceneId,'c');assert.deepEqual(clusterGlobePoints([]),[]);
});
test('Only current prepared target enters arrival; late ready/error results cannot overwrite cancellation, newer target or arrival',()=>{
 const current={token:2,key:'fixed:2',sceneId:'s',revision:'r1',phase:'loading'};
 assert.equal(preparedNavigation(current,'fixed:1','ready'),current);assert.equal(preparedNavigation(current,current.key,'loading'),current);assert.equal(preparedNavigation(null,current.key,'ready'),null);
 const arrived=preparedNavigation(current,current.key,'ready');assert.equal(arrived.phase,'arriving');assert.equal(preparedNavigation(arrived,current.key,'error'),arrived);assert.equal(mayFinishNavigation(arrived,2),true);assert.equal(mayFinishNavigation(arrived,1),false);assert.equal(mayFinishNavigation(null,2),false);
 const failed=preparedNavigation(current,current.key,'error');assert.equal(failed.phase,'failed');assert.equal(mayFinishNavigation(failed,2),false);assert.equal(preparedNavigation(failed,current.key,'ready'),failed);
});
