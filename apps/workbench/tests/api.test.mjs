import assert from 'node:assert/strict';
import test from 'node:test';
import { ApiError, WorkbenchApi } from '../src/api.ts';

const json = value => new Response(JSON.stringify(value), {headers: {'Content-Type':'application/json'}});
const deferred = () => {let resolve; const promise = new Promise(r => {resolve = r;}); return {promise,resolve};};

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
