import { useEffect, useId, useRef, useState } from 'react';
import { Box, ChevronDown, ChevronRight, Search } from 'lucide-react';
import * as Tabs from '@radix-ui/react-tabs';
import { ApiError, cancelled, failureMessage, type WorkbenchApi } from './api';
import { usePreferences } from './Preferences';
import { Btn, IconBtn } from './Primitives';
import {RowContext} from './ListMenus';
import { categoryLabel } from './objectCatalog';
import type { CatalogGroup, GroupedCatalogView, CatalogView, ChildrenView, ContextView, EngineeringObject, Installation } from './types';

function TreeNode({api, object, context, selected, ancestors, onSelect, seed, depth = 0}: {
  api: WorkbenchApi; object: EngineeringObject; context: Installation; selected: string; ancestors:string[];
  onSelect:(uid: string) => void; seed?: ChildrenView | null; depth?: number;
}) {
  const {t, locale} = usePreferences();
  const [open, setOpen] = useState(!!seed);
  const reveal = ancestors.includes(object.entityUid);
  useEffect(() => {if (reveal) setOpen(true);}, [selected, reveal]);
  const [children, setChildren] = useState(seed || null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!open || !object.hasChildren || children && !cursor && !retry) return;
    const controller = new AbortController(); setLoading(true); setError(null);
    api.request<ChildrenView>('/api/workbench/children', {parentEntityUid:object.entityUid,
      cursor, expectedHierarchyRevision:context.hierarchyRevision}, controller.signal)
      .then(value => setChildren(previous => ({...value, items:cursor ? [...(previous?.items || []), ...value.items] : value.items})))
      .catch(value => {if (!cancelled(value)) setError(value);})
      .finally(() => {if (!controller.signal.aborted) setLoading(false);});
    return () => controller.abort();
  }, [open, cursor, retry]);
  return <div className="cw-tree-node"><div className="cw-tree-row">
    {object.hasChildren && depth < 31 ? <IconBtn label={`${open ? '−' : '+'} ${object.displayName}`} aria-expanded={open} onClick={() => setOpen(value => !value)}>{open ? <ChevronDown size={12}/> : <ChevronRight size={12}/>}</IconBtn> : <span className="cw-leaf"/>}
    <RowContext name={object.displayName} actions={[{id:'view',label:locale==='zh'?'查看对象':'View object',icon:<Box/>,onSelect:()=>onSelect(object.entityUid)}]}><button className={`cw-tree-item ${selected === object.entityUid ? 'active' : ''}`} aria-pressed={selected===object.entityUid} type="button" onClick={() => onSelect(object.entityUid)}><Box size={14}/><span>{object.displayName}</span></button></RowContext>
  </div>{open && object.hasChildren && <div className="cw-branch">
    {children?.items.map(row => <TreeNode key={row.object.entityUid} api={api} object={row.object} context={context} selected={selected} ancestors={ancestors} onSelect={onSelect} depth={depth + 1}/>)}
    {loading && <p className="cw-state" role="status">{t('loading')}</p>}
    {error ? <div role="alert" className="cw-state">{failureMessage(error, locale)}<Btn onClick={() => setRetry(value => value + 1)}>{t('retry')}</Btn></div> : null}
    {!loading && children?.nextCursor && <Btn onClick={() => setCursor(children.nextCursor)}>{t('more')}</Btn>}
  </div>}</div>;
}

function Category({api, group, query, scope, snapshot, seed, selected, onSelect, onReload}: {
  api:WorkbenchApi; group:CatalogGroup; query:string; scope:string; snapshot:string; seed:CatalogView|null;
  selected:string; onSelect:(uid:string)=>void; onReload:()=>void;
}) {
  const {t,locale} = usePreferences(), id = useId();
  const [open,setOpen] = useState(!!seed), [view,setView] = useState(seed);
  const loaded = useRef<{cursor:string|null;attempt:number}|null>(seed ? {cursor:null,attempt:0} : null);
  const [cursor,setCursor] = useState<string|null>(null), [attempt,setAttempt] = useState(0);
  const [loading,setLoading] = useState(false), [error,setError] = useState<unknown>(null);
  useEffect(()=>{
    if (!open || loaded.current?.cursor===cursor && loaded.current.attempt===attempt) return;
    const controller = new AbortController(),epoch=api.epoch,revision=api.revision;
    const active=()=>!controller.signal.aborted&&api.epoch===epoch&&api.revision===revision;
    setLoading(true); setError(null);
    api.request<GroupedCatalogView>('/api/workbench/catalog', {q:query,scope,groupBy:'classification',categoryKey:group.key,
      expectedSnapshotRevision:snapshot,cursor}, controller.signal)
      .then(value=>{if(active()){loaded.current={cursor,attempt};setView(previous=>({...value,items:cursor ? [...(previous?.items||[]),...value.items] : value.items}));}})
      .catch(value=>{if (active()&&!cancelled(value)) setError(value);})
      .finally(()=>{if(active())setLoading(false);});
    return ()=>controller.abort();
  },[open,cursor,attempt]);
  return <section className="cw-category"><button type="button" className="cw-category-heading" aria-expanded={open} aria-controls={id} onClick={()=>setOpen(value=>!value)}>
    {open?<ChevronDown size={12}/>:<ChevronRight size={12}/>}<span>{categoryLabel(group,locale)}</span><small>{group.count}</small>
  </button>{open && <div className="cw-category-items" id={id}>
    {!error && view?.items.map(item=><RowContext key={item.entityUid} name={item.displayName} actions={[{id:'view',label:locale==='zh'?'查看对象':'View object',icon:<Box/>,onSelect:()=>onSelect(item.entityUid)}]}><button type="button" className={`cw-list-item ${selected===item.entityUid?'active':''}`} aria-pressed={selected===item.entityUid} onClick={()=>onSelect(item.entityUid)}><Box size={14}/><span>{item.displayName}</span></button></RowContext>)}
    {loading && <p className="cw-state" role="status">{t('loading')}</p>}
    {error ? <div className="cw-state" role="alert">{failureMessage(error,locale)}<Btn onClick={()=>error instanceof ApiError && error.status===409 ? onReload() : setAttempt(value=>value+1)}>{t(error instanceof ApiError && error.status===409?'refresh':'retry')}</Btn></div> : null}
    {!loading && !error && view?.nextCursor && <Btn onClick={()=>setCursor(view.nextCursor)}>{t('more')}</Btn>}
  </div>}</section>;
}

