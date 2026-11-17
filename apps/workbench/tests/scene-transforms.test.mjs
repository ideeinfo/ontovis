import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {fromDisplay,SceneTransformError,toDisplay,trueHeadingToThreeYaw} from '../src/sceneTransforms.ts';

const fixture=JSON.parse(readFileSync(new URL('./fixtures/scene-transforms-gdal.json',import.meta.url),'utf8'));
const local={mode:'local_plane',frameRevision:'local:1',origin:[0,0,0],unit:'m',axes:'X_EAST_Y_UP_Z_SOUTH'};
const clone=value=>structuredClone(value);
const within=(actual,expected,limit=.02)=>assert.ok(Math.hypot(...actual.map((value,index)=>value-expected[index]))<=limit,
  `Coordinate error exceeds ${limit} m: ${JSON.stringify({actual,expected})}`);
const reject=(code,callback)=>assert.throws(callback,error=>error instanceof SceneTransformError && error.code===code);
function geographicError(a,b) {
  const radians=Math.PI/180,dlat=(a.latitude-b.latitude)*radians,dlon=(a.longitude-b.longitude)*radians;
  const h=Math.sin(dlat/2)**2+Math.cos(a.latitude*radians)*Math.cos(b.latitude*radians)*Math.sin(dlon/2)**2;
  return 6_378_137*2*Math.asin(Math.min(1,Math.sqrt(h)));
}
const ground=(datum='EGM2008')=>({mode:'terrain_ground',terrainVersionId:'fixture-terrain',terrainSha256:'a'.repeat(64),
  sampleLongitude:111.02,sampleLatitude:33.01,sampledHeightM:100,offsetM:2,verticalDatum:datum,
  samplingRule:'mesh-triangle-tr-bl-cell-mask-v2'});

test('fixtures contain independent GDAL references including hemisphere/zone edges and 40 km',()=>{
  assert.match(fixture.source,/Independent rasterio\/GDAL/);
  assert.equal(fixture.convergenceRuleId,'projected-central-true-north-derivative-v1');
  assert.equal(fixture.cases.length,10);
  assert.ok(fixture.cases.some(value=>value.frame.horizontalCrs==='EPSG:32601'));
  assert.ok(fixture.cases.some(value=>value.frame.horizontalCrs==='EPSG:32760'));
  const far=fixture.cases.find(value=>value.name==='north-40km');
  assert.ok(Math.abs(Math.hypot(far.expectedDisplay[0],far.expectedDisplay[2])-40000)<1e-6);
});

for(const value of fixture.cases) {
  test(`GDAL display and inverse reference agree within 2 cm: ${value.name}`,()=>{
    const before=clone(value);
    within(toDisplay(value.frame,value.position,value.height),value.expectedDisplay);
    const inverse=fromDisplay(value.frame,value.expectedDisplay);
    assert.ok(geographicError(inverse.position,value.position)<=.02);
    assert.ok(Math.abs(inverse.heightM-value.height.valueM)<=.02);
    assert.equal(inverse.position.frameRevision,value.frame.frameRevision);
    assert.equal(inverse.position.transformId,value.frame.transformId);
    assert.equal(inverse.heightKind,'known_datum');assert.equal(inverse.verticalDatum,'EGM2008');
    within(toDisplay(value.frame,inverse.position,{...value.height,valueM:inverse.heightM}),value.expectedDisplay);
    assert.deepEqual(value,before);
  });
  test(`GDAL true-north derivative and calibrated Three yaw agree: ${value.name}`,()=>{
    for(const expected of value.headings) {
      const actual=trueHeadingToThreeYaw(value.frame,expected.trueHeadingDeg,value.position.longitude,value.position.latitude);
      const difference=Math.atan2(Math.sin(actual-expected.threeYawRad),Math.cos(actual-expected.threeYawRad));
      assert.ok(Math.abs(difference)<=1e-6,`Yaw differs from GDAL at heading ${expected.trueHeadingDeg}: ${difference}`);
    }
  });
}

test('local display preserves metre coordinates and relative height without fabricated geography',()=>{
  const position={mode:'local',xM:12,zM:-8},height={mode:'local_relative',relativeHeightM:3};
  assert.deepEqual(toDisplay(local,position,height),[12,3,-8]);
  assert.deepEqual(fromDisplay(local,[12,3,-8]),{position,heightM:3,verticalDatum:null,heightKind:'local_relative'});
  assert.equal(trueHeadingToThreeYaw(local,90),-Math.PI/2);
  assert.equal(trueHeadingToThreeYaw(local,-90),-3*Math.PI/2);
  assert.equal(trueHeadingToThreeYaw(local,450),-Math.PI/2);
});

test('Y uses the explicitly matching datum and ground offset instead of assuming zero altitude',()=>{
  const {frame,position}=fixture.cases[0];
  const display=toDisplay(frame,position,ground());
  assert.equal(display[1],102-frame.originHeight);
  reject('VERTICAL_DATUM_CONFLICT',()=>toDisplay(frame,position,ground('EGM96')));
  reject('VERTICAL_DATUM_CONFLICT',()=>toDisplay(frame,position,{mode:'absolute',valueM:102,verticalDatum:'WGS84_ELLIPSOIDAL',sourceNote:'mismatched'}));
});

