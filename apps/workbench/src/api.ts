export class ApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string) {
    super(code); this.status = status; this.code = code;
  }
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
    return this.request<T>('/api/workbench/models/upload',metadata,signal,false,file);
  }

  async request<T>(path: string, body?: object, signal?: AbortSignal, image: boolean | 'model' = false, upload?:Blob): Promise<T> {
    const epoch = this.epoch, revision = this.revision;
    const guard = () => {
      if (epoch !== this.epoch || revision !== this.revision || signal?.aborted) {
        throw new DOMException('Selection or session changed', 'AbortError');
      }
    };
    const json = body ? JSON.stringify({...body, expectedSessionRevision: revision}) : undefined;
    const headers:Record<string,string> = upload ? {'Content-Type':'model/gltf-binary',
      'X-Model-Metadata':btoa(String.fromCharCode(...new TextEncoder().encode(json!)))} : body ? {'Content-Type':'application/json'} : {};
    const response = await this.transport(path, {method: body ? 'POST' : 'GET', credentials: 'same-origin',
      cache: 'no-store', signal, headers, body:upload || json});
    guard();
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      guard();
      const writeDenied=response.status===403 && data.code==='MODEL_WRITE_FORBIDDEN'
        && ['/api/workbench/models/upload','/api/workbench/models/binding'].includes(path);
      if (response.status === 401 || response.status === 403 && !writeDenied) {
        this.invalidate(); this.onDenied(response.status);
      }
      throw new ApiError(response.status, data.code || 'SOURCE_UNAVAILABLE');
    }
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
    INVALID_MODEL:['模型结构不完整或已损坏，请检查文件。','The model is incomplete or damaged. Check the file.'],
    UNSUPPORTED_MODEL:['仅支持自包含静态 GLB，当前模型含未支持的资源或扩展。','Only self-contained static GLB is supported. This model uses unsupported resources or extensions.'],
    MODEL_LIMIT_EXCEEDED:['模型超过当前文件、几何或贴图处理限额。','The model exceeds file, geometry or texture limits.'],
    MODEL_LIBRARY_FULL:['模型库已达到当前容量限额。','The model library has reached its current capacity.'],
    MODEL_BUSY:['另一个模型正在校验，请稍后重试。','Another model is being validated. Retry shortly.'],
    MODEL_WRITE_FORBIDDEN:['需项目管理员权限，仍可查看已有模型。','Project administrator access is required. Existing models remain readable.'],
    MODEL_RIGHTS_REQUIRED:['请确认你有权使用此模型。','Confirm that you have the right to use this model.'],
    COMPONENT_ALREADY_LINKED:['该构件已关联另一个柜体，请选择其他构件。','This component is already linked to another cabinet. Choose a different component.'],
    MODEL_LIBRARY_CHANGED:['模型库已变化，请刷新后重试。','The library changed. Refresh and retry.'],
  };
  if (error instanceof ApiError && modelErrors[error.code]) return modelErrors[error.code][locale === 'en' ? 1 : 0];
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
