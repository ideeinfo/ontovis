import type {ProjectRef} from './projectTypes';

export class ApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string) {
    super(code); this.status = status; this.code = code;
  }
}

export interface BinaryDescriptor {
  mime: 'model/gltf-binary' | 'application/octet-stream' | 'image/png' | readonly ('image/png'|'image/jpeg'|'image/webp')[]; maxBytes: number; sha256: string;
}
type UploadKind = 'legacyModel' | 'projectModel' | 'terrain' | 'imagery' | 'imageryChunk';
const MIB = 1024 * 1024;
const writeOnlyDenials: Record<string, readonly string[]> = {
  ANALYSIS_WRITE_FORBIDDEN: ['/api/workbench/analysis-sessions/import-history','/api/workbench/analysis-sessions/evidence/register-batch','/api/workbench/analysis-sessions/start', '/api/workbench/analysis-sessions/copy', '/api/workbench/analysis-sessions/create', '/api/workbench/analysis-sessions/save', '/api/workbench/analysis-sessions/restore', '/api/workbench/analysis-sessions/evidence/register', '/api/workbench/analysis-sessions/link-work-order'],
  WORK_ORDER_WRITE_FORBIDDEN: ['/api/workbench/work-orders/seed-demo', '/api/workbench/work-orders/action'],
  IMAGERY_WRITE_FORBIDDEN:['/api/workbench/imagery/upload','/api/workbench/imagery/uploads/start',
    '/api/workbench/imagery/uploads/chunk','/api/workbench/imagery/uploads/complete','/api/workbench/imagery/uploads/cancel'],
  MODEL_WRITE_FORBIDDEN: ['/api/workbench/models/upload', '/api/workbench/models/binding',
    '/api/workbench/resources/model/upload', '/api/workbench/resources/model/calibrate',
    '/api/workbench/resources/model/delete', '/api/workbench/resources/model/restore',
    '/api/workbench/resources/model/import-existing', '/api/workbench/resources/model/info/save', '/api/workbench/resources/model/thumbnail/ensure', '/api/workbench/resources/model/metadata/save', '/api/workbench/resources/model/preserve-legacy-display'],
  SCENE_WRITE_FORBIDDEN: ['/api/workbench/scenes/create', '/api/workbench/scenes/save',
    '/api/workbench/scenes/delete', '/api/workbench/scenes/restore',
    '/api/workbench/terrains/upload', '/api/workbench/terrains/job/cancel',
    '/api/workbench/public-geodata/start', '/api/workbench/public-geodata/cancel'],
};

async function binaryResponse(response: Response, descriptor: BinaryDescriptor, revision: string, guard: () => void, verifyDigest=true) {
  const refuse = async (status: number, code: string): Promise<never> => {
    await response.body?.cancel().catch(() => {});
    throw new ApiError(status, code);
  };
  const mime = response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase() || '';
  const allowed = typeof descriptor.mime === 'string' ? [descriptor.mime] : descriptor.mime;
  if (response.headers.get('X-Session-Revision') !== revision || !(allowed as readonly string[]).includes(mime)) {
    return refuse(502, 'SOURCE_UNAVAILABLE');
  }
  if (response.headers.get('X-Content-SHA256') !== descriptor.sha256) return refuse(409, 'RESOURCE_CHANGED');
  const length = response.headers.get('Content-Length');
  const expectedLength = length === null ? null : /^\d+$/.test(length) ? Number(length) : NaN;
  if (expectedLength !== null && (!Number.isSafeInteger(expectedLength) || expectedLength < 0)) {
    return refuse(502, 'SOURCE_UNAVAILABLE');
  }
  if (expectedLength !== null && expectedLength > descriptor.maxBytes) return refuse(413, 'CONTENT_LIMIT_EXCEEDED');
  let blob: Blob;
  if (response.body) {
    const reader = response.body.getReader();
    const chunks: ArrayBuffer[] = [];
    let bytes = 0;
    try {
      while (true) {
        const next = await reader.read(); guard();
        if (next.done) break;
        bytes += next.value.byteLength;
        if (bytes > descriptor.maxBytes) throw new ApiError(413, 'CONTENT_LIMIT_EXCEEDED');
        chunks.push(new Uint8Array(next.value).buffer);
      }
    } catch (error) {
      await reader.cancel().catch(() => {});
      throw error;
    } finally { reader.releaseLock(); }
    blob = new Blob(chunks, {type: mime});
  } else {
    blob = await response.blob();
  }
  guard();
  if (blob.size > descriptor.maxBytes) throw new ApiError(413, 'CONTENT_LIMIT_EXCEEDED');
  if (blob.type !== mime || expectedLength !== null && blob.size !== expectedLength) throw new ApiError(502, 'SOURCE_UNAVAILABLE');
  if(verifyDigest){
    const bytes = await blob.arrayBuffer(); guard();
    const digest = await crypto.subtle.digest('SHA-256', bytes); guard();
    const sha256 = Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join('');
    if (sha256 !== descriptor.sha256) throw new ApiError(409, 'RESOURCE_CHANGED');
  }
  return blob;
}

