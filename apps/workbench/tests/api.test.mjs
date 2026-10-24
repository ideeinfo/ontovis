import assert from 'node:assert/strict';
import test from 'node:test';
import { ApiError, failureMessage, WorkbenchApi } from '../src/api.ts';

const json = value => new Response(JSON.stringify(value), {headers: {'Content-Type':'application/json'}});
const deferred = () => {let resolve; const promise = new Promise(r => {resolve = r;}); return {promise,resolve};};

test('model upload streams a Blob and encodes Unicode metadata with the current session', async () => {
  let sent;
  const api=new WorkbenchApi(async(path,options)=>{sent={path,options};return json({sessionRevision:'r1',item:{state:'ready'}});});
  api.session('r1');const blob=new Blob(['synthetic-glb']);await api.upload(blob,{displayName:'三柜模型',expectedLibraryRevision:'library:0'});
  assert.equal(sent.path,'/api/workbench/models/upload');assert.equal(sent.options.body,blob);
  assert.equal(sent.options.credentials,'same-origin');assert.equal(sent.options.cache,'no-store');
  const metadata=JSON.parse(Buffer.from(sent.options.headers['X-Model-Metadata'],'base64').toString('utf8'));
  assert.equal(metadata.displayName,'三柜模型');assert.equal(metadata.expectedSessionRevision,'r1');
  assert.equal(sent.options.headers.Authorization,undefined);
});

test('logout discards a late completed model import', async()=>{
  const waiting=deferred(),api=new WorkbenchApi(()=>waiting.promise);api.session('r1');
  const result=api.upload(new Blob(['synthetic']),{});api.invalidate();waiting.resolve(json({sessionRevision:'r1',item:{state:'ready'}}));
  await assert.rejects(result,{name:'AbortError'});
});
test('write permission loss does not falsely revoke a valid project read session',async()=>{
 const api=new WorkbenchApi(async()=>new Response('{"code":"MODEL_WRITE_FORBIDDEN"}',{status:403}));api.session('r1');
 let denied=false;api.onDenied=()=>{denied=true;};const epoch=api.epoch;
 await assert.rejects(api.upload(new Blob(['synthetic']),{}),error=>error.code==='MODEL_WRITE_FORBIDDEN');
 assert.equal(denied,false);assert.equal(api.epoch,epoch);
 await assert.rejects(api.request('/api/workbench/object',{}),error=>error.status===403);
 assert.equal(denied,true);
});

test('default transport calls the browser fetch without a foreign receiver', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = function () {assert.equal(this, undefined); return Promise.resolve(json({state:'signedOut'}));};
  try {assert.equal((await new WorkbenchApi().request('/api/session')).state,'signedOut');}
  finally {globalThis.fetch = original;}
});

test('protected reads use same-origin cookies, no-store and the current session revision', async () => {
  let sent;
  const api = new WorkbenchApi(async (path, options) => {sent = {path,options}; return json({sessionRevision:'fixture-r1',items:[]});});
  api.session('fixture-r1');
  await api.request('/api/workbench/evidence/resolve', {entityUid:'fixture-child'});
  assert.equal(sent.options.cache,'no-store'); assert.equal(sent.options.credentials,'same-origin');
  assert.equal(JSON.parse(sent.options.body).expectedSessionRevision,'fixture-r1');
  assert.equal(sent.options.headers.Authorization, undefined);
});

test('logout discards a late successful engineering response', async () => {
  const waiting = deferred(); const api = new WorkbenchApi(() => waiting.promise);
  api.session('fixture-r1'); const result = api.request('/api/workbench/object',{});
  api.invalidate(); waiting.resolve(json({sessionRevision:'fixture-r1',item:{secret:'old-user'}}));
  await assert.rejects(result, {name:'AbortError'});
});

test('an old denial cannot clear a newly signed-in user', async () => {
  const waiting = deferred(); const api = new WorkbenchApi(() => waiting.promise); let denied = 0;
  api.onDenied = () => {denied += 1;}; api.session('old');
  const result = api.request('/api/workbench/object',{}); api.session('new');
  waiting.resolve(new Response('{"code":"FORBIDDEN"}', {status:403}));
  await assert.rejects(result, {name:'AbortError'}); assert.equal(denied,0);
});

