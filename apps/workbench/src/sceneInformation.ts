import {ApiError} from './api.ts';
import type {SceneApi} from './sceneApi';
import {engineeringReviews,reviewedForSave,rootChangesForSave} from './sceneEngineeringState.ts';
import type {EditableSceneSnapshot,SceneOpen,SceneSaveRequest} from './sceneTypes';

export interface SceneInformation {name:string;description:string}
export function sceneInformationSnapshot(snapshot:EditableSceneSnapshot,info:SceneInformation):EditableSceneSnapshot {
  const name=info.name.trim();
  if(!name||Array.from(name).length>200||Array.from(info.description).length>2000||/[\u0000-\u001f]/u.test(name)||/[\u0000-\u0009\u000b-\u001f]/u.test(info.description))throw new ApiError(422,'INVALID_REQUEST');
  const next=structuredClone(snapshot);next.displayName=name;
  if(info.description!==''||snapshot.description!==undefined)next.description=info.description;
  return next;
}

export async function prepareSceneInformationSave(client:Pick<SceneApi,'check'>,opened:SceneOpen,info:SceneInformation,requestId:string,signal?:AbortSignal):Promise<SceneSaveRequest> {
  if(!opened.capabilities.canWrite)throw new ApiError(403,'SCENE_WRITE_FORBIDDEN');
  if(opened.sceneRevision!==opened.headRevision)throw new ApiError(409,'SCENE_CHANGED');
  const snapshot=sceneInformationSnapshot(opened.snapshot,info);
  const checked=await client.check({kind:'validate',sceneId:opened.sceneId,expectedSceneRevision:opened.sceneRevision,snapshot},signal);
  if(!checked.capabilities.canWrite)throw new ApiError(403,'SCENE_WRITE_FORBIDDEN');
  return {sceneId:opened.sceneId,expectedSceneRevision:opened.sceneRevision,expectedLifecycleRevision:opened.lifecycleRevision??0,
    clientRequestId:requestId,snapshot,
    reviewedEngineering:reviewedForSave(checked.reviewedEngineering||[],engineeringReviews(opened.validation)),
    rootBindingChanges:rootChangesForSave(checked.rootBindingChanges||[],[])};
}
