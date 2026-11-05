import type {EvidenceSource,Recommendation} from './analysisSources';
import type {Investigation,WorkOrderDetail,AssistantTransfer} from './workOrderTypes';

export type ProgressSource=Pick<EvidenceSource,'orderId'|'orderRevision'|'state'|'title'|'investigation'|'checks'|'note'|'diagnosis'>;
export const progressTargetLabel=(key:string,source:ProgressSource)=>source.diagnosis?.nodes?.find(row=>row.locateKey===key)?.label;
export type ProgressRow={id:string;kind:'hypothesis'|'step';before?:Investigation['hypotheses'][number]|Investigation['steps'][number];after?:Investigation['hypotheses'][number]|Investigation['steps'][number];change:'added'|'removed'|'changed'|'unchanged'};
const signature=(row:NonNullable<ProgressRow['before']>)=>'description' in row?[row.description,row.status,row.basis]:[row.title,row.targetKey,row.outcome,row.result];
const same=(a:NonNullable<ProgressRow['before']>,b:NonNullable<ProgressRow['after']>)=>JSON.stringify(signature(a))===JSON.stringify(signature(b));
export function progressRows(before:ProgressSource,after:ProgressSource):ProgressRow[]{
 return (['hypotheses','steps'] as const).flatMap(group=>{
  const old=before.investigation?.[group]??[],current=after.investigation?.[group]??[],ids=[...old.map(r=>r.id),...current.filter(r=>!old.some(p=>p.id===r.id)).map(r=>r.id)];
  return ids.map(id=>{const a=old.find(r=>r.id===id),b=current.find(r=>r.id===id);return {id,kind:group==='hypotheses'?'hypothesis':'step',before:a,after:b,change:!a?'added':!b?'removed':same(a,b)?'unchanged':'changed'} as ProgressRow;});
 });
}
export function progressRecommendation(before:ProgressSource,after:WorkOrderDetail):Recommendation|null{
 if(!before.orderId||after.orderId!==before.orderId||!Number.isInteger(after.orderRevision)||after.orderRevision<=(before.orderRevision??0))return null;
 return {key:'work-order-progress:'+after.orderId+':'+after.orderRevision,kind:'work_order',title:after.title,reason:'已明确选择的本单进展',selector:{orderId:after.orderId,expectedOrderRevision:after.orderRevision}};
}
export function adoptionProgress(item:AssistantTransfer['items'][number],plan:Investigation){
 const row=item.kind==='hypothesis'?plan.hypotheses.find(r=>r.id===item.planItemId):plan.steps.find(r=>r.id===item.planItemId);
 if(!row)return {retained:false,edited:false,text:'',record:'',state:'removed',targetKey:''};
 const text='description' in row?row.description:row.title,record='basis' in row?row.basis:row.result,state='status' in row?row.status:row.outcome,targetKey='targetKey' in row?row.targetKey:'';
 return {retained:true,edited:text!==((item.kind==='gap'?'补充证据：':'')+item.text)||targetKey!==item.targetKey,text,record,state,targetKey};
}
