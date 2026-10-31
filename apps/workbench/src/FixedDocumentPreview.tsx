import {useEffect,useMemo,useRef,useState} from 'react';
import {ChevronLeft,ChevronRight,RefreshCw} from 'lucide-react';
import {cancelled,failureMessage,type WorkbenchApi} from './api';
import {EquipmentApi,type EquipmentMaterial,type FixedDocument} from './equipmentApi';
import {Btn,Modal} from './Primitives';
import {WorkOrderPhotoViewport} from './WorkOrderPhotoViewport';

export function FixedDocumentPreview({api,item,en,onClose}:{api:WorkbenchApi;item:EquipmentMaterial;en:boolean;onClose:()=>void}){
 const service=useMemo(()=>new EquipmentApi(api),[api]);
 const [fixed,setFixed]=useState<FixedDocument|null>(null),[page,setPage]=useState(1),[image,setImage]=useState(''),[error,setError]=useState<unknown>(null),[retry,setRetry]=useState(0),[pending,setPending]=useState(false),[stopped,setStopped]=useState(false),[original,setOriginal]=useState(false);
 const files=useRef(new Map<string,{url:string;bytes:number}>()),active=useRef<AbortController|null>(null);
 useEffect(()=>{const abort=new AbortController();setFixed(null);setImage('');setError(null);
  void service.materialMetadata(item.documentId,item.contentVersionId,abort.signal).then(value=>{if(!abort.signal.aborted)setFixed(value);}).catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setError(e);});
  return()=>abort.abort();
 },[service,api.epoch,api.revision,item.documentId,item.contentVersionId,retry]);
 useEffect(()=>{if(!fixed)return;const abort=new AbortController();active.current=abort;setImage('');setError(null);setPending(true);setStopped(false);
  const key=JSON.stringify([fixed.documentId,fixed.contentVersionId,fixed.sourceSha256,page,original]);
  const cached=files.current.get(key);
  if(cached){setImage(cached.url);setPending(false);return()=>abort.abort();}
  void service.materialContent(fixed,page,abort.signal,original?'display':'preview').then(blob=>{if(abort.signal.aborted)return;
   const url=URL.createObjectURL(blob);files.current.set(key,{url,bytes:blob.size});
   while(files.current.size>12||[...files.current.values()].reduce((sum,x)=>sum+x.bytes,0)>64*1024*1024){const first=files.current.keys().next().value!;URL.revokeObjectURL(files.current.get(first)!.url);files.current.delete(first);}
   setImage(url);
  }).catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setError(e);}).finally(()=>{if(!abort.signal.aborted)setPending(false);});
  return()=>abort.abort();
 },[service,fixed,page,original,api.epoch,api.revision]);
 useEffect(()=>()=>{active.current?.abort();for(const value of files.current.values())URL.revokeObjectURL(value.url);files.current.clear();},[api,api.epoch,api.revision]);
 return <Modal className="eq-material-preview" title={item.title} description={en?'Protected fixed document version':'受保护的固定文档版本'} onClose={onClose}>
  <div className="eq-material-preview-bar">{fixed&&<><span>{en?'Fixed version':'固定版本'} v{fixed.versionNumber}</span>{fixed.kind==='pdf'&&<><Btn disabled={page<=1} onClick={()=>setPage(v=>v-1)}><ChevronLeft size={14}/>{en?'Previous':'上一页'}</Btn><label>{en?'Page':'页码'} <input aria-label={en?'Material page':'资料页码'} type="number" min={1} max={fixed.pageCount} value={page} onChange={e=>{const n=Number(e.target.value);if(Number.isInteger(n)&&n>=1&&n<=fixed.pageCount)setPage(n);}}/> / {fixed.pageCount}</label><Btn disabled={page>=fixed.pageCount} onClick={()=>setPage(v=>v+1)}>{en?'Next':'下一页'}<ChevronRight size={14}/></Btn></>}{fixed.newerVersionAvailable&&<small>{en?'Newer version available; retaining this version.':'已有新版；保持当前固定版本。'}</small>}</>}
   {fixed?.kind==='photo'&&<><span>{original?(en?'Original dimensions':'原尺寸'):(en?'Preview image':'预览图')}</span><Btn onClick={()=>setOriginal(v=>!v)}>{original?(en?'Back to preview':'返回预览'):(en?'Original dimensions':'原尺寸')}</Btn></>}{pending&&<Btn onClick={()=>{active.current?.abort();setPending(false);setStopped(true);}}>{en?'Cancel loading':'取消读取'}</Btn>}
  </div>
  {!!error&&<p role="alert">{failureMessage(error,en?'en':'zh')}</p>}
  {image?<WorkOrderPhotoViewport key={page+':'+image} embedded image={image} selector={null} label={item.title} en={en} onError={()=>setError(new Error('Image unavailable'))}/>:<div className="eq-material-wait" role="status">{stopped?(en?'Loading cancelled':'已取消读取'):error?(en?'Source unavailable':'资料暂不可用'):(en?'Loading material…':'正在读取资料…')}<Btn onClick={()=>setRetry(v=>v+1)}><RefreshCw size={14}/>{en?'Read again':'重新读取'}</Btn></div>}
  <p className="eq-caption">{en?'Whole page or photo. No object region was supplied.':'显示整页或整张照片；此目录未声明对象定位区域。'}</p>
 </Modal>;
}
