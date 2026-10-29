import {useEffect,useMemo,useRef,useState} from 'react';
import {RefreshCw,Send,Square} from 'lucide-react';
import {Btn} from './Primitives';
import {cancelled} from './api';
import type {DraftApi} from './AnalysisWorkspace';
import type {CanvasCard} from './analysisCanvas';
import type {DraftReceipt} from './analysisDraftState';
import {AssistantApi,ASSISTANT_ROOT,answerNote,assistantEvidenceKey,assistantMessage,running,sourceLabels,watchAssistantRun,type AssistantPolicyView,type AssistantRun,type AssistantSource} from './assistantApi';
import './assistant.css';

export function AssistantPanel({api,cards,receipt,en,canAddNote,onFocus,onAddNote}:{api:DraftApi&{assistantScope?:()=>DraftApi};cards:CanvasCard[];receipt:DraftReceipt|null;en:boolean;canAddNote:boolean;onFocus:(card:CanvasCard)=>void;onAddNote:(text:string)=>void}){
 const service=useMemo(()=>new AssistantApi(api),[api]);const t=(zh:string,english:string)=>en?english:zh;
 const available=cards.filter((card,index,all)=>card.source&&all.findIndex(v=>v.source?.id===card.source!.id)===index),inventory=available.map(card=>card.source!.id).join(':');
 const [view,setView]=useState<AssistantPolicyView|null>(null),[selected,setSelected]=useState<string[]>(()=>available.slice(0,8).map(c=>c.source!.id));
 const [question,setQuestion]=useState(''),[run,setRun]=useState<AssistantRun|null>(null),[error,setError]=useState<unknown>(null),[busy,setBusy]=useState(false),[reload,setReload]=useState(0),[summaries,setSummaries]=useState<AssistantSource[]|null>(null),[pending,setPending]=useState<string|null>(null);
 const [pollState,setPollState]=useState<'reading'|'retrying'|'paused'>('reading'),[pollReload,setPollReload]=useState(0);
 const latest=useRef<AssistantRun|null>(null);latest.current=run;
 const context=`${api.epoch}:${api.revision}:${receipt?.analysisSessionId}:${receipt?.analysisRevision}`;
 const current=useRef(context);current.current=context;
 const alive=useRef(true),scope=useRef<AssistantApi|null>(null);
 useEffect(()=>{alive.current=true;setRun(null);setError(null);setPending(null);setSummaries(null);
  const fixed=new AssistantApi(api.assistantScope?.()??api);scope.current=fixed;
  return()=>{alive.current=false;const previous=latest.current;if(running(previous))void fixed.cancel(previous!).catch(()=>{});};
 },[context]);
 useEffect(()=>{setSelected(previous=>previous.filter(id=>available.some(card=>card.source!.id===id)));setSummaries(null);},[inventory]);
 useEffect(()=>{const abort=new AbortController();setView(null);service.policy(abort.signal).then(value=>{if(!abort.signal.aborted){setView(value);setSelected(ids=>ids.slice(0,value.policy.reads));}}).catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setError(e);});return()=>abort.abort();},[service,context,reload]);
 useEffect(()=>{if(busy||!run||!running(run))return;const abort=new AbortController(),key=context;
  const stop=watchAssistantRun(service,run,abort.signal,value=>{if(current.current===key){setRun(value);setError(null);setPollState('reading');}},
   (e,retrying)=>{if(current.current===key){setError(e);setPollState(retrying?'retrying':'paused');}});
  return()=>{abort.abort();stop();};
 },[run?.runId,run?.state,context,reload,pollReload,busy]);
 const selection=()=>({analysisSessionId:receipt!.analysisSessionId,expectedAnalysisRevision:receipt!.analysisRevision,evidenceRefIds:selected});
 async function start(){if(!receipt||!view)return;const key=context,requestId=crypto.randomUUID(),fixed=scope.current!;setBusy(true);setError(null);setPending(requestId);setSummaries(null);
  try{const value=await api.request<AssistantRun>(ASSISTANT_ROOT+'/start',{...selection(),requestId,question:question.trim(),expectedPolicyRevision:view.revision,
    expectedAccessRevision:view.accessRevision,expectedServiceRevision:view.service.serviceRevision});
    if(!alive.current||current.current!==key){if(running(value))void fixed.cancel(value).catch(()=>{});return;}setRun(value);setPending(null);
  }catch(e){if(alive.current&&current.current===key){setError(e);if(e&&typeof e==='object'&&'status'in e)setPending(null);}}
  finally{if(alive.current&&current.current===key)setBusy(false);}
 }
 async function inspectRun(){if(!pending&&!run)return;const key=context;setBusy(true);setError(null);try{
  const value=pending?await api.request<AssistantRun>(ASSISTANT_ROOT+'/status',{requestId:pending}):await service.status(run!);
  if(alive.current&&current.current===key){setRun(value);setPending(null);setPollState('reading');setPollReload(v=>v+1);}
 }catch(e){if(alive.current&&current.current===key)setError(e);}finally{if(alive.current&&current.current===key)setBusy(false);}}
 async function stop(){if(!run)return;setBusy(true);setError(null);try{setRun(await service.cancel(run));}catch(e){setError(e);}finally{setBusy(false);}}
 async function preview(){if(!receipt)return;const key=context;setBusy(true);setError(null);try{const value=await api.request<{items:AssistantSource[]}>(ASSISTANT_ROOT+'/summary',selection());if(alive.current&&current.current===key)setSummaries(value.items);}catch(e){if(alive.current&&current.current===key)setError(e);}finally{if(alive.current&&current.current===key)setBusy(false);}}
 const names:Record<string,[string,string]>={reading:['读取所选资料','Reading selected materials'],model:['Qwen 整理中','Qwen is organizing evidence'],validating:['校验引用','Checking references'],complete:['引用校验完成','References checked'],partial:['部分资料缺失','Some sources are unavailable'],cancel_requested:['正在停止，等待后台确认','Stopping; waiting for server acknowledgement'],cancelled:['已取消','Cancelled'],interrupted:['运行已中断','Interrupted'],failed:['运行未完成','Incomplete'],changed:['来源或策略已变化','Sources or policy changed']};
 const active=running(run),limit=view?.policy.reads??8;
 return <div className="as-panel"><p className="ap-caption">{t('仅发送本次所选资料的脱敏摘要。结果是待核验的整理，不代表故障确诊。','Only redacted summaries of the selected materials are sent. Results require verification.')}</p>
  <div className="as-service"><span>Qwen · r{view?.revision??'—'}</span><Btn disabled={busy||active} onClick={()=>{setError(null);setReload(v=>v+1);}}><RefreshCw size={13}/>{t('刷新策略','Refresh policy')}</Btn></div>
  {view&&!view.policy.enabled&&<p className="ap-caption">{assistantMessage('ASSISTANT_POLICY_DISABLED',en)}</p>}{view&&!view.service.enabled&&<p className="ap-caption">{assistantMessage(view.service.reason||'ASSISTANT_SERVICE_UNAVAILABLE',en)}</p>}
  <div className="as-section-heading"><h4 id="as-materials-title">{t('本次资料','Selected materials')}</h4><span>{t('已选','Selected')} {selected.length} / {limit}</span></div>
  <p className="as-material-hint">{t('E 编号与本次回答中的资料引用对应。','E numbers match the material references in this answer.')}</p>
  <div className="as-materials" role="group" aria-labelledby="as-materials-title">{available.length?available.map(card=>{
   const key=assistantEvidenceKey(card.source!.id,selected),disabled=active||busy||!key&&selected.length>=limit;
   return <label className="as-material-row" data-selected={!!key} data-disabled={disabled} key={card.id}><input type="checkbox" aria-label={card.title+(card.historical?' · '+t('历史参考','Historical reference'):'')} aria-describedby={'as-material-type-'+card.id} checked={!!key} disabled={disabled} onChange={event=>{setSelected(ids=>event.target.checked?[...ids,card.source!.id]:ids.filter(id=>id!==card.source!.id));setSummaries(null);setRun(null);}}/><span className="as-material-copy"><span className="as-material-meta" id={'as-material-type-'+card.id}>{key&&<span className="as-evidence-key">{key}</span>}<span>{sourceLabels[card.kind==='model3d'?'model':card.kind]?.[en?1:0]||t('资料','Material')}{card.historical?' · '+t('历史参考','Historical reference'):''}</span></span><strong>{card.title}</strong></span></label>;
  }):<p>{t('加入一份固定资料后即可提问。','Add a fixed material to ask a question.')}</p>}</div>
  <Btn disabled={!receipt||!selected.length||busy||active} onClick={()=>void preview()}>{t('查看拟发送摘要','Preview outgoing summaries')}</Btn>
  {summaries&&<details open className="as-summaries"><summary>{t('摘要预览 · 未调用模型','Summary preview · no model call')}</summary>{summaries.map(row=><p key={row.key}><strong>{row.key} · {sourceLabels[row.kind]?.[en?1:0]}</strong><span>{row.summary}</span></p>)}</details>}
  <label className="as-question">{t('问题','Question')}<textarea aria-label={t('向分析助手提问','Ask the analysis assistant')} maxLength={1000} disabled={active||busy} value={question} placeholder={t('例如：对比当前报警、趋势和手册，列出支持依据与缺口。','Compare the alarm, trend and manual; list supporting evidence and gaps.')} onChange={event=>setQuestion(event.target.value)}/></label>
  <div className="ap-actions"><Btn primary disabled={busy||active||!receipt||!selected.length||!question.trim()||!view?.policy.enabled||!view.service.enabled||!view.service.canRun||!!pending} onClick={()=>void start()}><Send size={14}/>{t('发送','Send')}</Btn><Btn disabled={!active||busy||run?.state==='cancel_requested'} onClick={()=>void stop()}><Square size={14}/>{t('停止','Stop')}</Btn></div>
  {pending&&<div><p>{t('请求结果尚未确认，请先检查运行，避免重复调用。','The start result is uncertain. Check the run before sending again.')}</p><Btn disabled={busy} onClick={()=>void inspectRun()}>{t('检查运行','Check run')}</Btn></div>}
  {!!error&&<div><p role="alert">{assistantMessage(error,en)}</p>{run&&!pending&&<><p className="ap-caption">{pollState==='retrying'?t('正在重试读取运行状态；不会重新调用模型。','Retrying the saved run status. The model will not be called again.'):t('可检查本次运行，读取已保存的回执。','Check this run to read its saved receipt.')}</p><Btn disabled={busy} onClick={()=>void inspectRun()}>{t('检查运行','Check run')}</Btn></>}</div>}
  {run&&<section className="as-run"><p role="status">{names[run.state]?.[en?1:0]||run.state}{run.progress.length?' · '+run.progress.length+'/'+selected.length:''}</p>{run.error&&<p>{assistantMessage(run.error,en)}</p>}
   {run.result&&['complete','partial'].includes(run.state)&&<>{Object.entries({observations:t('观察','Observations'),hypotheses:t('待验证假设','Hypotheses'),gaps:t('缺口','Gaps'),nextSteps:t('下一步核验','Next checks')}).map(([key,name])=><div className="as-answer-group" key={key}><h4>{name}</h4>{run.result!.answer[key as keyof typeof run.result.answer].map((row,index)=><p key={index}>{row.text}<span>{row.refs.map(ref=>{const source=run.sources.find(s=>s.key===ref),card=cards.find(c=>c.source?.id===source?.evidenceRefId);return <button type="button" key={ref} title={card?ref+' · '+card.title:ref} disabled={!card} onClick={()=>card&&onFocus(card)}>{ref}</button>;})}</span></p>)}</div>)}
    <Btn disabled={busy||!canAddNote||current.current!==context} onClick={()=>{try{onAddNote(answerNote(run));}catch(e){setError(e);}}}>{t('加入本次分析笔记','Add to analysis note')}</Btn><p className="ap-caption">{t('笔记可撤销，仍通过原保存入口保存。','Notes can be undone and are saved through the existing Save action.')}</p><details><summary>{t('本次用量','Usage')}</summary><p>{t('模型调用','Model calls')}：{run.result.modelCalls} · tokens {run.result.usage.total_tokens??'—'}</p></details></>}
  </section>}
 </div>;
}
