import assert from 'node:assert/strict';
import test from 'node:test';
import {alarmAt,sampleAt,trendDomain,trendSegments} from '../src/simulatedAlarms.ts';
const start='2026-10-25T00:00:00Z',stamp=second=>new Date(Date.parse(start)+second*1000).toISOString();
const trend={metricId:'temperature',unit:'degC',timeFrom:start,timeTo:stamp(3),samples:[
  {sourceTime:stamp(0),value:24,quality:'good'},{sourceTime:stamp(1),value:999,quality:'bad'},
  {sourceTime:stamp(2),value:null,quality:'bad'},{sourceTime:stamp(3),value:72,quality:'good'}]};
test('replay status follows source lifecycle times, not the current wall clock',()=>{
  const value={dataset:{timeFrom:start},alarms:[{updatedAt:stamp(150),state:'cleared'},{updatedAt:stamp(30),state:'active'}]};
  for(const [second,state] of [[0,'pending'],[29,'pending'],[30,'active'],[149,'active'],[150,'cleared'],[180,'cleared']])assert.equal(alarmAt(value,second),state);
});
test('bad and null samples split the chart and never enter its numerical range',()=>{
  const domain=trendDomain([trend]);assert.ok(domain[0]<24&&domain[1]>72&&domain[1]<999);
  const parts=trendSegments(trend,domain);assert.equal(parts.length,2);assert.ok(parts.every(part=>!part.includes('NaN')));
  assert.equal(sampleAt(trend,1).quality,'bad');assert.equal(sampleAt(trend,2).value,null);assert.equal(sampleAt(trend,9),null);
});
test('constant or unavailable signals keep a finite plot without invented values',()=>{
  assert.deepEqual(trendDomain([]),[0,1]);assert.deepEqual(trendSegments({...trend,samples:[]},[0,1]),[]);
  const constant={...trend,samples:[trend.samples[0],{...trend.samples[3],value:24}]};
  assert.ok(trendDomain([constant])[1]>trendDomain([constant])[0]);assert.equal(trendSegments(constant,trendDomain([constant])).length,1);
});
