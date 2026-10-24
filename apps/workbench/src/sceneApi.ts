import type {ModelResourceMetadata} from './modelResourceMetadata';
import {ApiError, type WorkbenchApi} from './api.ts';
import type {SceneCheck, SceneCheckRequest, SceneCreateRequest, SceneHead, SceneList, SceneListRequest,
  SceneOpen, SceneReplacementCheckRequest, SceneSave, SceneSaveRequest, LegacySceneEntry, LegacySceneEntryRequest} from './sceneTypes';
import type {CalibrateModelRequest, CancelTerrainRequest, ImportExistingModelRequest, LegacyModelCatalog, ModelThumbnailInfo, ModelThumbnailReference, ModelUses, ModelUsesRequest,
  ProjectModel, ProjectModelCatalog, ProjectModelsRequest, ProjectModelVersion, ProjectModelWrite,
  TerrainArtifact, TerrainCatalog, TerrainJob, TerrainsRequest, TerrainVersion, UploadModelMetadata, UploadTerrainMetadata} from './resourceTypes';

import type {SceneObjectChildren, SceneObjectContext, SceneObjectDetailRequest, SceneLocation, SceneLocationRequest} from './sceneEngineeringTypes';
import type {ImageryCatalog, ImageryRecord, ImageryUploadResult, ImageryVersion, UploadImageryMetadata} from './resourceTypes';

const ROOT = '/api/workbench/';

/** Fixed scene/resource paths over the existing session and cancellation boundary. */
export class SceneApi {
  private readonly api: WorkbenchApi;
  constructor(api: WorkbenchApi) {this.api = api;}

  imagery(q='',signal?:AbortSignal) {return this.api.request<ImageryCatalog>(ROOT+'imagery',{q},signal);}
  imageryVersion(imageryVersionId:string,signal?:AbortSignal) {return this.api.request<ImageryVersion>(ROOT+'imagery/version',{imageryVersionId},signal);}
  uploadImagery(file:Blob,metadata:UploadImageryMetadata,signal?:AbortSignal) {return this.api.uploadImagery<ImageryVersion>(file,metadata,signal);}
  imageryUploadResult(metadata:UploadImageryMetadata,expectedSourceSha256:string,signal?:AbortSignal) {
    return this.api.request<ImageryUploadResult>(ROOT+'imagery/upload-result',{metadata,expectedSourceSha256},signal);
  }
  imageryContent(value:ImageryRecord,signal?:AbortSignal) {
    return this.api.content(ROOT+'imagery/content',{imageryVersionId:value.imageryVersionId,
      expectedContentRevision:value.contentRevision,expectedSha256:value.texture.sha256},
      {mime:'image/png',maxBytes:value.texture.bytes,sha256:value.texture.sha256},signal);
  }

