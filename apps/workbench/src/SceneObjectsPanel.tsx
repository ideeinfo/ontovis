import {useEffect,useRef,useState} from 'react';
import {Box,ChevronDown,ChevronRight,Search} from 'lucide-react';
import {ApiError,cancelled,failureMessage,type WorkbenchApi} from './api';
import {Catalog} from './ObjectsPanel';
import {usePreferences} from './Preferences';
import {Btn,IconBtn} from './Primitives';
import {SceneApi} from './sceneApi';
import {sceneEngineeringText} from './sceneEngineeringMessages';
import type {SceneObjectChildren,SceneObjectContext} from './sceneEngineeringTypes';
import type {EngineeringObject,Installation} from './types';
import './sceneEngineering.css';

export interface SceneObjectsPanelProps {
  api:WorkbenchApi;root:SceneObjectContext|null;selectedUid:string;ancestorUids:string[];
  rootReading?:boolean;
  onSelect:(uid:string,scope:'equipment'|'project')=>void;
}

function EquipmentNode({api,object,context,selectedUid,ancestorUids,onSelect,depth=0}:{
  api:WorkbenchApi;object:EngineeringObject;context:Installation;selectedUid:string;ancestorUids:string[];
  onSelect:(uid:string)=>void;depth?:number;
}) {
  const {locale}=usePreferences(),t=(key:Parameters<typeof sceneEngineeringText>[1])=>sceneEngineeringText(locale,key);
  const [open,setOpen]=useState(depth===0||ancestorUids.includes(object.entityUid));
  const [view,setView]=useState<SceneObjectChildren|null>(null),[cursor,setCursor]=useState<string|null>(null);
  const [attempt,setAttempt]=useState(0),[loading,setLoading]=useState(false),[error,setError]=useState<unknown>(null);
  const loaded=useRef<string|null>(null),currentView=useRef(view);currentView.current=view;
  useEffect(()=>{if(ancestorUids.includes(object.entityUid))setOpen(true);},[selectedUid,ancestorUids,object.entityUid]);
  useEffect(()=>{
    const signature=JSON.stringify([cursor,attempt]);
    if(!open||!object.hasChildren||depth>=31||loaded.current===signature)return;
    const controller=new AbortController(),epoch=api.epoch,revision=api.revision;
    const active=()=>!controller.signal.aborted&&api.epoch===epoch&&api.revision===revision;
    setLoading(true);setError(null);
    new SceneApi(api).objectChildren({installationContextId:context.installationContextId,
      entityUid:object.entityUid,expectedHierarchyRevision:context.hierarchyRevision,cursor},controller.signal)
      .then(value=>{
        if(!active())return;
        if(value.installationContextId!==context.installationContextId||value.hierarchyRevision!==context.hierarchyRevision
          ||value.parentEntityUid!==object.entityUid)throw new ApiError(409,'ENGINEERING_CHANGED');
        if(!Array.isArray(value.items)||value.items.length>50||value.nextCursor!==null&&value.nextCursor===cursor)
          throw new ApiError(502,'SOURCE_UNAVAILABLE');
        const items=cursor?[...(currentView.current?.items||[]),...value.items]:value.items;
        if(new Set(items.map(item=>item.object.entityUid)).size!==items.length)throw new ApiError(502,'SOURCE_UNAVAILABLE');
        const next={...value,items};currentView.current=next;setView(next);loaded.current=signature;
      }).catch(value=>{if(active()&&!cancelled(value))setError(value);})
      .finally(()=>{if(active())setLoading(false);});
    return ()=>controller.abort();
  },[api,api.epoch,api.revision,open,cursor,attempt,context.installationContextId,context.hierarchyRevision,object.entityUid,object.hasChildren,depth]);
  const expandable=object.hasChildren&&depth<31;
  return <div role="treeitem" aria-level={depth+1} aria-expanded={expandable?open:undefined}>
    <div className="se-tree-row">{expandable?<IconBtn label={`${open?'−':'+'} ${object.displayName}`} aria-expanded={open} onClick={()=>setOpen(value=>!value)}>{open?<ChevronDown size={12}/>:<ChevronRight size={12}/>}</IconBtn>:<span className="se-tree-spacer"/>}
      <button type="button" className="se-tree-name" aria-pressed={selectedUid===object.entityUid} onClick={()=>onSelect(object.entityUid)}><Box size={14}/><span>{object.displayName}</span></button>
    </div>
    {open&&object.hasChildren&&<div role="group" className="se-tree-children" style={depth>=6?{marginLeft:0,paddingLeft:0}:undefined}>
      {view?.items.map(row=><EquipmentNode key={row.object.entityUid} api={api} object={row.object} context={context} selectedUid={selectedUid} ancestorUids={ancestorUids} onSelect={onSelect} depth={depth+1}/>)}
      {depth>=31?<p className="se-note">{t('depthLimit')}</p>:loading?<p className="se-state" role="status">{t('loading')}</p>:null}
      {!!error&&<div className="se-state" role="alert">{failureMessage(error,locale)}<Btn onClick={()=>setAttempt(value=>value+1)}>{t('retry')}</Btn></div>}
      {!loading&&!error&&view?.items.length===0&&<p className="se-note">{t('noChildren')}</p>}
      {!loading&&!error&&view?.nextCursor&&<Btn onClick={()=>setCursor(view.nextCursor)}>{t('more')}</Btn>}
    </div>}
  </div>;
}

