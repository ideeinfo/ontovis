import { useEffect, useRef, useState } from 'react';
import * as Tabs from '@radix-ui/react-tabs';
import { Box, Boxes, Building2, ChevronDown, ChevronRight, CheckCheck, Database, FileText, GitBranch, Layers3, Link2, Settings2, ShieldCheck, Sparkles } from 'lucide-react';
import logo from '../../../assets/brand/ONTOVis.png';
import { ApiError, cancelled, failureMessage, WorkbenchApi } from './api';
import type { ChildrenView, ContextView, EngineeringObject, Installation, ObjectView, SessionView } from './types';
import { Badge, Btn, Modal, Panel } from './Primitives';
import { SourceEvidence } from './SourceEvidence';

const api = new WorkbenchApi();
const navigation = [
  ['project', '项目与访问', Building2], ['models', '模型中心', Boxes], ['bindings', '构件绑定', Link2],
  ['devices', '设备层级', GitBranch], ['scene', '场景与可视化', Layers3], ['data', '数据与告警', Database],
  ['ai', 'AI 策略', Sparkles], ['evidence', '证据与审计', FileText],
] as const;

function TreeNode({object, context, selected, onSelect, depth = 0, initialOpen = false}: {
  object: EngineeringObject; context: Installation; selected: string; onSelect: (uid: string) => void;
  depth?: number; initialOpen?: boolean;
}) {
  const [open, setOpen] = useState(initialOpen);
  const [children, setChildren] = useState<ChildrenView | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [cursor, setCursor] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController(); setLoading(true); setError('');
    api.request<ChildrenView>('/api/workbench/children', {parentEntityUid: object.entityUid,
      cursor, expectedHierarchyRevision: context.hierarchyRevision}, controller.signal)
      .then(value => setChildren(previous => ({...value, items: cursor ? [...(previous?.items || []), ...value.items] : value.items})))
      .catch(error => {if (!cancelled(error)) setError(failureMessage(error));})
      .finally(() => {if (!controller.signal.aborted) setLoading(false);});
    return () => controller.abort();
  }, [open, cursor, attempt]);
  return <div className="ov-runtime-tree-node">
    <div className="ov-runtime-tree-row">
      <button className="ov-text-btn ov-expand-node" type="button" disabled={depth >= 31} aria-label={`${open ? '收起' : '展开'}${object.displayName}`} aria-expanded={open} onClick={() => setOpen(v => !v)}>{open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}</button>
      <button type="button" className={selected === object.entityUid ? 'active' : ''} onClick={() => onSelect(object.entityUid)}><Box size={15} /><span><strong>{object.displayName}</strong><small>{object.objectKind === 'unknown' ? '类型待核实' : object.objectKind}</small></span></button>
    </div>
    {open && <div className="ov-tree-branch">
      {children?.items.map(child => <TreeNode key={child.object.entityUid} object={child.object} context={context} selected={selected} onSelect={onSelect} depth={depth + 1} />)}
      {loading ? <p className="ov-source-note" role="status">正在读取…</p> : error ? <div role="alert"><p className="ov-source-note">{error}</p><Btn onClick={() => setAttempt(v => v + 1)}>重试读取</Btn></div> : children?.items.length === 0 ? <p className="ov-source-note">无下级对象</p> : null}
      {!loading && children?.nextCursor && <Btn onClick={() => setCursor(children.nextCursor)}>加载更多</Btn>}
    </div>}
  </div>;
}

function Schematic() {
  return <div className="ov-model-view" aria-label="三柜布局示意，未绑定工程空间">
    <div className="ov-model-top"><div className="ov-view-crumb"><Box size={14} />构件视图</div><Badge>示意布局</Badge></div>
    <div className="ov-model-floor" /><div className="ov-cabinets">
      {['CN1','CN','CT'].map((id, i) => <div key={id} className={`ov-cabinet position-${i} ${id === 'CT' ? 'short' : ''}`}><span className="ov-cab-top" /><span className="ov-cab-side" /><span className="ov-cab-front"><span className="ov-cab-vents" /><span className="ov-cab-screen" /><span className="ov-cab-handle" /><span className="ov-cab-label">{id}</span></span><span className="ov-cab-ground" /></div>)}
    </div><div className="ov-model-bottom"><span>几何绑定待审核</span><span>空间位置未知</span></div>
  </div>;
}

