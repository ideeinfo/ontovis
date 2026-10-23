import type {Bounds3, KnownVerticalDatum, Vector3, VerticalDatum} from './sceneTypes';

export type ModelPurpose = 'equipment' | 'simplified_scene' | 'environment';
export interface ModelCalibrationInput {
  unit: 'm'; axes: 'Y_UP_RIGHT_HANDED'; basePoint: Vector3; forward: Vector3;
}
export type Matrix4 = [number, number, number, number, number, number, number, number,
  number, number, number, number, number, number, number, number];
export interface VerifiedModelCalibration extends ModelCalibrationInput {
  state: 'verified'; modelToCalibrated: Matrix4; verifiedBy: string; verifiedAt: string;
}
export interface LegacyDisplayCalibration {
  state: 'legacy_display'; unit: 'm'; axes: 'Y_UP_RIGHT_HANDED'; modelToCalibrated: Matrix4;
  sourceModelVersionId: string; sourceSha256: string; sourceNote: string; preservedBy: string; preservedAt: string;
}
export interface ProjectModelComponent {
  componentKey: string; displayName: string; nodeIndices: number[]; keyStability: 'version_local';
  geometryQuality: 'source_candidate' | 'proxy_schematic'; bounds: Bounds3;
}
export interface ProjectModelReport {
  bytes: number; nodes: number; activeMeshInstances: number; triangles: number;
  bounds: {min: Vector3; max: Vector3; basis: string}; coordinateConvention: string; animations: 0;
  images: number; texturePixels: number; externalResourcesFetched: 0; sourceIdentityVerified: false;
  coordinateVerification: 'unverified' | 'operator_calibrated' | 'legacy_display_preserved';
  calibrationVerification?: {method: 'm-y-up-forward-negative-z-v1'; calibratedBounds: Bounds3};
}
export interface ProjectModelVersion {
  modelAssetId: string; modelVersionId: string; contentRevision: string; displayName: string;
  sourceNote: string; sha256: string; bytes: number; createdAt: string; state: 'ready';
  calibration: {state: 'unverified'} | VerifiedModelCalibration | LegacyDisplayCalibration;
  calibrationState: 'unverified' | 'verified' | 'legacy_display'; canPlace: boolean; canPlaceGeographic: boolean;
  report: ProjectModelReport; components: ProjectModelComponent[]; sourceModelVersionId: string | null;
}
export type ProjectModelVersionSummary = Omit<ProjectModelVersion, 'report' | 'components' | 'calibration' | 'sourceNote'>;
export interface ProjectModelAsset {
  modelAssetId: string; displayName: string; purpose: ModelPurpose; assetRevision: string;
  versions: ProjectModelVersionSummary[];
}
export interface ResourceCapabilities {
  scope: 'project_static_glb_resources'; canRead: true; canUpload: boolean; canCalibrate: boolean;
  calibrationRequiredForGeographicPlacement: true; automaticLegacyAdoption: false;
}
export interface ResourceLimits {
  maxUploadBytes: number; maxVersions: number; maxLibraryBytes: number;
  maxMetadataHeaderBytes: number; maxMetadataJsonBytes: number; maxJsonBytes: number;
}
export interface ResourceResponse {sessionRevision: string; capabilities: ResourceCapabilities; limits: ResourceLimits}
export interface ProjectModelCatalog extends ResourceResponse {
  items: ProjectModelAsset[]; libraryRevision: string; nextCursor: string | null;
}
export interface LegacyModelCandidate {
  modelVersionId: string; displayName: string; modelRevision: number; sourceNote: string;
  sha256: string; bytes: number; legacyBindingCount: number;
  calibrationState: 'legacy_unverified'; canPlace: false; sourceRightsDeclared: boolean; canImport: boolean;
  importedResource?: {modelAssetId: string; modelVersionId: string};
}
export interface LegacyModelCatalog extends ResourceResponse {
  adoptionPerformed: false; libraryRevision: string; items: LegacyModelCandidate[];
}
export interface ImportExistingModelRequest {
  legacyModelVersionId: string; expectedModelRevision: number; expectedSha256: string;
  expectedLibraryRevision: string; purpose: ModelPurpose; clientRequestId: string;
}
export interface ProjectModelsRequest {q?: string; purpose?: ModelPurpose; cursor?: string | null; expectedLibraryRevision?: string; limit?: number}
export type ProjectModel = ProjectModelVersion & ResourceResponse;
export type ProjectModelWrite = ProjectModel & {libraryRevision: string; assetRevision: string};
export interface UploadModelMetadata {
  expectedLibraryRevision: string; clientRequestId: string; displayName: string; purpose: ModelPurpose;
  sourceNote: string; rightsDeclared: true; modelAssetId?: string;
}
export interface CalibrateModelRequest {
  modelVersionId: string; expectedContentRevision: string; expectedLibraryRevision: string;
  calibration: ModelCalibrationInput; clientRequestId: string;
}
export type ResourceUseScope = 'current' | 'retained' | 'current_or_retained';
export interface ModelUsesRequest {versionId: string; scope?: ResourceUseScope; cursor?: string | null; limit?: number}
export interface ModelUseCounts {currentInstanceCount: number; retainedInstanceCount: number; retainedReferenceCount: number}
export interface ModelUses extends ResourceResponse, ModelUseCounts {
  versionId: string; items: (ModelUseCounts & {sceneId: string; displayName: string})[];
  nextCursor: string | null; snapshotRevision: string;
}

