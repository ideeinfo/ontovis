import {useEffect,useRef,useState} from 'react';
import {RefreshCw} from 'lucide-react';
import {Btn,Modal} from './Primitives';
import {cancelled,failureMessage} from './api';
import type {DraftApi} from './AnalysisWorkspace';
import type {Recommendation} from './analysisSources';
import type {WorkOrderDetail} from './workOrderTypes';
import {progressRecommendation,progressRows,progressTargetLabel,type ProgressRow,type ProgressSource} from './workOrderProgress';
import './workOrderProgress.css';

export function WorkOrderProgressDialog({api,before,en,canLoad,onLoad,onClose}:{api:DraftApi;before:ProgressSource;en:boolean;canLoad:boolean;onLoad?:(item:Recommendation)=>Promise<boolean>;onClose:()=>void}){
 const t=(zh:string,english:string)=>en?english:zh;
 const [latest,setLatest]=useState<WorkOrderDetail|null>(null),[reading,setReading]=useState(true),[applying,setApplying]=useState(false),[error,setError]=useState(''),[reload,setReload]=useState(0),[all,setAll]=useState(false);
 const current=useRef(true);
 useEffect(()=>{current.current=true;const abort=new AbortController();setReading(true);setLatest(null);setError('');
  void api.request<WorkOrderDetail>('/api/workbench/work-orders/detail',{orderId:before.orderId},abort.signal).then(value=>{
   if(abort.signal.aborted)return;
   if(value.orderId!==before.orderId||!Number.isInteger(value.orderRevision)||value.orderRevision<(before.orderRevision??0))throw new Error(t('工单版本不一致，请重新读取。','The order version is inconsistent. Reload it.'));
   setLatest(value);
  }).catch(value=>{if(!abort.signal.aborted&&!cancelled(value))setError(value instanceof Error&&!(value as {code?:string}).code?value.message:failureMessage(value,en?'en':'zh'));}).finally(()=>{if(!abort.signal.aborted)setReading(false);});
  return()=>{current.current=false;abort.abort();};
 },[api,before.orderId,before.orderRevision,reload,en]);
 const rows=latest?progressRows(before,latest):[],changed=rows.filter(r=>r.change!=='unchanged'),recommendation=latest?progressRecommendation(before,latest):null;
 const state=(value:string)=>({candidate:t('待核候选','Candidate'),supported:t('记录支持','Support recorded'),rejected:t('记录排除','Exclusion recorded'),pending:t('待排查','Pending'),observed:t('已记录观察','Observation recorded'),gap:t('资料缺口','Evidence gap'),not_applicable:t('不适用','Not applicable'),open:t('待受理','Open'),diagnosing:t('诊断中','Diagnosing'),investigating:t('排查中','Investigating'),review:t('待复核','In review'),closed:t('已关闭','Closed')} as Record<string,string>)[value]??value;
 function contents(row:ProgressRow['before'],source:ProgressSource){return row?<><p>{'description' in row?row.description:row.title}</p><small>{state('status' in row?row.status:row.outcome)}{'targetKey' in row&&row.targetKey?' · '+(progressTargetLabel(row.targetKey,source)||t('关联对象名称未提供','Object label unavailable')):''}</small><p className="wp-record">{('basis' in row?row.basis:row.result)||t('尚无人工记录','No human record')}</p></>:<p>{t('此版本没有该条目','Not present in this revision')}</p>;}
 async function load(){if(!recommendation||!onLoad||applying)return;setApplying(true);setError('');try{
  const ok=await onLoad(recommendation);if(!current.current)return;if(ok)onClose();else setError(t('未能载入，原资料卡仍保留。请重新读取进展后再试。','Unable to load; the original card is retained. Reload the progress and retry.'));
 }catch(value){if(current.current&&!cancelled(value))setError(failureMessage(value,en?'en':'zh'));}finally{if(current.current)setApplying(false);}}
 return <Modal className="wp-dialog" title={t('工单进展','Work-order progress')} description={t('比较固定资料与本单最新保存版本；载入后仍需保存画布。','Compare the fixed material and latest saved order. Save the canvas after loading.')} onClose={()=>{if(!applying)onClose();}}><div className="wp-progress" onPointerDown={event=>event.stopPropagation()} onWheel={event=>event.stopPropagation()}>
  <div className="wp-heading"><strong>{before.orderId} · {before.title}</strong><Btn disabled={reading||applying} onClick={()=>setReload(r=>r+1)}><RefreshCw size={14}/>{t('重新读取进展','Reload progress')}</Btn></div>
  <div className="wp-versions"><div><small>{t('画布固定版本','Fixed canvas material')}</small><strong>r{before.orderRevision} · {state(before.state??'')}</strong></div><div><small>{t('本单已保存进展','Latest saved order')}</small><strong>{latest?'r'+latest.orderRevision+' · '+state(latest.state):'—'}</strong></div></div>
  <p className="wp-caption">{t('人工记录与待核内容分开保留。载入只替换本卡的固定来源，保存为新分析修订后可选择该资料继续提问。','Human records remain unverified. Loading changes this card’s fixed source; save a new analysis revision before selecting it for another question.')}</p>
  {error&&<p className="aw-notice" role="alert">{error}</p>}{reading&&<p role="status">{t('正在读取本单进展…','Reading order progress…')}</p>}
  {latest&&<><div className="wp-toolbar"><span>{changed.length} {t('项诊断变化','investigation changes')}</span><Btn aria-pressed={all} onClick={()=>setAll(v=>!v)}>{all?t('仅看变化','Changes only'):t('查看全部条目','All items')}</Btn></div><div className="wp-rows">{!all&&!changed.length&&<p>{t('诊断条目未变化；工单状态及记录仍以本单最新版本为准。','Investigation items are unchanged; order state and records use the latest version.')}</p>}{(all?rows:changed).map(row=><article key={row.kind+row.id}><header><b>{row.kind==='hypothesis'?t('原因假设','Hypothesis'):t('排查步骤','Check step')}</b><span>{({added:t('新增','Added'),removed:t('已移除','Removed'),changed:t('已调整','Changed'),unchanged:t('未变化','Unchanged')})[row.change]}</span></header><div className="wp-compare"><section aria-label={t('固定版本条目','Fixed item')}><small>{t('固定','Fixed')} r{before.orderRevision}</small>{contents(row.before,before)}</section><section aria-label={t('当前版本条目','Current item')}><small>{t('本单','Order')} r{latest.orderRevision}</small>{contents(row.after,latest)}</section></div></article>)}<details><summary>{t('处理记录与检查清单','Findings and checklist')}</summary><div className="wp-compare"><section><small>r{before.orderRevision}</small><p>{before.checks?.length??0} {t('项已勾选','items checked')}</p><p>{before.note||t('尚无处理记录','No findings recorded')}</p></section><section><small>r{latest.orderRevision} · {latest.checks.length}/{latest.diagnosis.checks.length}</small><p>{latest.note||t('尚无处理记录','No findings recorded')}</p></section></div></details></div></>}
  <div className="wp-footer">{!canLoad&&<small>{t('当前画布只读；可比较，不可替换来源。','This canvas is read-only; comparison is available.')}</small>}<Btn disabled={applying} onClick={onClose}>{t('保留原版本','Keep fixed version')}</Btn><Btn primary disabled={reading||applying||!canLoad||!recommendation} onClick={()=>void load()}>{applying?t('正在载入…','Loading…'):t('载入本单进展','Load order progress')}</Btn></div>
 </div></Modal>;
}
