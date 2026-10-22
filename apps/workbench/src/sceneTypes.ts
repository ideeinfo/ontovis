/** Current scene HTTP slice: unbound placements only; no engineering write API. */
export type Vector2 = [number, number];
export type Vector3 = [number, number, number];
export type Bounds3 = [Vector3, Vector3];
export type KnownVerticalDatum = 'EGM2008' | 'EGM96' | 'WGS84_ELLIPSOIDAL';
export type VerticalDatum = KnownVerticalDatum | 'UNKNOWN_RELATIVE';
export type SceneScope = 'local_plane_unbound' | 'projected_site_unbound';

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
export type AnchorHeight = {mode: 'terrain_ground'; terrainVersionId: string; offsetM: number} | AbsoluteHeight;
export interface GeographicAnchor {
  localAnchor: Vector2; geographicAnchor: Vector2; trueNorthHeadingDeg: number;
  anchorHeight: AnchorHeight; heightStrategy: 'keep_relative_to_anchor' | 'resample_each_ground';
}
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
  rootBinding: null; componentBindings: never[];
}
export interface LocalSceneModelInstance extends InstanceBase {placement: LocalPlacement}
export interface GeographicSceneModelInstance extends InstanceBase {placement: GeographicPlacement}
export type SceneModelInstance = LocalSceneModelInstance | GeographicSceneModelInstance;
export interface SceneView {eye: Vector3; target: Vector3}
export interface SceneDefaults {
  background: 'plain' | 'sky'; lighting: 'neutral' | 'dusk'; terrainMaterial: 'solid' | 'grass';
}
export interface SceneTerrainRef {terrainVersionId: string; expectedContentRevision: string}
interface SnapshotBase {displayName: string; initialView: SceneView; defaults: SceneDefaults}
export interface LocalSceneSnapshot extends SnapshotBase {
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
export interface GeometryValidation {
  scope: SceneScope; bindingIssues: never[];
  geometrySummary?: GeometrySummary; displayPlacements?: DisplayPlacement[];
  terrainDisplayTransform?: TerrainDisplayTransform; anchorTransform?: AnchorTransform; impact?: AnchorImpact;
}
export interface HeightProvenance {
  sceneModelInstanceId: string;
  kind: 'terrain_estimate' | 'declared_absolute' | 'relative_layout_from_anchor' | 'terrain_estimate_from_anchor_offset';
  verticalDatum: VerticalDatum; terrainVersionId?: string; reportSha256?: string;
  sampledHeightM?: number; offsetM?: number; relativeReferenceId?: string;
  sourceNote?: string; anchorSource?: AnchorHeight;
}
export interface SceneCapabilities {
  storageScope: SceneScope; supportsGeographic: boolean; supportsEngineeringBindings: false;
  maxInstances: number; maxSnapshotBytes: number; maxCheckJsonBytes: number;
  scope: SceneScope; localPlaneUnbound: true; canRead: true; canWrite: boolean;
  existingUploadedModelVersionsOnly: true; projectModelResources: true; canPreflightGeographic: boolean;
}
export interface SceneLimits {
  maxSaveJsonBytes: number; maxReadJsonBytes: number; maxCheckJsonBytes: number;
  maxInstances: number; maxComponentBindings: 0; maxNameCharacters: number; maxLocalCoordinateM: number;
}
export interface SceneResponse {sessionRevision: string; projectName?: string; capabilities: SceneCapabilities; limits: SceneLimits}
export interface SceneSummary {
  sceneId: string; displayName: string; headRevision: string; updatedAt: string; instanceCount: number;
}
export interface SceneList extends SceneResponse {items: SceneSummary[]; snapshotRevision: string; nextCursor: string | null}
export interface SceneListRequest {q?: string; cursor?: string | null; limit?: number}
export interface SceneCreateRequest {displayName: string; clientRequestId: string}
export interface SceneOpen extends SceneResponse {
  sceneId: string; projectCode: string; sceneRevision: string; headRevision: string; savedAt: string;
  snapshot: EditableSceneSnapshot; resourceRefs: ModelResourceRef[]; validation: GeometryValidation;
  heightProvenance?: HeightProvenance[]; terrainRefs?: TerrainResourceRef[];
}
export interface SceneHead extends SceneResponse {sceneId: string; headRevision: string; updateAvailable: boolean}
export interface SpatialChange {kind: 'anchor'; receipt: string}
export interface SceneSaveRequest {
  sceneId: string; expectedSceneRevision: string; clientRequestId: string; snapshot: EditableSceneSnapshot;
  reviewedEngineering: never[]; rootBindingChanges: never[]; spatialChange?: SpatialChange;
}
export interface SceneSave extends SceneResponse {
  sceneId: string; sceneRevision: string; headRevision: string; savedAt: string;
  validation: GeometryValidation; heightProvenance?: HeightProvenance[]; terrainRefs?: TerrainResourceRef[];
}
interface SceneCheckBase {sceneId: string; expectedSceneRevision: string; snapshot: EditableSceneSnapshot}
export type SceneCheckRequest = (SceneCheckBase & {kind: 'validate'}) | (
  Omit<SceneCheckBase, 'snapshot'> & {kind: 'anchor'; snapshot: LocalSceneSnapshot;
    candidateTerrainVersionId: string; anchor: GeographicAnchor}
);
export interface SceneCheck extends SceneResponse {
  sceneId: string; baseSceneRevision: string; proposedSnapshot: EditableSceneSnapshot;
  validation: GeometryValidation; heightProvenance: HeightProvenance[];
  resourceRefs: ResourceRefs; spatialChange: SpatialChange | null;
}
