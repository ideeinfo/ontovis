import assert from 'node:assert/strict';
import test from 'node:test';
import {ApiError,WorkbenchApi} from '../src/api.ts';
import {SceneApi} from '../src/sceneApi.ts';
import {checkImageryUpload,prepareImageryUpload,uncertainImageryUpload} from '../src/imageryUpload.ts';
import {imageryFailure} from '../src/imageryMessages.ts';

const metadata={clientRequestId:'request-original',displayName:'Synthetic',sourceNote:'Original source',
  licenseNote:'Synthetic',attribution:'Test',acquiredAt:'2026-10-24',qualityNote:'Not engineering accuracy',rightsDeclared:true};
const json=(body,status=200)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
const attempt=()=>prepareImageryUpload(new Blob(['original immutable bytes']),metadata);

test('preparation binds the exact original bytes and keeps an immutable copy of the submitted details',async()=>{
  const input={...metadata},file=new Blob(['original immutable bytes']);
  const pending=await prepareImageryUpload(file,input);
  input.sourceNote='Changed after submission';
  assert.equal(pending.file,file);assert.equal(pending.metadata.sourceNote,metadata.sourceNote);
  assert.equal(pending.expectedSourceSha256,Buffer.from(await crypto.subtle.digest('SHA-256',await file.arrayBuffer())).toString('hex'));
  assert.ok(Object.isFrozen(pending.metadata));
});

test('a committed upload with a lost response is recovered by a short project-scoped query without sending the file',async()=>{
  const pending=await attempt(),calls=[];
  const transport=new WorkbenchApi(async(path,options)=>{calls.push({path,options});return json({state:'completed',
    sessionRevision:'session:1',sha256:pending.expectedSourceSha256,metadata,imageryVersionId:'fixed-original',contentRevision:'fixed-content'});});
  transport.session('session:1');transport.selectProject({ontobaseConnectionId:'source-1',projectCode:'A'});
  const result=await checkImageryUpload(new SceneApi(transport),pending);
  assert.equal(result.imageryVersionId,'fixed-original');assert.equal(calls.length,1);
  assert.equal(calls[0].path,'/api/workbench/imagery/upload-result');
  assert.deepEqual(JSON.parse(calls[0].options.body),{metadata,expectedSourceSha256:pending.expectedSourceSha256,
    projectRef:{ontobaseConnectionId:'source-1',projectCode:'A'},expectedSessionRevision:'session:1'});
  assert.equal(calls[0].options.credentials,'same-origin');assert.equal(calls[0].options.cache,'no-store');
  assert.equal(calls[0].options.headers['Content-Type'],'application/json');
});

test('unknown result remains unconfirmed and never starts another upload or invents failure',async()=>{
  const pending=await attempt();let calls=0;
  const api=new SceneApi(new WorkbenchApi(async(path)=>{calls++;assert.equal(path,'/api/workbench/imagery/upload-result');return json({state:'unknown'});}));
  for(let i=0;i<2;i++)await assert.rejects(checkImageryUpload(api,pending),e=>e.code==='IMAGERY_UPLOAD_UNCONFIRMED');
  assert.equal(calls,2);assert.equal(pending.metadata.clientRequestId,metadata.clientRequestId);
  assert.match(imageryFailure(new ApiError(503,'IMAGERY_UPLOAD_UNCONFIRMED'),'zh'),/不代表上传失败/);
  assert.match(imageryFailure(new ApiError(503,'IMAGERY_UPLOAD_UNCONFIRMED'),'en'),/does not mean failure/);
});

test('wrong file, wrong original request and invalid result state cannot be adopted',async()=>{
  const pending=await attempt();
  for(const patch of [{sha256:'0'.repeat(64)},{metadata:{...metadata,clientRequestId:'different'}},{state:'failed'}]){
    const api={async imageryUploadResult(){return {state:'completed',sha256:pending.expectedSourceSha256,metadata,...patch};}};
    await assert.rejects(checkImageryUpload(api,pending),e=>e.code==='RESOURCE_CHANGED');
  }
});

test('permission and request conflicts are not treated as successful recovery',async()=>{
  const pending=await attempt();
  for(const [status,code] of [[403,'FORBIDDEN'],[409,'REQUEST_CONFLICT']]){
    const api=new SceneApi(new WorkbenchApi(async()=>json({code},status)));
    await assert.rejects(checkImageryUpload(api,pending),e=>e.status===status&&e.code===code);
  }
});

test('project changes discard a late recovery result through the existing request epoch',async()=>{
  let resolve,started;const waiting=new Promise(yes=>started=yes),response=new Promise(yes=>resolve=yes);
  const transport=new WorkbenchApi(async()=>{started();return response;});transport.session('session:1');
  const pending=await attempt(),read=checkImageryUpload(new SceneApi(transport),pending);await waiting;
  transport.selectProject({ontobaseConnectionId:'source-1',projectCode:'B'});
  resolve(json({state:'completed',metadata,sha256:pending.expectedSourceSha256}));
  await assert.rejects(read,e=>e.name==='AbortError');
});

test('cancelled preparation stops before an upload and only uncertain transport errors require result checks',async()=>{
  const controller=new AbortController();controller.abort();
  await assert.rejects(prepareImageryUpload(new Blob(['data']),metadata,controller.signal),e=>e.name==='AbortError');
  for(const value of [new TypeError('network'),new ApiError(524,'SOURCE_UNAVAILABLE'),new ApiError(429,'IMAGERY_BUSY')])assert.equal(uncertainImageryUpload(value),true);
  for(const value of [controller.signal.reason,new ApiError(403,'IMAGERY_WRITE_FORBIDDEN'),new ApiError(409,'REQUEST_CONFLICT'),new ApiError(422,'UNSUPPORTED_IMAGERY')])assert.equal(uncertainImageryUpload(value),false);
});
