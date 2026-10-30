import {lazy,Suspense,useCallback,useEffect,useMemo,useRef,useState,type CSSProperties,type PointerEvent as ReactPointerEvent} from 'react';
import {ArrowUpRight,BookOpen,Box,CheckCheck,ChevronDown,ChevronLeft,ChevronRight,ChevronUp,FileText,GitBranch,Image,LayoutDashboard,Maximize2,Plus,RefreshCw,Sparkles,StickyNote,TriangleAlert,TrendingUp,X} from 'lucide-react';
import {cancelled,failureMessage,type WorkbenchApi} from './api';
import {Btn,IconBtn,Modal} from './Primitives';
import {AnalysisSourceCard,materialNames} from './AnalysisSourceCard';
import {AnalysisSources,type AnalysisEntry,type SourceAnchor} from './analysisSources';
import {SourceRelationLines,useSourceRelations} from './AnalysisSourceRelations';
import type {CanvasCard} from './analysisCanvas';
import type {AssistantRun} from './assistantApi';
import {PageDeck} from './CockpitPanels';
import {cockpitAnalysisDetail,cockpitAnalysisHistorical,cockpitAnalysisIndex,cockpitAnalysisPage,cockpitAnalysisPageFor,cockpitAnalysisTurns,type CockpitAnalysisDetail,type CockpitFault} from './cockpitAnalysisState';
import './analysisWorkspace.css';
import './cockpitAnalysis.css';

