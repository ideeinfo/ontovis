import {useEffect,useMemo,useRef,useState} from 'react';
import {ChevronLeft,ChevronRight,RefreshCw} from 'lucide-react';
import {ApiError,cancelled,failureMessage,type WorkbenchApi} from './api';
import {EquipmentApi,type EquipmentMaterial,type FixedDocument} from './equipmentApi';
import {Btn,Modal} from './Primitives';
import {WorkOrderPhotoViewport} from './WorkOrderPhotoViewport';
import './equipmentMaterials.css';

export type FixedDocumentTarget=Pick<EquipmentMaterial,'documentId'|'contentVersionId'|'title'>;

interface DocumentComparison {
 versionNumber:number;
 pageNumber:number;
 addAsNew:boolean;
 onUse?:(fixed:FixedDocument,page:number)=>Promise<boolean>;
}

export function FixedDocumentPreview({api,item,en,onClose,comparison}:{api:Pick<WorkbenchApi,'request'|'epoch'|'revision'>;
 item:FixedDocumentTarget;en:boolean;onClose:()=>void;comparison?:DocumentComparison}){
 const service=useMemo(()=>new EquipmentApi(api),[api]);
 const [fixed,setFixed]=useState<FixedDocument|null>(null),[page,setPage]=useState(comparison?.pageNumber||1),[image,setImage]=useState(''),[error,setError]=useState<unknown>(null),[retry,setRetry]=useState(0),[pending,setPending]=useState(false),[stopped,setStopped]=useState(false),[original,setOriginal]=useState(false);
 const [imagePage,setImagePage]=useState(0),[using,setUsing]=useState(false),[useFailed,setUseFailed]=useState(false);
 const comparing=!!comparison,canUse=!!image&&imagePage===page&&!error&&!pending&&!using;
 const files=useRef(new Map<string,{url:string;bytes:number}>()),active=useRef<AbortController|null>(null);
 useEffect(()=>{const abort=new AbortController();setFixed(null);setImage('');setError(null);
  void service.materialMetadata(item.documentId,item.contentVersionId,abort.signal).then(value=>{
   if(abort.signal.aborted)return;
   if(comparing&&(value.documentId!==item.documentId||value.contentVersionId!==item.contentVersionId||value.kind!=='pdf')){
    throw new ApiError(409,'SOURCE_CHANGED');
   }
   if(comparing)setPage(current=>current<=value.pageCount?current:1);
   setFixed(value);
  }).catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setError(e);});
  return()=>abort.abort();
 },[service,api.epoch,api.revision,item.documentId,item.contentVersionId,retry,comparing]);
 useEffect(()=>{if(!fixed)return;const abort=new AbortController();active.current=abort;setImage('');setError(null);setPending(true);setStopped(false);
  const key=JSON.stringify([fixed.documentId,fixed.contentVersionId,fixed.sourceSha256,page,original]);
  const cached=files.current.get(key);
  if(cached){setImage(cached.url);setImagePage(page);setPending(false);return()=>abort.abort();}
  void service.materialContent(fixed,page,abort.signal,original?'display':'preview').then(blob=>{if(abort.signal.aborted)return;
   const url=URL.createObjectURL(blob);files.current.set(key,{url,bytes:blob.size});
   while(files.current.size>12||[...files.current.values()].reduce((sum,x)=>sum+x.bytes,0)>64*1024*1024){const first=files.current.keys().next().value!;URL.revokeObjectURL(files.current.get(first)!.url);files.current.delete(first);}
   setImage(url);setImagePage(page);
  }).catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setError(e);}).finally(()=>{if(!abort.signal.aborted)setPending(false);});
  return()=>abort.abort();
 },[service,fixed,page,original,api.epoch,api.revision]);
 useEffect(()=>()=>{active.current?.abort();for(const value of files.current.values())URL.revokeObjectURL(value.url);files.current.clear();},[api,api.epoch,api.revision]);
 async function useVersion(){
  if(!comparison?.onUse||!fixed||!canUse)return;
  setUsing(true);setUseFailed(false);
  try{if(await comparison.onUse(fixed,page))onClose();else setUseFailed(true);}
  catch{setUseFailed(true);}
  finally{setUsing(false);}
 }
 return <Modal className="eq-material-preview" title={comparing?(en?'Compare document versions':'对照文档版本'):item.title}
  description={en?'Protected fixed document version':'受保护的固定文档版本'} onClose={onClose} closeDisabled={using}>
  {comparison&&<div className="eq-material-comparison"><strong>{item.title}</strong><small>
   {en?`Canvas reference · v${comparison.versionNumber}, page ${comparison.pageNumber}`:`画布引用 · v${comparison.versionNumber} · 第 ${comparison.pageNumber} 页`}
  </small></div>}
  <div className="eq-material-preview-bar">{fixed&&<><span>{comparing?(en?'Compared version':'对照版本'):(en?'Fixed version':'固定版本')} v{fixed.versionNumber}</span>{fixed.kind==='pdf'&&<><Btn disabled={using||page<=1} onClick={()=>setPage(v=>v-1)}><ChevronLeft size={14}/>{en?'Previous':'上一页'}</Btn><label>{en?'Page':'页码'} <input aria-label={en?'Material page':'资料页码'} disabled={using} type="number" min={1} max={fixed.pageCount} value={page} onChange={e=>{const n=Number(e.target.value);if(Number.isInteger(n)&&n>=1&&n<=fixed.pageCount)setPage(n);}}/> / {fixed.pageCount}</label><Btn disabled={using||page>=fixed.pageCount} onClick={()=>setPage(v=>v+1)}>{en?'Next':'下一页'}<ChevronRight size={14}/></Btn></>}{fixed.newerVersionAvailable&&<small>{comparing?(en?'A different version is now current.':'资料库的当前版本已有变化。'):(en?'Newer version available; retaining this version.':'已有新版；保持当前固定版本。')}</small>}</>}
   {fixed?.kind==='photo'&&<><span>{original?(en?'Original dimensions':'原尺寸'):(en?'Preview image':'预览图')}</span><Btn onClick={()=>setOriginal(v=>!v)}>{original?(en?'Back to preview':'返回预览'):(en?'Original dimensions':'原尺寸')}</Btn></>}{pending&&<Btn onClick={()=>{active.current?.abort();setPending(false);setStopped(true);}}>{en?'Cancel loading':'取消读取'}</Btn>}
  </div>
  {!!error&&<p role="alert">{failureMessage(error,en?'en':'zh')}</p>}
  {image?<WorkOrderPhotoViewport key={page+':'+image} embedded image={image} selector={null} label={item.title} en={en} onError={()=>setError(new Error('Image unavailable'))}/>:<div className="eq-material-wait" role="status">{stopped?(en?'Loading cancelled':'已取消读取'):error?(en?'Source unavailable':'资料暂不可用'):(en?'Loading material…':'正在读取资料…')}<Btn onClick={()=>setRetry(v=>v+1)}><RefreshCw size={14}/>{en?'Read again':'重新读取'}</Btn></div>}
  {comparison?.onUse?<div className="eq-material-comparison-actions">
   {useFailed&&<p role="alert">{en?'Canvas reference could not be updated.':'此次未能更新画布引用。'}</p>}
   <Btn disabled={using} onClick={onClose}>{en?'Cancel':'取消'}</Btn>
   <Btn primary disabled={!canUse} onClick={()=>void useVersion()}>
    {using?(en?'Updating…':'正在更新…'):comparison.addAsNew?(en?'Add this version':'将此版本加入画布'):(en?'Use this version':'采用此版本')}
   </Btn>
  </div>:!comparing&&<p className="eq-caption">{en?'Whole page or photo. No object region was supplied.':'显示整页或整张照片；此目录未声明对象定位区域。'}</p>}
 </Modal>;
}
