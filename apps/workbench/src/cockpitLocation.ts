import type {SceneLocation,SceneLocationRequest,SceneObjectContext} from './sceneEngineeringTypes';
import type {SceneModelInstance} from './sceneTypes';
import type {SceneComponentPick} from './sceneComponentPick';
import {componentFocusKey} from './sceneComponentFocus.ts';
import {ApiError} from './api.ts';
import type {SceneApi} from './sceneApi';

export async function readCockpitLocation(client:Pick<SceneApi,'objectContext'|'locate'>,request:SceneLocationRequest,signal:AbortSignal,expectedEntityRevision?:string){
 const [context,value]=await Promise.all([client.objectContext(request.selectedObjectRef.entityUid,undefined,signal),client.locate(request,signal)]);
 signal.throwIfAborted();
 if(context.item.entityUid!==request.selectedObjectRef.entityUid||context.objectRef.entityUid!==request.selectedObjectRef.entityUid||expectedEntityRevision&&context.item.entityRevision!==expectedEntityRevision||!cockpitLocationCurrent(value,request,context))throw new ApiError(409,'ENGINEERING_CHANGED');
 return value;
}

export function cockpitLocationCurrent(value:SceneLocation,request:SceneLocationRequest,context:SceneObjectContext):boolean {
 const ref=request.selectedObjectRef,actual=value.selectedObject.objectRef;
 return value.sceneId===request.sceneId&&value.sceneRevision===request.sceneRevision&&value.contextEpoch===request.contextEpoch
  &&actual.entityUid===ref.entityUid&&actual.projectCode===ref.projectCode&&actual.ontobaseConnectionId===ref.ontobaseConnectionId
  &&value.selectedObject.entityRevision===context.item.entityRevision
  &&(value.status!=='located'||!!request.representationChoice&&value.sceneModelInstanceId===request.representationChoice.sceneModelInstanceId
   &&value.modelVersionId===request.representationChoice.modelVersionId&&value.worldBounds!==null
   &&componentFocusKey({token:1,instanceId:value.sceneModelInstanceId!,bounds:value.worldBounds,componentKeys:value.componentKeys})!==null);
}

/** Snapshot bindings already include server-validated configuration mappings. Names are never identities. */
export function cockpitPickedObject(instance:SceneModelInstance|undefined,pick:SceneComponentPick):string|null {
 if(!instance||instance.sceneModelInstanceId!==pick.sceneModelInstanceId||instance.modelVersionId!==pick.modelVersionId||!instance.rootBinding)return null;
 const root=instance.rootBinding.objectRef,matches=instance.componentBindings.filter(binding=>binding.componentKeys.includes(pick.componentKey));
 if(matches.length!==1)return null;
 const ref=matches[0].objectRef;
 return ref.projectCode===root.projectCode&&ref.ontobaseConnectionId===root.ontobaseConnectionId?ref.entityUid:null;
}

export function cockpitParentPath(context:SceneObjectContext,rootUid:string):string[] {
 if(context.item.entityUid===rootUid)return [rootUid];
 const ancestors=context.ancestors.path.map(row=>row.object.entityUid),rootIndex=ancestors.indexOf(rootUid);
 return rootIndex<0?[]:ancestors.slice(0,rootIndex+1).reverse();
}
