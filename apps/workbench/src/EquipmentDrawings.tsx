import {useEffect,useState} from 'react';
import {ChevronDown,ChevronUp,FileText,RefreshCw} from 'lucide-react';
import {ApiError,cancelled,failureMessage,type WorkbenchApi} from './api';
import type {EngineeringObject,Installation} from './types';
import type {MaterialSelection} from './equipmentApi';
import {equipmentDrawingSelection,equipmentDrawings,equipmentDrawingContent,type DrawingMatch,type RelatedDrawing,type RelatedDrawingPage} from './equipmentDrawingState';
import {Btn,Modal} from './Primitives';
import {PageDeck} from './CockpitPanels';
import {WorkOrderPhotoViewport} from './WorkOrderPhotoViewport';
import './equipmentMaterials.css';

const drawingLimit=()=>typeof window==='undefined'||window.innerHeight>=850?3:2;
type DrawingPaging={identity:string;cursor:string|null;previous:(string|null)[];start:number};
export function EquipmentDrawings({api,object,context,en,onReload}:{api:WorkbenchApi;object:EngineeringObject;context:Installation|null;en:boolean;onReload:()=>void}){
 const [includeDescendants,setIncludeDescendants]=useState(true),[limit,setLimit]=useState(drawingLimit),[attempt,setAttempt]=useState(0);
 const identity=JSON.stringify([api.epoch,api.revision,object.entityUid,object.entityRevision,object.installationContextId,context?.hierarchyRevision,includeDescendants,limit]);
 const [paging,setPaging]=useState<DrawingPaging>({identity,cursor:null,previous:[],start:0});
 const page=paging.identity===identity?paging:{identity,cursor:null,previous:[],start:0},key=JSON.stringify([identity,page.cursor,attempt]);
 const [loaded,setLoaded]=useState<{key:string;selection:MaterialSelection;page:RelatedDrawingPage}|null>(null),[failure,setFailure]=useState<{key:string;error:unknown}|null>(null);
 const [chosen,setChosen]=useState<RelatedDrawing|null>(null),[matches,setMatches]=useState<RelatedDrawing|null>(null);
 const value=loaded?.key===key?loaded:null,error=failure?.key===key?failure.error:null,busy=!value&&!error;
 useEffect(()=>{const resize=()=>setLimit(drawingLimit());window.addEventListener('resize',resize);return()=>window.removeEventListener('resize',resize);},[]);
 useEffect(()=>{const abort=new AbortController();setChosen(null);setMatches(null);
  void (async()=>{const selection=equipmentDrawingSelection(object,context),result=await equipmentDrawings(api,selection,{includeDescendants,limit,cursor:page.cursor},abort.signal);if(!abort.signal.aborted)setLoaded({key,selection,page:result});})()
   .catch(error=>{if(!abort.signal.aborted&&!cancelled(error))setFailure({key,error});});return()=>abort.abort();
 },[api,key]);
 const refresh=()=>{setPaging({identity,cursor:null,previous:[],start:0});setAttempt(v=>v+1);if(error instanceof ApiError&&error.status===409&&['ENGINEERING_CHANGED','REVISION_CONFLICT','SOURCE_DEFINITION_CHANGED'].includes(error.code))onReload();};
 const items=value?.page.items??[];
 return <section className="eq-materials pc-device-resources pc-related-drawings" aria-label={en?'Related drawings':'对象关联图纸'}><header><div><h4>{en?'Related drawings':'关联图纸'}</h4></div><Btn disabled={busy} onClick={refresh}><RefreshCw size={14}/>{en?'Refresh':'刷新'}</Btn></header>
  <div className="pc-parameter-tabs pc-drawing-scope" role="tablist" aria-label={en?'Drawing scope':'图纸范围'}>{[true,false].map(all=><button key={String(all)} role="tab" aria-selected={includeDescendants===all} onClick={()=>setIncludeDescendants(all)}>{all?(en?'Object & descendants':'本对象及下级'):(en?'Object only':'仅本对象')}</button>)}</div>
  {busy&&<p role="status">{en?'Loading drawings…':'正在读取图纸…'}</p>}{!!error&&<p role="alert">{failureMessage(error,en?'en':'zh')}</p>}
  {value&&!items.length&&<p className="eq-message">{includeDescendants?(en?'No drawings linked to this object or its registered descendants.':'本对象及已登记下级暂无关联图纸。'):(en?'No drawings linked directly to this object.':'本对象暂无直接关联图纸。')}</p>}
  {value&&!!items.length&&<div className="pc-drawing-pages" aria-label={en?'Drawing list':'图纸清单'}><div className="pc-page-items">{items.map(item=><article className="pc-resource-row" key={item.drawingUid}><FileText size={22}/><div><strong>{item.title}</strong><small>{[item.drawingNumber,item.pageNumber?`${en?'Page ':'第'}${item.pageNumber}${en?'':'页'}`:''].filter(Boolean).join(' · ')}</small><button className="pc-drawing-matches" onClick={()=>setMatches(item)}>{en?`Matched objects (${item.matchedObjects.length})`:`关联对象（${item.matchedObjects.length}）`}</button>{item.availability==='missing'&&<small>{en?'Source unavailable':'来源暂不可用'}</small>}</div><Btn disabled={item.availability!=='available'} onClick={()=>setChosen(item)}>{en?'Preview':'预览'}</Btn></article>)}</div><footer className="pc-pagination"><span>{`${page.start+1}–${page.start+items.length} / ${value.page.total}`}</span><button aria-label={en?'Previous drawings':'上一页图纸'} disabled={!page.previous.length} onClick={()=>setPaging({identity,cursor:page.previous.at(-1)??null,previous:page.previous.slice(0,-1),start:Math.max(0,page.start-limit)})}><ChevronUp size={16}/></button><button aria-label={en?'Next drawings':'下一页图纸'} disabled={!value.page.nextCursor} onClick={()=>setPaging({identity,cursor:value.page.nextCursor,previous:[...page.previous,page.cursor],start:page.start+items.length})}><ChevronDown size={16}/></button></footer></div>}
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
