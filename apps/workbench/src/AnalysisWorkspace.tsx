import {useEffect,useId,useMemo,useRef,useState,type PointerEvent as ReactPointerEvent} from 'react';
import {GitBranch,Hand,History,LayoutGrid,Maximize,MousePointer2,Pin,Plus,Save,Search,StickyNote,Trash2,Undo2,Redo2,X,ZoomIn,ZoomOut,PanelLeft,PanelRight,Copy,Group,RotateCcw,RefreshCw,Sparkles} from 'lucide-react';
import {Btn,IconBtn,Modal} from './Primitives';
import {addManualRelation,frameBounds,selectedInBox,arrangeCards,fitViewport,moveCard,removeCard,resizeCard,RESIZE_HANDLES,zoomAt,type ResizeHandle,type CanvasSnapshot,type ProjectScope,type RelationKind,type CanvasCard,type CardView} from './analysisCanvas';
import {blankAnalysisDraft,draftChanged,draftProblems,pendingDraft,pendingLifecycle,type AnalysisListItem,type DraftReceipt,type PendingDraft} from './analysisDraftState';
import {RowActions,RowContext,type ListAction} from './ListMenus';
import {AnalysisMaterialPanel} from './AnalysisMaterialPanel';
import {materialPosition,withPrimaryAlarm} from './analysisMaterials';
import {AnalysisSources,ANALYSIS_ROOT,setCardPreviewOpen,type AnalysisEntry,type Recommendation,type Recommendations,type EvidenceSource,type SourceAnchor} from './analysisSources';
import {AnalysisSourceCard,AnalysisTrend,materialNames} from './AnalysisSourceCard';
import {useSourceRelations,SourceRelationLines,SourceRelationDetails,type CardSourceRelation} from './AnalysisSourceRelations';
import type {SimulatedTrend} from './simulatedAlarms';
import './analysisWorkspace.css';
import './analysisMaterials.css';
import {noteSections,readNote,writeNote} from './analysisNotes';
import {applyCanvasAction} from './analysisActions';
import {AssistantPanel} from './AssistantPanel';

export interface DraftApi {revision:string;epoch:number;project:ProjectScope|null;request<T>(path:string,body?:object,signal?:AbortSignal,image?:boolean|'model'|'source'):Promise<T>}
type Detail=DraftReceipt&{snapshot:CanvasSnapshot};
type Listing={items:AnalysisListItem[];total:number;nextCursor:string|null;capabilities:{canWrite:boolean;canManageLifecycle?:boolean}};
type Versions={items:{revision:number;createdAt:string;operation:string}[];nextBeforeRevision:number|null};
const ROOT='/api/workbench/analysis-sessions';
const code=(error:unknown)=>error&&typeof error==='object'&&'code'in error?String(error.code):'';
const status=(error:unknown)=>error&&typeof error==='object'&&'status'in error?Number(error.status):0;
const zhError:Record<string,string>={ANALYSIS_BUSY:'分析读取较忙，请稍后重试；本地修改仍保留。',ANALYSIS_DATABASE_UNAVAILABLE:'分析存储暂时无法连接，请重试；本地修改仍保留。',ANALYSIS_CHANGED:'分析已有新修订。你当前的修改仍保留，可另存副本或重新读取。',
  ANALYSIS_LIST_CHANGED:'列表已更新，请刷新后继续。',ANALYSIS_NOT_ENABLED:'当前环境尚未启用分析画布。',
  ANALYSIS_TRASHED:'画布已移至回收站，恢复后可继续编辑。',ANALYSIS_LIFECYCLE_CHANGED:'画布状态已变化，列表已刷新，请重新选择操作。',
  ANALYSIS_LIFECYCLE_NOT_ENABLED:'当前环境尚未启用画布回收站。',ANALYSIS_LIFECYCLE_LIMIT:'此画布的回收站操作已达到上限。',
  ANALYSIS_WRITE_FORBIDDEN:'当前账号已无保存权限，可查看已有分析。',ANALYSIS_STORE_LIMIT:'分析存储空间已满，请联系管理员。',
  ANALYSIS_REVISION_LIMIT:'此分析已达到修订上限。',ANALYSIS_SOURCE_NOT_CONNECTED:'此资料来源尚未接入，可继续其他分析。',
  ANALYSIS_REVIEW_NOT_CONFIGURED:'当前分析尚未开放结论确认。',ACCESS_CHANGED:'项目权限已变化，请重新打开分析。',
  NOT_FOUND_OR_FORBIDDEN:'分析不存在或当前账号无权查看。',INVALID_REQUEST:'请检查分析名称、内容和时间范围。'};

