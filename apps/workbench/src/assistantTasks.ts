import type {CanvasSnapshot,ProjectScope} from './analysisCanvas.ts';
import {validateSnapshot} from './analysisCanvas.ts';
import type {DraftReceipt} from './analysisDraftState';
export const TASK_PROTOCOL='ontovis-engineering-tasks-v1';
export type TaskCandidate={key:string;kind:string;title:string;identifier:string;version:string|number;state?:string;faultCode?:string;simulated:boolean;reason:string};
export type TaskReceipt={operationId:string;state:'applied_draft'|'saved';saveRequested?:boolean;analysisSessionId:string;analysisRevision:number;snapshotSha256:string;items:{kind:string;status:string;identifier?:string;cardId?:string;simulated?:boolean}[]};
export type EngineeringTask={mode:'workbench'|'cockpit_query';baseDigest:string;plan:{intent:'query'|'edit';queries:{tool:string;query:string;faultCode:string}[];actions:{kind:string;targets:string[];text:string;x:number|null;y:number|null}[]};
 results:TaskCandidate[];graphs:{kind:'engineering'|'knowledge';graph:Record<string,unknown>}[];trace:{tool:string;state:string;count?:number;total?:number;nextCursor?:number|string|null;reason?:string;truncated?:boolean;scope?:string}[];
 reads:number;readLimit:number;receipts:TaskReceipt[];execution:string};
export type PreparedTask={operationId:string;baseDigest:string;snapshot:CanvasSnapshot;receipts:TaskReceipt['items'];wantsSave:boolean;analysis:DraftReceipt;baseline:CanvasSnapshot|null;alreadyApplied?:boolean};
export async function snapshotDigest(raw:string){return [...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(raw)))].map(n=>n.toString(16).padStart(2,'0')).join('');}
export function checkedTaskSnapshot(current:CanvasSnapshot,prepared:PreparedTask,scope:ProjectScope,baseJson:string){
 if(JSON.stringify(current)!==baseJson)throw new Error('画布已变化，请重新发送操作指令；当前修改已保留。');
 const errors=validateSnapshot(prepared.snapshot,scope);if(errors.length)throw new Error(errors[0]);
 if(prepared.alreadyApplied)throw new Error('此操作已有执行回执，未重复应用。需要再次修改时请发送新指令。');
 return structuredClone(prepared.snapshot);
}
export const taskActionNames:Record<string,[string,string]>={add_results:['加入检索资料','Add results'],remove_cards:['删除资料卡','Remove cards'],add_note:['添加待核验笔记','Add note'],arrange:['整理布局','Arrange'],rename:['修改画布名称','Rename'],save:['保存画布','Save'],set_window:['调整趋势时间','Change trend window'],add_relation:['添加假设关联','Add hypothesis relation'],move_card:['移动资料卡','Move card'],resize_card:['调整资料卡大小','Resize card']};
export function canApplyFreshTask(task:EngineeringTask|undefined,fresh:boolean,hasUnsaved:boolean){
 if(!fresh||!task||task.mode!=='workbench'||task.plan.intent!=='edit'||!task.plan.actions.length||task.receipts.length)return false;
 if(hasUnsaved&&task.plan.actions.some(a=>a.kind==='save'))return false;
 if(task.trace.some(t=>t.nextCursor!=null)&&task.plan.actions.some(a=>a.kind==='add_results'&&!a.targets.length))return false;
 return true;
}
