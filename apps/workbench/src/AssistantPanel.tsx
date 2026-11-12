import {useEffect,useId,useMemo,useRef,useState} from 'react';
import {Plus,RefreshCw,Send,Square,ChevronDown,History} from 'lucide-react';
import {AssistantTaskResult} from './AssistantTaskResult';
import {snapshotDigest,canApplyFreshTask,TASK_PROTOCOL,type PreparedTask} from './assistantTasks';
import {AssistantRetrieval} from './AssistantRetrieval';
import type {SourceAnchor} from './analysisSources';
import {Btn} from './Primitives';
import {cancelled} from './api';
import type {DraftApi} from './AnalysisWorkspace';
import type {CanvasCard,CanvasSnapshot} from './analysisCanvas';
import type {DraftReceipt} from './analysisDraftState';
import {defaultAssistantEvidence,AssistantApi,ASSISTANT_ROOT,mergeConversationTurns,assistantEvidenceKey,assistantMessage,assistantSendBlocker,running,sourceLabels,materialRoles,watchAssistantRun,type AssistantConversation,type AssistantPolicyView,type AssistantRun,type AssistantSource} from './assistantApi';
import {AssistantGraph} from './AssistantGraph';
import {AssistantSourceViewer} from './AssistantSourceViewer';
import {AssistantTurn} from './AssistantTurn';
import {AssistantWorkOrderDialog} from './AssistantWorkOrderDialog';
import './assistant.css';
import {llmTaskNames,type LlmTask} from './llmSettings';

