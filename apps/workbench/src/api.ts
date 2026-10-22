export class ApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string) {
    super(code); this.status = status; this.code = code;
  }
}

export interface BinaryDescriptor {
  mime: 'model/gltf-binary' | 'application/octet-stream'; maxBytes: number; sha256: string;
}
type UploadKind = 'legacyModel' | 'projectModel' | 'terrain';
const MIB = 1024 * 1024;
const writeOnlyDenials: Record<string, readonly string[]> = {
  MODEL_WRITE_FORBIDDEN: ['/api/workbench/models/upload', '/api/workbench/models/binding',
    '/api/workbench/resources/model/upload', '/api/workbench/resources/model/calibrate',
    '/api/workbench/resources/model/import-existing'],
  SCENE_WRITE_FORBIDDEN: ['/api/workbench/scenes/create', '/api/workbench/scenes/save',
    '/api/workbench/terrains/upload', '/api/workbench/terrains/job/cancel'],
};

async function binaryResponse(response: Response, descriptor: BinaryDescriptor, revision: string, guard: () => void) {
  const refuse = async (status: number, code: string): Promise<never> => {
    await response.body?.cancel().catch(() => {});
    throw new ApiError(status, code);
  };
  if (response.headers.get('X-Session-Revision') !== revision
      || response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase() !== descriptor.mime) {
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
    blob = new Blob(chunks, {type: descriptor.mime});
  } else {
    blob = await response.blob();
  }
  guard();
  if (blob.size > descriptor.maxBytes) throw new ApiError(413, 'CONTENT_LIMIT_EXCEEDED');
  if (blob.type !== descriptor.mime || expectedLength !== null && blob.size !== expectedLength) throw new ApiError(502, 'SOURCE_UNAVAILABLE');
  const bytes = await blob.arrayBuffer(); guard();
  const digest = await crypto.subtle.digest('SHA-256', bytes); guard();
  const sha256 = Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join('');
  if (sha256 !== descriptor.sha256) throw new ApiError(409, 'RESOURCE_CHANGED');
  return blob;
}

export class WorkbenchApi {
  revision = '';
  epoch = 0;
  onDenied: (status: number) => void = () => {};
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

  uploadTerrain<T>(file: Blob, metadata: object, signal?: AbortSignal) {
    return this.send<T>('/api/workbench/terrains/upload', metadata, signal, false, {file, kind:'terrain'});
  }

  content(path: string, body: object, descriptor: BinaryDescriptor, signal?: AbortSignal): Promise<Blob> {
    if (!['model/gltf-binary','application/octet-stream'].includes(descriptor.mime)
        || !Number.isSafeInteger(descriptor.maxBytes) || descriptor.maxBytes <= 0
        || descriptor.maxBytes > (descriptor.mime === 'model/gltf-binary' ? 20 : 256) * MIB
        || !/^[a-f0-9]{64}$/.test(descriptor.sha256)) {
      return Promise.reject(new ApiError(422, 'INVALID_REQUEST'));
    }
    return this.send<Blob>(path, body, signal, descriptor);
  }

  async request<T>(path: string, body?: object, signal?: AbortSignal, image: boolean | 'model' = false, upload?:Blob): Promise<T> {
    return this.send<T>(path, body, signal, image, upload ? {file:upload, kind:'legacyModel'} : undefined);
  }

