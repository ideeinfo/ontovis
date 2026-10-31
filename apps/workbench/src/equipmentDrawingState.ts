import {ApiError,type WorkbenchApi} from './api.ts';
import type {EngineeringObject,Installation} from './types.ts';
import type {MaterialSelection} from './equipmentApi.ts';

export function equipmentDrawingSelection(object:EngineeringObject,context:Installation|null):MaterialSelection{
 if(object.installationContextId&&object.installationContextId!==context?.installationContextId)throw new ApiError(409,'ENGINEERING_CHANGED');
 return {entityUid:object.entityUid,expectedEntityRevision:object.entityRevision,installationContextId:object.installationContextId,expectedHierarchyRevision:object.installationContextId?context!.hierarchyRevision:null};
}
export type DrawingMatch={entityUid:string;entityRevision:string;displayName:string;relation:'self'|'shared_definition'|'installation_descendant'|'definition_descendant';viaEntityUid:string;viaName:string};
export type RelatedDrawing={drawingUid:string;title:string;drawingNumber:string|null;pageNumber:number|null;sourceRevision:string;contentSha256:string|null;availability:'available'|'missing';matchedObjects:DrawingMatch[];precision:'page';region:null};
export type RelatedDrawingPage={items:RelatedDrawing[];total:number;nextCursor:string|null;snapshotRevision:string;scopeComplete:true;includeDescendants:boolean};
export function equipmentDrawings(api:Pick<WorkbenchApi,'request'>,selection:MaterialSelection,scope:{includeDescendants:boolean;limit:number;cursor:string|null},signal:AbortSignal){
 return api.request<RelatedDrawingPage>('/api/workbench/objects/evidence/related',{...selection,includeDescendants:scope.includeDescendants,limit:scope.limit,...(scope.cursor?{cursor:scope.cursor}:{})},signal);
}
export function equipmentDrawingContent(api:Pick<WorkbenchApi,'request'>,selection:MaterialSelection,item:RelatedDrawing,includeDescendants:boolean,signal:AbortSignal){
 if(item.availability!=='available'||!item.contentSha256)throw new ApiError(409,'SOURCE_CHANGED');
 return api.request<Blob>('/api/workbench/objects/evidence/related/content',{...selection,includeDescendants,drawingUid:item.drawingUid,expectedSourceRevision:item.sourceRevision,expectedContentSha256:item.contentSha256},signal,true);
}
