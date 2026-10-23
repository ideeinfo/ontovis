import assert from 'node:assert/strict';
import test from 'node:test';
import {ApiError, WorkbenchApi} from '../src/api.ts';
import {SceneApi} from '../src/sceneApi.ts';
import {calibrationInput, modelMetadata, privateDenial, ResourceFormError, ResourceRequestGate, ResourceRequestId,
  resourceFailure, resourceUploadBytes, terrainMetadata, terrainPending, TERRAIN_POLL_MS, validateResourceFile, writeDenial, placementModelVersion} from '../src/resourceForms.ts';
import {resourceText} from '../src/resourceMessages.ts';

const modelFields={name:'设备模型',purpose:'equipment',source:'项目提供的合成素材',rights:true};
const terrainFields={name:'地形',source:'公开源合成测试',license:'测试用途',rights:true,datum:'EGM2008',relativeReference:'',crop:false,bounds:['','','','']};
const json=value=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json'}});
const delayed=()=>{let resolve;const promise=new Promise(done=>{resolve=done;});return {promise,resolve};};

const versionSummary=(id,time,state='verified')=>({modelVersionId:id,createdAt:time,calibrationState:state,
  canPlace:state!=='unverified',canPlaceGeographic:state==='verified'});
test('model selection defaults to the newest calibrated placement version without mutating the catalog',()=>{
  const versions=[versionSummary('older','2026-10-21'),versionSummary('new-upload','2026-10-23','unverified'),
    versionSummary('calibrated','2026-10-22'),versionSummary('legacy','2026-10-24','legacy_display')];
  const asset={versions},before=structuredClone(asset);
  for(const geographic of [true,false])assert.equal(placementModelVersion(asset,geographic).modelVersionId,'calibrated');
  assert.deepEqual(asset,before);
});
test('an explicitly selected fixed version stays selected even when newer versions appear',()=>{
  const asset={versions:[versionSummary('latest','2026-10-23'),versionSummary('chosen','2026-10-21'),versionSummary('local-only','2026-10-22','legacy_display')]};
  assert.equal(placementModelVersion(asset,true,'chosen').modelVersionId,'chosen');
  assert.equal(placementModelVersion(asset,true,'local-only').canPlaceGeographic,false);
  assert.equal(placementModelVersion(asset,true,'removed').modelVersionId,'latest');
});
test('a model without a usable calibrated version exposes its real state for calibration',()=>{
  const asset={versions:[versionSummary('unverified','2026-10-23','unverified'),versionSummary('legacy','2026-10-22','legacy_display')]};
  assert.equal(placementModelVersion(asset,false).modelVersionId,'legacy');
  const geographic=placementModelVersion(asset,true);
  assert.equal(geographic.modelVersionId,'unverified');assert.equal(geographic.canPlace,false);
  assert.equal(placementModelVersion({versions:[]},true),null);
});

test('GLB and GeoTIFF file validation rejects wrong formats, truncation and hard or server limits before upload',()=>{
  validateResourceFile({name:'asset.GLB',size:24},'model');
  validateResourceFile({name:'height.TIFF',size:8},'terrain');
  for(const file of [{name:'model.glb',size:23},{name:'model.gltf',size:200},{name:'model.glb',size:20*1024*1024+1}]){
    assert.throws(()=>validateResourceFile(file,'model'),error=>error instanceof ResourceFormError&&error.key==='modelFileInvalid');
  }
  for(const file of [{name:'terrain.tif',size:7},{name:'terrain.png',size:200}]){
    assert.throws(()=>validateResourceFile(file,'terrain'),error=>error.key==='terrainFileInvalid');
  }
  assert.throws(()=>validateResourceFile({name:'terrain.tif',size:256*1024*1024+1},'terrain'),error=>error.key==='terrainFileTooLarge');
  assert.throws(()=>validateResourceFile({name:'small.glb',size:1025},'model',1024));
  assert.throws(()=>validateResourceFile({name:'bad.glb',size:NaN},'model'));
});

test('terrain selection uses the deployment byte limit at its exact boundary and reports it in both languages',()=>{
  const maximum=100_000_000,label=resourceUploadBytes(maximum);
  assert.equal(label,'100,000,000 B (95.37 MiB)');
  validateResourceFile({name:'terrain.tif',size:maximum},'terrain',maximum);
  assert.throws(()=>validateResourceFile({name:'terrain.tif',size:maximum+1},'terrain',maximum),error=>{
    assert.equal(error.key,'terrainFileTooLarge');
    assert.equal(resourceFailure(error,'zh'),`GeoTIFF 文件不能超过${label}。`);
    assert.equal(resourceFailure(error,'en'),`The GeoTIFF must not exceed ${label}.`);
    return true;
  });
  for(const locale of ['zh','en']){
    const text=resourceText(locale,'tiffLimit',{maximum:label});
    assert.ok(text.includes(label));assert.ok(!text.includes('256'));
  }
  assert.throws(()=>validateResourceFile({name:'terrain.tif',size:256*1024*1024+1},'terrain',Number.MAX_SAFE_INTEGER),error=>error.key==='terrainFileTooLarge');
});

