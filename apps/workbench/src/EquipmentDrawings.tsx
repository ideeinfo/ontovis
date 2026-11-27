import {useEffect,useMemo,useState} from 'react';
import {FileText,RefreshCw,Search} from 'lucide-react';
import {ApiError,cancelled,failureMessage,type WorkbenchApi} from './api';
import type {EngineeringObject,Installation} from './types';
import type {MaterialSelection} from './equipmentApi';
import {appendDrawingPage,equipmentDrawingSelection,equipmentDrawings,equipmentDrawingContent,filterEquipmentDrawings,type DrawingMatch,type RelatedDrawing,type RelatedDrawingPage} from './equipmentDrawingState';
import {Btn,Modal} from './Primitives';
import {PageDeck} from './CockpitPanels';
import {WorkOrderPhotoViewport} from './WorkOrderPhotoViewport';
import './equipmentMaterials.css';

const DRAWING_BATCH=20;
export function EquipmentDrawings({api,object,context,en,onReload}:{api:WorkbenchApi;object:EngineeringObject;context:Installation|null;en:boolean;onReload:()=>void}){
 const [includeDescendants,setIncludeDescendants]=useState(true),[query,setQuery]=useState(''),[attempt,setAttempt]=useState(0);
 const key=JSON.stringify([api.epoch,api.revision,object.entityUid,object.entityRevision,object.installationContextId,context?.hierarchyRevision,includeDescendants,attempt]);
 const [requested,setRequested]=useState<{key:string;cursor:string}|null>(null);
 const cursor=requested?.key===key?requested.cursor:null;
 const [loaded,setLoaded]=useState<{key:string;cursor:string|null;selection:MaterialSelection;page:RelatedDrawingPage}|null>(null),[failure,setFailure]=useState<{key:string;error:unknown}|null>(null);
 const [chosen,setChosen]=useState<RelatedDrawing|null>(null),[matches,setMatches]=useState<RelatedDrawing|null>(null);
 const value=loaded?.key===key?loaded:null,error=failure?.key===key?failure.error:null,busy=!error&&(!value||value.cursor!==cursor);
 const next=value?.page.nextCursor,search=query.trim();
 const items=useMemo(()=>filterEquipmentDrawings(value?.page.items??[],search),[value,search]);
 useEffect(()=>{setChosen(null);setMatches(null);},[key]);
 useEffect(()=>{
  const abort=new AbortController(),previous=cursor?value?.page??null:null;
  void (async()=>{
   const selection=equipmentDrawingSelection(object,context);
   const page=await equipmentDrawings(api,selection,{includeDescendants,limit:DRAWING_BATCH,cursor},abort.signal);
   if(!abort.signal.aborted)setLoaded({key,cursor,selection,page:appendDrawingPage(previous,page,cursor)});
  })().catch(error=>{
   if(!abort.signal.aborted&&!cancelled(error)){setLoaded(null);setFailure({key,error});setChosen(null);setMatches(null);}
  });
  return()=>abort.abort();
 },[api,key,cursor]);
 useEffect(()=>{
  if(search&&next&&!busy&&!error)setRequested({key,cursor:next});
 },[search,next,busy,error,key]);
 const loadMore=()=>{if(next&&!busy&&!error)setRequested({key,cursor:next});};
 const refresh=()=>{setAttempt(v=>v+1);if(error instanceof ApiError&&error.status===409&&['ENGINEERING_CHANGED','REVISION_CONFLICT','SOURCE_DEFINITION_CHANGED'].includes(error.code))onReload();};
 return <section className="eq-materials pc-device-resources pc-related-drawings" aria-label={en?'Related drawings':'对象关联图纸'}><header><div><h4>{en?'Related drawings':'关联图纸'}</h4></div><Btn disabled={busy} onClick={refresh}><RefreshCw size={14}/>{en?'Refresh':'刷新'}</Btn></header>
  <div className="pc-parameter-tabs pc-drawing-scope" role="tablist" aria-label={en?'Drawing scope':'图纸范围'}>{[true,false].map(all=><button key={String(all)} role="tab" aria-selected={includeDescendants===all} onClick={()=>setIncludeDescendants(all)}>{all?(en?'Object & descendants':'本对象及下级'):(en?'Object only':'仅本对象')}</button>)}</div>
  <label className="pc-drawing-search"><Search size={16} aria-hidden="true"/><input type="search" aria-label={en?'Search drawings':'搜索图纸'} placeholder={en?'Title, drawing number, page or object':'图名、图号、页码或关联对象'} value={query} maxLength={200} onChange={event=>setQuery(event.target.value)}/></label>
  {busy&&!value&&<p role="status">{en?'Loading drawings…':'正在读取图纸…'}</p>}{!!error&&<p role="alert">{failureMessage(error,en?'en':'zh')}</p>}
  {value&&<>
   {!items.length&&!next&&<p className="eq-message">{search?(en?'No drawings match your search.':'未找到匹配的图纸。'):includeDescendants?(en?'No drawings linked to this object or its registered descendants.':'本对象及已登记下级暂无关联图纸。'):(en?'No drawings linked directly to this object.':'本对象暂无直接关联图纸。')}</p>}
   {!!items.length&&<div key={JSON.stringify([key,search])} className="pc-resource-scroll" role="region" tabIndex={0} aria-label={en?'Drawing list':'图纸清单'} onScroll={event=>{const list=event.currentTarget;if(!search&&list.scrollHeight-list.scrollTop-list.clientHeight<72)loadMore();}}>
    {items.map(item=><article className="pc-resource-row" key={item.drawingUid}><FileText size={19}/><div><strong>{item.title}</strong><small>{[item.drawingNumber,item.pageNumber!==null?`${en?'Page ':'第'}${item.pageNumber}${en?'':'页'}`:''].filter(Boolean).join(' · ')}</small><button className="pc-drawing-matches" onClick={()=>setMatches(item)}>{en?`Matched objects (${item.matchedObjects.length})`:`关联对象（${item.matchedObjects.length}）`}</button>{item.availability==='missing'&&<small>{en?'Source unavailable':'来源暂不可用'}</small>}</div><Btn disabled={item.availability!=='available'} onClick={()=>setChosen(item)}>{en?'Preview':'预览'}</Btn></article>)}
   </div>}
   <footer className="pc-drawing-status"><span role="status">{search?(next?(en?`Searching ${value.page.items.length} / ${value.page.total} · ${items.length} matches`:`正在搜索 ${value.page.items.length} / ${value.page.total} · 已匹配 ${items.length} 张`):(en?`${items.length} matching drawings`:`找到 ${items.length} 张图纸`)):(en?`${value.page.items.length} of ${value.page.total} drawings`:`已载入 ${value.page.items.length} / ${value.page.total} 张图纸`)}</span>
    {!search&&next&&<Btn disabled={busy} onClick={loadMore}>{busy?(en?'Loading…':'正在载入…'):(en?'Load more drawings':'加载更多图纸')}</Btn>}
   </footer>
  </>}
  {matches&&value&&<Modal title={en?'Matched objects':'关联对象'} description={matches.title} onClose={()=>setMatches(null)}><p className="pc-drawing-match-title">{matches.title}</p><div className="pc-drawing-match-list"><PageDeck items={matches.matchedObjects} en={en} label={en?'Matched object list':'命中对象清单'} rowHeight={72} render={item=><div className="pc-drawing-match-row" key={[item.entityUid,item.relation,item.viaEntityUid].join(':')}><strong>{item.displayName}</strong><small>{drawingRelationLabel(item.relation,en)}{['installation_descendant','definition_descendant'].includes(item.relation)?` · ${item.viaName}`:''}</small></div>}/></div></Modal>}
  {chosen&&value&&<DrawingPreview key={chosen.drawingUid} api={api} selection={value.selection} item={chosen} includeDescendants={includeDescendants} en={en} onClose={()=>setChosen(null)}/>}
 </section>;
}
export function drawingRelationLabel(relation:DrawingMatch['relation'],en:boolean){
 return ({self:en?'This object':'本对象',shared_definition:en?'Shared definition':'共享定义',installation_descendant:en?'Installed descendant':'安装下级',definition_descendant:en?'Registered shared-definition member':'共享定义下级（用户登记）'})[relation];
}
function DrawingPreview({api,selection,item,includeDescendants,en,onClose}:{api:WorkbenchApi;selection:MaterialSelection;item:RelatedDrawing;includeDescendants:boolean;en:boolean;onClose:()=>void}){
 const [image,setImage]=useState(''),[error,setError]=useState<unknown>(null),[attempt,setAttempt]=useState(0);
 useEffect(()=>{const abort=new AbortController();let url='';setImage('');setError(null);
  void (async()=>{const blob=await equipmentDrawingContent(api,selection,item,includeDescendants,abort.signal);if(!abort.signal.aborted){url=URL.createObjectURL(blob);setImage(url);}})().catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setError(e);});
  return()=>{abort.abort();if(url)URL.revokeObjectURL(url);};
 },[api,api.epoch,api.revision,selection,item,includeDescendants,attempt]);
 return <Modal className="eq-material-preview" title={item.title} description={en?'Protected related drawing':'受保护的关联图纸'} onClose={onClose}><div className="eq-material-preview-bar"><span>{item.pageNumber?`${en?'Page ':'第'}${item.pageNumber}${en?'':'页'}`:en?'Whole page':'整页'}</span><span>{en?`${item.matchedObjects.length} matched objects`:`${item.matchedObjects.length} 个关联对象`}</span></div>
  {image?<WorkOrderPhotoViewport image={image} selector={null} embedded label={item.title} en={en} onError={()=>{setImage('');setError(new ApiError(502,'IMAGE_INVALID'));}}/>:<div className="eq-material-wait" role={error?'alert':'status'}><p>{error?failureMessage(error,en?'en':'zh'):(en?'Loading drawing…':'正在读取图纸…')}</p>{!!error&&<Btn onClick={()=>setAttempt(v=>v+1)}>{en?'Retry':'重试'}</Btn>}</div>}
 </Modal>;
}
