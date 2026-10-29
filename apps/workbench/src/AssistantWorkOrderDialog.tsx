import {useEffect,useRef,useState} from 'react';
import {Check,ClipboardList,ExternalLink,RefreshCw} from 'lucide-react';
import {Btn,Modal} from './Primitives';
import {ApiError,cancelled} from './api';
import type {DraftApi} from './AnalysisWorkspace';
import type {CanvasCard} from './analysisCanvas';
import {ASSISTANT_ROOT,assistantMessage,type AssistantRun} from './assistantApi';
import {transferBody,transferEdits,transferMessage,transferProblems,type TransferEdit,type TransferPreview} from './assistantWorkOrder';
import type {OrderListing,WorkOrderDetail} from './workOrderTypes';
import './assistantWorkOrder.css';

export function AssistantWorkOrderDialog({api,run,cards,en,preferredOrderId='',faultCode='',enabled,onClose,onOpenOrder,onFocus}:{
 api:DraftApi;run:AssistantRun;cards:CanvasCard[];en:boolean;preferredOrderId?:string;faultCode?:string;enabled:boolean;
 onClose:()=>void;onOpenOrder?:(id:string)=>void;onFocus:(card:CanvasCard)=>void;
}){
 const t=(zh:string,english:string)=>en?english:zh;
 const [query,setQuery]=useState(preferredOrderId||faultCode),[filter,setFilter]=useState(preferredOrderId||faultCode);
 const [listing,setListing]=useState<OrderListing|null>(null),[orderId,chooseOrder]=useState(''),[preview,setPreview]=useState<TransferPreview|null>(null);
 const [edits,setEdits]=useState<TransferEdit[]>([]),[busy,setBusy]=useState(false),[loading,setLoading]=useState(true),[reload,setReload]=useState(0),[error,setError]=useState<unknown>(null);
 const [saved,setSaved]=useState<WorkOrderDetail|null>(null),[uncertain,setUncertain]=useState(false);
 const editCache=useRef<{orderId:string;rows:TransferEdit[]}>({orderId:'',rows:[]});
 const pending=useRef<{fingerprint:string;body:object}|null>(null),alive=useRef(true);
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
 useEffect(()=>{const abort=new AbortController();setLoading(true);setError(null);
  api.request<OrderListing>('/api/workbench/work-orders',{q:filter,limit:50},abort.signal).then(value=>{
   if(abort.signal.aborted)return;setListing(value);chooseOrder(id=>value.items.some(row=>row.orderId===id)?id:
    value.items.find(row=>row.orderId===preferredOrderId)?.orderId||value.items.find(row=>['diagnosing','investigating'].includes(row.state))?.orderId||value.items[0]?.orderId||'');
  }).catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setError(e);}).finally(()=>{if(!abort.signal.aborted)setLoading(false);});
  return()=>abort.abort();
 },[api,filter]);
 useEffect(()=>{if(!orderId)return;const abort=new AbortController();setLoading(true);setError(null);setPreview(null);setSaved(null);
  api.request<TransferPreview>(ASSISTANT_ROOT+'/work-order-preview',{runId:run.runId,orderId},abort.signal).then(value=>{
   if(abort.signal.aborted)return;setPreview(value);setEdits(transferEdits(value,editCache.current.orderId===orderId?editCache.current.rows:[]));
  }).catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setError(e);}).finally(()=>{if(!abort.signal.aborted)setLoading(false);});
  return()=>abort.abort();
 },[api,run.runId,orderId,reload]);
 function edit(id:string,patch:Partial<TransferEdit>){setEdits(rows=>{const next=rows.map(row=>row.id===id?{...row,...patch}:row);editCache.current={orderId,rows:next};return next;});}
 async function save(){if(!preview||busy||!enabled)return;setBusy(true);setError(null);
  const content=transferBody(preview,edits),fingerprint=JSON.stringify(content);
  if(!pending.current||pending.current.fingerprint!==fingerprint)pending.current={fingerprint,body:{...content,requestId:crypto.randomUUID()}};
  try{const value=await api.request<WorkOrderDetail>(ASSISTANT_ROOT+'/work-order-apply',pending.current.body);
   if(!alive.current)return;setSaved(value);setUncertain(false);pending.current=null;
  }catch(e){if(alive.current){setError(e);setUncertain(!(e instanceof ApiError)||[502,503,504].includes(e.status));if(e instanceof ApiError&&![502,503,504].includes(e.status))pending.current=null;}}
  finally{if(alive.current)setBusy(false);}
 }
 const problems=preview?transferProblems(preview,edits):[],locked=busy||uncertain||!!saved;
 const kinds={hypothesis:t('原因假设','Hypothesis'),step:t('排查步骤','Check step'),gap:t('补充证据','Evidence gap')};
 const states:Record<string,string>={open:t('待受理','Open'),diagnosing:t('诊断中','Diagnosing'),investigating:t('排查中','Investigating'),review:t('待复核','In review'),closed:t('已关闭','Closed')};
 return <Modal title={t('整理到工单','Organize into work order')} description={t('选择并编辑要加入本单排查的建议；保留现有诊断和处理状态，不填写结论或观察结果。','Choose and edit suggestions to append. Existing investigation and state are retained; no conclusion or observation result is filled.')} onClose={()=>!busy&&onClose()}>
 <div className="aw-transfer">
  <form className="aw-search" onSubmit={e=>{e.preventDefault();setFilter(query);}}><label>{t('查找本项目工单','Find a work order in this project')}<input value={query} maxLength={200} disabled={locked} aria-label={t('查找目标工单','Find target order')} onChange={e=>setQuery(e.target.value)}/></label><Btn disabled={locked||loading} type="submit">{t('查找','Find')}</Btn></form>
  <label className="aw-target">{t('目标工单','Target work order')}<select aria-label={t('目标工单','Target work order')} value={orderId} disabled={locked||loading} onChange={e=>{editCache.current={orderId:'',rows:[]};pending.current=null;chooseOrder(e.target.value);}}>
   {!listing?.items.length&&<option value="">{t('没有匹配的工单','No matching work order')}</option>}{listing?.items.map(row=><option key={row.orderId} value={row.orderId}>{row.orderId} · {row.title} · {states[row.state]}</option>)}
  </select></label>
  {!!listing?.nextCursor&&<small>{t('仅显示前50条，请按编号或故障码缩小范围。','Showing the first fifty orders; narrow the search by ID or fault code.')}</small>}
  <p className="aw-scope">{t('来自固定分析','From fixed analysis')} r{run.analysisRevision} · {t('助手第','Assistant turn ')}{run.conversationVersion||1}{t('轮','')}{preview&&` → ${preview.order.orderId} · r${preview.order.orderRevision}`}</p>
  {loading&&<p role="status">{t('正在读取工单和本轮来源…','Reading the order and turn sources…')}</p>}
  {preview&&<>
   <details className="aw-observations"><summary>{t('本轮观察 · 仅供参照','Turn observations · reference only')}</summary>{preview.proposal.observations.map((row,i)=><p key={i}>{row.text} <small>{row.refs.join(' · ')}</small></p>)}</details>
   <div className="aw-rows">{preview.proposal.items.map(item=>{const row=edits.find(r=>r.id===item.id);if(!row)return null;const adopted=preview.adoptedItemIds.includes(item.id);return <article key={item.id} className="aw-row" data-selected={row.selected}>
    <label className="aw-select"><input type="checkbox" checked={row.selected} disabled={locked||adopted} aria-label={t('采用','Adopt')+' '+kinds[item.kind]+' '+item.text} onChange={e=>edit(item.id,{selected:e.target.checked})}/><span><b>{kinds[item.kind]}</b><small>{adopted?t('已采纳','Already adopted'):item.kind==='hypothesis'?t('加入后为待核候选','Added as a candidate'):t('加入后为待排查','Added as pending')}</small></span></label>
    <textarea aria-label={kinds[item.kind]+' '+item.id} value={row.text} maxLength={item.kind==='gap'?495:500} disabled={locked||adopted} rows={3} onChange={e=>edit(item.id,{text:e.target.value})}/>
    <div className="aw-refs">{item.refs.map(key=>{const ref=preview.proposal.sources.find(s=>s.key===key),card=cards.find(c=>c.source?.id===ref?.evidenceRefId);return <span key={key}>{key} · {card?.title||t('固定来源','Fixed source')}</span>;})}{!item.refs.length&&<small>{t('未引用来源的待补建议','A follow-up suggestion without a source reference')}</small>}</div>
    {item.kind!=='hypothesis'&&<label>{t('关联对象（可选）','Object reference (optional)')}<select value={row.targetKey} disabled={locked||adopted} onChange={e=>edit(item.id,{targetKey:e.target.value})}><option value="">{t('未指定对象','No object selected')}</option>{preview.order.diagnosis.nodes.filter(node=>node.locateKey).map(node=><option key={node.locateKey} value={node.locateKey}>{node.label}</option>)}</select></label>}
    <details><summary>{t('助手原建议与引用','Original suggestion and references')}</summary><p>{item.text}</p>{item.refs.map(key=>{const source=preview.proposal.sources.find(s=>s.key===key),card=cards.find(c=>c.source?.id===source?.evidenceRefId);return <div key={key}><small>{key} · {source?.sourceRevision}</small>{card&&<Btn disabled={busy} onClick={()=>{onClose();onFocus(card);}}>{t('定位原资料卡','Locate original material')}</Btn>}</div>;})}</details>
   </article>;})}</div>
   {problems.includes('state')&&<p className="aw-notice">{t('请先在工单页受理工单；诊断中或排查中可以加入条目。','Accept the order first. Diagnosing or investigating orders can receive items.')}</p>}
   {problems.includes('limit')&&<p className="aw-notice">{t('超出本单6条假设、12个步骤上限，请减少选择。','This exceeds six hypotheses or twelve steps. Select fewer items.')}</p>}
   {problems.includes('text')&&<p className="aw-notice">{t('所选条目内容不能为空或超过长度限制。','Selected text must be nonempty and within its length limit.')}</p>}
  </>}
  {!!error&&<div role="alert" className="aw-notice">{transferMessage(error,en)||assistantMessage(error,en)}{!uncertain&&<Btn disabled={busy||!orderId} onClick={()=>setReload(v=>v+1)}><RefreshCw size={13}/>{t('重新读取并比较','Reload and compare')}</Btn>}</div>}
  {uncertain&&<p className="aw-notice">{t('保存结果尚未明确，先检查本次保存；同一请求不会重复加入。','The save result is uncertain. Check this save first; the same request cannot add duplicates.')}</p>}
  {saved&&<p className="aw-success" role="status"><Check size={16}/>{t('已加入本单排查','Added to this order')} · {saved.orderId} r{saved.orderRevision}</p>}
  <div className="aw-footer"><Btn disabled={busy} onClick={onClose}>{t('返回分析','Return to analysis')}</Btn>{onOpenOrder&&orderId&&<Btn disabled={busy||uncertain} onClick={()=>onOpenOrder(orderId)}><ExternalLink size={14}/>{t(saved?'查看工单':'打开工单',saved?'View work order':'Open work order')}</Btn>}{!saved&&<Btn primary disabled={busy||loading||!preview||!enabled||!listing?.capabilities.canWrite||!!problems.length} onClick={()=>void save()}><ClipboardList size={14}/>{busy?t('正在保存…','Saving…'):uncertain?t('检查本次保存','Check this save'):t('加入本单排查','Add to this order')+' · '+edits.filter(row=>row.selected).length+t('项',' items')}</Btn>}</div>
 </div></Modal>;
}
