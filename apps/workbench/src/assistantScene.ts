import {ApiError} from './api.ts';
import type {ProjectRef} from './projectTypes';
import type {SceneApi} from './sceneApi';
import type {SceneModelInstance,SceneOpen} from './sceneTypes';

type FixedInstanceTarget={instanceId:string;modelVersionId:string;equipmentUid:string};
export type AssistantSceneTarget={sceneId:string;sceneRevision:string;title:string;instance?:FixedInstanceTarget;modelVersionId?:string};
type FixedSceneTarget=Pick<AssistantSceneTarget,'sceneId'|'sceneRevision'>;
export type AssistantSceneEditTarget=FixedSceneTarget&{instanceId?:string;modelVersionId?:string};

export function assistantInstanceOptions(instances:SceneModelInstance[],query='') {
 const normalize=(value:string)=>value.normalize('NFKC').toLowerCase();
 const words=normalize(query).trim().split(/\s+/).filter(Boolean);
 const counts=new Map<string,number>();
 const prefixes=new Map<string,number>();
 for(const instance of instances){
  const name=normalize(instance.displayName),prefix=name+'\0'+instance.sceneModelInstanceId.slice(0,8);
  counts.set(name,(counts.get(name)??0)+1);
  prefixes.set(prefix,(prefixes.get(prefix)??0)+1);
 }
 return instances.flatMap(instance=>{
  const name=normalize(instance.displayName),id=instance.sceneModelInstanceId;
  if(!words.every(word=>name.includes(word)||id.toLowerCase().includes(word)))return [];
  const prefix=id.slice(0,8),idLabel=(prefixes.get(name+'\0'+prefix)??0)>1?id:prefix;
  const display=(counts.get(name)??0)>1?instance.displayName+' · '+idLabel:instance.displayName;
  return [{instance,display}];
 });
}

function matchesSceneRevision(scene:SceneOpen,target:FixedSceneTarget) {
 return scene.sceneId===target.sceneId&&scene.sceneRevision===target.sceneRevision;
}

export function verifyAssistantScene(scene:SceneOpen,projectCode:string|undefined,target:FixedSceneTarget) {
 if(scene.projectCode!==projectCode)throw new ApiError(409,'PROJECT_SCOPE_MISMATCH');
 if(!matchesSceneRevision(scene,target))throw new ApiError(409,'SCENE_CHANGED');
}

function editInstance(scene:SceneOpen,target:AssistantSceneEditTarget) {
 if(!target.instanceId||!target.modelVersionId||!scene.resourceRefs.some(ref=>ref.modelVersionId===target.modelVersionId))return;
 return scene.snapshot.instances.find(item=>item.sceneModelInstanceId===target.instanceId&&item.modelVersionId===target.modelVersionId);
}

export function verifyAssistantSceneEdit(scene:SceneOpen,projectCode:string|undefined,target:AssistantSceneEditTarget) {
 verifyAssistantScene(scene,projectCode,target);
 if(!target.instanceId&&!target.modelVersionId)return;
 const instance=editInstance(scene,target);
 if(!instance)throw new ApiError(409,'SCENE_INSTANCE_CHANGED');
 return instance;
}

export function canEditAssistantScene(scene:SceneOpen,projectCode:string|undefined,
 target:AssistantSceneEditTarget&Pick<AssistantSceneTarget,'instance'>) {
 return !target.instance&&scene.capabilities.canWrite&&scene.projectCode===projectCode&&matchesSceneRevision(scene,target)
  &&scene.sceneRevision===scene.headRevision
  &&(!(target.instanceId||target.modelVersionId)||!!editInstance(scene,target));
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
