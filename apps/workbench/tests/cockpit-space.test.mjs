import test from 'node:test';
import assert from 'node:assert/strict';
import {globeVector,globeAngleDegrees,globeClusterDegrees,globeClusterFocusDistance,globeDriftRadians,sceneGlobePoint,clusterGlobePoints,preparedNavigation,mayFinishNavigation,globeFlightProgress,resumedGlobeFlightStart,globeFramePlan} from '../src/cockpitSpace.ts';
const point=(id,longitude,latitude)=>({sceneId:id,revision:'rev:1',name:id,longitude,latitude});
const row=(longitude,latitude)=>({summary:{sceneId:'s',displayName:'Scene'},opened:{sceneRevision:'r1',snapshot:{coordinateFrame:{mode:'projected_site',anchor:{geographicAnchor:[longitude,latitude]}}}}});
const liveScenePoints=[
 point('Beck Burn',-3.0239366666666667,55.011359666666664),
 point('Corriemoillie',-4.779967588235294,57.66545270588235),
 point('Crystal Rig',-2.5433396153846153,55.90670112087911),
 point('Dogger Bank',2.722959264367816,55.02065526436782),
 point('Hornsea 2',1.715484207317073,53.98044437804878),
 point('Teesside Offshore',-1.0941992222222223,54.64518066666666),
 point('海上风电· MySE',1.715484207317073,53.98044437804878),
 point('平顶山夏李风电场',113.20083333333336,33.453333333333326),
 point('鸣沙山',94.62879502700449,39.97207867557596)
];
test('globe drift runs at 1.8 degrees per second across frame rates, ramps in, stops when disabled and cannot leap after a stall',()=>{
 const at30=globeDriftRadians(1000/30,2000,true)*30,at60=globeDriftRadians(1000/60,2000,true)*60;
 assert.ok(Math.abs(at30-at60)<1e-12);assert.ok(Math.abs(at60*200-2*Math.PI)<1e-12);assert.ok(Math.abs(at60/(.6*Math.PI/180)-3)<1e-12);
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

test('returning after a long scene or analysis visit starts a new flight now, without the hidden time',()=>{
 for(const duration of [1000,60000,3600000]){
  const now=1000+duration,start=resumedGlobeFlightStart(now,1000,now,true);
  assert.equal(start,now);assert.equal(globeFlightProgress(start,now),0);
  assert.equal(globeFlightProgress(start,now+450),.5);assert.equal(globeFlightProgress(start,now+900),1);
 }
});
test('hiding an existing flight preserves its progress, and future clocks cannot extrapolate the camera',()=>{
 const start=resumedGlobeFlightStart(100,400,10000,false);
 assert.equal(globeFlightProgress(start,10000),1/3);
 assert.equal(globeFlightProgress(10000,500),0);assert.equal(globeFlightProgress(100,20000),1);
 assert.equal(resumedGlobeFlightStart(100,null,500,false),100);
});

test('the last flight frame schedules idle drift without an OrbitControls change; pause still settles',()=>{
 for(const driftAllowed of [true,false]){
  let flight=true,pending=true;const frames=[];
  for(let n=0;pending&&n<4;n++){
   const plan=globeFramePlan(flight,driftAllowed);frames.push(plan.drift);
   if(globeFlightProgress(0,900+n*16)===1)flight=false;
   pending=plan.continue;
  }
  assert.deepEqual(frames,driftAllowed?[false,true,true,true]:[false,false]);
  assert.equal(pending,driftAllowed);
 }
});

test('pairwise linkage bounds cluster span, zoom expands UK/North Sea scenes, and co-located anchors stay grouped',()=>{
 assert.ok(globeAngleDegrees(globeVector(-4.779967588235294,57.66545270588235),globeVector(1.715484207317073,53.98044437804878))>5.1);
 const overviewDeg=globeClusterDegrees(3.65,900);
 const overview=clusterGlobePoints(liveScenePoints,overviewDeg);
 for(const group of overview)assert.ok(group.spanDegrees<=overviewDeg+1e-6);
 assert.equal(overview.length,4);
 assert.deepEqual(overview.map(g=>g.points.length),[3,4,1,1]);
 const ukGroup=overview[0],northSeaGroup=overview[1];
 assert.equal(ukGroup.coincident,false);assert.equal(northSeaGroup.coincident,false);
 for(const regional of [ukGroup,northSeaGroup]){
  const focusDist=globeClusterFocusDistance(regional,900);
  assert.ok(focusDist>=1.22&&focusDist<1.6);
  const zoomedDeg=globeClusterDegrees(focusDist,900);
  assert.ok(zoomedDeg<overviewDeg);
  const zoomed=clusterGlobePoints(liveScenePoints,zoomedDeg);
  assert.equal(zoomed.length,8);
  const singleNames=zoomed.filter(g=>g.points.length===1).map(g=>g.points[0].name);
  assert.deepEqual(singleNames,['Beck Burn','Corriemoillie','Crystal Rig','Dogger Bank','Teesside Offshore','平顶山夏李风电场','鸣沙山']);
  const coincident=zoomed.find(g=>g.points.length>1);
  assert.ok(coincident);assert.equal(coincident.coincident,true);assert.equal(coincident.spanDegrees,0);
  assert.deepEqual(coincident.points.map(p=>p.name),['Hornsea 2','海上风电· MySE']);
  assert.equal(globeClusterFocusDistance(coincident,900),1.32);
  assert.equal(globeClusterFocusDistance(zoomed[0],900),2.1);
 }
});

test('portfolio scene focus target resolves its cluster group and focus parameters accurately',()=>{
 const overview=clusterGlobePoints(liveScenePoints,globeClusterDegrees(3.65,900));
 const findGroup=sceneId=>overview.find(g=>g.points.some(p=>p.sceneId===sceneId));
 const xiali=findGroup('平顶山夏李风电场');
 assert.ok(xiali);
 assert.equal(xiali.points.length,1);
 assert.equal(xiali.points[0].sceneId,'平顶山夏李风电场');
 assert.ok(Math.abs(xiali.longitude-113.20083333333336)<1e-9);
 assert.ok(Math.abs(xiali.latitude-33.453333333333326)<1e-9);
 const myse=findGroup('海上风电· MySE');
 assert.ok(myse);
 assert.ok(myse.points.some(p=>p.sceneId==='Hornsea 2'));
 const mingshashan=findGroup('鸣沙山');
 assert.ok(mingshashan);
 assert.equal(mingshashan.points[0].sceneId,'鸣沙山');
 const missing=findGroup('不存在的场景');
 assert.equal(missing,undefined);
});

test('cockpit scene preparation and viewport prompt overlays adhere to frosted glass and panel opacity rules',async()=>{
 const fs=await import('node:fs/promises');
 const spaceCss=await fs.readFile(new URL('../src/cockpitSpace.css',import.meta.url),'utf8');
 const cockpitCss=await fs.readFile(new URL('../src/projectCockpit.css',import.meta.url),'utf8');
 assert.ok(spaceCss.includes('.pc-app .sw-loading'));
 assert.ok(spaceCss.includes('.pc-viewport .sw-loading'));
 assert.ok(spaceCss.includes('.pc-viewport .ov-scene-viewport-state'));
 assert.ok(spaceCss.includes('.pc-viewport .ov-scene-viewport-state:has(.sw-loading)'));
 assert.ok(cockpitCss.includes('.pc-app .sw-ground-cursor-badge'));
 assert.ok(cockpitCss.includes('.pc-viewport .ov-scene-viewport-tools'));
 assert.ok(cockpitCss.includes('.pc-viewport .ov-scene-imagery-attribution'));
 assert.ok(cockpitCss.includes('.pc-viewport .ev-status'));
});
