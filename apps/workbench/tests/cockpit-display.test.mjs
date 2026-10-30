import test from 'node:test';
import assert from 'node:assert/strict';
import {pageWindow,presentationEnvironment} from '../src/cockpitDisplayState.ts';
import {environmentPreset} from '../src/sceneEnvironment.ts';
test('Paging adapts to short panels, reaches every item and clamps after filtering',()=>{
 const visited=[];for(let i=0;i<5;i++){const page=pageWindow(13,i,3);visited.push(...Array.from({length:page.end-page.start},(_,n)=>page.start+n));}
 assert.deepEqual(visited,Array.from({length:13},(_,n)=>n));
 assert.deepEqual(pageWindow(2,4,3),{page:0,pages:1,start:0,end:2});
 assert.deepEqual(pageWindow(0,4,0),{page:0,pages:1,start:0,end:0});
 assert.equal(pageWindow(20,15,1).start,15);
});
test('Display overrides preserve saved terrain, water and model environment',()=>{
 const original=environmentPreset('offshore-overview-v1'),copy=structuredClone(original);
 const rain=presentationEnvironment(original,null,'scene','rain').value;
 assert.notEqual(rain,original);assert.equal(rain.atmosphere.clouds.coverage,.88);assert.deepEqual(rain.water,original.water);
 const dusk=presentationEnvironment(original,null,'dusk','off').value;
 assert.equal(dusk.lighting.sun.elevationDeg,12);assert.deepEqual(dusk.water,original.water);assert.deepEqual(original,copy);
 assert.equal(presentationEnvironment(original,null,'scene','off'),null);
 assert.equal(presentationEnvironment(original,null,'scene','forecast'),null);
});
test('Valid forecast drives conditions; manual lighting overrides only presentation',()=>{
 const forecast={forecast:{condition:'rain',cloudPercent:88,symbol:'rain_night'}},before=structuredClone(forecast);
 const auto=presentationEnvironment(null,forecast,'scene','forecast').value;
 const day=presentationEnvironment(null,forecast,'day','forecast').value;
 assert.equal(auto.lighting.sun.enabled,false);assert.equal(day.lighting.sun.enabled,true);assert.equal(day.atmosphere.clouds.coverage,.88);assert.deepEqual(forecast,before);
 const fog=presentationEnvironment(null,null,'scene','fog').value;assert.equal(fog.atmosphere.fog.mode,'linear');
 const clear=presentationEnvironment(fog,null,'scene','clear').value;assert.equal(clear.atmosphere.fog.mode,'off');assert.equal(clear.atmosphere.clouds.enabled,false);
});