export type TerrainArtifactId = 'source.tif' | 'heights.f64' | 'mask.u8' | 'cells.u8' | 'positions.f32' | 'triangles.u32';
export interface TerrainArtifact {
  artifactId: TerrainArtifactId; bytes: number; sha256: string;
  format?: 'geotiff' | 'float64_le' | 'uint8' | 'float32_le' | 'uint32_le';
}
export type BoundsWgs84 = [number, number, number, number];
interface TerrainUploadBase {
  clientRequestId: string; displayName: string; sourceNote: string; licenseNote: string;
  rightsDeclared: true; heightUnit: 'm'; aoi?: BoundsWgs84;
}
export type UploadTerrainMetadata = TerrainUploadBase & (
  {verticalDatum: KnownVerticalDatum; relativeReferenceId?: null} |
  {verticalDatum: 'UNKNOWN_RELATIVE'; relativeReferenceId: string}
);
export interface TerrainCapabilities {
  scope: 'private_geotiff_processing'; canRead: true; canUpload: boolean; canCancel: boolean; sceneTerrainPlacement: boolean;
}
export interface TerrainLimits extends ResourceLimits {
  maxPixels: number; maxTriangles: number; maxPendingJobs: number; processingTimeoutSeconds: number;
}
export interface TerrainResponse {sessionRevision: string; capabilities: TerrainCapabilities; limits: TerrainLimits}
export interface TerrainJob extends TerrainResponse {
  jobId: string; jobRevision: string; state: 'queued' | 'processing' | 'ready' | 'failed' | 'cancelled';
  displayName: string; createdAt: string; updatedAt: string; terrainVersionId: string | null; errorCode: string | null;
}
export interface CancelTerrainRequest {jobId: string; expectedJobRevision: string; clientRequestId: string}
export interface TerrainSourceReport {
  sha256: string; bytes: number; width: number; height: number; bands: 1; dtype: string;
  horizontalCrs: string; horizontalCrsWkt: string; pixelCornerAffine: [number, number, number, number, number, number];
  areaOrPoint: string; heightUnit: 'm'; scale: number; offset: number; verticalDatum: VerticalDatum;
  embeddedVerticalDatums: VerticalDatum[]; verticalDeclarationSource: 'embedded_and_operator' | 'operator_source_evidence';
  relativeReferenceId: string | null; sourceNote: string; licenseNote: string;
  samplingCentreCoverageWgs84: BoundsWgs84; requestedAoiWgs84: BoundsWgs84 | null;
  validPixels: number; missingPixels: number; heightRangeM: [number, number];
}
export interface TerrainFrame {
  mode: 'projected_site'; frameRevision: string; horizontalCrs: string; horizontalCrsWkt: string;
  verticalDatum: VerticalDatum; transformId: string; convergenceRuleId: string;
  originEasting: number; originNorthing: number; originHeight: number; maxRadiusM: number;
  displayAxes: 'X_GRID_EAST_Y_UP_Z_GRID_SOUTH'; isStrictEnu: false;
}
export interface TerrainMeshReport {
  rows: number; columns: number; eastingMinM: number; northingMaxM: number; stepEastingM: number; stepNorthingM: number;
  vertices: number; validVertices: number; triangles: number; validCells: number; cellCoverageRule: string;
  sourceVertexSamplingRule: string; placementSamplingRule: string; placementCoordinatePrecision: 'fixed_display_float32_vertices';
  displayContactMaxErrorM: number; sourceSurfaceApproximationErrorM: null;
  sourceSurfaceApproximationStatus: 'not_measured_not_a_field_accuracy_claim'; heightExaggeration: 1; frame: TerrainFrame;
}
export interface TerrainReport {
  schemaVersion: 1; state: 'ready'; source: TerrainSourceReport; mesh: TerrainMeshReport; artifacts: TerrainArtifact[];
  externalResourcesFetched: 0; verticalConversionApplied: false; fieldAccuracyVerified: false;
  limits: {maxBytes: number; maxPixels: number; maxTriangles: number; maxGridSide: number};
}
export interface TerrainVersion extends TerrainResponse {
  terrainVersionId: string; contentRevision: string; displayName: string; sha256: string;
  expectedReportSha256: string; state: 'ready'; createdAt: string; report: TerrainReport; artifacts: TerrainArtifact[];
}
export interface TerrainSummary {
  terrainVersionId: string; contentRevision: string; displayName: string; sha256: string; createdAt: string;
  sourceHorizontalCrs: string | null; verticalDatum: VerticalDatum | null; coverageWgs84: BoundsWgs84 | null;
}
export interface TerrainsRequest {q?: string; cursor?: string | null; limit?: number}
export interface TerrainCatalog extends TerrainResponse {
  items: TerrainSummary[]; nextCursor: string | null; snapshotRevision: string;
}

