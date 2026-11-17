export interface ProjectRef {ontobaseConnectionId:string;projectCode:string}
export interface ProjectSummary {
  projectRef:ProjectRef;displayName:string;sourceDescription:string;status:'active';
  workspaceState:'unconfigured'|'preparing'|'ready'|'blocked';workspaceId?:string;sceneCount:number;
}
export interface ProjectDirectory {items:ProjectSummary[];nextCursor:string|null;snapshotRevision:string}
export interface ProjectAccess {projectRef:ProjectRef;projectName:string;role:string;capabilities:string[];accessRevision:string}
