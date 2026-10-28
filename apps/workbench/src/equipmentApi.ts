import type {WorkbenchApi} from './api';
import type {EngineeringObject,Installation} from './types';
import type {EngineeringRef} from './sceneEngineeringTypes';
import type {ProjectModelVersion} from './resourceTypes';
import type {ObjectPhoto} from './workOrderTypes';

export interface SharedMapping {objectRef:EngineeringRef;expectedEntityRevision:string;componentKeys:string[]}
export interface EquipmentConfigurationSnapshot {displayName:string;objectKind:string;
  rootDefinition:{objectRef:EngineeringRef;expectedEntityRevision:string}|null;
  models:{modelVersionId:string;mappings:SharedMapping[]}[]}
export interface EquipmentConfiguration {configurationId:string;configurationRevision:string;snapshot:EquipmentConfigurationSnapshot;equipmentCount:number;savedAt:string}
export interface EquipmentAdoption {equipment_uid:string;configuration_id:string;assignment_revision:string}
export interface EquipmentRecord {item:EngineeringObject&{equipmentState?:'active'|'inactive'};context:Installation;children:EngineeringObject[]}
export interface EquipmentConfigurations {items:EquipmentConfiguration[];assignments:EquipmentAdoption[];objects:EngineeringObject[];models:ProjectModelVersion[];capabilities:{canWrite:boolean}}
export type EquipmentCatalogItem=EngineeringObject&{sceneUseCount:number};
export interface EquipmentCatalogue {items:EquipmentCatalogItem[];nextCursor:string|null;snapshotRevision:string}
interface PhotoSelection {entityUid:string;expectedEntityRevision:string;installationContextId:string|null;
  expectedHierarchyRevision:string|null;photoPurpose:'object_location'|'field_record'}
const ROOT='/api/workbench/equipment';
export class EquipmentApi {
  private api:WorkbenchApi;
  constructor(api:WorkbenchApi){this.api=api;}
  catalogue(q='',cursor:string|null=null,signal?:AbortSignal){return this.api.request<EquipmentCatalogue>(ROOT,{q,cursor,limit:50,rootsOnly:true},signal);}
  configurations(signal?:AbortSignal){return this.api.request<EquipmentConfigurations>(ROOT+'/configurations',{},signal);}
  resolve(entityUids:string[],signal?:AbortSignal){return this.api.request<{items:EquipmentRecord[]}>(ROOT+'/resolve',{entityUids},signal);}
  children(parentEntityUid:string,cursor:string|null=null,signal?:AbortSignal){return this.api.request<{items:{object:EngineeringObject}[];nextCursor:string|null;total:number}>(ROOT+'/definitions/children',{parentEntityUid,...(cursor?{cursor}:{})},signal);}
  photoContent(selection:PhotoSelection,photo:ObjectPhoto,full=false,signal?:AbortSignal){
    return this.api.request<Blob>('/api/workbench/objects/photos/content',{...selection,evidenceRef:photo.evidenceRef,
      expectedSourceRevision:photo.sourceRevision,expectedContentVersionId:photo.contentVersionId,expectedSourceSha256:photo.sourceSha256,
      expectedDisplayRevision:photo.selector?.displayRevision,representation:full?'display':'preview'},signal,'source');
  }
  save(configurationId:string,expectedConfigurationRevision:string|null,snapshot:EquipmentConfigurationSnapshot,signal?:AbortSignal){
    return this.api.request<EquipmentConfiguration>(ROOT+'/configurations/save',{configurationId,expectedConfigurationRevision,snapshot,clientRequestId:crypto.randomUUID()},signal);
  }
  assign(configuration:EquipmentConfiguration,rows:EquipmentRecord[],assignments:EquipmentAdoption[],signal?:AbortSignal){
    return this.api.request(ROOT+'/configurations/assign',{configurationId:configuration.configurationId,expectedConfigurationRevision:configuration.configurationRevision,
      equipment:rows.map(({item,context})=>({entityUid:item.entityUid,expectedEntityRevision:item.entityRevision,expectedHierarchyRevision:context.hierarchyRevision,
        expectedAssignmentRevision:assignments.find(a=>a.equipment_uid===item.entityUid)?.assignment_revision??null})),clientRequestId:crypto.randomUUID()},signal);
  }
}
