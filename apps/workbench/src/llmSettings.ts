import {ASSISTANT_ROOT} from './assistantApi.ts';
import type {DraftApi} from './AnalysisWorkspace';
export type LlmTask='analysis'|'query'|'work_order';
export const llmTaskNames:Record<LlmTask,[string,string]>={analysis:['故障分析','Fault analysis'],query:['资料问答','Material questions'],work_order:['工单建议','Work-order suggestions']};
export const capabilityToolNames={selected_sources:['已选资料摘要（必选）','Selected source summaries (required)'],engineering_neighborhood:['工程对象邻域','Engineering object neighborhood'],manual_fault_lookup:['固定手册故障码检索','Fault-code lookup in the fixed manual']} as const;
export interface CapabilitySettings {enabled:boolean;connectionId:string|null;modelId:string;timeoutSeconds:number;concurrency:number;reasoningEffort:string;goal:string;focus:string;readLimit:number;readParallel:number;tools:string[];}
export interface LlmService {taskId?:LlmTask;execution?:'ontobase'|'ontovis';provider?:string|null;modelId?:string|null;enabled:boolean;canRun:boolean;serviceRevision?:string;reason?:string|null;settings?:CapabilitySettings;reasoningOptions?:string[];}
export interface ModelConnection {id:string;name:string;provider:string;version:number;keyConfigured:boolean;}
export interface LlmTaskConfig extends CapabilitySettings {id:LlmTask;nameZh:string;nameEn:string;configured:boolean;legacyNeedsReview:boolean;}
export interface LlmConfiguration {schemaVersion:2;protocol:string|null;defaultService:LlmService;revision:number;updatedAt:string|null;connections:ModelConnection[];connectionError:string|null;defaults:Record<LlmTask,CapabilitySettings>;tasks:LlmTaskConfig[];services:Record<LlmTask,LlmService>;accessRevision:string;canManage:boolean;}
export function modelTaskState(task:Pick<LlmTaskConfig,'enabled'|'legacyNeedsReview'>,service?:LlmService){return task.legacyNeedsReview?'review':!task.enabled?'off':service?.enabled?'ready':'unavailable';}
export function modelChoices(items:string[],query:string){const q=query.trim().toLocaleLowerCase();return [...new Set(items)].filter(s=>s.toLocaleLowerCase().includes(q)).sort();}
export function capabilitySettings(task:CapabilitySettings):CapabilitySettings {return {enabled:task.enabled,connectionId:task.connectionId,modelId:task.modelId,timeoutSeconds:task.timeoutSeconds,concurrency:task.concurrency,reasoningEffort:task.reasoningEffort,goal:task.goal,focus:task.focus,readLimit:task.readLimit,readParallel:task.readParallel,tools:[...task.tools]};}
export function capabilityProblems(value:CapabilitySettings){const errors:string[]=[];
 for(const [key,min,max] of [['timeoutSeconds',10,50],['concurrency',1,2],['readLimit',1,8],['readParallel',1,2]] as const)if(!Number.isInteger(value[key])||value[key]<min||value[key]>max)errors.push(key);
 if(!value.goal.trim()||value.goal.length>2000||value.focus.length>2000)errors.push('instructions');
 if(value.connectionId&&!/^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$/.test(value.modelId))errors.push('modelId');
 if(!value.connectionId&&value.modelId)errors.push('modelId');
 if(!value.tools.includes('selected_sources')||value.tools.some(tool=>!Object.hasOwn(capabilityToolNames,tool)))errors.push('tools');
 return errors;
}
export function modelConfigurationApi(api:DraftApi){const scope=(api as DraftApi&{assistantScope?:()=>DraftApi}).assistantScope?.()??api;return {
 read:(signal?:AbortSignal)=>scope.request<LlmConfiguration>(ASSISTANT_ROOT+'/model-config',{},signal),
 save:(view:LlmConfiguration,taskId:LlmTask,settings:CapabilitySettings,requestId=crypto.randomUUID())=>scope.request<LlmConfiguration>(ASSISTANT_ROOT+'/model-config-save',{requestId,expectedRevision:view.revision,expectedAccessRevision:view.accessRevision,change:{kind:'capability',taskId,settings:capabilitySettings(settings),expectedConnectionVersion:view.connections.find(c=>c.id===settings.connectionId)?.version??null}}),
 catalogue:(view:LlmConfiguration,connection:ModelConnection,signal?:AbortSignal)=>scope.request<{items:string[];reasoningOptions:Record<string,string[]>;modelCalls:0}>(ASSISTANT_ROOT+'/model-catalogue',{connectionId:connection.id,expectedConnectionVersion:connection.version,expectedRevision:view.revision,expectedAccessRevision:view.accessRevision},signal)
};}