test('session invalidation during decoding discards the decoded body', async () => {
  const decoding = deferred(); let started;
  const start = new Promise(r => {started = r;});
  const api = new WorkbenchApi(async () => ({ok:true,json:() => {started(); return decoding.promise;}}));
  api.session('r1'); const result = api.request('/api/workbench/context',{}); await start;
  api.invalidate(); decoding.resolve({context:{private:'old'}});
  await assert.rejects(result, {name:'AbortError'});
});

test('current permission denial invalidates other requests and clears protected state', async () => {
  const api = new WorkbenchApi(async () => new Response('{"code":"FORBIDDEN"}', {status:403}));
  api.session('r1'); const epoch = api.epoch; let denied;
  api.onDenied = status => {denied = status;};
  await assert.rejects(api.request('/api/workbench/evidence/content',{}), error => error instanceof ApiError && error.status === 403);
  assert.equal(denied,403); assert.ok(api.epoch > epoch);
});

test('late images are discarded on object selection change', async () => {
  const waiting = deferred(); const api = new WorkbenchApi(() => waiting.promise);
  api.session('r1'); const controller = new AbortController();
  const result = api.request('/api/workbench/evidence/content',{},controller.signal,true);
  controller.abort(); waiting.resolve(new Response(new Blob(['synthetic'], {type:'image/png'}),{headers:{'X-Session-Revision':'r1'}}));
  await assert.rejects(result, {name:'AbortError'});
});

test('an image from another session is refused before creating an object URL', async () => {
  const api = new WorkbenchApi(async () => new Response(new Blob(['synthetic'],{type:'image/png'}), {headers:{'X-Session-Revision':'old'}}));
  api.session('new');
  await assert.rejects(api.request('/api/workbench/evidence/content',{},undefined,true), error => error.code === 'SOURCE_UNAVAILABLE');
});

test('a content conflict stays a conflict, without an automatic fallback read', async () => {
  let calls = 0;
  const api = new WorkbenchApi(async () => {calls += 1; return new Response('{"code":"CONTENT_CHANGED"}',{status:409});});
  api.session('r1');
  await assert.rejects(api.request('/api/workbench/evidence/content',{}), error => error.status === 409 && error.code === 'CONTENT_CHANGED');
  assert.equal(calls,1);
});

test('protected model bytes require the model media type and matching session', async () => {
  const api = new WorkbenchApi(async()=>new Response('synthetic-model',{headers:{'Content-Type':'model/gltf-binary','X-Session-Revision':'r1'}}));
  api.session('r1');const blob=await api.request('/api/workbench/model/content',{},undefined,'model');
  assert.equal(blob.type,'model/gltf-binary');
  const wrong=new WorkbenchApi(async()=>new Response('html',{headers:{'Content-Type':'text/html','X-Session-Revision':'r1'}}));wrong.session('r1');
  await assert.rejects(wrong.request('/api/workbench/model/content',{},undefined,'model'),error=>error instanceof ApiError&&error.status===502);
});

const sha256 = async data => Buffer.from(await crypto.subtle.digest('SHA-256', data)).toString('hex');
const fixedResponse = (data, sha, mime = 'application/octet-stream', headers = {}) => new Response(data, {headers:{
  'Content-Type':mime, 'X-Session-Revision':'r1', 'X-Content-SHA256':sha, ...headers,
}});

test('new project GLB and terrain uploads use separate fixed headers and retain session guards', async () => {
  const calls = [];
  const api = new WorkbenchApi(async(path, options) => {calls.push({path, options});return json({sessionRevision:'r1'});});
  api.session('r1');
  const file = new Blob(['x'.repeat(32)]);
  for (const kind of ['uploadModel', 'uploadTerrain']) {
    await api[kind](file, {displayName:'模型与地形来源', expectedSessionRevision:'spoofed'});
  }
  for (const [index, kind] of ['Model', 'Terrain'].entries()) {
    const {path, options} = calls[index];
    assert.equal(path, index ? '/api/workbench/terrains/upload' : '/api/workbench/resources/model/upload');
    assert.equal(options.body, file);assert.equal(options.credentials, 'same-origin');assert.equal(options.cache, 'no-store');
    assert.equal(options.headers['Content-Type'], index ? 'image/tiff' : 'model/gltf-binary');
    const metadata = JSON.parse(Buffer.from(options.headers[`X-${kind}-Metadata`], 'base64').toString('utf8'));
    assert.equal(metadata.displayName, '模型与地形来源');assert.equal(metadata.expectedSessionRevision, 'r1');
    assert.equal(options.headers.Authorization, undefined);
  }
});

