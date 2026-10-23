import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {commitScene,sceneHistory,undoScene,placeModel} from '../src/sceneState.ts';
import {groupSceneInstances,moveSceneInstances,pruneSceneGroups,putSceneRoute,putSceneViewpoint,
  removeSceneViewpoint,sceneOrganization,selectSceneInstances,snapPoint,ungroupSceneInstances,viewpointIssue} from '../src/sceneOrganization.ts';
import {newRouteStep,SceneRoutePlayback} from '../src/sceneRoute.ts';
import {toDisplay} from '../src/sceneTransforms.ts';

const uid=()=>crypto.randomUUID();
const local=()=>({displayName:'合成场景',coordinateFrame:{mode:'local_plane',frameRevision:'local-r1',origin:[0,0,0],unit:'m',axes:'X_EAST_Y_UP_Z_SOUTH'},
  terrain:null,instances:[],initialView:{eye:[80,60,90],target:[0,15,0]},defaults:{background:'sky',lighting:'dusk',terrainMaterial:'solid'}});
const model={modelVersionId:uid(),displayName:'合成模型',canPlace:true,canPlaceGeographic:true,calibrationState:'verified',calibration:{state:'verified'}};
function pair(){let value=placeModel(local(),model,[2,0,3],null,'a',100);value=placeModel(value,model,[12,0,8],null,'b',100);return value;}
function camera(snapshot,kind='component'){return {viewpointId:uid(),displayName:'视点',kind,view:{eye:[20,30,40],target:[0,10,0]},frameRevision:snapshot.coordinateFrame.frameRevision,
  modelTarget:kind==='component'?{sceneModelInstanceId:snapshot.instances[0].sceneModelInstanceId,modelVersionId:model.modelVersionId}:null};}
function routeFixture(){let snapshot=pair();const component=camera(snapshot),overview={...camera(snapshot,'overview'),view:{eye:[100,100,100],target:[10,10,10]}};
  snapshot=putSceneViewpoint(putSceneViewpoint(snapshot,component),overview);
  const route={routeId:uid(),displayName:'路线',steps:[newRouteStep(component,uid()),newRouteStep(overview,uid())]};
  return {snapshot:putSceneRoute(snapshot,route),route,component,overview};}