test('append model version keeps existing resource name and purpose and does not invent engineering bindings',()=>{
  const asset={modelAssetId:'asset-fixed',displayName:'原设备',purpose:'environment',assetRevision:'asset:1',versions:[]};
  const metadata=modelMetadata({...modelFields,name:'不能覆写',purpose:'equipment'},'library:old','request:1',asset);
  assert.deepEqual(metadata,{expectedLibraryRevision:'library:old',clientRequestId:'request:1',displayName:'原设备',purpose:'environment',sourceNote:modelFields.source,rightsDeclared:true,modelAssetId:'asset-fixed'});
  assert.equal(metadata.bindings,undefined);assert.equal(metadata.modelRevision,undefined);assert.equal(asset.displayName,'原设备');
});

test('new model requires source and rights declaration and trims user-entered business text',()=>{
  assert.deepEqual(modelMetadata({...modelFields,name:' 名称 ',source:' 来源 '},'library:1','request:2'),{
    expectedLibraryRevision:'library:1',clientRequestId:'request:2',displayName:'名称',purpose:'equipment',sourceNote:'来源',rightsDeclared:true});
  for(const patch of [{rights:false},{name:' '},{source:''}])assert.throws(()=>modelMetadata({...modelFields,...patch},'r','id'),error=>error.key==='sourceRequired');
});

test('calibration accepts only finite metre Y-up vectors and cannot submit a client-computed matrix or verifier',()=>{
  const value=calibrationInput(['1.25','-4','0'],['0','0','-2']);
  assert.deepEqual(value,{unit:'m',axes:'Y_UP_RIGHT_HANDED',basePoint:[1.25,-4,0],forward:[0,0,-2]});
  assert.equal(value.modelToCalibrated,undefined);assert.equal(value.verifiedBy,undefined);
  for(const bad of [['','0','0'],['Infinity','0','0'],['NaN','0','0'],['1000001','0','0'],['0','0']])assert.throws(()=>calibrationInput(bad,['0','0','-1']),error=>error.key==='finiteCoordinates');
  for(const bad of [['0','1','-1'],['0','0','0']])assert.throws(()=>calibrationInput(['0','0','0'],bad),error=>error.key==='invalidForward');
});

test('terrain metadata has no default horizontal CRS or vertical datum and sends only declarations the service accepts',()=>{
  const value=terrainMetadata(terrainFields,'terrain-request');
  assert.deepEqual(value,{clientRequestId:'terrain-request',displayName:'地形',sourceNote:'公开源合成测试',licenseNote:'测试用途',rightsDeclared:true,heightUnit:'m',verticalDatum:'EGM2008'});
  assert.equal(value.horizontalCrs,undefined);assert.equal(value.aoi,undefined);assert.equal(value.relativeReferenceId,undefined);
  for(const patch of [{datum:''},{license:' '},{source:' '},{rights:false}])assert.throws(()=>terrainMetadata({...terrainFields,...patch},'r'),error=>error.key==='terrainRequired');
});

test('unknown relative heights require an explicit reference while AOI preserves WGS84 west south east north order',()=>{
  assert.throws(()=>terrainMetadata({...terrainFields,datum:'UNKNOWN_RELATIVE'},'r'),error=>error.key==='relativeRequired');
  const value=terrainMetadata({...terrainFields,datum:'UNKNOWN_RELATIVE',relativeReference:' 现场基准A ',crop:true,bounds:['113.1','33.4','113.2','33.5']},'r');
  assert.equal(value.relativeReferenceId,'现场基准A');assert.deepEqual(value.aoi,[113.1,33.4,113.2,33.5]);
  for(const bounds of [['','0','1','1'],['1','0','0','1'],['0','1','1','0'],['-181','0','1','1'],['0','-81','1','1'],['0','0','1','85'],['0','0','Infinity','1']])assert.throws(()=>terrainMetadata({...terrainFields,crop:true,bounds},'r'),error=>error.key==='invalidAoi');
});

test('unchanged retries keep the UUID while changed input, file, revision or an explicit new operation gets a new UUID',()=>{
  const identity=new ResourceRequestId(),payload={expectedLibraryRevision:'old',name:'test'},first=identity.forPayload(payload,'file-a');
  assert.match(first,/^[0-9a-f-]{36}$/);assert.equal(identity.forPayload({...payload},'file-a'),first);
  const next=identity.forPayload({...payload,expectedLibraryRevision:'new'},'file-a');assert.notEqual(next,first);
  const changedFile=identity.forPayload({...payload,expectedLibraryRevision:'new'},'file-b');assert.notEqual(changedFile,next);
  identity.reset();assert.notEqual(identity.forPayload({...payload,expectedLibraryRevision:'new'},'file-b'),changedFile);
});

