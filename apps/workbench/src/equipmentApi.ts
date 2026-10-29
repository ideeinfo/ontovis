import type {WorkbenchApi} from './api';
import type {EngineeringObject,Installation} from './types';
import type {EngineeringRef} from './sceneEngineeringTypes';
import type {ProjectModelVersion} from './resourceTypes';
import type {ObjectPhoto} from './workOrderTypes';

export interface SharedMapping {objectRef:EngineeringRef;expectedEntityRevision:string;componentKeys:string[]}
export interface ProjectApplicationRef {applicationId:string;applicationRevisionId:string;specificationRevisionId:string}
export interface EquipmentConfigurationSnapshot {displayName:string;objectKind:string;
  projectApplicationRef?:ProjectApplicationRef;
  rootDefinition:{objectRef:EngineeringRef;expectedEntityRevision:string}|null;
  models:{modelVersionId:string;mappings:SharedMapping[]}[]}
export interface EquipmentConfiguration {configurationId:string;configurationRevision:string;snapshot:EquipmentConfigurationSnapshot;equipmentCount:number|null;savedAt:string}
export interface EquipmentAdoption {equipment_uid:string;configuration_id:string;assignment_revision:string}
export interface SourceAdoption extends ProjectApplicationRef {adoptionId:string;roleKey:string|null;name:string;previousAdoptionId:string|null}
export interface EquipmentModel {specificationId:string;revisionId:string;headRevisionId:string;templateRevisionId:string;name:string;code:string;manufacturer:string|null;objectKind:string;revision:number;classificationRef:{revisionId:string;code:string}}
export interface EquipmentRecord {item:EngineeringObject&{equipmentState?:'active'|'inactive'};context:Installation;children:EngineeringObject[];adoption:SourceAdoption|null;attributes:{values:PropertyValue[]}|null;model:EquipmentModel|null}
export interface EquipmentConfigurations {items:EquipmentConfiguration[];assignments:EquipmentAdoption[];objects:EngineeringObject[];models:ProjectModelVersion[];capabilities:{canWrite:boolean}}
export type EquipmentCatalogItem=EngineeringObject&{sceneUseCount:number};
export interface EquipmentCatalogue {items:EquipmentCatalogItem[];nextCursor:string|null;snapshotRevision:string}
interface PhotoSelection {entityUid:string;expectedEntityRevision:string;installationContextId:string|null;
  expectedHierarchyRevision:string|null;photoPurpose:'object_location'|'field_record'}
const ROOT='/api/workbench/equipment';
export interface SourceReference {provider?:string;url?:string;kind?:string;version?:string;note?:string}
export interface PropertyValue {propertyKey:string;propertyRevisionId:string;status:string;value:unknown;unit:string|null;source?:SourceReference}
export interface EquipmentApplication {applicationId:string;revisionId:string;headRevisionId:string;revision:number;projectCode:string;
  snapshot:{name:string;specificationRevisionId:string;rootDefinition:{entityUid:string;expectedEntityRevision:string}|null;
    mappings:{roleKey:string;entityUid:string;expectedEntityRevision:string}[]};specification:{name:string;objectKind:string;manufacturer:string|null}}
export interface ApplicationBundle {application:EquipmentApplication;objects:EngineeringObject[];
  specification:{specificationId:string;revision:number;revisionId:string;headRevisionId:string;code:string;snapshot:{name:string;manufacturer:string|null;nature:string;
    classificationRef:{code:string};values:PropertyValue[];roles:{roleKey:string;name:string;quantity:number;optional:boolean}[];sources:SourceReference[]}};
  template:{fields:{propertyKey:string;propertyRevisionId:string;definition:{nameZh:string;nameEn:string;unit:string|null};inherited:boolean}[]}}
export interface ApplicationSummary {applicationId:string;revisionId:string;revision:number;name:string;specificationName:string;equipmentCount:number}
export interface SharedPhoto {documentId:string;contentVersionId:string;renditionId:string;displayRevision:string;title:string;viewLabel:string;
  sources:string[];regionCount:number;availability:string}
