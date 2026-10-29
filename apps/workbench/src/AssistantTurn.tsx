import {Btn} from './Primitives';
import {answerNote,assistantMessage,type AssistantRun} from './assistantApi';
import type {CanvasCard} from './analysisCanvas';

export function AssistantTurn({run,cards,en,canAddNote,canCheck,onFocus,onAddNote,onCheck,onTransfer,canTransfer=false}:{run:AssistantRun;cards:CanvasCard[];en:boolean;canAddNote:boolean;canCheck:boolean;onFocus:(card:CanvasCard)=>void;onAddNote:(text:string)=>void;onCheck:()=>void;onTransfer?:()=>void;canTransfer?:boolean}){
 const t=(zh:string,english:string)=>en?english:zh;
 return <section className="as-turn" data-run-id={run.runId}>
  <article className="as-user-message"><b>{t('你','You')} · {t('第','Turn ')}{run.conversationVersion||1}{t('轮','')}</b><p>{run.question}</p></article>
  <article className="as-assistant-message"><b>{t('助手','Assistant')} · {t('第','Turn ')}{run.conversationVersion||1}{t('轮','')}</b>
   {run.error&&<p className="ap-caption">{assistantMessage(run.error,en)}</p>}
   {run.result&&['complete','partial'].includes(run.state)?<>{Object.entries({observations:t('观察','Observations'),hypotheses:t('待验证假设','Hypotheses'),gaps:t('缺口','Gaps'),nextSteps:t('下一步核验','Next checks')}).map(([key,name])=><div className="as-answer-group" key={key}><h4>{name}</h4>{run.result!.answer[key as keyof typeof run.result.answer].map((row,index)=><p key={index}>{row.text}<span>{row.refs.map(ref=>{const source=run.sources.find(s=>s.key===ref),card=cards.find(c=>c.source?.id===source?.evidenceRefId);return <button type="button" key={ref} title={card?ref+' · '+card.title:ref} disabled={!card} onClick={()=>card&&onFocus(card)}>{ref}</button>;})}</span></p>)}</div>)}
    {run.result.context&&<p className="ap-caption">{t('参与本轮的历史对话','History included')}: {run.result.context.includedTurns} {t('轮','turns')}{!!run.result.context.skippedTurns.length&&t('；资料范围或来源变化，部分旧轮次未参与。','; some earlier turns were excluded after material changes.')}</p>}
    <div className="ap-actions"><Btn disabled={!canAddNote} onClick={()=>onAddNote(answerNote(run))}>{t('加入本次分析笔记','Add to analysis note')}</Btn>{onTransfer&&<Btn disabled={!canTransfer} title={!canTransfer?t('当前分析只读、有未保存修改或正在处理','This analysis is read-only, unsaved or busy'):undefined} onClick={onTransfer}>{t('整理到工单','Organize into work order')}</Btn>}</div><p className="ap-caption">{t('笔记可撤销；工单仅加入你选择并编辑的待核验条目。','Notes can be undone. Only chosen, edited suggestions are appended to the order.')}</p><details><summary>{t('本轮用量','Turn usage')}</summary><p>{t('模型调用','Model calls')}: {run.result.modelCalls} · tokens {run.result.usage.total_tokens??'—'}</p></details>
   </>:<p className="ap-caption">{run.state==='changed'?run.error==='ASSISTANT_HISTORY_SCOPE_LIMIT'?t('本轮可单独回读，不会重新调用模型。','Read this turn separately without another model call.'):t('资料或策略变化，旧回答暂不展示；记录仍保留。','Sources or policy changed; this answer is hidden, and its receipt is retained.'):['reading','model','validating','cancel_requested'].includes(run.state)?t('本轮进行中…','This turn is running…'):t('本轮没有可用回答，前轮记录保留。','No usable answer in this turn; earlier turns remain.')}</p>}
   {run.state==='changed'&&<Btn disabled={!canCheck} onClick={onCheck}>{t('检查本轮','Check this turn')}</Btn>}
  </article>
 </section>;
}
