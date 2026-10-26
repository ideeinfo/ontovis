import {useEffect,useRef,useState,type PointerEvent as ReactPointerEvent} from 'react';
import {ArrowLeft,GitBranch,Hand,History,LayoutGrid,Maximize,MousePointer2,Pin,Plus,Save,Search,StickyNote,Trash2,Undo2,X,ZoomIn,ZoomOut} from 'lucide-react';
import {Btn,IconBtn,Modal} from './Primitives';
import {addManualRelation,arrangeCards,fitViewport,moveCard,removeCard,zoomAt,type CanvasSnapshot,type ProjectScope,type RelationKind} from './analysisCanvas';
import {blankAnalysisDraft,draftChanged,draftProblems,pendingDraft,type DraftReceipt,type PendingDraft} from './analysisDraftState';
import {RowContext} from './ListMenus';
import './analysisWorkspace.css';

export interface DraftApi {revision:string;epoch:number;project:ProjectScope|null;request<T>(path:string,body?:object,signal?:AbortSignal):Promise<T>}
type Detail=DraftReceipt&{snapshot:CanvasSnapshot};
type Item={analysisSessionId:string;title:string;status:string;analysisRevision:number;updatedAt:string};
type Listing={items:Item[];total:number;nextCursor:string|null;capabilities:{canWrite:boolean}};
type Versions={items:{revision:number;createdAt:string;operation:string}[];nextBeforeRevision:number|null};
const ROOT='/api/workbench/analysis-sessions';
const code=(error:unknown)=>error&&typeof error==='object'&&'code'in error?String(error.code):'';
const status=(error:unknown)=>error&&typeof error==='object'&&'status'in error?Number(error.status):0;
const zhError:Record<string,string>={ANALYSIS_CHANGED:'分析已有新修订。你当前的修改仍保留，可另存副本或重新读取。',
  ANALYSIS_LIST_CHANGED:'列表已更新，请刷新后继续。',ANALYSIS_NOT_ENABLED:'当前环境尚未启用分析画布。',
  ANALYSIS_WRITE_FORBIDDEN:'当前账号已无保存权限，可查看已有分析。',ANALYSIS_STORE_LIMIT:'分析存储空间已满，请联系管理员。',
  ANALYSIS_REVISION_LIMIT:'此分析已达到修订上限。',ANALYSIS_SOURCE_NOT_CONNECTED:'当前只支持人工分析笔记。',
  ANALYSIS_REVIEW_NOT_CONFIGURED:'当前分析尚未开放结论确认。',ACCESS_CHANGED:'项目权限已变化，请重新打开分析。',
  NOT_FOUND_OR_FORBIDDEN:'分析不存在或当前账号无权查看。',INVALID_REQUEST:'请检查分析名称、内容和时间范围。'};

