import test from 'node:test';
import assert from 'node:assert/strict';
import {weatherUsable,weatherProblems,weatherScenes} from '../src/weather.ts';
import {WorkbenchApi} from '../src/api.ts';
const now=Date.parse('2026-10-30T01:30:00Z'),value={status:'available',forecast:{usable:true,condition:'rain',validFrom:'2026-10-30T01:00:00Z',validTo:'2026-10-30T02:00:00Z',updatedAt:'2026-10-29T23:00:00Z'}};
test('weather effects expire without waiting for the next network poll',()=>{
 assert.equal(weatherUsable(value,now),true);assert.equal(weatherUsable(value,Date.parse(value.forecast.validTo)),false);
 for(const status of ['disabled','unconfigured','unavailable','stale'])assert.equal(weatherUsable({...value,status},now),false);
 assert.equal(weatherUsable({...value,forecast:{...value.forecast,condition:'unknown'}},now),false);
 assert.equal(weatherUsable({...value,forecast:{...value.forecast,updatedAt:'2026-10-30T03:00:00Z'}},now),false);
});
test('weather settings reject absent and duplicate points and invalid coordinates',()=>{
 const point={sceneId:'scene',label:'point',latitude:39.9,longitude:116.4},config={enabled:true,contact:'https://github.com/ideeinfo/ontovis',points:[point]};
 assert.deepEqual(weatherProblems(config),[]);
 for(const points of [[],[point,point],[{...point,latitude:NaN}],[{...point,longitude:181}],[{...point,label:' '}]])assert.ok(weatherProblems({...config,points}).length);
});
test('weather scene selection pages stable authorized catalog and aborts mixed revisions',async()=>{
 let calls=0;const api={request:async()=>({items:[{sceneId:String(++calls)}],snapshotRevision:'r',nextCursor:calls===1?'next':null})};
 assert.equal((await weatherScenes(api,new AbortController().signal)).length,2);
 calls=0;api.request=async()=>({items:[],snapshotRevision:String(++calls),nextCursor:'next'});
 await assert.rejects(weatherScenes(api,new AbortController().signal),{code:'SCENE_CHANGED'});
});
test('weather write-only denial preserves authorized project but membership denial clears it',async()=>{
 let code='WEATHER_WRITE_FORBIDDEN',denied=0;
 const api=new WorkbenchApi(async()=>new Response(JSON.stringify({code}),{status:403}));api.session('s');api.selectProject({ontobaseConnectionId:'x',projectCode:'p'});api.onProjectDenied=()=>denied++;
 await assert.rejects(api.request('/api/workbench/weather/save',{}),{code});assert.equal(denied,0);
 code='FORBIDDEN';await assert.rejects(api.request('/api/workbench/weather/current',{}),{code});assert.equal(denied,1);
});
