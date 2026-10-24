import assert from 'node:assert/strict';
import test from 'node:test';
import {createHash} from 'node:crypto';
import {SceneApi} from '../src/sceneApi.ts';
import {WorkbenchApi} from '../src/api.ts';

const version={modelVersionId:'model-fixed-v1',contentRevision:'content:one',sha256:'a'.repeat(64)};
const json=value=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json'}});

test('thumbnail status and generation preserve exact model identity and idempotency conditions',async()=>{
 const calls=[],transport=new WorkbenchApi(async(path,options)=>{calls.push({path,body:JSON.parse(options.body)});return json({thumbnail:{state:'queued'},sessionRevision:'session:one'});});
 transport.session('session:one');const api=new SceneApi(transport);
 await api.modelThumbnail(version);await api.ensureModelThumbnail(version,'thumbnail:old','request:one');
 assert.equal(calls[0].path,'/api/workbench/resources/model/thumbnail');
 assert.equal(calls[1].path,'/api/workbench/resources/model/thumbnail/ensure');
 assert.deepEqual(calls[0].body,{expectedSessionRevision:'session:one',modelVersionId:version.modelVersionId,expectedContentRevision:version.contentRevision,expectedSha256:version.sha256});
 assert.deepEqual(calls[1].body,{...calls[0].body,expectedThumbnailRevision:'thumbnail:old',clientRequestId:'request:one'});
});

test('thumbnail image is a protected bounded binary read tied to source and thumbnail revisions',async()=>{
 const png=new Uint8Array([137,80,78,71,13,10,26,10]),sha=createHash('sha256').update(png).digest('hex');let sent;
 const transport=new WorkbenchApi(async(path,options)=>{sent={path,body:JSON.parse(options.body),options};return new Response(png,{headers:{'Content-Type':'image/png','X-Session-Revision':'session:one','X-Content-SHA256':sha}});});
 transport.session('session:one');const api=new SceneApi(transport),thumb={state:'ready',thumbnailRevision:'thumbnail:one',rendererVersion:'model-thumbnail-v1',imageSha256:sha};
 const image=await api.modelThumbnailContent(version,thumb);assert.equal(image.type,'image/png');
 assert.equal(sent.path,'/api/workbench/resources/model/thumbnail/content');
 assert.equal(sent.body.expectedSha256,version.sha256);assert.equal(sent.body.expectedImageSha256,sha);assert.equal(sent.body.expectedThumbnailRevision,thumb.thumbnailRevision);
 assert.equal(sent.options.cache,'no-store');assert.equal(sent.options.credentials,'same-origin');
});

test('losing permission to generate a thumbnail preserves the valid project read session',async()=>{
 const transport=new WorkbenchApi(async()=>new Response('{"code":"MODEL_WRITE_FORBIDDEN"}',{status:403}));transport.session('session:one');
 let denied=0;transport.onDenied=()=>denied++;const epoch=transport.epoch;
 await assert.rejects(new SceneApi(transport).ensureModelThumbnail(version,null,'request:one'),error=>error.code==='MODEL_WRITE_FORBIDDEN');
 assert.equal(denied,0);assert.equal(transport.epoch,epoch);
});
