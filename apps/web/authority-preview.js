import { UserSession } from './session.js';
const html = (value) => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const messages = {
  NOT_CONNECTED: '本机登录会话尚未启动。此页没有可读取的安装对象。',
  SESSION_EXPIRED: '登录已失效，请重新登录。',
  LOGIN_REQUIRED: '请先登录。',
  ACCESS_CHANGED: '访问权限已变化，请重新读取。',
  FORBIDDEN: '当前无权读取工程对象，已清理详情与高亮。',
  NOT_FOUND_OR_FORBIDDEN: '对象不可用或无权访问，未保留旧高亮。',
  INSTANCE_MISMATCH: '对象不属于当前机位，不能借用其他机位定位。',
  IDENTITY_CHANGED: '对象身份已变化，原绑定需要复核，不自动改绑。',
  PATH_UNAVAILABLE: '父链不完整，保留分析对象；空间位置未知。',
  DEPTH_LIMIT: '父链超过读取上限，空间位置未知。',
  REVISION_CONFLICT: '读取过程中层级已变化，请重新读取同一上下文。',
  PREVIEW_INPUT_CHANGED: '演示输入已变化，需要重新核实本机绑定草稿。',
  SOURCE_UNAVAILABLE: 'OntoBase暂不可达，请重试；本次没有定位成功。',
  NO_GEOMETRY: '当前对象及祖先没有可用几何，空间位置未知。',
};