const icons={object:Box,drawing:FileText,document:BookOpen,photo:Image,model3d:Box,trend:TrendingUp,alarm:TriangleAlert,work_order:CheckCheck,analysis:StickyNote};
const ignore=()=>{};
const AssistantPanel=lazy(()=>import('./AssistantPanel').then(module=>({default:module.AssistantPanel})));
type Index=Awaited<ReturnType<typeof cockpitAnalysisIndex>>;
type Props={api:WorkbenchApi;active:boolean;en:boolean;entry:AnalysisEntry|null;faults:CockpitFault[];onChooseFault:(entry:AnalysisEntry)=>void;onBackend:(entry:AnalysisEntry)=>void};
export function CockpitAnalysis({api,active,en,entry,faults,onChooseFault,onBackend}:Props){
 const t=(zh:string,eng:string)=>en?eng:zh,board=useRef<HTMLDivElement>(null),workspace=useRef<HTMLElement>(null),queryPanel=useRef<HTMLElement>(null);
 const [queryOpen,setQueryOpen]=useState(false),[queryPosition,setQueryPosition]=useState<{x:number;y:number}|null>(null),[recordAttempt,setRecordAttempt]=useState(0);
 const queryDrag=useRef<{x:number;y:number;left:number;top:number}|null>(null);
 const [index,setIndex]=useState<Index|null>(null),[selected,setSelected]=useState(''),[detail,setDetail]=useState<CockpitAnalysisDetail|null>(null);
 const [loading,setLoading]=useState(false),[error,setError]=useState<unknown>(null),[attempt,setAttempt]=useState(0);
 const [page,setPage]=useState(0),[capacity,setCapacity]=useState<3|5>(5),[focused,setFocused]=useState(''),[expanded,setExpanded]=useState<CanvasCard|null>(null),[anchor,setAnchor]=useState<SourceAnchor|null>(null);
 const [availability,setAvailability]=useState<Record<string,string>>({});
 const [turns,setTurns]=useState<AssistantRun[]|null>(null),[turnError,setTurnError]=useState(false),[turnIndex,setTurnIndex]=useState(0),[recordOpen,setRecordOpen]=useState(false);
 const key=JSON.stringify(entry);
 useEffect(()=>{
  setIndex(null);setSelected('');setDetail(null);setExpanded(null);setError(null);setQueryOpen(false);setQueryPosition(null);
  if(!active)return;const abort=new AbortController();setLoading(true);
  void cockpitAnalysisIndex(api,entry,abort.signal).then(value=>{if(!abort.signal.aborted){setIndex(value);setSelected(value.items[0]?.analysisSessionId||'');}})
   .catch(value=>{if(!abort.signal.aborted&&!cancelled(value))setError(value);}).finally(()=>{if(!abort.signal.aborted)setLoading(false);});
  return()=>abort.abort();
 },[api,api.revision,api.epoch,active,key,attempt]);
 const faultEntry=index?.entry;
 const fault=faultEntry&&'datasetId'in faultEntry?faults.find(item=>item.datasetId===faultEntry.datasetId&&item.datasetRevision===faultEntry.datasetRevision):null;
 const candidate=index?.items.find(item=>item.analysisSessionId===selected);
 useEffect(()=>{
  setDetail(null);setExpanded(null);setQueryOpen(false);setPage(0);setFocused('');setAvailability({});setError(null);
  if(!active||!index||!candidate)return;const abort=new AbortController();setLoading(true);
  const initial=index.initial,request=initial?.analysisSessionId===candidate.analysisSessionId&&initial.analysisRevision===candidate.analysisRevision?Promise.resolve(initial):cockpitAnalysisDetail(api,candidate,abort.signal,fault?.faultCode);
  void request.then(value=>{if(!abort.signal.aborted)setDetail(value);}).catch(value=>{if(!abort.signal.aborted&&!cancelled(value))setError(value);}).finally(()=>{if(!abort.signal.aborted)setLoading(false);});
  return()=>abort.abort();
 },[api,index,candidate,active]);
 const sources=useMemo(()=>active&&detail?new AnalysisSources(api,detail.analysisSessionId):null,[api,api.revision,api.epoch,active,detail]);
 useEffect(()=>()=>sources?.dispose(),[sources]);
 useEffect(()=>{
  setTurns(null);setTurnError(false);setTurnIndex(0);setRecordOpen(false);
  if(!active||!detail)return;const abort=new AbortController();
  void cockpitAnalysisTurns(api,detail,abort.signal).then(value=>{if(!abort.signal.aborted){setTurns(value);setTurnIndex(Math.max(0,value.length-1));}}).catch(value=>{if(!abort.signal.aborted&&!cancelled(value)){setTurns([]);setTurnError(true);}});
  return()=>abort.abort();
 },[api,active,detail,recordAttempt]);
 useEffect(()=>{
  const node=board.current;if(!node)return;const observer=new ResizeObserver(()=>setCapacity(node.clientWidth<780||node.clientHeight<520?3:5));observer.observe(node);return()=>observer.disconnect();
 },[!!detail]);
 const layout=useMemo(()=>cockpitAnalysisPage(detail?.snapshot.cards||[],page,capacity),[detail,page,capacity]);
 const sourceRelations=useSourceRelations(sources,layout.cards);
 const readable=(card:CanvasCard)=>!card.source||availability[card.source.id]==='available';
 const links=sourceRelations.relations.filter(link=>readable(link.from)&&readable(link.to));
 const manual=detail?.snapshot.relations.filter(link=>layout.cards.some(card=>card.id===link.from&&readable(card))&&layout.cards.some(card=>card.id===link.to&&readable(card)))||[];
 const onAvailability=useCallback((id:string,value:string)=>setAvailability(current=>current[id]===value?current:{...current,[id]:value}),[]);
 function focusCard(card:CanvasCard,nextAnchor?:SourceAnchor|null){setPage(cockpitAnalysisPageFor(detail?.snapshot.cards||[],card.id,capacity));setFocused(card.id);if(nextAnchor){setExpanded(card);setAnchor(nextAnchor);}}
 function openCard(card:CanvasCard){setExpanded(card);setAnchor(null);}
 function closeQuery(){setQueryOpen(false);setRecordAttempt(value=>value+1);}
 function dragQuery(event:ReactPointerEvent<HTMLElement>){if(event.button!==0||(event.target as HTMLElement).closest('button'))return;const panel=queryPanel.current;if(!panel)return;queryDrag.current={x:event.clientX,y:event.clientY,left:panel.offsetLeft,top:panel.offsetTop};event.currentTarget.setPointerCapture(event.pointerId);}
 function moveQuery(event:ReactPointerEvent<HTMLElement>){const drag=queryDrag.current,panel=queryPanel.current,parent=workspace.current;if(!drag||!panel||!parent)return;setQueryPosition({x:Math.max(8,Math.min(parent.clientWidth-panel.offsetWidth-8,drag.left+event.clientX-drag.x)),y:Math.max(8,Math.min(parent.clientHeight-panel.offsetHeight-8,drag.top+event.clientY-drag.y))});}
 function endQueryDrag(){queryDrag.current=null;}
 function edit(){if(detail)onBackend({analysisSessionId:detail.analysisSessionId,analysisRevision:detail.analysisRevision,openLatest:true});}
 const run=turns?.[turnIndex],answer=run?.result&&['complete','partial'].includes(run.state)?run.result.answer:null;
 const noteCards=detail?.snapshot.cards.filter(card=>card.kind==='analysis'&&card.note?.trim())||[];
 const groups=answer?Object.entries({observations:t('观察','Observations'),hypotheses:t('可能原因 · 待验证','Possible causes · unverified'),gaps:t('证据缺口','Evidence gaps'),nextSteps:t('下一步核验','Next checks')}).flatMap(([id,title])=>answer[id as keyof typeof answer].length?[{id,title,rows:answer[id as keyof typeof answer]}]:[]):noteCards.map(card=>({id:card.id,title:card.title,rows:[{text:card.note!,refs:[] as string[]}]}));
 const faultValue=fault?JSON.stringify([fault.datasetId,fault.datasetRevision]):entry&&'datasetId'in entry?JSON.stringify([entry.datasetId,entry.datasetRevision]):'';
 const historical=detail&&cockpitAnalysisHistorical(detail,index?.entry||null);
 const message=error instanceof Error&&error.message==='ANALYSIS_CONTEXT_MISMATCH'?t('画布与当前故障不匹配，请重新选择。','The canvas does not match this fault. Choose again.'):error instanceof Error&&error.message==='ANALYSIS_CHANGED'?t('画布版本已变化，请重新读取。','The canvas revision changed. Reload it.'):failureMessage(error,en?'en':'zh');
 const content=(card:CanvasCard,full=false)=>card.source&&sources?<AnalysisSourceCard card={card} sources={sources} en={en} active viewOnly full={full} anchor={full?anchor:null} onActivate={ignore} onDeactivate={ignore} onOpen={()=>openCard(card)} onAvailability={onAvailability}/>:<div className="pa-note"><StickyNote size={26}/><p>{card.note?.trim()||t('暂无已保存的分析内容','No saved analysis content')}</p><small>{t('人工分析 · ','Manual analysis · ')}{({not_started:t('未执行','Not started'),checking:t('核查中','Checking'),done:t('已登记完成','Recorded complete'),blocked:t('受阻','Blocked')} as Record<string,string>)[card.checkState||'not_started']}</small></div>;
 return <section className="pa-workspace" ref={workspace} aria-label={t('故障分析展示','Fault analysis display')}>
  <header className="pa-context"><label><TriangleAlert size={16}/><span className="pa-control-label">{t('当前故障','Current fault')}</span><select aria-label={t('当前故障','Current fault')} value={faultValue} onChange={event=>{const [datasetId,datasetRevision]=JSON.parse(event.target.value);onChooseFault({datasetId,datasetRevision});}}><option value="" disabled>{t('选择故障','Choose a fault')}</option>{faults.map(item=><option key={JSON.stringify([item.datasetId,item.datasetRevision])} value={JSON.stringify([item.datasetId,item.datasetRevision])}>{item.faultCode} · {item.title}</option>)}</select></label>
   <label className="pa-canvas-choice"><LayoutDashboard size={15}/><select aria-label={t('推荐分析画布','Recommended analysis canvas')} value={selected} disabled={!index?.items.length||loading} onChange={event=>setSelected(event.target.value)}>{!index?.items.length&&<option value="">{t('推荐画布','Recommended canvases')}</option>}{index?.items.map(item=><option key={item.analysisSessionId} value={item.analysisSessionId}>{item.title} · r{item.analysisRevision}</option>)}</select></label>
   <span className="pa-context-spacer"/><IconBtn label={t('刷新推荐画布','Refresh recommendations')} onClick={()=>setAttempt(value=>value+1)}><RefreshCw size={15}/></IconBtn><Btn disabled={!detail||loading} onClick={edit}><ArrowUpRight size={15}/>{t('后台编辑','Edit in workbench')}</Btn><Btn onClick={()=>onBackend({newDraft:true})}><Plus size={15}/>{t('新建画布','New canvas')}</Btn>
  </header>
  {!!error&&<div className="pa-error" role="alert"><TriangleAlert size={18}/><p>{message}</p><Btn onClick={()=>setAttempt(value=>value+1)}>{t('重试','Retry')}</Btn></div>}
  {loading&&!detail?<div className="pa-empty" role="status"><LayoutDashboard size={42}/><p>{t('正在加载相关画布…','Loading related canvas…')}</p></div>:!detail&&!error?<div className="pa-empty"><GitBranch size={52}/><h2>{index?.entry?t('暂无相关分析画布','No related analysis canvases'):t('选择当前故障','Choose the current fault')}</h2><p>{index?.entry?t('可在后台新建分析画布。','Create an analysis canvas in the workbench.'):t('查看此故障的已保存分析与关联资料。','View saved analysis and evidence for this fault.')}</p></div>:detail&&sources?<div className="pa-content">
   <main className="pa-evidence"><div className="pa-canvas-caption"><div><strong>{detail.snapshot.title}</strong><small>{historical?t('历史参考','Historical reference'):t('固定分析','Fixed analysis')} · r{detail.analysisRevision} · {new Date(detail.snapshot.context.timeFrom).toLocaleString(en?'en-GB':'zh-CN',{timeZone:detail.snapshot.context.timezone})}</small></div><button title={candidate?.reason} onClick={()=>setRecordOpen(true)}><InfoLabel en={en}/></button></div>
    <div className="pa-board" ref={board} aria-label={t('可视化分析画布','Visual analysis canvas')}>
     <svg className="pa-links" viewBox="0 0 1000 700" preserveAspectRatio="none" aria-label={t('已有资料关系','Recorded evidence relationships')}><defs><marker id="ad-source-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8" fill="none" stroke="currentColor"/></marker></defs><SourceRelationLines relations={links} onOpen={link=>focusCard(link.to,link.anchor)}/>{manual.map(link=>{const a=layout.cards.find(card=>card.id===link.from)!,b=layout.cards.find(card=>card.id===link.to)!,x=a.x+a.width/2,y=a.y+a.height/2,x2=b.x+b.width/2,y2=b.y+b.height/2;return <g key={link.id} className="pa-manual-link"><title>{link.reason}</title><path d={`M${x},${y} C${x},${(y+y2)/2} ${x2},${(y+y2)/2} ${x2},${y2}`}/><text x={(x+x2)/2} y={(y+y2)/2-6} textAnchor="middle">{link.kind==='hypothesis'?t('人工假设','Manual hypothesis'):t('人工关联','Manual relation')}</text></g>;})}</svg>
     {layout.cards.map(card=>{const Icon=icons[card.kind];return <article className="pa-card" key={detail.analysisSessionId+':'+detail.analysisRevision+':'+card.id} data-kind={card.kind} data-focused={card.id===focused||undefined} data-historical={card.historical||undefined} style={{left:card.x/10+'%',top:card.y/7+'%',width:card.width/10+'%',height:card.height/7+'%'} as CSSProperties}>
      <header><Icon size={18}/><h3 title={card.title}>{card.title}</h3><IconBtn label={t('放大查看：','Expand: ')+card.title} onClick={()=>openCard(card)}><Maximize2 size={14}/></IconBtn></header><div className="pa-card-body">{content(card)}</div><footer><span>{en?card.kind:materialNames[card.kind]}</span>{card.historical&&<small>{t('历史参考','Historical reference')}</small>}</footer>
     </article>;})}
    </div><footer className="pa-board-footer"><small>{t('实线：登记关系 · 虚线：候选或人工假设','Solid: recorded relations · Dashed: candidates or manual hypotheses')}</small><span>{layout.total} {t('张卡片','cards')}</span><button disabled={layout.page===0} aria-label={t('上一组资料','Previous evidence group')} onClick={()=>setPage(layout.page-1)}><ChevronLeft size={16}/></button><small>{layout.page+1} / {layout.count}</small><button disabled={layout.page+1===layout.count} aria-label={t('下一组资料','Next evidence group')} onClick={()=>setPage(layout.page+1)}><ChevronRight size={16}/></button></footer>
   </main>
   <aside className="pa-record pc-panel"><header><Sparkles size={22}/><h2>{t('工程助手','Engineering assistant')}</h2><small>{t('已保存记录','Saved record')}</small></header>
    {turns&&turns.length>1&&<div className="pa-turns"><button aria-label={t('上一轮分析','Previous analysis turn')} disabled={turnIndex===0} onClick={()=>setTurnIndex(turnIndex-1)}><ChevronLeft size={15}/></button><span>{t('第','Turn ')}{(run?.conversationVersion||turnIndex+1)}{t('轮','')}</span><button aria-label={t('下一轮分析','Next analysis turn')} disabled={turnIndex+1===turns.length} onClick={()=>setTurnIndex(turnIndex+1)}><ChevronRight size={15}/></button></div>}
    {run?.question&&<div className="pa-question"><Sparkles size={18}/><p>{run.question}</p></div>}
    {turns===null?<p className="pa-record-state" role="status">{t('正在读取分析记录…','Loading analysis record…')}</p>:turnError?<p className="pa-record-state" role="status">{t('已保存的助手记录暂不可用。','The saved assistant record is unavailable.')}</p>:run&&!answer?<p className="pa-record-state" role="status">{t('此轮暂无可展示回答，来源或状态可能已变化。','This turn has no displayable answer; its sources or state may have changed.')}</p>:!groups.length?<div className="pa-record-empty"><Sparkles size={36}/><p>{t('暂无已保存的分析记录','No saved analysis record')}</p></div>:null}
    {!!groups.length&&<PageDeck key={detail.analysisSessionId+':'+detail.analysisRevision+':'+turnIndex} en={en} label={t('已保存分析记录','Saved analysis record')} items={groups} rowHeight={160} minimumRows={1} render={group=><section className="pa-answer" data-kind={group.id}><h3>{group.id==='hypotheses'?<TriangleAlert size={17}/>:<CheckCheck size={17}/>}<span>{group.title}</span></h3>{group.rows.slice(0,2).map((row,i)=><p key={i}>{row.text}<span>{row.refs.map(ref=>{const source=run?.sources.find(item=>item.key===ref),card=detail.snapshot.cards.find(item=>item.source?.id===source?.evidenceRefId);return <button key={ref} disabled={!card} onClick={()=>card&&focusCard(card)}>{ref}</button>;})}</span></p>)}</section>}/>}
    <button className="pa-record-more" onClick={()=>setRecordOpen(true)}>{t('查看完整记录','View full record')}<Maximize2 size={14}/></button><button className="pa-edit-action" onClick={edit}><ArrowUpRight size={17}/>{t('在后台继续分析','Continue in workbench')}</button>
   </aside>
  </div>:null}
  {expanded&&<Modal className="pa-expanded" title={expanded.title} description={t('固定来源 · 查看','Fixed source · View')} onClose={()=>{setExpanded(null);setAnchor(null);}}>{content(expanded,true)}</Modal>}
  {recordOpen&&detail&&<Modal className="pa-record-dialog" title={t('分析记录与范围','Analysis record and scope')} description={detail.snapshot.title+' · r'+detail.analysisRevision} onClose={()=>setRecordOpen(false)}><p>{candidate?.reason}</p><p>{detail.snapshot.context.timeFrom} — {detail.snapshot.context.timeTo} · {detail.snapshot.context.timezone}</p>{run?.question&&<h3>{run.question}</h3>}{groups.map(group=><section key={group.id}><h3>{group.title}</h3>{group.rows.map((row,i)=><p key={i}>{row.text}</p>)}</section>)}{!groups.length&&<p>{t('暂无可展示的已保存记录。','No saved record is available to display.')}</p>}<Btn onClick={edit}><ArrowUpRight size={15}/>{t('在后台继续分析','Continue in workbench')}</Btn></Modal>}
  {detail&&<button className="pa-query-launch" aria-expanded={queryOpen} aria-controls="pa-floating-query" onClick={()=>queryOpen?closeQuery():setQueryOpen(true)}><Sparkles size={21}/><span>{t('向助手查询当前故障…','Ask about this fault…')}</span><ArrowUpRight size={17}/></button>}
  {queryOpen&&detail&&<aside id="pa-floating-query" ref={queryPanel} className="pa-query ad-inspector ad-assistant" role="dialog" aria-modal="false" aria-labelledby="pa-query-heading" style={queryPosition?{left:queryPosition.x,top:queryPosition.y,right:'auto',bottom:'auto'}:undefined} onKeyDown={event=>{if(event.key==='Escape'){event.stopPropagation();closeQuery();}}}>
   <header onPointerDown={dragQuery} onPointerMove={moveQuery} onPointerUp={endQueryDrag} onPointerCancel={endQueryDrag}><Sparkles size={19}/><div><h2 id="pa-query-heading">{t('查询助手','Query assistant')}</h2><small>{detail.snapshot.title} · r{detail.analysisRevision}</small></div><IconBtn label={t('关闭查询助手','Close query assistant')} onClick={closeQuery}><X size={16}/></IconBtn></header>
   <div className="pa-query-body"><Suspense fallback={<p role="status">{t('正在打开助手…','Opening assistant…')}</p>}><AssistantPanel queryOnly api={api} cards={detail.snapshot.cards} receipt={detail} en={en} canAddNote={false} canTransfer={false} onFocus={focusCard} onAddNote={ignore}/></Suspense></div><footer className="pa-query-pages"><button aria-label={t('查询内容上翻','Previous query content')} onClick={()=>queryPanel.current?.querySelector('.pa-query-body')?.scrollBy({top:-240,behavior:'smooth'})}><ChevronUp size={15}/></button><button aria-label={t('查询内容下翻','Next query content')} onClick={()=>queryPanel.current?.querySelector('.pa-query-body')?.scrollBy({top:240,behavior:'smooth'})}><ChevronDown size={15}/></button></footer>
  </aside>}
 </section>;
}
function InfoLabel({en}:{en:boolean}){return <><GitBranch size={13}/>{en?'Record & scope':'记录与范围'}<ChevronRight size={12}/></>;}
