import type {SceneEnvironmentV1} from './sceneEnvironment';
import type {EngineeringExpectation, EngineeringRef, SceneComponentBinding, SceneRootBinding} from './sceneEngineeringTypes';

/** Scene snapshots carry instance-scoped references; the server verifies engineering facts. */
export type Vector2 = [number, number];
export type Vector3 = [number, number, number];
export type Bounds3 = [Vector3, Vector3];
export type KnownVerticalDatum = 'EGM2008' | 'EGM96' | 'WGS84_ELLIPSOIDAL';
export type VerticalDatum = KnownVerticalDatum | 'UNKNOWN_RELATIVE';
export type SceneScope = 'local_plane_unbound' | 'projected_site_unbound' | 'local_plane_bound' | 'projected_site_bound' | 'project_scenes';

export interface LocalFrame {
  mode: 'local_plane'; frameRevision: string; origin: [0, 0, 0];
  unit: 'm'; axes: 'X_EAST_Y_UP_Z_SOUTH';
}
export interface LocalPosition {mode: 'local'; xM: number; zM: number}
export interface GeographicPosition {
  mode: 'geographic'; longitude: number; latitude: number; transformId: string; frameRevision: string;
}
export interface LocalRelativeHeight {mode: 'local_relative'; relativeHeightM: number}
export interface GroundHeight {
  mode: 'terrain_ground'; terrainVersionId: string; terrainSha256: string;
  sampleLongitude: number; sampleLatitude: number; sampledHeightM: number; offsetM: number;
  verticalDatum: VerticalDatum; samplingRule: string;
}
export interface AbsoluteHeight {
  mode: 'absolute'; valueM: number; verticalDatum: KnownVerticalDatum; sourceNote: string;
}
export type AnchorHeight = {mode: 'terrain_ground'; terrainVersionId: string; offsetM: number;
  /** Service-derived rounding correction for a retained relative frame origin. */
  offsetCompensationM?:number} | AbsoluteHeight;