test('groups are scene-local, disjoint and select/toggle whole membership without changing engineering links',()=>{
  const source=pair(),original=structuredClone(source);source.instances[0].rootBinding={synthetic:'unchanged'};
  const grouped=groupSceneInstances(source,['a','b'],'  设备组  ','group');
  assert.deepEqual(selectSceneInstances(grouped,[],'a'),['a','b']);
  assert.deepEqual(selectSceneInstances(grouped,['a','b'],'b',true),[]);
  assert.deepEqual(selectSceneInstances(grouped,[],'b',true),['a','b']);
  assert.deepEqual(grouped.instances,source.instances);assert.equal(original.organization,undefined);
  assert.throws(()=>groupSceneInstances(grouped,['a','b'],'另组','g2'),error=>error.code==='INSTANCE_ALREADY_GROUPED');
  assert.throws(()=>groupSceneInstances(source,['a','missing'],'坏组','g3'),error=>error.code==='INVALID_SCENE_ORGANIZATION');
  assert.deepEqual(sceneOrganization(ungroupSceneInstances(grouped,'group')).groups,[]);
  grouped.instances.pop();assert.deepEqual(pruneSceneGroups(grouped).organization.groups,[]);
});
test('batch delta snap preserves relative offsets and height, and one history step undoes both members',()=>{
  const source=pair(),before=structuredClone(source);source.instances[0].placement.height.relativeHeightM=5;
  const next=moveSceneInstances(source,['a','b'],[12,3],13,5,15);
  assert.deepEqual(next.instances.map(item=>item.placement.position),[{mode:'local',xM:12,zM:8},{mode:'local',xM:22,zM:13}]);
  assert.equal(next.instances[0].placement.height.relativeHeightM,5);assert.equal(next.instances[0].placement.headingDeg,15);
  assert.deepEqual(undoScene(commitScene(sceneHistory(source),next)).present,source);
  assert.equal(before.instances[1].placement.position.xM,12);
  assert.deepEqual(snapPoint([-2.6,99,13],5),[-5,99,15]);
});
test('locked, missing, duplicate or invalid members reject the whole batch without mutating source',()=>{
  const source=pair();source.instances[1].positionLocked=true;const before=structuredClone(source);
  assert.throws(()=>moveSceneInstances(source,['a','b'],[10,0],0),error=>error.code==='INSTANCE_POSITION_LOCKED'&&error.instanceIds[0]==='b');
  assert.deepEqual(source,before);source.instances[1].positionLocked=false;
  for(const ids of [['a','missing'],['a','a'],[]])assert.throws(()=>moveSceneInstances(source,ids,[0,0],0));
  assert.throws(()=>moveSceneInstances(source,['a','b'],[1_000_000,0],0));
  assert.throws(()=>moveSceneInstances(source,['a','b'],[NaN,0],0));
  assert.equal(source.instances[0].placement.position.xM,2);
});
test('regional batch uses projected X/Z metres while retaining independent ground/absolute strategies for server resampling',()=>{
  const frame=JSON.parse(readFileSync(new URL('./fixtures/scene-transforms-gdal.json',import.meta.url))).cases[0].frame;
  const terrain={terrainVersionId:'terrain',contentRevision:'r1',sha256:'a'.repeat(64),report:{mesh:{placementSamplingRule:'fixed'}}};
  let snapshot={...local(),coordinateFrame:frame,terrain:{terrainVersionId:'terrain',expectedContentRevision:'r1'}};
  snapshot=placeModel(snapshot,model,[0,5,0],terrain,'a',100);snapshot=placeModel(snapshot,model,[20,8,-15],terrain,'b',100);
  snapshot.instances[1].placement.height={mode:'absolute',valueM:frame.originHeight+8,verticalDatum:frame.verticalDatum,sourceNote:'synthetic'};
  const before=snapshot.instances.map(item=>toDisplay(frame,item.placement.position,item.placement.height)),next=moveSceneInstances(snapshot,['a','b'],[10,-5],-20);
  next.instances.forEach((item,index)=>{const point=toDisplay(frame,item.placement.position,item.placement.height);assert.ok(Math.abs(point[0]-before[index][0]-10)<1e-7);assert.ok(Math.abs(point[2]-before[index][2]+5)<1e-7);});
  assert.deepEqual(next.instances[0].placement.height,snapshot.instances[0].placement.height);assert.deepEqual(next.instances[1].placement.height,snapshot.instances[1].placement.height);
  const headingOnly=moveSceneInstances(snapshot,['a','b'],[0,0],15);
  assert.deepEqual(headingOnly.instances.map(item=>item.placement.position),snapshot.instances.map(item=>item.placement.position));
});
test('named views detect frame/model/removed target changes and resaving preserves route references',()=>{
  const {snapshot,component,route}=routeFixture();assert.equal(viewpointIssue(snapshot,component),null);
  const changed=structuredClone(snapshot);changed.coordinateFrame.frameRevision='new-frame';assert.equal(viewpointIssue(changed,component),'VIEW_FRAME_CHANGED');
  changed.coordinateFrame.frameRevision=component.frameRevision;changed.instances[0].modelVersionId='new-model';assert.equal(viewpointIssue(changed,component),'VIEW_MODEL_CHANGED');
  changed.instances.shift();assert.equal(viewpointIssue(changed,component),'VIEW_TARGET_MISSING');
  assert.throws(()=>removeSceneViewpoint(snapshot,component.viewpointId),error=>error.code==='VIEWPOINT_IN_USE');
  const resaved=putSceneViewpoint(snapshot,{...component,displayName:'更新',view:{eye:[40,40,40],target:[0,10,0]}});
  assert.equal(resaved.organization.viewpoints.length,2);assert.deepEqual(resaved.organization.routes[0],route);
});
test('route durations default to component 2/overview 3 and flight is distinct from dwell',()=>{
  const {snapshot,route,component,overview}=routeFixture();assert.equal(newRouteStep(component,uid()).dwellSeconds,2);assert.equal(newRouteStep(overview,uid()).dwellSeconds,3);
  const player=new SceneRoutePlayback(snapshot,route,snapshot.initialView);
  player.advance(.6);assert.equal(player.progress.phase,'flight');assert.equal(player.progress.elapsedSeconds,.6);
  assert.notDeepEqual(player.view,component.view);assert.notDeepEqual(player.view,snapshot.initialView);
  player.advance(.6);assert.equal(player.progress.phase,'dwell');assert.deepEqual(player.view,component.view);
  player.advance(2);assert.equal(player.progress.index,1);assert.equal(player.progress.phase,'flight');
  player.advance(4.2);assert.equal(player.progress.status,'complete');assert.deepEqual(player.view,overview.view);
});
test('pause excludes all elapsed time, cancellation restores origin, and route inputs cannot mutate a running preview',()=>{
  const {snapshot,route}=routeFixture(),origin=structuredClone(snapshot.initialView),player=new SceneRoutePlayback(snapshot,route,origin);
  player.advance(.4);player.pause();const paused=player.view;player.advance(3600);assert.deepEqual(player.view,paused);
  player.resume();player.advance(.2);assert.ok(Math.abs(player.progress.elapsedSeconds-.6)<1e-12);
  route.steps[0].flightSeconds=30;snapshot.organization.viewpoints[0].view.eye[0]=999;origin.eye[0]=999;
  assert.deepEqual(player.cancel(),snapshot.initialView);assert.equal(player.progress.status,'cancelled');assert.deepEqual(player.advance(99),snapshot.initialView);
});
test('zero dwell, reduced motion, large time step, invalid route and manual takeover remain bounded',()=>{
  const {snapshot,route,component}=routeFixture();route.steps=route.steps.slice(0,1);route.steps[0].dwellSeconds=0;
  const player=new SceneRoutePlayback(snapshot,route,snapshot.initialView,true);player.advance(0);assert.equal(player.progress.status,'complete');assert.deepEqual(player.view,component.view);
  const manual=new SceneRoutePlayback(snapshot,route,snapshot.initialView);manual.advance(.4);const position=manual.view;assert.deepEqual(manual.cancel(false),position);
  const finished=new SceneRoutePlayback(snapshot,route,snapshot.initialView);finished.advance(36000);assert.equal(finished.progress.status,'complete');
  assert.throws(()=>finished.advance(-1));assert.throws(()=>finished.advance(Infinity));
  assert.throws(()=>new SceneRoutePlayback(snapshot,{...route,steps:[]},snapshot.initialView));
  snapshot.instances=[];assert.throws(()=>new SceneRoutePlayback(snapshot,route,snapshot.initialView),error=>error.code==='VIEWPOINT_STALE');
});

test('opposite camera directions follow an arc and never collapse the camera onto its target',()=>{
  const {snapshot,route,component}=routeFixture();
  component.view={eye:[-10,0,0],target:[0,0,0]};snapshot.organization.viewpoints[0]=component;
  const player=new SceneRoutePlayback(snapshot,route,{eye:[10,0,0],target:[0,0,0]});
  player.advance(.6);const view=player.view;
  assert.ok(Math.abs(Math.hypot(...view.eye.map((value,i)=>value-view.target[i]))-10)<1e-9);
  player.advance(.6);assert.deepEqual(player.view,component.view);
});
