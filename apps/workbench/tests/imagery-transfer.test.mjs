import assert from 'node:assert/strict';
import test from 'node:test';
import {ApiError,WorkbenchApi} from '../src/api.ts';
import {SceneApi} from '../src/sceneApi.ts';
import {prepareImageryUpload,sendImageryUpload} from '../src/imageryUpload.ts';

const metadata={clientRequestId:'original-request',displayName:'Synthetic',sourceNote:'Synthetic source',
  licenseNote:'Synthetic licence',attribution:'Synthetic',acquiredAt:'2026-10-25',qualityNote:'Not field data',rightsDeclared:true};
const prepared=()=>prepareImageryUpload(new Blob(['0123456789abcdefghijklmnopqrstuvwxyz']),metadata);
const done=p=>({state:'completed',sha256:p.expectedSourceSha256,metadata,imageryVersionId:'fixed-original',contentRevision:'fixed-content'});
const row=(p,offset=0)=>({state:'receiving',uploadId:'upload-original',uploadRevision:'receipt-'+offset,
  sha256:p.expectedSourceSha256,metadata,bytes:p.file.size,receivedBytes:offset,expiresAt:2000000000,limits:{maxChunkBytes:8}});
async function harness(offset=0){
  const pending=await prepared(),calls=[],progress=[];let current=row(pending,offset);
  const api={imageryUploadStart:async(...args)=>{calls.push(['start',...args]);return current;},
    imageryUploadStatus:async()=>{calls.push(['status']);return current;},
    imageryUploadChunk:async(file,body)=>{calls.push(['chunk',file,body]);
      assert.equal(await file.text(),(await pending.file.text()).slice(body.offset,body.offset+file.size));
      assert.equal(Buffer.from(await crypto.subtle.digest('SHA-256',await file.arrayBuffer())).toString('hex'),body.expectedChunkSha256);
      current=row(pending,body.offset+file.size);return current;},
    imageryUploadComplete:async(...args)=>{calls.push(['complete',...args]);return done(pending);}};
  return {pending,api,calls,progress,options:{progress:value=>progress.push(value)},get current(){return current;},set current(v){current=v;}};
}

test('bounded parts confirm exact bytes and SHA before the original fixed version is committed',async()=>{
  const h=await harness(),value=await sendImageryUpload(h.api,h.pending,h.options);
  assert.equal(value.imageryVersionId,'fixed-original');
  assert.deepEqual(h.calls.filter(c=>c[0]==='chunk').map(c=>[c[2].offset,c[1].size]),[[0,8],[8,8],[16,8],[24,8],[32,4]]);
  assert.equal(h.calls.filter(c=>c[0]==='complete').length,1);
  assert.deepEqual(h.progress.map(p=>p.receivedBytes),[0,8,16,24,32,36]);
  assert.equal(h.progress.at(-1).phase,'processing');
  assert.deepEqual(h.calls[0].slice(1,4),[metadata,h.pending.expectedSourceSha256,h.pending.file.size]);
});

test('server-confirmed offset is resumed without resending the prefix after restart',async()=>{
  const h=await harness(12);await sendImageryUpload(h.api,h.pending,h.options);
  assert.deepEqual(h.calls.filter(c=>c[0]==='chunk').map(c=>c[2].offset),[12,20,28]);
  assert.equal(h.progress[0].receivedBytes,12);
});

test('a lost committed-part response is checked read-only and the next part proceeds once',async()=>{
  const h=await harness(),original=h.api.imageryUploadChunk;let lost=true;
  h.api.imageryUploadChunk=async(...args)=>{const result=await original(...args);if(lost){lost=false;throw new TypeError('synthetic response lost');}return result;};
  await sendImageryUpload(h.api,h.pending,h.options);
  assert.equal(h.calls.filter(c=>c[0]==='status').length,1);
  assert.equal(h.calls.filter(c=>c[0]==='chunk'&&c[2].offset===0).length,1);
});

test('unknown part outcome never loops or automatically retransmits the file',async()=>{
  const h=await harness();h.api.imageryUploadChunk=async()=>{h.calls.push(['lost']);throw new TypeError('synthetic unsent part');};
  await assert.rejects(sendImageryUpload(h.api,h.pending),error=>error.code==='IMAGERY_UPLOAD_UNCONFIRMED');
  assert.equal(h.calls.filter(c=>c[0]==='lost').length,1);
  assert.equal(h.calls.filter(c=>c[0]==='status').length,1);
  assert.equal(h.calls.filter(c=>c[0]==='complete').length,0);
});

