import {useEffect,useState} from 'react';
import {FileText,RefreshCw} from 'lucide-react';
import {ApiError,cancelled,failureMessage,type WorkbenchApi} from './api';
import type {EngineeringObject,Installation,Evidence} from './types';
import type {MaterialSelection} from './equipmentApi';
import {equipmentDrawingSelection,equipmentDrawings,equipmentDrawingContent} from './equipmentDrawingState';
import {Btn,Modal} from './Primitives';
import {PageDeck} from './CockpitPanels';
import {WorkOrderPhotoViewport} from './WorkOrderPhotoViewport';
import './equipmentMaterials.css';

export function EquipmentDrawings({api,object,context,en,onReload}:{api:WorkbenchApi;object:EngineeringObject;context:Installation|null;en:boolean;onReload:()=>void}){
 const [items,setItems]=useState<Evidence[]>([]),[busy,setBusy]=useState(true),[error,setError]=useState<unknown>(null),[attempt,setAttempt]=useState(0),[chosen,setChosen]=useState<Evidence|null>(null);
 const [selection,setSelection]=useState<MaterialSelection|null>(null);
 useEffect(()=>{const abort=new AbortController();setBusy(true);setItems([]);setChosen(null);setError(null);setSelection(null);
  void (async()=>{const selected=equipmentDrawingSelection(object,context),value=await equipmentDrawings(api,selected,abort.signal);if(!abort.signal.aborted){setItems(value.items);setSelection(selected);}})()
   .catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setError(e);}).finally(()=>{if(!abort.signal.aborted)setBusy(false);});return()=>abort.abort();
 },[api,api.epoch,api.revision,object.entityUid,object.entityRevision,object.installationContextId,context?.hierarchyRevision,attempt]);
 return <section className="eq-materials pc-device-resources" aria-label={en?'Related drawings':'对象关联图纸'}><header><div><h4>{en?'Related drawings':'当前对象关联图纸'}</h4></div><Btn disabled={busy} onClick={()=>error instanceof ApiError&&error.status===409?onReload():setAttempt(v=>v+1)}><RefreshCw size={14}/>{en?'Refresh':'刷新'}</Btn></header>
  {busy&&<p role="status">{en?'Loading drawings…':'正在读取图纸…'}</p>}{!!error&&<p role="alert">{failureMessage(error,en?'en':'zh')}</p>}
  {!busy&&!error&&!items.length&&<p className="eq-message">{en?'No drawings are linked to this object.':'当前对象暂无关联图纸。'}</p>}
  {!!items.length&&<div className="pc-resource-list" style={{'--pc-resource-height':Math.min(520,items.length*112+42)+'px'} as import('react').CSSProperties}><PageDeck items={items} en={en} label={en?'Drawing list':'图纸清单'} rowHeight={112} render={item=><article className="pc-resource-row" key={item.evidenceRef}><FileText size={22}/><div><strong>{item.title}</strong><small>{item.pageNumber?`${en?'Page ':'第'}${item.pageNumber}${en?'':'页'} · `:''}{item.sourceRelation==='template_definition'?(en?'Shared definition':'共享定义图纸'):(en?'Object drawing':'对象图纸')}</small>{item.availability==='missing'&&<small>{en?'Source unavailable':'来源暂不可用'}</small>}</div><Btn disabled={item.availability!=='available'} onClick={()=>setChosen(item)}>{en?'Preview':'预览'}</Btn></article>}/></div>}
  {chosen&&selection&&<DrawingPreview key={chosen.evidenceRef} api={api} selection={selection} item={chosen} en={en} onClose={()=>setChosen(null)}/>}
 </section>;
}
function DrawingPreview({api,selection,item,en,onClose}:{api:WorkbenchApi;selection:MaterialSelection;item:Evidence;en:boolean;onClose:()=>void}){
 const [image,setImage]=useState(''),[error,setError]=useState<unknown>(null),[attempt,setAttempt]=useState(0);
 useEffect(()=>{const abort=new AbortController();let url='';setImage('');setError(null);
  void (async()=>{const blob=await equipmentDrawingContent(api,selection,item,abort.signal);if(!abort.signal.aborted){url=URL.createObjectURL(blob);setImage(url);}})().catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setError(e);});
  return()=>{abort.abort();if(url)URL.revokeObjectURL(url);};
 },[api,api.epoch,api.revision,selection,item.evidenceRef,item.sourceRevision,item.contentSha256,attempt]);
 return <Modal className="eq-material-preview" title={item.title} description={en?'Protected object drawing':'受保护的对象关联图纸'} onClose={onClose}><div className="eq-material-preview-bar"><span>{item.pageNumber?`${en?'Page ':'第'}${item.pageNumber}${en?'':'页'}`:en?'Whole page':'整页'}</span><span>{item.sourceRelation==='template_definition'?(en?'Shared definition drawing':'共享定义图纸'):(en?'Object drawing':'对象图纸')}</span></div>
  {image?<WorkOrderPhotoViewport image={image} selector={null} embedded label={item.title} en={en} onError={()=>{setImage('');setError(new ApiError(502,'IMAGE_INVALID'));}}/>:<div className="eq-material-wait" role={error?'alert':'status'}><p>{error?failureMessage(error,en?'en':'zh'):(en?'Loading drawing…':'正在读取图纸…')}</p>{!!error&&<Btn onClick={()=>setAttempt(v=>v+1)}>{en?'Retry':'重试'}</Btn>}</div>}
 </Modal>;
}
