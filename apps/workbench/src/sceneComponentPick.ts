import type {Intersection,Object3D} from 'three';
import type {EngineeringRef,SceneComponentBinding,SceneObjectContext} from './sceneEngineeringTypes';
import type {ProjectModelComponent} from './resourceTypes';

export interface SceneComponentPick {sceneModelInstanceId:string;modelVersionId:string;componentKey:string}
export interface SceneComponentPickRequest extends SceneComponentPick {
  token:number;objectRef:EngineeringRef;expectedEntityRevision:string;
  installationContextId:string;expectedHierarchyRevision:string;
}
export interface SceneModelHit {sceneModelInstanceId:string;component:SceneComponentPick|null}
const text=(value:unknown):value is string=>typeof value==='string'&&value.length>0&&value.length<=512;
const sameRef=(first:EngineeringRef,second:EngineeringRef)=>first.entityUid===second.entityUid
  &&first.projectCode===second.projectCode&&first.ontobaseConnectionId===second.ontobaseConnectionId;

/** Only cache-created instance tags are consumed; the cache clears asset extras first. */
export function sceneModelHit(object:Object3D,boundary:Object3D):SceneModelHit|null {
  let node:Object3D|null=object,id:string|null=null,version:string|null=null,key:string|null=null;
  let componentSeen=false;
  while(node&&node!==boundary){
    if(!node.visible)return null;
    const data=node.userData;
    if(text(data.sceneModelInstanceId)){
      if(id!==null&&id!==data.sceneModelInstanceId)return null;id=data.sceneModelInstanceId;
    }
    if(text(data.ontoVisModelVersionId)){
      if(version!==null&&version!==data.ontoVisModelVersionId)return null;version=data.ontoVisModelVersionId;
    }
    if(!componentSeen&&(Number.isSafeInteger(data.ontoVisNodeIndex)&&data.ontoVisNodeIndex>=0
      ||data.ontoVisProxySchematic===true)){
      componentSeen=true;key=text(data.ontoVisComponentKey)?data.ontoVisComponentKey:null;
    }
    node=node.parent;
  }
  if(node!==boundary||!boundary.visible||id===null)return null;
  return {sceneModelInstanceId:id,component:version!==null&&key!==null
    ?{sceneModelInstanceId:id,modelVersionId:version,componentKey:key}:null};
}

/** Component picking can pass only shells deliberately faded in that exact instance. */
export function sceneModelRayHit(hits:readonly Pick<Intersection,'object'|'face'>[],boundary:Object3D,
  picking?:{instanceId:string;isFadedOccluder:(object:Object3D,materialIndex?:number)=>boolean}):SceneModelHit|null {
  for(const hit of hits){
    const result=sceneModelHit(hit.object,boundary);if(!result)continue;
    if(picking&&result.sceneModelInstanceId===picking.instanceId&&picking.isFadedOccluder(hit.object,hit.face?.materialIndex))continue;
    return result;
  }
  return null;
}

export interface ComponentPickContext {
  instanceId:string;modelVersionId:string;selectedObject:SceneObjectContext|null;
  components:ProjectModelComponent[];componentBindings:SceneComponentBinding[];
  enabled:boolean;lastToken:number;
}
export type ComponentPickSelection={status:'ignored'}|{status:'occupied'}|{status:'selected';keys:string[]};

/** A pick changes checkbox state only; an explicit Update still creates a draft change. */
export function pendingComponentPick(request:SceneComponentPickRequest|null|undefined,
  context:ComponentPickContext):ComponentPickSelection {
  const selected=context.selectedObject,expected=selected?.expectation;
  if(!request||!context.enabled||!Number.isSafeInteger(request.token)||request.token<=context.lastToken
    ||request.sceneModelInstanceId!==context.instanceId||request.modelVersionId!==context.modelVersionId
    ||!selected||!expected||!selected.bindingEligible||!sameRef(request.objectRef,selected.objectRef)
    ||!sameRef(expected.ref,selected.objectRef)||request.expectedEntityRevision!==selected.item.entityRevision
    ||request.expectedEntityRevision!==expected.expectedEntityRevision
    ||request.installationContextId!==expected.installationContextId
    ||request.expectedHierarchyRevision!==expected.expectedHierarchyRevision
    ||request.installationContextId!==selected.context?.installationContextId
    ||request.expectedHierarchyRevision!==selected.context?.hierarchyRevision
    ||context.components.filter(row=>row.componentKey===request.componentKey).length!==1)return {status:'ignored'};
  if(context.componentBindings.some(row=>!sameRef(row.objectRef,selected.objectRef)
    &&row.componentKeys.includes(request.componentKey)))return {status:'occupied'};
  return {status:'selected',keys:[request.componentKey]};
}
