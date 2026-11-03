import {useEffect,useId,useMemo,useRef,useState} from 'react';
import {Plus,RefreshCw,Send,Square,ChevronDown,History} from 'lucide-react';
import {AssistantRetrieval} from './AssistantRetrieval';
import type {SourceAnchor} from './analysisSources';
import {Btn} from './Primitives';
import {cancelled} from './api';
import type {DraftApi} from './AnalysisWorkspace';
import type {CanvasCard} from './analysisCanvas';
import type {DraftReceipt} from './analysisDraftState';
import {defaultAssistantEvidence,AssistantApi,ASSISTANT_ROOT,mergeConversationTurns,assistantEvidenceKey,assistantMessage,assistantSendBlocker,running,sourceLabels,materialRoles,watchAssistantRun,type AssistantConversation,type AssistantPolicyView,type AssistantRun,type AssistantSource} from './assistantApi';
import {AssistantGraph} from './AssistantGraph';
import {AssistantTurn} from './AssistantTurn';
import {AssistantWorkOrderDialog} from './AssistantWorkOrderDialog';
import './assistant.css';
import {llmTaskNames,type LlmTask} from './llmSettings';

export function AssistantPanel({api,cards,receipt,en,canAddNote,onFocus,onAddNote,canTransfer=false,preferredOrderId,faultCode,onOpenOrder,initialRunId,queryOnly=false}:{api:DraftApi&{assistantScope?:()=>DraftApi};cards:CanvasCard[];receipt:DraftReceipt|null;en:boolean;canAddNote:boolean;onFocus:(card:CanvasCard,anchor?:SourceAnchor|null)=>void;onAddNote:(text:string)=>void;canTransfer?:boolean;preferredOrderId?:string;faultCode?:string;onOpenOrder?:(id:string)=>void;initialRunId?:string;queryOnly?:boolean}){
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
 const historyGeneration=useRef(0);
 const latest=useRef<AssistantRun|null>(null);latest.current=run;
 const context=`${api.epoch}:${api.revision}:${receipt?.analysisSessionId}:${receipt?.analysisRevision}`;
 const current=useRef(context);current.current=context;
 const alive=useRef(true),scope=useRef<AssistantApi|null>(null);
 useEffect(()=>{alive.current=true;setRun(null);setError(null);setPending(null);setSummaries(null);setConversation(null);setConversations([]);setTurns([]);setHasEarlier(false);setLoadingHistory(false);setTransferRun(null);historyGeneration.current++;setQuestion('');
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
   if(!value.items.length)return;const detail=await service.conversation(value.items[0].conversationId,undefined,abort.signal);
   if(abort.signal.aborted||current.current!==key||historyGeneration.current!==generation)return;
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
 async function start(){if(!receipt||!view||sendBlocker)return;autoScroll.current=true;const key=context,requestId=crypto.randomUUID(),fixed=scope.current!;historyGeneration.current++;setTurns(previous=>mergeConversationTurns(previous,run));setBusy(true);setError(null);setPending(requestId);setSummaries(null);
  try{const value=await api.request<AssistantRun>(ASSISTANT_ROOT+'/start',{...selection(),requestId,question:question.trim(),conversationId:conversation?.conversationId??null,expectedConversationVersion:conversation?.version??0,parentRunId:conversation?.headRunId??null,expectedPolicyRevision:view.revision,
    expectedAccessRevision:view.accessRevision,expectedServiceRevision:effectiveService?.serviceRevision,taskId});
    if(!alive.current||current.current!==key){if(running(value))void fixed.cancel(value).catch(()=>{});return;}setRun(value);setPending(null);setQuestion('');if(value.conversationId){const head={conversationId:value.conversationId,title:conversation?.title||value.question||'分析',version:value.conversationVersion||1,headRunId:value.runId,analysisSessionId:value.analysisSessionId,analysisRevision:value.analysisRevision,updatedAt:new Date().toISOString()};setConversation(head);setConversations(items=>[head,...items.filter(v=>v.conversationId!==head.conversationId)].slice(0,20));}
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
 const active=running(run),locked=busy||running(run)||loadingHistory||!!pending;
 const effectiveService=view?.services?.[taskId]??view?.service;
 const limit=Math.min(view?.policy.reads??8,effectiveService?.settings?.readLimit??8);
 const taskMismatch=!!conversation&&!!run&&(run.taskId??'analysis')!==taskId;
 const sendBlocker=assistantSendBlocker({busy,active,pending:!!pending,loadingHistory,focusedEarlier,taskMismatch,hasReceipt:!!receipt,view,policyError,service:effectiveService,selectedCount:selected.length,question});
 const refreshService=()=>{setError(null);setReload(v=>v+1);};
 const canRefreshService=sendBlocker==='ASSISTANT_POLICY_READ_FAILED'||!!view&&view.policy.enabled&&!effectiveService?.enabled;
 const retryQuestion=(item:AssistantRun)=>{setQuestion(item.question??'');setSummaries(null);composerInput.current?.focus();};
 const metadataCount=available.filter(card=>selected.includes(card.source!.id)&&['drawing','photo','model3d'].includes(card.kind)).length;
 const composer=<div className="as-composer"><label className="as-question"><span className="as-visually-hidden">{t('继续提问','Continue the conversation')}</span><textarea ref={composerInput} aria-label={t('向分析助手提问','Ask the analysis assistant')} maxLength={1000} disabled={locked||focusedEarlier} value={question} placeholder={t('围绕当前资料提问…','Ask about these materials…')} onChange={event=>{setQuestion(event.target.value);setSummaries(null);}}/></label>
  <div className="as-compose-actions">{!queryOnly&&<select className="as-task" aria-label={t('助手任务','Assistant task')} value={taskId} disabled={locked} onChange={e=>{setTaskId(e.target.value as LlmTask);newConversation();}}>{(Object.keys(llmTaskNames) as LlmTask[]).map(id=><option value={id} key={id}>{llmTaskNames[id][en?1:0]}</option>)}</select>}<span className="as-compose-spacer"/>{active?<Btn disabled={busy||run?.state==='cancel_requested'} onClick={()=>void stop()}><Square size={14}/>{t('停止','Stop')}</Btn>:<Btn primary disabled={!!sendBlocker} aria-describedby={sendBlocker?sendStatusId:undefined} onClick={()=>void start()}><Send size={14}/>{t('发送','Send')}</Btn>}</div>
  {sendBlocker&&sendBlocker!=='ASSISTANT_QUESTION_REQUIRED'&&<p className="ap-caption" role="status" id={sendStatusId}>{assistantMessage(sendBlocker,en)}{canRefreshService&&<button type="button" disabled={locked} onClick={refreshService}>{t('刷新服务','Refresh service')}</button>}</p>}
  {sendBlocker==='ASSISTANT_QUESTION_REQUIRED'&&<span className="as-visually-hidden" id={sendStatusId}>{assistantMessage(sendBlocker,en)}</span>}
  <small>{t('仅发送所选资料摘要 · 回答需核对原依据','Selected summaries only · verify answers against their sources')}</small></div>;
 return <div className="as-panel"><div className="as-toolbar"><button type="button" className="as-context-toggle" aria-expanded={contextOpen} onClick={()=>setContextOpen(v=>!v)}>{t('本次资料','Materials')} <b>{selected.length}</b>{!!metadataCount&&<small>{t(`${metadataCount}份仅元数据`,`${metadataCount} metadata only`)}</small>}<ChevronDown size={13}/></button><button type="button" aria-label={t('对话与服务','Conversations and service')} title={t('对话与服务','Conversations and service')} aria-expanded={historyOpen} onClick={()=>setHistoryOpen(v=>!v)}><History size={15}/></button><button type="button" disabled={locked} onClick={newConversation}><Plus size={14}/>{t('新对话','New')}</button></div>
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
  }):<p>{t('加入一份固定资料后即可提问。','Add a fixed material to ask a question.')}</p>}</div>
  <Btn disabled={!receipt||!selected.length||busy||active} onClick={()=>void preview()}>{t('查看拟发送摘要','Preview outgoing summaries')}</Btn>
  {summaries&&<details open className="as-summaries"><summary>{t('摘要预览 · 未调用模型','Summary preview · no model call')}</summary>{summaries.map(row=><p key={row.key}><strong>{row.key} · {sourceLabels[row.kind]?.[en?1:0]}</strong><span>{row.summary}</span></p>)}<AssistantRetrieval sources={summaries} cards={cards} en={en} onFocus={onFocus}/></details>}
  <AssistantGraph service={service} cards={available} receipt={receipt} en={en} onFocus={onFocus}/>
  </section>}
  {!transcript.length&&!loadingHistory&&<div className="as-welcome"><strong>{t('从一个问题开始','Start with a question')}</strong><p>{t('结合所选资料，整理已知情况、待验证假设、资料缺口和下一步核查。','Use the selected evidence to organize facts, hypotheses, gaps and next checks.')}</p><button type="button" disabled={locked} onClick={()=>{setQuestion(t('对比当前报警、趋势和手册，哪些依据一致，哪些仍需核对？','Compare the alarm, trend and manual. What agrees and what still needs checking?'));composerInput.current?.focus();}}>{t('对比报警与资料','Compare the alarm and evidence')}</button><button type="button" disabled={locked} onClick={()=>{setQuestion(t('现有资料能支持哪些信息链段？请列出未读取或待复核的连接。','Which parts of the information path are supported? List unread or unverified connections.'));composerInput.current?.focus();}}>{t('梳理信息链路与缺口','Review the information path and gaps')}</button></div>}
  <div className="as-transcript">{hasEarlier&&conversation&&<Btn disabled={locked} onClick={()=>void openConversation(conversation.conversationId,true)}>{t('载入更早对话','Load earlier turns')}</Btn>}{transcript.map(item=><AssistantTurn queryOnly={queryOnly} key={item.runId} run={item} cards={cards} en={en} canAddNote={!queryOnly&&!locked&&canAddNote} canCheck={!locked} onRetry={!locked&&!focusedEarlier?()=>retryQuestion(item):undefined} canTransfer={!locked&&canTransfer} onTransfer={queryOnly?undefined:()=>setTransferRun(item)} onCheck={()=>void checkTurn(item)} onFocus={onFocus} onAddNote={text=>{try{onAddNote(text);}catch(e){setError(e);}}}/>)}</div>
  {!queryOnly&&transferRun&&<AssistantWorkOrderDialog key={`${context}:${transferRun.runId}`} api={api} run={transferRun} cards={cards} en={en} preferredOrderId={preferredOrderId} faultCode={faultCode} enabled={canTransfer&&!locked} onClose={()=>setTransferRun(null)} onOpenOrder={onOpenOrder} onFocus={onFocus}/>}
  {focusedEarlier&&<p className="ap-caption">{t('正在查看工单采纳的历史轮次。','Viewing the historical turn adopted by the work order.')}<Btn disabled={locked} onClick={()=>void openConversation(conversation!.conversationId)}>{t('打开完整对话后继续','Open full conversation to continue')}</Btn></p>}
  {pending&&busy&&<p role="status">{t('正在提交本轮问题…','Submitting this question…')}</p>}
  {pending&&!busy&&<div><p>{t('请求结果尚未确认，请先检查运行，避免重复调用。','The start result is uncertain. Check the run before sending again.')}</p><Btn onClick={()=>void inspectRun()}>{t('检查运行','Check run')}</Btn></div>}
  {!!error&&<div><p role="alert">{assistantMessage(error,en)}</p>{run&&!pending&&<><p className="ap-caption">{pollState==='retrying'?t('正在重试读取运行状态；不会重新调用模型。','Retrying the saved run status. The model will not be called again.'):t('可检查本次运行，读取已保存的回执。','Check this run to read its saved receipt.')}</p><Btn disabled={busy} onClick={()=>void inspectRun()}>{t('检查运行','Check run')}</Btn></>}</div>}
  </div>
  {composer}
 </div>;
}
