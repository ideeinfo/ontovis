import test from 'node:test';
import assert from 'node:assert/strict';
import {cockpitInstanceVisibility,deckCapacity,pageWindow,presentationEnvironment} from '../src/cockpitDisplayState.ts';
import {environmentPreset} from '../src/sceneEnvironment.ts';
import {prepareComponentFocus} from '../src/sceneComponentFocus.ts';

test('alarm component isolation preserves every other visible scene instance and explicit visibility choices',()=>{
 const instances=Array.from({length:15},(_,index)=>({sceneModelInstanceId:`instance-${index}`,modelVersionId:index===0?'detail':'appearance',visible:index!==13,
  placement:{position:{mode:'local',xM:index*100,zM:0},height:{mode:'local_relative',relativeHeightM:0},headingDeg:0},rootBinding:null,componentBindings:[]}));
 const personal={'instance-12':false,'instance-14':false},before=structuredClone({instances,personal});
 const visibility=cockpitInstanceVisibility(instances,true,personal),state={snapshot:{instances,coordinateFrame:{mode:'local_plane',frameRevision:'frame',origin:[0,0,0],unit:'m',axes:'X_EAST_Y_UP_Z_SOUTH'},terrain:null},
  selectedId:'instance-0',personalVisibility:visibility,previewActive:false,modelRefs:[{modelVersionId:'detail',modelAssetId:'asset',contentRevision:'content',sha256:'a'.repeat(64)}]};
 const request={token:1,instanceId:'instance-0',bounds:[[0,0,0],[2,3,4]],componentKeys:['cabinet'],isolate:true};
 assert.equal(prepareComponentFocus(request,state)?.isolate,true);
 assert.deepEqual(instances.filter(item=>visibility[item.sceneModelInstanceId]??item.visible).map(item=>item.sceneModelInstanceId),Array.from({length:12},(_,index)=>`instance-${index}`));
 assert.equal(prepareComponentFocus({...request,isolate:false},state)?.isolate,false);
 assert.deepEqual({instances,personal},before);
});

test('device layer can hide the whole scene and restore saved and personal visibility without changing either',()=>{
 const instances=[{sceneModelInstanceId:'visible',visible:true},{sceneModelInstanceId:'hidden',visible:false},{sceneModelInstanceId:'personal',visible:true}];
 const personal={personal:false},before=structuredClone({instances,personal});
 assert.deepEqual(cockpitInstanceVisibility(instances,false,personal),{visible:false,hidden:false,personal:false});
 const restored=cockpitInstanceVisibility(instances,true,personal);
 assert.deepEqual(instances.map(item=>restored[item.sceneModelInstanceId]??item.visible),[true,false,false]);
 assert.deepEqual(cockpitInstanceVisibility([],false,personal),{});
 assert.deepEqual({instances,personal},before);
});

test('Presentation minimum rows fit within the measured deck and retain every page item',()=>{
 for(const minimum of [3,5])for(const height of [210,300,480]){
  const value=deckCapacity(height,124,minimum);assert.ok(value.count>=minimum);assert.ok(value.rowHeight*value.count<=height-42+.00001);
  const seen=[];for(let i=0;i<Math.ceil(13/value.count);i++){const p=pageWindow(13,i,value.count);seen.push(...Array.from({length:p.end-p.start},(_,n)=>p.start+n));}assert.deepEqual(seen,Array.from({length:13},(_,n)=>n));
 }
});
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

test('night uses blue sky, brighter fill and lit imagery without changing the saved configuration',()=>{
 const base=environmentPreset('land-day-v1'),before=structuredClone(base),forecast={forecast:{condition:'clear',cloudPercent:0,symbol:'clearsky_night'}};
 const night=presentationEnvironment(base,forecast,'scene','forecast');
 assert.equal(night.night,true);assert.equal(night.value.atmosphere.topColor,'#070e23');assert.equal(night.value.atmosphere.horizonColor,'#25344f');
 assert.ok(night.value.lighting.hemisphereIntensity>=1);assert.equal(night.value.lighting.sun.enabled,false);assert.equal(night.value.surface.imageryShading,'lit');
 assert.equal(presentationEnvironment(base,null,'night','off').night,true);
 assert.equal(presentationEnvironment(base,forecast,'day','forecast').night,false);assert.deepEqual(base,before);
});
