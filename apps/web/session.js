// Authentication stays in the same origin. Only an opaque HttpOnly cookie is
// held by the browser; no upstream token or password enters browser storage.
export class UserSession {
  constructor() {
    this.state = 'checking'; this.revision = null; this.username = null;
    this.epoch = 0; this.listeners = new Set(); this.pending = false;
    this.remotePending = false; this.logoutRetry = null; this.lastActivity = 0;
    this.channel = typeof BroadcastChannel === 'function' ? new BroadcastChannel('ontovis-session') : null;
    this.channel?.addEventListener('message', ({data}) => {
      if (data?.type === 'clear') { this.remotePending = true; this.epoch++; this.publish('signedOut'); }
      if (data?.type === 'changed') { this.remotePending = false; this.refresh(); }
    });
    this.button = document.createElement('button'); this.button.id = 'session-button';
    this.button.type = 'button'; this.button.textContent = '登录';
    this.button.onclick = () => this.logoutRetry ? this.logout() : ['active','denied'].includes(this.state) ? this.logout() : this.open();
    document.querySelector('.top-end')?.append(this.button);
    this.dialog = document.createElement('dialog'); this.dialog.className = 'session-dialog'; this.dialog.setAttribute('aria-label','登录');
    this.dialog.innerHTML = `<button class="session-close" type="button" aria-label="关闭登录">×</button><img src="./assets/ONTOVis.png" alt="ONTOVis"><form><input name="username" aria-label="用户名" placeholder="用户名" autocomplete="username" maxlength="200" required><input name="password" type="password" aria-label="密码" placeholder="密码" autocomplete="current-password" maxlength="1024" required><p role="alert" hidden></p><button class="primary" type="submit">登录</button></form>`;
    document.body.append(this.dialog);
    this.dialog.querySelector('form').onsubmit = event => { event.preventDefault(); this.login(); };
    this.dialog.querySelector('.session-close').onclick = () => this.close();
    this.dialog.addEventListener('cancel', event => { event.preventDefault(); this.close(); });
    const activity = () => {
      if (this.state === 'active' && Date.now() - this.lastActivity > 60000) { this.lastActivity = Date.now(); this.refresh(true); }
    };
    for (const name of ['pointerdown','keydown','wheel']) window.addEventListener(name,activity,{passive:true});
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') this.refresh(); });
    setInterval(() => this.refresh(),30000);
    this.refresh();
  }
  get readable() { return this.state === 'active' && !this.remotePending && !this.logoutRetry; }
  subscribe(callback) { this.listeners.add(callback); return () => this.listeners.delete(callback); }
  publish(state, revision = null, username = null) {
    const changed = state !== this.state || revision !== this.revision;
    this.state = state; this.revision = revision; this.username = username;
    this.button.textContent = this.logoutRetry ? '重试退出' : ['active','denied'].includes(state) ? `${username} · 退出` : '登录';
    this.button.disabled = this.pending && !this.dialog.open;
    if (changed) for (const listener of this.listeners) listener();
  }
  async request(path, body) {
    const response = await fetch(path, {method:body ? 'POST' : 'GET', credentials:'same-origin', cache:'no-store',
      headers:body ? {'Content-Type':'application/json'} : {}, body:body ? JSON.stringify(body) : undefined});
    let value;
    try { value = await response.json(); } catch { throw Object.assign(new Error(),{code:'SOURCE_UNAVAILABLE'}); }
    if (!response.ok) throw Object.assign(new Error(),{code:value.code || 'SOURCE_UNAVAILABLE',status:response.status});
    return value;
  }
  async refresh(activity = false) {
    if (this.pending || this.remotePending || this.logoutRetry) return;
    const epoch = ++this.epoch;
    try {
      const value = await this.request('/api/session' + (activity ? '?activity=1' : ''));
      if (epoch !== this.epoch) return;
      this.publish(value.state,value.sessionRevision,value.username);
    } catch {
      if (epoch === this.epoch) this.publish('unavailable');
    }
  }
  async open() {
    this.dialog.querySelector('form').reset(); this.error(''); this.dialog.showModal();
    await this.refresh();
    if (['active','denied'].includes(this.state)) { this.dialog.close(); return; }
    if (this.dialog.open) this.dialog.querySelector('[name=username]').focus();
  }
  error(message) { const element = this.dialog.querySelector('[role=alert]'); element.textContent = message; element.hidden = !message; }
  pendingForm(value) {
    this.pending = value;
    const submit = this.dialog.querySelector('[type=submit]'); submit.disabled = value; submit.textContent = value ? '正在登录…' : '登录';
    for (const input of this.dialog.querySelectorAll('input')) input.disabled = value;
  }
  async login() {
    if (this.pending) return;
    if (!this.revision) await this.refresh();
    if (!this.dialog.open || !this.revision) { this.error('暂时无法登录，请稍后重试。'); return; }
    const form = this.dialog.querySelector('form');
    const username = form.elements.username.value.trim(), password = form.elements.password.value;
    if (!username || !password) return;
    const revision = this.revision, epoch = ++this.epoch;
    this.pendingForm(true); this.error(''); this.pendingRevision = revision;
    form.elements.password.value = '';
    try {
      const value = await this.request('/api/session/login',{username,password,expectedSessionRevision:revision});
      if (epoch !== this.epoch) return;
      this.pendingForm(false); this.publish(value.state,value.sessionRevision,value.username);
      form.reset(); this.dialog.close(); this.channel?.postMessage({type:'changed'});
    } catch (error) {
      if (epoch !== this.epoch) return;
      this.pendingForm(false);
      this.error(error.code === 'CREDENTIALS_REJECTED' ? '用户名或密码错误。' : error.code === 'LOGIN_RATE_LIMITED' ? '尝试次数较多，请稍后重试。' : '暂时无法登录，请稍后重试。');
      form.elements.password.focus();
    }
  }
  close() {
    const pendingRevision = this.pendingRevision;
    const wasPending = this.pending;
    this.epoch++; this.pendingForm(false); this.dialog.querySelector('form').reset(); this.dialog.close();
    if (wasPending) { this.logoutRetry = pendingRevision; this.logout(); }
  }
  async logout() {
    const revision = this.logoutRetry || this.revision;
    this.epoch++; this.pending = true; this.logoutRetry = revision;
    this.publish('signedOut'); this.channel?.postMessage({type:'clear'});
    try {
      await this.request('/api/session/logout',{expectedSessionRevision:revision});
      this.logoutRetry = null; this.pending = false; this.publish('signedOut');
      this.channel?.postMessage({type:'changed'});
    } catch {
      this.pending = false; this.publish('unavailable');
    }
  }
  expired() {
    this.epoch++; this.publish('expired'); this.channel?.postMessage({type:'clear'});
    // Every tab drops old geometry immediately, then independently rechecks.
    this.channel?.postMessage({type:'changed'});
  }
}
