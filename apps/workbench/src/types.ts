export interface SessionView { state: string; sessionRevision: string; username?: string }
export interface EngineeringObject {
  entityUid: string; entityRevision: string; displayName: string;
  objectKind: string; reviewStatus: string; lifecycle: string;
  installationContextId: string | null; installationPurpose: string | null;
  objectScope: string; hasChildren: boolean;
  sourceTemplateEntityUid: string | null;
}
export interface Installation {
  installationContextId: string; projectCode: string; displayName: string;
  hierarchyRevision: string; rootEntityUid: string | null;
  purpose: string; engineeringUseAllowed: boolean;
}
export interface ContextView { context: Installation; root: EngineeringObject | null; projectName: string; children: ChildrenView | null }
export interface CatalogView { items: EngineeringObject[]; nextCursor: string | null; snapshotRevision: string }
export interface Relation { verificationState: string; engineeringUseAllowed: boolean }
export interface ChildrenView {
  items: {object: EngineeringObject; relation: Relation}[];
  nextCursor: string | null; hierarchyRevision: string;
}
export interface ObjectView {
  item: EngineeringObject;
  ancestors: {completeness: string; path: {object: EngineeringObject; relation: Relation}[]};
}
export interface Evidence {
  evidenceRef: string; sourceRelation: 'direct' | 'template_definition';
  sourceEntityUid: string; sourceEntityRevision: string; sourceTemplateRevision: string | null;
  sourceRevision: string; recordDigest: string; contentSha256: string | null;
  title: string; pageNumber: number | null; availability: 'available' | 'missing';
  versionMode: 'current_content_snapshot'; precision: 'page'; region: null;
}
export interface EvidenceList { items: Evidence[]; complete: true }
export interface ModelBinding {
  entityUid:string; entityRevision:string; componentKey:string; displayName?:string;
  geometryQuality:'source_candidate' | 'proxy_schematic'; bounds:[number[], number[]];
}
export interface ModelView {
  sha256:string; rootEntityUid:string; bindingStatus:'demonstration_draft'; engineeringUseAllowed:false; bindings:ModelBinding[];
  modelVersionId?:string; modelRevision?:number; viewRevision?:string; displayName?:string;
  components?:ModelComponent[]; canEditBindings?:boolean; bindingWarnings?:{entityUid:string;code:string}[];
}
export interface ModelComponent {componentKey:string;displayName:string;nodeIndices:number[];keyStability:'version_local';geometryQuality:'source_candidate'|'proxy_schematic';bounds:[number[],number[]]}
export interface ModelReport {bytes:number;nodes:number;activeMeshInstances:number;triangles:number;images:number;coordinateVerification:'unverified';externalResourcesFetched:0}
export interface ModelVersion {versionId:string;displayName:string;sourceNote:string;sha256:string;bytes:number;createdAt:string;modelRevision:number;state:'ready';report:ModelReport;bindingCount:number}
export interface ModelLibraryView {libraryRevision:string;canUpload:boolean;hasCurrentModel:boolean;maxBytes:number;maxModels:number;items:ModelVersion[]}