export class WorkbenchApi {
  revision = '';
  epoch = 0;
  onDenied: (status: number) => void = () => {};
  onProjectDenied: () => void = () => {};
  project: ProjectRef|null = null;
  selectProject(value:ProjectRef|null) {this.invalidate();this.project=value;}
  transport: typeof fetch;
  constructor(transport: typeof fetch = (input, init) => fetch(input, init)) { this.transport = transport; }
  invalidate() { this.epoch += 1; }
  session(revision: string) { this.invalidate(); this.revision = revision; }

  upload<T>(file:Blob, metadata:object, signal?:AbortSignal) {
    return this.send<T>('/api/workbench/models/upload', metadata, signal, false, {file, kind:'legacyModel'});
  }

  uploadModel<T>(file: Blob, metadata: object, signal?: AbortSignal) {
    return this.send<T>('/api/workbench/resources/model/upload', metadata, signal, false, {file, kind:'projectModel'});
  }

  uploadImageryChunk<T>(file:Blob,metadata:object,signal?:AbortSignal) {
    return this.send<T>('/api/workbench/imagery/uploads/chunk',metadata,signal,false,{file,kind:'imageryChunk'});
  }

  uploadTerrain<T>(file: Blob, metadata: object, signal?: AbortSignal) {
    return this.send<T>('/api/workbench/terrains/upload', metadata, signal, false, {file, kind:'terrain'});
  }

  uploadImagery<T>(file:Blob,metadata:object,signal?:AbortSignal) {
    return this.send<T>('/api/workbench/imagery/upload',metadata,signal,false,{file,kind:'imagery'});
  }

  content(path: string, body: object, descriptor: BinaryDescriptor, signal?: AbortSignal): Promise<Blob> {
    const photoSet = Array.isArray(descriptor.mime) && descriptor.mime.length > 0 && descriptor.mime.length <= 3
      && descriptor.mime.every(mime => ['image/png','image/jpeg','image/webp'].includes(mime));
    if (!(typeof descriptor.mime === 'string' && ['model/gltf-binary','application/octet-stream','image/png'].includes(descriptor.mime) || photoSet)
        || !Number.isSafeInteger(descriptor.maxBytes) || descriptor.maxBytes <= 0
        || descriptor.maxBytes > (photoSet || descriptor.mime === 'model/gltf-binary' ? 20 : descriptor.mime === 'image/png' ? 64 : 256) * MIB
        || !/^[a-f0-9]{64}$/.test(descriptor.sha256)) {
      return Promise.reject(new ApiError(422, 'INVALID_REQUEST'));
    }
    return this.send<Blob>(path, body, signal, descriptor);
  }

  async request<T>(path: string, body?: object, signal?: AbortSignal, image: boolean | 'model' | 'source' = false, upload?:Blob): Promise<T> {
    return this.send<T>(path, body, signal, image, upload ? {file:upload, kind:'legacyModel'} : undefined);
  }

