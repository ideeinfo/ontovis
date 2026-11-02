import type {SceneLocation,SceneLocationRequest,SceneObjectContext} from './sceneEngineeringTypes';
import type {SceneModelInstance,SceneOpen} from './sceneTypes';
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
 const representation=value.representation,choice=request.representationChoice;
 const representationCurrent=!representation||!!request.preferDetailed&&!!choice
  &&representation.sourceModelVersionId===choice.modelVersionId
  &&representation.instance.sceneModelInstanceId===choice.sceneModelInstanceId
  &&representation.instance.modelVersionId===value.modelVersionId
  &&representation.modelRef.modelVersionId===value.modelVersionId
  &&(['modelAssetId','modelVersionId','contentRevision','sha256'] as const).every(key=>representation.model[key]===representation.modelRef[key])
  &&(value.modelVersionId===choice.modelVersionId||representation.model.representationType==='detailed'&&representation.model.calibrationState==='verified')
  &&representation.model.state==='ready'&&representation.model.canPlace
  &&!!representation.instance.rootBinding
  &&[representation.instance.rootBinding,...representation.instance.componentBindings].every(binding=>binding.objectRef.projectCode===ref.projectCode&&binding.objectRef.ontobaseConnectionId===ref.ontobaseConnectionId);
 return value.sceneId===request.sceneId&&value.sceneRevision===request.sceneRevision&&value.contextEpoch===request.contextEpoch
  &&actual.entityUid===ref.entityUid&&actual.projectCode===ref.projectCode&&actual.ontobaseConnectionId===ref.ontobaseConnectionId
  &&value.selectedObject.entityRevision===context.item.entityRevision
  &&representationCurrent
  &&(value.status!=='located'||!!choice&&value.sceneModelInstanceId===choice.sceneModelInstanceId
   &&(value.modelVersionId===choice.modelVersionId||!!representation)&&value.worldBounds!==null
   &&componentFocusKey({token:1,instanceId:value.sceneModelInstanceId!,bounds:value.worldBounds,componentKeys:value.componentKeys})!==null);
}

/** A read projection replaces one representation; scene identity, pose and saved data remain intact. */
export function cockpitInspectionScene(opened:SceneOpen|null,instance:SceneModelInstance|undefined,representation:SceneLocation['representation']|null):SceneOpen|null {
 if(!opened||!instance||!representation)return opened;
 const {instance:detail,modelRef,sourceModelVersionId}=representation;
 if(instance.sceneModelInstanceId!==detail.sceneModelInstanceId||instance.modelVersionId!==sourceModelVersionId
  ||!instance.rootBinding||!detail.rootBinding||(['entityUid','projectCode','ontobaseConnectionId'] as const).some(key=>instance.rootBinding!.objectRef[key]!==detail.rootBinding!.objectRef[key]))throw new ApiError(409,'ENGINEERING_CHANGED');
 const existing=opened.resourceRefs.find(ref=>ref.modelVersionId===modelRef.modelVersionId);
 if(existing&&(['modelAssetId','contentRevision','sha256'] as const).some(key=>existing[key]!==modelRef[key]))throw new ApiError(409,'RESOURCE_CHANGED');
 const snapshot=structuredClone(opened.snapshot);
 for(const item of snapshot.instances)if(item.sceneModelInstanceId===instance.sceneModelInstanceId){
  item.modelVersionId=modelRef.modelVersionId;item.componentBindings=structuredClone(detail.componentBindings);
 }
 return {...opened,snapshot,resourceRefs:existing?opened.resourceRefs:[...opened.resourceRefs,modelRef]};
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