  list(options: SceneListRequest = {}, signal?: AbortSignal) {
    return this.api.request<SceneList>(ROOT + 'scenes', options, signal);
  }
  create(body: SceneCreateRequest, signal?: AbortSignal) {
    return this.api.request<SceneOpen>(ROOT + 'scenes/create', body, signal);
  }
  open(sceneId: string, sceneRevision?: string, signal?: AbortSignal) {
    return this.api.request<SceneOpen>(ROOT + 'scenes/open',
      {sceneId, ...(sceneRevision === undefined ? {} : {sceneRevision})}, signal);
  }
  legacyEntry(body:LegacySceneEntryRequest = {}, signal?:AbortSignal) {
    return this.api.request<LegacySceneEntry>(ROOT+'scenes/legacy-migration/entry',body,signal);
  }
  head(sceneId: string, viewingRevision: string, signal?: AbortSignal) {
    return this.api.request<SceneHead>(ROOT + 'scenes/head', {sceneId, viewingRevision}, signal);
  }
  check(body: SceneCheckRequest, signal?: AbortSignal) {
    return this.api.request<SceneCheck>(ROOT + 'scenes/check', {...body,environmentWriteVersion:1,sceneInfoWriteVersion:1}, signal);
  }
  replacementCheck(body: SceneReplacementCheckRequest, signal?: AbortSignal) {
    return this.api.request<SceneCheck>(ROOT + 'scenes/replacement-check', {...body,environmentWriteVersion:1,sceneInfoWriteVersion:1}, signal);
  }
  save(body: SceneSaveRequest, signal?: AbortSignal) {
    return this.api.request<SceneSave>(ROOT + 'scenes/save', {...body,environmentWriteVersion:1,sceneInfoWriteVersion:1}, signal);
  }
  locate(body:SceneLocationRequest, signal?:AbortSignal) {
    return this.api.request<SceneLocation&{sessionRevision:string}>(ROOT+'scenes/locate',body,signal);
  }
  objectContext(entityUid:string, expectedEntityRevision?:string, signal?:AbortSignal) {
    return this.api.request<SceneObjectContext>(ROOT+'objects/context',
      {entityUid,...(expectedEntityRevision===undefined?{}:{expectedEntityRevision})},signal);
  }
  objectDetail(body:SceneObjectDetailRequest, signal?:AbortSignal) {
    return this.api.request<SceneObjectContext>(ROOT+'objects/detail',body,signal);
  }
  objectChildren(body:Omit<SceneObjectDetailRequest,'expectedEntityRevision'|'installationContextId'|'expectedHierarchyRevision'>&
    {installationContextId:string;expectedHierarchyRevision:string;cursor?:string|null}, signal?:AbortSignal) {
    return this.api.request<SceneObjectChildren>(ROOT+'objects/children',body,signal);
  }
  models(options: ProjectModelsRequest = {}, signal?: AbortSignal) {
    return this.api.request<ProjectModelCatalog>(ROOT + 'resources/models', options, signal);
  }
  legacyModels(signal?: AbortSignal) {
    return this.api.request<LegacyModelCatalog>(ROOT + 'resources/models/legacy', {}, signal);
  }
  importExistingModel(body: ImportExistingModelRequest, signal?: AbortSignal) {
    return this.api.request<ProjectModelWrite>(ROOT + 'resources/model/import-existing', body, signal);
  }
  model(modelAssetId: string, modelVersionId: string, signal?: AbortSignal) {
    return this.api.request<ProjectModel>(ROOT + 'resources/model', {modelAssetId, modelVersionId}, signal);
  }
  modelContent(version: Pick<ProjectModelVersion, 'modelVersionId' | 'contentRevision' | 'sha256' | 'bytes'>, signal?: AbortSignal) {
    return this.api.content(ROOT + 'resources/model/content', {modelVersionId: version.modelVersionId,
      expectedContentRevision: version.contentRevision, expectedSha256: version.sha256},
    {mime:'model/gltf-binary', maxBytes:version.bytes, sha256:version.sha256}, signal);
  }
  uploadModel(file: Blob, metadata: UploadModelMetadata, signal?: AbortSignal) {
    return this.api.uploadModel<ProjectModelWrite>(file, metadata, signal);
  }
  calibrateModel(body: CalibrateModelRequest, signal?: AbortSignal) {
    return this.api.request<ProjectModelWrite>(ROOT + 'resources/model/calibrate', body, signal);
  }
  modelMetadata(modelAssetId:string,modelVersionId:string,signal?:AbortSignal) {
    return this.api.request<{item:ModelResourceMetadata|null;sessionRevision:string}>(ROOT+'resources/model/metadata',
      {modelAssetId,modelVersionId},signal);
  }
  modelThumbnail(version:ModelThumbnailReference,signal?:AbortSignal) {
    return this.api.request<{thumbnail:ModelThumbnailInfo}>(ROOT+'resources/model/thumbnail',
      {modelVersionId:version.modelVersionId,expectedContentRevision:version.contentRevision,expectedSha256:version.sha256},signal);
  }
  ensureModelThumbnail(version:ModelThumbnailReference,expectedThumbnailRevision:string|null,clientRequestId:string,signal?:AbortSignal) {
    return this.api.request<{thumbnail:ModelThumbnailInfo}>(ROOT+'resources/model/thumbnail/ensure',
      {modelVersionId:version.modelVersionId,expectedContentRevision:version.contentRevision,expectedSha256:version.sha256,
        expectedThumbnailRevision,clientRequestId},signal);
  }
  modelThumbnailContent(version:ModelThumbnailReference,thumbnail:ModelThumbnailInfo,signal?:AbortSignal) {
    return this.api.content(ROOT+'resources/model/thumbnail/content',
      {modelVersionId:version.modelVersionId,expectedContentRevision:version.contentRevision,expectedSha256:version.sha256,
        expectedThumbnailRevision:thumbnail.thumbnailRevision,expectedImageSha256:thumbnail.imageSha256},
      {mime:'image/png',maxBytes:384*1024,sha256:thumbnail.imageSha256||''},signal);
  }
  modelUses(body: ModelUsesRequest, signal?: AbortSignal) {
    return this.api.request<ModelUses>(ROOT + 'resources/uses', {...body, resourceKind:'model'}, signal);
  }
  uploadTerrain(file: Blob, metadata: UploadTerrainMetadata, signal?: AbortSignal) {
    return this.api.uploadTerrain<TerrainJob>(file, metadata, signal);
  }
  terrains(options: TerrainsRequest = {}, signal?: AbortSignal) {
    return this.api.request<TerrainCatalog>(ROOT + 'terrains', options, signal);
  }
  job(jobId: string, signal?: AbortSignal) {
    return this.api.request<TerrainJob>(ROOT + 'terrains/job', {jobId}, signal);
  }
  cancelTerrain(body: CancelTerrainRequest, signal?: AbortSignal) {
    return this.api.request<TerrainJob>(ROOT + 'terrains/job/cancel', body, signal);
  }
  version(terrainVersionId: string, signal?: AbortSignal) {
    return this.api.request<TerrainVersion>(ROOT + 'terrains/version', {terrainVersionId}, signal);
  }
  content(terrainVersionId: string, artifact: TerrainArtifact, signal?: AbortSignal) {
    const maximum = (artifact.artifactId === 'source.tif' ? 256 : 16) * 1024 * 1024;
    if (!Number.isSafeInteger(artifact.bytes) || artifact.bytes <= 0 || artifact.bytes > maximum) {
      return Promise.reject(new ApiError(413, 'TERRAIN_LIMIT_EXCEEDED'));
    }
    return this.api.content(ROOT + 'terrains/content',
      {terrainVersionId, artifactId: artifact.artifactId, expectedSha256: artifact.sha256},
      {mime:'application/octet-stream', maxBytes:artifact.bytes, sha256:artifact.sha256}, signal);
  }
}
