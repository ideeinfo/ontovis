import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import * as Tabs from '@radix-ui/react-tabs';
import * as Dropdown from '@radix-ui/react-dropdown-menu';
import { Boxes, Building2, ChevronDown, ChevronRight, Database, FileClock, Focus, GitBranch, Languages, Layers, Link2, LogOut, PanelLeft, PanelRight, RefreshCw, Sparkles, Sun, User } from 'lucide-react';
import logo from '../../../assets/brand/ONTOVis.png';
import { ApiError, cancelled, failureMessage, WorkbenchApi } from './api';
import type { ContextView, ModelView, ObjectView, SessionView } from './types';
import type { MessageKey } from './messages';
import { usePreferences } from './Preferences';
import { Badge, Btn, IconBtn, Modal } from './Primitives';
import { ObjectsPanel } from './ObjectsPanel';
import { modelLocation } from './modelLocation';
import { SourceEvidence } from './SourceEvidence';

const api = new WorkbenchApi();
const ModelViewport = lazy(() => import('./ModelViewport').then(module => ({default:module.ModelViewport})));
const navigation = [
  ['project', 'projectAccess', Building2], ['models', 'modelCenter', Boxes],
  ['bindings', 'componentBinding', Link2], ['hierarchy', 'equipmentHierarchy', GitBranch],
  ['scene', 'sceneSettings', Layers], ['data', 'dataAlarms', Database],
  ['ai', 'aiPolicy', Sparkles], ['audit', 'evidenceAudit', FileClock],
] as const;
type Page = 'project' | 'models' | 'bindings' | 'hierarchy';
export function Workbench() {
  const {t, locale, theme, setTheme, setLocale} = usePreferences();
  const [session, setSession] = useState<SessionView | null>(null);
  const [context, setContext] = useState<ContextView | null>(null);
  const [selection, setSelection] = useState({uid:'', scope:'equipment' as 'equipment' | 'project'});
  const [detail, setDetail] = useState<ObjectView | null>(null);
  const [model, setModel] = useState<ModelView | null>(null);
  const [tab, setTab] = useState('details');
  const [modal, setModal] = useState<'login' | 'account' | 'project' | 'model' | null>(null);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [signingIn, setSigningIn] = useState(false);
  const [loginError, setLoginError] = useState<unknown>(null);
  const [message, setMessage] = useState<MessageKey | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const [reload, setReload] = useState(0);
  const [left, setLeft] = useState(false), [right, setRight] = useState(false);
  const [focusSignal, setFocusSignal] = useState(0);
  const [page, setPage] = useState<Page>('bindings');
  const [layout, setLayout] = useState('balanced');
  const channel = useRef<BroadcastChannel | null>(null);
  const current = useRef(session); current.current = session;
  const lastActivity = useRef(0);

  function clear(state:string, text:MessageKey | null) {
    api.invalidate(); setContext(null); setSelection({uid:'', scope:'equipment'}); setDetail(null); setModel(null);
    setLoading(false); setSession(previous => previous ? {...previous, state} : null);
    setMessage(text); setError(null); setPassword('');
  }
  async function inspect(activity = false) {
    try {
      const value = await api.request<SessionView>('/api/session' + (activity ? '?activity=1' : ''));
      if (value.state !== 'active') {
        clear(value.state, value.state === 'denied' ? 'denied' : value.state === 'expired' ? 'expired' : 'loginPrompt');
        api.session(value.sessionRevision); setSession(value);
      } else if (!current.current || current.current.sessionRevision !== value.sessionRevision || current.current.state !== 'active') {
        clear('active', null); api.session(value.sessionRevision); setSession(value); setReload(value => value+1);
      }
    } catch (value) {if (!cancelled(value)) clear('unavailable', 'unavailable');}
  }
  useEffect(() => {
    api.onDenied = status => clear(status === 401 ? 'expired' : 'denied', status === 401 ? 'expired' : 'denied');
    void inspect();
    channel.current = new BroadcastChannel('ontovis-workbench-session');
    channel.current.onmessage = () => {clear('signedOut', 'sessionChanged'); void inspect();};
    const poll = window.setInterval(() => {void inspect();}, 30000);
    const activity = () => {
      if (current.current?.state === 'active' && Date.now()-lastActivity.current > 60000) {
        lastActivity.current = Date.now(); void inspect(true);
      }
    };
    window.addEventListener('pointerdown',activity); window.addEventListener('keydown',activity);
    const visible = () => {if (!document.hidden) void inspect();}; document.addEventListener('visibilitychange',visible);
    return () => {window.clearInterval(poll); channel.current?.close(); api.onDenied=() => {};
      window.removeEventListener('pointerdown',activity); window.removeEventListener('keydown',activity);
      document.removeEventListener('visibilitychange',visible); api.invalidate();};
  }, []);
  useEffect(() => {
    if (session?.state !== 'active') return;
    const controller = new AbortController(); setLoading(true); setMessage(null); setError(null);
    api.request<ContextView>('/api/workbench/context', {}, controller.signal)
      .then(value => {setContext(value); if (value.root) setSelection({uid:value.root.entityUid, scope:'equipment'});})
      .catch(value => {if (!cancelled(value)) {setContext(null); setError(value);}})
      .finally(() => {if (!controller.signal.aborted) setLoading(false);});
    return () => controller.abort();
  }, [session?.state, session?.sessionRevision, reload]);
  useEffect(() => {
    setDetail(null);
    if (!selection.uid || !context || session?.state !== 'active') return;
    const controller = new AbortController(); setError(null);
    api.request<ObjectView>('/api/workbench/object', {entityUid:selection.uid, scope:selection.scope,
      expectedHierarchyRevision:context.context.hierarchyRevision}, controller.signal)
      .then(setDetail).catch(value => {if (!cancelled(value)) {
        if (value instanceof ApiError && value.status === 409) {setContext(null); setSelection({uid:'',scope:'equipment'});}
        setError(value);
      }});
    return () => controller.abort();
  }, [selection, context, session?.state, session?.sessionRevision]);
  async function login() {
    setSigningIn(true); setLoginError(null);
    try {
      const value = await api.request<SessionView>('/api/session/login', {username, password});
      clear(value.state,null); api.session(value.sessionRevision); setSession(value); setModal(null);
      setReload(value => value+1); channel.current?.postMessage('session-changed');
    } catch (value) {if (!cancelled(value)) setLoginError(value);}
    finally {setPassword(''); setSigningIn(false);}
  }
  async function logout() {
    const revision = api.revision; clear('signedOut','loginPrompt'); setModal(null);
    channel.current?.postMessage('session-changed');
    try {await api.request('/api/session/logout', {expectedSessionRevision:revision});}
    catch (value) {if (!cancelled(value)) setMessage('logoutFailed');}
    finally {void inspect();}
  }
  function closeModal() {setModal(null); setPassword(''); if (signingIn) void logout();}
  function refresh() {
    api.invalidate(); setContext(null); setDetail(null); setSelection({uid:'',scope:'equipment'}); setModel(null); setReload(value => value+1);
  }
  function select(uid:string, scope:'equipment' | 'project' = 'equipment') {
    setDetail(null); setSelection({uid,scope}); setLeft(false);
  }
  const active = session?.state === 'active';
  const location = modelLocation(detail,model);
  const host = location ? location.mode === 'ancestor' ? t('ancestor') : location.binding.geometryQuality === 'proxy_schematic' ? t('proxy') : t('candidate') : !!model && detail?.item.entityUid === model.rootEntityUid ? t('modelReady') : t('unlocated');
  const parent = detail?.ancestors.path[0]?.object;
  const kinds = {turbine:'turbine', cabinet:'cabinet', device:'device', component:'component'} as const;
  const kind = detail && kinds[detail.item.objectKind as keyof typeof kinds];
  const title = navigation.find(row => row[0] === page)![1];
  const workspace = page === 'bindings' || page === 'hierarchy';
  return <div className="ov-app ov-compact">
    <header className="cw-header"><a className="cw-brand" href="#project" onClick={event => {event.preventDefault();setPage('project');}} aria-label="ONTOVis"><img src={logo} alt="ONTOVis 本源数智"/></a><span className="cw-divider"/>
      <button className="cw-project" type="button" onClick={() => setPage('project')}><Building2 size={15}/><span>{context?.projectName || t('workbench')}</span><ChevronDown size={12}/></button><span className="cw-grow"/>
      {active ? <Dropdown.Root><Dropdown.Trigger asChild><button type="button" className="cw-avatar" aria-label={t('account')}>{session?.username?.slice(0,2).toUpperCase() || <User size={16}/>}</button></Dropdown.Trigger><Dropdown.Portal><Dropdown.Content className="cw-menu" align="end" sideOffset={8}>
        <div className="cw-user-info"><strong>{session?.username}</strong><span className="cw-caption">{context?.projectName}</span></div>
        <Dropdown.Item onSelect={() => setModal('account')}><User size={15}/>{t('account')}</Dropdown.Item><Dropdown.Separator/>
        <div className="cw-preference"><span><Languages size={14}/>{t('language')}</span><Dropdown.RadioGroup value={locale} onValueChange={value => setLocale(value as 'zh' | 'en')}><Dropdown.RadioItem value="zh">简体中文</Dropdown.RadioItem><Dropdown.RadioItem value="en">English</Dropdown.RadioItem></Dropdown.RadioGroup></div>
        <div className="cw-preference"><span><Sun size={14}/>{t('theme')}</span><Dropdown.RadioGroup value={theme} onValueChange={value => setTheme(value as 'light' | 'dark' | 'system')}>{(['light','system','dark'] as const).map(value => <Dropdown.RadioItem key={value} value={value}>{t(value)}</Dropdown.RadioItem>)}</Dropdown.RadioGroup></div>
        <Dropdown.Separator/><Dropdown.Item onSelect={() => void logout()}><LogOut size={15}/>{t('signOut')}</Dropdown.Item>
      </Dropdown.Content></Dropdown.Portal></Dropdown.Root> : <Btn onClick={() => {setLoginError(null);setModal('login');}}>{t('signIn')}</Btn>}
    </header>
    <div className="cw-shell"><nav className="cw-navigation" aria-label={t('projectManagement')}><span className="cw-nav-heading">{t('projectManagement')}</span>{navigation.map(([id,label,Icon]) => <button type="button" key={id} className={page === id ? 'active' : ''} aria-label={t(label)} aria-current={page === id ? 'page' : undefined} disabled={!['project','models','bindings','hierarchy'].includes(id)} title={t(label)} onClick={() => {setPage(id as Page);setLeft(false);setRight(false);}}><Icon size={17} strokeWidth={1.7}/><span>{t(label)}</span></button>)}</nav>
      <main className="cw-main"><div className="cw-toolbar">{workspace && <IconBtn label={t('objects')} onClick={() => {setLeft(value => !value);setRight(false);}}><PanelLeft size={17}/></IconBtn>}<div className="cw-page-title"><span className="cw-breadcrumb">{t('projectManagement')}<ChevronRight size={11}/>{t(title)}</span><h1>{t(title)}</h1></div>{workspace && <><span className="cw-divider"/><span className="cw-equipment">{context?.context.displayName}</span>{context && <Badge tone="amber">{t('demo')}</Badge>}</>}<span className="cw-grow"/>{workspace && <div className="cw-layout" role="group" aria-label={t('workbenchLayout')}>{(['balanced','modelLayout','drawingLayout'] as const).map(value => <button type="button" key={value} aria-pressed={layout === value} className={layout === value ? 'active' : ''} onClick={() => setLayout(value)}>{t(value)}</button>)}</div>}<IconBtn label={t('refresh')} disabled={!active || loading} onClick={refresh}><RefreshCw size={15} className={loading ? 'cw-spin' : ''}/></IconBtn>{workspace && <IconBtn label={t('details')} onClick={() => {setRight(value => !value);setLeft(false);}}><PanelRight size={17}/></IconBtn>}</div>
      {(loading || !!error || message) && <div className="cw-notice" role={error ? 'alert' : 'status'}><span>{loading ? t('loading') : error ? failureMessage(error,locale) : message ? t(message) : ''}</span>{!!error && active && <Btn onClick={refresh}>{t('retry')}</Btn>}</div>}
      {!workspace && <div className="cw-page-content"><section className="cw-panel"><header><strong>{t(page === 'project' ? 'access' : 'modelCenter')}</strong></header><div className="cw-page-body">{page === 'project' ? <><dl className="cw-kv"><dt>{t('currentProject')}</dt><dd>{context?.projectName || '—'}</dd><dt>{t('username')}</dt><dd>{session?.username || '—'}</dd><dt>{t('access')}</dt><dd>{active ? t('readOnly') : t('loginPrompt')}</dd></dl><Btn primary onClick={() => active ? setPage('bindings') : setModal('login')}>{t(active ? 'enter' : 'signIn')}</Btn></> : <><dl className="cw-kv"><dt>{t('modelSource')}</dt><dd>{model ? t('modelName') : '—'}</dd><dt>{t('binding')}</dt><dd>{model ? t('modelReady') : active ? t('modelUnavailable') : t('loginPrompt')}</dd><dt>{t('location')}</dt><dd>{t('geometryNote')}</dd></dl>{model && <><div className="cw-model-links">{model.bindings.map(row => <button type="button" className="cw-list-item" key={row.entityUid} onClick={() => {select(row.entityUid);setPage('bindings');}}>{row.componentKey}<span className="cw-grow"/><Badge>{row.geometryQuality === 'proxy_schematic' ? t('proxy') : t('candidate')}</Badge></button>)}</div><details className="cw-details"><summary>{t('moreInfo')}</summary><p>{t('reviewNote')}</p><p className="ov-mono">{model.sha256}</p></details></>}</>}</div></section></div>}
      <div className={`cw-workspace layout-${layout}`} hidden={!workspace}>
        <ObjectsPanel key={`${session?.sessionRevision}:${reload}:${context?.context.hierarchyRevision}`} api={api} view={context} selected={selection.uid} onSelect={select} className={left ? 'is-open' : ''}/>
        <Suspense fallback={<section className="cw-panel cw-scene"><p className="cw-state" role="status">{t('loading')}</p></section>}>{active ? <ModelViewport key={`${session?.sessionRevision}:${reload}`} api={api} active={active} detail={detail} model={model} onModel={setModel} onSelect={uid => select(uid)} focusSignal={focusSignal}/> : <section className="cw-panel cw-scene"><header><strong>{t('modelView')}</strong></header><p className="cw-state">{t('loginPrompt')}</p></section>}</Suspense>
        <aside className={`cw-panel cw-inspector ${right ? 'is-open' : ''}`}><header><strong>{detail?.item.displayName || (selection.uid ? t('loading') : t('select'))}</strong>{detail && <Badge tone={detail.item.reviewStatus === 'confirmed' ? 'neutral' : 'amber'}>{detail.item.reviewStatus === 'confirmed' ? t('confirmed') : t('unverified')}</Badge>}</header>
          {detail && context && <Tabs.Root value={tab} onValueChange={setTab}><Tabs.List className="cw-tabs" aria-label={t('details')}>{(['details','properties','drawings'] as const).map(value => <Tabs.Trigger value={value} key={value} className={tab === value ? 'active' : ''}>{t(value)}</Tabs.Trigger>)}</Tabs.List>
            <div className="cw-inspector-scroll"><Tabs.Content value="details"><dl className="cw-kv"><dt>{t('parent')}</dt><dd>{parent?.displayName || (detail.item.installationContextId ? t('noParent') : t('definition'))}</dd><dt>{t('kind')}</dt><dd>{kind ? t(kind) : t('unknown')}</dd><dt>{t('location')}</dt><dd>{host}</dd>{location && <><dt>{t('modelView')}</dt><dd>{location.binding.componentKey}</dd></>}</dl><Btn disabled={!location} onClick={() => setFocusSignal(value => value+1)}><Focus size={14}/>{t('locate')}</Btn><details className="cw-details"><summary>{t('moreInfo')}<ChevronDown size={12}/></summary><p>{t('reviewNote')}</p>{location?.mode === 'ancestor' && <p>{t('noGeometry')}</p>}{!detail.item.installationContextId && <p>{t('sourceOnly')}</p>}{detail.ancestors.completeness === 'incomplete' && <p>{t('incomplete')}</p>}</details></Tabs.Content>
            <Tabs.Content value="properties"><dl className="cw-kv"><dt>{t('objectUid')}</dt><dd className="ov-mono">{detail.item.entityUid}</dd><dt>{t('objectRevision')}</dt><dd className="ov-mono">{detail.item.entityRevision}</dd><dt>{t('template')}</dt><dd className="ov-mono">{detail.item.sourceTemplateEntityUid || t('noTemplate')}</dd></dl></Tabs.Content>
            <Tabs.Content value="drawings"><SourceEvidence key={`${selection.uid}:${detail.item.entityRevision}:${context.context.hierarchyRevision}:${session?.sessionRevision}`} api={api} object={detail.item} context={context.context} host={host}/></Tabs.Content></div>
          </Tabs.Root>}
        </aside>
      </div></main>
    </div>
    {modal === 'login' && <Modal title={t('signInTitle')} description={t('accountHint')} onClose={closeModal}><form className="ov-simple-login" onSubmit={event => {event.preventDefault();void login();}}>
      <input aria-label={t('username')} placeholder={t('username')} autoComplete="username" value={username} onChange={event => setUsername(event.target.value)} required disabled={signingIn}/><input aria-label={t('password')} placeholder={t('password')} type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} required disabled={signingIn}/>
      {loginError ? <p role="alert">{failureMessage(loginError,locale)}</p> : null}<button type="submit" className="ov-btn primary" disabled={signingIn}>{signingIn ? t('signingIn') : t('signIn')}</button>
    </form></Modal>}
    {(modal === 'account' || modal === 'project') && <Modal title={t(modal === 'account' ? 'account' : 'project')} description={t('access')} onClose={closeModal}><dl className="cw-kv"><dt>{t('username')}</dt><dd>{session?.username || '—'}</dd><dt>{t('currentProject')}</dt><dd>{context?.projectName || '—'}</dd><dt>{t('access')}</dt><dd>{active ? t('readOnly') : t('loginPrompt')}</dd></dl>{!active && <Btn primary onClick={() => setModal('login')}>{t('signIn')}</Btn>}</Modal>}
    {modal === 'model' && <Modal title={t('models')} description={t('modelView')} onClose={closeModal}><dl className="cw-kv"><dt>{t('modelSource')}</dt><dd>{t('modelName')}</dd><dt>{t('binding')}</dt><dd>{model ? t('modelReady') : t('modelUnavailable')}</dd><dt>{t('location')}</dt><dd>{t('geometryNote')}</dd></dl>{model && <div className="cw-model-links">{model.bindings.map(row => <button type="button" className="cw-list-item" key={row.entityUid} onClick={() => {select(row.entityUid);setModal(null);}}>{row.componentKey}<span className="cw-grow"/><Badge>{row.geometryQuality === 'proxy_schematic' ? t('proxy') : t('candidate')}</Badge></button>)}</div>}<details className="cw-details"><summary>{t('moreInfo')}</summary><p>{t('reviewNote')}</p><p className="ov-mono">{model?.sha256}</p></details></Modal>}
  </div>;
}