export class InstallationAuthorityPanel {
  constructor({ scope, onLocate, onSelection, onClear, enterUnit }) {
    this.scope = scope; this.onLocate = onLocate; this.onSelection = onSelection; this.onClear = onClear; this.enterUnit = enterUnit;
    this.epoch = 0; this.mode = 'idle'; this.data = null; this.result = null; this.selectedUid = null;
    this.container = null; this.controller = null; this.error = null; this.signature = null;
    this.auth = new UserSession();
    this.auth.subscribe(() => {
      this.cancel(); this.data = null; this.selectedUid = null; this.error = null; this.mode = 'idle';
      this.draw();
      if (this.auth.readable && this.signature === '7:engineering') this.load();
    });
  }
  current(epoch, signature) {
    const scope = this.scope();
    return this.epoch === epoch && this.signature === signature && scope.active && scope.unitLabel === '7' && this.auth.readable;
  }
  cancel(clear = true) {
    this.epoch += 1; this.controller?.abort(); this.controller = null;
    this.result = null;
    if (clear) this.onClear();
  }
  inactive() {
    if (this.signature !== null) { this.cancel(); this.signature = null; this.mode = 'idle'; this.data = null; this.selectedUid = null; }
    this.container = null;
  }
  async read(path, signal) {
    const response = await fetch(path, { signal, cache: 'no-store', credentials: 'same-origin' });
    let data;
    try { data = await response.json(); } catch { throw Object.assign(new Error(), {code:'NOT_CONNECTED'}); }
    if (!response.ok) {
      if (response.status === 401) this.auth.expired();
      throw Object.assign(new Error(), {code:data.code || 'SOURCE_UNAVAILABLE'});
    }
    if (data.sessionRevision !== this.auth.revision) throw Object.assign(new Error(), {code:'SESSION_EXPIRED'});
    if (data.previewOnly !== true || data.engineeringUseAllowed !== false || data.bindingStatus !== 'demonstration_draft') {
      throw Object.assign(new Error(), {code:'PREVIEW_INPUT_CHANGED'});
    }
    return data;
  }
  async load() {
    if (!this.auth.readable) return;
    this.cancel();
    const epoch = this.epoch, signature = this.signature;
    this.mode = 'loading'; this.error = null; this.draw();
    this.controller = new AbortController();
    try {
      const data = await this.read('/api/demo/context', this.controller.signal);
      if (!this.current(epoch, signature)) return;
      this.data = data;
      if (!data.items.some(item => item.entityUid === this.selectedUid)) this.selectedUid = data.childEntityUid;
      this.mode = 'ready'; this.draw();
    } catch (error) {
      if (!this.current(epoch, signature) || error.name === 'AbortError') return;
      this.error = error.code || 'SOURCE_UNAVAILABLE'; this.mode = 'error';
      this.data = null; this.selectedUid = null;
      this.draw();
    }
  }
  async locate() {
    if (!this.selectedUid || !this.auth.readable) return;
    this.cancel();
    const epoch = this.epoch, signature = this.signature, uid = this.selectedUid;
    this.mode = 'loading'; this.error = null; this.draw();
    this.controller = new AbortController();
    try {
      const params = new URLSearchParams({entityUid:uid, unitLabel:'7', contextEpoch:String(epoch)});
      const data = await this.read('/api/demo/locate?' + params, this.controller.signal);
      if (!this.current(epoch, signature) || this.selectedUid !== uid || data.contextEpoch !== String(epoch)) return;
      if (data.selectedObjectRef?.entityUid !== uid || data.installationContextId !== this.data?.context.installationContextId) {
        throw Object.assign(new Error(), {code:'INSTANCE_MISMATCH'});
      }
      this.result = data; this.mode = 'ready'; this.draw();
      this.onSelection(data.selectedObjectRef);
      if (data.componentKey && ['demo_direct_geometry','demo_ancestor_proxy'].includes(data.locationMode)) {
        await this.onLocate(data);
      }
    } catch (error) {
      if (!this.current(epoch, signature) || error.name === 'AbortError') return;
      this.error = error.code || 'SOURCE_UNAVAILABLE'; this.mode = 'error';
      this.data = null; this.selectedUid = null;
      this.draw();
    }
  }
  render(container) {
    const scope = this.scope(), signature = scope.active ? `${scope.unitLabel}:engineering` : 'outside';
    if (signature !== this.signature) {
      this.cancel(); this.signature = signature; this.mode = 'idle'; this.data = null; this.selectedUid = null;
    }
    this.container = container;
    this.draw();
    if (signature === '7:engineering' && this.mode === 'idle' && this.auth.readable) this.load();
  }
  draw() {
    if (!this.container) return;
    const scope = this.scope();
    if (!this.auth.readable) {
      const denied = this.auth.state === 'denied';
      const message = denied ? '当前无权读取，请联系项目管理员。' : this.auth.state === 'unavailable' ? '暂时无法连接，请稍后重试。' : this.auth.state === 'expired' ? '登录已失效，请重新登录。' : '登录后查看工程对象。';
      this.container.innerHTML = `<h2>工程对象</h2><p class="plain-note" role="status">${message}</p><button class="primary wide" id="authority-login">${denied ? '重试' : '登录'}</button>`;
      this.container.querySelector('#authority-login').onclick = () => denied ? this.auth.refresh() : this.auth.open();
      return;
    }
    if (!scope.active || scope.unitLabel !== '7') {
      this.container.innerHTML = '<div class="section-label">ONTOBASE / DEMO</div><h2>演示安装对象</h2><p class="plain-note">本批只核对7号演示实例。其他机位继续使用通用模型，不借用7号对象身份。</p><button class="primary wide" id="authority-enter">进入7号演示实例 ↗</button>';
      this.container.querySelector('#authority-enter').onclick = this.enterUnit;
      return;
    }
    const selected = this.data?.items.find(item => item.entityUid === this.selectedUid);
    const result = this.result;
    const host = result?.locatedObjectRef ? this.data?.items.find(item => item.entityUid === result.locatedObjectRef.entityUid) : null;
    const pending = this.mode === 'loading';
    const status = this.error ? messages[this.error] || '本次读取未完成，空间位置未知。' : pending ? '正在核验当前身份与安装范围，旧高亮已清理。' : result ? result.componentKey ? '演示定位已核验 · 假定安装关系' : messages[result.reasonCode] || '空间位置未知。' : '读取安装对象后，可核验并定位所选对象。';
    this.container.innerHTML = `<div class="section-label">ONTOBASE / UNIT 7</div><h2>${html(selected?.displayName || '7号演示安装对象')}</h2>
      <p class="panel-subtitle">Demo-PDS · 登录用户 ${html(this.data?.operator || '待核验')}</p>
      <div class="tags"><span class="tag warn">假定安装关系</span><span class="tag">演示绑定草稿</span></div>
      <div class="authority-status ${this.error ? 'error' : ''}" role="status" aria-live="polite">${html(status)}</div>
      ${this.data ? `<label class="authority-field">所选工程对象<select id="authority-object" aria-label="所选工程对象" ${pending ? 'disabled' : ''}>${this.data.items.map(item => `<option value="${html(item.entityUid)}" ${item.entityUid === this.selectedUid ? 'selected' : ''}>${html(item.displayName)}</option>`).join('')}</select></label>
      <button class="primary wide" id="authority-locate" ${pending ? 'disabled' : ''}>核验并定位所选对象 ↗</button>
      <dl class="facts authority-facts"><dt>分析对象</dt><dd>${html(selected?.displayName || '—')}</dd><dt>空间宿主</dt><dd>${html(host?.displayName || '未定位')}</dd><dt>定位方式</dt><dd>${result?.locationMode === 'demo_ancestor_proxy' ? '演示祖先代理' : result?.locationMode === 'demo_direct_geometry' ? '演示直接几何' : '未定位'}</dd><dt>柜内坐标</dt><dd>未知</dd><dt>几何质量</dt><dd>${result?.geometryQuality === 'source_candidate' ? '源模型候选' : result?.geometryQuality === 'proxy_schematic' ? '示意代理' : '—'}</dd><dt>对象分类</dt><dd>${selected?.objectKind === 'unknown' ? '待核实' : html(selected?.objectKind || '—')}</dd></dl>
      <details><summary>身份与版本</summary><p class="authority-reference">所选 UID：${html(selected?.entityUid || '—')}<br>空间宿主 UID：${html(host?.entityUid || '未定位')}<br>安装范围：${html(this.data.context.installationContextId)}<br>层级修订：${html(result?.hierarchyRevision || this.data.context.hierarchyRevision)}</p></details>` : ''}
      <button class="wide" id="authority-refresh" ${pending ? 'disabled' : ''}>${this.error ? '重新读取对象' : '刷新安装对象'}</button>
      <p class="plain-note">同型号图纸定义共用，安装身份独立。当前子对象类型和物理归属未现场核实；CN为候选几何，CT/CN1为示意代理。工程发布保持阻断。</p>`;
    this.container.querySelector('#authority-refresh').onclick = () => this.load();
    if (this.data) {
      this.container.querySelector('#authority-object').onchange = event => {
        this.cancel(); this.selectedUid = event.target.value; this.error = null; this.mode = 'ready'; this.draw();
      };
      this.container.querySelector('#authority-locate').onclick = () => this.locate();
    }
  }
  inspect() {
    return { mode:this.mode,error:this.error,selectedEntityUid:this.selectedUid,result:structuredClone(this.result),
      contextId:this.data?.context.installationContextId || null,objectCount:this.data?.items.length || 0,epoch:this.epoch,
      sessionState:this.auth.state };
  }
}