/** Device reads always carry the selected equipment's explicit installation. */
export function SceneObjectsPanel({api,root,rootReading=false,selectedUid,ancestorUids,onSelect}:SceneObjectsPanelProps) {
  const {locale}=usePreferences(),t=(key:Parameters<typeof sceneEngineeringText>[1])=>sceneEngineeringText(locale,key);
  const [scope,setScope]=useState<'equipment'|'project'>(root?.context?'equipment':'project');
  const [query,setQuery]=useState(''),[settled,setSettled]=useState('');
  useEffect(()=>{const timer=window.setTimeout(()=>setSettled(query.trim()),250);return ()=>clearTimeout(timer);},[query]);
  useEffect(()=>{if(!root?.context&&!rootReading)setScope('project');},[root?.context,rootReading]);
  const context=root?.context,object=root?.item;
  const identity=JSON.stringify([api.epoch,api.revision,context?.installationContextId,context?.hierarchyRevision,object?.entityUid,object?.entityRevision]);
  return <section className="se-objects" aria-label={t('projectObjects')}>
    <div className="se-object-tabs" role="tablist" aria-label={t('projectObjects')}>
      <button type="button" role="tab" aria-selected={scope==='equipment'} onClick={()=>{setScope('equipment');setQuery('');setSettled('');}}>{t('equipment')}</button>
      <button type="button" role="tab" aria-selected={scope==='project'} onClick={()=>setScope('project')}>{t('projectObjects')}</button>
    </div>
    {scope==='project'&&<label className="se-search"><Search size={14}/><input aria-label={t('search')} placeholder={t('search')} value={query} onChange={event=>setQuery(event.target.value)}/></label>}
    <div className="se-object-body">{!api.revision?<p className="se-state">{t('login')}</p>:scope==='equipment'?
      rootReading?<p className="se-state" role="status">{t('loading')}</p>:context&&object?<div role="tree" aria-label={t('equipment')}><EquipmentNode key={identity} api={api} object={object} context={context} selectedUid={selectedUid} ancestorUids={ancestorUids} onSelect={uid=>onSelect(uid,'equipment')}/></div>:<p className="se-state">{t('rootRequired')}</p>:
      query.trim()!==settled?<p className="se-state" role="status">{t('loading')}</p>:<Catalog key={`${identity}:${settled}`} api={api} query={settled} scope="project" selected={selectedUid} onSelect={uid=>onSelect(uid,'project')}/>}</div>
  </section>;
}
