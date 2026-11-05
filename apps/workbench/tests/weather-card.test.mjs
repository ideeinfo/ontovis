import test from 'node:test';
import assert from 'node:assert/strict';
import {getBeaufortInfo,getWindDirectionInfo,getPrecipitationInfo,getCloudCoverageInfo,getOperationAdvice,formatWeatherCoordinates} from '../src/weatherCardLogic.ts';

test('wind scale uses forecast wind without asserting an equipment operating state',()=>{
  for(const value of [null,undefined,NaN,Infinity,-1])assert.equal(getBeaufortInfo(value).stage,'unknown');
  for(const [speed,scale] of [[.1,0],[2,2],[6.5,4],[12,6],[26,10]]){
    const result=getBeaufortInfo(speed);assert.equal(result.scale,scale);assert.equal(result.stage,'forecast');
    assert.doesNotMatch(result.description,/并网|满发|顺桨|正常发电/);
  }
});
test('getWindDirectionInfo correctly maps 360-degree angles to 16 cardinal points', () => {
  // 无效值
  const nullDir = getWindDirectionInfo(null);
  assert.equal(nullDir.code, '—');
  assert.equal(nullDir.degrees, null);

  // 正北 (0° 或 360°)
  const north0 = getWindDirectionInfo(0);
  assert.equal(north0.code, 'N');
  assert.equal(north0.name, '北风');
  assert.equal(north0.oppositeCode, 'S');

  const north360 = getWindDirectionInfo(360);
  assert.equal(north360.code, 'N');

  // 正东 (90°)
  const east = getWindDirectionInfo(90);
  assert.equal(east.code, 'E');
  assert.equal(east.name, '东风');

  // 东南偏东 (112.5°)
  const ese = getWindDirectionInfo(112.5);
  assert.equal(ese.code, 'ESE');
  assert.equal(ese.name, '东南偏东风');

  // 东南风 (135°)
  const se = getWindDirectionInfo(135);
  assert.equal(se.code, 'SE');
  assert.equal(se.name, '东南风');
  assert.equal(se.oppositeCode, 'NW');

  // 正南 (180°)
  const south = getWindDirectionInfo(180);
  assert.equal(south.code, 'S');
  assert.equal(south.name, '南风');

  // 西北偏西 (292.5°)
  const wnw = getWindDirectionInfo(292.5);
  assert.equal(wnw.code, 'WNW');
  assert.equal(wnw.name, '西北偏西风');

  // 英文模式
  const seEn = getWindDirectionInfo(135, true);
  assert.equal(seEn.name, 'Southeast');
});


test('precipitation preserves the accumulation interval and does not invent an official warning or surface observation',()=>{
  for(const hours of [1,6,12]){
    const result=getPrecipitationInfo(20,hours);assert.match(result.desc,new RegExp(`${hours} h`));
    assert.equal(result.label,'预报累计');assert.doesNotMatch(result.label,/预警|湿|干爽/);
  }
  assert.equal(getPrecipitationInfo(null).mm,null);
  assert.equal(getPrecipitationInfo(-1).mm,null);
});
test('cloud cover labels do not assert on-site sunlight or nighttime lighting',()=>{
  for(const cloud of [10,40,75,95])assert.match(getCloudCoverageInfo(cloud).lighting,/预报/);
  assert.equal(getCloudCoverageInfo(null).percent,null);
});
test('missing, stale, unknown or invalid data never produces favorable operations advice',()=>{
  for(const args of [['clear',null,null],['unknown',6,0],['clear',NaN,0],['clear',-1,0]]){
    assert.equal(getOperationAdvice(...args).status,'unknown');
  }
  assert.equal(getOperationAdvice('clear',6,0,false,false).status,'unknown');
  assert.equal(getOperationAdvice('clear',6,0).status,'neutral');
  assert.equal(getOperationAdvice('rain',6,4).status,'warning');
  assert.equal(getOperationAdvice('clear',20,0).status,'caution');
  assert.doesNotMatch(getOperationAdvice('clear',6,0).desc,/适宜|自动航线|理想/);
});
test('coordinates retain hemispheres, including UK and southern-hemisphere scenes',()=>{
  assert.equal(formatWeatherCoordinates(55.897659,-2.507093),'55.8977°N, 2.5071°W');
  assert.equal(formatWeatherCoordinates(-33,-70),'33.0000°S, 70.0000°W');
  assert.equal(formatWeatherCoordinates(0,0),'0.0000°N, 0.0000°E');
  for(const [lat,lon] of [[91,0],[0,-181],[NaN,0]])assert.equal(formatWeatherCoordinates(lat,lon),'—');
});
