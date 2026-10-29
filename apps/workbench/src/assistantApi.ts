import {ApiError,failureMessage} from './api.ts';
import type {DraftApi} from './AnalysisWorkspace';
export const ASSISTANT_ROOT='/api/workbench/assistant';
export const sourceLabels:Record<string,[string,string]>={object:['工程对象摘要','Object summary'],alarm:['模拟报警','Simulated alarm'],trend:['趋势汇总','Trend summary'],drawing:['图纸元数据','Drawing metadata'],photo:['照片定位元数据','Photo location metadata'],model:['模型绑定摘要','Model binding metadata'],document:['文档知识摘录','Document knowledge excerpt'],work_order:['历史工单摘要','Historical work order']};
export interface AssistantPolicy {enabled:boolean;serviceRef:string;allowedKinds:string[];reads:number;parallel:number;seconds:number}
export interface AssistantPolicyView {revision:number;policy:AssistantPolicy;canManage:boolean;accessRevision:string;savedAt:string|null;
 service:{enabled:boolean;canRun:boolean;serviceRef?:string;serviceRevision?:string;modelId?:string;reason?:string};}
export function policyChanges(current:AssistantPolicy,next:AssistantPolicy){
 return (['enabled','allowedKinds','reads','parallel','seconds'] as const).filter(key=>key==='allowedKinds'
  ?JSON.stringify([...current.allowedKinds].sort())!==JSON.stringify([...next.allowedKinds].sort())
  :current[key]!==next[key]);
}
export interface AssistantSource {key:string;kind:string;evidenceRefId:string;sourceRevision?:string;summary?:string;availability?:string;reason?:string}
export interface AssistantRun {runId:string;state:string;version:number;analysisSessionId:string;analysisRevision:number;policyRevision:number;
 progress:{key:string;state:string}[];sources:AssistantSource[];error:string|null;result:null|{answer:Record<'observations'|'hypotheses'|'gaps'|'nextSteps',{text:string;refs:string[]}[]>;usage:Record<string,number>;modelCalls:number;engineeringConfirmation:false;partial:boolean};}
