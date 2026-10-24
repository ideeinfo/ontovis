import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {commitScene,duplicateAt,moveInstance,placeModel,redoScene,sceneHistory,undoScene} from '../src/sceneState.ts';

const fixture=JSON.parse(readFileSync(new URL('./fixtures/scene-transforms-gdal.json',import.meta.url)));
const model={modelVersionId:'fixed-model',displayName:'设备A',canPlace:true,canPlaceGeographic:true,calibrationState:'verified',calibration:{state:'verified'}};
const local=()=>({displayName:'布置验证',coordinateFrame:{mode:'local_plane',frameRevision:'frame1',origin:[0,0,0],unit:'m',axes:'X_EAST_Y_UP_Z_SOUTH'},terrain:null,instances:[],initialView:{eye:[80,60,90],target:[0,15,0]},defaults:{background:'sky',lighting:'dusk',terrainMaterial:'solid'}});
const withModel=()=>placeModel(local(),model,[12,0,-8],null,'instance-A',100);
test('repeated placement shares only the fixed model version and keeps independent instance identities',()=>{
  const first=withModel(),second=placeModel(first,model,[32,0,6],null,'instance-B',100);
  assert.equal(first.instances.length,1);assert.equal(second.instances.length,2);
  assert.equal(second.instances[0].modelVersionId,second.instances[1].modelVersionId);
  const moved=moveInstance(second,'instance-B',[52,0,8]);
  assert.deepEqual(moved.instances[0].placement.position,{mode:'local',xM:12,zM:-8});
  assert.deepEqual(second.instances[1].placement.position,{mode:'local',xM:32,zM:6});
  let many=second;const unchangedModel=structuredClone(model);
  for(let index=3;index<=20;index++)many=placeModel(many,model,[index*10,0,index],null,`instance-${index}`,100);
  assert.equal(many.instances.length,20);assert.equal(new Set(many.instances.map(item=>item.sceneModelInstanceId)).size,20);
  assert.deepEqual([...new Set(many.instances.map(item=>item.modelVersionId))],['fixed-model']);
  assert.ok(many.instances.every(item=>item.rootBinding===null&&item.componentBindings.length===0));
  assert.deepEqual(model,unchangedModel);
});
test('a copy is unlocked and clears engineering identity instead of copying equipment links',()=>{
  const source=withModel();source.instances[0].positionLocked=true;
  source.instances[0].rootBinding={entityUid:'synthetic-equipment'};
  source.instances[0].componentBindings=[{entityUid:'synthetic-child'}];
  const copy=duplicateAt(source,'instance-A',[30,0,20],'instance-B',100);
  assert.equal(copy.instances[0].positionLocked,true);assert.equal(copy.instances[1].positionLocked,false);
  assert.equal(copy.instances[1].rootBinding,null);assert.deepEqual(copy.instances[1].componentBindings,[]);
  assert.equal(copy.instances[0].rootBinding.entityUid,'synthetic-equipment');
});
test('locked movement, unverified model, duplicate identity and capacity overflow are rejected',()=>{
  const source=withModel();source.instances[0].positionLocked=true;
  for(const [run,code] of [[()=>moveInstance(source,'instance-A',[0,0,0]),'INSTANCE_POSITION_LOCKED'],
    [()=>placeModel(local(),{...model,canPlace:false},[0,0,0],null,'new',100),'MODEL_CALIBRATION_REQUIRED'],
    [()=>placeModel(source,model,[0,0,0],null,'instance-A',100),'INSTANCE_ID_REUSED'],
    [()=>placeModel(source,model,[0,0,0],null,'new',1),'SCENE_LIMIT_EXCEEDED']])assert.throws(run,error=>error.code===code);
});
test('undo and redo preserve the immutable saved snapshot, and a new edit drops the redo branch',()=>{
  const original=withModel(),next=moveInstance(original,'instance-A',[44,0,-1]);
  const saved=sceneHistory(original),edited=commitScene(saved,next),undone=undoScene(edited),redone=redoScene(undone);
  assert.deepEqual(undone.present,original);assert.deepEqual(redone.present,next);assert.deepEqual(saved.present,original);
  const branched=commitScene(undone,moveInstance(original,'instance-A',[55,0,12]));assert.equal(branched.future.length,0);
  next.instances[0].displayName='caller mutation';assert.equal(edited.present.instances[0].displayName,'设备A');
});
test('invalid or mixed geographic positions fail before creating a partial local placement',()=>{
  const source=withModel();assert.throws(()=>moveInstance(source,'instance-A',[NaN,0,0]),error=>error.code==='INVALID_COORDINATE');
  assert.equal(source.instances[0].placement.position.xM,12);
});
test('geographic placement pins terrain identity and sampling rule for later server checking',()=>{
  const frame=fixture.cases[0].frame,source={...local(),coordinateFrame:frame,terrain:{terrainVersionId:'fixed-terrain',expectedContentRevision:'terrain-r1'}};
  const terrain={terrainVersionId:'fixed-terrain',contentRevision:'terrain-r1',sha256:'a'.repeat(64),report:{mesh:{placementSamplingRule:'fixed-mesh-rule'}}};
  const result=placeModel(source,model,[0,5,0],terrain,'geographic-A',100),item=result.instances[0];
  assert.equal(item.placement.position.mode,'geographic');assert.equal(item.placement.height.terrainSha256,terrain.sha256);
  assert.equal(item.placement.height.samplingRule,'fixed-mesh-rule');assert.equal(item.placement.height.offsetM,0);
  assert.throws(()=>placeModel(source,model,[0,5,0],{...terrain,contentRevision:'other'},'new',100),error=>error.code==='RESOURCE_CHANGED');
});

test('legacy display preserves local coordinates and a fresh identity without inventing calibration',()=>{
  const legacy={...model,calibrationState:'legacy_display',canPlaceGeographic:false,
    calibration:{state:'legacy_display',modelToCalibrated:[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]}};
  const placed=placeModel(local(),legacy,[15,0,-4],null,'legacy-local',100),item=placed.instances[0];
  assert.deepEqual(item.placement.position,{mode:'local',xM:15,zM:-4});
  assert.equal(item.placement.height.relativeHeightM,0);assert.equal(item.placement.headingDeg,0);
  assert.equal(item.rootBinding,null);assert.deepEqual(item.componentBindings,[]);
  assert.equal(legacy.calibration.state,'legacy_display');assert.equal(legacy.calibration.forward,undefined);
});
test('geographic placement rejects legacy display before adding an instance or requesting terrain data',()=>{
  const source={...local(),coordinateFrame:fixture.cases[0].frame,terrain:{terrainVersionId:'fixed-terrain',expectedContentRevision:'terrain-r1'}};
  const before=structuredClone(source),legacy={...model,calibrationState:'legacy_display',canPlaceGeographic:false,calibration:{state:'legacy_display'}};
  assert.throws(()=>placeModel(source,legacy,[0,5,0],null,'legacy-geographic',100),error=>error.code==='MODEL_GEOGRAPHIC_CALIBRATION_REQUIRED');
  assert.deepEqual(source,before);
});
