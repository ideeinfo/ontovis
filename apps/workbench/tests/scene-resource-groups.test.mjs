import assert from 'node:assert/strict';
import test from 'node:test';
import {sceneResourceGroups} from '../src/sceneResourceGroups.ts';
import {duplicateAt,placeModel} from '../src/sceneState.ts';

test('resource groups distinguish resources, retained geometry versions and independent instances without mutating input',()=>{
  const instances=[['one','v1'],['two','v2'],['three','other'],['four','v1']].map(([sceneModelInstanceId,modelVersionId])=>({sceneModelInstanceId,modelVersionId}));
  const refs=[{modelVersionId:'v1',modelAssetId:'asset'},{modelVersionId:'v2',modelAssetId:'asset'},{modelVersionId:'other',modelAssetId:'second'}];
  const before=structuredClone({instances,refs}),groups=sceneResourceGroups(instances,refs);
  assert.equal(groups.length,2);assert.equal(groups[0].instanceCount,3);
  assert.deepEqual(groups[0].versions.map(v=>[v.modelVersionId,v.instances.map(i=>i.sceneModelInstanceId)]),[['v1',['one','four']],['v2',['two']]]);
  assert.deepEqual({instances,refs},before);
  assert.equal(sceneResourceGroups([{sceneModelInstanceId:'legacy-a',modelVersionId:'unknown-a'},{sceneModelInstanceId:'legacy-b',modelVersionId:'unknown-b'}],[]).length,2);
});

test('repeated placement and copying produce one resource/version group with distinct instance identities and no inherited equipment binding',()=>{
  let scene={displayName:'Test',coordinateFrame:{mode:'local_plane',frameRevision:'frame',origin:[0,0,0],unit:'m',axes:'X_EAST_Y_UP_Z_SOUTH'},terrain:null,instances:[],initialView:{eye:[100,100,100],target:[0,0,0]},defaults:{background:'plain',lighting:'neutral',terrainMaterial:'solid'}};
  const model={modelVersionId:'version',modelAssetId:'asset',displayName:'Turbine',canPlace:true,canPlaceGeographic:true,calibrationState:'verified',calibration:{state:'verified'}};
  for(let i=0;i<99;i++)scene=placeModel(scene,model,[i*10,0,0],null,`instance-${i}`,100);
  scene.instances[0].rootBinding={objectRef:{entityUid:'installation-7'}};
  scene=duplicateAt(scene,'instance-0',[0,0,50],'copy',100);
  const groups=sceneResourceGroups(scene.instances,[{modelVersionId:'version',modelAssetId:'asset'}]);
  assert.equal(groups.length,1);assert.equal(groups[0].versions.length,1);assert.equal(groups[0].instanceCount,100);
  assert.equal(new Set(scene.instances.map(i=>i.sceneModelInstanceId)).size,100);
  assert.equal(scene.instances.at(-1).modelVersionId,'version');assert.equal(scene.instances.at(-1).rootBinding,null);
});

test('metadata evidence links accept only HTTPS sources and never credentials or executable schemes',async()=>{
  const {metadataSourceUrl,modelPropertyLabel}=await import('../src/modelResourceMetadata.ts');
  assert.equal(metadataSourceUrl('https://terraursa.com/wind-lab/turbine-models.html'),'https://terraursa.com/wind-lab/turbine-models.html');
  for(const value of ['javascript:alert(1)','data:text/html,test','file:///private','https://name:secret@example.com','not a URL'])assert.equal(metadataSourceUrl(value),null);
  assert.equal(modelPropertyLabel('ratedPowerKw','zh'),'额定功率');
});
