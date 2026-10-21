import { useEffect, useState } from 'react';
import { Box, ChevronDown, ChevronRight, Search } from 'lucide-react';
import * as Tabs from '@radix-ui/react-tabs';
import { cancelled, failureMessage, type WorkbenchApi } from './api';
import { usePreferences } from './Preferences';
import { Btn, IconBtn } from './Primitives';
import type { CatalogView, ChildrenView, ContextView, EngineeringObject, Installation } from './types';

function TreeNode({api, object, context, selected, onSelect, seed, depth = 0}: {
  api: WorkbenchApi; object: EngineeringObject; context: Installation; selected: string;
  onSelect:(uid: string) => void; seed?: ChildrenView | null; depth?: number;
}) {
  const {t, locale} = usePreferences();
  const [open, setOpen] = useState(!!seed);
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
    <button className={`cw-tree-item ${selected === object.entityUid ? 'active' : ''}`} type="button" onClick={() => onSelect(object.entityUid)}><Box size={14}/><span>{object.displayName}</span></button>
  </div>{open && object.hasChildren && <div className="cw-branch">
    {children?.items.map(row => <TreeNode key={row.object.entityUid} api={api} object={row.object} context={context} selected={selected} onSelect={onSelect} depth={depth + 1}/>)}
    {loading && <p className="cw-state" role="status">{t('loading')}</p>}
    {error ? <div role="alert" className="cw-state">{failureMessage(error, locale)}<Btn onClick={() => setRetry(value => value + 1)}>{t('retry')}</Btn></div> : null}
    {!loading && children?.nextCursor && <Btn onClick={() => setCursor(children.nextCursor)}>{t('more')}</Btn>}
  </div>}</div>;
}

function Catalog({api, query, scope, selected, onSelect}: {
  api: WorkbenchApi; query:string; scope:string; selected:string; onSelect:(uid:string) => void;
}) {
  const {t, locale} = usePreferences();
  const [view, setView] = useState<CatalogView | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError(null);
    api.request<CatalogView>('/api/workbench/catalog', {q:query, cursor, scope}, controller.signal)
      .then(value => setView(previous => ({...value, items:cursor ? [...(previous?.items || []), ...value.items] : value.items})))
      .catch(value => {if (!cancelled(value)) setError(value);})
      .finally(() => {if (!controller.signal.aborted) setLoading(false);});
    return () => controller.abort();
  }, [cursor, attempt]);
  return <><div className="cw-catalog">{view?.items.map(item => <button className={`cw-list-item ${selected === item.entityUid ? 'active' : ''}`} key={item.entityUid} type="button" onClick={() => onSelect(item.entityUid)}><Box size={14}/><span>{item.displayName}</span></button>)}</div>
    {loading && <p className="cw-state" role="status">{t('loading')}</p>}
    {error ? <div className="cw-state" role="alert">{failureMessage(error, locale)}<Btn onClick={() => {setCursor(null); setView(null); setAttempt(value => value + 1);}}>{t('refresh')}</Btn></div> : null}
    {!loading && !error && view?.items.length === 0 && <p className="cw-state">{t('noMatch')}</p>}
    {!loading && !error && view?.nextCursor && <Btn onClick={() => setCursor(view.nextCursor)}>{t('more')}</Btn>}
    {view && <p className="cw-caption cw-count">{t('loadedCount', {number:view.items.length})}</p>}
  </>;
}

export function ObjectsPanel({api, view, selected, onSelect, className}: {
  api: WorkbenchApi; view:ContextView | null; selected:string;
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
      : scope === 'equipment' && !settled ? view.root ? <TreeNode api={api} object={view.root} seed={view.children} context={view.context} selected={selected} onSelect={uid => onSelect(uid, 'equipment')}/> : <p className="cw-state">{t('noObjects')}</p>
      : <Catalog key={`${scope}:${settled}`} api={api} query={settled} scope={scope} selected={selected} onSelect={uid => onSelect(uid, scope as 'equipment' | 'project')}/>}</div>
    <footer className="cw-panel-foot"><span className="cw-dot"/>OntoBase</footer>
  </section>;
}
