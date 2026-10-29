import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import * as Tabs from '@radix-ui/react-tabs';
import * as Dropdown from '@radix-ui/react-dropdown-menu';
import { Boxes, Building2, ChevronDown, ChevronRight, ClipboardList, Database, FileClock, Focus, GitBranch, Languages, Layers, LayoutDashboard, LogOut, PanelLeft, PanelLeftClose, PanelLeftOpen, PanelRight, RefreshCw, Sparkles, Sun, User } from 'lucide-react';
import logo from '../../../assets/brand/ONTOVis.png';
import { ApiError, cancelled, failureMessage, WorkbenchApi } from './api';
import type { ContextView, ModelView, ObjectView, SessionView } from './types';
import type { MessageKey } from './messages';
import { usePreferences } from './Preferences';
import { Badge, Btn, IconBtn, Modal } from './Primitives';
import { ObjectsPanel } from './ObjectsPanel';
import { ObjectHierarchy } from './ObjectHierarchy';
import { objectCategory } from './objectCatalog';
import { bindingNeedsReview, modelLocation } from './modelLocation';
import { SourceEvidence } from './SourceEvidence';
import {ProjectModelCenter} from './ProjectModelCenter';
import { BindingEditor } from './BindingEditor';
import type {SceneWorkspaceHandle} from './SceneWorkspace';
import {SceneApi} from './sceneApi';
import {LegacySceneEntryReader} from './legacySceneEntry';
import type {LegacySceneEntryTarget} from './sceneTypes';
import {LandingPage} from './LandingPage';
import {ProjectsPanel} from './ProjectsPanel';
import {EquipmentHierarchy} from './EquipmentHierarchy';
import type {ProjectAccess,ProjectRef,ProjectSummary} from './projectTypes';
import {canNavigate,isGlobalPage,workbenchHeader,type WorkbenchPage} from './workbenchNavigation';
import {keepWorkspaceOnSessionFailure} from './sessionAvailability';

