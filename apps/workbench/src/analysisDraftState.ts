import {validateSnapshot, type CanvasSnapshot, type ProjectScope} from './analysisCanvas.ts';

export type DraftReceipt = {analysisSessionId:string;analysisRevision:number;headRevision?:number;contentSha256:string};
export type PendingDraft = {path:string;body:object;snapshot:CanvasSnapshot};
export function draftChanged(value:CanvasSnapshot|null,saved:string,includeViewport=true):boolean {
  if(!value)return false;
  if(!saved)return true;
  if(includeViewport)return JSON.stringify(value)!==saved;
  const previous=JSON.parse(saved) as CanvasSnapshot;
  return JSON.stringify({...value,viewport:previous.viewport})!==saved;
}
export function blankAnalysisDraft(scope:ProjectScope, now=new Date()):CanvasSnapshot {
  return {schemaVersion:1,...scope,title:'新建分析',status:'analyzing',
    context:{objectIds:[],timeFrom:new Date(now.getTime()-86400000).toISOString(),timeTo:now.toISOString(),timezone:'Asia/Shanghai'},
    cards:[],relations:[],viewport:{x:24,y:24,zoom:1}};
}
export function draftProblems(value:CanvasSnapshot,scope:ProjectScope):string[] {
  const errors=validateSnapshot(value,scope);
  if(!['analyzing','awaiting_field_check','awaiting_expert_review'].includes(value.status))errors.push('请选择有效的分析进度');
  if(value.cards.some(c=>c.kind!=='analysis'||c.source)||value.context.objectIds.length||value.context.eventId||value.context.workOrderId)errors.push('本阶段只支持人工分析内容');
  if(value.title!==value.title.trim()||value.cards.some(c=>c.title!==c.title.trim())||value.relations.some(r=>r.origin!=='manual'||r.reason!==r.reason.trim()))errors.push('名称与关系依据不能以空格开头或结尾');
  if(value.cards.some(c=>typeof c.note!=='string'||c.note.includes('\0')))errors.push('笔记内容无效');
  if(new TextEncoder().encode(JSON.stringify(value)).byteLength>262144)errors.push('分析内容过大，请减少本次笔记内容');
  return [...new Set(errors)];
}
export function pendingDraft(snapshot:CanvasSnapshot,receipt:DraftReceipt|null,requestId:string,restoreRevision?:number):PendingDraft {
  const action=restoreRevision!==undefined?'restore':receipt?'save':'create';
  if(action==='restore'&&!receipt)throw new Error('A saved analysis is required');
  return {path:'/api/workbench/analysis-sessions/'+action,snapshot:structuredClone(snapshot),body:{requestId,
    ...(receipt?{analysisSessionId:receipt.analysisSessionId,expectedAnalysisRevision:receipt.headRevision??receipt.analysisRevision}:{}),
    ...(restoreRevision!==undefined?{restoreRevision}:{snapshot:structuredClone(snapshot)})}};
}
