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

export function appendDrawingPage(previous:RelatedDrawingPage|null,page:RelatedDrawingPage,cursor:string|null):RelatedDrawingPage{
 if(cursor!==null&&(!previous||previous.nextCursor!==cursor||page.nextCursor===cursor||
     previous.snapshotRevision!==page.snapshotRevision||previous.total!==page.total||previous.includeDescendants!==page.includeDescendants))
  throw new ApiError(409,'SNAPSHOT_EXPIRED');
 const items=previous?[...previous.items,...page.items]:page.items;
 if(items.length>page.total||Boolean(page.nextCursor)!==(items.length<page.total)||new Set(items.map(item=>item.drawingUid)).size!==items.length)
  throw new ApiError(409,'SNAPSHOT_EXPIRED');
 return {...page,items};
}

export function filterEquipmentDrawings(items:RelatedDrawing[],query:string){
 const normalize=(value:string)=>value.normalize('NFKC').toLowerCase();
 const search=normalize(query).trim(),pageOnly=search.match(/^(?:第\s*)?(\d+)\s*页$|^page\s+(\d+)$/);
 if(pageOnly)return items.filter(item=>item.pageNumber===Number(pageOnly[1]??pageOnly[2]));
 const terms=search.split(/\s+/).filter(Boolean);
 if(!terms.length)return items;
 return items.filter(item=>{
  const page=item.pageNumber===null?'':`第${item.pageNumber}页 Page ${item.pageNumber}`;
  const text=normalize([item.title,item.drawingNumber,page,...item.matchedObjects.flatMap(match=>[match.displayName,match.viaName])].join(' '));
  return terms.every(term=>text.includes(term));
 });
}

export function equipmentDrawings(api:Pick<WorkbenchApi,'request'>,selection:MaterialSelection,scope:{includeDescendants:boolean;limit:number;cursor:string|null},signal:AbortSignal){
 return api.request<RelatedDrawingPage>('/api/workbench/objects/evidence/related',{...selection,includeDescendants:scope.includeDescendants,limit:scope.limit,...(scope.cursor?{cursor:scope.cursor}:{})},signal);
}
export function equipmentDrawingContent(api:Pick<WorkbenchApi,'request'>,selection:MaterialSelection,item:RelatedDrawing,includeDescendants:boolean,signal:AbortSignal){
 if(item.availability!=='available'||!item.contentSha256)throw new ApiError(409,'SOURCE_CHANGED');
 return api.request<Blob>('/api/workbench/objects/evidence/related/content',{...selection,includeDescendants,drawingUid:item.drawingUid,expectedSourceRevision:item.sourceRevision,expectedContentSha256:item.contentSha256},signal,true);
}