export function AssistantPanel({api,cards,receipt,en,canAddNote,onFocus,onAddNote,canTransfer=false,preferredOrderId,faultCode,onOpenOrder,initialRunId,queryOnly=false,snapshot,onApplyTask,onHandoff,initialQuestion,onInitialQuestionUsed,hasUnsaved=false,historyJson}:{api:DraftApi&{assistantScope?:()=>DraftApi};cards:CanvasCard[];receipt:DraftReceipt|null;en:boolean;canAddNote:boolean;onFocus:(card:CanvasCard,anchor?:SourceAnchor|null)=>void;onAddNote:(text:string)=>void;canTransfer?:boolean;preferredOrderId?:string;faultCode?:string;onOpenOrder?:(id:string,record?:string)=>void;initialRunId?:string;queryOnly?:boolean;snapshot?:CanvasSnapshot;hasUnsaved?:boolean;historyJson?:string;initialQuestion?:string;onInitialQuestionUsed?:()=>void;onHandoff?:(run:AssistantRun)=>void;onApplyTask?:(prepared:PreparedTask,baseJson:string)=>Promise<number|null>}){
 const service=useMemo(()=>new AssistantApi(api),[api]);const t=(zh:string,english:string)=>en?english:zh;
 const [taskId,setTaskId]=useState<LlmTask>(queryOnly?'query':'analysis');
 const available=cards.filter((card,index,all)=>card.source&&all.findIndex(v=>v.source?.id===card.source!.id)===index),inventory=available.map(card=>card.source!.id).join(':');
 const [view,setView]=useState<AssistantPolicyView|null>(null),[selected,setSelected]=useState<string[]>(()=>defaultAssistantEvidence(available));
 const [policyError,setPolicyError]=useState<unknown>(null),sendStatusId=useId();
 const [question,setQuestion]=useState(''),[run,setRun]=useState<AssistantRun|null>(null),[error,setError]=useState<unknown>(null),[busy,setBusy]=useState(false),[reload,setReload]=useState(0),[summaries,setSummaries]=useState<AssistantSource[]|null>(null),[pending,setPending]=useState<string|null>(null);
 const [pollState,setPollState]=useState<'reading'|'retrying'|'paused'>('reading'),[pollReload,setPollReload]=useState(0);
 const [conversations,setConversations]=useState<AssistantConversation[]>([]),[conversation,setConversation]=useState<AssistantConversation|null>(null),[turns,setTurns]=useState<AssistantRun[]>([]),[hasEarlier,setHasEarlier]=useState(false);
 const [loadingHistory,setLoadingHistory]=useState(false);
 const [contextOpen,setContextOpen]=useState(false),[historyOpen,setHistoryOpen]=useState(false);
 const scrollArea=useRef<HTMLDivElement>(null),composerInput=useRef<HTMLTextAreaElement>(null);
 const autoScroll=useRef(true);
 const [transferRun,setTransferRun]=useState<AssistantRun|null>(null);
 const [sourceView,setSourceView]=useState<{runId:string;reference:AssistantSource}|null>(null);
 const historyGeneration=useRef(0);
 const automatic=useRef<{runId:string;context:string}|null>(null),applying=useRef(false),applyTaskRef=useRef(onApplyTask);applyTaskRef.current=onApplyTask;
 const draftId=useRef(crypto.randomUUID()),execution=useRef<{runId:string;keys:string[];prepared:PreparedTask;savedRevision:number|null}|null>(null);
 const [executionPending,setExecutionPending]=useState(false);
 const latest=useRef<AssistantRun|null>(null);latest.current=run;
 const context=`${api.epoch}:${api.revision}:${receipt?.analysisSessionId}:${receipt?.analysisRevision}`;
 const current=useRef(context);current.current=context;
 const alive=useRef(true),scope=useRef<AssistantApi|null>(null);
 useEffect(()=>{alive.current=true;automatic.current=null;setRun(null);setError(null);setPending(null);setSummaries(null);setConversation(null);setConversations([]);setTurns([]);setHasEarlier(false);setLoadingHistory(false);setTransferRun(null);setSourceView(null);historyGeneration.current++;setQuestion(initialQuestion??'');if(initialQuestion)onInitialQuestionUsed?.();
  const fixed=new AssistantApi(api.assistantScope?.()??api);scope.current=fixed;
  return()=>{alive.current=false;const previous=latest.current;if(running(previous))void fixed.cancel(previous!).catch(()=>{});};
 },[context]);
 useEffect(()=>{setSelected(previous=>previous.filter(id=>available.some(card=>card.source!.id===id)));setSummaries(null);},[inventory]);
 useEffect(()=>{const abort=new AbortController();setView(null);setPolicyError(null);service.policy(abort.signal).then(value=>{if(!abort.signal.aborted){setView(value);setSelected(ids=>ids.slice(0,value.policy.reads));}}).catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setPolicyError(e);});return()=>abort.abort();},[service,context,reload]);
 useEffect(()=>{if(busy||!run||!running(run))return;const abort=new AbortController(),key=context;
  const stop=watchAssistantRun(service,run,abort.signal,value=>{if(current.current===key){setRun(value);setError(null);setPollState('reading');}},
   (e,retrying)=>{if(current.current===key){setError(e);setPollState(retrying?'retrying':'paused');}});
  return()=>{abort.abort();stop();};
 },[run?.runId,run?.state,context,reload,pollReload,busy]);
 useEffect(()=>{if(!receipt)return;const abort=new AbortController(),generation=historyGeneration.current,key=context;
  setLoadingHistory(true);service.conversations(receipt.analysisSessionId,receipt.analysisRevision,abort.signal).then(async value=>{
   if(abort.signal.aborted||current.current!==key||historyGeneration.current!==generation)return;setConversations(value.items);
   if(initialRunId){const chosen=await api.request<AssistantRun>(ASSISTANT_ROOT+'/status',{runId:initialRunId},abort.signal);
    if(abort.signal.aborted||current.current!==key||historyGeneration.current!==generation)return;
    if(chosen.analysisSessionId!==receipt.analysisSessionId||chosen.analysisRevision!==receipt.analysisRevision)throw new Error(t('分析来源与本轮记录不匹配','Analysis and turn do not match'));
    const head=value.items.find(item=>item.conversationId===chosen.conversationId);
    if(!queryOnly)setTaskId(chosen.taskId??'analysis');setConversation(head??null);setTurns([chosen]);setRun(chosen);setHasEarlier(false);return;
   }
   if(initialQuestion)return;
   if(!value.items.length)return;const detail=await service.conversation(value.items[0].conversationId,undefined,abort.signal);
   if(abort.signal.aborted||current.current!==key||historyGeneration.current!==generation)return;
   // Saved analysis remains in Records; a query starts with its own conversation.
   if(queryOnly&&detail.items.at(-1)?.taskId!=='query')return;
   if(!queryOnly)setTaskId(detail.items.at(-1)?.taskId??'analysis');setConversation(detail);setTurns(detail.items);setRun(detail.items.at(-1)??null);setHasEarlier(detail.hasEarlier);
  }).catch(e=>{if(!abort.signal.aborted&&!cancelled(e)&&historyGeneration.current===generation)setError(e);}).finally(()=>{if(!abort.signal.aborted&&current.current===key&&historyGeneration.current===generation)setLoadingHistory(false);});
  return()=>abort.abort();
 },[service,context,initialRunId]);
 async function openConversation(id:string,earlier=false){if(!receipt)return;const key=context,generation=++historyGeneration.current;setLoadingHistory(true);setError(null);
  try{const detail=await service.conversation(id,earlier?Math.min(...turns.map(r=>r.conversationVersion||1)):undefined);
   if(!alive.current||current.current!==key||historyGeneration.current!==generation)return;
   setConversation(detail);setTurns(previous=>earlier?mergeConversationTurns([...detail.items,...previous],null):detail.items);setHasEarlier(detail.hasEarlier);
   if(!earlier){if(!queryOnly)setTaskId(detail.items.at(-1)?.taskId??'analysis');setRun(detail.items.at(-1)??null);setPending(null);setSummaries(null);setQuestion('');}
  }catch(e){if(alive.current&&current.current===key&&historyGeneration.current===generation)setError(e);}finally{if(alive.current&&current.current===key&&historyGeneration.current===generation)setLoadingHistory(false);}
 }
 function newConversation(){autoScroll.current=true;setContextOpen(false);setHistoryOpen(false);historyGeneration.current++;setConversation(null);setTurns([]);setRun(null);setPending(null);setError(null);setQuestion('');setHasEarlier(false);setLoadingHistory(false);}
 const transcript=mergeConversationTurns(turns,run);
 useEffect(()=>{if(autoScroll.current&&scrollArea.current)scrollArea.current.scrollTop=scrollArea.current.scrollHeight;},[run?.runId,run?.state,loadingHistory]);
 const selection=()=>({analysisSessionId:receipt!.analysisSessionId,expectedAnalysisRevision:receipt!.analysisRevision,evidenceRefIds:selected});
 async function start(){if((!receipt&&!snapshot)||!view||sendBlocker)return;autoScroll.current=true;const key=context,requestId=crypto.randomUUID(),fixed=scope.current!;historyGeneration.current++;setTurns(previous=>mergeConversationTurns(previous,run));setBusy(true);setError(null);setPending(requestId);setSummaries(null);
  try{const value=await api.request<AssistantRun>(ASSISTANT_ROOT+(snapshot?'/task-start':'/start'),{...(snapshot?{protocol:TASK_PROTOCOL,mode:queryOnly?'cockpit_query':'workbench',...(!queryOnly&&historyJson?{historyJson}:{}),snapshotJson:JSON.stringify(snapshot),analysisSessionId:receipt?.analysisSessionId??draftId.current,expectedAnalysisRevision:receipt?.analysisRevision??0,evidenceRefIds:receipt?selected:[]}:selection()),requestId,question:question.trim(),conversationId:conversation?.conversationId??null,expectedConversationVersion:conversation?.version??0,parentRunId:conversation?.headRunId??null,expectedPolicyRevision:view.revision,
    expectedAccessRevision:view.accessRevision,expectedServiceRevision:effectiveService?.serviceRevision,taskId});
    if(!alive.current||current.current!==key){if(running(value))void fixed.cancel(value).catch(()=>{});return;}automatic.current={runId:value.runId,context:key};setRun(value);setPending(null);setQuestion('');if(value.conversationId){const head={conversationId:value.conversationId,title:conversation?.title||value.question||'分析',version:value.conversationVersion||1,headRunId:value.runId,analysisSessionId:value.analysisSessionId,analysisRevision:value.analysisRevision,updatedAt:new Date().toISOString()};setConversation(head);setConversations(items=>[head,...items.filter(v=>v.conversationId!==head.conversationId)].slice(0,20));}
  }catch(e){if(alive.current&&current.current===key){setError(e);if(e&&typeof e==='object'&&'status'in e)setPending(null);}}
  finally{if(alive.current&&current.current===key)setBusy(false);}
 }
 async function inspectRun(){if(!pending&&!run)return;const key=context;setBusy(true);setError(null);try{
  const value=pending?await api.request<AssistantRun>(ASSISTANT_ROOT+'/status',{requestId:pending}):await service.status(run!);
  if(alive.current&&current.current===key){setRun(value);setPending(null);if(value.conversationId)setConversation({conversationId:value.conversationId,title:conversation?.title||value.question||'分析',version:value.conversationVersion||1,headRunId:value.runId,analysisSessionId:value.analysisSessionId,analysisRevision:value.analysisRevision,updatedAt:new Date().toISOString()});setPollState('reading');setPollReload(v=>v+1);}
 }catch(e){if(alive.current&&current.current===key)setError(e);}finally{if(alive.current&&current.current===key)setBusy(false);}}
 async function stop(){if(!run)return;setBusy(true);setError(null);try{setRun(await service.cancel(run));}catch(e){setError(e);}finally{setBusy(false);}}
 async function checkTurn(item:AssistantRun){const key=context;setBusy(true);setError(null);try{const value=await service.status(item);
  if(alive.current&&current.current===key){setTurns(previous=>mergeConversationTurns(previous,value));if(run?.runId===value.runId)setRun(value);}
 }catch(e){if(alive.current&&current.current===key)setError(e);}finally{if(alive.current&&current.current===key)setBusy(false);}}
 async function preview(){if(!receipt)return;const key=context;setBusy(true);setError(null);try{const value=await api.request<{items:AssistantSource[]}>(ASSISTANT_ROOT+'/summary',{...selection(),question:question.trim(),taskId});if(alive.current&&current.current===key)setSummaries(value.items);}catch(e){if(alive.current&&current.current===key)setError(e);}finally{if(alive.current&&current.current===key)setBusy(false);}}
 const focusedEarlier=!!initialRunId&&run?.runId===initialRunId&&!!conversation&&conversation.headRunId!==initialRunId;
 const active=running(run),locked=busy||running(run)||loadingHistory||!!pending||executionPending;
 const effectiveService=view?.services?.[taskId]??view?.service;
 const limit=Math.min(view?.policy.reads??8,effectiveService?.settings?.readLimit??8);
 const taskMismatch=!!conversation&&!!run&&(run.taskId??'analysis')!==taskId;
 const sendBlocker=assistantSendBlocker({busy,active,pending:!!pending||executionPending,loadingHistory,focusedEarlier,taskMismatch,hasReceipt:!!receipt,view,policyError,service:effectiveService,selectedCount:selected.length,question,projectTools:!!snapshot});
 const refreshService=()=>{setError(null);setReload(v=>v+1);};
 const canRefreshService=sendBlocker==='ASSISTANT_POLICY_READ_FAILED'||!!view&&view.policy.enabled&&!effectiveService?.enabled;
 const retryQuestion=(item:AssistantRun)=>{setQuestion(item.question??'');setSummaries(null);composerInput.current?.focus();};
 async function acknowledgeExecution(){const pending=execution.current;if(!pending)return;setBusy(true);setError(null);try{const value=await api.request<{run:AssistantRun}>(ASSISTANT_ROOT+'/task-ack',{runId:pending.runId,selectedKeys:pending.keys,snapshotJson:JSON.stringify(pending.prepared.snapshot),savedRevision:pending.savedRevision});setTurns(previous=>mergeConversationTurns(previous,value.run));setRun(value.run);execution.current=null;setExecutionPending(false);}catch(e){setError(e);}finally{setBusy(false);}}
 async function executeTask(item:AssistantRun,keys:string[]){if(!snapshot||!applyTaskRef.current||queryOnly||locked||execution.current||applying.current)return;const baseJson=JSON.stringify(snapshot),key=context,fixed=scope.current?.api??api;applying.current=true;setBusy(true);setError(null);try{if(await snapshotDigest(baseJson)!==item.result?.task?.baseDigest)throw new Error(t('画布已变化，请重新发送操作指令；修改已保留。','The draft changed. Send a new instruction; current edits are retained.'));const prepared=await fixed.request<PreparedTask>(ASSISTANT_ROOT+'/task-prepare',{runId:item.runId,selectedKeys:keys,snapshotJson:baseJson});if(!alive.current||current.current!==key||!applyTaskRef.current)return;const savedRevision=await applyTaskRef.current(prepared,baseJson);execution.current={runId:item.runId,keys,prepared,savedRevision};setExecutionPending(true);await acknowledgeExecution();}catch(e){if(alive.current)setError(e);}finally{applying.current=false;if(alive.current)setBusy(false);}}
 useEffect(()=>{const fresh=automatic.current;if(!fresh||!run||fresh.runId!==run.runId||fresh.context!==context||locked||queryOnly||!applyTaskRef.current||!['complete','partial'].includes(run.state))return;automatic.current=null;if(canApplyFreshTask(run.result?.task,true,hasUnsaved))void executeTask(run,[]);},[run?.runId,run?.state,busy,loadingHistory,executionPending]);
 async function taskPage(item:AssistantRun,index:number){setBusy(true);setError(null);try{const value=await api.request<AssistantRun>(ASSISTANT_ROOT+'/task-page',{runId:item.runId,traceIndex:index});setTurns(previous=>mergeConversationTurns(previous,value));if(run?.runId===item.runId)setRun(value);}catch(e){setError(e);}finally{setBusy(false);}}
 const metadataCount=available.filter(card=>selected.includes(card.source!.id)&&['drawing','photo','model3d'].includes(card.kind)).length;
 const composer=<div className="as-composer"><label className="as-question"><span className="as-visually-hidden">{t('继续提问','Continue the conversation')}</span><textarea ref={composerInput} aria-label={t('向分析助手提问','Ask the analysis assistant')} maxLength={1000} disabled={locked||focusedEarlier} value={question} placeholder={t(queryOnly?'查询本项目工单、工程关系或分析资料…':'查询项目资料，或告诉我如何修改当前画布…',queryOnly?'Ask about project orders, graphs or evidence…':'Find project evidence or edit this canvas…')} onChange={event=>{setQuestion(event.target.value);setSummaries(null);}}/></label>
  <div className="as-compose-actions">{!queryOnly&&<select className="as-task" aria-label={t('助手任务','Assistant task')} value={taskId} disabled={locked} onChange={e=>{setTaskId(e.target.value as LlmTask);newConversation();}}>{(Object.keys(llmTaskNames) as LlmTask[]).map(id=><option value={id} key={id}>{llmTaskNames[id][en?1:0]}</option>)}</select>}<span className="as-compose-spacer"/>{active?<Btn disabled={busy||run?.state==='cancel_requested'} onClick={()=>void stop()}><Square size={14}/>{t('停止','Stop')}</Btn>:<Btn primary disabled={!!sendBlocker} aria-describedby={sendBlocker?sendStatusId:undefined} onClick={()=>void start()}><Send size={14}/>{t('发送','Send')}</Btn>}</div>
  {sendBlocker&&sendBlocker!=='ASSISTANT_QUESTION_REQUIRED'&&<p className="ap-caption" role="status" id={sendStatusId}>{assistantMessage(sendBlocker,en)}{canRefreshService&&<button type="button" disabled={locked} onClick={refreshService}>{t('刷新服务','Refresh service')}</button>}</p>}
  {sendBlocker==='ASSISTANT_QUESTION_REQUIRED'&&<span className="as-visually-hidden" id={sendStatusId}>{assistantMessage(sendBlocker,en)}</span>}
  <small>{t(snapshot?(queryOnly?'项目检索与问答 · 编辑可转后台执行':'项目检索与画布操作 · 修改可撤销'):'仅发送所选资料摘要 · 回答需核对原依据',snapshot?'Project tools · source and execution receipts retained':'Selected summaries only · verify answers against their sources')}</small></div>;
 return <div className="as-panel">{snapshot&&<div className="as-scope-heading"><span>{t('本项目 · 按需检索','This project · search on demand')}</span><span>{queryOnly?t('查询模式','Query only'):onApplyTask?t('后台编辑','Workbench editing'):t('只读画布','Read-only canvas')}</span></div>}<div className="as-toolbar"><button type="button" className="as-context-toggle" aria-expanded={contextOpen} onClick={()=>setContextOpen(v=>!v)}>{t(snapshot?'画布资料':'本次资料',snapshot?'Canvas materials':'Materials')} <b>{selected.length}</b>{!!metadataCount&&<small>{t(`${metadataCount}份仅元数据`,`${metadataCount} metadata only`)}</small>}<ChevronDown size={13}/></button><button type="button" aria-label={t('对话与服务','Conversations and service')} title={t('对话与服务','Conversations and service')} aria-expanded={historyOpen} onClick={()=>setHistoryOpen(v=>!v)}><History size={15}/></button><button type="button" disabled={locked} onClick={newConversation}><Plus size={14}/>{t('新对话','New')}</button></div>
  <div className="as-scroll" ref={scrollArea} onScroll={e=>{const el=e.currentTarget;autoScroll.current=el.scrollHeight-el.scrollTop-el.clientHeight<60;}}>
  {historyOpen&&<div className="as-history-tools"><div className="as-conversation"><label>{t('当前对话','Current conversation')}<select aria-label={t('当前对话','Current conversation')} disabled={locked} value={conversation?.conversationId??''} onChange={e=>e.target.value?void openConversation(e.target.value):newConversation()}><option value="">{t('新对话','New conversation')}</option>{conversations.map(item=><option key={item.conversationId} value={item.conversationId}>{item.title}</option>)}{conversation&&!conversations.some(c=>c.conversationId===conversation.conversationId)&&<option value={conversation.conversationId}>{conversation.title}</option>}</select></label></div><div className="as-service"><span>{effectiveService?.provider??'—'} · {effectiveService?.modelId||'—'}</span><Btn disabled={locked} onClick={refreshService}><RefreshCw size={13}/>{t('刷新服务','Refresh service')}</Btn></div></div>}
  {loadingHistory&&<p role="status">{t('读取已保存对话…','Loading saved conversation…')}</p>}
  {contextOpen&&<section className="as-sources">
  <div className="as-section-heading"><h4 id="as-materials-title">{t('本次资料','Selected materials')}</h4><span>{t('已选','Selected')} {selected.length} / {limit}</span></div>
  <p className="as-material-hint">{limit>6?t(`默认选取最多6份资料，可手动增加至${limit}份。`,`Up to 6 materials are selected automatically. You can select up to ${limit}.`):t(`每次最多选择${limit}份资料。`,`Select up to ${limit} materials per question.`)}</p>
  {!!metadataCount&&<p className="as-material-hint">{t(`${metadataCount}份图纸、照片或模型仅提供元数据，不包含原图或几何。`,`${metadataCount} drawing, photo or model sources contain metadata only, without images or geometry.`)}</p>}
  <div className="as-materials" role="group" aria-labelledby="as-materials-title">{available.length?available.map(card=>{
   const key=assistantEvidenceKey(card.source!.id,selected),disabled=active||busy||!key&&selected.length>=limit;
   return <label className="as-material-row" data-selected={!!key} data-disabled={disabled} key={card.id}><input type="checkbox" aria-label={card.title+(card.historical?' · '+t('历史参考','Historical reference'):'')} aria-describedby={'as-material-type-'+card.id} checked={!!key} disabled={disabled} onChange={event=>{setSelected(ids=>event.target.checked?[...ids,card.source!.id]:ids.filter(id=>id!==card.source!.id));setSummaries(null);}}/><span className="as-material-copy"><span className="as-material-meta" id={'as-material-type-'+card.id}>{key&&<span className="as-evidence-key">{key}</span>}<span>{sourceLabels[card.kind==='model3d'?'model':card.kind]?.[en?1:0]||t('资料','Material')}{card.historical?' · '+t('历史参考','Historical reference'):''}</span></span><strong>{card.title}</strong><small>{materialRoles[card.kind==='model3d'?'model':card.kind]?.[en?1:0]}</small></span></label>;
  }):<p>{t('可直接检索本项目，无需先向画布加入资料。','Search the project without first adding a card.')}</p>}</div>
  <Btn disabled={!receipt||!selected.length||busy||active} onClick={()=>void preview()}>{t('查看拟发送摘要','Preview outgoing summaries')}</Btn>
  {summaries&&<details open className="as-summaries"><summary>{t('摘要预览 · 未调用模型','Summary preview · no model call')}</summary>{summaries.map(row=><p key={row.key}><strong>{row.key} · {sourceLabels[row.kind]?.[en?1:0]}</strong><span>{row.summary}</span></p>)}<AssistantRetrieval sources={summaries} cards={cards} en={en} onFocus={onFocus}/></details>}
  <AssistantGraph service={service} cards={available} receipt={receipt} en={en} onFocus={onFocus}/>
  </section>}
  {!transcript.length&&!loadingHistory&&<div className="as-welcome"><strong>{t('从一个问题开始','Start with a question')}</strong><p>{t(snapshot?'可检索项目工单、资料和知识图谱；画布中的资料可作为补充依据。':'结合所选资料，整理已知情况、待验证假设、资料缺口和下一步核查。',snapshot?'Search project orders, documents and knowledge graphs; canvas materials provide additional context.':'Use selected evidence to organize facts and checks.')}</p><button type="button" disabled={locked} onClick={()=>{setQuestion(t('查找当前故障代码的历史工单，列出编号、版本和匹配依据。','Find historical orders for the current fault code, with identifiers, versions and match reasons.'));composerInput.current?.focus();}}>{t('查找相关历史工单','Find related work orders')}</button><button type="button" disabled={locked} onClick={()=>{setQuestion(t('现有资料能支持哪些信息链段？请列出未读取或待复核的连接。','Which parts of the information path are supported? List unread or unverified connections.'));composerInput.current?.focus();}}>{t('梳理信息链路与缺口','Review the information path and gaps')}</button></div>}
  <div className="as-transcript">{hasEarlier&&conversation&&<Btn disabled={locked} onClick={()=>void openConversation(conversation.conversationId,true)}>{t('载入更早对话','Load earlier turns')}</Btn>}{transcript.map(item=><div key={item.runId}><AssistantTurn onOpenSource={key=>{const reference=item.sources.find(s=>s.key===key);if(reference)setSourceView({runId:item.runId,reference});}} queryOnly={queryOnly} key={item.runId} run={item} cards={cards} en={en} canAddNote={!queryOnly&&!locked&&canAddNote} canCheck={!locked} onRetry={!locked&&!focusedEarlier?()=>retryQuestion(item):undefined} canTransfer={!locked&&canTransfer&&!snapshot?.workflowOrderId} onTransfer={queryOnly||item.result?.task?undefined:()=>setTransferRun(item)} onCheck={()=>void checkTurn(item)} onFocus={onFocus} onAddNote={text=>{try{onAddNote(text);}catch(e){setError(e);}}}/><AssistantTaskResult hasUnsaved={hasUnsaved} run={item} onHandoff={onHandoff?()=>onHandoff(item):undefined} en={en} locked={locked||executionPending} onExecute={!queryOnly&&onApplyTask?keys=>void executeTask(item,keys):undefined} onPage={index=>void taskPage(item,index)}/></div>)}</div>
  {sourceView&&<AssistantSourceViewer api={api} {...sourceView} en={en} onClose={()=>setSourceView(null)}/>}
  {!queryOnly&&transferRun&&<AssistantWorkOrderDialog key={`${context}:${transferRun.runId}`} api={api} run={transferRun} cards={cards} en={en} preferredOrderId={preferredOrderId} faultCode={faultCode} enabled={canTransfer&&!locked} onClose={()=>setTransferRun(null)} onOpenOrder={onOpenOrder} onFocus={onFocus}/>}
  {focusedEarlier&&<p className="ap-caption">{t('正在查看工单采纳的历史轮次。','Viewing the historical turn adopted by the work order.')}<Btn disabled={locked} onClick={()=>void openConversation(conversation!.conversationId)}>{t('打开完整对话后继续','Open full conversation to continue')}</Btn></p>}
  {executionPending&&<div role="status"><p>{t('草稿已应用，正在等待服务端执行回执；不会重复修改画布。','Draft applied; waiting for the server receipt. Changes will not be repeated.')}</p><Btn disabled={busy} onClick={()=>void acknowledgeExecution()}>{t('核对执行回执','Check execution receipt')}</Btn></div>}
  {pending&&busy&&<p role="status">{t('正在提交本轮问题…','Submitting this question…')}</p>}
  {pending&&!busy&&<div><p>{t('请求结果尚未确认，请先检查运行，避免重复调用。','The start result is uncertain. Check the run before sending again.')}</p><Btn onClick={()=>void inspectRun()}>{t('检查运行','Check run')}</Btn></div>}
  {!!error&&<div><p role="alert">{assistantMessage(error,en)}</p>{run&&!pending&&<><p className="ap-caption">{pollState==='retrying'?t('正在重试读取运行状态；不会重新调用模型。','Retrying the saved run status. The model will not be called again.'):t('可检查本次运行，读取已保存的回执。','Check this run to read its saved receipt.')}</p><Btn disabled={busy} onClick={()=>void inspectRun()}>{t('检查运行','Check run')}</Btn></>}</div>}
  </div>
  {!queryOnly&&snapshot?.workflowOrderId&&question.trim()&&onOpenOrder&&canTransfer&&
    <Btn disabled={locked||busy} onClick={()=>onOpenOrder(snapshot.workflowOrderId!,question.trim())}>
      {t('把输入填入工单记录','Use input as a work order record')}
    </Btn>}
  {composer}
 </div>;
}
