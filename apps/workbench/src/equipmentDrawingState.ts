import {ApiError,type WorkbenchApi} from './api.ts';
import type {EngineeringObject,Installation,Evidence,EvidenceList} from './types.ts';
import type {MaterialSelection} from './equipmentApi.ts';

export function equipmentDrawingSelection(object:EngineeringObject,context:Installation|null):MaterialSelection{
 if(object.installationContextId&&object.installationContextId!==context?.installationContextId)throw new ApiError(409,'ENGINEERING_CHANGED');
 return {entityUid:object.entityUid,expectedEntityRevision:object.entityRevision,installationContextId:object.installationContextId,expectedHierarchyRevision:object.installationContextId?context!.hierarchyRevision:null};
}
export function equipmentDrawings(api:Pick<WorkbenchApi,'request'>,selection:MaterialSelection,signal:AbortSignal){
 return api.request<EvidenceList>('/api/workbench/objects/evidence/resolve',selection,signal);
}
export function equipmentDrawingContent(api:Pick<WorkbenchApi,'request'>,selection:MaterialSelection,item:Evidence,signal:AbortSignal){
 if(item.availability!=='available'||!item.contentSha256)throw new ApiError(409,'SOURCE_CHANGED');
 return api.request<Blob>('/api/workbench/objects/evidence/content',{...selection,evidenceRef:item.evidenceRef,expectedSourceRevision:item.sourceRevision,expectedContentSha256:item.contentSha256},signal,true);
}
