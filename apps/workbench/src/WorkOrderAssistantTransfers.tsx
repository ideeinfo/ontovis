import {ClipboardList} from 'lucide-react';
import {Btn} from './Primitives';
import type {WorkOrderDetail} from './workOrderTypes';
import './assistantWorkOrder.css';
export function WorkOrderAssistantTransfers({detail,en,onOpenAnalysis}:{detail:WorkOrderDetail;en:boolean;onOpenAnalysis?:(id:string,revision:number,runId?:string)=>void}){
 const t=(zh:string,english:string)=>en?english:zh;
 if(!detail.assistantTransfers?.length)return null;
 const names={hypothesis:t('原因假设','Hypothesis'),step:t('排查步骤','Check step'),gap:t('补充证据','Evidence gap')};
 return <section className="wo-card"><header><ClipboardList size={16}/><h3>{t('助手建议采纳记录','Adopted assistant suggestions')}</h3></header><div className="wo-assistant-transfers">{detail.assistantTransfers.slice().reverse().map(transfer=><article key={transfer.orderRevision}>
  <header><strong>{t('本单','Order')} r{transfer.orderRevision} · {t('分析','Analysis')} r{transfer.analysisRevision} · {t('第','Turn ')}{transfer.conversationVersion||1}{t('轮','')}</strong>{onOpenAnalysis&&<Btn onClick={()=>onOpenAnalysis(transfer.analysisSessionId,transfer.analysisRevision,transfer.runId)}>{t('回看本轮分析','View this analysis turn')}</Btn>}</header>
  <small>{new Date(transfer.recordedAt).toLocaleString(en?'en-GB':'zh-CN')} · {t('加入时均为待核验，不代表现场结论','Added as unverified suggestions, not field conclusions')}</small>
  <ol>{transfer.items.map(item=>{const current=item.kind==='hypothesis'?detail.investigation.hypotheses.find(row=>row.id===item.planItemId):detail.investigation.steps.find(row=>row.id===item.planItemId);return <li key={item.sourceItemId}><b>{names[item.kind]}</b><p>{item.text}</p><small>{current?t('当前方案仍保留该条目','The current plan retains this item'):t('当前方案已移除此条目；本次采纳历史保留','Removed from the current plan; adoption history retained')}</small><details><summary>{t('助手原建议与固定引用','Original suggestion and fixed references')}</summary><p>{item.originalText}</p>{item.refs.map(key=>{const ref=transfer.sources.find(s=>s.key===key);return <p key={key}><strong>{key}</strong><br/><small>{ref?.kind} · {ref?.evidenceRefId}<br/>{ref?.sourceRevision}</small></p>;})}{!item.refs.length&&<small>{t('原建议没有来源引用','The original suggestion had no source reference')}</small>}</details></li>;})}</ol>
 </article>)}</div></section>;
}
