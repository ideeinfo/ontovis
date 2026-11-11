import {useState} from 'react';
import {FileText, Paperclip} from 'lucide-react';
import {Btn} from './Primitives';
import {orderRecordTime} from './workOrderHistory';
import {workflowLabel, type FixedAttachment, type TreatmentRecord, type Workflow} from './workOrderWorkflow';
import './workOrderWorkflow.css';

export function WorkOrderRecords({orderId, revision, state, simulated, workflow, en, compact=false,
  onOpenAttachment, onCorrect, onHistory, onAttach}:{
  orderId:string; revision:number; state:string; simulated:boolean; workflow:Workflow; en:boolean; compact?:boolean;
  onOpenAttachment?:(item:FixedAttachment)=>void; onCorrect?:(record:TreatmentRecord)=>void;
  onHistory?:(record:TreatmentRecord)=>void; onAttach?:(record:TreatmentRecord)=>void;
}) {
  const t=(zh:string,english:string)=>en?english:zh;
  const [page,setPage]=useState(0);
  const rows=[...workflow.records].reverse();
  const start=Math.min(page*8, Math.max(0,Math.floor((rows.length-1)/8)*8));
  const result=workflow.result;
  const visible=compact?rows.slice(0,1):rows.slice(start,start+8);
  return <section className={'wov-records'+(compact?' compact':'')}>
    <div className="wov-record-identity"><span>{orderId} · r{revision}</span><span>{workflowLabel(state,en)}</span>
      {simulated&&<span className="wov-tag">{t('模拟','Simulation')}</span>}</div>
    {result?<article className="wov-result"><strong>{result.voided?t('作废 · 未执行','Voided · No treatment'):t('处理结果','Treatment result')}</strong>
      <p>{result.text}</p></article>:<small>{t('尚无最终处理结果','No final result recorded')}</small>}
    {visible.length>0&&<h3>{compact?t('最近处置记录','Latest treatment record'):t('处置过程','Treatment records')}</h3>}
    {visible.map(record=><article key={record.recordId} className="wov-record">
      <small>{record.actor} · {orderRecordTime(record.occurredAt||record.recordedAt,en)} · r{record.recordRevision}
        {!compact&&record.occurredAt&&<> · {t('录入','Entered')} {orderRecordTime(record.recordedAt,en)}</>}</small>
      <p>{record.text}</p>
      {!compact&&<>
        {!!record.basis&&<small>{t('当时采用分析','Analysis used at the time')} · r{record.basis.analysisRevision}</small>}
        <div className="wov-actions">
          {workflow.attachments.filter(item=>item.recordId===record.recordId).map(item=><Btn key={item.attachmentId}
            onClick={()=>onOpenAttachment?.(item)} disabled={!onOpenAttachment}><FileText size={14}/>{item.title}</Btn>)}
          {record.cycle===workflow.cycle&&onCorrect&&<Btn onClick={()=>onCorrect(record)}>{t('更正记录','Correct record')}</Btn>}
          {record.editedAt&&onHistory&&<Btn onClick={()=>onHistory(record)}>{t('更正历史','Correction history')}</Btn>}
          {onAttach&&<Btn onClick={()=>onAttach(record)}><Paperclip size={14}/>{t('关联附件','Attach file')}</Btn>}
        </div>
      </>}
    </article>)}
    {rows.length===0&&<small>{t('暂无处置记录','No treatment records yet')}</small>}
    {compact&&rows.length>1&&<small>{rows.length} {t('条处置记录','treatment records')}</small>}
    {!compact&&rows.length>8&&<div className="wov-actions"><small>{start+1}–{start+visible.length} / {rows.length}</small>
      <Btn disabled={start===0} onClick={()=>setPage(value=>Math.max(0,value-1))}>{t('上一页','Previous')}</Btn>
      <Btn disabled={start+8>=rows.length} onClick={()=>setPage(value=>value+1)}>{t('下一页','Next')}</Btn></div>}
  </section>;
}
