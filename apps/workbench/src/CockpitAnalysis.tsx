import {lazy,Suspense,useCallback,useEffect,useLayoutEffect,useMemo,useRef,useState,type CSSProperties,type KeyboardEvent as ReactKeyboardEvent,type PointerEvent as ReactPointerEvent} from 'react';
import {ArrowUpRight,BookOpen,Box,CheckCheck,ChevronDown,ChevronLeft,ChevronRight,ChevronUp,FileText,GitBranch,GripVertical,Hand,Image,LayoutDashboard,Maximize2,Plus,RefreshCw,RotateCcw,Sparkles,StickyNote,TriangleAlert,TrendingUp,X,ZoomIn,ZoomOut} from 'lucide-react';
import {cancelled,failureMessage,type WorkbenchApi} from './api';
import {Btn,IconBtn,Modal} from './Primitives';
import {AnalysisSourceCard,materialNames} from './AnalysisSourceCard';
import {AnalysisSources,type AnalysisEntry,type SourceAnchor} from './analysisSources';
import {useSourceRelations} from './AnalysisSourceRelations';
import {cockpitRelationGraph,cockpitRelationLabels,cockpitRelationRoute,type CockpitRelation} from './cockpitRelationGraph';
import type {CanvasCard,Viewport} from './analysisCanvas';
import {COCKPIT_CANVAS_MIN_ZOOM,COCKPIT_CANVAS_MAX_ZOOM,cockpitAnalysisLayout,cockpitCardMove,cockpitCanvasFit,cockpitCanvasZoom,cockpitCanvasPan,cockpitCanvasFocus,cockpitCanvasReveal,cockpitCanvasWheel,type CockpitCardPositions} from './cockpitAnalysisCanvas';
import type {AssistantRun} from './assistantApi';
import {PageDeck} from './CockpitPanels';
import {cockpitAnalysisDetail,cockpitAnalysisHistorical,cockpitAnalysisIndex,cockpitAnalysisTurns,cockpitNoteRecords,type CockpitAnalysisDetail,type CockpitFault} from './cockpitAnalysisState';
import './analysisWorkspace.css';
import './cockpitAnalysis.css';

