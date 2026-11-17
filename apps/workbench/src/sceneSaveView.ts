import {cloneSnapshot,SceneEditError} from './sceneState.ts';
import type {EditableSceneSnapshot,SceneView} from './sceneTypes';

function valid(view:SceneView){
 return ['eye','target'].every(key=>{const values=view[key as keyof SceneView];return Array.isArray(values)&&values.length===3&&values.every(Number.isFinite);})&&
  view.eye.reduce((sum,value,index)=>sum+(value-view.target[index])**2,0)>1e-12;
}
export function sceneViewChanged(saved:SceneView,current:SceneView|null){
 return !!current&&valid(current)&&(['eye','target'] as const).some(key=>saved[key].some((value,index)=>Math.abs(value-current[key][index])>1e-6));
}
/** Freeze the camera with the scene before any asynchronous validation or save. */
export function sceneSnapshotWithView(snapshot:EditableSceneSnapshot,current:SceneView|null){
 const view=current||snapshot.initialView;if(!valid(view))throw new SceneEditError('INVALID_COORDINATE');
 const result=cloneSnapshot(snapshot);result.initialView=structuredClone(view);return result;
}
