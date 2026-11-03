import {AssistantRetrieval} from './AssistantRetrieval';
import type {SourceAnchor} from './analysisSources';
import {Btn} from './Primitives';
import {answerNote,assistantMessage,assistantRunPhase,assistantSourceAnchor,type AssistantRun} from './assistantApi';
import type {CanvasCard} from './analysisCanvas';

export function AssistantTurn({run,cards,en,canAddNote,canCheck,onFocus,onAddNote,onCheck,onTransfer,onRetry,canTransfer=false,queryOnly=false}:{run:AssistantRun;cards:CanvasCard[];en:boolean;canAddNote:boolean;canCheck:boolean;onFocus:(card:CanvasCard,anchor?:SourceAnchor|null)=>void;onAddNote:(text:string)=>void;onCheck:()=>void;onTransfer?:()=>void;onRetry?:()=>void;canTransfer?:boolean;queryOnly?:boolean}){
 const t=(zh:string,english:string)=>en?english:zh;
 const complete=!!run.result&&['complete','partial'].includes(run.state),phase=assistantRunPhase(run);
 const active=['reading','model','validating','cancel_requested'].includes(run.state);
 const read=run.sources.filter(source=>source.availability==='available').length;
 const phaseIndex=['reading','model','validating','complete'].indexOf(phase??'');
 return <section className="as-turn" data-run-id={run.runId}>
  <article className="as-user-message"><b>{t('你','You')} · {t('第','Turn ')}{run.conversationVersion||1}{t('轮','')}</b><p>{run.question}</p></article>
  <article className="as-assistant-message"><div className="as-answer-heading"><b>{t('助手','Assistant')}</b><small>{complete?t('引用已核对','References checked'):active?t('正在处理','In progress'):t('本轮未完成','Turn incomplete')}</small></div>
   {active&&<ol className="as-progress" aria-label={t('本轮处理步骤','Turn progress')}>{['读取资料','分析整理','校验引用'].map((title,index)=><li key={title} data-state={index<phaseIndex?'done':index===phaseIndex?'active':'pending'} aria-current={index===phaseIndex?'step':undefined}>{en?['Read sources','Analyze','Check references'][index]:title}</li>)}</ol>}
   {run.state==='cancel_requested'&&<p role="status">{t('正在停止，等待后台确认。','Stopping; waiting for acknowledgement.')}</p>}
   {complete?<>{Object.entries({observations:t('已知情况','Known information'),hypotheses:t('待验证假设','Hypotheses to check'),gaps:t('资料缺口','Evidence gaps'),nextSteps:t('建议核查','Suggested checks')}).filter(([key])=>run.result!.answer[key as 'observations'|'hypotheses'|'gaps'|'nextSteps'].length).map(([key,name])=><div className="as-answer-group" key={key}><h4>{name}</h4>{run.result!.answer[key as 'observations'|'hypotheses'|'gaps'|'nextSteps'].map((row,index)=><p key={index}>{row.text}<span>{row.refs.map(ref=>{const source=run.sources.find(s=>s.key===ref),card=cards.find(c=>c.source?.id===source?.evidenceRefId);return <button type="button" key={ref} title={card?ref+' · '+card.title:ref} disabled={!card} onClick={()=>card&&onFocus(card,source?assistantSourceAnchor(source):null)}>{ref}</button>;})}</span></p>)}</div>)}</>:!active&&<div className="as-failure" role="status"><p>{run.error?assistantMessage(run.error,en):t('本轮没有生成回答，已有资料与对话保留。','No answer was produced. Materials and earlier turns remain.')}</p>{onRetry&&['failed','interrupted','cancelled'].includes(run.state)&&<Btn onClick={onRetry}>{t('修改后重试','Edit and retry')}</Btn>}{run.state==='changed'&&<Btn disabled={!canCheck} onClick={onCheck}>{t('检查本轮','Check this turn')}</Btn>}</div>}
   {!!run.sources.length&&<details className="as-turn-details"><summary>{t('依据与过程','Sources and process')} · {read}/{run.sources.length}</summary>
    <p className="ap-caption">{t('按固定引用读取 → 结合问题整理 → 校验格式与引用。引用可读不代表结论已获确认。','Read fixed sources → organize for this question → validate format and references. Readable citations do not confirm conclusions.')}</p>
    {run.sources.some(source=>source.availability!=='available')&&<p className="ap-caption">{t('部分资料未读到，回答只能使用可读部分。','Some sources were unavailable; only readable sources can support the answer.')}</p>}
    <AssistantRetrieval sources={run.sources} cards={cards} en={en} onFocus={onFocus}/>
    {run.result?.context&&<p className="ap-caption">{t('采用历史','History included')}: {run.result.context.includedTurns} {t('轮','turns')}{!!run.result.context.skippedTurns.length&&t('；部分旧轮次不再适用。','; some previous turns no longer apply.')}</p>}
    {run.result&&<p className="ap-caption">{run.result.model?.modelId} · {t('模型调用','Model calls')} {run.result.modelCalls} · tokens {run.result.usage.total_tokens??'—'}</p>}
   </details>}
   {complete&&!queryOnly&&<details className="as-turn-actions"><summary>{t('使用这份回答','Use this answer')}</summary><div className="ap-actions"><Btn disabled={!canAddNote} onClick={()=>onAddNote(answerNote(run))}>{t('加入本次分析笔记','Add to analysis note')}</Btn>{onTransfer&&<Btn disabled={!canTransfer} title={!canTransfer?t('当前分析只读、有未保存修改或正在处理','This analysis is read-only, unsaved or busy'):undefined} onClick={onTransfer}>{t('整理到工单','Organize into work order')}</Btn>}</div><p className="ap-caption">{t('仅加入你确认的待核验条目，不自动确认结论。','Only chosen suggestions are added; conclusions are not automatically confirmed.')}</p></details>}
  </article>
 </section>;
}