test('restricted uploads reject empty, over-budget and oversized metadata before transport', async () => {
  let calls = 0;
  const api = new WorkbenchApi(async() => {calls++;return json({});});api.session('r1');
  for (const [method, size, code] of [['uploadModel',23,'MODEL_LIMIT_EXCEEDED'],
    ['uploadModel',20*1024*1024+1,'MODEL_LIMIT_EXCEEDED'], ['uploadTerrain',7,'TERRAIN_LIMIT_EXCEEDED'],
    ['uploadTerrain',256*1024*1024+1,'TERRAIN_LIMIT_EXCEEDED']]) {
    await assert.rejects(api[method]({size}, {}), error => error instanceof ApiError && error.status === 413 && error.code === code);
  }
  await assert.rejects(api.uploadTerrain(new Blob(['x'.repeat(8)]), {note:'中'.repeat(2100)}), error => error.status === 413);
  assert.equal(calls, 0);
});

test('write-only endpoint pairs preserve reads; shared model denials stay local', async () => {
  const allowed = {
    MODEL_WRITE_FORBIDDEN:['models/upload','models/binding','resources/model/upload','resources/model/calibrate'],
    SCENE_WRITE_FORBIDDEN:['scenes/create','scenes/save','terrains/upload','terrains/job/cancel','public-geodata/start','public-geodata/cancel'],
  };
  for (const [code, paths] of Object.entries(allowed)) {
    for (const path of paths) {
      const api = new WorkbenchApi(async() => new Response(JSON.stringify({code}), {status:403}));api.session('r1');
      let denied = false;api.onDenied = () => {denied = true;};const epoch = api.epoch;
      await assert.rejects(api.request(`/api/workbench/${path}`, {}), error => error.code === code);
      assert.equal(denied, false, `${code}: ${path}`);assert.equal(api.epoch, epoch);
    }
  }
  for (const body of [{code:'FORBIDDEN'}, {code:'SCENE_WRITE_FORBIDDEN'}, {code:'toString'}, null]) {
    const api = new WorkbenchApi(async() => new Response(JSON.stringify(body), {status:403}));api.session('r1');
    let denied = false;api.onDenied = () => {denied = true;};
    await assert.rejects(api.request('/api/workbench/resources/model', {}), error => error instanceof ApiError && error.status === 403);
    assert.equal(denied, false);
  }
});

test('fixed binary reads verify media, session, length, header fingerprint and actual SHA before returning bytes', async () => {
  const data = new TextEncoder().encode('private fixture bytes');const sha = await sha256(data);
  for (const mime of ['model/gltf-binary', 'application/octet-stream']) {
    const api = new WorkbenchApi(async() => fixedResponse(data, sha, mime, {'Content-Length':String(data.length)}));api.session('r1');
    const blob = await api.content('/api/workbench/resources/model/content', {}, {mime,maxBytes:data.length,sha256:sha});
    assert.equal(blob.type, mime);assert.deepEqual(new Uint8Array(await blob.arrayBuffer()), data);
  }
  const cases = [
    [data, {}, 'text/html', 502, 'SOURCE_UNAVAILABLE'],
    [data, {'X-Session-Revision':'old'}, 'application/octet-stream', 502, 'SOURCE_UNAVAILABLE'],
    [data, {'X-Content-SHA256':'0'.repeat(64)}, 'application/octet-stream', 409, 'RESOURCE_CHANGED'],
    [new TextEncoder().encode('corrupt fixture bytes'), {}, 'application/octet-stream', 409, 'RESOURCE_CHANGED'],
    [data, {'Content-Length':String(data.length-1)}, 'application/octet-stream', 502, 'SOURCE_UNAVAILABLE'],
    [data, {'Content-Length':'-1'}, 'application/octet-stream', 502, 'SOURCE_UNAVAILABLE'],
  ];
  for (const [bytes, headers, mime, status, code] of cases) {
    const api = new WorkbenchApi(async() => fixedResponse(bytes, sha, mime, headers));api.session('r1');
    await assert.rejects(api.content('/api/workbench/terrains/content', {},
      {mime:'application/octet-stream',maxBytes:100,sha256:sha}), error => error.status === status && error.code === code);
  }
});

