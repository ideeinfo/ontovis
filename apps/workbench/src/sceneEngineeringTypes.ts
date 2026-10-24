import type {EngineeringObject, Installation, Relation} from './types';
import type {Bounds3} from './sceneTypes';

export interface EngineeringRef {ontobaseConnectionId:string;projectCode:string;entityUid:string}
export interface SceneRootBinding {objectRef:EngineeringRef}
export interface SceneComponentBinding {objectRef:EngineeringRef;componentKeys:string[]}
export interface EngineeringExpectation {
  ref:EngineeringRef;expectedEntityRevision:string;installationContextId:string;expectedHierarchyRevision:string;
}
export interface SceneObjectAncestors {
  path:{object:EngineeringObject;relation:Relation}[];
  completeness:'complete'|'incomplete'|'not_applicable';reasonCode:string|null;
  hierarchyRevision?:string;installationContextId?:string;
}
export interface SceneObjectSelection {
  objectRef:EngineeringRef;item:EngineeringObject;context:Installation|null;root:EngineeringObject|null;
  ancestors:SceneObjectAncestors;expectation:EngineeringExpectation|null;
  bindingEligible:boolean;bindingReason:string|null;
}
export interface SceneObjectContext extends SceneObjectSelection {sessionRevision:string;projectName?:string}
export interface SceneObjectDetailRequest {
  installationContextId:string|null;entityUid:string;expectedHierarchyRevision:string|null;expectedEntityRevision?:string;
}
export interface SceneObjectChildren {
  projectCode:string;installationContextId:string;parentEntityUid:string;hierarchyRevision:string;
  snapshotRevision:string;items:{object:EngineeringObject;relation:Relation}[];nextCursor:string|null;
  selection:SceneObjectSelection;sessionRevision:string;projectName?:string;
}
export interface SceneRepresentation {
  sceneModelInstanceId:string;instanceName:string;modelVersionId:string;componentKeys:string[];
  geometryQuality:'source_candidate'|'proxy_schematic';visible:boolean;hostObject:EngineeringObject&{objectRef:EngineeringRef};
}
export interface SceneLocation {
  sceneId:string;sceneRevision:string;contextEpoch:string;selectedObject:EngineeringObject&{objectRef:EngineeringRef};
  status:'located'|'choose_representation'|'unavailable';mode:'direct'|'ancestor'|null;
  hostObject:(EngineeringObject&{objectRef:EngineeringRef})|null;sceneModelInstanceId:string|null;
  componentKeys:string[];modelVersionId:string|null;geometryQuality:'source_candidate'|'proxy_schematic'|null;
  relationshipStatus:'confirmed'|'assumed'|null;worldBounds:Bounds3|null;choices:SceneRepresentation[];reason:string|null;
}
export interface SceneLocationRequest {
  sceneId:string;sceneRevision:string;selectedObjectRef:EngineeringRef;contextEpoch:string;
  representationChoice?:Pick<SceneRepresentation,'sceneModelInstanceId'|'modelVersionId'>;
}
