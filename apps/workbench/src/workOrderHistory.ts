import type {EvidenceSource} from './analysisSources';

export type HistoricalOrderSource=Pick<EvidenceSource,'orderId'|'orderRevision'|'faultCode'|'state'|'title'|'investigation'|'note'|'diagnosis'|'events'>;
export const orderStateLabel=(state:string|undefined,en:boolean)=>({open:['待受理','Open'],diagnosing:['诊断中','Diagnosing'],investigating:['排查中','Investigating'],review:['待复核','In review'],closed:['已关闭','Closed']} as Record<string,string[]>)[state||'']?.[en?1:0]||(en?'State unavailable':'状态未提供');
export const orderActionLabel=(action:string,en:boolean)=>({seed_demo:['创建演示工单','Demo order created'],create:['建立工单','Order created'],assign:['分派处理人','Handler assigned'],record:['保存处置记录','Treatment saved'],correct_record:['更正处置记录','Treatment corrected'],complete:['完成处理','Completed'],archive:['归档','Archived'],void:['作废并归档','Voided and archived'],reopen:['重新处理','Reopened'],attach:['添加附件','Attachment added'],detach:['移出附件','Attachment removed'],adopt_analysis:['采纳分析','Analysis adopted'],clear_analysis:['取消采纳','Adoption cleared'],link_analysis:['关联分析','Analysis linked'],accept:['受理','Accepted'],investigate:['开始排查','Investigation started'],submit:['提交复核','Submitted for review'],close:['关闭','Closed'],save_investigation:['保存排查记录','Investigation saved'],update_investigation:['更新排查记录','Investigation updated']} as Record<string,string[]>)[action]?.[en?1:0]||(en?'Record updated':'更新记录');
export const orderOutcomeLabel=(outcome:string,en:boolean)=>({pending:['待排查','Pending'],observed:['已记录观察','Observation recorded'],gap:['资料缺口','Evidence gap'],not_applicable:['不适用','Not applicable'],candidate:['待核假设','Candidate'],supported:['记录支持','Support recorded'],rejected:['记录排除','Exclusion recorded']} as Record<string,string[]>)[outcome]?.[en?1:0]||(en?'Not recorded':'未记录');
export function orderRecordTime(value:string|undefined,en:boolean){
 if(!value||!Number.isFinite(Date.parse(value)))return en?'Time unavailable':'时间未提供';
 return new Date(value).toLocaleString(en?'en-GB':'zh-CN',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
}
export function historicalOrderView(source:HistoricalOrderSource){
 const events=(source.events||[]).map((event,index)=>({...event,index})).reverse(),steps=source.investigation?.steps||[],hypotheses=source.investigation?.hypotheses||[];
 const conclusion=source.investigation?.conclusion?.trim(),recent=events.find(event=>event.note.trim()),note=source.note?.trim();
 const summary=conclusion?{kind:'conclusion',text:conclusion}:recent?{kind:'event',text:recent.note}:note?{kind:'note',text:note}:{kind:'empty',text:''};
 return {events,steps,hypotheses,summary,recent,simulated:events.some(event=>event.action==='seed_demo'),gap:source.diagnosis?.gap?.trim()||'',
  counts:{pending:steps.filter(step=>step.outcome==='pending').length,observed:steps.filter(step=>step.outcome==='observed').length,gap:steps.filter(step=>step.outcome==='gap').length,notApplicable:steps.filter(step=>step.outcome==='not_applicable').length}};
}
