import test from 'node:test';
import assert from 'node:assert/strict';
import {weatherUsable,weatherProblems} from '../src/weather.ts';
import {WorkbenchApi} from '../src/api.ts';
import {weatherEnvironment} from '../src/weatherEnvironment.ts';
import {environmentPreset} from '../src/sceneEnvironment.ts';
const now=Date.parse('2026-10-30T01:30:00Z'),value={status:'available',forecast:{usable:true,condition:'rain',validFrom:'2026-10-30T01:00:00Z',validTo:'2026-10-30T02:00:00Z',updatedAt:'2026-10-29T23:00:00Z'}};
test('weather effects expire without waiting for the next network poll',()=>{
 assert.equal(weatherUsable(value,now),true);assert.equal(weatherUsable(value,Date.parse(value.forecast.validTo)),false);
 for(const status of ['disabled','unconfigured','unavailable','stale'])assert.equal(weatherUsable({...value,status},now),false);
 assert.equal(weatherUsable({...value,forecast:{...value.forecast,condition:'unknown'}},now),false);
 assert.equal(weatherUsable({...value,forecast:{...value.forecast,updatedAt:'2026-10-30T03:00:00Z'}},now),false);
});
test('weather settings validate contact and refresh interval without scene query points',()=>{
 const config={enabled:true,provider:'met_no',contact:'https://github.com/ideeinfo/ontovis',refreshMinutes:180};
 assert.deepEqual(weatherProblems(config),[]);
 assert.deepEqual(weatherProblems({...config,contact:'ops@ontobase.ai'}),[]);
 for(const contact of ['','http://example.com','https://user:pass@example.com','bad contact','not-an-email'])assert.ok(weatherProblems({...config,contact}).includes('contact'));
 assert.ok(weatherProblems({...config,refreshMinutes:60}).includes('refreshMinutes'));
});
test('weather write-only denial preserves authorized project but membership denial clears it',async()=>{
 let code='WEATHER_WRITE_FORBIDDEN',denied=0;
 const api=new WorkbenchApi(async()=>new Response(JSON.stringify({code}),{status:403}));api.session('s');api.selectProject({ontobaseConnectionId:'x',projectCode:'p'});api.onProjectDenied=()=>denied++;
 await assert.rejects(api.request('/api/workbench/weather/save',{}),{code});assert.equal(denied,0);
 code='FORBIDDEN';await assert.rejects(api.request('/api/workbench/weather/current',{}),{code});assert.equal(denied,1);
});
test('forecast cloud cover changes a transient environment and preserves saved water/pose inputs',()=>{
 const base=environmentPreset('offshore-overview-v1'),before=structuredClone(base);
 const sunny=weatherEnvironment(base,{...value,forecast:{...value.forecast,condition:'clear',cloudPercent:0,symbol:'clearsky_day'}});
 assert.equal(sunny.atmosphere.clouds.enabled,false);assert.deepEqual(base,before);assert.deepEqual(sunny.water,base.water);
 const fog=weatherEnvironment(base,{...value,forecast:{...value.forecast,condition:'fog',cloudPercent:95,symbol:'fog'}});
 assert.equal(fog.atmosphere.clouds.coverage,.95);assert.equal(fog.atmosphere.fog.mode,'linear');assert.equal(fog.lighting.sun.enabled,false);
 const night=weatherEnvironment(base,{...value,forecast:{...value.forecast,condition:'clear',cloudPercent:0,symbol:'clearsky_night'}});
 assert.equal(night.lighting.sun.enabled,false);assert.deepEqual(night.water,base.water);
});
