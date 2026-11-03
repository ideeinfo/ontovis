import {ApiError,failureMessage} from './api.ts';
import type {CanvasCard} from './analysisCanvas';
import type {SourceAnchor} from './analysisSources';
import type {DraftApi} from './AnalysisWorkspace';
import type {LlmService,LlmTask} from './llmSettings';
export const ASSISTANT_ROOT='/api/workbench/assistant';
export const sourceLabels:Record<string,[string,string]>={object:['工程对象摘要','Object summary'],alarm:['模拟报警','Simulated alarm'],trend:['趋势汇总','Trend summary'],drawing:['图纸元数据','Drawing metadata'],photo:['照片定位元数据','Photo location metadata'],model:['模型绑定摘要','Model binding metadata'],document:['文档知识摘录','Document knowledge excerpt'],work_order:['历史工单摘要','Historical work order']};
export const materialRoles:Record<string,[string,string]>={
 alarm:['事件、时间与状态 · 保留模拟标记','Events, timing and state · simulation labels retained'],
 trend:['固定窗口统计与质量 · 不发送完整曲线','Fixed-window statistics and quality · no full curve'],
 object:['有限工程关联 · 候选接线须复核','Bounded associations · candidate wiring needs review'],
 document:['固定知识摘录与证据页 · 非全文','Fixed knowledge excerpts and evidence pages · not full text'],
 drawing:['仅版本与页码 · 未读取图面和接线','Version and page only · drawing and wiring not read'],
 photo:['仅定位与用途 · 未读取照片像素','Location and purpose only · image pixels not read'],
 model:['绑定与精度摘要 · 不含模型几何','Binding and precision summary · no geometry'],
 work_order:['固定版人工记录 · 未登记不代表未执行','Fixed human records · unrecorded does not mean unperformed']
};
export function assistantRunPhase(run:AssistantRun):'reading'|'model'|'validating'|'complete'|null{
 if(['reading','model','validating'].includes(run.state))return run.state as 'reading'|'model'|'validating';
 if(['complete','partial'].includes(run.state)&&run.result)return 'complete';
 if(run.error?.startsWith('ASSISTANT_MODEL_')||run.error==='ASSISTANT_OUTPUT_INCOMPLETE'||run.error==='ASSISTANT_OUTPUT_REFUSED')return 'model';
 if(run.error==='ASSISTANT_OUTPUT_INVALID'||run.error==='ASSISTANT_REFERENCE_INVALID'||run.error==='ASSISTANT_OUTPUT_EMPTY')return 'validating';
 if(run.error==='ASSISTANT_NO_EVIDENCE')return 'reading';
 return null;
}
export function defaultAssistantEvidence(cards:CanvasCard[]){
 const kinds=['alarm','object','document','trend','work_order','model3d','drawing','photo'];
 const selected:string[]=[];
 for(const kind of kinds){const card=cards.find(c=>c.kind===kind&&c.source&&!c.historical)??cards.find(c=>c.kind===kind&&c.source);if(card&&!selected.includes(card.source!.id))selected.push(card.source!.id);if(selected.length===6)break;}
 for(const card of cards){if(selected.length===6)break;if(card.source&&!selected.includes(card.source.id))selected.push(card.source.id);}
 return selected;
}
export interface AssistantPolicy {enabled:boolean;serviceRef:string;allowedKinds:string[];reads:number;parallel:number;seconds:number}
export interface AssistantPolicyView {revision:number;policy:AssistantPolicy;canManage:boolean;accessRevision:string;savedAt:string|null;
 service:LlmService;services?:Record<LlmTask,LlmService>;}