test('pause after a confirmed part prevents all later parts and completion',async()=>{
  const h=await harness(),controller=new AbortController(),original=h.api.imageryUploadChunk;
  h.api.imageryUploadChunk=async(...args)=>{const result=await original(...args);controller.abort();return result;};
  await assert.rejects(sendImageryUpload(h.api,h.pending,{signal:controller.signal}),error=>error.name==='AbortError');
  assert.equal(h.calls.filter(c=>c[0]==='chunk').length,1);
  assert.equal(h.calls.filter(c=>c[0]==='complete').length,0);
});

test('already-completed and fully-received starts do not send any file parts',async()=>{
  for(const completed of [false,true]){
    const h=await harness();h.current=completed?done(h.pending):row(h.pending,h.pending.file.size);
    assert.equal((await sendImageryUpload(h.api,h.pending)).imageryVersionId,'fixed-original');
    assert.equal(h.calls.filter(c=>c[0]==='chunk').length,0);
    assert.equal(h.calls.filter(c=>c[0]==='complete').length,completed?0:1);
  }
});

test('mismatched identity, size, unsafe offset and advertised part limit are refused before sending',async()=>{
  for(const changes of [{sha256:'0'.repeat(64)},{metadata:{...metadata,sourceNote:'wrong'}},
    {bytes:1},{receivedBytes:-1},{receivedBytes:0.5},{receivedBytes:1000},{limits:{maxChunkBytes:262145}}]){
    const h=await harness();h.current={...h.current,...changes};
    await assert.rejects(sendImageryUpload(h.api,h.pending),error=>['RESOURCE_CHANGED','SOURCE_UNAVAILABLE'].includes(error.code));
    assert.equal(h.calls.filter(c=>c[0]==='chunk').length,0);
  }
});

test('a stale write conflict is not treated as an uncertain network response',async()=>{
  const h=await harness();h.api.imageryUploadChunk=async()=>{throw new ApiError(409,'IMAGERY_UPLOAD_CHANGED');};
  await assert.rejects(sendImageryUpload(h.api,h.pending),error=>error.code==='IMAGERY_UPLOAD_CHANGED');
  assert.equal(h.calls.filter(c=>c[0]==='status').length,0);
});

test('a successful response that did not confirm the sent range cannot advance progress',async()=>{
  const h=await harness();h.api.imageryUploadChunk=async()=>h.current;
  await assert.rejects(sendImageryUpload(h.api,h.pending),error=>error.code==='RESOURCE_CHANGED');
  assert.equal(h.calls.filter(c=>c[0]==='complete').length,0);
});

test('chunk transport uses the fixed binary boundary with current session and project',async()=>{
  const calls=[],transport=new WorkbenchApi(async(path,options)=>{calls.push({path,options});return new Response(JSON.stringify({sessionRevision:'session:1'}));});
  transport.session('session:1');transport.selectProject({ontobaseConnectionId:'source-1',projectCode:'A'});
  const body={uploadId:'original',offset:0,expectedUploadRevision:'revision',expectedChunkSha256:'0'.repeat(64)};
  await new SceneApi(transport).imageryUploadChunk(new Blob(['x']),body);
  const call=calls[0];assert.equal(call.path,'/api/workbench/imagery/uploads/chunk');
  assert.equal(call.options.headers['Content-Type'],'application/octet-stream');
  assert.deepEqual(JSON.parse(Buffer.from(call.options.headers['X-Imagery-Chunk'],'base64').toString()),
    {...body,projectRef:{ontobaseConnectionId:'source-1',projectCode:'A'},expectedSessionRevision:'session:1'});
  assert.equal(call.options.credentials,'same-origin');assert.equal(call.options.cache,'no-store');
  await assert.rejects(new SceneApi(transport).imageryUploadChunk(new Blob([new Uint8Array(262145)]),body),error=>error.code==='IMAGERY_LIMIT_EXCEEDED');
  assert.equal(calls.length,1);
});

test('part write denial keeps the authenticated identity and project selection',async()=>{
  const transport=new WorkbenchApi(async()=>new Response(JSON.stringify({code:'IMAGERY_WRITE_FORBIDDEN'}),{status:403}));
  transport.session('session:1');transport.selectProject({ontobaseConnectionId:'source-1',projectCode:'A'});
  let denied=0;transport.onDenied=()=>denied++;transport.onProjectDenied=()=>denied++;
  await assert.rejects(new SceneApi(transport).imageryUploadChunk(new Blob(['x']),{}),error=>error.code==='IMAGERY_WRITE_FORBIDDEN');
  assert.equal(denied,0);assert.equal(transport.project.projectCode,'A');
});