const icons={object:Box,drawing:FileText,document:BookOpen,photo:Image,model3d:Box,trend:TrendingUp,alarm:TriangleAlert,work_order:CheckCheck,analysis:StickyNote};
const ignore=()=>{};
const AssistantPanel=lazy(()=>import('./AssistantPanel').then(module=>({default:module.AssistantPanel})));
type Index=Awaited<ReturnType<typeof cockpitAnalysisIndex>>;
type Props={api:WorkbenchApi;active:boolean;en:boolean;entry:AnalysisEntry|null;faults:CockpitFault[];onChooseFault:(entry:AnalysisEntry)=>void;onBackend:(entry:AnalysisEntry)=>void};
export function CockpitAnalysis({api,active,en,entry,faults,onChooseFault,onBackend}:Props){
 const t=(zh:string,eng:string)=>en?eng:zh,board=useRef<HTMLDivElement>(null),world=useRef<HTMLDivElement>(null),workspace=useRef<HTMLElement>(null),queryPanel=useRef<HTMLElement>(null);
 const [queryOpen,setQueryOpen]=useState(false),[queryPosition,setQueryPosition]=useState<{x:number;y:number}|null>(null),[recordAttempt,setRecordAttempt]=useState(0);
 const queryDrag=useRef<{x:number;y:number;left:number;top:number}|null>(null);
 const [index,setIndex]=useState<Index|null>(null),[selected,setSelected]=useState(''),[detail,setDetail]=useState<CockpitAnalysisDetail|null>(null);
 const [loading,setLoading]=useState(false),[error,setError]=useState<unknown>(null),[attempt,setAttempt]=useState(0);
 const [focused,setFocused]=useState(''),[expanded,setExpanded]=useState<CanvasCard|null>(null),[anchor,setAnchor]=useState<SourceAnchor|null>(null);
 const [availability,setAvailability]=useState<Record<string,string>>({});
 const [relation,setRelation]=useState<CockpitRelation|null>(null);
 const [boardSize,setBoardSize]=useState({width:0,height:0}),[labelPositions,setLabelPositions]=useState<Record<string,{x:number;y:number}>>({});
 const [cardPositions,setCardPositions]=useState<CockpitCardPositions>({}),[draggingCard,setDraggingCard]=useState(''),[frontCard,setFrontCard]=useState('');
 const [viewport,setViewport]=useState<Viewport>({x:24,y:24,zoom:1}),[hand,setHand]=useState(false),[panning,setPanning]=useState(false);
 const viewportRef=useRef(viewport),autoFit=useRef(true),space=useRef(false),lastBoardSize=useRef({width:0,height:0});viewportRef.current=viewport;
 const panDrag=useRef<{pointerId:number;x:number;y:number;sx:number;sy:number;view:Viewport;node:HTMLDivElement}|null>(null);

 const cardDrag=useRef<{card:CanvasCard;pointerId:number;x:number;y:number;width:number;height:number;previous:CockpitCardPositions[string]|undefined;header:HTMLElement;moved:boolean}|null>(null);
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
  endCardDrag(true);endPan(true);setCardPositions({});setFrontCard('');setHand(false);autoFit.current=true;
  setDetail(null);setExpanded(null);setRelation(null);setQueryOpen(false);setFocused('');setAvailability({});setError(null);
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
 const layout=useMemo(()=>cockpitAnalysisLayout(detail?.snapshot.cards||[],cardPositions),[detail,cardPositions]);
 const layoutRef=useRef(layout);layoutRef.current=layout;
 useEffect(()=>{
  const node=board.current;if(!node)return;
  const resize=()=>{endCardDrag(true);endPan(true);const size={width:node.clientWidth,height:node.clientHeight},previous=lastBoardSize.current;lastBoardSize.current=size;
   setBoardSize(size);setViewport(current=>autoFit.current?cockpitCanvasFit(layoutRef.current.cards,size):cockpitCanvasPan(current,{x:(size.width-previous.width)/2,y:(size.height-previous.height)/2}));};
  const observer=new ResizeObserver(resize);observer.observe(node);return()=>observer.disconnect();
 },[!!detail]);
 useLayoutEffect(()=>{if(detail&&board.current){autoFit.current=true;setViewport(cockpitCanvasFit(layoutRef.current.cards,{width:board.current.clientWidth,height:board.current.clientHeight}));}},[detail?.analysisSessionId,detail?.analysisRevision]);
 useEffect(()=>{const cancel=(event:KeyboardEvent)=>{if(event.key==='Escape'){if(cardDrag.current){event.preventDefault();endCardDrag(true);}if(panDrag.current){event.preventDefault();endPan(true);}space.current=false;}};const blur=()=>{space.current=false;endCardDrag(true);endPan(true);};window.addEventListener('keydown',cancel);window.addEventListener('blur',blur);return()=>{window.removeEventListener('keydown',cancel);window.removeEventListener('blur',blur);};},[]);
 useEffect(()=>{
  const node=board.current;if(!node)return;
  const wheel=(event:WheelEvent)=>{
   if(cardDrag.current||panDrag.current){event.preventDefault();event.stopPropagation();return;}
   if(!cockpitCanvasWheel(!!(event.target as Element).closest('[data-canvas-inner]'),event.ctrlKey||event.metaKey,hand))return;
   const rect=node.getBoundingClientRect();if(!rect.width||!rect.height)return;event.preventDefault();event.stopPropagation();autoFit.current=false;
   const delta=event.deltaY*(event.deltaMode===1?16:event.deltaMode===2?node.clientHeight:1);
   const point={x:(event.clientX-rect.left)*node.clientWidth/rect.width,y:(event.clientY-rect.top)*node.clientHeight/rect.height};
   setViewport(current=>cockpitCanvasZoom(current,current.zoom*Math.exp(-Math.max(-400,Math.min(400,delta))*.0015),point));
  };
  node.addEventListener('wheel',wheel,{passive:false,capture:true});return()=>node.removeEventListener('wheel',wheel,true);
 },[!!detail,hand]);
 const sourceRelations=useSourceRelations(sources,detail?.snapshot.cards||[]);
 const links=cockpitRelationGraph(detail?.snapshot.cards||[],layout.cards,sourceRelations.relations,detail?.snapshot.relations||[],availability,sourceRelations.gaps,en).map(link=>({...link,route:cockpitRelationRoute(link.from,link.to)}));
 const linkSignature=JSON.stringify(links.map(link=>[link.id,link.label,link.route]));
 useLayoutEffect(()=>{
  const sizes:Record<string,{width:number;height:number}>={};board.current?.querySelectorAll<HTMLButtonElement>('.pa-relation-label').forEach(node=>{sizes[node.dataset.relationId!]={width:node.offsetWidth,height:node.offsetHeight};});
  const positions=cockpitRelationLabels(links,layout.cards,sizes,layout.width,layout.height,layout);
  setLabelPositions(current=>JSON.stringify(current)===JSON.stringify(positions)?current:positions);
 },[linkSignature,boardSize.width,boardSize.height,layout.width,layout.height]);
 const onAvailability=useCallback((id:string,value:string)=>setAvailability(current=>current[id]===value?current:{...current,[id]:value}),[]);
 function focusCard(card:CanvasCard,nextAnchor?:SourceAnchor|null){const placed=layout.cards.find(item=>item.id===card.id);if(placed){autoFit.current=false;setViewport(current=>cockpitCanvasFocus(current,placed,boardSize));}setFocused(card.id);setFrontCard(card.id);if(nextAnchor){setExpanded(card);setAnchor(nextAnchor);}}
 function openCard(card:CanvasCard){setExpanded(card);setAnchor(null);}
 function revealCard(card:CanvasCard,target:Element,node:HTMLElement){
  if(!target.matches(':focus-visible')||!board.current)return;
  const rect=node.getBoundingClientRect(),bounds=board.current.getBoundingClientRect();
  if(rect.left<bounds.left||rect.top<bounds.top||rect.right>bounds.right||rect.bottom>bounds.bottom)focusCard(card);
 }
 function revealRelation(point:{x:number;y:number},node:HTMLElement){
  if(!node.matches(':focus-visible')||!board.current)return;
  const rect=node.getBoundingClientRect(),bounds=board.current.getBoundingClientRect();
  if(rect.left>=bounds.left&&rect.top>=bounds.top&&rect.right<=bounds.right&&rect.bottom<=bounds.bottom)return;
  autoFit.current=false;setViewport(current=>({...current,x:boardSize.width/2-point.x*current.zoom,y:boardSize.height/2-point.y*current.zoom}));
 }

 function closeQuery(){setQueryOpen(false);setRecordAttempt(value=>value+1);}
 function dragCard(event:ReactPointerEvent<HTMLElement>,card:CanvasCard){
  if(event.button!==0||!event.isPrimary||card.id===layout.center?.id||(event.target as Element).closest('button:not(.pa-card-grip)'))return;
  const rect=world.current?.getBoundingClientRect();if(!rect?.width||!rect.height)return;
  event.preventDefault();event.stopPropagation();autoFit.current=false;event.currentTarget.setPointerCapture(event.pointerId);setFrontCard(card.id);
  cardDrag.current={card,pointerId:event.pointerId,x:event.clientX,y:event.clientY,width:rect.width,height:rect.height,previous:cardPositions[card.id],header:event.currentTarget,moved:false};
 }
 function moveCard(event:ReactPointerEvent<HTMLElement>){
  const drag=cardDrag.current;if(!drag||event.pointerId!==drag.pointerId)return;
  const delta={x:event.clientX-drag.x,y:event.clientY-drag.y};if(!drag.moved&&Math.hypot(delta.x,delta.y)<3)return;
  drag.moved=true;setDraggingCard(drag.card.id);setCardPositions(current=>({...current,[drag.card.id]:cockpitCardMove(drag.card,delta,drag,layout)}));
 }
 function endCardDrag(cancel=false){
  const drag=cardDrag.current;if(!drag)return;cardDrag.current=null;setDraggingCard('');
  if(cancel&&drag.moved)setCardPositions(current=>{const next={...current};if(drag.previous)next[drag.card.id]=drag.previous;else delete next[drag.card.id];return next;});
  if(drag.header.hasPointerCapture(drag.pointerId))drag.header.releasePointerCapture(drag.pointerId);
 }
 function nudgeCard(event:ReactKeyboardEvent<HTMLButtonElement>,card:CanvasCard){
  if(cardDrag.current)return;
  const step=event.shiftKey?24:8,delta=({ArrowLeft:{x:-step,y:0},ArrowRight:{x:step,y:0},ArrowUp:{x:0,y:-step},ArrowDown:{x:0,y:step}} as Record<string,{x:number;y:number}>)[event.key];
  if(!delta)return;const rect=world.current?.getBoundingClientRect();if(!rect)return;event.preventDefault();event.stopPropagation();autoFit.current=false;setFrontCard(card.id);setFocused(card.id);const moved={...card,...cockpitCardMove(card,delta,rect,layout)};setCardPositions(current=>({...current,[card.id]:{x:moved.x,y:moved.y}}));setViewport(current=>cockpitCanvasReveal(current,moved,boardSize));
 }
 function resetLayout(){endCardDrag();endPan();setCardPositions({});setFrontCard('');autoFit.current=true;setViewport(cockpitCanvasFit(cockpitAnalysisLayout(detail?.snapshot.cards||[]).cards,boardSize));}
 function fitCanvas(){endCardDrag();endPan();autoFit.current=true;setViewport(cockpitCanvasFit(layout.cards,boardSize));}
 function zoomCanvas(value:number){autoFit.current=false;setViewport(current=>cockpitCanvasZoom(current,value,{x:boardSize.width/2,y:boardSize.height/2}));}
 function beginPan(event:ReactPointerEvent<HTMLDivElement>,capture=false){
  if(!event.isPrimary||![0,1].includes(event.button)||cardDrag.current||panDrag.current)return;
  const forced=event.button===1||hand||space.current;
  if(capture&&!forced||!capture&&forced)return;
  if(!forced&&(event.target as Element).closest('.pa-card,.pa-relation-label,button,input,select,textarea,a'))return;
  if(forced&&event.button===0&&(event.target as Element).closest('button,input,select,textarea,a'))return;
  const node=event.currentTarget,rect=node.getBoundingClientRect();if(!rect.width||!rect.height)return;
  event.preventDefault();event.stopPropagation();node.focus({preventScroll:true});node.setPointerCapture(event.pointerId);autoFit.current=false;setPanning(true);
  panDrag.current={pointerId:event.pointerId,x:event.clientX,y:event.clientY,sx:node.clientWidth/rect.width,sy:node.clientHeight/rect.height,view:viewportRef.current,node};
 }
 function movePan(event:ReactPointerEvent<HTMLDivElement>){const drag=panDrag.current;if(!drag||event.pointerId!==drag.pointerId)return;setViewport(cockpitCanvasPan(drag.view,{x:(event.clientX-drag.x)*drag.sx,y:(event.clientY-drag.y)*drag.sy}));}
 function endPan(cancel=false){const drag=panDrag.current;if(!drag)return;panDrag.current=null;setPanning(false);if(cancel)setViewport(drag.view);if(drag.node.hasPointerCapture(drag.pointerId))drag.node.releasePointerCapture(drag.pointerId);}
 function canvasKey(event:ReactKeyboardEvent<HTMLDivElement>){
  if((event.target as Element).closest('button,input,select,textarea,[data-canvas-inner]'))return;
  if(event.code==='Space'){event.preventDefault();space.current=true;return;}
  if(['+','=','-','0','1'].includes(event.key)){event.preventDefault();if(event.key==='0')fitCanvas();else zoomCanvas(event.key==='1'?1:viewportRef.current.zoom*(event.key==='-'?.8:1.25));return;}
  const delta=({ArrowLeft:{x:48,y:0},ArrowRight:{x:-48,y:0},ArrowUp:{x:0,y:48},ArrowDown:{x:0,y:-48}} as Record<string,{x:number;y:number}>)[event.key];
  if(delta){event.preventDefault();autoFit.current=false;setViewport(current=>cockpitCanvasPan(current,delta));}
 }

 function dragQuery(event:ReactPointerEvent<HTMLElement>){if(event.button!==0||(event.target as HTMLElement).closest('button'))return;const panel=queryPanel.current;if(!panel)return;queryDrag.current={x:event.clientX,y:event.clientY,left:panel.offsetLeft,top:panel.offsetTop};event.currentTarget.setPointerCapture(event.pointerId);}
 function moveQuery(event:ReactPointerEvent<HTMLElement>){const drag=queryDrag.current,panel=queryPanel.current,parent=workspace.current;if(!drag||!panel||!parent)return;setQueryPosition({x:Math.max(8,Math.min(parent.clientWidth-panel.offsetWidth-8,drag.left+event.clientX-drag.x)),y:Math.max(8,Math.min(parent.clientHeight-panel.offsetHeight-8,drag.top+event.clientY-drag.y))});}
 function endQueryDrag(){queryDrag.current=null;}
 function edit(){if(detail)onBackend({analysisSessionId:detail.analysisSessionId,analysisRevision:detail.analysisRevision,openLatest:true});}
 const run=turns?.[turnIndex],answer=run?.result&&['complete','partial'].includes(run.state)?run.result.answer:null;
 const noteCards=detail?.snapshot.cards.filter(card=>card.kind==='analysis'&&card.note?.trim())||[];
 const groups=answer?Object.entries({observations:t('观察','Observations'),hypotheses:t('可能原因 · 待验证','Possible causes · unverified'),gaps:t('证据缺口','Evidence gaps'),nextSteps:t('下一步核验','Next checks')}).flatMap(([id,title])=>answer[id as keyof typeof answer].length?[{id,title,rows:answer[id as keyof typeof answer]}]:[]):cockpitNoteRecords(noteCards,en);
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
    <div className="pa-board" ref={board} tabIndex={0} role="region" aria-label={t('可视化分析画布','Visual analysis canvas')} aria-describedby="pa-canvas-help" data-pan-tool={hand||undefined} data-panning={panning||undefined}
     onPointerDownCapture={event=>beginPan(event,true)} onPointerDown={event=>beginPan(event)} onPointerMove={movePan} onPointerUp={()=>endPan()} onPointerCancel={()=>endPan(true)} onLostPointerCapture={()=>endPan(true)} onAuxClick={event=>{if(event.button===1)event.preventDefault();}} onKeyDown={canvasKey} onKeyUp={event=>{if(event.code==='Space')space.current=false;}} onBlur={event=>{if(!event.currentTarget.contains(event.relatedTarget as Node)){space.current=false;endPan();}}}>
     <span id="pa-canvas-help" className="pa-canvas-help">{t('滚轮缩放，拖动空白平移；空格或中键拖动也可平移。资料卡标题栏可拖动。','Wheel to zoom, drag the background to pan; Space or middle-drag also pans. Drag card headers to move cards.')}</span>
     <div className="pa-world" ref={world} style={{width:layout.width,height:layout.height,transform:`translate(${viewport.x}px,${viewport.y}px) scale(${viewport.zoom})`}}>
     <svg className="pa-links" viewBox={`0 0 ${layout.width} ${layout.height}`} preserveAspectRatio="xMidYMid meet" aria-hidden="true"><defs><marker id="pa-source-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8" fill="none" stroke="currentColor"/></marker></defs>{links.map(link=><path key={link.id} data-origin={link.origin} d={cockpitRelationRoute(link.from,link.to,labelPositions[link.id]).d} markerEnd="url(#pa-source-arrow)"/>)}</svg>
     <div className="pa-relation-labels" role="group" aria-label={t('已有资料关系','Recorded evidence relationships')}>{links.map(link=>{const point=labelPositions[link.id]||link.route;return <button key={link.id} className="pa-relation-label" data-relation-id={link.id} data-origin={link.origin} data-via={link.via.length||undefined} style={{left:point.x,top:point.y}} title={link.reason} aria-label={link.label+'：'+[link.from,...link.via,link.to].map(card=>card.title).join(' ↔ ')} onFocus={event=>revealRelation(point,event.currentTarget)} onClick={()=>setRelation(link)}>{link.label}{link.origin==='candidate'&&!/候选|candidate/i.test(link.label)&&<span>{t('候选','Candidate')}</span>}</button>;})}</div>
     {layout.cards.map(card=>{const Icon=icons[card.kind],draggable=card.id!==layout.center?.id;return <article className="pa-card" key={detail.analysisSessionId+':'+detail.analysisRevision+':'+card.id} data-card-id={card.id} data-kind={card.kind} onFocus={event=>revealCard(card,event.target,event.currentTarget)} data-focused={card.id===focused||undefined} data-historical={card.historical||undefined} data-front={card.id===frontCard||undefined} data-dragging={card.id===draggingCard||undefined} style={{left:card.x,top:card.y,width:card.width,height:card.height} as CSSProperties}>
      <header data-draggable={draggable||undefined} onPointerDown={event=>dragCard(event,card)} onPointerMove={moveCard} onPointerUp={event=>{if(event.pointerId===cardDrag.current?.pointerId)endCardDrag();}} onPointerCancel={event=>{if(event.pointerId===cardDrag.current?.pointerId)endCardDrag(true);}} onLostPointerCapture={event=>{if(event.pointerId===cardDrag.current?.pointerId)endCardDrag(true);}}>{draggable&&<button className="pa-card-grip" aria-label={t('移动资料卡：','Move card: ')+card.title} title={t('拖动标题栏，或用方向键调整位置','Drag the header or use arrow keys to move')} onKeyDown={event=>nudgeCard(event,card)}><GripVertical size={14}/></button>}<Icon size={18}/><h3 title={card.title}>{card.title}</h3><IconBtn label={t('放大查看：','Expand: ')+card.title} onClick={()=>openCard(card)}><Maximize2 size={14}/></IconBtn></header><div className="pa-card-body">{content(card)}</div><footer><span>{en?card.kind:materialNames[card.kind]}</span>{card.historical&&<small>{t('历史参考','Historical reference')}</small>}</footer>
     </article>;})}
    </div></div><footer className="pa-board-footer"><small title={t('实线：登记关系 · 虚线：候选或人工关联 · 经对象：关联链','Solid: recorded · Dashed: candidate or manual · Via object: relationship path')}>{sourceRelations.error?<button onClick={sourceRelations.retry}>{t('关系读取失败，重试','Retry relationships')}</button>:sourceRelations.loading?t('正在读取关系…','Loading relationships…'):t('实线：登记关系 · 虚线：候选/人工 · 经对象：关联链','Solid: recorded · Dashed: candidate/manual · Via object: path')}</small><button className="pa-layout-reset" disabled={!Object.keys(cardPositions).length} onClick={resetLayout}><RotateCcw size={13}/>{t('恢复布局','Reset layout')}</button><span>{layout.total} {t('张卡片','cards')}</span><div className="pa-canvas-tools" role="group" aria-label={t('画布视图','Canvas view')}><IconBtn label={t('平移画布','Pan canvas')} aria-pressed={hand} onClick={()=>setHand(value=>!value)}><Hand size={15}/></IconBtn><IconBtn label={t('缩小画布','Zoom out canvas')} disabled={viewport.zoom<=COCKPIT_CANVAS_MIN_ZOOM} onClick={()=>zoomCanvas(viewport.zoom*.8)}><ZoomOut size={15}/></IconBtn><button className="pa-zoom-value" aria-label={t('画布原尺寸100%','Canvas actual size 100%')} title={t('恢复100%','Reset to 100%')} onClick={()=>zoomCanvas(1)}>{Math.round(viewport.zoom*100)}%</button><IconBtn label={t('放大画布','Zoom in canvas')} disabled={viewport.zoom>=COCKPIT_CANVAS_MAX_ZOOM} onClick={()=>zoomCanvas(viewport.zoom*1.25)}><ZoomIn size={15}/></IconBtn><IconBtn label={t('适应全部资料','Fit all evidence')} onClick={fitCanvas}><Maximize2 size={15}/></IconBtn></div></footer>
   </main>
   <aside className="pa-record pc-panel"><header><Sparkles size={22}/><h2>{t('工程助手','Engineering assistant')}</h2><small>{t('已保存记录','Saved record')}</small></header>
    {turns&&turns.length>1&&<div className="pa-turns"><button aria-label={t('上一轮分析','Previous analysis turn')} disabled={turnIndex===0} onClick={()=>setTurnIndex(turnIndex-1)}><ChevronLeft size={15}/></button><span>{t('第','Turn ')}{(run?.conversationVersion||turnIndex+1)}{t('轮','')}</span><button aria-label={t('下一轮分析','Next analysis turn')} disabled={turnIndex+1===turns.length} onClick={()=>setTurnIndex(turnIndex+1)}><ChevronRight size={15}/></button></div>}
    {run?.question&&<div className="pa-question"><Sparkles size={18}/><p>{run.question}</p></div>}
    {turns===null?<p className="pa-record-state" role="status">{t('正在读取分析记录…','Loading analysis record…')}</p>:turnError?<p className="pa-record-state" role="status">{t('已保存的助手记录暂不可用。','The saved assistant record is unavailable.')}</p>:run&&!answer?<p className="pa-record-state" role="status">{t('此轮暂无可展示回答，来源或状态可能已变化。','This turn has no displayable answer; its sources or state may have changed.')}</p>:!groups.length?<div className="pa-record-empty"><Sparkles size={36}/><p>{t('暂无已保存的分析记录','No saved analysis record')}</p></div>:null}
    {!!groups.length&&<PageDeck key={detail.analysisSessionId+':'+detail.analysisRevision+':'+turnIndex} en={en} label={t('已保存分析记录','Saved analysis record')} items={groups} rowHeight={160} minimumRows={1} render={group=><section className="pa-answer" data-kind={group.id}><h3>{group.id==='hypotheses'?<TriangleAlert size={17}/>:<CheckCheck size={17}/>}<span>{group.title}</span></h3>{group.rows.slice(0,2).map((row,i)=><p key={i}>{row.text}<span>{row.refs.map(ref=>{const source=run?.sources.find(item=>item.key===ref),card=detail.snapshot.cards.find(item=>item.source?.id===source?.evidenceRefId);return <button key={ref} disabled={!card} onClick={()=>card&&focusCard(card)}>{ref}</button>;})}</span></p>)}</section>}/>}
    <button className="pa-record-more" onClick={()=>setRecordOpen(true)}>{t('查看完整记录','View full record')}<Maximize2 size={14}/></button><button className="pa-edit-action" onClick={edit}><ArrowUpRight size={17}/>{t('在后台继续分析','Continue in workbench')}</button>
   </aside>
  </div>:null}
  {relation&&<Modal className="pa-relation-dialog" title={t('资料关系','Evidence relationship')} description={relation.label} onClose={()=>setRelation(null)}><div className="pa-relation-chain">{[relation.from,...relation.via,relation.to].map((card,i)=><span key={card.id}>{i>0&&<ChevronRight size={15}/>}<button onClick={()=>{setRelation(null);focusCard(card);openCard(card);}}>{card.title}</button></span>)}</div>{relation.via.length>0&&<p>{t('经已登记对象关系连接，属于间接关联。','Connected through recorded object relationships; this is an indirect association.')}</p>}{relation.steps.map(step=><section key={step.id}><strong>{step.label}{step.origin==='candidate'?' · '+t('候选','Candidate'):''}</strong><small>{step.from.title} → {step.to.title}</small><p>{step.reason}</p></section>)}{!relation.steps.length&&<p>{relation.reason}</p>}<Btn onClick={()=>{setRelation(null);focusCard(relation.to);setExpanded(relation.to);setAnchor(relation.anchor);}}><ArrowUpRight size={15}/>{t('展开并定位','Open at location')}</Btn></Modal>}
  {expanded&&<Modal className="pa-expanded" title={expanded.title} description={t('固定来源 · 查看','Fixed source · View')} onClose={()=>{setExpanded(null);setAnchor(null);}}>{content(expanded,true)}</Modal>}
  {recordOpen&&detail&&<Modal className="pa-record-dialog" title={t('分析记录与范围','Analysis record and scope')} description={detail.snapshot.title+' · r'+detail.analysisRevision} onClose={()=>setRecordOpen(false)}><p>{candidate?.reason}</p><p>{detail.snapshot.context.timeFrom} — {detail.snapshot.context.timeTo} · {detail.snapshot.context.timezone}</p>{run?.question&&<h3>{run.question}</h3>}{groups.map((group,groupIndex)=><section key={group.id+':'+groupIndex}><h3>{group.title}</h3>{group.rows.map((row,i)=><p key={i}>{row.text}</p>)}</section>)}{!groups.length&&<p>{t('暂无可展示的已保存记录。','No saved record is available to display.')}</p>}<Btn onClick={edit}><ArrowUpRight size={15}/>{t('在后台继续分析','Continue in workbench')}</Btn></Modal>}
  {detail&&<button className="pa-query-launch" aria-expanded={queryOpen} aria-controls="pa-floating-query" onClick={()=>queryOpen?closeQuery():setQueryOpen(true)}><Sparkles size={21}/><span>{t('向助手查询当前故障…','Ask about this fault…')}</span><ArrowUpRight size={17}/></button>}
  {queryOpen&&detail&&<aside id="pa-floating-query" ref={queryPanel} className="pa-query ad-inspector ad-assistant" role="dialog" aria-modal="false" aria-labelledby="pa-query-heading" style={queryPosition?{left:queryPosition.x,top:queryPosition.y,right:'auto',bottom:'auto'}:undefined} onKeyDown={event=>{if(event.key==='Escape'){event.stopPropagation();closeQuery();}}}>
   <header onPointerDown={dragQuery} onPointerMove={moveQuery} onPointerUp={endQueryDrag} onPointerCancel={endQueryDrag}><Sparkles size={19}/><div><h2 id="pa-query-heading">{t('查询助手','Query assistant')}</h2><small>{detail.snapshot.title} · r{detail.analysisRevision}</small></div><IconBtn label={t('关闭查询助手','Close query assistant')} onClick={closeQuery}><X size={16}/></IconBtn></header>
   <div className="pa-query-body"><Suspense fallback={<p role="status">{t('正在打开助手…','Opening assistant…')}</p>}><AssistantPanel queryOnly api={api} cards={detail.snapshot.cards} receipt={detail} en={en} canAddNote={false} canTransfer={false} onFocus={focusCard} onAddNote={ignore}/></Suspense></div><footer className="pa-query-pages"><button aria-label={t('查询内容上翻','Previous query content')} onClick={()=>queryPanel.current?.querySelector('.pa-query-body')?.scrollBy({top:-240,behavior:'smooth'})}><ChevronUp size={15}/></button><button aria-label={t('查询内容下翻','Next query content')} onClick={()=>queryPanel.current?.querySelector('.pa-query-body')?.scrollBy({top:240,behavior:'smooth'})}><ChevronDown size={15}/></button></footer>
  </aside>}
 </section>;
}
function InfoLabel({en}:{en:boolean}){return <><GitBranch size={13}/>{en?'Record & scope':'记录与范围'}<ChevronRight size={12}/></>;}