export interface UploadImageryMetadata {
  clientRequestId:string;displayName:string;sourceNote:string;licenseNote:string;attribution:string;
  acquiredAt:string;qualityNote:string;rightsDeclared:true;
}
export interface ImageryReport {
  schemaVersion:1;purpose:'overview';width:number;height:number;bands:3|4;dtype:'uint8';horizontalCrs:string;
  pixelCornerAffine:[number,number,number,number,number,number];pixelSize:[number,number];coverageWgs84:BoundsWgs84;
  validPixels:number;transparentPixels:number;fieldAccuracyVerified:false;externalResourcesFetched:0;heightDataUsed:false;
}
export interface ImageryRecord {
  imageryVersionId:string;contentRevision:string;displayName:string;sha256:string;expectedReportSha256:string;createdAt:string;
  metadata:UploadImageryMetadata;report:ImageryReport;texture:{bytes:number;sha256:string;mediaType:'image/png'};
}
export interface ImageryResponse {
  sessionRevision:string;capabilities:{scope:'private_overview_imagery';canRead:true;canUpload:boolean};
  limits:{maxUploadBytes:number;maxSide:number;maxVersions:number;maxLibraryBytes:number};
}
export type ImageryVersion=ImageryRecord&ImageryResponse;
export interface ImageryCatalog extends ImageryResponse {items:ImageryRecord[]}
