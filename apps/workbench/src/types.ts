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
  entityUid:string; entityRevision:string; componentKey:'CT' | 'CN' | 'CN1';
  geometryQuality:'source_candidate' | 'proxy_schematic'; bounds:[number[], number[]];
}
export interface ModelView {
  sha256:string; rootEntityUid:string; bindingStatus:'demonstration_draft'; engineeringUseAllowed:false; bindings:ModelBinding[];
}
