import test from 'node:test';
import assert from 'node:assert/strict';
import {readCockpitAlarms,replayAlarm,requireReplaySelection} from '../src/cockpitAlarms.ts';
const start='2026-10-25T00:00:00Z',stamp=s=>new Date(Date.parse(start)+s*1000).toISOString();
const dataset=(id='SIM-PDS-13001')=>({datasetId:id,datasetRevision:'fixed:1',sourceKind:'simulated',timeFrom:start});
const detail=d=>({dataset:d,alarms:[{updatedAt:stamp(150),sourceTime:stamp(150),state:'cleared',severity:'warning'},{updatedAt:stamp(30),sourceTime:stamp(30),state:'active',severity:'critical'}],trends:[]});
test('home reuses the combined detail, preserves separate recurrence and pins every subsequent read',async()=>{
 const items=[dataset(),dataset('SIM-PDS-13001-recurrence-1'),dataset('SIM-PDS-13004')],calls=[];
 const api={request:async(path,payload,signal)=>{calls.push({path,payload,signal});return path.endsWith('catalogue')?{items,initialDetail:detail(items[0])}:detail(items.find(x=>x.datasetId===payload.datasetId));}};
 const signal=new AbortController().signal,rows=await readCockpitAlarms(api,signal);
 assert.equal(calls.length,3);assert.deepEqual(calls[0].payload,{includeDetail:true});assert.ok(calls.every(x=>x.signal===signal));
 assert.deepEqual(calls.slice(1).map(x=>x.payload),items.slice(1).map(({datasetId,datasetRevision})=>({datasetId,datasetRevision})));
 assert.deepEqual(rows.map(x=>x.dataset.datasetId),items.map(x=>x.datasetId));assert.ok(rows.every(x=>x.detail));
});
test('an unavailable or changed detail never becomes a healthy alarm row',async()=>{
 const items=[dataset(),dataset('failed'),dataset('changed')];
 const rows=await readCockpitAlarms({request:async(path,payload)=>{if(path.endsWith('catalogue'))return{items,initialDetail:detail(items[0])};if(payload.datasetId==='failed')throw Error('read failed');return detail({...items[2],datasetRevision:'new'});}},new AbortController().signal);
 assert.equal(rows[0].detail.dataset.datasetId,items[0].datasetId);assert.equal(rows[1].detail,null);assert.equal(rows[2].error.code,'SIMULATION_DATASET_CHANGED');assert.equal(replayAlarm(rows[1]),null);
});
test('aborted home loads reject, and unavailable projects are not fabricated as empty healthy lists',async()=>{
 const controller=new AbortController();controller.abort();
 await assert.rejects(readCockpitAlarms({request:async()=>({items:[]})},controller.signal),{name:'AbortError'});
 const error=Error('project unavailable');await assert.rejects(readCockpitAlarms({request:async()=>{throw error;}},new AbortController().signal),error);
});
test('home summaries use the replay source time, including pending and recovered states',()=>{
 const row={dataset:dataset(),detail:detail(dataset())};
 assert.equal(replayAlarm(row,29),null);assert.equal(replayAlarm(row).state,'active');assert.equal(replayAlarm(row).severity,'critical');assert.equal(replayAlarm(row).sourceTime,stamp(30));assert.equal(replayAlarm(row,150).state,'cleared');
});
test('opening a home case requires that exact identity and revision, never another case with the same fault code',()=>{
 const first=dataset(),recurrence=dataset('SIM-PDS-13001-recurrence-1'),catalogue={items:[first,recurrence]};
 assert.equal(requireReplaySelection(catalogue,recurrence),recurrence);
 for(const selection of [{...first,datasetRevision:'old'},dataset('missing')])assert.throws(()=>requireReplaySelection(catalogue,selection),{code:'SIMULATION_DATASET_CHANGED'});
});
