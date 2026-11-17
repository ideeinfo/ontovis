import {fromDisplay} from './sceneTransforms.ts';
import {modelPlacementIssue} from './resourceForms.ts';
import type {ProjectModelVersion, TerrainVersion} from './resourceTypes';
import type {EditableSceneSnapshot, LocalSceneSnapshot, LocalSceneModelInstance, SceneModelInstance, Vector3} from './sceneTypes';

export interface SceneHistory {present: EditableSceneSnapshot; past: EditableSceneSnapshot[]; future: EditableSceneSnapshot[]}
export class SceneEditError extends Error {code: string; constructor(code: string) {super(code);this.code=code;}}
export const cloneSnapshot = (value: EditableSceneSnapshot): EditableSceneSnapshot => structuredClone(value);
export const isLocalScene = (value:EditableSceneSnapshot):value is LocalSceneSnapshot => value.coordinateFrame.mode==='local_plane';
export const isLocalInstance = (value:SceneModelInstance):value is LocalSceneModelInstance => value.placement.position.mode==='local';
export function hasSceneChanges(saved:EditableSceneSnapshot|null,draft:EditableSceneSnapshot|null,extraChanges=false):boolean {
  return !!saved&&!!draft&&(extraChanges||JSON.stringify(saved)!==JSON.stringify(draft));
}
export function sceneHistory(snapshot: EditableSceneSnapshot): SceneHistory {return {present:cloneSnapshot(snapshot),past:[],future:[]};}
export function commitScene(history: SceneHistory, next: EditableSceneSnapshot): SceneHistory {
  if (JSON.stringify(history.present)===JSON.stringify(next)) return history;
  return {present:cloneSnapshot(next),past:[...history.past.slice(-29),cloneSnapshot(history.present)],future:[]};
}
export function undoScene(history: SceneHistory): SceneHistory {
  const prior=history.past.at(-1);return prior ? {present:cloneSnapshot(prior),past:history.past.slice(0,-1),future:[cloneSnapshot(history.present),...history.future]} : history;
}
export function redoScene(history: SceneHistory): SceneHistory {
  const next=history.future[0];return next ? {present:cloneSnapshot(next),past:[...history.past,cloneSnapshot(history.present)],future:history.future.slice(1)} : history;
}
export function updateInstance(snapshot:EditableSceneSnapshot, instance:SceneModelInstance):EditableSceneSnapshot {
  const next=cloneSnapshot(snapshot),index=next.instances.findIndex(item=>item.sceneModelInstanceId===instance.sceneModelInstanceId);
  if(index<0 || (next.coordinateFrame.mode==='local_plane')!==(instance.placement.position.mode==='local')) throw new SceneEditError('INVALID_REQUEST');
  next.instances[index]=structuredClone(instance);return next;
}
export function moveInstance(snapshot:EditableSceneSnapshot,id:string,point:Vector3):EditableSceneSnapshot {
  const item=snapshot.instances.find(value=>value.sceneModelInstanceId===id);
  if(!item)throw new SceneEditError('INVALID_REQUEST');
  if(item.positionLocked)throw new SceneEditError('INSTANCE_POSITION_LOCKED');
  const coordinate=fromDisplay(snapshot.coordinateFrame,point),next=structuredClone(item);
  if(next.placement.position.mode==='local' && coordinate.position.mode==='local') next.placement.position=coordinate.position;
  else if(next.placement.position.mode==='geographic' && coordinate.position.mode==='geographic') next.placement.position=coordinate.position;
  else throw new SceneEditError('INVALID_REQUEST');
  return updateInstance(snapshot,next);
}
export function placeModel(snapshot:EditableSceneSnapshot,model:ProjectModelVersion,point:Vector3,terrain:TerrainVersion|null,id:string,maxInstances:number):EditableSceneSnapshot {
  const issue=modelPlacementIssue(model,!isLocalScene(snapshot));
  if(issue)throw new SceneEditError(issue);
  if(snapshot.instances.length>=maxInstances)throw new SceneEditError('SCENE_LIMIT_EXCEEDED');
  if(snapshot.instances.some(item=>item.sceneModelInstanceId===id))throw new SceneEditError('INSTANCE_ID_REUSED');
  const next=cloneSnapshot(snapshot),coordinate=fromDisplay(next.coordinateFrame,point);
  const common={sceneModelInstanceId:id,displayName:model.displayName,modelVersionId:model.modelVersionId,
    visible:true,positionLocked:false,rootBinding:null,componentBindings:[] as never[]};
  if(isLocalScene(next) && coordinate.position.mode==='local') {
    next.instances.push({...common,placement:{position:coordinate.position,height:{mode:'local_relative',relativeHeightM:0},headingDeg:0}});
  } else if(!isLocalScene(next) && coordinate.position.mode==='geographic') {
    if(!terrain || terrain.terrainVersionId!==next.terrain.terrainVersionId || terrain.contentRevision!==next.terrain.expectedContentRevision)throw new SceneEditError('RESOURCE_CHANGED');
    next.instances.push({...common,placement:{position:coordinate.position,height:{mode:'terrain_ground',terrainVersionId:terrain.terrainVersionId,
      terrainSha256:terrain.sha256,sampleLongitude:coordinate.position.longitude,sampleLatitude:coordinate.position.latitude,
      sampledHeightM:coordinate.heightM,offsetM:0,verticalDatum:next.coordinateFrame.verticalDatum,
      samplingRule:terrain.report.mesh.placementSamplingRule},headingDeg:0}});
  } else throw new SceneEditError('INVALID_REQUEST');
  return next;
}
export function duplicateAt(snapshot:EditableSceneSnapshot,sourceId:string,point:Vector3,id:string,maxInstances:number):EditableSceneSnapshot {
  if(snapshot.instances.length>=maxInstances)throw new SceneEditError('SCENE_LIMIT_EXCEEDED');
  const source=snapshot.instances.find(item=>item.sceneModelInstanceId===sourceId);
  if(!source || snapshot.instances.some(item=>item.sceneModelInstanceId===id))throw new SceneEditError('INVALID_REQUEST');
  const next=cloneSnapshot(snapshot),copy={...structuredClone(source),sceneModelInstanceId:id,visible:true,positionLocked:false,
    rootBinding:null,componentBindings:[] as never[]};
  if(isLocalScene(next) && isLocalInstance(copy))next.instances.push(copy);
  else if(!isLocalScene(next) && !isLocalInstance(copy))next.instances.push(copy);
  else throw new SceneEditError('INVALID_REQUEST');
  return moveInstance(next,id,point);
}
