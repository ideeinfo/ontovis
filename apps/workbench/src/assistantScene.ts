import {ApiError} from './api.ts';
import type {ProjectRef} from './projectTypes';
import type {SceneApi} from './sceneApi';
import type {SceneOpen} from './sceneTypes';

type FixedInstanceTarget={instanceId:string;modelVersionId:string;equipmentUid:string};
export type AssistantSceneTarget={sceneId:string;sceneRevision:string;title:string;instance?:FixedInstanceTarget;modelVersionId?:string};
type FixedSceneTarget=Pick<AssistantSceneTarget,'sceneId'|'sceneRevision'>;

function matchesSceneRevision(scene:SceneOpen,target:FixedSceneTarget) {
 return scene.sceneId===target.sceneId&&scene.sceneRevision===target.sceneRevision;
}

export function verifyAssistantScene(scene:SceneOpen,projectCode:string|undefined,target:FixedSceneTarget) {
 if(scene.projectCode!==projectCode)throw new ApiError(409,'PROJECT_SCOPE_MISMATCH');
 if(!matchesSceneRevision(scene,target))throw new ApiError(409,'SCENE_CHANGED');
}

export function canEditAssistantScene(scene:SceneOpen,projectCode:string|undefined,
 target:FixedSceneTarget&Pick<AssistantSceneTarget,'instance'|'modelVersionId'>) {
 return !target.instance&&!target.modelVersionId&&scene.capabilities.canWrite&&scene.projectCode===projectCode&&matchesSceneRevision(scene,target)
  &&scene.sceneRevision===scene.headRevision;
}

function verifyFixedInstance(scene:SceneOpen,project:ProjectRef,target:FixedInstanceTarget) {
 const instances=scene.snapshot.instances.filter(item=>item.sceneModelInstanceId===target.instanceId);
 const instance=instances[0],ref=instance?.rootBinding?.objectRef;
 if(instances.length!==1||instance.modelVersionId!==target.modelVersionId
  ||ref?.entityUid!==target.equipmentUid||ref.projectCode!==project.projectCode
  ||ref.ontobaseConnectionId!==project.ontobaseConnectionId
  ||!scene.resourceRefs.some(model=>model.modelVersionId===target.modelVersionId)){
  throw new ApiError(409,'SCENE_INSTANCE_CHANGED');
 }
 return instance;
}

function verifyModelInstances(scene:SceneOpen,modelVersionId:string) {
 const instances=scene.snapshot.instances.filter(item=>item.modelVersionId===modelVersionId);
 if(!instances.length||!scene.resourceRefs.some(model=>model.modelVersionId===modelVersionId)){
  throw new ApiError(409,'SCENE_INSTANCE_CHANGED');
 }
 return instances;
}

export async function openAssistantScene(
 client:Pick<SceneApi,'open'|'version'|'imageryVersion'>, project:ProjectRef|null,
 target:AssistantSceneTarget, signal:AbortSignal,
){
 if(!project)throw new ApiError(422,'PROJECT_REQUIRED');
 const scene=await client.open(target.sceneId,target.sceneRevision,signal);
 signal.throwIfAborted();
 verifyAssistantScene(scene,project.projectCode,target);
 const instance=target.instance?verifyFixedInstance(scene,project,target.instance):null;
 const modelInstances=target.modelVersionId?verifyModelInstances(scene,target.modelVersionId):[];
 const {terrain:ground,imagery:image}=scene.snapshot;
 const [terrain,imagery]=await Promise.all([
  ground?client.version(ground.terrainVersionId,signal):null,
  image?client.imageryVersion(image.imageryVersionId,signal):null,
 ]);
 signal.throwIfAborted();
 if(ground&&(terrain?.terrainVersionId!==ground.terrainVersionId||terrain.contentRevision!==ground.expectedContentRevision)
  ||image&&(imagery?.imageryVersionId!==image.imageryVersionId||imagery.contentRevision!==image.expectedContentRevision
   ||imagery.expectedReportSha256!==image.expectedReportSha256))throw new ApiError(409,'RESOURCE_CHANGED');
 return {scene,instance,modelInstances,terrain,imagery};
}