test('write-only denials remain readable while real project or session denials clear private state',()=>{
  for(const code of ['MODEL_WRITE_FORBIDDEN','SCENE_WRITE_FORBIDDEN']){const error=new ApiError(403,code);assert.equal(writeDenial(error),true);assert.equal(privateDenial(error),false);}
  for(const error of [new ApiError(401,'LOGIN_REQUIRED'),new ApiError(403,'PROJECT_FORBIDDEN')]){assert.equal(writeDenial(error),false);assert.equal(privateDenial(error),true);}
  assert.equal(privateDenial(new ApiError(409,'LIBRARY_CHANGED')),false);
});

test('only queued and processing jobs continue polling; terminal states never imply fabricated success',()=>{
  assert.equal(TERRAIN_POLL_MS,2000);
  for(const state of ['queued','processing'])assert.equal(terrainPending(state),true);
  for(const state of ['ready','failed','cancelled',undefined,'unknown'])assert.equal(terrainPending(state),false);
});

test('a newer selection aborts and suppresses a late old detail even when transport ignores AbortSignal',async()=>{
  const old=delayed(),current=delayed(),seen=[],calls=[];
  const transport=new WorkbenchApi(async(path,options)=>{calls.push({path,options});const body=JSON.parse(options.body);return (body.modelVersionId==='old'?old:current).promise;});
  transport.session('s:1');const api=new SceneApi(transport),gate=new ResourceRequestGate();
  const read=async id=>{const request=gate.start();try{const value=await api.model('asset',id,request.signal);if(request.isCurrent())seen.push(value.modelVersionId);}catch(error){assert.equal(error.name,'AbortError');}};
  const first=read('old'),second=read('new');assert.equal(calls[0].options.signal.aborted,true);
  current.resolve(json({sessionRevision:'s:1',modelVersionId:'new'}));await second;
  old.resolve(json({sessionRevision:'s:1',modelVersionId:'old'}));await first;
  assert.deepEqual(seen,['new']);
});

test('unmount cancels an in-flight terrain status read without issuing an implicit business cancellation',async()=>{
  const reply=delayed(),calls=[];const transport=new WorkbenchApi(async(path,options)=>{calls.push({path,options});return reply.promise;});
  transport.session('s:1');const api=new SceneApi(transport),gate=new ResourceRequestGate(),request=gate.start();
  const read=api.job('pending-job',request.signal);gate.cancel();reply.resolve(json({sessionRevision:'s:1',state:'ready'}));
  await assert.rejects(read,error=>error.name==='AbortError');assert.equal(request.isCurrent(),false);
  assert.deepEqual(calls.map(item=>item.path),['/api/workbench/terrains/job']);
});

test('library conflict is surfaced once and leaves the form and original UUID available for an unchanged retry',async()=>{
  const calls=[],fields={...modelFields};const ids=new ResourceRequestId(),draft=modelMetadata(fields,'library:old','');
  const requestId=ids.forPayload(draft,'same.glb'),metadata={...draft,clientRequestId:requestId};
  const transport=new WorkbenchApi(async(path,options)=>{calls.push({path,options});return new Response('{"code":"LIBRARY_CHANGED"}',{status:409});});
  transport.session('s:1');const api=new SceneApi(transport);
  await assert.rejects(api.uploadModel(new Blob(['x'.repeat(32)]),metadata),error=>error.status===409&&error.code==='LIBRARY_CHANGED');
  assert.equal(calls.length,1);assert.deepEqual(fields,modelFields);assert.equal(ids.forPayload(draft,'same.glb'),requestId);
  assert.notEqual(ids.forPayload({...draft,expectedLibraryRevision:'library:new'},'same.glb'),requestId);
});

test('local validation and declarations use the selected language without exposing raw protocol error codes',()=>{
  assert.equal(resourceFailure(new ResourceFormError('relativeRequired'),'zh'),'相对高程需要填写可辨识的参考名称。');
  assert.match(resourceFailure(new ApiError(400,'INVALID_CALIBRATION'),'en'),/horizontal/);
  assert.match(resourceFailure(new ApiError(413,'INVALID_REQUEST'),'en'),/too long/);
  assert.equal(resourceText('en','useCounts',{current:2,retained:1,references:3}),'Current 2 · Historical instances 1 · Historical references 3');
  assert.notEqual(resourceText('zh','calibrationNote'),resourceText('en','calibrationNote'));
});
