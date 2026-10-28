import {useEffect,useRef,useState} from 'react';
import {cancelled,failureMessage,type WorkbenchApi} from './api';
import {Btn,Modal} from './Primitives';
import type {SceneObjectContext} from './sceneEngineeringTypes';
import type {ObjectPhoto} from './workOrderTypes';
import {WorkOrderPhotoViewport} from './WorkOrderPhotoViewport';
import {EquipmentApi} from './equipmentApi';

type PhotoPurpose='object_location'|'field_record';
interface PhotoCandidate {documentId:string;title:string;contentVersionId:string;renditionId:string;displayRevision:string}
export function EquipmentPhotos({api,definition,device,en,canWrite=false}:{api:WorkbenchApi;definition:SceneObjectContext|null;device:SceneObjectContext|null;en:boolean;canWrite?:boolean}){
  const [purpose,setPurpose]=useState<PhotoPurpose>('object_location'),[photos,setPhotos]=useState<ObjectPhoto[]>([]);
  const [error,setError]=useState<unknown>(null),[loading,setLoading]=useState(false),[chosen,setChosen]=useState<ObjectPhoto|null>(null),[image,setImage]=useState('');
  const [picker,setPicker]=useState(false),[candidates,setCandidates]=useState<PhotoCandidate[]>([]),[candidate,setCandidate]=useState<PhotoCandidate|null>(null),[reload,setReload]=useState(0),[saving,setSaving]=useState(false),[next,setNext]=useState<string|null>(null),[candidatesLoading,setCandidatesLoading]=useState(false),[original,setOriginal]=useState(false);
  const current=purpose==='object_location'?definition:device;
  const cache=useRef(new Map<string,string>()),active=useRef<AbortController|null>(null),operation=useRef<AbortController|null>(null);
  const body=current?{entityUid:current.item.entityUid,expectedEntityRevision:current.item.entityRevision,
    installationContextId:current.item.installationContextId,expectedHierarchyRevision:current.item.installationContextId?current.context?.hierarchyRevision??null:null,photoPurpose:purpose}:null;
  useEffect(()=>()=>{for(const url of cache.current.values())URL.revokeObjectURL(url);cache.current.clear();active.current?.abort();},[api,api.epoch,api.revision]);
  useEffect(()=>{
    const abort=new AbortController();setPhotos([]);setError(null);setChosen(null);setImage('');active.current?.abort();operation.current?.abort();setPicker(false);setCandidates([]);setSaving(false);
    if(!current||!body){setLoading(false);return;}
    setLoading(true);
    api.request<{items:ObjectPhoto[]}>('/api/workbench/objects/photos/resolve',body,abort.signal)
      .then(value=>{if(!abort.signal.aborted)setPhotos(value.items);}).catch(error=>{if(!abort.signal.aborted&&!cancelled(error))setError(error);})
      .finally(()=>{if(!abort.signal.aborted)setLoading(false);});
    return()=>{abort.abort();operation.current?.abort();};
  },[api,api.epoch,api.revision,current?.item.entityUid,current?.item.entityRevision,current?.context?.hierarchyRevision,purpose,reload]);
  async function chooseFieldPhoto(cursor:string|null=null){
    operation.current?.abort();const abort=new AbortController();operation.current=abort;
    setPicker(true);setError(null);setCandidatesLoading(true);
    if(!cursor){setCandidates([]);setCandidate(null);setNext(null);}
    try{const value=await api.request<{items:PhotoCandidate[];nextCursor:string|null}>('/api/workbench/equipment/photo-candidates',cursor?{cursor}:{},abort.signal);
      if(!abort.signal.aborted){setCandidates(rows=>cursor?[...rows,...value.items]:value.items);setNext(value.nextCursor);}}
    catch(error){if(!abort.signal.aborted&&!cancelled(error))setError(error);}
    finally{if(!abort.signal.aborted)setCandidatesLoading(false);}
  }

  async function associate(){if(!device||!candidate||!device.context)return;operation.current?.abort();const abort=new AbortController();operation.current=abort;setSaving(true);setError(null);try{
    await api.request('/api/workbench/equipment/photos/associate',{entityUid:device.item.entityUid,expectedEntityRevision:device.item.entityRevision,expectedHierarchyRevision:device.context.hierarchyRevision,
      documentId:candidate.documentId,contentVersionId:candidate.contentVersionId,renditionId:candidate.renditionId,expectedDisplayRevision:candidate.displayRevision,
      basis:en?'User associates a device field photo':'用户关联此设备的现场照片',clientRequestId:crypto.randomUUID()},abort.signal);if(!abort.signal.aborted){setPicker(false);setReload(value=>value+1);}
    }catch(error){if(!abort.signal.aborted&&!cancelled(error))setError(error);}finally{if(!abort.signal.aborted)setSaving(false);}}
  async function open(photo:ObjectPhoto,full=false){
    if(!body)return;
    setOriginal(full);
    active.current?.abort();const abort=new AbortController();active.current=abort;setChosen(photo);setImage('');setError(null);
    const key=JSON.stringify([api.epoch,api.revision,photo.documentId,photo.contentVersionId,photo.selector?.displayRevision,photo.sourceSha256,full]);
    const cached=cache.current.get(key);if(cached){setImage(cached);return;}
    try{
      const blob=await new EquipmentApi(api).photoContent(body,photo,full,abort.signal);
      if(abort.signal.aborted)return;
      if(cache.current.size>=8){const first=cache.current.keys().next().value;if(first){URL.revokeObjectURL(cache.current.get(first)!);cache.current.delete(first);}}
      const url=URL.createObjectURL(blob);cache.current.set(key,url);setImage(url);
    }catch(error){if(!cancelled(error)&&!abort.signal.aborted)setError(error);}
  }
  return <section className="eq-photos"><div className="eq-tabs" role="tablist" aria-label={en?'Photo purpose':'照片用途'}>
    <button role="tab" aria-selected={purpose==='object_location'} onClick={()=>setPurpose('object_location')}>{en?'Object location photos':'对象定位照片'}</button>
    <button role="tab" aria-selected={purpose==='field_record'} onClick={()=>setPurpose('field_record')}>{en?'Field photos':'现场照片'}</button></div>
    <p className="eq-caption">{purpose==='object_location'?(en?'Shared by the same project and configuration':'同项目同型号共享照片和标注区域'):(device?.item.displayName||(en?'Select a device':'选择设备查看本机照片'))}</p>
    {purpose==='field_record'&&device&&canWrite&&<Btn onClick={()=>void chooseFieldPhoto()}>{en?'Associate a project photo':'关联已有项目照片'}</Btn>}
    {loading?<p role="status">{en?'Loading photos…':'正在读取照片…'}</p>:error?<p role="alert">{failureMessage(error,en?'en':'zh')}</p>:photos.length?photos.map(photo=><div className="eq-photo-row" key={photo.evidenceRef}><span>{photo.title}</span><Btn onClick={()=>void open(photo)}>{en?'Open photo':'打开照片'}</Btn></div>):<p className="eq-caption">{purpose==='field_record'?(en?'No field photos for this device':'当前设备暂无现场照片'):(en?'No object location photos':'当前对象暂无定位照片')}</p>}
    {chosen&&<Modal title={chosen.title} description={purpose==='object_location'?(en?'Shared object location':'共享工程对象定位'):(device?.item.displayName??'')} onClose={()=>{active.current?.abort();setChosen(null);setImage('');}}>
      <Btn onClick={()=>void open(chosen,!original)}>{original?(en?'Fast preview':'快速预览'):(en?'Full resolution':'原尺寸')}</Btn>
      {image?<WorkOrderPhotoViewport image={image} selector={purpose==='field_record'?null:chosen.selector} label={chosen.title} en={en} focusFraction={.35} onError={()=>setImage('')}/>:<p role={error?'alert':'status'}>{error?failureMessage(error,en?'en':'zh'):(en?'Loading photo…':'正在载入照片…')}</p>}
    </Modal>}
    {picker&&<Modal title={en?'Associate field photo':'关联现场照片'} description={device?.item.displayName??''} onClose={()=>{if(!saving)setPicker(false);}}><div className="eq-adoption-list">{candidates.map(photo=><label key={photo.documentId}><input type="radio" name="field-photo" checked={candidate?.documentId===photo.documentId} onChange={()=>setCandidate(photo)}/>{photo.title}</label>)}</div>{candidatesLoading&&<p role="status">{en?'Loading project photos…':'正在读取项目照片…'}</p>}{next&&<Btn disabled={candidatesLoading||saving} onClick={()=>void chooseFieldPhoto(next)}>{en?'Load more':'加载更多'}</Btn>}{!!error&&<p role="alert">{failureMessage(error,en?'en':'zh')}</p>}<Btn primary disabled={!candidate||saving} onClick={()=>void associate()}>{en?'Save association':'保存关联'}</Btn></Modal>}
  </section>;
}