test('declared over-budget binary is cancelled without reading its body', async () => {
  let cancelled = false, read = false;
  const sha = 'a'.repeat(64);
  const api = new WorkbenchApi(async() => ({ok:true,headers:new Headers({'Content-Type':'application/octet-stream',
    'Content-Length':'9','X-Session-Revision':'r1','X-Content-SHA256':sha}),
    body:{cancel:async()=>{cancelled=true;},getReader:()=>{read=true;throw new Error('must not read');}}}));
  api.session('r1');
  await assert.rejects(api.content('/api/workbench/terrains/content', {},
    {mime:'application/octet-stream',maxBytes:8,sha256:sha}), error => error.code === 'CONTENT_LIMIT_EXCEEDED');
  assert.equal(cancelled, true);assert.equal(read, false);
});

test('an absent or false Content-Length cannot bypass the streaming byte budget', async () => {
  for (const length of [undefined, '4']) {
    let cancelled = false;
    const stream = new ReadableStream({start(controller){controller.enqueue(new Uint8Array(9));},cancel(){cancelled=true;}});
    const headers = length === undefined ? {} : {'Content-Length':length};
    const api = new WorkbenchApi(async() => fixedResponse(stream, 'a'.repeat(64), 'application/octet-stream', headers));api.session('r1');
    await assert.rejects(api.content('/api/workbench/terrains/content', {},
      {mime:'application/octet-stream',maxBytes:8,sha256:'a'.repeat(64)}), error => error.code === 'CONTENT_LIMIT_EXCEEDED');
    assert.equal(cancelled, true);
  }
});

test('invalid binary descriptors are rejected before transport', async () => {
  let calls = 0;const api = new WorkbenchApi(async() => {calls++;return fixedResponse('', 'a'.repeat(64));});api.session('r1');
  for (const descriptor of [{mime:'text/html',maxBytes:8,sha256:'a'.repeat(64)},
    {mime:'application/octet-stream',maxBytes:0,sha256:'a'.repeat(64)},
    {mime:'application/octet-stream',maxBytes:256*1024*1024+1,sha256:'a'.repeat(64)},
    {mime:'model/gltf-binary',maxBytes:20*1024*1024+1,sha256:'a'.repeat(64)},
    {mime:'application/octet-stream',maxBytes:8,sha256:'unverified'}]) {
    await assert.rejects(api.content('/api/workbench/terrains/content', {}, descriptor), error => error.code === 'INVALID_REQUEST');
  }
  assert.equal(calls, 0);
});

test('logout during binary digest discards already decoded private bytes', async () => {
  const data = new TextEncoder().encode('private fixture');const sha = await sha256(data);
  const api = new WorkbenchApi(async() => fixedResponse(data, sha));api.session('r1');
  const waiting = deferred(), started = deferred(), original = crypto.subtle.digest;
  crypto.subtle.digest = () => {started.resolve();return waiting.promise;};
  try {
    const result = api.content('/api/workbench/terrains/content', {}, {mime:'application/octet-stream',maxBytes:100,sha256:sha});
    await started.promise;api.invalidate();waiting.resolve(new Uint8Array(32).buffer);
    await assert.rejects(result, {name:'AbortError'});
  } finally {crypto.subtle.digest = original;}
});

test('selection cancellation during a binary stream cancels that body and discards late bytes', async () => {
  let controller, cancelled = false;
  const stream = new ReadableStream({start(value){controller=value;},cancel(){cancelled=true;}});
  const api = new WorkbenchApi(async() => fixedResponse(stream, 'a'.repeat(64)));api.session('r1');
  const abort = new AbortController();
  const result = api.content('/api/workbench/terrains/content', {},
    {mime:'application/octet-stream',maxBytes:100,sha256:'a'.repeat(64)}, abort.signal);
  await new Promise(resolve=>setImmediate(resolve));abort.abort();controller.enqueue(new Uint8Array(8));
  await assert.rejects(result, {name:'AbortError'});assert.equal(cancelled, true);
});

test('new business failures have concise Chinese and English messages', () => {
  for (const code of ['SCENE_CHANGED','SPATIAL_PRECHECK_INVALID','MODEL_CALIBRATION_REQUIRED','NO_DATA','TERRAIN_BUSY']) {
    const error = new ApiError(409, code), zh = failureMessage(error, 'zh'), en = failureMessage(error, 'en');
    assert.equal(typeof zh, 'string');assert.equal(typeof en, 'string');assert.notEqual(zh, en);
    assert.ok(!zh.includes(code) && !en.includes(code));
  }
  assert.equal(failureMessage(new ApiError(403,'toString'),'zh'),'资料不可用或无权访问。');
});
