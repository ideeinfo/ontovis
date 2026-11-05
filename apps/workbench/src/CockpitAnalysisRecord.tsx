import {useEffect,useId,useRef,useState,type RefObject} from 'react';
import {ArrowUpRight,CheckCheck,ClipboardList,FileText,MessageSquare,TriangleAlert} from 'lucide-react';
import {Btn,Modal} from './Primitives';
import type {AssistantRun} from './assistantApi';
import type {CockpitAnalysisDetail} from './cockpitAnalysisState';

export type CockpitRecordGroup={id:string;title:string;rows:{text:string;refs:string[]}[]};
export type CockpitRecordReference={title:string;available:boolean};
type Props={detail:CockpitAnalysisDetail;reason?:string;run?:AssistantRun;groups:CockpitRecordGroup[];
 references:Record<string,CockpitRecordReference>;en:boolean;onReference:(key:string)=>void;onAsk:()=>void;onEdit:()=>void};

export function cockpitRecordWindow(context:CockpitAnalysisDetail['snapshot']['context'],en:boolean){
 try{
  const format=new Intl.DateTimeFormat(en?'en-GB':'zh-CN',{dateStyle:'medium',timeStyle:'short',timeZone:context.timezone});
  return `${format.format(new Date(context.timeFrom))} — ${format.format(new Date(context.timeTo))}`;
 }catch{return `${context.timeFrom} — ${context.timeTo}`;}
}

export function CockpitAnalysisRecord({open,onClose,...props}:Props&{open:boolean;onClose:()=>void}){
 const [section,setSection]=useState(-1),reader=useRef<HTMLElement>(null),id=useId();
 useEffect(()=>setSection(-1),[props.detail.analysisSessionId,props.detail.analysisRevision,props.run?.runId]);
 function select(index:number){setSection(index);if(index<0)reader.current?.scrollTo({top:0,behavior:'smooth'});else reader.current?.querySelector<HTMLElement>(`[data-record-section="${index}"]`)?.scrollIntoView({block:'start',behavior:'smooth'});}
 if(!open)return null;
 return <Modal className="pa-record-dialog" title={props.en?'Analysis record':'分析记录'} description={props.detail.snapshot.title+' · r'+props.detail.analysisRevision} onClose={onClose}>
  <CockpitAnalysisRecordContent {...props} id={id} readerRef={reader} activeSection={section} onSection={select} onReference={key=>props.onReference(key)}/>
 </Modal>;
}

export function CockpitAnalysisRecordContent({detail,reason,run,groups,references,en,onReference,onAsk,onEdit,id='analysis-record',readerRef,activeSection=-1,onSection=()=>{}}:Props&{
 id?:string;readerRef?:RefObject<HTMLElement|null>;activeSection?:number;onSection?:(index:number)=>void}){
 const t=(zh:string,english:string)=>en?english:zh;
 const confirmed=!!run?.result&&['complete','partial'].includes(run.state);
 const icons={observations:CheckCheck,hypotheses:TriangleAlert,gaps:FileText,nextSteps:ClipboardList};
 useEffect(()=>{if(activeSection>=0)readerRef?.current?.querySelector<HTMLElement>(`[data-record-section="${activeSection}"]`)?.scrollIntoView({block:'start'});},[readerRef]);
 return <div className="pa-record-reading">
  <div className="pa-record-meta"><strong>{detail.snapshot.title}</strong><span>r{detail.analysisRevision}</span><small>{confirmed?t('已保存回答 · 待人工核验','Saved answer · review required'):t('已保存分析笔记','Saved analysis notes')}</small></div>
  <div className="pa-record-layout">
   <aside className="pa-record-outline"><small>{t('内容目录','Contents')}</small><nav aria-label={t('分析记录目录','Analysis record contents')}>
    <button type="button" aria-current={activeSection<0?'location':undefined} onClick={()=>onSection(-1)}>{t('问题与范围','Question and scope')}</button>
    {groups.map((group,index)=><button type="button" key={group.id+':'+index} aria-current={activeSection===index?'location':undefined} onClick={()=>onSection(index)}><span>{group.title}</span><b>{group.rows.length}</b></button>)}
   </nav><div className="pa-record-scope"><b>{t('分析范围','Analysis scope')}</b>{reason&&<p>{reason}</p>}<small>{t('固定时间窗','Fixed time window')}</small><p>{cockpitRecordWindow(detail.snapshot.context,en)}</p><small>{detail.snapshot.context.timezone}</small>{confirmed&&<p>{run.sources.length} {t('份固定资料','fixed sources')} · {t('第','Turn ')}{run.conversationVersion||1}{t('轮','')}</p>}</div></aside>
   <main className="pa-record-reader" ref={readerRef} aria-label={t('完整分析记录正文','Full analysis record text')}>
    <details className="pa-record-mobile-scope"><summary>{t('分析范围','Analysis scope')}</summary>{reason&&<p>{reason}</p>}<p>{cockpitRecordWindow(detail.snapshot.context,en)} · {detail.snapshot.context.timezone}</p></details>
    <div className="pa-record-question"><span><MessageSquare size={15}/>{run?.question?t('本轮问题','Question'):t('记录内容','Record')}</span><h2>{run?.question||detail.snapshot.title}</h2></div>
    {groups.map((group,index)=>{const Icon=icons[group.id as keyof typeof icons]??FileText;return <section className="pa-record-section" data-kind={group.id} data-record-section={index} key={group.id+':'+index} aria-labelledby={`${id}-${index}`}>
     <header><span className="pa-record-number">{String(index+1).padStart(2,'0')}</span><Icon size={18}/><h3 id={`${id}-${index}`}>{group.title}</h3><small>{group.rows.length} {en?(group.rows.length===1?'item':'items'):'条'}</small></header>
     <ol>{group.rows.map((row,item)=><li key={item}><span className="pa-record-item-number">{String(item+1).padStart(2,'0')}</span><div><p>{row.text}</p>{!!row.refs.length&&<div className="pa-record-citations"><small>{t('依据','Sources')}</small>{row.refs.map(key=><button type="button" key={key} disabled={!references[key]?.available} title={references[key]?.title??t('固定资料不可用','Fixed source unavailable')} onClick={()=>{onSection(index);onReference(key);}}>{key}<ArrowUpRight size={11}/></button>)}</div>}</div></li>)}</ol>
    </section>;})}
    {!groups.length&&<p className="pa-record-unavailable" role="status">{t('暂无可展示的已保存记录。来源或状态变化时，请先核对资料。','No saved record can be displayed. Check the sources if their state has changed.')}</p>}
    <p className="pa-record-boundary">{t('结论与建议仍需核对原始依据。可围绕当前画布资料继续提问。','Check conclusions and suggestions against their sources. You can ask about the current canvas materials.')}</p>
   </main>
  </div>
  <footer className="pa-record-footer"><small>{t('固定修订 · 只读查看','Fixed revision · read only')}</small><Btn onClick={onEdit}><ArrowUpRight size={14}/>{t('后台编辑','Edit in workbench')}</Btn><Btn primary onClick={onAsk}><MessageSquare size={14}/>{t('基于当前资料提问','Ask about these materials')}</Btn></footer>
 </div>;
}