export function AnalysisWorkspace({api,locale='zh',onDirtyChange}:{api:DraftApi;locale?:string;onDirtyChange?:(dirty:boolean)=>void}) {
  const en=locale==='en'; const t=(zh:string,eng:string)=>en?eng:zh;
  const [list,setList]=useState<Listing|null>(null),[query,setQuery]=useState(''),[filter,setFilter]=useState(''),[reload,setReload]=useState(0);
  const [draft,setDraft]=useState<CanvasSnapshot|null>(null),[receipt,setReceipt]=useState<DraftReceipt|null>(null),[saved,setSaved]=useState('');
  const [selected,setSelected]=useState(''),[busy,setBusy]=useState(false),[loading,setLoading]=useState(false),[error,setError]=useState<unknown>(null);
  const [uncertain,setUncertain]=useState(false),[writable,setWritable]=useState(false),[notice,setNotice]=useState('');
  const [tool,setTool]=useState<'pointer'|'hand'>('pointer'),[versions,setVersions]=useState<Versions|null>(null),[preview,setPreview]=useState<Detail|null>(null);
  const [historyOpen,setHistoryOpen]=useState(false),[leave,setLeave]=useState<(()=>void)|null>(null),[linkOpen,setLinkOpen]=useState(false);
  const [target,setTarget]=useState(''),[relationKind,setRelationKind]=useState<RelationKind>('hypothesis'),[reason,setReason]=useState('');
  const [undo,setUndo]=useState<CanvasSnapshot[]>([]);
  const alive=useRef(true),current=useRef(draft),pending=useRef<PendingDraft|null>(null),request=useRef<AbortController|null>(null);
  const initialLoaded=useRef(false);
  const canvas=useRef<HTMLDivElement>(null),space=useRef(false);
  const drag=useRef<{kind:'card'|'pan';id?:string;x:number;y:number;before:CanvasSnapshot}|null>(null);
  current.current=draft;
  const dirty=draftChanged(draft,saved,writable)||uncertain;
  const editable=writable&&!busy&&!uncertain;
  const selectedCard=draft?.cards.find(card=>card.id===selected);
  useEffect(()=>{onDirtyChange?.(dirty);return()=>onDirtyChange?.(false);},[dirty,onDirtyChange]);
  useEffect(()=>{const warn=(event:BeforeUnloadEvent)=>{if(dirty){event.preventDefault();event.returnValue='';}};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn);},[dirty]);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;request.current?.abort();};},[]);
  function failure(value:unknown){
    if(!alive.current||value instanceof Error&&value.name==='AbortError')return;
    setError(value);setNotice('');
    if(code(value)==='ANALYSIS_WRITE_FORBIDDEN')setWritable(false);
    else if([401,403].includes(status(value))){setDraft(null);setReceipt(null);setList(null);setSaved('');setSelected('');setPreview(null);setVersions(null);pending.current=null;setUncertain(false);}
  }
  useEffect(()=>{
    const abort=new AbortController();setLoading(true);setError(null);
    void api.request<Listing>(ROOT,{q:filter,limit:25},abort.signal).then(value=>{if(!abort.signal.aborted){setList(value);setWritable(value.capabilities.canWrite);if(!initialLoaded.current){initialLoaded.current=true;if(value.items[0])void open(value.items[0].analysisSessionId);}}})
      .catch(value=>{if(!abort.signal.aborted)failure(value);}).finally(()=>{if(!abort.signal.aborted)setLoading(false);});
    return()=>abort.abort();
  },[api,api.revision,api.epoch,filter,reload]);
  useEffect(()=>{
    const node=canvas.current;if(!node)return;
    const wheel=(event:WheelEvent)=>{event.preventDefault();const value=current.current;if(!value||busy||uncertain)return;
      const rect=node.getBoundingClientRect();setDraft({...value,viewport:zoomAt(value.viewport,value.viewport.zoom*Math.exp(-event.deltaY*.0015),event.clientX-rect.left,event.clientY-rect.top)});};
    node.addEventListener('wheel',wheel,{passive:false});return()=>node.removeEventListener('wheel',wheel);
  },[!!draft,busy,uncertain]);
  function apply(value:CanvasSnapshot,remember=true){if(!editable)return;if(remember&&draft)setUndo(items=>[...items.slice(-19),draft]);setDraft(value);setNotice('');}
  function adopt(value:Detail){setDraft(value.snapshot);setReceipt(value);setSaved(JSON.stringify(value.snapshot));setSelected(value.snapshot.cards[0]?.id||'');setUndo([]);setError(null);setUncertain(false);pending.current=null;}
  function change(action:()=>void){if(dirty)setLeave(()=>action);else action();}
  async function open(id:string){
    request.current?.abort();const abort=new AbortController();request.current=abort;setBusy(true);setError(null);
    try {const value=await api.request<Detail>(ROOT+'/detail',{analysisSessionId:id},abort.signal);if(alive.current&&!abort.signal.aborted)adopt(value);}
    catch(value){if(!abort.signal.aborted)failure(value);}finally{if(alive.current&&!abort.signal.aborted)setBusy(false);}
  }
  function fresh(){if(!api.project)return;setDraft(blankAnalysisDraft(api.project));setReceipt(null);setSaved('');setSelected('');setUndo([]);setError(null);setNotice('');pending.current=null;setUncertain(false);}
  async function commit(copy=false,restore?:Detail):Promise<boolean>{
    if(busy||!draft||!api.project||!writable)return false;
    let task=pending.current;
    if(!uncertain){
      const value=restore?.snapshot??(copy?{...draft,title:draft.title.slice(0,110)+t(' · 副本',' · Copy')}:draft);
      const problems=draftProblems(value,api.project);if(problems.length){setError(new Error(en?'Please check the analysis content.':problems[0]));return false;}
      task=pendingDraft(value,copy?null:receipt,crypto.randomUUID(),restore?.analysisRevision);pending.current=task;
    }
    if(!task)return false;
    const abort=new AbortController();request.current=abort;setBusy(true);setError(null);
    try{
      const result=await api.request<DraftReceipt>(task.path,task.body,abort.signal);
      if(!alive.current||abort.signal.aborted)return false;
      adopt({...result,snapshot:task.snapshot});setNotice(t('已保存','Saved'));setReload(value=>value+1);setPreview(null);setHistoryOpen(false);return true;
    }catch(value){
      if(alive.current&&!abort.signal.aborted){const unknown=status(value)===0||status(value)>=500;setUncertain(unknown);if(!unknown)pending.current=null;failure(value);}
      return false;
    }finally{if(alive.current&&!abort.signal.aborted)setBusy(false);}
  }
  async function more(){if(!list?.nextCursor||loading)return;setLoading(true);const abort=new AbortController();request.current=abort;
    try{const next=await api.request<Listing>(ROOT,{q:filter,limit:25,cursor:list.nextCursor},abort.signal);if(alive.current&&!abort.signal.aborted)setList({...next,items:[...list.items,...next.items]});}
    catch(value){failure(value);}finally{if(alive.current&&!abort.signal.aborted)setLoading(false);}}
  async function history(before?:number){if(!receipt)return;const abort=new AbortController();request.current=abort;setHistoryOpen(true);setBusy(true);setError(null);
    try{const value=await api.request<Versions>(ROOT+'/revisions',{analysisSessionId:receipt.analysisSessionId,limit:25,...(before?{before}:{})},abort.signal);if(alive.current&&!abort.signal.aborted)setVersions(previous=>before&&previous?{...value,items:[...previous.items,...value.items]}:value);}
    catch(value){failure(value);}finally{if(alive.current&&!abort.signal.aborted)setBusy(false);}}
  async function viewRevision(revision:number){if(!receipt)return;const abort=new AbortController();request.current=abort;setBusy(true);
    try{const value=await api.request<Detail>(ROOT+'/detail',{analysisSessionId:receipt.analysisSessionId,analysisRevision:revision},abort.signal);if(alive.current&&!abort.signal.aborted)setPreview(value);}
    catch(value){failure(value);}finally{if(alive.current&&!abort.signal.aborted)setBusy(false);}}
  function addNote(){if(!draft||draft.cards.length>=50)return;const id=crypto.randomUUID();apply({...draft,cards:[...draft.cards,{id,kind:'analysis',title:t('分析笔记','Analysis note'),note:'',x:32+(draft.cards.length%3)*340,y:40+Math.floor(draft.cards.length/3)*240,width:300,height:200,pinned:false}]});setSelected(id);}
  function pointerDown(event:ReactPointerEvent,id?:string){
    if(!draft||event.button!==0||busy||uncertain)return;
    if(id){setSelected(id);if(tool==='hand'||space.current||!editable)return;const card=draft.cards.find(value=>value.id===id);if(!card||card.pinned)return;event.stopPropagation();}
    else if(tool!=='hand'&&!space.current){if(event.target===event.currentTarget)setSelected('');return;}
    event.preventDefault();event.currentTarget.setPointerCapture(event.pointerId);drag.current={kind:id?'card':'pan',id,x:event.clientX,y:event.clientY,before:draft};
    if(id)setUndo(values=>[...values.slice(-19),draft]);
  }
  function pointerMove(event:ReactPointerEvent){const moving=drag.current;if(!moving)return;const dx=event.clientX-moving.x,dy=event.clientY-moving.y;
    if(moving.kind==='pan')setDraft(value=>value?{...value,viewport:{...moving.before.viewport,x:Math.max(-50000,Math.min(50000,moving.before.viewport.x+dx)),y:Math.max(-50000,Math.min(50000,moving.before.viewport.y+dy))}}:value);
    else {const card=moving.before.cards.find(value=>value.id===moving.id);if(card)setDraft(moveCard(moving.before,card.id,card.x+dx/moving.before.viewport.zoom,card.y+dy/moving.before.viewport.zoom));}}
  function fit(){if(draft&&canvas.current)setDraft({...draft,viewport:fitViewport(draft.cards,canvas.current.clientWidth,canvas.current.clientHeight)});}
  function zoom(factor:number){if(draft&&canvas.current)setDraft({...draft,viewport:zoomAt(draft.viewport,draft.viewport.zoom*factor,canvas.current.clientWidth/2,canvas.current.clientHeight/2)});}
  const errorText=error instanceof Error&&!code(error)?error.message:en?'The request could not be completed. Your local edits are retained.':zhError[code(error)]||'暂时无法完成请求，请重试。';
  const statuses=[['analyzing','分析中','Analyzing'],['awaiting_field_check','待现场核查','Awaiting field check'],['awaiting_expert_review','待复核','Awaiting review']];
  return <section className={`ad-workspace${draft?' ad-has-draft':''}`} aria-label={t('分析工作空间','Analysis workspace')}>
    <aside className="ad-list"><header><strong>{t('我的分析','My analyses')}</strong><span>{list?.total??'—'}</span></header>
      <form className="ad-search" onSubmit={event=>{event.preventDefault();setFilter(query);}}><Search size={14}/><input aria-label={t('搜索分析','Search analyses')} placeholder={t('搜索名称','Search titles')} value={query} onChange={event=>setQuery(event.target.value)}/><button>{t('搜索','Search')}</button></form>
      <Btn primary disabled={!writable||busy} onClick={()=>change(fresh)}><Plus size={14}/>{t('新建分析','New analysis')}</Btn>
      <ul className="ad-list-items ov-list" aria-label={t('我的分析','My analyses')}>{list?.items.map(item=><RowContext key={item.analysisSessionId} name={item.title} disabled={busy} actions={[{id:'open',label:t('打开分析','Open analysis'),icon:<GitBranch/>,disabled:busy,onSelect:()=>change(()=>void open(item.analysisSessionId))}]}><li className={`ov-list-item${receipt?.analysisSessionId===item.analysisSessionId?' selected':''}`}><button type="button" className="ov-list-main" disabled={busy} aria-current={receipt?.analysisSessionId===item.analysisSessionId?'page':undefined} onClick={()=>change(()=>void open(item.analysisSessionId))}><span className="ov-list-copy"><strong>{item.title}</strong><small>{t(statuses.find(s=>s[0]===item.status)?.[1]||'分析中',statuses.find(s=>s[0]===item.status)?.[2]||'Analyzing')} · r{item.analysisRevision}</small><time>{new Date(item.updatedAt).toLocaleString(en?'en-GB':'zh-CN')}</time></span></button></li></RowContext>)}
        {!loading&&list&&!list.total&&<li><p>{t('还没有分析','No analyses yet')}</p></li>}{loading&&<li><p role="status">{t('正在读取…','Loading…')}</p></li>}
        {list?.nextCursor&&<li><Btn disabled={loading} onClick={()=>void more()}>{t('加载更多','Load more')}</Btn></li>}</ul>
      <footer>{t('仅本人可见','Private to you')}</footer>
    </aside>
    <div className="ad-editor">
      {!!error&&<div className="ad-alert" role="alert"><span>{errorText}</span>{!draft&&<Btn onClick={()=>setReload(v=>v+1)}>{t('重试','Retry')}</Btn>}
        {code(error)==='ANALYSIS_CHANGED'&&<><Btn disabled={busy} onClick={()=>void commit(true)}>{t('另存副本','Save a copy')}</Btn><Btn disabled={busy} onClick={()=>change(()=>receipt&&void open(receipt.analysisSessionId))}>{t('重新读取','Reload saved')}</Btn></>}
      </div>}
      {uncertain&&<div className="ad-alert" role="status">{t('保存结果尚未确认。重试会使用同一请求，避免重复创建。','Save result is unknown. Retry reuses the same request.')}</div>}
      {draft?<>
        <header className="ad-heading"><IconBtn label={t('返回列表','Back to list')} disabled={busy} onClick={()=>change(()=>{setDraft(null);setReceipt(null);setSaved('');})}><ArrowLeft size={16}/></IconBtn>
          <input aria-label={t('分析名称','Analysis title')} maxLength={120} value={draft.title} disabled={!editable} onChange={event=>apply({...draft,title:event.target.value})}/>
          <select aria-label={t('分析进度','Analysis progress')} value={draft.status} disabled={!editable} onChange={event=>apply({...draft,status:event.target.value as CanvasSnapshot['status']})}>{statuses.map(([value,zh,eng])=><option key={value} value={value}>{t(zh,eng)}</option>)}</select>
          <small aria-live="polite">{busy?t('处理中…','Working…'):dirty?t('未保存','Unsaved'):notice||t('已保存','Saved')}{receipt?' · r'+receipt.analysisRevision:''}</small>
          <IconBtn label={t('修订历史','Revision history')} disabled={!receipt||busy||uncertain} onClick={()=>void history()}><History size={17}/></IconBtn>
          <Btn primary disabled={!writable||busy||!dirty} onClick={()=>void commit()}><Save size={14}/>{uncertain?t('重试保存','Retry save'):t('保存','Save')}</Btn>
        </header>
        <div className="ad-tools"><Btn disabled={!editable||draft.cards.length>=50} onClick={addNote}><Plus size={14}/>{t('分析笔记','Analysis note')}</Btn>
          <IconBtn label={t('选择工具','Select tool')} aria-pressed={tool==='pointer'} onClick={()=>setTool('pointer')}><MousePointer2 size={16}/></IconBtn><IconBtn label={t('平移工具','Pan tool')} aria-pressed={tool==='hand'} onClick={()=>setTool('hand')}><Hand size={16}/></IconBtn>
          <IconBtn label={t('撤销修改','Undo change')} disabled={!undo.length||!editable} onClick={()=>{setDraft(undo[undo.length-1]);setUndo(values=>values.slice(0,-1));}}><Undo2 size={16}/></IconBtn>
          <Btn disabled={!editable||!draft.cards.length} onClick={()=>apply(arrangeCards(draft))}><LayoutGrid size={14}/>{t('整理布局','Arrange')}</Btn>
        </div>
        <div className="ad-canvas-row"><div ref={canvas} className={`ad-canvas ad-tool-${tool}`} tabIndex={0} aria-label={t('分析画布','Analysis canvas')}
          onKeyDown={event=>{if(event.code==='Space'){space.current=true;event.preventDefault();}}} onKeyUp={event=>{if(event.code==='Space')space.current=false;}} onBlur={()=>{space.current=false;drag.current=null;}}
          onPointerDown={event=>pointerDown(event)} onPointerMove={pointerMove} onPointerUp={()=>{drag.current=null;}} onPointerCancel={()=>{drag.current=null;}} onLostPointerCapture={()=>{drag.current=null;}}>
          <div className="ad-world" style={{transform:`translate(${draft.viewport.x}px,${draft.viewport.y}px) scale(${draft.viewport.zoom})`}}>
            <svg className="ad-links" aria-hidden="true"><defs><marker id="ad-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8" fill="none" stroke="currentColor"/></marker></defs>{draft.relations.map(link=>{const a=draft.cards.find(c=>c.id===link.from),b=draft.cards.find(c=>c.id===link.to);if(!a||!b)return null;const x=a.x+a.width,y=a.y+a.height/2,x2=b.x,y2=b.y+b.height/2;return <path key={link.id} d={`M${x},${y} C${x+60},${y} ${x2-60},${y2} ${x2},${y2}`} markerEnd="url(#ad-arrow)"/>;})}</svg>
            {draft.cards.map(card=><article key={card.id} className={`ad-card${selected===card.id?' selected':''}`} style={{left:card.x,top:card.y,width:card.width,height:card.height}} onClick={()=>setSelected(card.id)}>
              <header onPointerDown={event=>pointerDown(event,card.id)}><StickyNote size={14}/><strong>{card.title}</strong>{card.pinned&&<Pin size={13}/>}</header><div><span className="ad-badge">{t('人工分析 · 待核查','Manual analysis · Unverified')}</span><p>{card.note||t('选择卡片编辑笔记','Select to edit this note')}</p></div>
            </article>)}
          </div>
          {!draft.cards.length&&<div className="ad-empty"><StickyNote size={28}/><strong>{t('从一条分析笔记开始','Start with an analysis note')}</strong><p>{t('记录原因假设、排查步骤和证据缺口','Record hypotheses, checks and missing evidence')}</p><Btn primary disabled={!editable} onClick={addNote}>{t('添加分析笔记','Add analysis note')}</Btn></div>}
          <div className="ad-zoom"><IconBtn label={t('缩小画布','Zoom out canvas')} disabled={busy||uncertain} onClick={()=>zoom(1/1.2)}><ZoomOut size={15}/></IconBtn><span>{Math.round(draft.viewport.zoom*100)}%</span><IconBtn label={t('放大画布','Zoom in canvas')} disabled={busy||uncertain} onClick={()=>zoom(1.2)}><ZoomIn size={15}/></IconBtn><IconBtn label={t('适应全部','Fit all')} disabled={busy||uncertain} onClick={fit}><Maximize size={15}/></IconBtn></div>
          <span className="ad-hint">{t('拖动标题移动卡片 · 空格拖动画布 · 滚轮缩放','Drag titles to move · Space to pan · Wheel to zoom')}</span>
        </div>
        <aside className="ad-inspector"><header><strong>{t(selectedCard?'卡片详情':'分析范围',selectedCard?'Card details':'Analysis context')}</strong></header>{selectedCard?<>
          <label>{t('笔记名称','Note title')}<input maxLength={120} disabled={!editable} value={selectedCard.title} onChange={event=>apply({...draft,cards:draft.cards.map(card=>card.id===selected?{...card,title:event.target.value}:card)})}/></label>
          <label>{t('原因假设与排查笔记','Hypotheses and investigation notes')}<textarea maxLength={4000} disabled={!editable} value={selectedCard.note||''} onChange={event=>apply({...draft,cards:draft.cards.map(card=>card.id===selected?{...card,note:event.target.value}:card)})}/></label>
          <div className="ad-inline"><Btn disabled={!editable} onClick={()=>apply({...draft,cards:draft.cards.map(card=>card.id===selected?{...card,pinned:!card.pinned}:card)})}><Pin size={14}/>{selectedCard.pinned?t('取消固定','Unpin'):t('固定卡片','Pin card')}</Btn><IconBtn disabled={!editable} label={t('移除笔记','Remove note')} onClick={()=>{apply(removeCard(draft,selected));setSelected('');}}><Trash2 size={15}/></IconBtn></div>
          <p>{t('人工笔记不代表已确认的工程事实。','Notes do not constitute confirmed engineering facts.')}</p>
          <div className="ad-inline"><strong>{t('关联关系','Relationships')}</strong><IconBtn label={t('添加关系','Add relationship')} disabled={!editable||draft.cards.length<2} onClick={()=>{setTarget(draft.cards.find(card=>card.id!==selected)?.id||'');setReason('');setLinkOpen(true);}}><Plus size={15}/></IconBtn></div>
          {draft.relations.filter(link=>link.from===selected||link.to===selected).map(link=><div className="ad-relation" key={link.id}><GitBranch size={13}/><div><strong>{draft.cards.find(card=>card.id===(link.from===selected?link.to:link.from))?.title}</strong><p>{link.reason}</p></div><IconBtn label={t('移除关系','Remove relationship')} disabled={!editable} onClick={()=>apply({...draft,relations:draft.relations.filter(item=>item.id!==link.id)})}><X size={13}/></IconBtn></div>)}
        </>:<><p>{t('当前项目','Current project')}<strong>{api.project?.projectCode}</strong></p><details><summary>{t('分析时间范围','Analysis time window')}</summary><label>{t('开始时间（UTC）','From (UTC)')}<input disabled={!editable} value={draft.context.timeFrom} onChange={event=>apply({...draft,context:{...draft.context,timeFrom:event.target.value}})}/></label><label>{t('结束时间（UTC）','To (UTC)')}<input disabled={!editable} value={draft.context.timeTo} onChange={event=>apply({...draft,context:{...draft.context,timeTo:event.target.value}})}/></label></details></>}</aside></div>
      </>:<div className="ad-empty"><GitBranch size={32}/><h2>{t('整理你的分析思路','Organize your investigation')}</h2><p>{t('新建或继续一项分析，保留笔记、人工关系与修订历史。','Create or continue an analysis with notes, relationships and version history.')}</p><Btn primary disabled={!writable||busy} onClick={fresh}><Plus size={14}/>{t('新建分析','New analysis')}</Btn></div>}
    </div>
    {leave&&<Modal title={t('修改尚未保存','Unsaved changes')} description={t('离开前处理当前修改','Handle changes before leaving')} onClose={()=>setLeave(null)}><p>{uncertain?t('保存结果尚未确认，建议先重试。','Save result is unknown; retry first.'):t('离开将放弃当前未保存的修改。','Leaving discards unsaved edits.')}</p><div className="ad-inline"><Btn onClick={()=>setLeave(null)}>{t('继续编辑','Keep editing')}</Btn><Btn disabled={busy} onClick={()=>{const action=leave;setLeave(null);pending.current=null;setUncertain(false);action();}}>{t('放弃修改并离开','Discard and leave')}</Btn><Btn primary disabled={!writable||busy} onClick={()=>void commit().then(ok=>{if(ok){setLeave(null);leave();}})}>{t('保存并继续','Save and continue')}</Btn></div></Modal>}
    {historyOpen&&<Modal title={t('修订历史','Revision history')} description={t('历史只读，恢复将追加新修订','History is immutable; restoring adds a revision')} onClose={()=>{if(!busy){setHistoryOpen(false);setPreview(null);}}}><div className="ad-history">{versions?.items.map(item=><Btn key={item.revision} disabled={busy} onClick={()=>void viewRevision(item.revision)}>r{item.revision} · {new Date(item.createdAt).toLocaleString(en?'en-GB':'zh-CN')}</Btn>)}{versions?.nextBeforeRevision&&<Btn disabled={busy} onClick={()=>void history(versions.nextBeforeRevision!)}>{t('更早修订','Earlier revisions')}</Btn>}</div>{preview&&<><h3>{preview.snapshot.title} · r{preview.analysisRevision}</h3>{preview.snapshot.cards.map(card=><div key={card.id}><strong>{card.title}</strong><p className="ad-history-note">{card.note}</p></div>)}<Btn primary disabled={!writable||busy||dirty||preview.analysisRevision===(receipt?.headRevision??receipt?.analysisRevision)} onClick={()=>void commit(false,preview)}>{t('恢复为新修订','Restore as a new revision')}</Btn>{dirty&&<p>{t('先保存或放弃当前修改，再恢复历史。','Save or discard your edits before restoring.')}</p>}</>}</Modal>}
    {linkOpen&&draft&&<Modal title={t('添加人工关系','Add manual relationship')} description={t('记录两张笔记之间的依据','Record a reason connecting two notes')} onClose={()=>setLinkOpen(false)}><form className="ad-link-form" onSubmit={event=>{event.preventDefault();try{apply(addManualRelation(draft,{id:crypto.randomUUID(),from:selected,to:target,kind:relationKind,origin:'manual',reason}));setLinkOpen(false);}catch(value){failure(value);}}}><label>{t('关联笔记','Related note')}<select value={target} onChange={event=>setTarget(event.target.value)}>{draft.cards.filter(card=>card.id!==selected).map(card=><option key={card.id} value={card.id}>{card.title}</option>)}</select></label><label>{t('关系类型','Relation type')}<select value={relationKind} onChange={event=>setRelationKind(event.target.value as RelationKind)}>{[['reference','资料引用','Reference'],['hypothesis','原因假设','Hypothesis'],['supports','支持依据','Supports'],['contradicts','反证','Contradicts']].map(([key,zh,eng])=><option key={key} value={key}>{t(zh,eng)}</option>)}</select></label><label>{t('关系依据','Reason')}<textarea maxLength={1000} required value={reason} onChange={event=>setReason(event.target.value)}/></label><button type="submit" className="ov-btn primary">{t('添加关系','Add relationship')}</button></form></Modal>}
  </section>;
}
