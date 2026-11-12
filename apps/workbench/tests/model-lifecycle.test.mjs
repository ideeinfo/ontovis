import assert from 'node:assert/strict';
import test from 'node:test';
import {modelPlacementIssue} from '../src/resourceForms.ts';
import {SceneApi} from '../src/sceneApi.ts';

test('deleted calibrated models cannot be placed and restoration preserves the calibration',()=>{
 const model={calibrationState:'verified',calibration:{state:'verified'},canPlace:true,canPlaceGeographic:true,assetState:'deleted'};
 assert.equal(modelPlacementIssue(model,false),'MODEL_DELETED');assert.equal(modelPlacementIssue(model,true),'MODEL_DELETED');
 assert.equal(modelPlacementIssue({...model,assetState:'active'},true),null);
});
test('lifecycle requests keep the fixed action path and conditional body through the session transport',async()=>{
 const calls=[];const client=new SceneApi({request:async(...args)=>{calls.push(args);return {assetState:'deleted'};}});
 const body={modelAssetId:'asset',modelVersionId:'version',expectedAssetRevision:'asset:1',expectedLifecycleRevision:0,clientRequestId:'request'};
 for(const action of ['delete','restore'])await client.modelLifecycle(action,body);
 assert.deepEqual(calls.map(c=>c.slice(0,2)),[['/api/workbench/resources/model/delete',body],['/api/workbench/resources/model/restore',body]]);
});
