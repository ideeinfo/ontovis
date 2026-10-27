import {useEffect,useMemo,useState} from 'react';
import {ExternalLink,GitBranch,RefreshCw} from 'lucide-react';
import {Btn} from './Primitives';
import type {CanvasCard} from './analysisCanvas';
import {AnalysisSources,type SourceRelationship} from './analysisSources';

export type CardSourceRelation=SourceRelationship&{from:CanvasCard;to:CanvasCard};
export function useSourceRelations(sources:AnalysisSources|null,cards:CanvasCard[]){
  const signature=JSON.stringify(cards.filter(c=>c.source).map(c=>c.source!.id).sort());
  const [items,setItems]=useState<SourceRelationship[]>([]),[loading,setLoading]=useState(false),[error,setError]=useState(false),[attempt,setAttempt]=useState(0),[gaps,setGaps]=useState(0);
  useEffect(()=>{setItems([]);setGaps(0);setError(false);if(!sources||signature==='[]')return;
    const abort=new AbortController();setLoading(true);
    void sources.relationships(cards.flatMap(c=>c.source?[c.source]:[]),abort.signal).then(result=>{if(!abort.signal.aborted){setItems(result.items);setGaps(result.gaps.length);}})
      .catch(()=>{if(!abort.signal.aborted)setError(true);}).finally(()=>{if(!abort.signal.aborted)setLoading(false);});
    return()=>abort.abort();
  },[sources,signature,attempt]);
  const relations=useMemo(()=>items.flatMap(item=>{
    const from=cards.filter(c=>c.source?.id===item.fromRef),to=cards.filter(c=>c.source?.id===item.toRef);
    return from.flatMap(a=>to.filter(b=>a.id!==b.id&&!!a.historical===!!b.historical).map(b=>({...item,id:item.id+':'+a.id+':'+b.id,from:a,to:b})));
  }),[items,cards]);
  return {relations,loading,error,gaps,retry:()=>setAttempt(v=>v+1)};
}

export function SourceRelationLines({relations,onOpen}:{relations:CardSourceRelation[];onOpen:(relation:CardSourceRelation)=>void}){
  return <>{relations.map(link=>{
    const a=link.from,b=link.to,right=b.x+b.width/2>=a.x+a.width/2;
    const x=right?a.x+a.width:a.x,x2=right?b.x:b.x+b.width,y=a.y+a.height/2,y2=b.y+b.height/2;
    const bend=Math.max(70,Math.min(240,Math.abs(x2-x)/2))*(right?1:-1),mx=(x+x2)/2,my=(y+y2)/2;
    return <g key={link.id} className="ac-source-link" role="button" tabIndex={0} aria-label={`${link.label}：${a.title} → ${b.title}`} onClick={event=>{event.stopPropagation();onOpen(link);}} onKeyDown={event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();onOpen(link);}}}>
      <title>{link.reason}</title><path className="ac-link-hit" d={`M${x},${y} C${x+bend},${y} ${x2-bend},${y2} ${x2},${y2}`}/>
      <path d={`M${x},${y} C${x+bend},${y} ${x2-bend},${y2} ${x2},${y2}`} markerEnd="url(#ad-source-arrow)"/>
      <rect x={mx-58} y={my-12} width="116" height="24" rx="6"/><text x={mx} y={my+4} textAnchor="middle">{link.label}</text>
    </g>;
  })}</>;
}

export function SourceRelationDetails({selected,relations,loading,error,gaps,retry,onOpen,en}:{selected:CanvasCard;relations:CardSourceRelation[];loading:boolean;error:boolean;gaps:number;retry:()=>void;onOpen:(relation:CardSourceRelation)=>void;en:boolean}){
  const rows=relations.filter(r=>r.from.id===selected.id||r.to.id===selected.id);
  return <section className="ac-inspector-section"><div className="ad-inline"><strong>{en?'Source relationships':'资料之间的关系'}</strong><Btn onClick={retry} disabled={loading} aria-label={en?'Refresh source relationships':'刷新资料关系'}><RefreshCw size={13}/></Btn></div>
    {loading&&<p role="status">{en?'Loading source relationships…':'正在读取来源关系…'}</p>}
    {error&&<p role="status">{en?'Relationships are temporarily unavailable. Retry.':'关系暂时未返回，可重新读取。'}</p>}
    {!loading&&!error&&!rows.length&&<p>{en?'No recorded relationships for this card.':'此卡暂无已登记的资料关系。'}</p>}
    {rows.map(link=><div className="ad-relation ac-source-relation" key={link.id}><GitBranch size={15}/><div><small>{link.label}</small><strong>{link.from.id===selected.id?link.to.title:link.from.title}</strong><p>{link.reason}</p><Btn onClick={()=>onOpen(link)}><ExternalLink size={13}/>{en?'Open at location':'展开并定位'}</Btn></div></div>)}
    {gaps>0&&<small>{en?'Some sources are temporarily unavailable.':'部分来源暂时未返回，已保留可读取的关系。'}</small>}
  </section>;
}