const api = new WorkbenchApi();
const ModelViewport = lazy(() => import('./ModelViewport').then(module => ({default:module.ModelViewport})));
const SceneWorkspace = lazy(() => import('./SceneWorkspace').then(module => ({default:module.SceneWorkspace})));
const WorkOrders = lazy(() => import('./WorkOrders').then(module => ({default:module.WorkOrders})));
const AnalysisWorkspace = lazy(() => import('./AnalysisWorkspace').then(module => ({default:module.AnalysisWorkspace})));
const AiPolicy = lazy(() => import('./AiPolicy').then(module => ({default:module.AiPolicy})));
const DataAlarms = lazy(() => import('./DataAlarms').then(module => ({default:module.DataAlarms})));
const navigation = [
  ['project', 'projectAccess', Building2], ['models', 'modelCenter', Boxes],
  ['hierarchy', 'equipmentHierarchy', GitBranch],
  ['scene', 'sceneSettings', Layers], ['orders', 'projectWorkOrders', ClipboardList], ['analysis', 'analysisDrafts', LayoutDashboard], ['data', 'dataAlarms', Database],
  ['ai', 'aiPolicy', Sparkles], ['audit', 'evidenceAudit', FileClock],
] as const;
type Page = WorkbenchPage;
export function Workbench() {
  const {t, locale, theme, setTheme, setLocale} = usePreferences();
  const [session, setSession] = useState<SessionView | null>(null);
  const [projectName,setProjectName]=useState('');
  const [project,setProject]=useState<ProjectSummary|null>(null);
  const [context, setContext] = useState<ContextView | null>(null);
  const [selection, setSelection] = useState({uid:'', scope:'equipment' as 'equipment' | 'project'});
  const [detail, setDetail] = useState<ObjectView | null>(null);
  const [model, setModel] = useState<ModelView | null>(null);
  const [tab, setTab] = useState('details');
  const [modal, setModal] = useState<'login' | 'account' | 'project' | 'model' | null>(null);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [signingIn, setSigningIn] = useState(false);
  const [signingOut,setSigningOut] = useState(false);
  const [sessionCheck,setSessionCheck] = useState<'loading'|'ready'|'failed'>('loading');
  const [loginError, setLoginError] = useState<unknown>(null);
  const [message, setMessage] = useState<MessageKey | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const [reload, setReload] = useState(0);
  const [left, setLeft] = useState(false), [right, setRight] = useState(false);
  const [focusSignal, setFocusSignal] = useState(0);
  const [page, setPage] = useState<Page>('project');
  const [navExpanded, setNavExpanded] = useState(false);
  const [layout, setLayout] = useState('balanced');
  const [modelVersionId,setModelVersionId] = useState<string|null>(null);
  const [modelReload,setModelReload] = useState(0);
  const [resourceSceneId,setResourceSceneId]=useState<string|undefined>();
  const [sceneEntry,setSceneEntry] = useState<LegacySceneEntryTarget|null>(null);
  const [legacyReady,setLegacyReady] = useState<string|null>(null);
  const entryIdentity=JSON.stringify([session?.sessionRevision,reload,modelVersionId,modelReload]);
  const legacyEntry=useRef(new LegacySceneEntryReader(new SceneApi(api)));
  const channel = useRef<BroadcastChannel | null>(null);
  const current = useRef(session); current.current = session;
  const mounted=useRef(true),sessionReady=useRef(false),mustSignOut=useRef(false),loginOpen=useRef(false);
  const authIntent=useRef(0),authBusy=useRef<'login'|'logout'|null>(null),inspectIntent=useRef(0);
  const inspection=useRef<{controller:AbortController;promise:Promise<SessionView|null>;activity:boolean}|null>(null);
  const pendingActivity=useRef(false),loginButton=useRef<HTMLButtonElement>(null);
  const lastActivity = useRef(0);
  const sceneWorkspace = useRef<SceneWorkspaceHandle|null>(null);
  const [ordersDirty,setOrdersDirty]=useState(false);
  const [initialOrderQuery,setInitialOrderQuery]=useState('');
  const [initialAnalysisEntry,setInitialAnalysisEntry]=useState<import('./analysisSources').AnalysisEntry|null>(null);
  const [pendingOrderLeave,setPendingOrderLeave]=useState<(()=>void)|null>(null);
  function leaveOrders(change:()=>void){if((page==='orders'||page==='analysis'||page==='hierarchy'||page==='ai')&&ordersDirty)setPendingOrderLeave(()=>change);else change();}
  function navigate(next:Page,legacyVersionId:string|null=null,orderQuery='',analysisEntry:import('./analysisSources').AnalysisEntry|null=null){
    if(!canNavigate(next,!!project))next='project';
    if(next==='bindings'&&legacyVersionId===null)next='hierarchy';
    const change=()=>{legacyEntry.current.cancel();setSceneEntry(null);setResourceSceneId(undefined);setLegacyReady(null);
      api.selectProject(next==='models'?null:project?.projectRef||null);setError(null);
      if(next==='bindings'){setModelVersionId(legacyVersionId);setModel(null);setContext(null);setDetail(null);setModelReload(value=>value+1);}
      setInitialOrderQuery(orderQuery);setInitialAnalysisEntry(analysisEntry);setPage(next);setLeft(false);setRight(false);};
    if(page==='scene'&&(next!=='scene'||sceneEntry!==null)&&sceneWorkspace.current)sceneWorkspace.current.requestLeave(change);else leaveOrders(change);
  }

  function clear(state:string, text:MessageKey | null) {
    setPendingOrderLeave(null);setOrdersDirty(false);
    sessionReady.current=false;setSessionCheck('loading');
    legacyEntry.current.cancel();setSceneEntry(null);setResourceSceneId(undefined);setLegacyReady(null);
    api.selectProject(null);setProject(null);setPage('project'); setProjectName('');setContext(null); setSelection({uid:'', scope:'equipment'}); setDetail(null); setModel(null);
    setModelVersionId(null);
    const value={state,sessionRevision:current.current?.sessionRevision||api.revision};current.current=value;setSession(value);
    setLoading(false);setModal(previous=>previous==='login'?previous:null);
    setMessage(text); setError(null);setUsername('');setPassword('');
  }
  function cancelInspection(){inspectIntent.current++;inspection.current?.controller.abort();inspection.current=null;pendingActivity.current=false;}
  async function inspect(activity = false) {
    if(authBusy.current)return null;if(inspection.current){if(activity&&!inspection.current.activity)pendingActivity.current=true;return inspection.current.promise;}
    const controller=new AbortController(),ticket=++inspectIntent.current;sessionReady.current=false;setSessionCheck('loading');
    const promise=(async()=>{
      try {
        const value=await api.request<SessionView>('/api/session'+(activity?'?activity=1':''),undefined,controller.signal);
        if(!mounted.current||controller.signal.aborted||ticket!==inspectIntent.current)return null;
        if(typeof value.sessionRevision!=='string'||!value.sessionRevision||!['active','denied','signedOut','expired'].includes(value.state))throw new ApiError(502,'SOURCE_UNAVAILABLE');
        if(mustSignOut.current&&['active','denied'].includes(value.state)){
          clear('signedOut','logoutFailed');api.session(value.sessionRevision);
          current.current={state:'signedOut',sessionRevision:value.sessionRevision};setSession(current.current);setSessionCheck('failed');
          loginOpen.current=true;setModal('login');return value;
        }
        const changed=!current.current||current.current.sessionRevision!==value.sessionRevision||current.current.state!==value.state;
        if(changed){const text=value.state==='active'?null:value.state==='denied'?'denied':value.state==='expired'?'expired':'loginPrompt';
          if(current.current)clear(value.state,text);else setMessage(text);}
        if(changed||api.revision!==value.sessionRevision)api.session(value.sessionRevision);
        const safe=value.state==='active'?value:{state:value.state,sessionRevision:value.sessionRevision};
        current.current=safe;setSession(safe);sessionReady.current=true;setSessionCheck('ready');
        if(value.state==='active')setMessage(previous=>previous==='unavailable'?null:previous);
        if(['signedOut','expired'].includes(value.state))mustSignOut.current=false;
        if(value.state==='active'){loginOpen.current=false;setModal(previous=>previous==='login'?null:previous);if(changed)setReload(value=>value+1);}
        return value;
      }catch(value){if(mounted.current&&ticket===inspectIntent.current&&!cancelled(value)){
        if(keepWorkspaceOnSessionFailure(value,current.current,mustSignOut.current))setMessage('unavailable');
        else clear('unavailable',mustSignOut.current?'logoutFailed':'unavailable');
        setSessionCheck('failed');
        if(mustSignOut.current){loginOpen.current=true;setModal('login');}}return null;}
      finally{if(ticket===inspectIntent.current){inspection.current=null;const touch=pendingActivity.current;pendingActivity.current=false;
        if(touch&&mounted.current&&current.current?.state==='active'&&!authBusy.current&&!mustSignOut.current)void inspect(true);}}
    })();
    inspection.current={controller,promise,activity};return promise;
  }
  useEffect(() => {
    mounted.current=true;
    api.onProjectDenied=()=>{api.selectProject(null);setProject(null);setProjectName('');setSceneEntry(null);setResourceSceneId(undefined);setContext(null);setDetail(null);setModel(null);setPage('project');setError(new ApiError(403,'FORBIDDEN'));};
    api.onDenied = status => {const checking=!!inspection.current;cancelInspection();clear(status === 401 ? 'expired' : 'denied', status === 401 ? 'expired' : 'denied');if(checking){setSessionCheck('failed');
      if(mustSignOut.current){setMessage('logoutFailed');loginOpen.current=true;setModal('login');}}else if(!authBusy.current)void inspect();};
    void inspect();
    channel.current = new BroadcastChannel('ontovis-workbench-session');
    channel.current.onmessage = () => {cancelInspection();clear('signedOut', 'sessionChanged');void inspect();};
    const poll = window.setInterval(() => {void inspect();}, 30000);
    const activity = () => {
      if (current.current?.state === 'active' && Date.now()-lastActivity.current > 60000) {
        lastActivity.current = Date.now(); void inspect(true);
      }
    };
    window.addEventListener('pointerdown',activity); window.addEventListener('keydown',activity);
    const visible = () => {if (!document.hidden) void inspect();}; document.addEventListener('visibilitychange',visible);
    return () => {mounted.current=false;authIntent.current++;cancelInspection();window.clearInterval(poll); channel.current?.close(); api.onDenied=() => {};api.onProjectDenied=()=>{};
      window.removeEventListener('pointerdown',activity); window.removeEventListener('keydown',activity);
      document.removeEventListener('visibilitychange',visible); legacyEntry.current.cancel();api.invalidate();};
  }, []);
  useEffect(() => {
    if (session?.state !== 'active'||page!=='bindings'||!project) {setLoading(false);if(page==='scene')setError(null);return;}
    const controller = new AbortController(); setLoading(true); setMessage(null); setError(null);
    const read=async()=>{
      if(page==='bindings'){
        setLegacyReady(null);
        const target=await legacyEntry.current.read(modelVersionId);
        if(controller.signal.aborted)return;
        if(target){setSceneEntry(target);setContext(null);setDetail(null);setModel(null);setPage('scene');return;}
        setLegacyReady(entryIdentity);
      }
      const value=await api.request<ContextView>('/api/workbench/context', {}, controller.signal);
      if(!controller.signal.aborted){setContext(value);setProjectName(value.projectName);if(value.root)setSelection({uid:value.root.entityUid,scope:'equipment'});}
    };
    void read()
      .catch(value => {if (!controller.signal.aborted&&!cancelled(value)) {setContext(null); setError(value);}})
      .finally(() => {if (!controller.signal.aborted) setLoading(false);});
    return () => {controller.abort();legacyEntry.current.cancel();};
  }, [session?.state, session?.sessionRevision, reload,page,modelVersionId,modelReload]);
  useEffect(() => {
    setDetail(null);
    if (!selection.uid || !context || session?.state !== 'active'||!['bindings','hierarchy'].includes(page)) return;
    const controller = new AbortController(); setError(null);
    api.request<ObjectView>('/api/workbench/object', {entityUid:selection.uid, scope:selection.scope,
      expectedHierarchyRevision:context.context.hierarchyRevision}, controller.signal)
      .then(value=>{if(!controller.signal.aborted)setDetail(value);}).catch(value => {if (!controller.signal.aborted&&!cancelled(value)) {
        if (value instanceof ApiError && value.status === 409) {setContext(null); setSelection({uid:'',scope:'equipment'});}
        setError(value);
      }});
    return () => controller.abort();
  }, [selection, context, session?.state, session?.sessionRevision,page]);
  async function login() {
    if(authBusy.current||!sessionReady.current||!current.current||!['signedOut','expired'].includes(current.current.state)||
      !api.revision||current.current.sessionRevision!==api.revision||mustSignOut.current)return;
    const ticket=++authIntent.current;authBusy.current='login';cancelInspection();setSigningIn(true);setLoginError(null);let accepted=false;
    try {
      const value = await api.request<SessionView>('/api/session/login', {username, password});
      if(!mounted.current||ticket!==authIntent.current)return;
      if(typeof value.sessionRevision!=='string'||!value.sessionRevision||!['active','denied'].includes(value.state))throw new ApiError(502,'SOURCE_UNAVAILABLE');
      clear(value.state,value.state==='denied'?'denied':null);api.session(value.sessionRevision);
      current.current=value.state==='active'?value:{state:value.state,sessionRevision:value.sessionRevision};setSession(current.current);
      sessionReady.current=true;setSessionCheck('ready');accepted=true;
      loginOpen.current=value.state!=='active';setModal(value.state==='active'?null:'login');
      setReload(value => value+1); channel.current?.postMessage('session-changed');
    } catch (value) {if(mounted.current&&ticket===authIntent.current&&!cancelled(value))setLoginError(value);}
    finally {if(mounted.current&&ticket===authIntent.current){authBusy.current=null;setPassword('');setSigningIn(false);if(!accepted)void inspect();}}
  }
  async function logout(keepLogin=false) {
    const ticket=++authIntent.current,revision=api.revision;authBusy.current='logout';mustSignOut.current=true;cancelInspection();
    setSigningIn(false);setSigningOut(true);loginOpen.current=keepLogin;clear('signedOut','loginPrompt');setModal(keepLogin?'login':null);
    channel.current?.postMessage('session-changed');
    try {if(revision)await api.request('/api/session/logout',{expectedSessionRevision:revision});}
    catch(value){if(mounted.current&&ticket===authIntent.current&&!cancelled(value))setMessage('logoutFailed');}
    finally{if(mounted.current&&ticket===authIntent.current){authBusy.current=null;setSigningOut(false);await inspect();}}
  }
  async function openLogin(){
    loginOpen.current=true;setLoginError(null);setModal('login');if(authBusy.current)return;
    if(mustSignOut.current||current.current?.state==='denied'){await logout(true);return;}
    if(!sessionReady.current){const value=await inspect();if(!loginOpen.current)return;
      if(value?.state==='denied')await logout(true);else if(value?.state==='active'){loginOpen.current=false;setModal(null);}}
  }
  function closeModal(){loginOpen.current=false;setModal(null);setPassword('');if(authBusy.current==='login')void logout();}
  function refresh() {
    const change=()=>{legacyEntry.current.cancel();api.invalidate();setLegacyReady(null);
      if(page==='scene'&&sceneEntry){setSceneEntry(null);setPage('bindings');}
      setContext(null); setDetail(null); setSelection({uid:'',scope:'equipment'}); setModel(null); setReload(value => value+1);};
    if(page==='scene'&&sceneWorkspace.current)sceneWorkspace.current.requestLeave(change);else leaveOrders(change);
  }
  function enterProject(value:ProjectSummary,sceneId?:string){
    legacyEntry.current.cancel();api.selectProject(value.projectRef);setProject(value);setProjectName(value.displayName);setSceneEntry(null);setResourceSceneId(sceneId);setContext(null);setDetail(null);setModel(null);setSelection({uid:'',scope:'project'});setPage('scene');setReload(v=>v+1);
  }
  function chooseProject(value:ProjectSummary,_access?:ProjectAccess){
    const change=()=>enterProject(value);
    if(page==='scene'&&sceneWorkspace.current)sceneWorkspace.current.requestLeave(change);else change();
  }
  async function openModelScene(sceneId?:string,projectRef?:ProjectRef){
    if(!sceneId||!projectRef){navigate(project?'scene':'project');return;}
    const revision=api.revision;
    try{
      const access=await api.request<ProjectAccess>('/api/workbench/projects/access',{projectRef});
      if(revision!==api.revision||current.current?.state!=='active')return;
      enterProject({projectRef,displayName:access.projectName,sourceDescription:'',status:'active',
        workspaceState:'ready',sceneCount:0},sceneId);
    }catch(value){if(!cancelled(value))setError(value);}
  }
  function select(uid:string, scope:'equipment' | 'project' = 'equipment') {
    setDetail(null); setSelection({uid,scope}); setLeft(false);
  }
  const active = session?.state === 'active'&&!mustSignOut.current;
  const canLogin=sessionCheck==='ready'&&sessionReady.current&&!!session?.sessionRevision&&session.sessionRevision===api.revision&&
    ['signedOut','expired'].includes(session.state)&&!mustSignOut.current&&!signingIn&&!signingOut;
  const location = modelLocation(detail,model);
  const host = bindingNeedsReview(detail,model) ? t('bindingChanged') : location ? location.mode === 'ancestor' ? t('ancestor') : location.binding.geometryQuality === 'proxy_schematic' ? t('proxy') : t('candidate') : !!model && detail?.item.entityUid === model.rootEntityUid ? t('modelReady') : t('unlocated');
  const [,title,ModuleIcon] = navigation.find(row => row[0] === page)!;
  const header=workbenchHeader(page,t(title),projectName||project?.displayName||'');
  const workspace = page === 'bindings';
  return <>{!active&&<LandingPage onLogin={()=>void openLogin()} videoSrc={import.meta.env.VITE_LOGIN_VIDEO_SRC} posterSrc={import.meta.env.VITE_LOGIN_POSTER_SRC} suspended={modal==='login'} loginButtonRef={loginButton}/>}{active&&<div className="ov-app ov-compact">
    <header className="cw-header"><a className="cw-brand" href="#project" onClick={event => {event.preventDefault();navigate('project');}} aria-label="ONTOVis"><img src={logo} alt="ONTOVis 本源数智" fetchPriority="high"/></a><span className="cw-divider"/>
      {isGlobalPage(page)?<span className="cw-project" title={header}><ModuleIcon size={15}/><span>{header}</span></span>:<button className="cw-project" type="button" title={header} onClick={() => navigate('project')}><ModuleIcon size={15}/><span>{header}</span><ChevronDown size={12}/></button>}<span className="cw-grow"/>
      {active ? <Dropdown.Root><Dropdown.Trigger asChild><button type="button" className="cw-avatar" aria-label={t('account')}>{session?.username?.slice(0,2).toUpperCase() || <User size={16}/>}</button></Dropdown.Trigger><Dropdown.Portal><Dropdown.Content className="cw-menu ov-list-menu" align="end" sideOffset={8}>
        <div className="cw-user-info"><strong>{session?.username}</strong><span className="cw-caption">{projectName}</span></div>
        <Dropdown.Item className="ov-list-menu-item" onSelect={() => setModal('account')}><User size={15}/>{t('account')}</Dropdown.Item><Dropdown.Separator className="ov-list-menu-separator"/>
        <div className="cw-preference"><span><Languages size={14}/>{t('language')}</span><Dropdown.RadioGroup value={locale} onValueChange={value => setLocale(value as 'zh' | 'en')}><Dropdown.RadioItem value="zh">简体中文</Dropdown.RadioItem><Dropdown.RadioItem value="en">English</Dropdown.RadioItem></Dropdown.RadioGroup></div>
        <div className="cw-preference"><span><Sun size={14}/>{t('theme')}</span><Dropdown.RadioGroup value={theme} onValueChange={value => setTheme(value as 'light' | 'dark' | 'system')}>{(['light','system','dark'] as const).map(value => <Dropdown.RadioItem key={value} value={value}>{t(value)}</Dropdown.RadioItem>)}</Dropdown.RadioGroup></div>
        <Dropdown.Separator className="ov-list-menu-separator"/><Dropdown.Item className="ov-list-menu-item" onSelect={() => leaveOrders(()=>void logout())}><LogOut size={15}/>{t('signOut')}</Dropdown.Item>
      </Dropdown.Content></Dropdown.Portal></Dropdown.Root> : <Btn onClick={() => {setLoginError(null);setModal('login');}}>{t('signIn')}</Btn>}
    </header>
    <div className="cw-shell"><nav className="cw-navigation" data-expanded={navExpanded} aria-label={t('projectManagement')} onKeyDown={event => {if (event.key === 'Escape' && navExpanded) {setNavExpanded(false);event.currentTarget.querySelector<HTMLButtonElement>('.cw-nav-toggle')?.focus();}}}>
      <div className="cw-nav-header"><span className="cw-nav-heading">{t('projectManagement')}</span><button type="button" className="cw-nav-toggle" aria-label={t(navExpanded ? 'collapseNavigation' : 'expandNavigation')} title={t(navExpanded ? 'collapseNavigation' : 'expandNavigation')} aria-expanded={navExpanded} aria-controls="cw-navigation-items" onClick={() => setNavExpanded(value => !value)}>{navExpanded ? <PanelLeftClose size={17}/> : <PanelLeftOpen size={17}/>}</button></div>
      <div className="cw-nav-items" id="cw-navigation-items">{navigation.map(([id,label,Icon]) => <button type="button" key={id} className={`cw-nav-item ${page === id ? 'active' : ''}`} aria-label={t(label)} aria-current={page === id ? 'page' : undefined} disabled={!canNavigate(id,!!project)} title={t(label)} onClick={() => {if(canNavigate(id,!!project))navigate(id);}}><Icon size={17} strokeWidth={1.7}/><span>{t(label)}</span></button>)}</div>
    </nav>
      <main className="cw-main"><div className="cw-toolbar">{workspace && <IconBtn label={t('objects')} onClick={() => {setLeft(value => !value);setRight(false);}}><PanelLeft size={17}/></IconBtn>}<div className="cw-page-title"><span className="cw-breadcrumb">{t('projectManagement')}<ChevronRight size={11}/>{t(title)}</span><h1>{t(title)}</h1></div>{workspace && <><span className="cw-divider"/><span className="cw-equipment">{context?.context.displayName}</span>{context && <Badge tone="amber">{t('demo')}</Badge>}</>}<span className="cw-grow"/>{workspace && <div className="cw-layout" role="group" aria-label={t('workbenchLayout')}>{(['balanced','modelLayout','drawingLayout'] as const).map(value => <button type="button" key={value} aria-pressed={layout === value} className={layout === value ? 'active' : ''} onClick={() => setLayout(value)}>{t(value)}</button>)}</div>}<IconBtn label={t('refresh')} disabled={!active || loading} onClick={refresh}><RefreshCw size={15} className={loading ? 'cw-spin' : ''}/></IconBtn>{workspace && <IconBtn label={t('details')} onClick={() => {setRight(value => !value);setLeft(false);}}><PanelRight size={17}/></IconBtn>}</div>
      {(loading || !!error || message) && <div className="cw-notice" role={error ? 'alert' : 'status'}><span>{loading ? t('loading') : error ? failureMessage(error,locale) : message ? t(message) : ''}</span>{!!error && active && <Btn onClick={refresh}>{t('retry')}</Btn>}{!error&&active&&message==='unavailable'&&sessionCheck==='failed'&&<Btn onClick={()=>void inspect()}>{t('retry')}</Btn>}</div>}
      {page==='scene'&&active&&project&&<Suspense fallback={<p className="cw-state" role="status">{t('loading')}</p>}><SceneWorkspace key={`${session?.sessionRevision}:${JSON.stringify(project?.projectRef)}:${reload}:${sceneEntry?.sceneId||''}:${sceneEntry?.sceneRevision||''}:${resourceSceneId||''}`} api={api} ref={sceneWorkspace} initialEntry={sceneEntry} initialSceneId={resourceSceneId} project={project} onProjectCreated={enterProject} onProjectName={setProjectName} onConfigure={()=>navigate('hierarchy')}/></Suspense>}
      {page==='orders'&&active&&project&&<Suspense fallback={<p className="cw-state" role="status">{t('loading')}</p>}><WorkOrders key={`${session?.sessionRevision}:${JSON.stringify(project.projectRef)}:${reload}`} api={api} locale={locale} initialQuery={initialOrderQuery} onDirtyChange={setOrdersDirty} onAnalyze={orderId=>navigate('analysis',null,'',{orderId})} onOpenAnalysis={(analysisSessionId,analysisRevision)=>navigate('analysis',null,'',{analysisSessionId,analysisRevision})}/></Suspense>}
      {page==='analysis'&&active&&project&&<Suspense fallback={<p className="cw-state" role="status">{t('loading')}</p>}><AnalysisWorkspace initialEntry={initialAnalysisEntry} onOpenWorkOrder={code=>navigate('orders',null,code)} key={`${session?.sessionRevision}:${JSON.stringify(project.projectRef)}:${reload}`} api={api} locale={locale} onDirtyChange={setOrdersDirty}/></Suspense>}
      {page==='data'&&active&&project&&<Suspense fallback={<p className="cw-state" role="status">{t('loading')}</p>}><DataAlarms onAnalyze={entry=>navigate('analysis',null,'',entry)} key={`${session?.sessionRevision}:${JSON.stringify(project.projectRef)}:${reload}`} api={api} locale={locale} onOpenWorkOrders={code=>navigate('orders',null,code)}/></Suspense>}
      {page==='ai'&&active&&project&&<Suspense fallback={<p className="cw-state" role="status">{t('loading')}</p>}><AiPolicy key={`${session?.sessionRevision}:${JSON.stringify(project.projectRef)}:${reload}`} api={api} en={locale==='en'} onDirtyChange={setOrdersDirty}/></Suspense>}
      {!workspace&&page!=='ai'&&page!=='scene'&&page!=='orders'&&page!=='analysis'&&page!=='data'&&<div className="cw-page-content">{page==='models'&&active?<ProjectModelCenter key={`${session?.sessionRevision}:${reload}`} api={api} onConfigure={()=>navigate('hierarchy')} onOpenScene={(sceneId,ref)=>void openModelScene(sceneId,ref)}/>:page==='hierarchy'&&active&&project?<EquipmentHierarchy key={JSON.stringify(project.projectRef)} api={api} onDirtyChange={setOrdersDirty} onOpenScene={()=>navigate('scene')} onAnalyze={entry=>navigate('analysis',undefined,undefined,entry)}/>:active?<ProjectsPanel key={`${session?.sessionRevision}:${reload}`} api={api} onSelect={chooseProject}/>:null}</div>}
      {page==='scene'&&!active&&<p className="cw-state">{t('loginPrompt')}</p>}
      {workspace&&(!active||legacyReady===entryIdentity)&&<div className={`cw-workspace layout-${layout}`}>
        <ObjectsPanel key={`${session?.sessionRevision}:${reload}:${context?.context.hierarchyRevision}`} api={api} view={context} selected={selection.uid} ancestors={detail?.ancestors.path.map(row=>row.object.entityUid) || []} onSelect={select} className={left ? 'is-open' : ''}/>
        <Suspense fallback={<section className="cw-panel cw-scene"><p className="cw-state" role="status">{t('loading')}</p></section>}>{active&&workspace ? <ModelViewport key={`${session?.sessionRevision}:${reload}:${modelVersionId}:${modelReload}`} api={api} active={active&&workspace} detail={detail} model={model} modelVersionId={modelVersionId} onModel={setModel} onSelect={uid => select(uid)} focusSignal={focusSignal}/> : <section className="cw-panel cw-scene"><header><strong>{t('modelView')}</strong></header><p className="cw-state">{t('loginPrompt')}</p></section>}</Suspense>
        <aside className={`cw-panel cw-inspector ${right ? 'is-open' : ''}`}><header><strong>{detail?.item.displayName || (selection.uid ? t('loading') : t('select'))}</strong>{detail && <Badge tone={detail.item.reviewStatus === 'confirmed' ? 'neutral' : 'amber'}>{detail.item.reviewStatus === 'confirmed' ? t('confirmed') : t('unverified')}</Badge>}</header>
          {detail && context && <Tabs.Root value={tab} onValueChange={setTab}><Tabs.List className="cw-tabs" aria-label={t('details')}>{(['details','properties','drawings'] as const).map(value => <Tabs.Trigger value={value} key={value} className={tab === value ? 'active' : ''}>{t(value)}</Tabs.Trigger>)}</Tabs.List>
            <div className="cw-inspector-scroll"><Tabs.Content value="details"><dl className="cw-kv"><dt>{t('equipmentHierarchy')}</dt><dd><ObjectHierarchy detail={detail} onSelect={uid=>select(uid)}/></dd><dt>{t('category')}</dt><dd>{objectCategory(detail.item,locale)}</dd><dt>{t('location')}</dt><dd>{host}</dd>{location && <><dt>{t('modelView')}</dt><dd>{location.binding.displayName || location.binding.componentKey}</dd></>}</dl><Btn disabled={!location} onClick={() => setFocusSignal(value => value+1)}><Focus size={14}/>{t('locate')}</Btn><details className="cw-details"><summary>{t('moreInfo')}<ChevronDown size={12}/></summary><p>{t('reviewNote')}</p>{detail.item.classification && detail.item.classification.reviewState!=='confirmed' && <p>{t('classificationUnverified')}</p>}{location?.mode === 'ancestor' && <p>{t('noGeometry')}</p>}{!detail.item.installationContextId && <p>{t('sourceOnly')}</p>}{detail.ancestors.completeness === 'incomplete' && <p>{t('incomplete')}</p>}</details>{modelVersionId && detail.item.objectKind==='cabinet' && <BindingEditor key={selection.uid} api={api} model={model} object={detail.item} context={context.context} onReload={()=>setModelReload(v=>v+1)}/>}</Tabs.Content>
            <Tabs.Content value="properties"><dl className="cw-kv"><dt>{t('objectUid')}</dt><dd className="ov-mono">{detail.item.entityUid}</dd><dt>{t('objectRevision')}</dt><dd className="ov-mono">{detail.item.entityRevision}</dd><dt>{t('template')}</dt><dd className="ov-mono">{detail.item.sourceTemplateEntityUid || t('noTemplate')}</dd></dl></Tabs.Content>
            <Tabs.Content value="drawings"><SourceEvidence key={`${selection.uid}:${detail.item.entityRevision}:${context.context.hierarchyRevision}:${session?.sessionRevision}`} api={api} object={detail.item} context={context.context} host={host}/></Tabs.Content></div>
          </Tabs.Root>}
        </aside>
      </div>}</main>
    </div></div>}
    {pendingOrderLeave&&<Modal title={page==='ai'?(locale==='zh'?'策略修改尚未生效':'Unapplied policy changes'):page==='hierarchy'?(locale==='zh'?'共享配置尚未保存':'Unsaved equipment configuration'):page==='analysis'?(locale==='zh'?'分析修改尚未保存':'Unsaved analysis changes'):(locale==='zh'?'诊断方案尚未保存':'Unsaved investigation')} description={locale==='zh'?'继续离开将放弃当前未保存的修改。':'Leaving discards the current unsaved edits.'} onClose={()=>setPendingOrderLeave(null)}><div className="wo-actions"><Btn onClick={()=>setPendingOrderLeave(null)}>{locale==='zh'?'继续编辑':'Continue editing'}</Btn><Btn onClick={()=>{const change=pendingOrderLeave;setPendingOrderLeave(null);setOrdersDirty(false);change();}}>{locale==='zh'?'放弃修改并离开':'Discard and leave'}</Btn></div></Modal>}
    {modal === 'login' && <Modal className="ov-login-dialog" title={t('signInTitle')} description={t('accountHint')} onClose={closeModal} onCloseAutoFocus={event=>{if(loginButton.current){event.preventDefault();loginButton.current.focus();}}}><form className="ov-simple-login" onSubmit={event => {event.preventDefault();void login();}}>
      <input aria-label={t('username')} placeholder={t('username')} autoComplete="username" value={username} onChange={event => setUsername(event.target.value)} required disabled={signingIn||signingOut}/><input aria-label={t('password')} placeholder={t('password')} type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} required disabled={signingIn||signingOut}/>
      {(sessionCheck==='loading'||signingOut)&&!signingIn&&<p role="status">{t('loading')}</p>}
      {sessionCheck==='failed'&&<p role="alert">{t(mustSignOut.current?'logoutFailed':'unavailable')} <Btn disabled={signingOut} onClick={()=>void openLogin()}>{t('retry')}</Btn></p>}
      {sessionCheck==='ready'&&session?.state==='denied'&&<p role="alert">{t('denied')} <Btn onClick={()=>void logout(true)}>{t('signOut')}</Btn></p>}
      {loginError ? <p role="alert">{failureMessage(loginError,locale)}</p> : null}<button type="submit" className="ov-btn primary" disabled={!canLogin}>{signingIn ? t('signingIn') : t('signIn')}</button>
    </form></Modal>}
    {active&&(modal === 'account' || modal === 'project') && <Modal title={t(modal === 'account' ? 'account' : 'project')} description={t('access')} onClose={closeModal}><dl className="cw-kv"><dt>{t('username')}</dt><dd>{session?.username || '—'}</dd><dt>{t('currentProject')}</dt><dd>{projectName || '—'}</dd><dt>{t('access')}</dt><dd>{active ? t('projectReadable') : t('loginPrompt')}</dd></dl></Modal>}
    {active&&modal === 'model' && <Modal title={t('models')} description={t('modelView')} onClose={closeModal}><dl className="cw-kv"><dt>{t('modelSource')}</dt><dd>{t('modelName')}</dd><dt>{t('binding')}</dt><dd>{model ? t('modelReady') : t('modelUnavailable')}</dd><dt>{t('location')}</dt><dd>{t('geometryNote')}</dd></dl>{model && <div className="cw-model-links">{model.bindings.map(row => <button type="button" className="cw-list-item" key={row.entityUid} onClick={() => {select(row.entityUid);setModal(null);}}>{row.componentKey}<span className="cw-grow"/><Badge>{row.geometryQuality === 'proxy_schematic' ? t('proxy') : t('candidate')}</Badge></button>)}</div>}<details className="cw-details"><summary>{t('moreInfo')}</summary><p>{t('reviewNote')}</p><p className="ov-mono">{model?.sha256}</p></details></Modal>}
  </>;
}