export type AnchorInputHeight = {mode:'terrain_ground';terrainVersionId:string;offsetM:number;offsetCompensationM?:never}|AbsoluteHeight;
export interface GeographicAnchor {
  localAnchor: Vector2; geographicAnchor: Vector2; trueNorthHeadingDeg: number;
  anchorHeight: AnchorHeight; heightStrategy: 'keep_relative_to_anchor' | 'resample_each_ground';
}
export type GeographicAnchorInput=Omit<GeographicAnchor,'anchorHeight'>&{anchorHeight:AnchorInputHeight};
interface ProjectedFrameBase {
  mode: 'projected_site'; frameRevision: string; horizontalCrs: string; transformId: string;
  originEasting: number; originNorthing: number; originHeight: number;
  convergenceRuleId: string; anchor: GeographicAnchor;
}
export type ProjectedFrame = ProjectedFrameBase & (
  {verticalDatum: KnownVerticalDatum; relativeReferenceId?: never} |
  {verticalDatum: 'UNKNOWN_RELATIVE'; relativeReferenceId: string}
);
export type CoordinateFrame = LocalFrame | ProjectedFrame;
export interface LocalPlacement {position: LocalPosition; height: LocalRelativeHeight; headingDeg: number}
export interface GeographicPlacement {position: GeographicPosition; height: GroundHeight | AbsoluteHeight; headingDeg: number}
interface InstanceBase {
  sceneModelInstanceId: string; displayName: string; modelVersionId: string;
  visible: boolean; positionLocked: boolean;
  rootBinding: SceneRootBinding|null; componentBindings: SceneComponentBinding[];
}
export interface LocalSceneModelInstance extends InstanceBase {placement: LocalPlacement}
export interface GeographicSceneModelInstance extends InstanceBase {placement: GeographicPlacement}
export type SceneModelInstance = LocalSceneModelInstance | GeographicSceneModelInstance;
export interface SceneView {eye: Vector3; target: Vector3}
export interface SceneGroup {groupId:string;displayName:string;instanceIds:string[]}
export interface SceneViewpoint {
  viewpointId:string;displayName:string;kind:'component'|'overview';view:SceneView;frameRevision:string;
  modelTarget:{sceneModelInstanceId:string;modelVersionId:string}|null;
}
export interface SceneRouteStep {stepId:string;viewpointId:string;flightSeconds:number;dwellSeconds:number}
export interface SceneRoute {routeId:string;displayName:string;steps:SceneRouteStep[]}
export interface SceneOrganization {groups:SceneGroup[];viewpoints:SceneViewpoint[];routes:SceneRoute[]}
export interface SceneDefaults {
  background: 'plain' | 'sky'; lighting: 'neutral' | 'dusk'; terrainMaterial: 'solid' | 'grass';
}
export interface SceneTerrainRef {terrainVersionId: string; expectedContentRevision: string}
export interface SceneImageryRef {imageryVersionId:string;expectedContentRevision:string;expectedReportSha256:string;visible:boolean}
interface SnapshotBase {environment?:SceneEnvironmentV1|null;displayName: string; description?:string; initialView: SceneView; defaults: SceneDefaults;organization?:SceneOrganization;imagery?:SceneImageryRef|null}
export interface LocalSceneSnapshot extends SnapshotBase {
  imagery?:null;
  coordinateFrame: LocalFrame; terrain: null; instances: LocalSceneModelInstance[];
}
export interface ProjectedSceneSnapshot extends SnapshotBase {
  coordinateFrame: ProjectedFrame; terrain: SceneTerrainRef; instances: GeographicSceneModelInstance[];
}
export type EditableSceneSnapshot = LocalSceneSnapshot | ProjectedSceneSnapshot;
export interface ModelResourceRef {modelVersionId: string; modelAssetId?: string; sha256: string; contentRevision: string}
export interface TerrainResourceRef {terrainVersionId: string; contentRevision: string; sha256: string; reportSha256: string}
export interface ResourceRefs {models: ModelResourceRef[]; terrains: TerrainResourceRef[]}
export interface DisplayPlacement {
  sceneModelInstanceId: string; position: Vector3; threeYawRad: number;
  heightM?: number; gridHeadingDeg?: number;
}
export interface TerrainDisplayTransform {translation: Vector3; rotationY: number; scale: 1}
export interface GeometrySummary {
  mode: 'local_plane' | 'projected_site'; instanceCount: number;
  transformId?: string; samplingRule?: string;
  fieldAccuracyVerified: false; engineeringValidationPerformed: false;
}
export interface AnchorTransform {
  gridHeadingDegAtAnchor: number; rotationYRad: number; translationM: Vector3;
  heightStrategy: GeographicAnchor['heightStrategy']; anchorHeightM: number;
  verticalTransform: 'rigid_relative' | 'per_instance_fixed_mesh';
}
export interface AnchorImpact {
  kind: 'first_geographic_anchor'; instanceIds: string[]; oldFrameRevision: string;
  newFrameRevision: string; explicitConfirmationRequired: true;
}
export interface RootBindingChange {
  sceneModelInstanceId:string;from:EngineeringRef|null;to:EngineeringRef|null;
  clearOldComponentBindings:true;reviewedRemovedBindingsDigest:string;
}
export interface RootBindingImpact extends RootBindingChange {removedBindings:SceneComponentBinding[]}
export type BindingIssue={sceneModelInstanceId:string;objectRef:EngineeringRef;installationContextId:string;blocking:true} & (
  {kind:'model_version_changed';previousModelVersionId:string;previousComponentKeys:string[];sourceSceneRevision:string;
    code:'COMPONENT_MISSING'|'MIGRATION_REQUIRED'|'SOURCE_ID_AMBIGUOUS'} |
  {kind:'engineering_changed';expectedEntityRevision:string;expectedHierarchyRevision:string;
    code:'IDENTITY_CHANGED'|'ENTITY_CHANGED'|'PARENT_CHAIN_CHANGED'}
);
export interface GeometryValidation {
  scope: SceneScope; bindingIssues: BindingIssue[];
  engineeringExpectations?:EngineeringExpectation[];rootBindingChanges?:RootBindingChange[];rootBindingImpact?:RootBindingImpact[];
  geometrySummary?: GeometrySummary; displayPlacements?: DisplayPlacement[];
  terrainDisplayTransform?: TerrainDisplayTransform; anchorTransform?: AnchorTransform; impact?: unknown;
}
export type HeightBasisKind = 'terrain_estimate' | 'declared_absolute' | 'relative_layout_from_anchor' |
  'terrain_estimate_from_anchor_offset' | 'terrain_estimate_preserved_as_absolute' | 'terrain_estimate_on_replacement';
