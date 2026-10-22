import assert from 'node:assert/strict';
import test from 'node:test';
import {WorkbenchApi} from '../src/api.ts';
import {SceneApi} from '../src/sceneApi.ts';

const json = value => new Response(JSON.stringify(value), {headers:{'Content-Type':'application/json'}});
const sha256 = async data => Buffer.from(await crypto.subtle.digest('SHA-256', data)).toString('hex');
const fixed = (data, sha, mime) => new Response(data, {headers:{'Content-Type':mime,
  'Content-Length':String(data.length), 'X-Session-Revision':'session:1', 'X-Content-SHA256':sha}});

test('scene methods preserve exact request revisions, IDs and anchor receipt without implicit fallback', async () => {
  const calls = [];
  const transport = new WorkbenchApi(async(path, options) => {calls.push({path,options});return json({sessionRevision:'session:1'});});
  transport.session('session:1');const api = new SceneApi(transport);const controller = new AbortController();
  const save = {sceneId:'scene-id',expectedSceneRevision:'scene:old',clientRequestId:'request-id',snapshot:{displayName:'业务场景'},
    reviewedEngineering:[],rootBindingChanges:[],spatialChange:{kind:'anchor',receipt:'fixed-receipt'}};
  const checks = [
    ['scenes',{q:'设备',cursor:'fixed-cursor',limit:2},()=>api.list({q:'设备',cursor:'fixed-cursor',limit:2},controller.signal)],
    ['scenes/create',{displayName:'业务场景',clientRequestId:'create-id'},()=>api.create({displayName:'业务场景',clientRequestId:'create-id'},controller.signal)],
    ['scenes/open',{sceneId:'scene-id'},()=>api.open('scene-id',undefined,controller.signal)],
    ['scenes/open',{sceneId:'scene-id',sceneRevision:'scene:fixed'},()=>api.open('scene-id','scene:fixed',controller.signal)],
    ['scenes/head',{sceneId:'scene-id',viewingRevision:'scene:fixed'},()=>api.head('scene-id','scene:fixed',controller.signal)],
    ['scenes/check',{kind:'validate',sceneId:'scene-id',expectedSceneRevision:'scene:old',snapshot:{}},()=>api.check({kind:'validate',sceneId:'scene-id',expectedSceneRevision:'scene:old',snapshot:{}},controller.signal)],
    ['scenes/save',save,()=>api.save(save,controller.signal)],
  ];
  for (const [path, body, run] of checks) {
    await run();const sent = calls.at(-1);
    assert.equal(sent.path, `/api/workbench/${path}`);assert.equal(sent.options.method,'POST');
    assert.equal(sent.options.signal,controller.signal);
    assert.deepEqual(JSON.parse(sent.options.body),{...body,expectedSessionRevision:'session:1'});
  }
  assert.equal(calls.length,checks.length);assert.equal(save.clientRequestId,'request-id');
});

test('resource and terrain methods use only the implemented fixed paths and model use scope', async () => {
  const calls = [];
  const transport = new WorkbenchApi(async(path, options) => {calls.push({path,body:JSON.parse(options.body)});return json({sessionRevision:'session:1'});});
  transport.session('session:1');const api = new SceneApi(transport);
  const calibration = {modelVersionId:'model-v1',expectedContentRevision:'content:1',expectedLibraryRevision:'library:1',clientRequestId:'calibration-id',
    calibration:{unit:'m',axes:'Y_UP_RIGHT_HANDED',basePoint:[0,0,0],forward:[0,0,-1]}};
  const cancel = {jobId:'job-id',expectedJobRevision:'job:1',clientRequestId:'cancel-id'};
  const checks = [
    ['resources/models',{purpose:'equipment',expectedLibraryRevision:'library:1'},()=>api.models({purpose:'equipment',expectedLibraryRevision:'library:1'})],
    ['resources/model',{modelAssetId:'asset-id',modelVersionId:'model-v1'},()=>api.model('asset-id','model-v1')],
    ['resources/model/calibrate',calibration,()=>api.calibrateModel(calibration)],
    ['resources/uses',{resourceKind:'model',versionId:'model-v1',scope:'retained',cursor:'cursor'},()=>api.modelUses({versionId:'model-v1',scope:'retained',cursor:'cursor'})],
    ['terrains/job',{jobId:'job-id'},()=>api.job('job-id')],
    ['terrains/job/cancel',cancel,()=>api.cancelTerrain(cancel)],
    ['terrains/version',{terrainVersionId:'terrain-v1'},()=>api.version('terrain-v1')],
  ];
  for (const [path, body, run] of checks) {
    await run();assert.deepEqual(calls.at(-1),{path:`/api/workbench/${path}`,body:{...body,expectedSessionRevision:'session:1'}});
  }
  assert.equal(calls.length,checks.length);
  assert.equal(typeof api.replacementCheck,'undefined');assert.equal(typeof api.bind,'undefined');
});

test('resource upload wrappers preserve source declarations and idempotency keys', async () => {
  const calls = [];
  const transport = new WorkbenchApi(async(path, options) => {calls.push({path,options});return json({sessionRevision:'session:1'});});
  transport.session('session:1');const api = new SceneApi(transport),file = new Blob(['x'.repeat(32)]);
  const model = {expectedLibraryRevision:'library:1',clientRequestId:'model-id',displayName:'测试资源',purpose:'equipment',sourceNote:'合成模型',rightsDeclared:true};
  const terrain = {clientRequestId:'terrain-id',displayName:'测试地形',sourceNote:'合成高程',licenseNote:'测试素材',rightsDeclared:true,
    verticalDatum:'UNKNOWN_RELATIVE',relativeReferenceId:'relative:fixture',heightUnit:'m',aoi:[110,32,111,33]};
  await api.uploadModel(file,model);await api.uploadTerrain(file,terrain);
  for (const [index, metadata] of [model,terrain].entries()) {
    const header = index ? 'X-Terrain-Metadata' : 'X-Model-Metadata',sent = calls[index];
    assert.deepEqual(JSON.parse(Buffer.from(sent.options.headers[header],'base64').toString('utf8')),
      {...metadata,expectedSessionRevision:'session:1'});
    assert.equal(sent.options.body,file);
  }
  assert.equal(calls[0].path,'/api/workbench/resources/model/upload');assert.equal(calls[1].path,'/api/workbench/terrains/upload');
});

