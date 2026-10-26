import {useEffect,useRef,useState} from 'react';
import {Building2,ExternalLink,Info,Search} from 'lucide-react';
import {RowActions,RowContext,type ListAction} from './ListMenus';
import {cancelled,failureMessage,type WorkbenchApi} from './api';
import {Btn} from './Primitives';
import {usePreferences} from './Preferences';
import type {ProjectAccess,ProjectDirectory,ProjectSummary} from './projectTypes';
import './projects.css';

export function ProjectsPanel({api,onSelect}:{api:WorkbenchApi;onSelect:(project:ProjectSummary,access:ProjectAccess)=>void}){
  const {locale}=usePreferences(),en=locale==='en';
  const [query,setQuery]=useState(''),[attempt,setAttempt]=useState(0);
  const [value,setValue]=useState<ProjectDirectory|null>(null),[access,setAccess]=useState<ProjectAccess|null>(null);
  const [selected,setSelected]=useState<ProjectSummary|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState<unknown>(null);
  const accessRequest=useRef<AbortController|null>(null);
  useEffect(()=>()=>accessRequest.current?.abort(),[api]);
  useEffect(()=>{
    accessRequest.current?.abort();setBusy(false);
    const abort=new AbortController();setValue(null);setError(null);setAccess(null);setSelected(null);
    void api.request<ProjectDirectory>('/api/workbench/projects',{q:query},abort.signal).then(result=>{if(!abort.signal.aborted)setValue(result);})
      .catch(error=>{if(!cancelled(error)&&!abort.signal.aborted)setError(error);});
    return()=>abort.abort();
  },[api,attempt]);
  async function choose(project:ProjectSummary){
    accessRequest.current?.abort();const abort=new AbortController();accessRequest.current=abort;
    setBusy(true);setError(null);setSelected(project);setAccess(null);
    try{const result=await api.request<ProjectAccess>('/api/workbench/projects/access',{projectRef:project.projectRef},abort.signal);if(!abort.signal.aborted){setAccess(result);return result;}}
    catch(error){if(!abort.signal.aborted&&!cancelled(error))setError(error);}finally{if(!abort.signal.aborted)setBusy(false);}
    return null;
  }
  async function enter(project:ProjectSummary){const grant=await choose(project);if(grant&&project.workspaceState!=='blocked')onSelect(project,grant);}
  async function more(){
    if(!value?.nextCursor)return;setBusy(true);
    try{const next=await api.request<ProjectDirectory>('/api/workbench/projects',{q:query,cursor:value.nextCursor});setValue({...next,items:[...value.items,...next.items]});}
    catch(error){if(!cancelled(error))setError(error);}finally{setBusy(false);}
  }
  return <section className="pv-directory" aria-label={en?'Projects and access':'项目与访问'}>
    <div className="pv-heading"><div><h2>{en?'OntoBase projects':'OntoBase 项目'}</h2><p>{en?'Choose a project to manage its scenes and model resources.':'选择项目，管理该项目的场景和模型资源。'}</p></div><form onSubmit={event=>{event.preventDefault();setAttempt(v=>v+1);}}><label><Search size={15}/><input aria-label={en?'Search projects':'搜索项目'} placeholder={en?'Project name or code':'项目名称或代码'} value={query} onChange={event=>setQuery(event.target.value)}/></label><Btn disabled={busy} onClick={()=>setAttempt(v=>v+1)}>{en?'Search':'搜索'}</Btn></form></div>
    {error?<p role="alert">{failureMessage(error,locale)} <Btn onClick={()=>setAttempt(v=>v+1)}>{en?'Retry':'重试'}</Btn></p>:null}
    {!value&&!error&&<p role="status">{en?'Loading projects…':'正在读取项目…'}</p>}
    {value?.items.length===0&&<p className="pv-empty">{en?'No accessible projects.':'暂无可访问项目。'}</p>}
    {value&&value.items.length>0&&<div className="pv-columns"><ul className="pv-projects ov-list" aria-label={en?'Project directory':'项目目录'}>{value.items.map(project=>{
      const active=selected?.projectRef.projectCode===project.projectRef.projectCode;
      const actions:ListAction[]=[{id:'access',label:en?'View access':'查看项目权限',icon:<Info/>,disabled:busy,onSelect:()=>void choose(project)},
        {id:'enter',label:en?'Enter project':'进入项目',icon:<ExternalLink/>,disabled:busy||project.workspaceState==='blocked',onSelect:()=>void enter(project)}];
      return <RowContext key={JSON.stringify(project.projectRef)} name={project.displayName} actions={actions} disabled={busy}><li className={`ov-list-item${active?' selected':''}`}><button type="button" className="pv-project ov-list-main" aria-pressed={active} disabled={busy} onClick={()=>void choose(project)}><Building2 size={18}/><span className="ov-list-copy"><strong>{project.displayName}</strong><small>{project.projectRef.projectCode}</small></span><span className="pv-count">{project.sceneCount} {en?'scenes':'个场景'}</span></button><RowActions name={project.displayName} actions={actions} locale={locale} disabled={busy}/></li></RowContext>;
    })}{value.nextCursor&&<li><Btn disabled={busy} onClick={()=>void more()}>{en?'Load more':'加载更多'}</Btn></li>}</ul><aside className="pv-access">{selected?<><h3>{selected.displayName}</h3><dl><dt>{en?'Project code':'项目代码'}</dt><dd>{selected.projectRef.projectCode}</dd><dt>{en?'Scenes':'场景'}</dt><dd>{selected.sceneCount}</dd><dt>{en?'Your access':'本人权限'}</dt><dd>{busy?(en?'Checking…':'正在核对…'):access?(access.role==='admin'?(en?'Project administrator':'项目管理员'):(en?'Read access':'可查看')):'—'}</dd></dl>{selected.sourceDescription&&<p>{selected.sourceDescription}</p>}<Btn primary disabled={busy||!access||selected.workspaceState==='blocked'} onClick={()=>{if(access)onSelect(selected,access);}}>{en?'Enter project':'进入项目'}</Btn>{selected.workspaceState==='blocked'&&<p role="alert">{en?'Project storage requires review.':'项目存储归属需要核对。'}</p>}</>:<p>{en?'Select a project to check your access.':'选择项目，查看本人权限和场景。'}</p>}</aside></div>}
  </section>;
}