test('unknown relative terrain returns its reference and never fabricates absolute elevation',()=>{
  const {frame,position}=clone(fixture.cases[0]);
  frame.verticalDatum='UNKNOWN_RELATIVE';frame.relativeReferenceId='relative:fixture';
  frame.anchor.anchorHeight={mode:'terrain_ground',terrainVersionId:'fixture-terrain',offsetM:0};
  const display=toDisplay(frame,position,ground('UNKNOWN_RELATIVE'));
  const inverse=fromDisplay(frame,display);
  assert.equal(inverse.heightKind,'relative_terrain');assert.equal(inverse.relativeReferenceId,'relative:fixture');
  assert.equal(inverse.verticalDatum,'UNKNOWN_RELATIVE');assert.equal(inverse.heightM,102);
  assert.equal('height' in inverse,false);
  reject('VERTICAL_DATUM_CONFLICT',()=>toDisplay(frame,position,{mode:'absolute',valueM:102,verticalDatum:'UNKNOWN_RELATIVE',sourceNote:'not absolute'}));
  delete frame.relativeReferenceId;
  reject('VERTICAL_DATUM_CONFLICT',()=>fromDisplay(frame,display));
});

test('non-whitelisted CRS, grids and fake ENU are rejected before projection',()=>{
  const {frame,position,height}=fixture.cases[0];
  for(const horizontalCrs of ['EPSG:32600','EPSG:32661','EPSG:32700','EPSG:32761','EPSG:3857','EPSG:4326',
    '+proj=utm +zone=49 +nadgrids=https://invalid.example/grid','https://invalid.example/crs'])
    reject('UNSUPPORTED_CRS',()=>toDisplay({...frame,horizontalCrs},position,height));
  reject('SCENE_SCOPE_UNSUPPORTED',()=>fromDisplay({...frame,mode:'enu'},[0,0,0]));
});

test('cross-zone/hemisphere, polar and over-50-km points never silently change projection',()=>{
  const {frame,position,height}=fixture.cases[0];
  reject('OUTSIDE_PROJECTION_AREA',()=>toDisplay(frame,{...position,longitude:114.001},height));
  reject('OUTSIDE_PROJECTION_AREA',()=>toDisplay(frame,{...position,latitude:-.001},height));
  reject('OUTSIDE_PROJECTION_AREA',()=>toDisplay(frame,{...position,latitude:85},height));
  reject('OUTSIDE_COVERAGE',()=>toDisplay(frame,{...position,longitude:111,latitude:33.6},height));
  reject('OUTSIDE_COVERAGE',()=>fromDisplay(frame,[0,0,-60000]));
  const edge=fixture.cases.find(value=>value.name==='north-zone1');
  reject('OUTSIDE_PROJECTION_AREA',()=>toDisplay(edge.frame,{...edge.position,longitude:179.99},edge.height));
});

test('frame/position identities and origin cannot silently diverge',()=>{
  const {frame,position,height}=fixture.cases[0];
  reject('FRAME_CHANGED',()=>toDisplay(frame,{...position,frameRevision:'other'},height));
  reject('FRAME_CHANGED',()=>toDisplay(frame,{...position,transformId:'other'},height));
  reject('FRAME_CHANGED',()=>toDisplay({...frame,originEasting:frame.originEasting+.1},position,height));
  reject('FRAME_CHANGED',()=>toDisplay({...frame,originHeight:frame.originHeight+1},position,height));
  reject('FRAME_CHANGED',()=>toDisplay({...frame,convergenceRuleId:'guessed-sign'},position,height));
  reject('VERTICAL_DATUM_CONFLICT',()=>toDisplay(local,position,height));
  reject('VERTICAL_DATUM_CONFLICT',()=>toDisplay(frame,position,{mode:'local_relative',relativeHeightM:0}));
});

test('non-finite, boolean, malformed vectors and missing projected heading coordinates are rejected',()=>{
  const {frame,position,height}=fixture.cases[0];
  for(const value of [NaN,Infinity,-Infinity,true,'12']) {
    reject('INVALID_COORDINATE',()=>toDisplay(frame,{...position,longitude:value},height));
    reject('INVALID_COORDINATE',()=>fromDisplay(frame,[value,0,0]));
    reject('INVALID_COORDINATE',()=>trueHeadingToThreeYaw(local,value));
  }
  reject('INVALID_COORDINATE',()=>fromDisplay(frame,[0,0]));
  reject('INVALID_COORDINATE',()=>trueHeadingToThreeYaw(frame,0));
  reject('INVALID_COORDINATE',()=>toDisplay(frame,position,{...height,valueM:NaN}));
});


test('server-derived relative-origin compensation survives display/inverse without allowing unbounded corrections',()=>{
  const {frame,position}=clone(fixture.cases[0]);
  frame.verticalDatum='UNKNOWN_RELATIVE';frame.relativeReferenceId='relative:compensated';frame.originHeight=.1;
  frame.anchor.anchorHeight={mode:'terrain_ground',terrainVersionId:'fixture-terrain',offsetM:-99.9,offsetCompensationM:5.689893001203927e-15};
  const display=toDisplay(frame,position,ground('UNKNOWN_RELATIVE'));
  assert.equal(display[1],102-.1);assert.equal(fromDisplay(frame,display).heightM,102);
  for(const correction of [Infinity,NaN,.001]){
    frame.anchor.anchorHeight.offsetCompensationM=correction;
    reject('INVALID_COORDINATE',()=>toDisplay(frame,position,ground('UNKNOWN_RELATIVE')));
  }
});
