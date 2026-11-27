import assert from 'node:assert/strict';
import test from 'node:test';
import {ApiError,WorkbenchApi} from '../src/api.ts';
import {PublicGeoWrite,cancelPublicGeo,mapCoordinate,mapPixel,readPublicGeo,startPublicGeo,validPublicGeo} from '../src/publicGeoApi.ts';
import {publicGeoFailure} from '../src/publicGeoMessages.ts';

test('public source center and radius reject nonfinite, date-line and polar extents',()=>{
 assert.equal(validPublicGeo(113.18,33.45,1),true);
 for(const values of [[NaN,33,1],[113,Infinity,1],[180,33,1],[179.999,33,10],[113,84,1],[113,33,.1],[113,33,11]])assert.equal(validPublicGeo(...values),false,JSON.stringify(values));
});
test('map click coordinates preserve longitude/latitude order through zoom and hemisphere changes',()=>{
 for(const point of [[113.18,33.45],[-122.4,37.7],[20,-33],[0,0],[179,80]])for(const zoom of [2,8,15]){
  const round=mapCoordinate(...mapPixel(...point,zoom),zoom);
  assert.ok(Math.abs(round[0]-point[0])<1e-8);assert.ok(Math.abs(round[1]-point[1])<1e-8);
 }
});
test('public acquisition uses only exact same-origin paths and session-conditioned JSON',async()=>{
 const calls=[],api=new WorkbenchApi(async(path,init)=>{calls.push([path,JSON.parse(init.body)]);return new Response('{"sessionRevision":"current","jobId":"job"}',{headers:{'Content-Type':'application/json'}});});api.session('current');
 const body={name:'Overview',longitude:113.18,latitude:33.45,radiusKm:1,terrain:true,imagery:true,clientRequestId:'fixed-request'};
 await startPublicGeo(api,body);await readPublicGeo(api,'job');await readPublicGeo(api);await cancelPublicGeo(api,{jobId:'job',jobRevision:'fixed-revision'});
 assert.deepEqual(calls,[['/api/workbench/public-geodata/start',{...body,expectedSessionRevision:'current'}],['/api/workbench/public-geodata/job',{jobId:'job',expectedSessionRevision:'current'}],['/api/workbench/public-geodata/job',{expectedSessionRevision:'current'}],['/api/workbench/public-geodata/cancel',{jobId:'job',expectedJobRevision:'fixed-revision',expectedSessionRevision:'current'}]]);
 assert.equal(body.expectedSessionRevision,undefined);
});
test('late public acquisition responses are discarded after a session change',async()=>{
 let finish;const pending=new Promise(resolve=>{finish=resolve;});
 const api=new WorkbenchApi(()=>pending);api.session('before');const work=readPublicGeo(api,'job');api.session('after');
 finish(new Response('{"sessionRevision":"before"}'));await assert.rejects(work,error=>error.name==='AbortError');
});
test('public failures explain a bounded retry without claiming successful imports or exposing raw errors',()=>{
 for(const locale of ['zh','en'])for(const code of ['PUBLIC_COVERAGE_UNAVAILABLE','PUBLIC_LIMIT_EXCEEDED','PUBLIC_ACQUISITION_BUSY','PUBLIC_JOB_CHANGED','PUBLIC_PROCESSING_INTERRUPTED','SCENE_WRITE_FORBIDDEN']){
  const text=publicGeoFailure(new ApiError(422,code),locale);assert.ok(text.length>5);assert.ok(!text.includes(code));
 }
 assert.ok(!publicGeoFailure(new Error('private path /credentials'),'zh').includes('credentials'));
});

test('a lost start response preserves the same request ID even when an older terminal job is displayed',async()=>{
 const write=new PublicGeoWrite(),body={name:'Overview',longitude:113.18,latitude:33.45,radiusKm:1,terrain:true,imagery:true};
 const old={state:'ready',request:{clientRequestId:'old-completed-job'}};
 const first=write.begin(body,old),calls=[];
 const api=new WorkbenchApi(async(path,init)=>{calls.push(JSON.parse(init.body));throw new TypeError('simulated response lost after server accepted start');});api.session('current');
 await assert.rejects(startPublicGeo(api,first));
 const retry=write.begin(body,old);assert.equal(retry.clientRequestId,first.clientRequestId);
 await assert.rejects(startPublicGeo(api,retry));assert.equal(calls[0].clientRequestId,calls[1].clientRequestId);
 const completed={state:'ready',request:{clientRequestId:first.clientRequestId}};
 assert.notEqual(write.begin(body,completed).clientRequestId,first.clientRequestId);
});
