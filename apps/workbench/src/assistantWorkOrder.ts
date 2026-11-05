import {ApiError} from './api.ts';
import type {AssistantRun,AssistantSource} from './assistantApi';
import type {WorkOrderDetail} from './workOrderTypes';
export interface TransferItem {id:string;kind:'hypothesis'|'step'|'gap';text:string;refs:string[]}
export interface TransferProposal {runId:string;runVersion:number;conversationId:string|null;conversationVersion:number;
 analysisSessionId:string;analysisRevision:number;proposalSha256:string;items:TransferItem[];sources:AssistantSource[];
 observations:{text:string;refs:string[]}[];engineeringConfirmation:false}
export interface TransferPreview {proposal:TransferProposal;order:WorkOrderDetail;adoptedItemIds:string[];modelCalls:0}
export interface TransferEdit {id:string;text:string;targetKey:string;selected:boolean}
export function transferEdits(preview:TransferPreview,previous:TransferEdit[]=[]){
 return preview.proposal.items.map(item=>{const old=previous.find(row=>row.id===item.id);return {id:item.id,text:old?.text??item.text,
  targetKey:item.kind==='hypothesis'?'':old?.targetKey??'',selected:!preview.adoptedItemIds.includes(item.id)&&(old?.selected??item.kind!=='gap')};});
}
export function transferProblems(preview:TransferPreview,edits:TransferEdit[]){
 const selected=edits.filter(row=>row.selected),items=new Map(preview.proposal.items.map(row=>[row.id,row])),errors:string[]=[];
 if(!['diagnosing','investigating'].includes(preview.order.state))errors.push('state');
 if(!selected.length)errors.push('empty');
 if(selected.some(row=>!row.text.trim()||row.text.trim().length+(items.get(row.id)?.kind==='gap'?5:0)>500))errors.push('text');
 if(preview.order.investigation.hypotheses.length+selected.filter(row=>items.get(row.id)?.kind==='hypothesis').length>6||
    preview.order.investigation.steps.length+selected.filter(row=>items.get(row.id)?.kind!=='hypothesis').length>12)errors.push('limit');
 return errors;
}
export function transferBody(preview:TransferPreview,edits:TransferEdit[]){
 return {runId:preview.proposal.runId,orderId:preview.order.orderId,expectedOrderRevision:preview.order.orderRevision,
  expectedProposalSha256:preview.proposal.proposalSha256,items:edits.filter(row=>row.selected).map(({id,text,targetKey})=>({id,text:text.trim(),targetKey}))};
}
export function canTransfer(run:AssistantRun){return ['complete','partial'].includes(run.state)&&!!run.result;}
export function transferMessage(error:unknown,en:boolean){
 const code=error instanceof ApiError?error.code:'';
 const labels:Record<string,[string,string]>={ASSISTANT_TRANSFER_UNAVAILABLE:['回答来源或策略已变化，本轮建议暂不能采用。','Sources or policy changed. Suggestions from this turn cannot be used.'],
 ASSISTANT_TRANSFER_INVALID:['请检查所选条目、长度和关联对象。','Check selected items, text length and object references.'],
 ASSISTANT_PROPOSAL_CHANGED:['建议内容已有变化，请重新读取后比较。','Suggestions changed. Reload and compare before saving.'],
 WORK_ORDER_CHANGED:['工单已有新版本；你的编辑保留，重新读取后再比较。','The work order changed. Your edits are retained; reload and compare.'],
 WORK_ORDER_STATE_CONFLICT:['仅诊断中、排查中的工单可加入条目；待受理的工单请先受理，其他状态仅支持查看。','Only diagnosing or investigating orders can receive items. Accept open orders first; other states are read only.'],
 WORK_ORDER_PLAN_LIMIT:['本单最多6条假设、12个步骤，请减少选择或先整理现有方案。','This order supports six hypotheses and twelve steps. Select fewer items or edit its existing plan.'],
 WORK_ORDER_ITEM_DUPLICATE:['本单已有相同内容，请取消重复条目。','The order already contains this text. Deselect duplicate items.'],
 ASSISTANT_ITEM_ALREADY_APPLIED:['部分条目已被采纳，请重新读取后选择其余条目。','Some items were already adopted. Reload to select remaining items.']};
 return labels[code]?.[en?1:0];
}
