import {useCallback,useEffect,useMemo,useRef,useState} from 'react';
import {cancelled,failureMessage,type WorkbenchApi} from './api';
import {Btn,Modal} from './Primitives';
import type {SceneObjectContext} from './sceneEngineeringTypes';
import type {ObjectPhoto} from './workOrderTypes';
import {WorkOrderPhotoViewport} from './WorkOrderPhotoViewport';
import {EquipmentApi,type MaterialSelection,type SharedPhoto,type SharedPhotoRegion} from './equipmentApi';

function Thumbnail({photo,read,en}:{photo:SharedPhoto;read:(photo:SharedPhoto,representation:'thumbnail'|'preview'|'original',signal:AbortSignal)=>Promise<string>;en:boolean}){
  const [image,setImage]=useState('');
  useEffect(()=>{const abort=new AbortController();setImage('');read(photo,'thumbnail',abort.signal).then(url=>{if(!abort.signal.aborted)setImage(url);}).catch(()=>{});return()=>abort.abort();},[photo,read]);
  return image?<img className="eq-photo-thumbnail" src={image} alt=""/>:<span className="eq-photo-thumbnail">{en?'Open to view':'打开查看'}</span>;
}
export function EquipmentPhotos({api,definition,device,en,purpose='object_location'}:{api:WorkbenchApi;definition:SceneObjectContext|null;device:SceneObjectContext|null;en:boolean;purpose?:'object_location'|'field_record'}){
  const service=useMemo(()=>new EquipmentApi(api),[api]);
  const current=purpose==='field_record'?device:device??definition;
  const selection=useMemo<MaterialSelection|null>(()=>current?{entityUid:current.item.entityUid,expectedEntityRevision:current.item.entityRevision,
    installationContextId:current.item.installationContextId,expectedHierarchyRevision:current.item.installationContextId?current.context?.hierarchyRevision??null:null}:null,
    [current?.item.entityUid,current?.item.entityRevision,current?.item.installationContextId,current?.context?.hierarchyRevision]);
  const [photos,setPhotos]=useState<SharedPhoto[]>([]),[field,setField]=useState<ObjectPhoto[]>([]),[cursor,setCursor]=useState<string|null>(null),[next,setNext]=useState<string|null>(null);
  const [error,setError]=useState<unknown>(null),[loading,setLoading]=useState(false),[chosen,setChosen]=useState<SharedPhoto|ObjectPhoto|null>(null),[image,setImage]=useState(''),[original,setOriginal]=useState(false);
  const [regions,setRegions]=useState<SharedPhotoRegion[]>([]),[regionNext,setRegionNext]=useState<string|null>(null),[region,setRegion]=useState(''),[regionBusy,setRegionBusy]=useState(false);
  const cache=useRef(new Map<string,string>()),active=useRef<AbortController|null>(null),regionRead=useRef<AbortController|null>(null);
  useEffect(()=>()=>{for(const url of cache.current.values())URL.revokeObjectURL(url);cache.current.clear();active.current?.abort();regionRead.current?.abort();},[api,api.epoch,api.revision]);
  useEffect(()=>{setCursor(null);setPhotos([]);setField([]);setChosen(null);setImage('');active.current?.abort();regionRead.current?.abort();},[selection,purpose]);
  useEffect(()=>{const abort=new AbortController();setError(null);if(!selection)return;setLoading(true);
    const request=purpose==='object_location'?service.sharedPhotos(selection,cursor,abort.signal).then(value=>{if(!abort.signal.aborted){setPhotos(rows=>cursor?[...rows,...value.items]:value.items);setNext(value.nextCursor);}})
      :api.request<{items:ObjectPhoto[]}>('/api/workbench/objects/photos/resolve',{...selection,photoPurpose:'field_record'},abort.signal).then(value=>{if(!abort.signal.aborted)setField(value.items);});
    request.catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setError(e);}).finally(()=>{if(!abort.signal.aborted)setLoading(false);});return()=>abort.abort();
  },[service,api,api.epoch,api.revision,selection,purpose,cursor]);
  const read=useCallback(async(photo:SharedPhoto,representation:'thumbnail'|'preview'|'original',signal:AbortSignal)=>{
    if(!selection)throw new Error('No selection');
    const key=JSON.stringify([api.epoch,api.revision,photo.documentId,photo.contentVersionId,photo.displayRevision,representation]);
    const cached=cache.current.get(key);if(cached)return cached;
    const blob=await service.sharedContent(selection,photo,representation,signal);if(signal.aborted)throw new DOMException('Aborted','AbortError');
    if(cache.current.size>=24){const first=cache.current.keys().next().value;if(first){URL.revokeObjectURL(cache.current.get(first)!);cache.current.delete(first);}}
    const url=URL.createObjectURL(blob);cache.current.set(key,url);return url;
  },[api.epoch,api.revision,service,selection]);
  async function loadRegions(photo:SharedPhoto,after:string|null=null){
    if(!selection)return;regionRead.current?.abort();const abort=new AbortController();regionRead.current=abort;setRegionBusy(true);
    try{const value=await service.sharedRegions(selection,photo,after,abort.signal);if(!abort.signal.aborted){setRegions(rows=>after?[...rows,...value.items]:value.items);setRegionNext(value.nextCursor);}}
    catch(e){if(!abort.signal.aborted&&!cancelled(e))setError(e);}finally{if(!abort.signal.aborted)setRegionBusy(false);}
  }
  async function open(photo:SharedPhoto|ObjectPhoto,full=false){
    if(!selection)return;active.current?.abort();const abort=new AbortController();active.current=abort;setChosen(photo);setOriginal(full);setImage('');setError(null);
    if('regionCount' in photo&&chosen!==photo){setRegions([]);setRegion('');void loadRegions(photo);}
    try{let url:string;if('regionCount' in photo)url=await read(photo,full?'original':'preview',abort.signal);else{
      const blob=await service.photoContent({...selection,photoPurpose:'field_record'},photo,full,abort.signal);if(abort.signal.aborted)return;
      url=URL.createObjectURL(blob);const key='field';const old=cache.current.get(key);if(old)URL.revokeObjectURL(old);cache.current.set(key,url);
    }if(!abort.signal.aborted)setImage(url);}catch(e){if(!abort.signal.aborted&&!cancelled(e))setError(e);}
  }
  const selected=regions.find(row=>row.photo.evidenceRef===region);
  return <section className="eq-photos">
    <p className="eq-caption">{purpose==='object_location'?(en?'Shared location photos, with original object regions':'按项目和型号共享定位照片，保留原对象区域'):(en?'Field photos for this device only':'仅显示此单台设备的现场照片；在 OntoBase 中管理')}</p>
    {!!error&&<p role="alert">{failureMessage(error,en?'en':'zh')}</p>}
    {purpose==='object_location'?<div className="eq-photo-grid">{photos.map(photo=><button key={photo.documentId+photo.contentVersionId} disabled={photo.availability!=='available'} onClick={()=>void open(photo)}><Thumbnail photo={photo} read={read} en={en}/><span>{photo.viewLabel||photo.title}<small>{photo.regionCount} {en?'original regions':'个原对象区域'} · {photo.sources.includes('explicit')?(en?'Explicit scope':'显式适用'):''}{photo.sources.includes('member')?(en?' · Cabinet members':' · 柜内成员'):''}</small></span></button>)}</div>
      :field.map(photo=><div className="eq-photo-row" key={photo.evidenceRef}><span>{photo.title}</span><Btn onClick={()=>void open(photo)}>{en?'Open photo':'打开照片'}</Btn></div>)}
    {loading?<p role="status">{en?'Loading photos…':'正在读取照片…'}</p>:!error&&!(purpose==='object_location'?photos:field).length&&<p className="eq-caption">{purpose==='field_record'?(en?'No field photos for this device':'当前设备暂无现场照片'):(en?'No shared location photos':'当前对象暂无共享定位照片')}</p>}
    {purpose==='object_location'&&next&&!loading&&<Btn onClick={()=>setCursor(next)}>{en?'Load more':'加载更多'}</Btn>}
    {chosen&&<Modal className="eq-photo-modal" title={chosen.title} description={en?'Fixed photo and original object regions':'固定照片与原对象区域'} onClose={()=>{active.current?.abort();regionRead.current?.abort();setChosen(null);setImage('');}}>
      <div className="eq-photo-toolbar"><Btn onClick={()=>void open(chosen,!original)}>{original?(en?'Fast preview':'快速预览'):(en?'Full resolution':'原尺寸')}</Btn>
      {'regionCount' in chosen&&<><label>{en?'Original object region':'原对象区域'}<select aria-label={en?'Original object region':'原对象区域'} value={region} onChange={event=>setRegion(event.target.value)}><option value="">{en?'Whole photo':'整张照片'}</option>{regions.map(row=><option key={row.photo.evidenceRef} value={row.photo.evidenceRef}>{row.object.displayName}</option>)}</select></label>{regionNext&&<Btn disabled={regionBusy} onClick={()=>void loadRegions(chosen,regionNext)}>{en?'More regions':'更多区域'}</Btn>}</>}
      </div>{selected&&<p className="eq-caption">{selected.object.displayName} · {selected.object.entityUid}</p>}
      {image?<WorkOrderPhotoViewport key={region} image={image} selector={selected?.photo.selector??('regionCount' in chosen?null:chosen.selector)} label={chosen.title} en={en} focusFraction={.35} onError={()=>setImage('')}/>:<p role={error?'alert':'status'}>{error?failureMessage(error,en?'en':'zh'):(en?'Loading photo…':'正在载入照片…')}</p>}
    </Modal>}
  </section>;
}
