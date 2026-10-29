import {useEffect,useMemo,useState} from 'react';
import {GitBranch,RefreshCw} from 'lucide-react';
import {Btn} from './Primitives';
import {cancelled} from './api';
import {AssistantApi,assistantMessage,filterEngineeringGraph,relationLabels,type EngineeringGraph} from './assistantApi';
import type {CanvasCard} from './analysisCanvas';
import type {DraftReceipt} from './analysisDraftState';

export function AssistantGraph({service,cards,receipt,en,onFocus}:{service:AssistantApi;cards:CanvasCard[];receipt:DraftReceipt|null;en:boolean;onFocus:(card:CanvasCard)=>void}){
 const t=(zh:string,english:string)=>en?english:zh;
 const objects=cards.filter(c=>c.kind==='object'&&c.source),ids=objects.map(c=>c.source!.id).join(':');
 const [open,setOpen]=useState(false),[root,setRoot]=useState(()=>objects[0]?.source?.id??''),[graph,setGraph]=useState<EngineeringGraph|null>(null),[error,setError]=useState<unknown>(null),[loading,setLoading]=useState(false),[reload,setReload]=useState(0);
 const [query,setQuery]=useState(''),[relation,setRelation]=useState('');
 useEffect(()=>{if(!objects.some(c=>c.source!.id===root))setRoot(objects[0]?.source?.id??'');},[ids,root]);
 useEffect(()=>{setGraph(null);setError(null);if(!open||!receipt||!root)return;const abort=new AbortController();setLoading(true);
  service.graph(receipt.analysisSessionId,receipt.analysisRevision,root,abort.signal).then(value=>{if(!abort.signal.aborted)setGraph(value.graph);}).catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setError(e);}).finally(()=>{if(!abort.signal.aborted)setLoading(false);});
  return()=>abort.abort();
 },[service,receipt?.analysisSessionId,receipt?.analysisRevision,open,root,reload]);
 const rows=useMemo(()=>graph?filterEngineeringGraph(graph,relation,query):[],[graph,relation,query]);
 return <details className="as-graph" open={open} onToggle={event=>setOpen(event.currentTarget.open)}><summary><GitBranch size={14}/>{t('工程图谱','Engineering graph')}</summary>
  {!objects.length?<p>{t('加入工程对象后，可查看其资料与候选连接。','Add an engineering object to inspect its associations.')}</p>:<>
   <div className="as-graph-root"><label>{t('起点对象','Root object')}<select value={root} onChange={e=>setRoot(e.target.value)}>{objects.map(c=><option key={c.id} value={c.source!.id}>{c.title}</option>)}</select></label><Btn disabled={loading||!receipt} onClick={()=>setReload(v=>v+1)} title={t('刷新关联','Refresh associations')}><RefreshCw size={13}/></Btn></div>
   <p className="ap-caption">{t('两跳关联，最多24节点、48条关系。候选接线保留待复核状态。','Two hops, up to 24 nodes and 48 links. Imported connections remain unreviewed.')}</p>
   {loading&&<p role="status">{t('读取对象关联…','Reading object associations…')}</p>}{!!error&&<p role="alert">{assistantMessage(error,en)}</p>}
   {graph&&<><label>{t('筛选关联','Filter associations')}<select value={relation} onChange={e=>setRelation(e.target.value)}><option value="">{t('全部关联','All associations')}</option>{Object.entries(relationLabels).map(([key,name])=><option key={key} value={key}>{name[en?1:0]}</option>)}</select></label><input aria-label={t('在当前图谱中搜索','Search this graph')} placeholder={t('在当前关联中搜索名称','Search names in these associations')} value={query} onChange={e=>setQuery(e.target.value)}/>
    <div className="as-graph-rows">{rows.map(edge=>{const a=graph.nodes.find(n=>n.id===edge.source)!,b=graph.nodes.find(n=>n.id===edge.target)!;
     const cardFor=(id:string)=>id===graph.nodes[0]?.entityUid?objects.find(c=>c.source!.id===root):undefined;
     return <article key={edge.id}><b>{relationLabels[edge.type]?.[en?1:0]||edge.type}</b><p>{a.title} {edge.type==='CANDIDATE_CONNECTION'?'—':'→'} {b.title}</p>{edge.provenance.pageNumber&&<span>{t('第','Page ')}{edge.provenance.pageNumber}{t('页','')}</span>}{b.entityUid&&cardFor(b.entityUid)&&<Btn onClick={()=>onFocus(cardFor(b.entityUid!)!)}>{t('定位资料卡','Locate card')}</Btn>}<details><summary>{t('来源记录','Source record')}</summary><small>{edge.provenance.recordId}</small>{edge.provenance.importId&&<small>{t('导入批次','Import')}: {edge.provenance.importId}</small>}</details></article>})}{!rows.length&&<p>{t('当前筛选没有关联。','No matching association.')}</p>}</div>
    {graph.gaps.map((gap,i)=><p key={i} className="ap-caption">{gap}</p>)}
   </>}
  </>}
 </details>;
}
