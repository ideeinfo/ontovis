import {ApiError} from './api.ts';
import type {SceneApi} from './sceneApi';

export type AssistantSceneTarget={sceneId:string;sceneRevision:string;title:string};

export async function openAssistantScene(
 client:Pick<SceneApi,'open'|'version'|'imageryVersion'>, projectCode:string|undefined,
 target:AssistantSceneTarget, signal:AbortSignal,
){
 if(!projectCode)throw new ApiError(422,'PROJECT_REQUIRED');
 const scene=await client.open(target.sceneId,target.sceneRevision,signal);
 signal.throwIfAborted();
 if(scene.projectCode!==projectCode)throw new ApiError(409,'PROJECT_SCOPE_MISMATCH');
 if(scene.sceneId!==target.sceneId||scene.sceneRevision!==target.sceneRevision)throw new ApiError(409,'SCENE_CHANGED');
 const {terrain:ground,imagery:image}=scene.snapshot;
 const [terrain,imagery]=await Promise.all([
  ground?client.version(ground.terrainVersionId,signal):null,
  image?client.imageryVersion(image.imageryVersionId,signal):null,
 ]);
 signal.throwIfAborted();
 if(ground&&(terrain?.terrainVersionId!==ground.terrainVersionId||terrain.contentRevision!==ground.expectedContentRevision)
  ||image&&(imagery?.imageryVersionId!==image.imageryVersionId||imagery.contentRevision!==image.expectedContentRevision
   ||imagery.expectedReportSha256!==image.expectedReportSha256))throw new ApiError(409,'RESOURCE_CHANGED');
 return {scene,terrain,imagery};
}