export function Catalog({api, query, scope, selected, onSelect}: {
  api: WorkbenchApi; query:string; scope:string; selected:string; onSelect:(uid:string) => void;
}) {
  const {t, locale} = usePreferences();
  const [view, setView] = useState<GroupedCatalogView | null>(null);
  const [loading, setLoading] = useState(true), [attempt,setAttempt] = useState(0);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    const controller = new AbortController(),epoch=api.epoch,revision=api.revision;
    const active=()=>!controller.signal.aborted&&api.epoch===epoch&&api.revision===revision;
    setView(null); setLoading(true); setError(null);
    api.request<GroupedCatalogView>('/api/workbench/catalog', {q:query,scope,groupBy:'classification'}, controller.signal)
      .then(value=>{if (!active())return;if (!Array.isArray(value.groups)) throw new ApiError(503,'SOURCE_UNAVAILABLE');setView(value);})
      .catch(value => {if (active()&&!cancelled(value)) setError(value);})
      .finally(() => {if (active()) setLoading(false);});
    return () => controller.abort();
  }, [attempt]);
  return <div className="cw-catalog-groups">
    {view?.groups.map(group=><Category key={`${attempt}:${group.key}`} api={api} group={group} query={query} scope={scope} snapshot={view.snapshotRevision}
      seed={view.selectedCategoryKey===group.key ? view : null} selected={selected} onSelect={onSelect} onReload={()=>setAttempt(value=>value+1)}/>)}
    {loading && <p className="cw-state" role="status">{t('loading')}</p>}
    {error ? <div role="alert" className="cw-state">{failureMessage(error, locale)}<Btn onClick={() => setAttempt(value => value + 1)}>{t('retry')}</Btn></div> : null}
    {!loading && !error && view?.groups.length === 0 && <p className="cw-state">{t('noMatch')}</p>}
    {view && <p className="cw-caption cw-count">{t('totalCount', {number:view.groups.reduce((total,group)=>total+group.count,0)})}</p>}
  </div>;
}

export function ObjectsPanel({api, view, selected, ancestors, onSelect, className}: {
  api: WorkbenchApi; view:ContextView | null; selected:string; ancestors:string[];
  onSelect:(uid:string, scope:'equipment' | 'project') => void; className:string;
}) {
  const {t} = usePreferences();
  const [scope, setScope] = useState('equipment');
  const [query, setQuery] = useState('');
  const [settled, setSettled] = useState('');
  useEffect(() => {const timer = window.setTimeout(() => setSettled(query.trim()), 250); return () => clearTimeout(timer);}, [query]);
  return <section className={`cw-panel cw-objects ${className}`}><header><strong>{t('objects')}</strong><span className="cw-grow"/><span className="cw-caption">OntoBase</span></header>
    <Tabs.Root value={scope} onValueChange={value => {setScope(value); setQuery(''); setSettled('');}}><Tabs.List className="cw-tabs" aria-label={t('objects')}>
      <Tabs.Trigger className={scope === 'equipment' ? 'active' : ''} value="equipment">{t('equipment')}</Tabs.Trigger><Tabs.Trigger className={scope === 'project' ? 'active' : ''} value="project">{t('objects')}</Tabs.Trigger>
    </Tabs.List></Tabs.Root>
    <label className="cw-search"><Search size={14}/><input value={query} aria-label={t('search')} placeholder={t('search')} onChange={event => setQuery(event.target.value)}/></label>
    <div className="cw-object-scroll">{!view ? <p className="cw-state">{t('loginPrompt')}</p>
      : query.trim() !== settled ? <p className="cw-state" role="status">{t('loading')}</p>
      : scope === 'equipment' && !settled ? view.root ? <TreeNode api={api} object={view.root} seed={view.children} context={view.context} selected={selected} ancestors={ancestors} onSelect={uid => onSelect(uid, 'equipment')}/> : <p className="cw-state">{t('noObjects')}</p>
      : <Catalog key={`${scope}:${settled}`} api={api} query={settled} scope={scope} selected={selected} onSelect={uid => onSelect(uid, scope as 'equipment' | 'project')}/>}</div>
    <footer className="cw-panel-foot"><span className="cw-dot"/>OntoBase</footer>
  </section>;
}