export function assistantSendBlocker(state:{busy:boolean;active:boolean;pending:boolean;loadingHistory:boolean;focusedEarlier:boolean;taskMismatch:boolean;hasReceipt:boolean;view:AssistantPolicyView|null;policyError:unknown;service?:LlmService;selectedCount:number;question:string}){
 if(state.busy)return 'ASSISTANT_WORKING';
 if(state.pending)return 'ASSISTANT_START_UNCERTAIN';
 if(state.active)return 'ASSISTANT_RUNNING';
 if(state.loadingHistory)return 'ASSISTANT_HISTORY_LOADING';
 if(state.focusedEarlier)return 'ASSISTANT_HISTORICAL_TURN';
 if(state.taskMismatch)return 'LLM_CONVERSATION_TASK_CHANGED';
 if(!state.hasReceipt)return 'ASSISTANT_SAVE_REQUIRED';
 if(!state.view)return state.policyError?'ASSISTANT_POLICY_READ_FAILED':'ASSISTANT_POLICY_LOADING';
 if(!state.view.policy.enabled)return 'ASSISTANT_POLICY_DISABLED';
 if(!state.service?.enabled)return state.service?.reason||'ASSISTANT_SERVICE_UNAVAILABLE';
 if(!state.service.canRun)return state.service.reason||'ASSISTANT_RUN_FORBIDDEN';
 if(!state.selectedCount)return 'ASSISTANT_SELECTION_REQUIRED';
 if(state.selectedCount>Math.min(state.view.policy.reads,state.service?.settings?.readLimit??8))return 'ASSISTANT_SELECTION_LIMIT';
 if(!state.question.trim())return 'ASSISTANT_QUESTION_REQUIRED';
 return null;
}
export function policyChanges(current:AssistantPolicy,next:AssistantPolicy){
 return (['enabled','allowedKinds','reads','parallel','seconds'] as const).filter(key=>key==='allowedKinds'
  ?JSON.stringify([...current.allowedKinds].sort())!==JSON.stringify([...next.allowedKinds].sort())
  :current[key]!==next[key]);
}
export interface RetrievalTrace {version:1;plan:{tool:string;faultCode:string|null;operations:number};anchor:{nodeId:string;pageNumber:number}|null;tools:{tool:string;state:string;matches?:number;nodes?:number;relations?:number;truncated?:boolean}[]}
export function assistantSourceAnchor(source:AssistantSource):SourceAnchor|null{const anchor=source.retrieval?.anchor;return source.kind==='document'&&source.retrieval?.version===1&&anchor&&typeof anchor.nodeId==='string'&&anchor.nodeId.length>0&&anchor.nodeId.length<=160&&Number.isInteger(anchor.pageNumber)&&anchor.pageNumber>=1?anchor:null;}
export interface AssistantSource {retrieval?:RetrievalTrace;key:string;kind:string;evidenceRefId:string;sourceRevision?:string;summary?:string;availability?:string;reason?:string;summaryHash?:string;retrievalRevision?:string}
export interface AssistantRun {runId:string;state:string;version:number;analysisSessionId:string;analysisRevision:number;policyRevision:number;
 taskId?:LlmTask;
 question?:string;conversationId?:string|null;conversationVersion?:number;parentRunId?:string|null;
 progress:{key:string;state:string}[];sources:AssistantSource[];error:string|null;result:null|{answer:Record<'observations'|'hypotheses'|'gaps'|'nextSteps',{text:string;refs:string[]}[]>;model?:{taskId?:LlmTask;execution?:'ontobase'|'ontovis';provider?:string;modelId?:string};usage:Record<string,number>;modelCalls:number;engineeringConfirmation:false;partial:boolean;context?:{includedTurns:number;skippedTurns:{runId:string;reason:string}[]}};}
export interface AssistantConversation {conversationId:string;title:string;version:number;headRunId:string;analysisSessionId:string;analysisRevision:number;updatedAt:string}
export interface AssistantConversationDetail extends AssistantConversation {items:AssistantRun[];hasEarlier:boolean}
export interface EngineeringGraph {root:string;revision:string;truncated:boolean;gaps:string[];nodes:{id:string;kind:string;title:string;entityUid?:string;statement?:string;documentName?:string}[];
 relations:{id:string;source:string;target:string;type:string;status:string;provenance:{recordId:string;recordRevision:string;pageNumber?:number;drawingUid?:string;importId?:string;portIds?:string[]}}[]}