test('fixed model and terrain artifact reads carry content fingerprints and return verified private bytes', async () => {
  const data = new TextEncoder().encode('fixed resource bytes'),sha = await sha256(data),calls = [];
  const transport = new WorkbenchApi(async(path,options) => {
    calls.push({path,body:JSON.parse(options.body)});
    return fixed(data,sha,path.includes('/resources/')?'model/gltf-binary':'application/octet-stream');
  });transport.session('session:1');const api = new SceneApi(transport);
  const model = {modelVersionId:'model-v1',contentRevision:'content:1',sha256:sha,bytes:data.length};
  const artifact = {artifactId:'positions.f32',sha256:sha,bytes:data.length,format:'float32_le'};
  for (const blob of [await api.modelContent(model),await api.content('terrain-v1',artifact)]) {
    assert.equal(await blob.text(),'fixed resource bytes');
  }
  assert.deepEqual(calls,[
    {path:'/api/workbench/resources/model/content',body:{modelVersionId:'model-v1',expectedContentRevision:'content:1',expectedSha256:sha,expectedSessionRevision:'session:1'}},
    {path:'/api/workbench/terrains/content',body:{terrainVersionId:'terrain-v1',artifactId:'positions.f32',expectedSha256:sha,expectedSessionRevision:'session:1'}},
  ]);
});

test('terrain source and derived artifact budgets remain distinct and require declared sizes', async () => {
  let calls = 0;
  const transport = new WorkbenchApi(async() => {calls++;return json({});});transport.session('session:1');const api = new SceneApi(transport);
  for (const [artifactId,bytes] of [['positions.f32',16*1024*1024+1],['source.tif',256*1024*1024+1],['mask.u8',0]]) {
    await assert.rejects(api.content('terrain-v1',{artifactId,bytes,sha256:'a'.repeat(64)}), error => error.code === 'TERRAIN_LIMIT_EXCEEDED');
  }
  assert.equal(calls,0);
});

test('a scene conflict is returned once without selecting a new head or manufacturing success', async () => {
  const calls = [];
  const transport = new WorkbenchApi(async(path) => {calls.push(path);return new Response('{"code":"SCENE_CHANGED"}',{status:409});});
  transport.session('session:1');const api = new SceneApi(transport);
  await assert.rejects(api.save({sceneId:'scene-id',expectedSceneRevision:'scene:old',clientRequestId:'same-request',snapshot:{},reviewedEngineering:[],rootBindingChanges:[]}),
    error => error.status === 409 && error.code === 'SCENE_CHANGED');
  assert.deepEqual(calls,['/api/workbench/scenes/save']);
});

test('existing-model discovery, explicit reuse and saved terrain discovery use their real project paths', async () => {
  const calls = [],controller = new AbortController();
  const transport = new WorkbenchApi(async(path, options) => {
    calls.push({path,body:JSON.parse(options.body),signal:options.signal});return json({sessionRevision:'session:1'});
  });transport.session('session:1');const api = new SceneApi(transport);
  const reuse = {legacyModelVersionId:'legacy-fixed',expectedModelRevision:4,expectedSha256:'a'.repeat(64),
    expectedLibraryRevision:'library:7',purpose:'equipment',clientRequestId:'reuse-id'};
  await api.legacyModels(controller.signal);await api.importExistingModel(reuse,controller.signal);
  await api.terrains({q:'地区',cursor:'fixed-cursor',limit:2},controller.signal);
  assert.deepEqual(calls,[
    {path:'/api/workbench/resources/models/legacy',body:{expectedSessionRevision:'session:1'},signal:controller.signal},
    {path:'/api/workbench/resources/model/import-existing',body:{...reuse,expectedSessionRevision:'session:1'},signal:controller.signal},
    {path:'/api/workbench/terrains',body:{q:'地区',cursor:'fixed-cursor',limit:2,expectedSessionRevision:'session:1'},signal:controller.signal},
  ]);
  assert.equal('rightsDeclared' in calls[1].body,false);assert.equal('path' in calls[1].body,false);
});

test('reuse write denial preserves readable resources while directory read denial clears the session', async () => {
  let code = 'MODEL_WRITE_FORBIDDEN',denied = false;
  const transport = new WorkbenchApi(async() => new Response(JSON.stringify({code}),{status:403}));
  transport.session('session:1');transport.onDenied = () => {denied = true;};const api = new SceneApi(transport),epoch = transport.epoch;
  await assert.rejects(api.importExistingModel({legacyModelVersionId:'legacy',expectedModelRevision:4,expectedSha256:'a'.repeat(64),
    expectedLibraryRevision:'library:7',purpose:'equipment',clientRequestId:'reuse-id'}),error => error.code==='MODEL_WRITE_FORBIDDEN');
  assert.equal(denied,false);assert.equal(transport.epoch,epoch);
  code = 'FORBIDDEN';await assert.rejects(api.terrains(),error=>error.code==='FORBIDDEN');
  assert.equal(denied,true);assert.ok(transport.epoch>epoch);
});
