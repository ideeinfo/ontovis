import assert from 'node:assert/strict';
import test from 'node:test';
import {WorkbenchApi} from '../src/api.ts';
import {SceneApi} from '../src/sceneApi.ts';

const ref=code=>({ontobaseConnectionId:'synthetic-source',projectCode:code});
const json=value=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json'}});

test('scene requests use the selected project; shared models and uploads do not',async()=>{
  const requests=[];
  const api=new WorkbenchApi(async(path,init)=>{requests.push([path,init]);return json({sessionRevision:'r1'});});
  api.session('r1');api.selectProject(ref('A'));
  await api.request('/api/workbench/scenes',{});
  await api.request('/api/workbench/projects',{});
  await api.uploadModel(new Blob(['x'.repeat(24)]),{displayName:'Synthetic'});
  assert.deepEqual(JSON.parse(requests[0][1].body).projectRef,ref('A'));
  assert.equal(JSON.parse(requests[1][1].body).projectRef,undefined);
  const metadata=JSON.parse(Buffer.from(requests[2][1].headers['X-Model-Metadata'],'base64').toString('utf8'));
  assert.equal(metadata.projectRef,undefined);
  await new SceneApi(api).models();
  assert.equal(JSON.parse(requests[3][1].body).projectRef,undefined);
});

test('changing project discards a late success and a late denial from the previous project',async()=>{
  let resolve;const pending=new Promise(r=>resolve=r),api=new WorkbenchApi(()=>pending);let denied=0;
  api.onDenied=()=>denied++;api.onProjectDenied=()=>denied++;
  api.session('r1');api.selectProject(ref('A'));
  const read=api.request('/api/workbench/scenes',{});
  api.selectProject(ref('B'));resolve(new Response('{"code":"FORBIDDEN"}',{status:403}));
  await assert.rejects(read,{name:'AbortError'});assert.equal(denied,0);assert.deepEqual(api.project,ref('B'));
});

test('project denial does not revoke the logged-in identity; project directory access failure is local',async()=>{
  const api=new WorkbenchApi(async()=>new Response('{"code":"FORBIDDEN"}',{status:403}));
  api.session('r1');api.selectProject(ref('A'));let global=0,local=0;
  api.onDenied=()=>global++;api.onProjectDenied=()=>local++;
  await assert.rejects(api.request('/api/workbench/scenes',{}));
  assert.equal(global,0);assert.equal(local,1);assert.equal(api.revision,'r1');
  await assert.rejects(api.request('/api/workbench/projects/access',{projectRef:ref('B')}));
  assert.equal(global,0);assert.equal(local,1);
});

test('a successful response from a different project is refused',async()=>{
  const api=new WorkbenchApi(async()=>json({projectRef:ref('B'),sessionRevision:'r1'}));
  api.session('r1');api.selectProject(ref('A'));
  await assert.rejects(api.request('/api/workbench/scenes',{}),error=>error.code==='PROJECT_SCOPE_MISMATCH');
});

test('scene writes explicitly preserve the optional information version',async()=>{
  let body;
  const api=new WorkbenchApi(async(_path,init)=>{body=JSON.parse(init.body);return json({sessionRevision:'r1'});});
  api.session('r1');api.selectProject(ref('A'));
  await new SceneApi(api).save({sceneId:'synthetic',snapshot:{displayName:'Name',description:'Purpose'}});
  assert.equal(body.sceneInfoWriteVersion,1);assert.equal(body.environmentWriteVersion,1);
  assert.equal(body.snapshot.description,'Purpose');assert.deepEqual(body.projectRef,ref('A'));
});

test('shared model access errors retain identity and the selected project',async()=>{
  const api=new WorkbenchApi(async()=>new Response('{"code":"FORBIDDEN"}',{status:403}));
  api.session('r1');api.selectProject(ref('A'));let denied=0;
  api.onDenied=()=>denied++;api.onProjectDenied=()=>denied++;
  await assert.rejects(new SceneApi(api).models());
  assert.equal(denied,0);assert.equal(api.revision,'r1');assert.deepEqual(api.project,ref('A'));
});