  private async send<T>(path: string, body?: object, signal?: AbortSignal,
    image: boolean | 'model' | 'source' | BinaryDescriptor = false, upload?: {file: Blob; kind: UploadKind}): Promise<T> {
    const epoch = this.epoch, revision = this.revision,project=this.project?{...this.project}:null;
    const guard = () => {
      if (epoch !== this.epoch || revision !== this.revision || signal?.aborted) {
        throw new DOMException('Selection or session changed', 'AbortError');
      }
    };
    guard();
    const sharedModels=path.startsWith('/api/workbench/resources/model');
    const scoped=path.startsWith('/api/workbench/')&&!path.startsWith('/api/workbench/projects')&&!sharedModels;
    const json = body ? JSON.stringify({...body,...(scoped&&project?{projectRef:project}:{}), expectedSessionRevision: revision}) : undefined;
    const headers:Record<string,string> = body ? {'Content-Type':'application/json'} : {};
    if (upload) {
      const chunk = upload.kind === 'imageryChunk';
      const imagery = upload.kind === 'imagery'||chunk,terrain = upload.kind === 'terrain'||imagery;
      if (upload.kind !== 'legacyModel' && (!Number.isSafeInteger(upload.file.size)
          || upload.file.size < (chunk ? 1 : terrain ? 8 : 24) || upload.file.size > (chunk ? MIB/4 : (imagery ? 64 : terrain ? 256 : 20) * MIB))) {
        throw new ApiError(413, imagery ? 'IMAGERY_LIMIT_EXCEEDED' : terrain ? 'TERRAIN_LIMIT_EXCEEDED' : 'MODEL_LIMIT_EXCEEDED');
      }
      const metadata = new TextEncoder().encode(json!);
      if (metadata.length > (chunk ? 3072 : 6144)) throw new ApiError(413, 'INVALID_REQUEST');
      headers['Content-Type'] = chunk ? 'application/octet-stream' : terrain ? 'image/tiff' : 'model/gltf-binary';
      headers[chunk ? 'X-Imagery-Chunk' : imagery ? 'X-Imagery-Metadata' : terrain ? 'X-Terrain-Metadata' : 'X-Model-Metadata'] = btoa(String.fromCharCode(...metadata));
    }
    const response = await this.transport(path, {method: body ? 'POST' : 'GET', credentials: 'same-origin',
      cache: 'no-store', signal, headers, body:upload?.file || json});
    guard();
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      guard();
      const code = data && typeof data.code === 'string' ? data.code : 'SOURCE_UNAVAILABLE';
      const writeDenied = response.status === 403 && Object.hasOwn(writeOnlyDenials, code)
        && writeOnlyDenials[code].includes(path);
      if(response.status===403&&(path.startsWith('/api/workbench/projects')||sharedModels||path==='/api/workbench/resources/uses')){/* Resource/project access failures keep the authenticated identity. */}
      else if(response.status===403&&!writeDenied&&scoped&&project){this.invalidate();this.onProjectDenied();}
      else if (response.status === 401 || response.status === 403 && !writeDenied) {
        this.invalidate(); this.onDenied(response.status);
      }
      throw new ApiError(response.status, code);
    }
    // Fixed photo bytes are already verified by the same-origin server. Keep
    // revision/header/size checks, without copying and hashing the image again.
    if (typeof image === 'object') return await binaryResponse(response, image, revision, guard,
      path!=='/api/workbench/objects/photos/content') as T;
    if (image) {
      const blob = await response.blob();
      guard();
      if (response.headers.get('X-Session-Revision') !== revision || (image==='source'?!['image/png','image/jpeg','image/webp','model/gltf-binary'].includes(blob.type):blob.type !== (image === 'model' ? 'model/gltf-binary' : 'image/png'))
          || blob.size > 20 * 1024 * 1024) throw new ApiError(502, 'SOURCE_UNAVAILABLE');
      return blob as T;
    }
    const data = await response.json();
    guard();
    if(scoped&&project&&data.projectRef&&(data.projectRef.ontobaseConnectionId!==project.ontobaseConnectionId||data.projectRef.projectCode!==project.projectCode))throw new ApiError(409,'PROJECT_SCOPE_MISMATCH');
    if (data.sessionRevision && path.startsWith('/api/workbench/') && data.sessionRevision !== revision) {
      throw new DOMException('Session changed', 'AbortError');
    }
    return data as T;
  }
}