export interface SharedPhotoRegion {object:EngineeringObject;photo:ObjectPhoto}
export type MaterialSelection=Omit<PhotoSelection,'photoPurpose'>;
export interface EquipmentMaterial {documentId:string;contentVersionId:string;title:string;kind:'pdf'|'photo';documentKind:string;versionNumber:number;pageCount:number|null;availability:'available'|'unavailable'|'field_record';scopes:string[];origins:string[]}
export interface EquipmentMaterialPage {model:EquipmentModel|null;role?:string|null;roles:{value:string;kind:'model'|'root'|'role';name:string|null}[];revision:number;total?:number;items:EquipmentMaterial[];nextCursor:string|null;canManage:boolean}
export interface FixedDocument {documentId:string;contentVersionId:string;sourceSha256:string;title:string;kind:'pdf'|'photo';pageNumber:number;pageCount:number;versionNumber:number;newerVersionAvailable:boolean}
export interface EquipmentAttributeForm {available:boolean;reason:string|null;model:EquipmentModel|null;scope?:{source:string;name:string;classificationCode:string};fields:ApplicationBundle['template']['fields'];values:PropertyValue[]}
export class EquipmentApi {
  private api:WorkbenchApi;
  constructor(api:WorkbenchApi){this.api=api;}
  catalogue(q='',cursor:string|null=null,signal?:AbortSignal){return this.api.request<EquipmentCatalogue>(ROOT,{q,cursor,limit:50,rootsOnly:true},signal);}
  configurations(signal?:AbortSignal){return this.api.request<EquipmentConfigurations>(ROOT+'/configurations',{},signal);}
  resolve(entityUids:string[],signal?:AbortSignal){return this.api.request<{items:EquipmentRecord[]}>(ROOT+'/resolve',{entityUids},signal);}
  modelMaterials(specificationId:string,scope='',kind='',cursor:string|null=null,signal?:AbortSignal){return this.api.request<EquipmentMaterialPage>(ROOT+'/materials/models',{specificationId,scope,kind,cursor,limit:20},signal);}
  materialCandidates(specificationId:string,revision:number,scope='model',q='',kind='',cursor:string|null=null,signal?:AbortSignal){return this.api.request<{items:(EquipmentMaterial&{selected:boolean})[];nextCursor:string|null}>(ROOT+'/materials/candidates',{specificationId,revision,scope,q,kind,cursor,limit:20},signal);}
  deviceMaterials(selection:MaterialSelection,cursor:string|null=null,signal?:AbortSignal){return this.api.request<EquipmentMaterialPage>(ROOT+'/materials/resolve',{...selection,cursor,limit:20},signal);}
  materialMetadata(documentId:string,contentVersionId:string,signal?:AbortSignal){return this.api.request<FixedDocument>(ROOT+'/materials/metadata',{documentId,contentVersionId},signal);}
  materialContent(value:FixedDocument,pageNumber:number,signal?:AbortSignal,representation:'preview'|'display'='preview'){return this.api.request<Blob>(ROOT+'/materials/content',{documentId:value.documentId,contentVersionId:value.contentVersionId,sourceSha256:value.sourceSha256,pageNumber,representation},signal,'source');}
  attributeForm(entityUid:string,signal?:AbortSignal){return this.api.request<EquipmentAttributeForm>(ROOT+'/attribute-form',{entityUid},signal);}
  children(parentEntityUid:string,cursor:string|null=null,signal?:AbortSignal){return this.api.request<{items:{object:EngineeringObject}[];nextCursor:string|null;total:number}>(ROOT+'/definitions/children',{parentEntityUid,...(cursor?{cursor}:{})},signal);}
  applications(offset=0,signal?:AbortSignal){return this.api.request<{items:ApplicationSummary[];total:number;offset:number;limit:number}>(ROOT+'/applications',{offset,limit:50},signal);}
  application(applicationRevisionId:string,signal?:AbortSignal){return this.api.request<ApplicationBundle>(ROOT+'/applications/detail',{applicationRevisionId},signal);}
  sharedPhotos(selection:MaterialSelection,cursor:string|null=null,signal?:AbortSignal){return this.api.request<{items:SharedPhoto[];nextCursor:string|null}>(ROOT+'/shared-photos/query',{...selection,limit:12,cursor},signal);}
  sharedRegions(selection:MaterialSelection,photo:SharedPhoto,cursor:string|null=null,signal?:AbortSignal){return this.api.request<{items:SharedPhotoRegion[];nextCursor:string|null}>(ROOT+'/shared-photos/regions',{...selection,documentId:photo.documentId,contentVersionId:photo.contentVersionId,limit:50,cursor},signal);}
  sharedContent(selection:MaterialSelection,photo:SharedPhoto,representation:'thumbnail'|'preview'|'original',signal?:AbortSignal){return this.api.request<Blob>(ROOT+'/shared-photos/content',{...selection,documentId:photo.documentId,contentVersionId:photo.contentVersionId,renditionId:photo.renditionId,expectedDisplayRevision:photo.displayRevision,representation},signal,'source');}
  photoContent(selection:PhotoSelection,photo:ObjectPhoto,full=false,signal?:AbortSignal){
    return this.api.request<Blob>('/api/workbench/objects/photos/content',{...selection,evidenceRef:photo.evidenceRef,
      expectedSourceRevision:photo.sourceRevision,expectedContentVersionId:photo.contentVersionId,expectedSourceSha256:photo.sourceSha256,
      expectedDisplayRevision:photo.selector?.displayRevision,representation:full?'display':'preview'},signal,'source');
  }
  save(configurationId:string,expectedConfigurationRevision:string|null,snapshot:EquipmentConfigurationSnapshot,signal?:AbortSignal){
    return this.api.request<EquipmentConfiguration>(ROOT+'/configurations/save',{configurationId,expectedConfigurationRevision,
      snapshot:{projectApplicationRef:snapshot.projectApplicationRef,models:snapshot.models},clientRequestId:crypto.randomUUID()},signal);
  }
}
