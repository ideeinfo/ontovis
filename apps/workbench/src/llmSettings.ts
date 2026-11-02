import {ASSISTANT_ROOT} from './assistantApi.ts';
import type {DraftApi} from './AnalysisWorkspace';
export type LlmProvider='openai'|'gemini'|'qwen'|'deepseek';
export type LlmTask='analysis'|'query'|'work_order';
export const llmTaskNames:Record<LlmTask,[string,string]>={analysis:['故障分析','Fault analysis'],query:['资料问答','Material questions'],work_order:['工单建议','Work-order suggestions']};
export const llmProviderNames:Record<LlmProvider,string>={openai:'OpenAI',gemini:'Gemini',qwen:'Qwen',deepseek:'DeepSeek'};
export interface LlmService {taskId?:LlmTask;provider?:LlmProvider;modelId?:string|null;enabled:boolean;canRun:boolean;serviceRevision?:string;reason?:string|null;mode?:'inherited'|'managed';}
export interface LlmProviderConfig {id:LlmProvider;name:string;baseUrl:string;mode:'inherited'|'managed';keyConfigured:boolean;}
export interface LlmTaskConfig {id:LlmTask;nameZh:string;nameEn:string;provider:LlmProvider;modelId:string;enabled:boolean;}
export interface LlmConfiguration {revision:number;updatedAt:string|null;providers:LlmProviderConfig[];tasks:LlmTaskConfig[];services:Record<LlmTask,LlmService>;accessRevision:string;canManage:boolean;}
export type LlmChange={kind:'provider';provider:LlmProvider;baseUrl:string;mode:'inherited'|'managed';keyAction:'keep'|'replace'|'clear';apiKey:string|null}|{kind:'task';taskId:LlmTask;provider:LlmProvider;modelId:string;enabled:boolean};
export function modelTaskState(task:LlmTaskConfig,provider:LlmProviderConfig,service?:LlmService):'off'|'ready'|'unavailable'|'missing'{
 if(!task.enabled)return 'off';
 if(service?.enabled)return 'ready';
 return provider.mode==='inherited'?'unavailable':'missing';
}
export function modelChoices(items:string[],query:string){const q=query.trim().toLocaleLowerCase();return [...new Set(items)].filter(s=>s.toLocaleLowerCase().includes(q)).sort();}
export function providerChange(original:LlmProviderConfig,baseUrl:string,mode:LlmProviderConfig['mode'],key:string,clear:boolean):LlmChange{
 return {kind:'provider',provider:original.id,baseUrl:baseUrl.trim().replace(/\/$/,''),mode,keyAction:clear?'clear':key?'replace':'keep',apiKey:clear?null:key||null};
}
export function modelConfigurationApi(api:DraftApi){const scope=(api as DraftApi&{assistantScope?:()=>DraftApi}).assistantScope?.()??api;return {
 read:(signal?:AbortSignal)=>scope.request<LlmConfiguration>(ASSISTANT_ROOT+'/model-config',{},signal),
 save:(view:LlmConfiguration,change:LlmChange,requestId=crypto.randomUUID())=>scope.request<Omit<LlmConfiguration,'services'|'canManage'>>(ASSISTANT_ROOT+'/model-config-save',{requestId,expectedRevision:view.revision,expectedAccessRevision:view.accessRevision,change}),
 catalogue:(view:LlmConfiguration,provider:LlmProvider,baseUrl:string,apiKey:string|null,signal?:AbortSignal)=>scope.request<{items:string[];modelCalls:0;verified:'catalogue_only'}>(ASSISTANT_ROOT+'/model-catalogue',{provider,baseUrl,apiKey,expectedRevision:view.revision,expectedAccessRevision:view.accessRevision},signal)
};}