export function failureMessage(error: unknown, locale = 'zh'): string {
  const modelErrors:Record<string,[string,string]> = {
    WORK_ORDER_WRITE_FORBIDDEN:['当前项目仅管理员可修改工单。','Only project administrators can update work orders.'],
    WORK_ORDER_CHANGED:['工单已变化，请重新读取后再操作。','This work order changed. Reload before continuing.'],
    WORK_ORDER_STATE_CONFLICT:['当前工单状态不允许此操作，请重新读取。','This action is not available in the current state. Reload.'],
    WORK_ORDER_CHECKS_REQUIRED:['请完成全部演示排查项，再提交或关闭。','Complete all exercise checks before submitting or closing.'],
    WORK_ORDER_DIAGNOSIS_REQUIRED:['请先保存逐项排查结果、结论和复核依据；支持或排除的原因也需要依据。','Save all step results, conclusion and review basis. Supported or rejected hypotheses also need a basis.'],
    WORK_ORDER_DIAGNOSIS_INVALID:['排查方案内容无效或超过上限，请检查后再保存。','The investigation plan is invalid or exceeds its limits.'],
    DEMO_TARGETS_UNAVAILABLE:['演示柜体身份需要重新核对，尚未生成工单。','The demo cabinet identities require review. No orders were created.'],
    WORK_ORDER_TARGET_CHANGED:['工单保留的柜体依据已变化，请重新核对。','The stored cabinet basis changed and requires review.'],
    DIAGNOSTIC_OBJECT_UNRESOLVED:['该完整主位号尚无唯一可读取对象，请核对项目定义和资料。','This full primary tag has no unique readable object. Review the project definition.'],
    CABINET_MEMBERSHIP_UNRESOLVED:['该对象尚未登记到所选柜体，请先在OntoBase核对归属。','This object has no recorded membership in the selected cabinet. Review it in OntoBase.'],
    PHOTO_SOURCE_UNAVAILABLE:['固定照片读取接口暂不可用，请稍后重新读取。','Fixed photo references are temporarily unavailable. Reload later.'],
    RENDITION_UNAVAILABLE:['该固定版本的照片显示或区域不可用，未替换为其他版本。','The fixed photo display or region is unavailable. No replacement was opened.'],
    PROJECT_REQUIRED:['请先选择所属项目。','Select a project first.'],
    PROJECT_SCOPE_MISMATCH:['项目范围不一致，请返回项目目录重新选择。','The project scope changed. Select the project again.'],
    WORKSPACE_SCOPE_INVALID:['项目存储归属需要核对，当前已停止写入。','The project storage scope requires review. Writes are blocked.'],
    SCENE_INFO_WRITE_VERSION_REQUIRED:['请刷新新版工作台，完整保留场景说明后再保存。','Reload the workbench to preserve the scene description before saving.'],
    LEGACY_SCENE_ENTRY_UNAVAILABLE:['原模型对应的场景暂不可用，请重新读取。','The scene for this legacy model is unavailable. Reload it.'],
    INVALID_MODEL:['模型结构不完整或已损坏，请检查文件。','The model is incomplete or damaged. Check the file.'],
    UNSUPPORTED_MODEL:['仅支持自包含静态 GLB，当前模型含未支持的资源或扩展。','Only self-contained static GLB is supported. This model uses unsupported resources or extensions.'],
    MODEL_LIMIT_EXCEEDED:['模型超过当前文件、几何或贴图处理限额。','The model exceeds file, geometry or texture limits.'],
    MODEL_LIBRARY_FULL:['模型库已达到当前容量限额。','The model library has reached its current capacity.'],
    MODEL_BUSY:['另一个模型正在校验，请稍后重试。','Another model is being validated. Retry shortly.'],
    MODEL_WRITE_FORBIDDEN:['需模型维护权限（现有项目管理员），仍可查看共享模型。','Model maintenance access (an existing project administrator) is required. Shared models remain readable.'],
    SHARED_MODEL_MIGRATION_REQUIRED:['发现旧项目模型库，请先核对并合并共享资源；原文件已保留。','A former project model library requires a reviewed shared-resource migration. Original files are retained.'],
    MODEL_RIGHTS_REQUIRED:['请确认你有权使用此模型。','Confirm that you have the right to use this model.'],
    COMPONENT_ALREADY_LINKED:['该构件已关联另一个柜体，请选择其他构件。','This component is already linked to another cabinet. Choose a different component.'],
    MODEL_LIBRARY_CHANGED:['模型库已变化，请刷新后重试。','The library changed. Refresh and retry.'],
    MODEL_DELETED:['模型已移至回收站，请先恢复后再新增使用。','This model is in the recycle bin. Restore it before adding new uses.'],
    MODEL_ASSET_CHANGED:['模型资源信息已变化，请重新读取。','The model resource changed. Reload it.'],
    MODEL_GEOGRAPHIC_CALIBRATION_REQUIRED:['沿用旧显示的模型仅可用于局部场景；地理布置请先校准。','Legacy display models are limited to local scenes. Calibrate before geographic placement.'],
    MODEL_CALIBRATION_REQUIRED:['请先核对模型单位、基点和正面朝向。','Verify the model units, base point and forward direction first.'],
    MODEL_STORAGE_UNAVAILABLE:['模型暂存或保存失败，请重试；不要重复创建版本。','Model storage failed. Retry the same request.'],
    SCENE_WRITE_FORBIDDEN:['当前仅可查看，未保存的修改仍保留。','You can currently view this scene. Unsaved edits are retained.'],
    SCENE_CHANGED:['场景已有新版本，保留当前修改后重新读取。','A newer scene exists. Keep your edits and reload before retrying.'],
    SCENE_DELETED:['场景已移到回收站，恢复后可继续查看和编辑。','This scene is in the recycle bin. Restore it to view or edit.'],
    INVALID_SCENE_ENVIRONMENT:['环境参数不符合范围，请检查后重试。','Check the environment parameter ranges and retry.'],
    UNSUPPORTED_SCENE_ENVIRONMENT:['当前版本不支持此环境配置，请更新工作台。','This environment configuration requires a newer workbench.'],
    WATER_SURFACE_NOT_SUPPORTED:['水面需要当前平坦的相对定位面，不能用于起伏地形或已知高程基准。','Water requires the active flat relative positioning surface.'],
    ENVIRONMENT_WRITE_VERSION_REQUIRED:['请刷新到新版工作台后保存环境配置。','Reload the updated workbench before saving environment settings.'],
    ENVIRONMENT_FIELD_REQUIRED:['环境配置未完整保留，请重新读取场景。','Reload the scene to preserve its environment settings.'],
    SURROUNDING_BACKGROUND_FIELD_REQUIRED:['外围背景配置未完整保留，请重新读取场景。','Reload the scene to preserve its surrounding background settings.'],
    CLOUD_FIELD_REQUIRED:['云层配置未完整保留，请重新读取场景。','Reload the scene to preserve its cloud settings.'],
    SNAPSHOT_EXPIRED:['列表已变化，请从第一页重新读取。','The list changed. Reload from the first page.'],
    REQUEST_CONFLICT:['该请求的内容已变化，请核对后重新操作。','This request was already used with different content. Review the change.'],
    RESOURCE_CHANGED:['资源内容或版本已变化，请重新核对。','The resource content or version changed. Review it again.'],
    SOURCE_MANAGED:['请在 OntoBase 管理设备采用和资料。','Manage equipment adoption and materials in OntoBase.'],
    SOURCE_APPLICATION_REQUIRED:['请先选择 OntoBase 项目采用，接续已有构件绑定。','Select an OntoBase project application before editing these bindings.'],
    SOURCE_APPLICATION_MISMATCH:['固定项目采用不一致，请保留原绑定并为新采用建立绑定。','The fixed project application differs. Keep the existing binding and create one for the new application.'],
    DEFINITION_NOT_IN_APPLICATION:['此对象或修订不属于当前项目采用，请在 OntoBase 核对角色。','This object or revision is outside the adopted application. Review its roles in OntoBase.'],
    APPLICATION_BINDING_EXISTS:['该项目采用已有构件绑定，请打开已有绑定。','This application already has a component binding. Open it instead.'],
    LEGACY_MAPPING_CHANGED:['首次接续须保留原构件映射，请先核对项目采用。','Keep the original component mappings when linking the source application.'],
    FRAME_CHANGED:['场景坐标已变化，请重新进行位置预览。','The scene coordinate frame changed. Preview the positions again.'],
    SPATIAL_PRECHECK_INVALID:['位置预览已失效，请重新预览后确认。','The position preview expired. Preview and confirm again.'],
    INSTANCE_POSITION_LOCKED:['请先解除该模型的位置锁定。','Unlock this model position first.'],
    INSTANCE_ID_REUSED:['此放置标识已使用，请重新添加模型。','This placement identifier was already used. Add the model again.'],
    DUPLICATE_INSTANCE:['场景含重复的放置，请重新添加副本。','The scene contains duplicate placements. Add the copy again.'],
    SCENE_SCOPE_UNSUPPORTED:['此操作尚未开放，当前修改未保存。','This operation is not available yet. Changes were not saved.'],
    SCENE_LIMIT_EXCEEDED:['场景超过当前数量或处理限额，请缩小范围。','The scene exceeds current size or processing limits. Reduce its scope.'],
    SCENE_GEOMETRY_BUSY:['另一项位置检查正在进行，请稍后重试。','Another position check is running. Retry shortly.'],
    INVALID_COORDINATE:['位置数值无效，请检查坐标和高度。','The position is invalid. Check its coordinates and height.'],
    OUTSIDE_COVERAGE:['该位置超出地形有效范围，请选择其他落点。','This position is outside the terrain coverage. Choose another point.'],
    OUTSIDE_PROJECTION_AREA:['该位置超出当前场景支持范围。','This position is outside the supported scene region.'],
    SCENE_DRAFT_REQUIRES_SAVE:['请先保存当前修改，再更换资源。','Save your current changes before replacing resources.'],
    NO_DATA:['该位置没有有效地形数据，请选择其他落点。','This position has no valid terrain data. Choose another point.'],
    TERRAIN_SAMPLE_CHANGED:['地面高度需重新核对，请重新预览位置。','The ground height needs checking. Preview the position again.'],
    VERTICAL_DATUM_CONFLICT:['高度基准不一致，请核对地形与场景声明。','Height references differ. Check the terrain and scene declarations.'],
    CRS_REQUIRED:['地形缺少坐标参考，请使用含明确坐标的文件。','The terrain has no coordinate reference. Use a referenced file.'],
    UNSUPPORTED_CRS:['此坐标参考暂不支持，请使用当前支持的区域数据。','This coordinate reference is not supported yet.'],
    UNSUPPORTED_TERRAIN:['仅支持当前范围内的单波段高程 GeoTIFF。','Only supported single-band elevation GeoTIFFs are accepted.'],
    INVALID_TERRAIN:['地形文件或处理结果无效，请检查文件。','The terrain file or processing result is invalid. Check the file.'],
    TERRAIN_LIMIT_EXCEEDED:['地形超过当前文件、像元或网格限额。','The terrain exceeds current file, pixel or mesh limits.'],
    TERRAIN_LIBRARY_FULL:['地形资源已达到容量限额。','The terrain library has reached its capacity.'],
    TERRAIN_RIGHTS_REQUIRED:['请确认你有权使用此地形资料。','Confirm that you have the right to use this terrain.'],
    TERRAIN_BUSY:['地形处理队列已满，请稍后重试。','The terrain processing queue is full. Retry shortly.'],
    JOB_CHANGED:['处理任务状态已变化，请重新读取。','The processing task changed. Reload its status.'],
    PROCESSING_INTERRUPTED:['处理已中断，请重新上传后再试。','Processing was interrupted. Upload again to retry.'],
    PROCESSING_FAILED:['地形处理失败，请检查文件与来源声明。','Terrain processing failed. Check the file and its source declaration.'],
    PROCESSING_UNAVAILABLE:['地形或位置处理暂不可用，请稍后重试。','Terrain or position processing is unavailable. Retry later.'],
    TRANSFORM_UNAVAILABLE:['当前坐标转换不可用，未更改场景。','The coordinate transformation is unavailable. The scene was not changed.'],
    TERRAIN_STORAGE_BUSY:['地形保存繁忙，请重新读取任务状态。','Terrain storage is busy. Reload the task status.'],
    TERRAIN_STORAGE_UNAVAILABLE:['地形保存暂不可用，请重新读取任务状态。','Terrain storage is unavailable. Reload the task status.'],
    CONTENT_LIMIT_EXCEEDED:['资源内容超过读取限额，未打开。','The resource exceeds its read limit and was not opened.'],
  };
  if (error instanceof ApiError && Object.hasOwn(modelErrors, error.code)) return modelErrors[error.code][locale === 'en' ? 1 : 0];
  if (locale === 'en') {
    if (error instanceof ApiError) {
      if (error.code === 'CREDENTIALS_REJECTED') return 'Incorrect username or password.';
      if (error.code === 'IMAGE_INVALID') return 'Drawing display incomplete. Retry.';
      if (error.status === 401) return 'Session expired. Sign in again.';
      if (error.status === 403) return 'Content unavailable or access denied.';
      if (error.code === 'SOURCE_MISSING') return 'Source unavailable. The reference is retained.';
      if (error.status === 409) return 'Object or source changed. Reload and select again.';
      if (error.status === 413) return 'Content exceeds this preview limit.';
    }
    return 'Read failed. Retry later.';
  }
  if (error instanceof ApiError) {
    if (error.code === 'CREDENTIALS_REJECTED') return '账号或密码不正确，请重新登录。';
    if (error.code === 'IMAGE_INVALID') return '图纸未完整显示，请重试。';
    if (error.status === 401) return '会话已失效，请重新登录。';
    if (error.status === 403) return '资料不可用或无权访问。';
    if (error.code === 'SOURCE_MISSING') return '原文暂不可用，保留资料引用。';
    if (error.status === 409) return '对象或来源版本已变化，请重新读取后选择。';
    if (error.status === 413) return '超过本次读取范围，未打开替代内容。';
  }
  return '读取失败，请稍后重试。';
}
export function cancelled(error: unknown) { return error instanceof DOMException && error.name === 'AbortError'; }