  private async send<T>(path: string, body?: object, signal?: AbortSignal,
    image: boolean | 'model' | BinaryDescriptor = false, upload?: {file: Blob; kind: UploadKind}): Promise<T> {
    const epoch = this.epoch, revision = this.revision;
    const guard = () => {
      if (epoch !== this.epoch || revision !== this.revision || signal?.aborted) {
        throw new DOMException('Selection or session changed', 'AbortError');
      }
    };
    guard();
    const json = body ? JSON.stringify({...body, expectedSessionRevision: revision}) : undefined;
    const headers:Record<string,string> = body ? {'Content-Type':'application/json'} : {};
    if (upload) {
      const terrain = upload.kind === 'terrain';
      if (upload.kind !== 'legacyModel' && (!Number.isSafeInteger(upload.file.size)
          || upload.file.size < (terrain ? 8 : 24) || upload.file.size > (terrain ? 256 : 20) * MIB)) {
        throw new ApiError(413, terrain ? 'TERRAIN_LIMIT_EXCEEDED' : 'MODEL_LIMIT_EXCEEDED');
      }
      const metadata = new TextEncoder().encode(json!);
      if (metadata.length > 6144) throw new ApiError(413, 'INVALID_REQUEST');
      headers['Content-Type'] = terrain ? 'image/tiff' : 'model/gltf-binary';
      headers[terrain ? 'X-Terrain-Metadata' : 'X-Model-Metadata'] = btoa(String.fromCharCode(...metadata));
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
      if (response.status === 401 || response.status === 403 && !writeDenied) {
        this.invalidate(); this.onDenied(response.status);
      }
      throw new ApiError(response.status, code);
    }
    if (typeof image === 'object') return await binaryResponse(response, image, revision, guard) as T;
    if (image) {
      const blob = await response.blob();
      guard();
      if (response.headers.get('X-Session-Revision') !== revision || blob.type !== (image === 'model' ? 'model/gltf-binary' : 'image/png')
          || blob.size > 20 * 1024 * 1024) throw new ApiError(502, 'SOURCE_UNAVAILABLE');
      return blob as T;
    }
    const data = await response.json();
    guard();
    if (data.sessionRevision && path.startsWith('/api/workbench/') && data.sessionRevision !== revision) {
      throw new DOMException('Session changed', 'AbortError');
    }
    return data as T;
  }
}

export function failureMessage(error: unknown, locale = 'zh'): string {
  const modelErrors:Record<string,[string,string]> = {
    LEGACY_SCENE_ENTRY_UNAVAILABLE:['原模型对应的场景暂不可用，请重新读取。','The scene for this legacy model is unavailable. Reload it.'],
    INVALID_MODEL:['模型结构不完整或已损坏，请检查文件。','The model is incomplete or damaged. Check the file.'],
    UNSUPPORTED_MODEL:['仅支持自包含静态 GLB，当前模型含未支持的资源或扩展。','Only self-contained static GLB is supported. This model uses unsupported resources or extensions.'],
    MODEL_LIMIT_EXCEEDED:['模型超过当前文件、几何或贴图处理限额。','The model exceeds file, geometry or texture limits.'],
    MODEL_LIBRARY_FULL:['模型库已达到当前容量限额。','The model library has reached its current capacity.'],
    MODEL_BUSY:['另一个模型正在校验，请稍后重试。','Another model is being validated. Retry shortly.'],
    MODEL_WRITE_FORBIDDEN:['需项目管理员权限，仍可查看已有模型。','Project administrator access is required. Existing models remain readable.'],
    MODEL_RIGHTS_REQUIRED:['请确认你有权使用此模型。','Confirm that you have the right to use this model.'],
    COMPONENT_ALREADY_LINKED:['该构件已关联另一个柜体，请选择其他构件。','This component is already linked to another cabinet. Choose a different component.'],
    MODEL_LIBRARY_CHANGED:['模型库已变化，请刷新后重试。','The library changed. Refresh and retry.'],
    MODEL_ASSET_CHANGED:['模型资源信息已变化，请重新读取。','The model resource changed. Reload it.'],
    MODEL_GEOGRAPHIC_CALIBRATION_REQUIRED:['沿用旧显示的模型仅可用于局部场景；地理布置请先校准。','Legacy display models are limited to local scenes. Calibrate before geographic placement.'],
    MODEL_CALIBRATION_REQUIRED:['请先核对模型单位、基点和正面朝向。','Verify the model units, base point and forward direction first.'],
    MODEL_STORAGE_UNAVAILABLE:['模型暂存或保存失败，请重试；不要重复创建版本。','Model storage failed. Retry the same request.'],
    SCENE_WRITE_FORBIDDEN:['当前仅可查看，未保存的修改仍保留。','You can currently view this scene. Unsaved edits are retained.'],
    SCENE_CHANGED:['场景已有新版本，保留当前修改后重新读取。','A newer scene exists. Keep your edits and reload before retrying.'],
    SNAPSHOT_EXPIRED:['列表已变化，请从第一页重新读取。','The list changed. Reload from the first page.'],
    REQUEST_CONFLICT:['该请求的内容已变化，请核对后重新操作。','This request was already used with different content. Review the change.'],
    RESOURCE_CHANGED:['资源内容或版本已变化，请重新核对。','The resource content or version changed. Review it again.'],
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
