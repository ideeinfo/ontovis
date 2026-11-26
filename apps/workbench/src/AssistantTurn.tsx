import {displayText} from './displayText';
import {AssistantRetrieval} from './AssistantRetrieval';
import type {SourceAnchor} from './analysisSources';
import {Btn} from './Primitives';
import {answerNote,assistantMessage,assistantSourceAnchor,running,type AssistantRun} from './assistantApi';
import type {CanvasCard} from './analysisCanvas';
import {useState,type ReactNode} from 'react';
import {assistantEditReview} from './assistantTasks';

export function AssistantTurn({run,cards,en,canAddNote,canCheck,onFocus,onAddNote,onCheck,onTransfer,onRetry,onContinueEdit,cardPicker,canTransfer=false,queryOnly=false,onOpenSource}:{
 run:AssistantRun;cards:CanvasCard[];en:boolean;canAddNote:boolean;canCheck:boolean;
 onFocus:(card:CanvasCard,anchor?:SourceAnchor|null)=>void;onAddNote:(text:string)=>void;onCheck:()=>void;
 onTransfer?:()=>void;onRetry?:()=>void;onContinueEdit?:()=>void;cardPicker?:ReactNode;
 canTransfer?:boolean;queryOnly?:boolean;onOpenSource?:(key:string)=>void;
}){
 const t=(zh:string,english:string)=>en?english:zh;
 const [expandedEvidence,setExpandedEvidence]=useState('');
 const complete=!!run.result&&['complete','partial'].includes(run.state);
 const execution=run.result?.task?.receipts.at(-1),existingOnly=!!execution?.items.length&&execution.items.every(item=>item.status==='already_present');
 const disposition=!!run.result?.task?.disposition;
 const active=running(run);
 const read=run.sources.filter(source=>source.availability==='available').length;
 const selectedReads=run.result?.task?.selectedReads??[];
 const readSelected=selectedReads.filter(item=>item.state==='complete').length;
 const answer=run.result?.answer;
 const review=assistantEditReview(run.result?.task,answer?.gaps);
 const reviewTitle={card:t('选择要操作的卡片','Choose cards to edit'),group:t('指定要修改的分组','Identify the group to edit'),
  relation:t('指定要修改的连线','Identify the connection to edit'),result:t('选择要加入的资料','Choose materials to add'),
  instruction:t('补充要做的修改','Describe the edit')};
 const reviewText={card:'Select the cards to edit, then continue with the original instruction.',
  group:'Enter the name of the group to change.',relation:'Enter the names of the cards at both ends of the connection.',
  result:'Choose from the results below or enter a material name or equipment tag.',instruction:'Describe the specific change to make.'};
 const groups=answer?[
  {title:t('已知情况','Known information'),rows:answer.observations},
  {title:t('待验证假设','Hypotheses to check'),rows:answer.hypotheses},
  {title:t('还需补充的依据','Evidence still needed'),rows:answer.gaps.filter(row=>!review?.legacyGap||row.refs.length||row.text!==review.legacyGap)},
  {title:disposition?t('处置建议','Response plan'):t('建议核查','Suggested checks'),rows:answer.nextSteps},
 ].filter(group=>group.rows.length):[];
 const onlyReview=!!review&&!groups.length;
 return <section className="as-turn" data-run-id={run.runId}>
  <article className="as-user-message"><b>{t('你','You')} · {t('第','Turn ')}{run.conversationVersion||1}{t('轮','')}</b><p>{displayText(run.question)}</p></article>
  <article className="as-assistant-message"><div className="as-answer-heading"><b>{t('助手','Assistant')}</b>
   <small>{complete?review?t('待补充操作信息','Edit needs clarification'):execution?t('操作已回执','Execution recorded'):t('引用已核对','References checked'):active?t('正在处理','In progress'):t('本轮未完成','Turn incomplete')}</small></div>
   {complete?<>{review&&<section className="as-edit-review">
    <h4>{reviewTitle[review.target]}</h4>
    {(review.message||!cardPicker)&&<p>{displayText(en?reviewText[review.target]:review.message||'请在画布上选择需要修改的卡片。')}</p>}
    {cardPicker}
    {onContinueEdit&&<Btn onClick={onContinueEdit}>{t('继续原指令','Continue with original instruction')}</Btn>}
   </section>}
   {execution&&<div className="as-run-outcome" role="status"><strong>{execution.state==='saved'?t(`本轮操作已保存 · r${execution.analysisRevision}`,`Saved · r${execution.analysisRevision}`):existingOnly?t('资料已在画布中，未重复添加','Already on the canvas; no duplicate added'):t('本轮画布操作已应用到草稿','Canvas actions applied to draft')}</strong><small>{disposition?t('处置分析见下方。','See the response analysis below.'):t('以下保留执行前的检索回答，实际操作以回执和当前画布状态为准。','The search answer below predates execution. Check the receipt and current canvas for the outcome.')}</small></div>}
   {!!groups.length&&<details className={execution&&!disposition?'as-executed-answer':'as-live-answer'} open={!execution||disposition}>
    <summary>{disposition?t('查看处置分析','View response analysis'):t('查看检索时回答（执行前）','Read the pre-execution answer')}</summary>
    {groups.map(({title,rows})=><div className="as-answer-group" key={title}><h4>{title}</h4>{rows.map((row,index)=><p key={index}>{displayText(row.text)}<span>{row.refs.map(ref=>{
     const source=run.sources.find(s=>s.key===ref),card=cards.find(c=>c.source?.id===source?.evidenceRefId);
     return <button type="button" key={ref} title={displayText(card?ref+' · '+card.title:ref)} disabled={!card&&!run.result?.task} onClick={()=>card?onFocus(card,source?assistantSourceAnchor(source):null):source?.descriptor&&['document','drawing'].includes(source.kind)&&onOpenSource?onOpenSource(ref):setExpandedEvidence(ref)}>{ref}</button>;
    })}</span></p>)}</div>)}
   </details>}</>:!active&&<div className="as-failure" role="status"><p>{run.error?assistantMessage(run.error,en):t('本轮没有生成回答，已有资料与对话保留。','No answer was produced. Materials and earlier turns remain.')}</p>{onRetry&&['failed','interrupted','cancelled'].includes(run.state)&&<Btn onClick={onRetry}>{t('修改后重试','Edit and retry')}</Btn>}{run.state==='changed'&&<Btn disabled={!canCheck} onClick={onCheck}>{t('检查本轮','Check this turn')}</Btn>}</div>}
   {!onlyReview&&!!selectedReads.length&&<details className="as-turn-details">
    <summary>{t('分析用资料已读','Analysis materials read')} · {readSelected}/{selectedReads.length}</summary>
    <ul className="as-selected-read-list">{selectedReads.map((item,index)=>{
     const label=cards.find(card=>card.source?.id===item.evidenceRefId)?.title??t('资料','Material')+' '+(index+1);
     const status=item.state==='complete'?(item.metadataOnly?t('仅元数据','Metadata only'):t('已读摘要','Summary read'))+' · '+item.sourceKey
       :item.state==='budget_limited'?t('当时读取次数达上限 · 未读取','Previous read count reached · unread')
       :item.state==='policy_excluded'?t('项目策略未允许读取','Excluded by project policy'):assistantMessage(item.reason,en);
     return <li key={item.evidenceRefId}><span>{displayText(label)}</span><small>{displayText(status)}</small></li>;
    })}</ul>
   </details>}
   {!onlyReview&&!!run.sources.length&&<details className="as-turn-details" open={!!expandedEvidence||undefined}><summary>{t('依据与过程','Sources and process')} · {read}/{run.sources.length}</summary>
    <p className="ap-caption">{t('按固定引用读取 → 结合问题整理 → 校验格式与引用。引用可读不代表结论已获确认。','Read fixed sources → organize for this question → validate format and references. Readable citations do not confirm conclusions.')}</p>
    {run.sources.some(source=>source.availability!=='available')&&<p className="ap-caption">{t('部分资料未读到，回答只能使用可读部分。','Some sources were unavailable; only readable sources can support the answer.')}</p>}
    {run.result?.task&&run.sources.map(source=><details className="as-read-source" key={source.key} open={expandedEvidence===source.key} onToggle={e=>{if(e.currentTarget.open)setExpandedEvidence(source.key);else if(expandedEvidence===source.key)setExpandedEvidence('');}}><summary>{source.key} · {source.kind==='work_order'?t('工单目录与固定记录','Work order catalogue and records'):source.kind==='document'?t('已读取文档知识','Read document knowledge'):t('已读取资料','Read material')}</summary><p>{t('这是本次回答使用的摘要，标明资料版本和测试来源。工程事实仍待核实。','This summary was used in the answer. It identifies source versions and test data. Engineering facts need verification.')}</p>{source.descriptor&&['document','drawing'].includes(source.kind)&&onOpenSource&&<Btn onClick={()=>onOpenSource(source.key)}>{t('查看固定版本原文','Read fixed source')}{source.pageNumbers?.length?' · '+source.pageNumbers.map(p=>'p'+p).join('、'):''}</Btn>}<pre>{displayText(source.summary)}</pre></details>)}
    <AssistantRetrieval sources={run.sources} cards={cards} en={en} onFocus={onFocus}/>
    {run.result?.context&&<p className="ap-caption">{t('采用历史','History included')}: {run.result.context.includedTurns} {t('轮','turns')}{!!run.result.context.skippedTurns.length&&t('；部分旧轮次不再适用。','; some previous turns no longer apply.')}</p>}
    {run.result&&<p className="ap-caption">{displayText(run.result.model?.modelId)} · {t('模型调用','Model calls')} {run.result.modelCalls} · tokens {run.result.usage.total_tokens??'—'}</p>}
   </details>}
   {complete&&!onlyReview&&!queryOnly&&<details className="as-turn-actions"><summary>{t('使用这份回答','Use this answer')}</summary><div className="ap-actions"><Btn disabled={!canAddNote} onClick={()=>onAddNote(answerNote(run))}>{t('加入本次分析笔记','Add to analysis note')}</Btn>{onTransfer&&<Btn disabled={!canTransfer} title={!canTransfer?t('当前分析只读、有未保存修改或正在处理','This analysis is read-only, unsaved or busy'):undefined} onClick={onTransfer}>{t('整理到工单','Organize into work order')}</Btn>}</div><p className="ap-caption">{t('仅加入你确认的待核验条目，不自动确认结论。','Only chosen suggestions are added; conclusions are not automatically confirmed.')}</p></details>}
  </article>
 </section>;
}