export const relationLabels:Record<string,[string,string]>={DEFINITION_MEMBER:['柜内工程定义关系','Cabinet definition membership'],INSTANCE_OF:['安装对象采用定义','Instance of definition'],DRAWING_LOCATION:['图纸定位记录','Drawing location'],CANDIDATE_CONNECTION:['候选连接 · 待复核','Candidate connection · unreviewed'],KNOWLEDGE_MAPPING:['已确认文档知识映射','Confirmed document mapping']};
export function filterEngineeringGraph(graph:EngineeringGraph,relation:string,query:string){
 const q=query.trim().toLocaleLowerCase(),nodes=new Map(graph.nodes.map(n=>[n.id,n]));
 return graph.relations.filter(edge=>(!relation||edge.type===relation)&&(!q||[nodes.get(edge.source)?.title,nodes.get(edge.target)?.title,relationLabels[edge.type]?.join(' ')].some(v=>v?.toLocaleLowerCase().includes(q))));
}
export function groupEngineeringEdges(edges:EngineeringGraph['relations']){
 const groups=new Map<string,EngineeringGraph['relations']>();
 for(const edge of edges){const key=edge.type==='CANDIDATE_CONNECTION'?JSON.stringify([edge.type,...[edge.source,edge.target].sort()]):edge.id;
  const existing=groups.get(key);if(existing)existing.push(edge);else groups.set(key,[edge]);}
 return [...groups.values()];
}
export function mergeConversationTurns(previous:AssistantRun[],latest:AssistantRun|null){
 const rows=new Map(previous.map(r=>[r.runId,r]));if(latest)rows.set(latest.runId,latest);
 return [...rows.values()].sort((a,b)=>(a.conversationVersion??0)-(b.conversationVersion??0));
}
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
 const readiness:Record<string,[string,string]>={
  ASSISTANT_WORKING:['正在处理当前操作，请稍候。','Wait for the current operation to finish.'],
  ASSISTANT_START_UNCERTAIN:['提交结果尚未确认，请先检查运行。','The submission result is uncertain. Check the run first.'],
  ASSISTANT_RUNNING:['本轮回答尚未结束，请等待完成或停止。','Wait for this answer to finish or stop it.'],
  ASSISTANT_HISTORY_LOADING:['正在读取对话，请稍候。','Loading the conversation. Please wait.'],
  ASSISTANT_HISTORICAL_TURN:['当前为历史轮次，请打开完整对话后继续。','Open the full conversation to continue from this historical turn.'],
  ASSISTANT_SAVE_REQUIRED:['请先保存当前画布，再向助手提问。','Save the current canvas before asking the assistant.'],
  ASSISTANT_POLICY_LOADING:['正在检查助手服务…','Checking assistant availability…'],
  LLM_CONNECTION_REVIEW_REQUIRED:['请在 AI 策略中选择 OntoBase 模型连接并保存。','Choose an OntoBase model connection in AI policy and save.'],
  LLM_SETTINGS_INVALID:['请检查能力参数范围与任务指令。','Check the capability limits and instructions.'],
  LLM_REASONING_UNSUPPORTED:['当前模型不支持所选推理强度，请读取目录后重新选择。','This model does not support the reasoning effort. Read the catalogue and choose again.'],
  ASSISTANT_POLICY_READ_FAILED:['助手服务状态读取失败，请刷新服务。','Could not read assistant availability. Refresh the service.'],
  SOURCE_UNAVAILABLE:['无法读取 OntoBase 模型服务，请刷新服务后重试。','Cannot read the OntoBase model service. Refresh the service and retry.'],
  ASSISTANT_PROJECT_DISABLED:['OntoBase 尚未为本项目开放助手服务，请联系管理员。','Ask an administrator to enable the OntoBase assistant for this project.'],
  ASSISTANT_SERVICE_NOT_APPROVED:['OntoBase 模型连接配置不可用，请联系管理员检查。','Ask an administrator to check the OntoBase model connection.'],
  ASSISTANT_SELECTION_REQUIRED:['请至少选择一份资料。','Select at least one material.'],
  ASSISTANT_SELECTION_LIMIT:['已选资料超过本项目上限，请减少选择。','Reduce the selection to the project limit.'],
  ASSISTANT_QUESTION_REQUIRED:['请输入问题后发送。','Enter a question to send.']};
 if(readiness[code])return readiness[code][en?1:0];
 if(code==='ASSISTANT_CANCELLED')return en?'This run stopped. No model answer was applied.':'本次运行已停止，未采用模型结果。';
 const modelErrors:Record<string,[string,string]>={LLM_CONFIGURATION_CHANGED:['模型配置已更新，请刷新连接与配置后比较；当前修改会保留。','Model settings changed. Refresh connections and settings to compare; your edits are kept.'],LLM_KEY_REQUIRED:['请先配置所选来源的 API Key。','Configure the selected provider’s API key first.'],LLM_KEY_INVALID:['密钥格式不正确，请检查后重试。','Check the API key format.'],LLM_MODEL_REQUIRED:['请选择或输入文本对话模型标识。','Select or enter a text-chat model ID.'],LLM_AUTH_FAILED:['来源未接受此密钥，请检查来源、地址和密钥是否匹配。','The provider rejected the key. Check its provider and endpoint.'],LLM_ENDPOINT_INVALID:['请输入所选来源支持的官方 HTTPS 地址。','Use a supported official HTTPS address for this provider.'],LLM_NEW_ENDPOINT_KEY_REQUIRED:['地址已变化，请重新填写此地址对应的密钥。','The endpoint changed. Enter the key for the new endpoint.'],LLM_KEY_STORE_UNAVAILABLE:['保存的密钥暂不可用，请联系管理员检查配置存储。','Saved credentials are unavailable. Ask an administrator to check the store.'],LLM_INHERITED_MODEL_FIXED:['现有服务的型号由源端管理；选择其他型号需先自主配置来源。','The existing service manages its model; configure the provider to choose another one.'],LLM_TASK_DISABLED:['此任务已关闭，请在 AI 策略中设置。','This task is disabled in the AI policy.'],LLM_TASK_INVALID:['任务类型不受支持，请刷新页面。','Unsupported task. Refresh the page.'],LLM_PROVIDER_UNAVAILABLE:['模型来源暂不可用；没有自动重发，请检查配置后重试。','The provider is unavailable. No automatic retry was made.'],LLM_CATALOGUE_INVALID:['模型目录返回格式不可用，可检查来源或手工输入型号。','The model catalogue is unusable. Check the provider or enter a model ID manually.'],LLM_RATE_LIMITED:['来源调用额度或频率受限，请稍后重试。','The provider rate or quota limit was reached.']};
 if(modelErrors[code])return modelErrors[code][en?1:0];
 if(code==='LLM_CONVERSATION_TASK_CHANGED')return en?'This conversation uses a different task. Start a new conversation for this task.':'当前对话属于另一任务，请为此任务新建对话。';
 const outcomes:Record<string,[string,string]>={
  ASSISTANT_MODEL_UNAVAILABLE:['模型阶段未完成；旧回执未保留具体原因。可修改问题后重新发送。','The model step failed; this older receipt has no detailed cause. Edit the question before sending again.'],
  ASSISTANT_MODEL_REQUEST_REJECTED:['模型服务拒绝了请求，请在 AI 策略核对模型与参数。','The model service rejected this request. Check the model and parameters in AI policy.'],
  ASSISTANT_MODEL_AUTH_FAILED:['模型连接未通过认证，请在 OntoBase 检查连接。','Model authentication failed. Check the connection in OntoBase.'],
  ASSISTANT_MODEL_ACCESS_DENIED:['当前模型连接没有访问权限，请在 OntoBase 核对。','The model connection lacks access. Check it in OntoBase.'],
  ASSISTANT_MODEL_RATE_LIMITED:['模型服务暂时限流，请稍后重新发送。','The model service is rate limited. Send again later.'],
  ASSISTANT_MODEL_QUOTA_EXCEEDED:['模型服务额度不足，请在 OntoBase 核对连接额度。','The model service quota is exhausted. Check the connection quota in OntoBase.'],
  ASSISTANT_MODEL_UPSTREAM_ERROR:['模型服务暂时出错，所选资料已保留。可稍后重新发送。','The model service returned an error. Materials remain selected; send again later.'],
  ASSISTANT_MODEL_CONNECTION_FAILED:['未能完成模型连接，所选资料已保留。请稍后再试。','The model connection failed. Materials remain selected; try again later.'],
  ASSISTANT_MODEL_TIMEOUT:['模型未在设定时限内完成；没有自动重复调用。可缩小问题后再试。','The model exceeded its time limit and was not called again. Try a narrower question.'],
  ASSISTANT_OUTPUT_INCOMPLETE:['模型回答被截断，未作为完整结果展示。可缩小问题后再试。','The answer was truncated and is not shown as a complete result. Try a narrower question.'],
  ASSISTANT_OUTPUT_REFUSED:['模型未接受本次问题，未生成可展示回答。可调整问题后再试。','The model declined this question. Edit it before trying again.'],
  ASSISTANT_OUTPUT_EMPTY:['模型返回了空回答。可明确本次要核对的问题后再试。','The model returned an empty answer. Make the requested check more specific and try again.']
 };
 if(outcomes[code])return outcomes[code][en?1:0];
 const messages:Record<string,[string,string]>={ASSISTANT_CONVERSATION_CHANGED:['对话已有更新，请重新打开当前对话后继续。','The conversation changed. Reopen it before continuing.'],ASSISTANT_HISTORY_SOURCES_CHANGED:['资料内容或关联已变化，相关旧轮次不参与当前分析。','Material contents or associations changed. Affected turns are excluded.'],ASSISTANT_HISTORY_SCOPE_LIMIT:['此页历史包含较多资料，可逐轮检查原回执。','This history page contains more materials. Check individual saved turns.'],ASSISTANT_HISTORY_INVALID:['历史对话范围不符合当前资料范围。','History is outside the current evidence scope.'],ASSISTANT_POLICY_DISABLED:['本项目尚未启用助手，请在 AI 策略中设置。','Enable the assistant in the project AI policy.'],ASSISTANT_SERVICE_DISABLED:['模型服务尚未启用。','The model service is not enabled.'],ASSISTANT_SERVICE_UNAVAILABLE:['源端模型服务暂不可用。','The source model service is unavailable.'],ASSISTANT_CONFIGURATION_CHANGED:['服务或权限已变化，请刷新后重新发起。','Service or permissions changed. Refresh before restarting.'],ASSISTANT_POLICY_CHANGED:['项目策略已变化，本次结果未继续使用。','The project policy changed. This result was not applied.'],ASSISTANT_RUN_CHANGED:['运行状态已更新，请重试停止。','The run changed. Retry stopping.'],ASSISTANT_BUSY:['当前已有运行，请稍后重试。','Another run is active. Retry later.'],ASSISTANT_TIMEOUT:['已达到运行时限，没有继续调用模型。','The time budget was reached. No further model call was made.'],ASSISTANT_INTERRUPTED:['服务重启使运行中断，未自动重发模型请求。','The run was interrupted by a restart and was not resubmitted.'],ASSISTANT_NO_EVIDENCE:['所选固定资料当前均不可用，未调用模型。','No selected evidence is available. The model was not called.'],ASSISTANT_OUTPUT_INVALID:['模型结果未通过结构校验，未作为回答显示。','The model output did not pass validation.'],ASSISTANT_REFERENCE_INVALID:['模型引用未通过校验，未作为回答显示。','Model references did not pass validation.'],ASSISTANT_RUN_FORBIDDEN:['当前账号没有运行或配置助手的权限。','This account cannot run or configure the assistant.']};
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
 conversations(analysisSessionId:string,expectedAnalysisRevision:number,signal?:AbortSignal){return this.api.request<{items:AssistantConversation[]}>(ASSISTANT_ROOT+'/conversations',{analysisSessionId,expectedAnalysisRevision},signal);}
 conversation(conversationId:string,beforeTurn?:number,signal?:AbortSignal){return this.api.request<AssistantConversationDetail>(ASSISTANT_ROOT+'/conversation',{conversationId,...(beforeTurn===undefined?{}:{beforeTurn})},signal);}
 graph(analysisSessionId:string,expectedAnalysisRevision:number,evidenceRefId:string,signal?:AbortSignal){return this.api.request<{graph:EngineeringGraph}>(ASSISTANT_ROOT+'/graph',{analysisSessionId,expectedAnalysisRevision,evidenceRefIds:[evidenceRefId]},signal);}
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