export function AnalysisWorkspace({api,locale='zh',onDirtyChange,initialEntry,onOpenWorkOrder}:{api:DraftApi;locale?:string;onDirtyChange?:(dirty:boolean)=>void;initialEntry?:AnalysisEntry|null;onOpenWorkOrder?:(code:string)=>void}) {
  const en=locale==='en'; const t=(zh:string,eng:string)=>en?eng:zh;
  const listId=useId();
  const [list,setList]=useState<Listing|null>(null),[query,setQuery]=useState(''),[filter,setFilter]=useState(''),[reload,setReload]=useState(0);
  const [draft,setDraft]=useState<CanvasSnapshot|null>(null),[receipt,setReceipt]=useState<DraftReceipt|null>(null),[saved,setSaved]=useState('');
  const [selected,setSelected]=useState(''),[busy,setBusy]=useState(false),[loading,setLoading]=useState(false),[error,setError]=useState<unknown>(null);
  const [uncertain,setUncertain]=useState(false),[writable,setWritable]=useState(false),[notice,setNotice]=useState('');
  const [tool,setTool]=useState<'pointer'|'hand'>('pointer'),[versions,setVersions]=useState<Versions|null>(null),[preview,setPreview]=useState<Detail|null>(null);
  const [historyOpen,setHistoryOpen]=useState(false),[leave,setLeave]=useState<(()=>void)|null>(null),[linkOpen,setLinkOpen]=useState(false);
  const [target,setTarget]=useState(''),[relationKind,setRelationKind]=useState<RelationKind>('hypothesis'),[reason,setReason]=useState('');
  const [undo,setUndo]=useState<CanvasSnapshot[]>([]);
  const [redo,setRedo]=useState<CanvasSnapshot[]>([]),[multi,setMulti]=useState<string[]>([]);
  const [listVisible,setListVisible]=useState(!initialEntry),[materialsOpen,setMaterialsOpen]=useState(!!initialEntry),[right,setRight]=useState(false),[assistantOpen,setAssistantOpen]=useState(false);
  const [trashView,setTrashView]=useState(false),[deleteTarget,setDeleteTarget]=useState<AnalysisListItem|null>(null),[lifecycleUnknown,setLifecycleUnknown]=useState(false);
  const [lifecycleNotice,setLifecycleNotice]=useState('');
  const lifecyclePending=useRef<{item:AnalysisListItem;action:'trash'|'untrash';task:ReturnType<typeof pendingLifecycle>}|null>(null);
  const [section,setSection]=useState('types'),[recommendations,setRecommendations]=useState<Recommendations|null>(null),[recommendLoading,setRecommendLoading]=useState(false);
  const [related,setRelated]=useState<{entityUid:string;expectedEntityRevision:string}|null>(null),[relatedLabel,setRelatedLabel]=useState(''),[sourceAttempt,setSourceAttempt]=useState(0);
  const [expandedAnchor,setExpandedAnchor]=useState<SourceAnchor|null>(null);
  const [openPreviews,setOpenPreviews]=useState<ReadonlySet<string>>(()=>new Set()),[expanded,setExpanded]=useState('');
  const [compare,setCompare]=useState(false),[trendData,setTrendData]=useState<Record<string,SimulatedTrend>>({}),[linkOrderOpen,setLinkOrderOpen]=useState(false),[orderId,setOrderId]=useState('');
  const [startAttempt,setStartAttempt]=useState(0),[fixed,setFixed]=useState(false),[referenceState,setReferenceState]=useState<Record<string,string>>({});
  const [recommendQuery,setRecommendQuery]=useState(''),[recommendFilter,setRecommendFilter]=useState<string|undefined>(),[chosen,setChosen]=useState<string[]>([]);
  const [frameDialog,setFrameDialog]=useState<{id:string;title:string}|null>(null),[editingRelation,setEditingRelation]=useState('');
  const [compareIds,setCompareIds]=useState<string[]>([]),[trendCursor,setTrendCursor]=useState<number|null>(null);
  const [historyCandidates,setHistoryCandidates]=useState<{analysisSessionId:string;analysisRevision:number;title:string;reason:string;eventId?:string}[]|null>(null);
  const [windowDialog,setWindowDialog]=useState<{from:string;to:string}|null>(null);
  const viewAction=useRef<(id:string,view:CardView)=>void>(()=>{});
  const startId=useRef(crypto.randomUUID());
  const lastCommitted=useRef<DraftReceipt|null>(null);
  const pageAction=useRef<(card:CanvasCard,page:number,value:EvidenceSource)=>void>(()=>{});
  const alive=useRef(true),current=useRef(draft),pending=useRef<PendingDraft|null>(null),request=useRef<AbortController|null>(null);
  const initialLoaded=useRef(false);
  const canvas=useRef<HTMLDivElement>(null),space=useRef(false),wasDragged=useRef(false);
  const heading=useRef<HTMLElement>(null);
  const drag=useRef<{kind:'card'|'pan'|'resize';id?:string;handle?:ResizeHandle;ids?:string[];x:number;y:number;before:CanvasSnapshot}|null>(null);
  const frame=useRef(0),nextFrame=useRef<CanvasSnapshot|null>(null);
  const boxDrag=useRef<{x:number;y:number;append:string[]}|null>(null),[selectionBox,setSelectionBox]=useState<{x:number;y:number;width:number;height:number}|null>(null);
  current.current=draft;
  const dirty=draftChanged(draft,saved,false)||uncertain||lifecycleUnknown;
  const archived=receipt?.lifecycle==='trashed';
  const editable=writable&&!busy&&!uncertain&&!fixed&&!archived&&!lifecycleUnknown;
  const selectedCard=draft?.cards.find(card=>card.id===selected);
  const sources=useMemo(()=>receipt?new AnalysisSources(api,receipt.analysisSessionId):null,[api,receipt?.analysisSessionId,api.epoch,api.revision]);
  useEffect(()=>()=>sources?.dispose(),[sources]);
  useEffect(()=>setOpenPreviews(new Set()),[sources]);
  const previewCardIds=draft?.cards.map(card=>card.id).join('|')||'';
  useEffect(()=>setOpenPreviews(open=>{const ids=new Set(draft?.cards.map(card=>card.id));
    const next=new Set([...open].filter(id=>ids.has(id)));return next.size===open.size?open:next;
  }),[previewCardIds]);
  const sourceRelations=useSourceRelations(sources,draft?.cards||[]);
  const visibleRelations=sourceRelations.relations.filter(link=>[link.from,link.to].every(card=>!referenceState[card.source!.id]||referenceState[card.source!.id]==='available'));
  const analysisEntry=useMemo<AnalysisEntry|null>(()=>draft?(draft.context.datasetId&&draft.context.datasetRevision?{datasetId:draft.context.datasetId,datasetRevision:draft.context.datasetRevision}:{projectOnly:true}):initialEntry&& !('analysisSessionId' in initialEntry)&&!('entityUid' in initialEntry)?initialEntry:null,[draft?.context.datasetId,draft?.context.datasetRevision,!!draft,initialEntry]);
  useEffect(()=>{
    if(!initialEntry)return;const abort=new AbortController();request.current=abort;setBusy(true);setError(null);setMaterialsOpen(true);
    const isFixed='analysisSessionId' in initialEntry;setFixed(isFixed);if(isFixed&&initialEntry.assistantRunId)setAssistantOpen(true);
    void api.request<Detail&{resumed:boolean;historyImported:boolean;missingHistorySources?:unknown[]}>(ROOT+(isFixed?'/detail':'/start'),isFixed?{analysisSessionId:initialEntry.analysisSessionId,analysisRevision:initialEntry.analysisRevision}:{entry:initialEntry,requestId:startId.current},abort.signal)
      .then(value=>{if(!abort.signal.aborted){adopt(value);setNotice(isFixed?t('工单关联版本 · 只读查看','Linked revision · read only'):value.historyImported?t('已调入历史参考，本次记录独立保存','History loaded; current investigation is independent'):value.resumed?t('已继续本次分析','Resumed analysis'):'');}})
      .catch(value=>{if(!abort.signal.aborted)failure(value);}).finally(()=>{if(!abort.signal.aborted)setBusy(false);});
    return()=>abort.abort();
  },[initialEntry,api,startAttempt]);
  useEffect(()=>{
    if(!materialsOpen||!analysisEntry||section==='types'){setRecommendations(null);setRecommendLoading(false);return;}const abort=new AbortController();setRecommendLoading(true);setRecommendations(null);
    setChosen([]);
    void api.request<Recommendations>(ROOT+'/recommendations',{entry:analysisEntry,section,...(recommendFilter!==undefined&&['objects','models','documents','orders','alarms','trends'].includes(section)?{q:recommendFilter}:{}),...(['materials','drawings','photos','models'].includes(section)&&related?related:{})},abort.signal)
      .then(value=>{if(!abort.signal.aborted)setRecommendations(value);}).catch(value=>{if(!abort.signal.aborted)failure(value);}).finally(()=>{if(!abort.signal.aborted)setRecommendLoading(false);});
    return()=>abort.abort();
  },[analysisEntry,materialsOpen,section,related,sourceAttempt,recommendFilter,api]);
  useEffect(()=>{onDirtyChange?.(dirty);return()=>onDirtyChange?.(false);},[dirty,onDirtyChange]);
  useEffect(()=>{const warn=(event:BeforeUnloadEvent)=>{if(dirty){event.preventDefault();event.returnValue='';}};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn);},[dirty]);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;request.current?.abort();cancelAnimationFrame(frame.current);};},[]);
  function failure(value:unknown){
    if(!alive.current||value instanceof Error&&value.name==='AbortError')return;
    setError(value);setNotice('');
    if(code(value)==='ANALYSIS_WRITE_FORBIDDEN')setWritable(false);
    else if([401,403].includes(status(value))){setDraft(null);setReceipt(null);setList(null);setSaved('');setSelected('');setPreview(null);setVersions(null);pending.current=null;setUncertain(false);}
  }
  useEffect(()=>{
    const abort=new AbortController();setLoading(true);setError(null);
    void api.request<Listing>(ROOT,{q:filter,limit:25,lifecycle:trashView?'trashed':'active'},abort.signal).then(value=>{if(!abort.signal.aborted){setList(value);setWritable(value.capabilities.canWrite);if(!initialLoaded.current){initialLoaded.current=true;if(!initialEntry&&!trashView&&value.items[0])void open(value.items[0].analysisSessionId);}}})
      .catch(value=>{if(!abort.signal.aborted)failure(value);}).finally(()=>{if(!abort.signal.aborted)setLoading(false);});
    return()=>abort.abort();
  },[api,api.revision,api.epoch,filter,reload,trashView]);
  useEffect(()=>{
    const node=canvas.current;if(!node)return;
    const wheel=(event:WheelEvent)=>{if((event.target as Element).closest('.ac-material-panel'))return;event.preventDefault();event.stopPropagation();const value=current.current;if(!value||busy||uncertain)return;
      const rect=node.getBoundingClientRect(),delta=event.deltaY*(event.deltaMode===1?16:event.deltaMode===2?node.clientHeight:1);setDraft({...value,viewport:zoomAt(value.viewport,value.viewport.zoom*Math.exp(-delta*.0015),event.clientX-rect.left,event.clientY-rect.top)});};
    node.addEventListener('wheel',wheel,{passive:false,capture:true});return()=>node.removeEventListener('wheel',wheel,true);
  },[!!draft,busy,uncertain]);
  function apply(value:CanvasSnapshot,remember=true){if(!editable)return;if(remember&&draft){setUndo(items=>[...items.slice(-19),draft]);setRedo([]);}setDraft(value);setNotice('');}
  function adopt(value:Detail){setDraft(value.snapshot);setReceipt(value);setSaved(JSON.stringify(value.snapshot));setSelected(value.snapshot.cards[0]?.id||'');setUndo([]);setRedo([]);setMulti([]);setExpanded('');setError(null);setNotice('');setLifecycleNotice('');setUncertain(false);pending.current=null;}
  function change(action:()=>void){if(dirty)setLeave(()=>action);else action();}
  async function open(id:string){
    setFixed(false);
    request.current?.abort();const abort=new AbortController();request.current=abort;setBusy(true);setError(null);
    try {const value=await api.request<Detail>(ROOT+'/detail',{analysisSessionId:id},abort.signal);if(alive.current&&!abort.signal.aborted)adopt(value);}
    catch(value){if(!abort.signal.aborted)failure(value);}finally{if(alive.current&&!abort.signal.aborted)setBusy(false);}
  }
  function fresh(){if(!api.project)return;setFixed(false);setDraft({...blankAnalysisDraft(api.project),schemaVersion:2});setReceipt(null);setSaved('');setSelected('');setUndo([]);setRedo([]);setError(null);setNotice('');pending.current=null;setUncertain(false);}
  async function commit(copy=false,restore?:Detail):Promise<boolean>{
    if(busy||!draft||!api.project||!writable||fixed||archived||lifecycleUnknown)return false;
    let task=pending.current;
    if(!uncertain){
      const value=restore?.snapshot??(copy?{...draft,title:draft.title.slice(0,110)+t(' · 副本',' · Copy')}:draft);
      const problems=draftProblems(value,api.project);if(problems.length){setError(new Error(en?'Please check the analysis content.':problems[0]));return false;}
      task=copy&&receipt?{path:ROOT+'/copy',body:{analysisSessionId:receipt.analysisSessionId,requestId:crypto.randomUUID(),snapshot:structuredClone(value)},snapshot:structuredClone(value)}:pendingDraft(value,copy?null:receipt,crypto.randomUUID(),restore?.analysisRevision);pending.current=task;
    }
    if(!task)return false;
    const abort=new AbortController();request.current=abort;setBusy(true);setError(null);
    try{
      const result=await api.request<DraftReceipt&{snapshot?:CanvasSnapshot}>(task.path,task.body,abort.signal);
      if(!alive.current||abort.signal.aborted)return false;
      lastCommitted.current=result;adopt({...result,snapshot:result.snapshot||task.snapshot});setNotice(t('已保存','Saved'));setReload(value=>value+1);setPreview(null);setHistoryOpen(false);return true;
    }catch(value){
      if(alive.current&&!abort.signal.aborted){const unknown=status(value)===0||status(value)>=500;setUncertain(unknown);if(!unknown)pending.current=null;failure(value);}
      return false;
    }finally{if(alive.current&&!abort.signal.aborted)setBusy(false);}
  }
  async function more(){if(!list?.nextCursor||loading)return;setLoading(true);const abort=new AbortController();request.current=abort;
    try{const next=await api.request<Listing>(ROOT,{q:filter,limit:25,cursor:list.nextCursor,lifecycle:trashView?'trashed':'active'},abort.signal);if(alive.current&&!abort.signal.aborted)setList({...next,items:[...list.items,...next.items]});}
    catch(value){failure(value);}finally{if(alive.current&&!abort.signal.aborted)setLoading(false);}}
  async function manageLifecycle(item?:AnalysisListItem,action?:'trash'|'untrash'){
    if(busy)return;
    if(!lifecyclePending.current&&item&&action)lifecyclePending.current={item,action,task:pendingLifecycle(item,action,crypto.randomUUID())};
    const operation=lifecyclePending.current;if(!operation)return;
    const abort=new AbortController();request.current=abort;setBusy(true);setError(null);
    try{
      const result=await api.request<{lifecycle:'active'|'trashed';lifecycleRevision:number}>(operation.task.path,operation.task.body,abort.signal);
      if(!alive.current||abort.signal.aborted)return;
      lifecyclePending.current=null;setLifecycleUnknown(false);setDeleteTarget(null);setReload(v=>v+1);
      setLifecycleNotice(operation.action==='trash'?t('画布已移至回收站','Canvas moved to recycle bin'):t('画布已恢复','Canvas restored'));
      if(receipt?.analysisSessionId===operation.item.analysisSessionId){
        if(result.lifecycle==='trashed'){
          setDraft(null);setReceipt(null);setSaved('');setSelected('');setExpanded('');setPreview(null);setVersions(null);
          setUndo([]);setRedo([]);setMulti([]);pending.current=null;setUncertain(false);setMaterialsOpen(false);setRight(false);setListVisible(true);
        }else setReceipt(value=>value?{...value,lifecycle:result.lifecycle,lifecycleRevision:result.lifecycleRevision}:value);
      }
    }catch(value){if(alive.current&&!abort.signal.aborted){
      const unknown=status(value)===0||status(value)>=500;setLifecycleUnknown(unknown);
      if(!unknown){lifecyclePending.current=null;setDeleteTarget(null);setReload(v=>v+1);}failure(value);
    }}finally{if(alive.current&&!abort.signal.aborted)setBusy(false);}
  }
  function listActions(item:AnalysisListItem):ListAction[]{
    const disabled=busy||uncertain||lifecycleUnknown;
    return [{id:'open',label:item.lifecycle==='trashed'?t('查看画布','View canvas'):t('打开画布','Open canvas'),icon:<LayoutGrid/>,disabled,
      onSelect:()=>change(()=>void open(item.analysisSessionId))},
      {id:trashView?'untrash':'trash',label:trashView?t('恢复画布','Restore canvas'):t('移至回收站','Move to recycle bin'),
        icon:trashView?<RotateCcw/>:<Trash2/>,disabled:disabled||!list?.capabilities.canManageLifecycle,danger:!trashView,opensDialog:!trashView,
        onSelect:()=>trashView?void manageLifecycle(item,'untrash'):setDeleteTarget(item)}];
  }
  async function history(before?:number){if(!receipt)return;const abort=new AbortController();request.current=abort;setHistoryOpen(true);setBusy(true);setError(null);
    try{const value=await api.request<Versions>(ROOT+'/revisions',{analysisSessionId:receipt.analysisSessionId,limit:25,...(before?{before}:{})},abort.signal);if(alive.current&&!abort.signal.aborted)setVersions(previous=>before&&previous?{...value,items:[...previous.items,...value.items]}:value);}
    catch(value){failure(value);}finally{if(alive.current&&!abort.signal.aborted)setBusy(false);}}
  async function viewRevision(revision:number){if(!receipt)return;const abort=new AbortController();request.current=abort;setBusy(true);
    try{const value=await api.request<Detail>(ROOT+'/detail',{analysisSessionId:receipt.analysisSessionId,analysisRevision:revision},abort.signal);if(alive.current&&!abort.signal.aborted)setPreview(value);}
    catch(value){failure(value);}finally{if(alive.current&&!abort.signal.aborted)setBusy(false);}}
  function addNote(){if(!draft||draft.cards.length>=50)return;const id=crypto.randomUUID();apply({...draft,cards:[...draft.cards,{id,kind:'analysis',title:t('分析笔记','Analysis note'),note:'',x:32+(draft.cards.length%3)*340,y:40+Math.floor(draft.cards.length/3)*240,width:300,height:200,pinned:false}]});setSelected(id);}
  function focusCard(card:CanvasCard){setSelected(card.id);setMulti([card.id]);if(current.current&&canvas.current)setDraft({...current.current,viewport:{...current.current.viewport,x:canvas.current.clientWidth/2-(card.x+card.width/2)*current.current.viewport.zoom,y:canvas.current.clientHeight/2-(card.y+card.height/2)*current.current.viewport.zoom}});}
  async function moreRecommendations(){if(!recommendations||!analysisEntry||recommendLoading)return;setRecommendLoading(true);
    try{const value=await api.request<Recommendations>(ROOT+'/recommendations',{entry:analysisEntry,section,...(recommendations.nextCursor?{cursor:recommendations.nextCursor}:{offset:recommendations.nextOffset}),...(recommendFilter!==undefined&&['objects','documents','models','orders','alarms','trends'].includes(section)?{q:recommendFilter}:{}),...(['materials','drawings','photos','models'].includes(section)&&related?related:{})});
      setRecommendations({...value,items:[...recommendations.items,...value.items.filter(i=>!recommendations.items.some(old=>old.key===i.key))]});}
    catch(value){failure(value);}finally{setRecommendLoading(false);}}
  async function addSource(item:Recommendation,replaceId?:string,position?:{x:number;y:number}){return addSources([item],replaceId,position);}
  async function addSources(items:Recommendation[],replaceId?:string,position?:{x:number;y:number}){
    const snapshot=current.current;if(!snapshot||!editable)return;let version=receipt;
    if(!version){if(!await commit()||!lastCommitted.current)return;version=lastCommitted.current;}
    const abort=new AbortController();request.current=abort;setBusy(true);setError(null);let next=snapshot;let added=0;let addedId='';const failed:string[]=[];
    try{const references=new Map<string,{evidenceRefId:string;sourceRevision:string}>();
      for(let start=0;start<items.length;start+=12){const result=await api.request<{items:{key:string;reference?:{evidenceRefId:string;sourceRevision:string};error?:string}[]}>(ROOT+'/evidence/register-batch',{
        analysisSessionId:version.analysisSessionId,expectedAnalysisRevision:version.analysisRevision,
        items:items.slice(start,start+12).map(item=>({key:item.key,requestId:crypto.randomUUID(),sourceKind:item.kind,selector:item.selector}))},abort.signal);
        result.items.forEach(item=>{if(item.reference)references.set(item.key,item.reference);});}
      for(const item of items){if(!replaceId&&next.cards.length>=50)break;
      try{const ref=references.get(item.key);if(!ref){failed.push(item.title);continue;}
        if(!alive.current||abort.signal.aborted)return;const kind=item.kind==='model'?'model3d':item.kind;
        const existing=next.cards.find(c=>!c.historical&&c.kind===kind&&c.source?.revision===ref.sourceRevision);
        if(existing&&!replaceId){addedId=existing.id;if(['photo','drawing','document','model'].includes(item.kind))setOpenPreviews(open=>setCardPreviewOpen(open,existing.id,true));if(items.length===1)focusCard(existing);continue;}
        const id=replaceId||crypto.randomUUID(),height=['photo','drawing','document','model'].includes(item.kind)?360:250;
        const board=canvas.current,panel=materialsOpen?Math.min(380,(board?.clientWidth||0)/2):0;
        const point=position||materialPosition(next.viewport,{x:panel+((board?.clientWidth||800)-panel)/2-170*next.viewport.zoom,y:(board?.clientHeight||600)/2-height/2*next.viewport.zoom});
        const card:CanvasCard={id,kind,title:item.title,x:Math.min(20000,point.x+added*28),y:Math.min(20000,point.y+added*28),width:340,height,pinned:false,
          source:{...api.project!,system:['object','drawing','document','photo'].includes(item.kind)?'ontobase':'ontovis',id:ref.evidenceRefId,revision:ref.sourceRevision}};
        next={...next,schemaVersion:2,cards:replaceId?next.cards.map(old=>old.id===id?{...old,source:card.source}:old):[...next.cards,card]};if(!replaceId)next=withPrimaryAlarm(next,item);added++;addedId=id;setSelected(id);setMulti([id]);
        if(['photo','drawing','document','model'].includes(item.kind))setOpenPreviews(open=>setCardPreviewOpen(open,id,true));
      }catch(value){if([401,403].includes(status(value))||abort.signal.aborted)throw value;failed.push(item.title);}}
      if(added)apply(next);setChosen([]);setNotice(failed.length?t(`已加入${added}项；${failed.length}项未加入，可重试`,`Added ${added}; ${failed.length} failed`):added?t(`已加入${added}项资料`,`Added ${added} materials`):t('资料已在画布中','Material already on canvas'));return addedId;
    }catch(value){failure(value);}finally{if(alive.current&&!abort.signal.aborted)setBusy(false);}
  }
  async function loadRelatedHistory(){if(!analysisEntry)return;setBusy(true);setError(null);const abort=new AbortController();request.current=abort;
    try{const value=await api.request<{items:NonNullable<typeof historyCandidates>}>(ROOT+'/history-candidates',{entry:analysisEntry},abort.signal);
      if(!abort.signal.aborted)setHistoryCandidates(value.items.filter(item=>item.analysisSessionId!==receipt?.analysisSessionId));}
    catch(value){failure(value);}finally{if(!abort.signal.aborted)setBusy(false);}}
  async function importHistory(item:NonNullable<typeof historyCandidates>[number]){if(!receipt||!draft||!editable)return;
    setBusy(true);setError(null);const abort=new AbortController();request.current=abort;
    try{const value=await api.request<{snapshot:CanvasSnapshot}>(ROOT+'/import-history',{analysisSessionId:receipt.analysisSessionId,expectedAnalysisRevision:receipt.analysisRevision,
      snapshot:draft,historySessionId:item.analysisSessionId,historyRevision:item.analysisRevision,requestId:crypto.randomUUID()},abort.signal);
      if(!abort.signal.aborted){apply(value.snapshot);setHistoryCandidates(null);setNotice(t('历史参考已载入；保存后记录本次选择','History loaded. Save to record your selection'));}}
    catch(value){failure(value);}finally{if(!abort.signal.aborted)setBusy(false);}}
  function chooseRelated(value:EvidenceSource){if(!value.item)return;setRelatedLabel(value.item.displayName||t('所选对象','Selected object'));setRelated({entityUid:value.item.entityUid,expectedEntityRevision:value.item.entityRevision});setSection('materials');setMaterialsOpen(true);setRight(false);}
  function changePage(card:CanvasCard,page:number,value:EvidenceSource){if(!value.documentId||!value.contentVersionId||!value.sourceSha256)return;
    void addSource({key:card.id,kind:'document',title:card.title,reason:'指定文档页',selector:{documentId:value.documentId,contentVersionId:value.contentVersionId,sourceSha256:value.sourceSha256,pageNumber:page}},card.id);}
  pageAction.current=changePage;
  viewAction.current=(id,view)=>{const value=current.current;if(!editable||!value)return;
    setDraft({...value,cards:value.cards.map(card=>card.id===id?{...card,view}:card)});};
  async function changeWindow(){
    if(!windowDialog||!draft||!receipt||!editable)return;
    const next=applyCanvasAction(draft,{kind:'set-window',...windowDialog},draft);
    const targets=draft.cards.filter(card=>card.kind==='trend'&&!card.historical);
    if(targets.some(card=>!trendData[card.id])){setError(new Error(t('先读取当前趋势，再调整时间窗','Read the current trends before changing the window')));return;}
    const abort=new AbortController();request.current=abort;setBusy(true);setError(null);
    try{const replacements=new Map<string,CanvasCard['source']>();
      for(const card of targets){const source=trendData[card.id];const result=await api.request<{evidenceRefId:string;sourceRevision:string}>(ROOT+'/evidence/register',{
        analysisSessionId:receipt.analysisSessionId,expectedAnalysisRevision:receipt.analysisRevision,requestId:crypto.randomUUID(),sourceKind:'trend',
        selector:{datasetId:source.dataset?.datasetId,datasetRevision:source.dataset?.datasetRevision,metricId:source.metricId,timeFrom:windowDialog.from,timeTo:windowDialog.to}},abort.signal);
        replacements.set(card.id,{...card.source!,id:result.evidenceRefId,revision:result.sourceRevision});}
      if(!abort.signal.aborted){apply({...next,cards:next.cards.map(card=>replacements.has(card.id)?{...card,source:replacements.get(card.id)}:card)});setWindowDialog(null);setTrendCursor(null);}
    }catch(value){failure(value);}finally{if(!abort.signal.aborted)setBusy(false);}
  }
  function copyView(card:CanvasCard){if(!draft||draft.cards.length>=50)return;const id=crypto.randomUUID();
    apply({...draft,cards:[...draft.cards,{...card,id,x:card.x+48,y:card.y+48,pinned:false}]});setSelected(id);}

  function pin(card:CanvasCard){if(draft)apply({...draft,cards:draft.cards.map(c=>c.id===card.id?{...c,pinned:!c.pinned}:c)});}
  function remove(card:CanvasCard){if(draft){apply(removeCard(draft,card.id));setSelected('');setMulti(ids=>ids.filter(id=>id!==card.id));}}
  function copyNote(card:CanvasCard){if(!draft||draft.cards.length>=50)return;const id=crypto.randomUUID();apply({...draft,cards:[...draft.cards,{...card,id,title:t('本次记录 · ','Current note · ')+card.title.slice(0,100),x:card.x+40,y:card.y+40,historical:false,pinned:false,frameId:undefined,checkState:'not_started'}]});setSelected(id);setRight(true);}
  function makeFrame(){if(!draft||multi.length<2||(draft.frames?.length||0)>=10)return;const cards=draft.cards.filter(c=>multi.includes(c.id)),id=crypto.randomUUID();
    const x=Math.min(...cards.map(c=>c.x))-20,y=Math.min(...cards.map(c=>c.y))-38;
    apply({...draft,schemaVersion:2,cards:draft.cards.map(c=>multi.includes(c.id)?{...c,frameId:id}:c),frames:[...(draft.frames||[]),{id,title:t('资料分组','Material group'),x,y,width:Math.max(...cards.map(c=>c.x+c.width))-x+20,height:Math.max(...cards.map(c=>c.y+c.height))-y+20}]});}
  async function saveAndLink(){
    if(!draft||!receipt||!orderId.trim())return;let version=receipt;
    if(dirty){const ok=await commit();if(!ok||!lastCommitted.current)return;version=lastCommitted.current;}
    setBusy(true);try{const order=await api.request<{orderId:string;orderRevision:number}>('/api/workbench/work-orders/detail',{orderId:orderId.trim()});
      await api.request(ROOT+'/link-work-order',{analysisSessionId:version.analysisSessionId,analysisRevision:version.analysisRevision,orderId:order.orderId,expectedOrderRevision:order.orderRevision,requestId:crypto.randomUUID()});
      setLinkOrderOpen(false);setNotice(t('分析已保存并关联工单','Analysis saved and linked'));}
    catch(value){failure(value);setNotice(t('分析已保存；工单关联未完成，可重试','Analysis saved; linking is incomplete. Retry.'));}finally{setBusy(false);}
  }
  function pointerDown(event:ReactPointerEvent,id?:string,handle?:ResizeHandle){
    if(!draft||![0,1].includes(event.button)||busy||uncertain||(event.target as Element).closest('.ac-material-panel'))return;
    // Portaled context menus bubble through the card in React, but are not a drag surface.
    if(!event.currentTarget.contains(event.target as Node))return;
    if(event.button===1||!handle&&(tool==='hand'||space.current)){
      event.preventDefault();event.stopPropagation();wasDragged.current=false;
      canvas.current?.setPointerCapture(event.pointerId);
      drag.current={kind:'pan',x:event.clientX,y:event.clientY,before:draft};return;
    }
    if((event.target as HTMLElement).closest('.ac-source-link'))return;
    if(!handle&&(event.target as HTMLElement).closest('button:not(.ac-card-title),input,select,textarea,[data-canvas-inner]'))return;
    wasDragged.current=false;
    let ids=id?(multi.includes(id)?multi:[id]):[];
    if(id){setSelected(id);if(event.shiftKey&&!handle)ids=multi.includes(id)?multi:[...multi,id];setMulti(ids);if(tool==='hand'||space.current||!editable)return;const card=draft.cards.find(value=>value.id===id);if(!card||card.pinned)return;event.stopPropagation();}
    else if(tool!=='hand'&&!space.current){if(event.target===event.currentTarget||!(event.target as HTMLElement).closest('article,[data-frame-id]')){
      const bounds=event.currentTarget.getBoundingClientRect();boxDrag.current={x:(event.clientX-bounds.left-draft.viewport.x)/draft.viewport.zoom,y:(event.clientY-bounds.top-draft.viewport.y)/draft.viewport.zoom,append:event.shiftKey?multi:[]};
      event.currentTarget.setPointerCapture(event.pointerId);setSelected('');if(!event.shiftKey)setMulti([]);event.preventDefault();}return;}
    event.preventDefault();if(handle||!id)event.currentTarget.setPointerCapture(event.pointerId);drag.current={kind:handle?'resize':id?'card':'pan',id,ids,handle,x:event.clientX,y:event.clientY,before:draft};
  }
  function pointerMove(event:ReactPointerEvent){
    if(boxDrag.current&&draft&&canvas.current){const bounds=canvas.current.getBoundingClientRect(),start=boxDrag.current,
      x=(event.clientX-bounds.left-draft.viewport.x)/draft.viewport.zoom,y=(event.clientY-bounds.top-draft.viewport.y)/draft.viewport.zoom;
      const box={x:Math.min(x,start.x),y:Math.min(y,start.y),width:Math.abs(x-start.x),height:Math.abs(y-start.y)};
      setSelectionBox(box);setMulti([...new Set([...start.append,...selectedInBox(draft,box)])]);return;}
    const moving=drag.current;if(!moving)return;const dx=event.clientX-moving.x,dy=event.clientY-moving.y;
    if(!wasDragged.current){if(Math.abs(dx)+Math.abs(dy)<=3)return;wasDragged.current=true;if(moving.kind==='card')canvas.current?.setPointerCapture(event.pointerId);if(moving.id){setUndo(values=>[...values.slice(-19),moving.before]);setRedo([]);}}
    let value=moving.before;
    if(moving.kind==='pan')value={...value,viewport:{...value.viewport,x:Math.max(-50000,Math.min(50000,value.viewport.x+dx)),y:Math.max(-50000,Math.min(50000,value.viewport.y+dy))}};
    else if(moving.kind==='resize')value=resizeCard(value,moving.id!,moving.handle!,dx/value.viewport.zoom,dy/value.viewport.zoom,event.shiftKey);
    else for(const id of moving.ids||[]){const card=moving.before.cards.find(c=>c.id===id);if(card)value=moveCard(value,id,card.x+dx/moving.before.viewport.zoom,card.y+dy/moving.before.viewport.zoom);}
    nextFrame.current=value;if(!frame.current)frame.current=requestAnimationFrame(()=>{frame.current=0;if(nextFrame.current){setDraft(frameBounds(nextFrame.current));nextFrame.current=null;}});
  }
  function finishGesture(){boxDrag.current=null;setSelectionBox(null);drag.current=null;cancelAnimationFrame(frame.current);frame.current=0;if(nextFrame.current){setDraft(frameBounds(nextFrame.current));nextFrame.current=null;}}
  function fit(){if(draft&&canvas.current)setDraft({...draft,viewport:fitViewport(draft.cards,canvas.current.clientWidth,canvas.current.clientHeight)});}
  function zoom(factor:number){if(draft&&canvas.current)setDraft({...draft,viewport:zoomAt(draft.viewport,draft.viewport.zoom*factor,canvas.current.clientWidth/2,canvas.current.clientHeight/2)});}
  function undoChange(reverse=false){if(!draft||!editable)return;const stack=reverse?redo:undo;if(!stack.length)return;
    (reverse?setUndo:setRedo)(items=>[...items.slice(-19),draft]);setDraft(stack[stack.length-1]);(reverse?setRedo:setUndo)(items=>items.slice(0,-1));}
  function label(card:CanvasCard){return card.kind==='analysis'||referenceState[card.source!.id]==='available'?card.title:referenceState[card.source!.id]==='restricted'?t('资料访问已撤销','Access removed'):materialNames[card.kind]+t(' · 待读取',' · pending');}
  const errorText=error instanceof Error&&!code(error)?error.message:en?'The request could not be completed. Your local edits are retained.':zhError[code(error)]||'暂时无法完成请求，请重试。';
  const statuses=[['analyzing','分析中','Analyzing'],['awaiting_field_check','待现场核查','Awaiting field check'],['awaiting_expert_review','待复核','Awaiting review']];
  const expandedCard=draft?.cards.find(c=>c.id===expanded);
  function openSource(card:CanvasCard,anchor?:SourceAnchor|null){
    const relation=sourceRelations.relations.find(link=>link.to.id===card.id&&link.anchor);
    setExpandedAnchor(anchor??relation?.anchor??null);setExpanded(card.id);
  }
  function openRelation(link:CardSourceRelation){setSelected(link.to.id);openSource(link.to,link.anchor);}
  async function addAndOpen(item:Recommendation){const id=await addSource(item);if(id){setExpandedAnchor(null);setExpanded(id);}}
  const sourceContent=(card:CanvasCard,full=false)=>sources&&<AnalysisSourceCard key={card.id+(full?':full':':inline')} card={card} sources={sources} en={en} full={full} anchor={full?expandedAnchor:null} onAddMaterial={editable?item=>void addAndOpen(item):undefined} onUpdateWorkOrder={editable&&card.kind==='work_order'?async item=>{const loaded=await addSources([item],card.id);if(loaded)setNotice(t('已载入工单进展，保存为新修订后可继续分析。','Order progress loaded. Save a new revision to continue analysis.'));return !!loaded;}:undefined} active={full||openPreviews.has(card.id)}
    onActivate={()=>setOpenPreviews(open=>setCardPreviewOpen(open,card.id,true))} onDeactivate={()=>setOpenPreviews(open=>setCardPreviewOpen(open,card.id,false))} onOpen={()=>openSource(card)} onRelated={chooseRelated} onPage={(page,value)=>pageAction.current(card,page,value)}
    onAvailability={(id,state)=>setReferenceState(previous=>previous[id]===state?previous:{...previous,[id]:state})}
    onView={view=>viewAction.current(card.id,view)} cursor={card.historical?undefined:trendCursor} onCursor={card.historical?undefined:setTrendCursor}
    onTrend={(id,value)=>setTrendData(previous=>previous[id]===value?previous:{...previous,[id]:value})}/>;
  return <section className={`ad-workspace${draft?' ad-has-draft':''}${right||assistantOpen?' ac-right-open':''}`} aria-label={t('分析工作空间','Analysis workspace')}>
    {listVisible&&<aside id={listId} className="ad-list" aria-label={t('画布列表','Canvas list')}><header><strong>{trashView?t('回收站','Recycle bin'):t('画布列表','Canvas list')}</strong><span>{list?.total??'—'}</span><IconBtn label={t('隐藏画布列表','Hide canvas list')} onClick={()=>{setListVisible(false);heading.current?.querySelector<HTMLButtonElement>('.ad-list-toggle')?.focus();}}><X size={14}/></IconBtn></header>
      <div className="ad-list-tools"><Btn aria-pressed={trashView} onClick={()=>{setTrashView(v=>!v);setQuery('');setFilter('');setList(null);}}><Trash2 size={14}/>{trashView?t('正常画布','Active canvases'):t('回收站','Recycle bin')}</Btn><IconBtn label={t('刷新画布列表','Refresh canvas list')} disabled={loading} onClick={()=>setReload(v=>v+1)}><RefreshCw size={14}/></IconBtn></div>
      <form className="ad-search" onSubmit={event=>{event.preventDefault();setFilter(query);}}><Search size={14}/><input aria-label={t('搜索画布','Search canvases')} placeholder={t('搜索名称','Search titles')} value={query} onChange={event=>setQuery(event.target.value)}/><button>{t('搜索','Search')}</button></form>
      <Btn primary disabled={!writable||busy||uncertain||lifecycleUnknown} onClick={()=>change(()=>{fresh();setTrashView(false);})}><Plus size={14}/>{t('新建分析','New analysis')}</Btn>
      <ul className="ad-list-items ov-list" aria-label={trashView?t('画布回收站','Canvas recycle bin'):t('画布列表','Canvas list')}>{list?.items.map(item=>{const actions=listActions(item);return <RowContext key={item.analysisSessionId} name={item.title} disabled={busy||lifecycleUnknown} actions={actions}><li className={`ov-list-item${receipt?.analysisSessionId===item.analysisSessionId?' selected':''}`}><button type="button" className="ov-list-main" disabled={busy||lifecycleUnknown} aria-current={receipt?.analysisSessionId===item.analysisSessionId?'page':undefined} onClick={()=>change(()=>void open(item.analysisSessionId))}><span className="ov-list-copy"><strong>{item.title}</strong><small>{t(statuses.find(s=>s[0]===item.status)?.[1]||'分析中',statuses.find(s=>s[0]===item.status)?.[2]||'Analyzing')} · r{item.analysisRevision}</small><time>{new Date(item.updatedAt).toLocaleString(en?'en-GB':'zh-CN')}</time></span></button><RowActions name={item.title} actions={actions} locale={locale} disabled={busy||lifecycleUnknown}/></li></RowContext>;})}
        {!loading&&list&&!list.total&&<li><p>{trashView?t('回收站为空','Recycle bin is empty'):t('还没有分析','No analyses yet')}</p></li>}{loading&&<li><p role="status">{t('正在读取…','Loading…')}</p></li>}
        {list?.nextCursor&&<li><Btn disabled={loading} onClick={()=>void more()}>{t('加载更多','Load more')}</Btn></li>}</ul>
      <footer>{t('仅本人可见','Private to you')}</footer>
    </aside>}
    <div className="ad-editor">
      <header ref={heading} className="ad-heading"><Btn className="ad-list-toggle" title={listVisible?t('隐藏画布列表','Hide canvas list'):t('显示画布列表','Show canvas list')} aria-expanded={listVisible} aria-controls={listId} onClick={()=>setListVisible(v=>!v)}><PanelLeft size={16}/>{t('画布列表','Canvas list')}</Btn>{draft&&<>
          <input aria-label={t('分析名称','Analysis title')} maxLength={120} value={draft.title} disabled={!editable} onChange={event=>apply({...draft,title:event.target.value})}/>
          <select aria-label={t('分析进度','Analysis progress')} value={draft.status} disabled={!editable} onChange={event=>apply({...draft,status:event.target.value as CanvasSnapshot['status']})}>{statuses.map(([value,zh,eng])=><option key={value} value={value}>{t(zh,eng)}</option>)}</select>
          <small aria-live="polite">{busy?t('处理中…','Working…'):dirty?t('未保存','Unsaved'):notice||t('已保存','Saved')}{receipt?' · r'+receipt.analysisRevision:''}</small>
          <IconBtn label={t('修订历史','Revision history')} disabled={!receipt||busy||uncertain} onClick={()=>void history()}><History size={17}/></IconBtn>
          <Btn primary disabled={!writable||busy||fixed||archived||lifecycleUnknown||!dirty} onClick={()=>void commit()}><Save size={14}/>{uncertain?t('重试保存','Retry save'):t('保存','Save')}</Btn>
        </>}</header>
      {!!error&&<div className="ad-alert" role="alert"><span>{errorText}</span>{!draft&&<Btn onClick={()=>initialEntry?setStartAttempt(v=>v+1):setReload(v=>v+1)}>{t('重试','Retry')}</Btn>}
        {code(error)==='ANALYSIS_CHANGED'&&<><Btn disabled={busy} onClick={()=>void commit(true)}>{t('另存副本','Save a copy')}</Btn><Btn disabled={busy} onClick={()=>change(()=>receipt&&void open(receipt.analysisSessionId))}>{t('重新读取','Reload saved')}</Btn></>}
      </div>}
      {uncertain&&<div className="ad-alert" role="status">{t('保存结果尚未确认。重试会使用同一请求，避免重复创建。','Save result is unknown. Retry reuses the same request.')}</div>}
      {lifecycleUnknown&&<div className="ad-alert" role="status">{t('回收站操作结果尚未确认，重试会复用同一请求。','Recycle-bin result is unknown. Retry reuses the same request.')}<Btn disabled={busy} onClick={()=>void manageLifecycle()}>{t('重试回收站操作','Retry recycle-bin operation')}</Btn></div>}
      {lifecycleNotice&&<div className="ad-alert" role="status">{lifecycleNotice}</div>}
      {draft?<>

        {fixed&&receipt&&<div className="ad-alert" role="status">{t('正在查看工单关联的固定版本','Viewing the linked fixed revision')} · r{receipt.analysisRevision}<Btn onClick={()=>void open(receipt.analysisSessionId)}>{t('继续最新分析','Continue latest analysis')}</Btn></div>}
        {archived&&<div className="ad-alert" role="status">{t('画布已在回收站中，当前为只读查看。','This canvas is in the recycle bin and is read only.')}<Btn disabled={!list?.capabilities.canManageLifecycle||busy||lifecycleUnknown} onClick={()=>receipt&&void manageLifecycle({analysisSessionId:receipt.analysisSessionId,analysisRevision:receipt.headRevision??receipt.analysisRevision,lifecycleRevision:receipt.lifecycleRevision,title:draft.title,status:draft.status,updatedAt:''},'untrash')}>{t('恢复画布','Restore canvas')}</Btn></div>}
        <div className="ad-tools"><Btn className="ac-add-materials" aria-pressed={materialsOpen} onClick={()=>{setMaterialsOpen(v=>!v);setSection('types');setRecommendFilter(undefined);setRecommendQuery('');setRight(false);}}><Plus size={16}/>{t('加入资料','Add materials')}</Btn>
          <IconBtn label={t('选择工具','Select tool')} aria-pressed={tool==='pointer'} onClick={()=>setTool('pointer')}><MousePointer2 size={16}/></IconBtn><IconBtn label={t('平移工具','Pan tool')} aria-pressed={tool==='hand'} onClick={()=>setTool('hand')}><Hand size={16}/></IconBtn>
          <IconBtn label={t('撤销修改','Undo change')} disabled={!undo.length||!editable} onClick={()=>undoChange()}><Undo2 size={16}/></IconBtn>
          <IconBtn label={t('重做修改','Redo change')} disabled={!redo.length||!editable} onClick={()=>undoChange(true)}><Redo2 size={16}/></IconBtn>
          <Btn disabled={!editable||!draft.cards.length} onClick={()=>apply(applyCanvasAction(draft,{kind:'arrange'},draft))}><LayoutGrid size={14}/>{t('整理布局','Arrange')}</Btn>
          <IconBtn label={t('将所选卡片分组','Group selected cards')} disabled={!editable||multi.length<2} onClick={makeFrame}><Group size={16}/></IconBtn>
          <Btn disabled={!draft.context.faultCode||busy||fixed} onClick={()=>void loadRelatedHistory()}>{t('同码历史','Same-code history')}</Btn>
          <Btn disabled={!editable} onClick={()=>setWindowDialog({from:draft.context.timeFrom,to:draft.context.timeTo})}>{t('时间范围','Time window')}</Btn>
          <Btn disabled={draft.cards.filter(c=>c.kind==='trend'&&trendData[c.id]).length<2} onClick={()=>{setCompareIds(draft.cards.filter(c=>c.kind==='trend'&&trendData[c.id]).slice(0,4).map(c=>c.id));setCompare(true);}}>{t('趋势对比','Compare trends')}</Btn>
          <Btn disabled={!receipt||busy||!writable||fixed||archived||lifecycleUnknown} onClick={()=>{setOrderId(draft.context.workOrderId||'');setLinkOrderOpen(true);}}>{t('保存并关联工单','Save & link')}</Btn>
          <Btn aria-pressed={assistantOpen} onClick={()=>{setAssistantOpen(v=>!v);setRight(false);}}><Sparkles size={15}/>{t('分析助手','Assistant')}</Btn>
          <IconBtn label={t('查看详情','Show details')} aria-pressed={right} onClick={()=>{setRight(v=>!v);setAssistantOpen(false);setMaterialsOpen(false);}}><PanelRight size={16}/></IconBtn>
        </div>
        <div className="ad-canvas-row"><div ref={canvas} className={`ad-canvas ad-tool-${tool}`} tabIndex={0} aria-label={t('分析画布','Analysis canvas')}
          onKeyDown={event=>{if((event.target as HTMLElement).closest('input,textarea,select,[data-canvas-inner]'))return;if(event.key==='Escape'){setSelected('');setMulti([]);setExpanded('');setLinkOpen(false);}else if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='z'){event.preventDefault();undoChange(event.shiftKey);}else if(event.code==='Space'){space.current=true;event.preventDefault();}}} onKeyUp={event=>{if(event.code==='Space')space.current=false;}} onBlur={()=>{space.current=false;drag.current=null;}}
          onDragOver={event=>{if(event.dataTransfer.types.includes('application/x-ontovis-recommendation')){event.preventDefault();event.dataTransfer.dropEffect='copy';}}} onDrop={event=>{event.preventDefault();if((event.target as Element).closest('.ac-material-panel'))return;const item=recommendations?.items.find(item=>item.key===event.dataTransfer.getData('application/x-ontovis-recommendation'));if(item){const rect=event.currentTarget.getBoundingClientRect();void addSource(item,undefined,materialPosition(draft.viewport,{x:event.clientX-rect.left,y:event.clientY-rect.top}));}}}
          onPointerDownCapture={event=>{if(event.button===1||event.button===0&&(tool==='hand'||space.current))pointerDown(event);}}
          onAuxClick={event=>{if(event.button===1)event.preventDefault();}}
          onPointerDown={event=>pointerDown(event)} onPointerMove={pointerMove} onPointerUp={finishGesture} onPointerCancel={finishGesture} onLostPointerCapture={finishGesture}>
          {materialsOpen&&<AnalysisMaterialPanel section={section} query={recommendQuery} en={en} loading={recommendLoading} value={recommendations} chosen={chosen} editable={editable} canAdd={editable&&draft.cards.length<50}
            contextLabel={[draft.context.faultCode?t('当前报警 '+draft.context.faultCode,'Current alarm '+draft.context.faultCode):'',related?relatedLabel:''].filter(Boolean).join(' · ')} onClose={()=>setMaterialsOpen(false)}
            onSection={value=>{setSection(value);setRecommendFilter(undefined);setRecommendQuery('');setChosen([]);}} onQuery={setRecommendQuery} onSearch={()=>{if(section!=='types')setRecommendFilter(recommendQuery);}}
            onToggle={key=>setChosen(keys=>keys.includes(key)?keys.filter(value=>value!==key):[...keys,key])} onAdd={item=>void addSource(item)} onAddChosen={()=>void addSources(recommendations!.items.filter(item=>chosen.includes(item.key)))}
            onNote={addNote} onMore={()=>void moreRecommendations()} onRefresh={()=>setSourceAttempt(v=>v+1)}/>}
          <div className="ad-world" style={{transform:`translate(${draft.viewport.x}px,${draft.viewport.y}px) scale(${draft.viewport.zoom})`}}>
            {selectionBox&&<div className="ac-selection-box" style={{left:selectionBox.x,top:selectionBox.y,width:selectionBox.width,height:selectionBox.height}}/>}
            {draft.frames?.map(group=><div className="ac-frame" key={group.id} style={{left:group.x,top:group.y,width:group.width,height:group.height}}><button type="button" data-frame-id={group.id} disabled={!editable} onClick={()=>setFrameDialog({id:group.id,title:group.title})}>{group.title}</button></div>)}
            <svg className="ad-links" aria-label={t('资料关系','Source relationships')}><defs><marker id="ad-source-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8" fill="none" stroke="currentColor"/></marker><marker id="ad-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8" fill="none" stroke="currentColor"/></marker></defs><SourceRelationLines relations={visibleRelations} onOpen={openRelation}/>{draft.relations.map(link=>{const a=draft.cards.find(c=>c.id===link.from),b=draft.cards.find(c=>c.id===link.to);if(!a||!b||[a,b].some(c=>c.source&&referenceState[c.source.id]!=='available'))return null;const x=a.x+a.width,y=a.y+a.height/2,x2=b.x,y2=b.y+b.height/2;return <path key={link.id} d={`M${x},${y} C${x+60},${y} ${x2-60},${y2} ${x2},${y2}`} markerEnd="url(#ad-arrow)"/>;})}</svg>
            {draft.cards.map(card=>{const actions=[{id:'open',label:t('展开查看','Expand'),icon:<Maximize/>,onSelect:()=>card.kind==='analysis'?(setSelected(card.id),setRight(true),setMaterialsOpen(false)):openSource(card)},
              {id:'pin',label:card.pinned?t('取消固定','Unpin'):t('固定','Pin'),icon:<Pin/>,disabled:!editable,onSelect:()=>pin(card)},
              ...(card.kind!=='analysis'?[{id:'copy-view',label:t('复制视图','Copy view'),icon:<Copy/>,disabled:!editable||draft.cards.length>=50,onSelect:()=>copyView(card)}]:[]),
              ...(card.kind==='analysis'?[{id:'copy',label:t('复制为本次记录','Copy as current note'),icon:<Copy/>,disabled:!editable,onSelect:()=>copyNote(card)}]:[]),
              {id:'remove',label:t('从画布移除','Remove from canvas'),icon:<Trash2/>,disabled:!editable,onSelect:()=>remove(card)}];
              const inView=canvas.current?card.x*draft.viewport.zoom+draft.viewport.x+card.width*draft.viewport.zoom>-300&&card.x*draft.viewport.zoom+draft.viewport.x<canvas.current.clientWidth+300&&card.y*draft.viewport.zoom+draft.viewport.y+card.height*draft.viewport.zoom>-300&&card.y*draft.viewport.zoom+draft.viewport.y<canvas.current.clientHeight+300:true;
              return <RowContext key={card.id} name={label(card)} actions={actions}><article className={`ad-card${selected===card.id||multi.includes(card.id)?' selected':''}${card.historical?' ac-historical':''}`} data-card-id={card.id} data-card-kind={card.kind} style={{left:card.x,top:card.y,width:card.width,height:card.height}}
                onClick={event=>{setSelected(card.id);if(event.shiftKey)setMulti(ids=>ids.includes(card.id)?ids:[...ids,card.id]);}}
                onDoubleClick={()=>{setSelected(card.id);setRight(true);setMaterialsOpen(false);}}>
                <header onPointerDown={event=>pointerDown(event,card.id)}><span className="ac-kind">{materialNames[card.kind]}</span><button type="button" className="ac-card-title" onClick={()=>{if(wasDragged.current){wasDragged.current=false;return;}card.kind==='analysis'?(setSelected(card.id),setRight(true),setMaterialsOpen(false)):openSource(card);}}>{label(card)}</button>{card.pinned&&<Pin size={13}/>}<RowActions name={label(card)} actions={actions} locale={locale}/></header>
                <div className="ac-card-body" data-canvas-inner>{card.kind==='analysis'?<><span className="ad-badge">{card.historical?t('历史记录 · 只读内容','Historical note · read only'):t('人工分析','Analysis note')}</span><p>{card.note||t('双击卡片编辑笔记','Double-click to edit')}</p>{card.checkState&&<small>{({not_started:'未执行',checking:'排查中',done:'已记录结果',blocked:'待补充依据'})[card.checkState]}</small>}</>:inView?sourceContent(card):<p>{t('移入视野后读取资料','Loads when visible')}</p>}</div>
                {editable&&!card.pinned&&RESIZE_HANDLES.map(handle=><button key={handle} type="button" className={`ac-resize ac-resize-${handle}`} aria-label={`${t('调整大小','Resize')} ${label(card)} ${handle}`} onPointerDown={event=>pointerDown(event,card.id,handle)}/>)}
              </article></RowContext>;
            })}
          </div>
          {!draft.cards.length&&<div className="ad-empty"><StickyNote size={28}/><strong>{t('从报警、资料或分析笔记开始','Start with an alarm, material or note')}</strong><p>{t('加入报警后，按当前事件推荐相关对象与资料','An alarm provides related objects and materials')}</p><Btn primary onClick={()=>{setMaterialsOpen(true);setSection('types');setRecommendQuery('');setRecommendFilter(undefined);setRight(false);}}>{t('加入资料','Add materials')}</Btn></div>}
          {sourceRelations.relations.some(link=>link.origin==='candidate')&&<small className="ac-relation-legend">{t('虚线：候选或人工引用','Dashed: candidates or manual references')}</small>}
          <div className="ad-zoom"><IconBtn label={t('缩小画布','Zoom out canvas')} disabled={busy||uncertain} onClick={()=>zoom(1/1.2)}><ZoomOut size={15}/></IconBtn><button type="button" aria-label={t('画布100%','Canvas 100%')} onClick={()=>zoom(1/draft.viewport.zoom)}>{Math.round(draft.viewport.zoom*100)}%</button><IconBtn label={t('放大画布','Zoom in canvas')} disabled={busy||uncertain} onClick={()=>zoom(1.2)}><ZoomIn size={15}/></IconBtn><IconBtn label={t('适应全部','Fit all')} disabled={busy||uncertain} onClick={fit}><Maximize size={15}/></IconBtn></div>
          <Btn className="ac-save-view" disabled={!editable||!receipt} onClick={()=>void commit()}>{t('保存当前视图','Save current view')}</Btn>
          <span className="ad-hint">{t('中键拖动平移 · 滚轮缩放画布 · 拖标题移动 · 拖边角调整大小','Middle drag to pan · Wheel to zoom canvas · Drag title to move · Edges to resize')}</span>
        </div>
        {assistantOpen&&<aside className="ad-inspector ad-assistant"><header><strong>{t('分析助手','Analysis assistant')}</strong><IconBtn label={t('关闭助手','Close assistant')} onClick={()=>setAssistantOpen(false)}><X size={16}/></IconBtn></header><AssistantPanel api={api} canTransfer={editable&&!dirty} preferredOrderId={draft.context.workOrderId} faultCode={draft.context.faultCode} onOpenOrder={onOpenWorkOrder} initialRunId={initialEntry&&'analysisSessionId' in initialEntry?initialEntry.assistantRunId:undefined} cards={draft.cards} receipt={receipt} en={en} canAddNote={editable&&draft.cards.length<50} onFocus={focusCard} onAddNote={text=>{if(!editable||draft.cards.length>=50)return;const id=crypto.randomUUID();apply({...draft,cards:[...draft.cards,{id,kind:'analysis',title:t('助手整理 · 待人工核验','Assistant note · requires verification'),note:text,x:40+(draft.cards.length%3)*340,y:40+Math.floor(draft.cards.length/3)*240,width:340,height:300,pinned:false}]});setSelected(id);}}/></aside>}
        {right&&<aside className="ad-inspector"><header><strong>{t(selectedCard?'卡片详情':'分析范围',selectedCard?'Card details':'Analysis context')}</strong><IconBtn label={t('关闭详情','Close details')} onClick={()=>setRight(false)}><X size={16}/></IconBtn></header>{selectedCard?<>
          <label>{t('卡片名称','Card title')}<input maxLength={120} disabled={!editable||selectedCard.historical||!!selectedCard.source&&referenceState[selectedCard.source.id]!=='available'} value={label(selectedCard)} onChange={event=>apply({...draft,cards:draft.cards.map(card=>card.id===selected?{...card,title:event.target.value}:card)})}/></label>
          {selectedCard.kind==='analysis'?<>{noteSections.map(([key,eng])=><label key={key}>{t(key,eng)}<textarea className="ac-note-section" maxLength={4000} disabled={!editable||selectedCard.historical} value={readNote(selectedCard.note||'')[key]} onChange={event=>{const note=writeNote({...readNote(selectedCard.note||''),[key]:event.target.value});if(note.length<=4000)apply({...draft,cards:draft.cards.map(card=>card.id===selected?{...card,note}:card)});}}/></label>)}<small>{(selectedCard.note||'').length} / 4000</small>
            <label>{t('检查进度','Check status')}<select disabled={!editable||selectedCard.historical} value={selectedCard.checkState||'not_started'} onChange={event=>apply({...draft,schemaVersion:2,cards:draft.cards.map(card=>card.id===selected?{...card,checkState:event.target.value as CanvasCard['checkState']}:card)})}>{[['not_started','未执行'],['checking','排查中'],['done','已记录结果'],['blocked','待补充依据']].map(([id,name])=><option key={id} value={id}>{name}</option>)}</select></label>
            {selectedCard.historical&&<Btn onClick={()=>copyNote(selectedCard)}>{t('复制为本次记录','Copy to current investigation')}</Btn>}</>:<><p>{materialNames[selectedCard.kind]} · {selectedCard.historical?t('历史参考','Historical reference'):t('固定资料版本','Fixed source')}</p><Btn onClick={()=>openSource(selectedCard)}>{t('展开查看资料','Expand source')}</Btn>{selectedCard.source&&referenceState[selectedCard.source.id]==='available'&&<p className="ov-mono">{selectedCard.source.revision.slice(0,12)}</p>}</>}
          <div className="ad-inline"><Btn disabled={!editable} onClick={()=>apply({...draft,cards:draft.cards.map(card=>card.id===selected?{...card,pinned:!card.pinned}:card)})}><Pin size={14}/>{selectedCard.pinned?t('取消固定','Unpin'):t('固定卡片','Pin card')}</Btn><IconBtn disabled={!editable} label={t('移除笔记','Remove note')} onClick={()=>{apply(removeCard(draft,selected));setSelected('');}}><Trash2 size={15}/></IconBtn></div>
          {selectedCard.kind==='analysis'&&<p>{t('人工笔记不代表已确认的工程事实。','Notes do not constitute confirmed engineering facts.')}</p>}
          <SourceRelationDetails selected={selectedCard} {...sourceRelations} relations={visibleRelations} onOpen={openRelation} en={en}/>
          <div className="ad-inline"><strong>{t('分析关系','Analysis relationships')}</strong><IconBtn label={t('添加关系','Add relationship')} disabled={!editable||draft.cards.length<2} onClick={()=>{setTarget(draft.cards.find(card=>card.id!==selected)?.id||'');setReason('');setEditingRelation('');setLinkOpen(true);}}><Plus size={15}/></IconBtn></div>
          {draft.relations.filter(link=>(link.from===selected||link.to===selected)&&[link.from,link.to].every(id=>{const c=draft.cards.find(c=>c.id===id);return c&&!c.source||c?.source&&referenceState[c.source.id]==='available';})).map(link=><div className="ad-relation" key={link.id}><GitBranch size={13}/><div><strong>{label(draft.cards.find(card=>card.id===(link.from===selected?link.to:link.from))!)}</strong><p>{link.reason}</p><Btn disabled={!editable} onClick={()=>{setEditingRelation(link.id);setSelected(link.from);setTarget(link.to);setRelationKind(link.kind);setReason(link.reason);setLinkOpen(true);}}>{t('编辑关系','Edit relation')}</Btn><Btn onClick={()=>focusCard(draft.cards.find(c=>c.id===(link.from===selected?link.to:link.from))!)}>{t('定位资料','Focus material')}</Btn></div><IconBtn label={t('移除关系','Remove relationship')} disabled={!editable} onClick={()=>apply({...draft,relations:draft.relations.filter(item=>item.id!==link.id)})}><X size={13}/></IconBtn></div>)}
        </>:<><p>{t('当前项目','Current project')}<strong>{api.project?.projectCode}</strong></p><p>{draft.context.timeFrom}<br/>{draft.context.timeTo}</p><Btn disabled={!editable} onClick={()=>setWindowDialog({from:draft.context.timeFrom,to:draft.context.timeTo})}>{t('调整分析时间范围','Change time window')}</Btn></>}</aside>}</div>
      </>:<div className="ad-empty"><GitBranch size={32}/><h2>{busy?t('正在准备本次分析…','Preparing analysis…'):t('整理你的分析思路','Organize your investigation')}</h2><p>{t('新建或继续一项分析，保留笔记、人工关系与修订历史。','Create or continue an analysis with notes, relationships and version history.')}</p><Btn primary disabled={!writable||busy} onClick={fresh}><Plus size={14}/>{t('新建分析','New analysis')}</Btn></div>}
    </div>
    {historyCandidates&&<Modal title={t('同码历史分析','Analyses with the same fault code')} description={t('仅列出本人当前可读的分析；加载为独立历史参考，可撤销','Readable owned analyses only; imports a separate, undoable reference')} onClose={()=>!busy&&setHistoryCandidates(null)}>{!historyCandidates.length&&<p>{t('尚无其他可复用分析','No other analyses to reuse')}</p>}{historyCandidates.map(item=><div className="ac-history-candidate" key={item.analysisSessionId}><strong>{item.title} · r{item.analysisRevision}</strong><p>{item.reason}</p><Btn disabled={busy||!editable} onClick={()=>void importHistory(item)}>{t('载入参考','Load reference')}</Btn></div>)}</Modal>}
    {windowDialog&&<Modal title={t('分析时间范围','Analysis time window')} description={t('当前趋势同步更新，历史参考保留原时间窗；输入UTC时间','Current trends update together; historical windows stay fixed. Enter UTC times.')} onClose={()=>!busy&&setWindowDialog(null)}><label>{t('开始时间','From')}<input aria-label={t('时间窗开始','Time window from')} value={windowDialog.from} onChange={event=>setWindowDialog({...windowDialog,from:event.target.value})}/></label><label>{t('结束时间','To')}<input aria-label={t('时间窗结束','Time window to')} value={windowDialog.to} onChange={event=>setWindowDialog({...windowDialog,to:event.target.value})}/></label><Btn primary disabled={busy||!Number.isFinite(Date.parse(windowDialog.from))||!Number.isFinite(Date.parse(windowDialog.to))||Date.parse(windowDialog.from)>=Date.parse(windowDialog.to)} onClick={()=>void changeWindow().catch(failure)}>{t('应用时间范围','Apply window')}</Btn></Modal>}
    {frameDialog&&draft&&<Modal title={t('资料分区','Material group')} description={t('分区只组织布局，不改变工程关系','Groups organize layout only')} onClose={()=>setFrameDialog(null)}><input aria-label={t('分区名称','Group name')} maxLength={120} value={frameDialog.title} onChange={event=>setFrameDialog({...frameDialog,title:event.target.value})}/><Btn primary disabled={!frameDialog.title.trim()} onClick={()=>{apply({...draft,frames:draft.frames?.map(f=>f.id===frameDialog.id?{...f,title:frameDialog.title.trim()}:f)});setFrameDialog(null);}}>{t('保存名称','Save name')}</Btn><Btn onClick={()=>{apply({...draft,cards:draft.cards.map(c=>{if(c.frameId!==frameDialog.id)return c;const {frameId,...rest}=c;return rest;}),frames:draft.frames?.filter(f=>f.id!==frameDialog.id)});setFrameDialog(null);}}>{t('解除分区','Ungroup')}</Btn><Btn onClick={()=>{const ids=new Set(draft.cards.filter(c=>c.frameId===frameDialog.id).map(c=>c.id));apply({...draft,cards:draft.cards.filter(c=>!ids.has(c.id)),relations:draft.relations.filter(r=>!ids.has(r.from)&&!ids.has(r.to)),frames:draft.frames?.filter(f=>f.id!==frameDialog.id)});setFrameDialog(null);}}>{t('移除整组资料','Remove group and cards')}</Btn></Modal>}
    {expandedCard&&sources&&<Modal className="ac-source-modal" title={label(expandedCard)} description={t('固定来源资料；浏览操作不改变源文件','Fixed source; viewing does not change the original')} onClose={()=>{setExpanded('');setExpandedAnchor(null);}}><div className="ac-expanded">{sourceContent(expandedCard,true)}</div></Modal>}
    {compare&&draft&&<Modal className="ac-compare-modal" title={t('趋势对比','Trend comparison')} description={t('最多四条曲线，按窗口起点对齐；不同单位分开显示','Up to four trends; separate axes for different units')} onClose={()=>setCompare(false)}><div className="ac-compare-choice">{draft.cards.filter(c=>c.kind==='trend'&&trendData[c.id]).map(c=><label key={c.id}><input type="checkbox" checked={compareIds.includes(c.id)} disabled={!compareIds.includes(c.id)&&compareIds.length>=4} onChange={event=>setCompareIds(ids=>event.target.checked?[...ids,c.id]:ids.filter(id=>id!==c.id))}/>{label(c)} · {trendData[c.id].unit}</label>)}</div><div className="ac-comparison">{[...new Set(compareIds.map(id=>trendData[id]?.unit).filter(Boolean))].map(unit=><AnalysisTrend key={unit} en={en} cursor={trendCursor} onCursor={setTrendCursor} trends={compareIds.map(id=>trendData[id]).filter(row=>row?.unit===unit)}/>)}</div></Modal>}
    {linkOrderOpen&&<Modal title={t('保存并关联工单','Save and link work order')} description={t('工单记录所保存的明确修订，不改变处理状态','Links a fixed analysis revision without changing work-order state')} onClose={()=>!busy&&setLinkOrderOpen(false)}><label>{t('工单编号','Work order ID')}<input aria-label={t('关联工单编号','Linked work order ID')} value={orderId} onChange={event=>setOrderId(event.target.value)}/></label><Btn primary disabled={busy||!orderId.trim()} onClick={()=>void saveAndLink()}>{t('保存并关联','Save and link')}</Btn>{draft?.context.faultCode&&onOpenWorkOrder&&<Btn disabled={busy||dirty} onClick={()=>onOpenWorkOrder(draft.context.faultCode!)}>{t('查看相关工单','View related orders')}</Btn>}</Modal>}
    {deleteTarget&&<Modal title={t('移至回收站','Move to recycle bin')} description={deleteTarget.title} onClose={()=>{if(!busy)setDeleteTarget(null);}}><p>{t('画布将从正常列表移除，可以在回收站恢复。原有修订、资料引用和工单关联会保留。','The canvas leaves the active list and can be restored. Revisions, source references and work-order links are retained.')}</p>{receipt?.analysisSessionId===deleteTarget.analysisSessionId&&dirty&&<p>{t('当前未保存的修改不会保存。','Current unsaved changes will not be saved.')}</p>}<div className="ad-inline"><Btn disabled={busy} onClick={()=>setDeleteTarget(null)}>{t('取消','Cancel')}</Btn><Btn primary disabled={busy||uncertain} onClick={()=>void manageLifecycle(deleteTarget,'trash')}>{busy?t('处理中…','Working…'):lifecycleUnknown?t('重试移至回收站','Retry move'):t('移至回收站','Move to recycle bin')}</Btn></div></Modal>}
    {leave&&<Modal title={t('修改尚未保存','Unsaved changes')} description={t('离开前处理当前修改','Handle changes before leaving')} onClose={()=>setLeave(null)}><p>{uncertain?t('保存结果尚未确认，建议先重试。','Save result is unknown; retry first.'):t('离开将放弃当前未保存的修改。','Leaving discards unsaved edits.')}</p><div className="ad-inline"><Btn onClick={()=>setLeave(null)}>{t('继续编辑','Keep editing')}</Btn><Btn disabled={busy} onClick={()=>{const action=leave;setLeave(null);pending.current=null;setUncertain(false);action();}}>{t('放弃修改并离开','Discard and leave')}</Btn><Btn primary disabled={!writable||busy} onClick={()=>void commit().then(ok=>{if(ok){setLeave(null);leave();}})}>{t('保存并继续','Save and continue')}</Btn></div></Modal>}
    {historyOpen&&<Modal title={t('修订历史','Revision history')} description={t('历史只读，恢复将追加新修订','History is immutable; restoring adds a revision')} onClose={()=>{if(!busy){setHistoryOpen(false);setPreview(null);}}}><div className="ad-history">{versions?.items.map(item=><Btn key={item.revision} disabled={busy} onClick={()=>void viewRevision(item.revision)}>r{item.revision} · {new Date(item.createdAt).toLocaleString(en?'en-GB':'zh-CN')}</Btn>)}{versions?.nextBeforeRevision&&<Btn disabled={busy} onClick={()=>void history(versions.nextBeforeRevision!)}>{t('更早修订','Earlier revisions')}</Btn>}</div>{preview&&<><h3>{preview.snapshot.title} · r{preview.analysisRevision}</h3>{preview.snapshot.cards.map(card=><div key={card.id}><strong>{label(card)}</strong><p className="ad-history-note">{card.note}</p></div>)}<Btn primary disabled={!writable||busy||dirty||preview.analysisRevision===(receipt?.headRevision??receipt?.analysisRevision)} onClick={()=>void commit(false,preview)}>{t('恢复为新修订','Restore as a new revision')}</Btn>{dirty&&<p>{t('先保存或放弃当前修改，再恢复历史。','Save or discard your edits before restoring.')}</p>}</>}</Modal>}
    {linkOpen&&draft&&<Modal title={t('添加人工关系','Add manual relationship')} description={t('记录资料或笔记之间的依据','Record evidence connecting materials or notes')} onClose={()=>setLinkOpen(false)}><form className="ad-link-form" onSubmit={event=>{event.preventDefault();try{apply(addManualRelation({...draft,relations:draft.relations.filter(r=>r.id!==editingRelation)},{id:editingRelation||crypto.randomUUID(),from:selected,to:target,kind:relationKind,origin:'manual',reason}));setLinkOpen(false);}catch(value){failure(value);}}}><label>{t('关联卡片','Related card')}<select value={target} onChange={event=>setTarget(event.target.value)}>{draft.cards.filter(card=>card.id!==selected).map(card=><option key={card.id} value={card.id}>{label(card)}</option>)}</select></label><label>{t('关系类型','Relation type')}<select value={relationKind} onChange={event=>setRelationKind(event.target.value as RelationKind)}>{[['reference','资料引用','Reference'],['hypothesis','原因假设','Hypothesis'],['supports','支持依据','Supports'],['contradicts','反证','Contradicts']].map(([key,zh,eng])=><option key={key} value={key}>{t(zh,eng)}</option>)}</select></label><label>{t('关系依据','Reason')}<textarea maxLength={1000} required value={reason} onChange={event=>setReason(event.target.value)}/></label><button type="submit" className="ov-btn primary">{t('添加关系','Add relationship')}</button></form></Modal>}
  </section>;
}
