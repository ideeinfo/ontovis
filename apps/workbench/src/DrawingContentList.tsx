import {useEffect,useId,useMemo,useRef,useState} from 'react';
import {ChevronRight} from 'lucide-react';
import {drawingGroups} from './drawingGroups';
import type {PreviewRow} from './analysisSources';

export function DrawingContentList({rows,section,query,selected,focusToken,en,onSelect}:{rows:PreviewRow[];section:string;query:string;selected:string;focusToken:number;en:boolean;onSelect:(row:PreviewRow)=>void}){
  const prefix=useId(),selectedElement=useRef<HTMLButtonElement|null>(null);
  const [collapsedTypes,setCollapsedTypes]=useState<ReadonlySet<string>>(()=>new Set()),[expandedOwners,setExpandedOwners]=useState<ReadonlySet<string>>(()=>new Set());
  const ports=section==='ports',grouped=ports||section==='objects',searching=!!query.trim();
  const groups=useMemo(()=>drawingGroups(rows,ports,en,query),[rows,ports,en,query]);
  const selectedType=groups.find(group=>group.rows.some(row=>row.id===selected)),selectedOwner=selectedType?.owners.find(owner=>owner.rows.some(row=>row.id===selected));
  useEffect(()=>{
    if(!selectedType)return;
    setCollapsedTypes(current=>{if(!current.has(selectedType.key))return current;const next=new Set(current);next.delete(selectedType.key);return next;});
    if(selectedOwner)setExpandedOwners(current=>current.has(selectedOwner.key)?current:new Set([...current,selectedOwner.key]));
    const frame=requestAnimationFrame(()=>selectedElement.current?.scrollIntoView({block:'nearest'}));return()=>cancelAnimationFrame(frame);
  },[selected,focusToken,selectedType?.key,selectedOwner?.key]);
  useEffect(()=>{
    if(!searching)return;
    setCollapsedTypes(current=>{const next=new Set(current);groups.forEach(group=>next.delete(group.key));return next.size===current.size?current:next;});
    setExpandedOwners(current=>{const next=new Set(current);groups.forEach(group=>group.owners.forEach(owner=>next.add(owner.key)));return next.size===current.size?current:next;});
  },[query,groups,searching]);
  function toggle(set:typeof setCollapsedTypes,key:string){set(current=>{const next=new Set(current);if(next.has(key))next.delete(key);else next.add(key);return next;});}
  const rowButton=(row:PreviewRow)=><button key={row.id} type="button" className="ac-drawing-row" ref={selected===row.id?selectedElement:undefined} aria-current={selected===row.id?'true':undefined} onClick={()=>onSelect(row)}>
    <strong>{row.title}</strong>{!ports&&<small>{row.identifier||row.targetTitle||''}</small>}{!row.bbox&&<small>{en?'No locatable region':'未提供可定位区域'}</small>}
  </button>;
  if(!grouped)return <>{rows.filter(row=>[row.title,row.identifier,row.owner,row.targetTitle].join(' ').toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())).map(rowButton)}</>;
  return <div className="ac-drawing-groups">{groups.map((group,index)=>{const open=!collapsedTypes.has(group.key),groupId=prefix+'-type-'+index;
    return <section className="ac-drawing-type" key={group.key} aria-label={group.label}>
      <button type="button" className="ac-drawing-toggle" aria-expanded={open} aria-controls={groupId} onClick={()=>toggle(setCollapsedTypes,group.key)}><ChevronRight size={14}/><strong>{group.label}</strong><span>{group.rows.length}</span></button>
      {open&&<div id={groupId} className="ac-drawing-children">{ports?group.owners.map((owner,ownerIndex)=>{const expanded=expandedOwners.has(owner.key),ownerId=groupId+'-owner-'+ownerIndex;
        return <section key={owner.key} className="ac-drawing-owner" aria-label={owner.label}>
          <button type="button" className="ac-drawing-toggle ac-drawing-owner-toggle" title={owner.rows[0]?.ownerId||undefined} aria-expanded={expanded} aria-controls={ownerId} onClick={()=>toggle(setExpandedOwners,owner.key)}><ChevronRight size={13}/><strong>{owner.label}{group.owners.filter(item=>item.label===owner.label).length>1&&<small className="ac-drawing-instance">{owner.rows[0]?.ownerId?.split('/').at(-1)}</small>}</strong><span>{owner.rows.length}</span></button>
          {expanded&&<div id={ownerId} className="ac-drawing-children">{owner.rows.map(rowButton)}</div>}
        </section>;
      }):group.rows.map(rowButton)}</div>}
    </section>;
  })}{!groups.length&&searching&&<p className="ac-preview-empty">{en?'No matching items':'没有匹配项'}</p>}</div>;
}