export function Workbench() {
  const [session, setSession] = useState<SessionView | null>(null);
  const [context, setContext] = useState<ContextView | null>(null);
  const [selected, setSelected] = useState('');
  const [detail, setDetail] = useState<ObjectView | null>(null);
  const [page, setPage] = useState<'bindings' | 'project'>('bindings');
  const [tab, setTab] = useState('对象');
  const [loginOpen, setLoginOpen] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [signingIn, setSigningIn] = useState(false);
  const [loginError, setLoginError] = useState('');
  const [message, setMessage] = useState('正在检查会话…');
  const [loading, setLoading] = useState(false);
  const [reload, setReload] = useState(0);
  const [layout, setLayout] = useState('balanced');
  const channel = useRef<BroadcastChannel | null>(null);
  const current = useRef(session); current.current = session;
  const lastActivity = useRef(0);

  function clear(state: string, text: string) {
    api.invalidate(); setContext(null); setSelected(''); setDetail(null); setLoading(false);
    setSession(previous => previous ? {...previous, state} : null); setMessage(text);
    setPassword('');
  }
  async function inspect(activity = false) {
    try {
      const value = await api.request<SessionView>('/api/session' + (activity ? '?activity=1' : ''));
      if (value.state !== 'active') {
        clear(value.state, value.state === 'denied' ? '当前项目不可读，请联系项目管理员。' : '登录后读取工程对象。');
        api.session(value.sessionRevision); setSession(value);
      } else if (!current.current || current.current.sessionRevision !== value.sessionRevision || current.current.state !== 'active') {
        clear('active', ''); api.session(value.sessionRevision); setSession(value); setReload(v => v + 1);
      }
    } catch (error) {if (!cancelled(error)) clear('unavailable', '工程服务暂不可达，请重试。');}
  }
  useEffect(() => {
    api.onDenied = status => clear(status === 401 ? 'expired' : 'denied', status === 401 ? '会话已失效，请重新登录。' : '当前项目不可读，请联系项目管理员。');
    void inspect();
    channel.current = new BroadcastChannel('ontovis-workbench-session');
    channel.current.onmessage = () => {clear('signedOut', '会话已变化，工程详情已清理。'); void inspect();};
    const poll = window.setInterval(() => {void inspect();}, 30000);
    const activity = () => {
      if (current.current?.state === 'active' && Date.now() - lastActivity.current > 60000) {
        lastActivity.current = Date.now(); void inspect(true);
      }
    };
    window.addEventListener('pointerdown', activity); window.addEventListener('keydown', activity);
    const visible = () => {if (!document.hidden) void inspect();};
    document.addEventListener('visibilitychange', visible);
    return () => {window.clearInterval(poll); channel.current?.close(); api.onDenied = () => {};
      window.removeEventListener('pointerdown', activity); window.removeEventListener('keydown', activity);
      document.removeEventListener('visibilitychange', visible); api.invalidate();};
  }, []);

  useEffect(() => {
    if (session?.state !== 'active') return;
    const controller = new AbortController(); setLoading(true); setMessage('正在读取当前安装范围…');
    api.request<ContextView>('/api/workbench/context', {}, controller.signal)
      .then(value => {setContext(value); setMessage('演示安装关系仍待核实；工程绑定和发布尚未开放。');})
      .catch(error => {if (!cancelled(error)) {setContext(null); setMessage(failureMessage(error));}})
      .finally(() => {if (!controller.signal.aborted) setLoading(false);});
    return () => controller.abort();
  }, [session?.state, session?.sessionRevision, reload]);

  useEffect(() => {
    setDetail(null);
    if (!selected || !context || session?.state !== 'active') return;
    const controller = new AbortController();
    api.request<ObjectView>('/api/workbench/object', {entityUid: selected,
      expectedHierarchyRevision: context.context.hierarchyRevision}, controller.signal)
      .then(setDetail).catch(error => {if (!cancelled(error)) {
        if (error instanceof ApiError && error.status === 409) clear('active', failureMessage(error));
        else setMessage(failureMessage(error));
      }});
    return () => controller.abort();
  }, [selected, context, session?.state, session?.sessionRevision]);

  async function login() {
    setSigningIn(true); setLoginError('');
    try {
      const value = await api.request<SessionView>('/api/session/login', {username, password});
      clear(value.state, ''); api.session(value.sessionRevision); setSession(value); setLoginOpen(false);
      setReload(v => v + 1); channel.current?.postMessage('session-changed');
    } catch (error) {if (!cancelled(error)) setLoginError(error instanceof ApiError && error.code === 'CREDENTIALS_REJECTED' ? '账号或密码不正确，请重新登录。' : failureMessage(error));}
    finally {setPassword(''); setSigningIn(false);}
  }
  async function logout() {
    const revision = api.revision;
    clear('signedOut', '已退出，工程详情已清理。');
    channel.current?.postMessage('session-changed');
    try {await api.request('/api/session/logout', {expectedSessionRevision: revision});}
    catch (error) {if (!cancelled(error)) setMessage('退出状态待核验，请重试退出。');}
    finally {void inspect();}
  }
  function closeLogin() {
    setLoginOpen(false); setPassword('');
    if (signingIn) {void logout();}
  }
  const isActive = session?.state === 'active';
  const title = page === 'bindings' ? '构件绑定' : '项目与访问';
  const parent = detail?.ancestors.path[0]?.object;
  return <div className="ov-app">
    <header className="ov-topbar"><a className="ov-logo" href="#project" onClick={event => {event.preventDefault(); setPage('project');}} aria-label="ONTOVis 项目首页"><img src={logo} alt="ONTOVis 本源数智" /></a><span className="ov-top-divider" />
      <button className="ov-project-picker" type="button" onClick={() => setPage('project')}><Building2 size={15} /><span>{context?.projectName || '工程工作台'}</span><ChevronDown size={13} /></button><div className="ov-top-spacer" /><Badge>只读试点</Badge>
      {session?.username && <span className="ov-muted">{session.username}</span>}{isActive || session?.state === 'denied' ? <Btn onClick={logout}>退出</Btn> : <Btn onClick={() => {setLoginError(''); setLoginOpen(true);}}>登录</Btn>}</header>
    <div className="ov-shell"><aside className="ov-sidebar"><div className="ov-sidebar-label">项目管理</div><nav aria-label="项目管理">
      {navigation.map(([id,label,Icon]) => <button type="button" key={id} aria-current={page === id ? 'page' : undefined} className={page === id ? 'active' : ''} disabled={!['project','bindings'].includes(id)} title={['project','bindings'].includes(id) ? label : '尚未开放'} onClick={() => setPage(id as 'project' | 'bindings')}><Icon size={17} strokeWidth={1.7} /><span>{label}</span></button>)}
    </nav><div className="ov-sidebar-bottom"><div className="ov-connection"><span className={`ov-dot ${isActive ? '' : 'muted'}`} />OntoBase <Badge>{isActive ? '已登录' : '未连接'}</Badge></div><button type="button" onClick={() => setPage('project')}><Settings2 size={15} />项目与访问<ChevronRight size={13} /></button></div></aside>
    <main className="ov-main"><div className="ov-breadcrumb">项目管理<ChevronRight size={12} />{title}</div><div className="ov-page-head"><div><h1>{title}</h1><div className="ov-page-meta"><span>{context?.context.displayName || '当前工程范围'}</span><Badge>演示安装 · 待核实</Badge></div></div><div className="ov-page-actions"><Btn primary disabled title="工程身份、物理证据和几何绑定尚未审核"><CheckCheck size={15} />发布</Btn></div></div>
      <section className="ov-slice-review" aria-label="当前读取状态"><div className="ov-slice-status" role="status"><span>{message}</span>{isActive && <Btn disabled={loading} onClick={() => {setContext(null); setSelected(''); setDetail(null); api.invalidate(); setReload(v => v + 1);}}>重新读取</Btn>}</div></section>
      {page === 'project' ? <Panel title="工程访问"><div className="ov-panel-body"><div className="ov-inline"><ShieldCheck size={18} /><strong>{isActive ? '当前项目可读' : '登录后读取工程对象'}</strong></div><p className="ov-runtime-description">使用本人 OntoBase 账号。工程对象、安装层级和资料按当前项目权限读取。</p><p className="ov-source-note">首批开放当前图纸预览；安装关系为演示假定。绑定确认、发布和现场控制尚未开放。</p><div className="ov-session-actions">{isActive ? <Btn primary onClick={() => setPage('bindings')}>进入工作台</Btn> : <Btn primary onClick={() => setLoginOpen(true)}>登录</Btn>}</div></div></Panel>
      : <><div className="ov-binding-toolbar"><div className="ov-inline"><Badge tone="amber">演示假定</Badge><span className="ov-muted">工程绑定未确认</span></div><div className="ov-toolbar-end"><div className="ov-segment" aria-label="工作台布局">{[['balanced','均衡'],['model','模型'],['evidence','证据']].map(([id,label]) => <button type="button" key={id} className={layout === id ? 'active' : ''} onClick={() => setLayout(id)}>{label}</button>)}</div></div></div>
        <div className={`ov-binding-grid layout-${layout}`}><Panel title="工程对象" className="ov-tree-panel"><div className="ov-tree">{context?.root ? <TreeNode key={`${context.context.hierarchyRevision}:${session?.sessionRevision}:${reload}`} object={context.root} context={context.context} selected={selected} onSelect={uid => {setDetail(null); setSelected(uid);}} initialOpen /> : <p className="ov-source-note">{isActive ? '当前没有可读的安装对象。' : '登录后读取安装对象。'}</p>}</div></Panel>
          <Panel className="ov-viewport-panel"><Schematic /></Panel>
          <Panel className="ov-inspector"><div className="ov-inspector-heading"><span className="ov-eyebrow">当前对象</span><h2>{detail?.item.displayName || (selected ? '正在读取…' : '请选择工程对象')}</h2>{detail && <div className="ov-inline"><Badge tone="amber">{detail.item.reviewStatus === 'confirmed' ? '正式对象' : '待核实'}</Badge><span className="ov-source-note">{detail.item.objectKind === 'unknown' ? '类型未知' : detail.item.objectKind}</span></div>}</div>
            {detail && context && <Tabs.Root value={tab} onValueChange={setTab}><Tabs.List className="ov-tabs" aria-label="对象详情">{['对象','属性','证据'].map(label => <Tabs.Trigger className={tab === label ? 'active' : ''} key={label} value={label}>{label}</Tabs.Trigger>)}</Tabs.List>
              <Tabs.Content value="对象" className="ov-inspector-body"><dl className="ov-kv"><dt>分析对象</dt><dd>{detail.item.displayName}</dd><dt>安装身份</dt><dd>独立安装对象</dd><dt>所属对象</dt><dd>{parent?.displayName || '未取得上级对象'}</dd><dt>物理关系</dt><dd>{detail.ancestors.completeness === 'complete' ? '演示假定 · 待核实' : '父链不完整'}</dd><dt>空间定位</dt><dd>未知 · 几何绑定待审核</dd></dl></Tabs.Content>
              <Tabs.Content value="属性" className="ov-inspector-body"><dl className="ov-kv"><dt>对象 UID</dt><dd className="ov-mono">{detail.item.entityUid}</dd><dt>对象修订</dt><dd className="ov-mono">{detail.item.entityRevision}</dd><dt>型号来源</dt><dd className="ov-mono">{detail.item.sourceTemplateEntityUid || '无固定来源'}</dd></dl></Tabs.Content>
              <Tabs.Content value="证据" className="ov-inspector-body"><SourceEvidence key={`${selected}:${detail.item.entityRevision}:${context.context.hierarchyRevision}:${session?.sessionRevision}`} api={api} object={detail.item} context={context.context} host="未知 · 几何绑定待审核" /></Tabs.Content>
            </Tabs.Root>}
            <div className="ov-inspector-footer"><Btn primary disabled title="需要核实工程身份、物理关系和几何绑定">确认绑定</Btn></div>
          </Panel></div><div className="ov-context-strip"><span>所选：{detail?.item.displayName || '未选择'}</span><span>空间定位：未知</span><span className="ov-spacer" /><span className="ov-muted">示意布局 · 工程发布未开放</span></div></>}
    </main></div>
    {loginOpen && <Modal title="登录 ONTOVis" description="使用本人 OntoBase 账号登录" onClose={closeLogin}><form className="ov-simple-login" onSubmit={event => {event.preventDefault(); void login();}}>
      <input aria-label="用户名" placeholder="用户名" autoComplete="username" value={username} onChange={event => setUsername(event.target.value)} required disabled={signingIn} />
      <input aria-label="密码" placeholder="密码" type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} required disabled={signingIn} />
      {loginError && <p role="alert">{loginError}</p>}<button type="submit" className="ov-btn primary" disabled={signingIn}>{signingIn ? '正在登录…' : '登录'}</button>
    </form></Modal>}
  </div>;
}