export interface HeightBasis {kind:HeightBasisKind;reviewedSceneRevision:string;height:GroundHeight|AbsoluteHeight;terrainRef:TerrainResourceRef|null}
export interface HeightProvenance {
  sceneModelInstanceId: string;
  kind: HeightBasisKind | 'retained_height_basis';
  verticalDatum: VerticalDatum; terrainVersionId?: string; reportSha256?: string;
  sampledHeightM?: number; offsetM?: number; relativeReferenceId?: string;
  sourceNote?: string; anchorSource?: AnchorHeight;
  basisKind?: HeightBasisKind; basisSceneRevision?: string; heightBasis?:HeightBasis;
  replacementStrategy?: 'keep_height' | 'resample_ground';
  previousHeight?: unknown; previousHeightProvenance?: unknown;
  previousTerrainRef?: unknown; previousAnchorHeight?: unknown;
}
export interface SceneCapabilities {
  environmentSchemaVersions?:number[];waterModes?:string[];surroundingBackgroundModes?:string[];cloudModes?:string[];
  storageScope: SceneScope; supportsGeographic: boolean; supportsEngineeringBindings: boolean;
  maxInstances: number; maxSnapshotBytes: number; maxCheckJsonBytes: number;
  scope: SceneScope; localPlaneUnbound: true; canRead: true; canWrite: boolean;
  existingUploadedModelVersionsOnly: true; projectModelResources: true; canPreflightGeographic: boolean;
}
export interface SceneLimits {
  maxSaveJsonBytes: number; maxReadJsonBytes: number; maxCheckJsonBytes: number;
  maxInstances: number; maxComponentBindings: number; maxNameCharacters: number; maxLocalCoordinateM: number;
}
export interface SceneResponse {sessionRevision: string; projectName?: string; capabilities: SceneCapabilities; limits: SceneLimits}
export interface SceneSummary {
  sceneId: string; displayName: string; headRevision: string; updatedAt: string; instanceCount: number;
}
export interface SceneList extends SceneResponse {items: SceneSummary[]; snapshotRevision: string; nextCursor: string | null}
export interface SceneListRequest {q?: string; cursor?: string | null; limit?: number}
export interface LegacySceneEntryTarget {
  sceneId:string;sceneRevision:string;registeredSceneRevision:string;sceneModelInstanceId:string;
}
export type LegacySceneEntryRequest = {sourceKind:'fixed_model'|'uploaded_version';sourceKey:string} |
  {sourceKind?:never;sourceKey?:never};
export interface LegacySceneEntry {
  migrated:boolean;legacyReadOnly:boolean;available:boolean;entry:LegacySceneEntryTarget|null;
  reason:string|null;sessionRevision:string;
}
export interface SceneCreateRequest {displayName: string; description?:string; clientRequestId: string}
export interface SceneOpen extends SceneResponse {
  createdAt?:string;
  sceneId: string; projectCode: string; sceneRevision: string; headRevision: string; savedAt: string;
  snapshot: EditableSceneSnapshot; resourceRefs: ModelResourceRef[]; validation: GeometryValidation;
  heightProvenance?: HeightProvenance[]; terrainRefs?: TerrainResourceRef[];
  reviewedEngineering?:EngineeringExpectation[];rootBindingChanges?:RootBindingChange[];rootBindingImpact?:RootBindingImpact[];
}
export interface SceneHead extends SceneResponse {sceneId: string; headRevision: string; updateAvailable: boolean}
export interface SpatialChange {kind: 'anchor' | 'model' | 'terrain'; receipt: string}
export interface SceneSaveRequest {
  environmentWriteVersion?:1;sceneInfoWriteVersion?:1;
  sceneId: string; expectedSceneRevision: string; clientRequestId: string; snapshot: EditableSceneSnapshot;
  reviewedEngineering: EngineeringExpectation[]; rootBindingChanges: RootBindingChange[]; spatialChange?: SpatialChange;
}
export interface SceneSave extends SceneResponse {
  sceneId: string; sceneRevision: string; headRevision: string; savedAt: string;
  validation: GeometryValidation; heightProvenance?: HeightProvenance[]; terrainRefs?: TerrainResourceRef[];
}
interface SceneCheckBase {environmentWriteVersion?:1;sceneInfoWriteVersion?:1;sceneId: string; expectedSceneRevision: string; snapshot: EditableSceneSnapshot}
export type SceneCheckRequest = (SceneCheckBase & {kind: 'validate'}) | (
  Omit<SceneCheckBase, 'snapshot'> & {kind: 'anchor'; snapshot: LocalSceneSnapshot;
    candidateTerrainVersionId: string; anchor: GeographicAnchorInput}
);
/** Replacement previews compare the supplied unchanged snapshot with its saved head. */
export type SceneReplacementCheckRequest = SceneCheckBase & (
  {kind: 'model'; sceneModelInstanceId: string; candidateModelVersionId: string;
    candidateTerrainVersionId?: never; strategy?: never} |
  {kind: 'terrain'; candidateTerrainVersionId: string; strategy: 'keep_height' | 'resample_ground';
    sceneModelInstanceId?: never; candidateModelVersionId?: never}
);
export interface SceneCheck extends SceneResponse {
  sceneId: string; baseSceneRevision: string; proposedSnapshot: EditableSceneSnapshot;
  validation: GeometryValidation; heightProvenance: HeightProvenance[];
  resourceRefs: ResourceRefs; spatialChange: SpatialChange | null;
  reviewedEngineering?:EngineeringExpectation[];rootBindingChanges?:RootBindingChange[];rootBindingImpact?:RootBindingImpact[];
}
