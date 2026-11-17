import { ChevronRight } from 'lucide-react';
import { Badge } from './Primitives';
import { usePreferences } from './Preferences';
import { recordedObjectPath } from './objectCatalog';
import type { ObjectView } from './types';

export function ObjectHierarchy({detail,onSelect}:{detail:ObjectView;onSelect:(uid:string)=>void}) {
  const {t} = usePreferences(), path = recordedObjectPath(detail);
  if (!path.length) return <span>{t('notAssigned')}</span>;
  const incomplete = detail.ancestors.completeness !== 'complete';
  const unverified = detail.ancestors.path.some(row=>row.relation.status !== 'confirmed');
  return <nav className="cw-object-path" aria-label={t('equipmentHierarchy')}><ol>{path.map((item,index)=><li key={`${item.entityUid}:${index}`}>
    {index>0 && <ChevronRight size={12} aria-hidden="true"/>}{index===path.length-1 ? <span aria-current="location">{item.displayName}</span> : <button type="button" onClick={()=>onSelect(item.entityUid)}>{item.displayName}</button>}
  </li>)}</ol>{(incomplete||unverified) && <Badge tone="amber">{t(incomplete?'incomplete':'unverified')}</Badge>}</nav>;
}