export const running=(run:AssistantRun|null)=>!!run&&['reading','model','validating','cancel_requested'].includes(run.state);
export function assistantEvidenceKey(evidenceRefId:string,selected:string[]){
 const index=selected.indexOf(evidenceRefId);return index<0?null:`E${index+1}`;
}
export function policyProblems(value:AssistantPolicy){
 const errors:string[]=[];
 if(typeof value.enabled!=='boolean')errors.push('enabled');
 if(value.serviceRef!=='ontobase-qwen-ontovis-v1')errors.push('service');
 if(!value.allowedKinds.length||value.allowedKinds.some(v=>!Object.hasOwn(sourceLabels,v))||new Set(value.allowedKinds).size!==value.allowedKinds.length)errors.push('kinds');
 for(const [key,min,max] of [['reads',1,8],['parallel',1,2],['seconds',10,120]] as const)if(!Number.isInteger(value[key])||value[key]<min||value[key]>max)errors.push(key);
 return errors;
}
export function answerNote(run:AssistantRun){
 if(!run.result||!['complete','partial'].includes(run.state))throw new Error('No validated answer');
 const names={observations:'观察',hypotheses:'待验证假设',gaps:'缺口',nextSteps:'下一步核验'};
 const keys=new Set(run.sources.filter(s=>s.availability==='available').map(s=>s.key));
 const references=run.sources.filter(s=>keys.has(s.key)).map(s=>s.key+'：'+s.evidenceRefId+' @ '+(s.sourceRevision||'')).join('\n');
 const body=Object.entries(names).map(([key,name])=>name+'\n'+run.result!.answer[key as keyof typeof names].slice(0,3).map(row=>{
  if(row.refs.some(ref=>!keys.has(ref)))throw new Error('Invalid reference');
  return (row.text.length>200?row.text.slice(0,197)+'…':row.text)+(row.refs.length?' ['+row.refs.join(', ')+']':'');
 }).join('\n')).join('\n\n');
 return '助手整理 · 待人工核验（节选）\n'+body+'\n\n'+references;
}
export function assistantMessage(error:unknown,en=false){
 const code=error instanceof ApiError?error.code:typeof error==='string'?error:'';
 if(code==='ASSISTANT_CANCELLED')return en?'This run stopped. No model answer was applied.':'本次运行已停止，未采用模型结果。';
 const messages:Record<string,[string,string]>={ASSISTANT_POLICY_DISABLED:['本项目尚未启用助手，请在 AI 策略中设置。','Enable the assistant in the project AI policy.'],ASSISTANT_SERVICE_DISABLED:['模型服务尚未启用。','The model service is not enabled.'],ASSISTANT_SERVICE_UNAVAILABLE:['源端模型服务暂不可用。','The source model service is unavailable.'],ASSISTANT_MODEL_UNAVAILABLE:['模型未返回可用结果；已选资料仍保留。','No usable model response; selected materials remain.'],ASSISTANT_CONFIGURATION_CHANGED:['服务或权限已变化，请刷新后重新发起。','Service or permissions changed. Refresh before restarting.'],ASSISTANT_POLICY_CHANGED:['项目策略已变化，本次结果未继续使用。','The project policy changed. This result was not applied.'],ASSISTANT_RUN_CHANGED:['运行状态已更新，请重试停止。','The run changed. Retry stopping.'],ASSISTANT_BUSY:['当前已有运行，请稍后重试。','Another run is active. Retry later.'],ASSISTANT_TIMEOUT:['已达到运行时限，没有继续调用模型。','The time budget was reached. No further model call was made.'],ASSISTANT_INTERRUPTED:['服务重启使运行中断，未自动重发模型请求。','The run was interrupted by a restart and was not resubmitted.'],ASSISTANT_NO_EVIDENCE:['所选固定资料当前均不可用，未调用模型。','No selected evidence is available. The model was not called.'],ASSISTANT_OUTPUT_INVALID:['模型结果未通过结构校验，未作为回答显示。','The model output did not pass validation.'],ASSISTANT_REFERENCE_INVALID:['模型引用未通过校验，未作为回答显示。','Model references did not pass validation.'],ASSISTANT_RUN_FORBIDDEN:['当前账号没有运行或配置助手的权限。','This account cannot run or configure the assistant.']};
 return messages[code]?.[en?1:0]||failureMessage(typeof error==='string'?new ApiError(409,error):error,en?'en':'zh');
}
export class AssistantApi {
 readonly api:DraftApi;
 constructor(api:DraftApi){this.api=api;}
 policy(signal?:AbortSignal){return this.api.request<AssistantPolicyView>(ASSISTANT_ROOT+'/policy',{},signal);}
 preview(policy:AssistantPolicy,signal?:AbortSignal){return this.api.request<AssistantPolicyView>(ASSISTANT_ROOT+'/preview',{policy},signal);}
 history(signal?:AbortSignal){return this.api.request<AssistantPolicyView&{items:{revision:number;savedAt:string;operation:string;policy:AssistantPolicy}[]}>(ASSISTANT_ROOT+'/history',{},signal);}
 publish(view:AssistantPolicyView,policy:AssistantPolicy,restoreRevision?:number){return this.api.request<AssistantPolicyView>(ASSISTANT_ROOT+(restoreRevision===undefined?'/publish':'/rollback'),{
  requestId:crypto.randomUUID(),expectedRevision:view.revision,expectedAccessRevision:view.accessRevision,expectedServiceRevision:view.service.serviceRevision??null,
  ...(restoreRevision===undefined?{policy}:{restoreRevision})});}
 status(run:AssistantRun,signal?:AbortSignal){return this.api.request<AssistantRun>(ASSISTANT_ROOT+'/status',{runId:run.runId},signal);}
 async cancel(run:AssistantRun){try{return await this.api.request<AssistantRun>(ASSISTANT_ROOT+'/cancel',{runId:run.runId,expectedVersion:run.version});}
  catch(error){if(error instanceof ApiError&&error.code==='ASSISTANT_RUN_CHANGED'){const latest=await this.status(run);return this.api.request<AssistantRun>(ASSISTANT_ROOT+'/cancel',{runId:latest.runId,expectedVersion:latest.version});}throw error;}}
}

/** Retry status reads only. A failed read must never submit another model operation. */
export function watchAssistantRun(service:Pick<AssistantApi,'status'>,initial:AssistantRun,signal:AbortSignal,
 update:(run:AssistantRun)=>void,failed:(error:unknown,retrying:boolean)=>void){
 let run=initial,retries=0,stopped=false,timer:ReturnType<typeof setTimeout>|undefined;
 const stop=()=>{stopped=true;if(timer!==undefined)clearTimeout(timer);signal.removeEventListener('abort',stop);};
 const schedule=(delay:number)=>{timer=setTimeout(()=>void poll(),delay);};
 const poll=async()=>{
  try{
   const value=await service.status(run,signal);if(signal.aborted||stopped)return;
   run=value;retries=0;update(value);if(running(value)&&!signal.aborted&&!stopped)schedule(2000);
  }catch(error){
   if(signal.aborted||stopped)return;
   const temporary=error instanceof TypeError||error instanceof ApiError&&[429,502,503,504].includes(error.status);
   const delay=temporary?[1000,2500,5000][retries++]:undefined;
   failed(error,delay!==undefined);if(delay!==undefined&&!signal.aborted&&!stopped)schedule(delay);
  }
 };
 if(!signal.aborted){signal.addEventListener('abort',stop,{once:true});schedule(500);}
 return stop;
}
