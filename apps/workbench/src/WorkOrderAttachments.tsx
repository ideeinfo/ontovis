import {useEffect, useRef, useState} from 'react';
import {Download, FileText, Paperclip, Plus, Search} from 'lucide-react';
import {ApiError, cancelled} from './api';
import {Btn, Modal} from './Primitives';
import {ORDER_ROOT, orderFailure, type AttachmentOrder, type DocumentVersion, type FixedAttachment,
  type OrderApi, type TreatmentRecord} from './workOrderWorkflow';
import './workOrderWorkflow.css';

const ATTACHMENTS = ORDER_ROOT+'/attachments';
const PART_BYTES = 4*1024*1024;
const FILE_TYPES = '.pdf,.docx,.xlsx,.doc,.xls,.ppt,.pptx,.md,.txt,.csv,.json,.jsonld,.ttl,.png,.jpg,.jpeg,.webp,.svg,.mp4';

type Upload = {file:File; uploadId:string; sha?:string; fixed?:DocumentVersion};

export function WorkOrderAttachmentForm({api, order, en, records, recordId, onAttach, onClose, locked=false, notice}:{
  api:OrderApi; order:AttachmentOrder; en:boolean; records:TreatmentRecord[]; recordId?:string;
  onAttach:(version:DocumentVersion, recordId:string)=>Promise<boolean>; onClose:()=>void; locked?:boolean;
  notice?:import('react').ReactNode;
}) {
  const t=(zh:string,english:string)=>en?english:zh;
  const [mode,setMode]=useState<'upload'|'link'>('upload');
  const [target,setTarget]=useState(recordId||'');
  const [file,setFile]=useState<File|null>(null);
  const [query,setQuery]=useState('');
  const [matches,setMatches]=useState<DocumentVersion[]>([]);
  const [next,setNext]=useState<string|null>(null);
  const [fixed,setFixed]=useState<DocumentVersion|null>(null);
  const [busy,setBusy]=useState(false);
  const [progress,setProgress]=useState('');
  const [error,setError]=useState<unknown>(null);
  const upload=useRef<Upload|null>(null);
  const request=useRef<AbortController|null>(null);
  useEffect(()=>()=>request.current?.abort(),[]);

  async function search(cursor?:string) {
    const abort=new AbortController();request.current?.abort();request.current=abort;
    setBusy(true);setError(null);
    try {
      const result=await api.request<{items:DocumentVersion[];nextCursor:string|null}>(ATTACHMENTS+'/catalogue',
        {q:query.trim(),...(cursor?{cursor}:{})},abort.signal);
      if(!abort.signal.aborted){
        setMatches(rows=>cursor?[...rows,...result.items]:result.items);setNext(result.nextCursor);
      }
    } catch(value){if(!cancelled(value))setError(value);}
    finally{if(!abort.signal.aborted)setBusy(false);}
  }

  async function submit() {
    if(busy||locked)return;
    setBusy(true);setError(null);
    const abort=new AbortController();request.current=abort;
    try {
      let version=fixed;
      if(mode==='upload'){
        const job=upload.current;
        if(!job)return;
        const max=(/\.(png|jpe?g|webp)$/i.test(job.file.name)?32:128)*1024*1024;
        if(job.file.size<=0||job.file.size>max)throw new ApiError(413,'CONTENT_SIZE_LIMIT');
        if(!job.fixed){
          setProgress(t('正在核对文件','Checking file'));
          if(!job.sha){
            const hash=await crypto.subtle.digest('SHA-256',await job.file.arrayBuffer());
            job.sha=Array.from(new Uint8Array(hash),x=>x.toString(16).padStart(2,'0')).join('');
          }
          const scope={orderId:order.orderId,expectedOrderRevision:order.orderRevision,uploadId:job.uploadId};
          const start=await api.request<{uploadId:string;partBytes:number;parts:Record<string,{bytes:number}>}>(
            ATTACHMENTS+'/start',{...scope,filename:job.file.name,byteSize:job.file.size,sourceSha256:job.sha},abort.signal);
          if(start.uploadId!==job.uploadId||start.partBytes!==PART_BYTES)throw new ApiError(502,'SOURCE_UNAVAILABLE');
          const count=Math.ceil(job.file.size/PART_BYTES);
          for(let index=0;index<count;index++){
            const chunk=job.file.slice(index*PART_BYTES,(index+1)*PART_BYTES);
            setProgress(t('正在上传','Uploading')+' '+(index+1)+' / '+count);
            if(start.parts[String(index)]?.bytes!==chunk.size)
              await api.uploadWorkOrderPart(chunk,{...scope,index},abort.signal);
          }
          setProgress(t('正在确认文件版本','Checking uploaded revision'));
          job.fixed=await api.request<DocumentVersion>(ATTACHMENTS+'/complete',scope,abort.signal);
        }
        version=job.fixed;
        setProgress(t('文件已入库，正在加入本单','File stored. Linking to this order.'));
      }
      if(version&&!abort.signal.aborted&&await onAttach(version,target))onClose();
    } catch(value){if(!cancelled(value))setError(value);}
    finally{if(!abort.signal.aborted)setBusy(false);}
  }

  return <Modal title={t('添加附件','Add attachment')} description={order.orderId} onClose={()=>!busy&&!locked&&onClose()}>
    <div className="wov-form">
      {notice}
      <div className="wov-actions">
        <Btn aria-pressed={mode==='upload'} disabled={busy||locked} onClick={()=>setMode('upload')}><Plus size={15}/>{t('上传文件','Upload file')}</Btn>
        <Btn aria-pressed={mode==='link'} disabled={busy||locked} onClick={()=>{setMode('link');if(!matches.length)void search();}}><Paperclip size={15}/>{t('引用已有资料','Link existing file')}</Btn>
      </div>
      {mode==='upload'?<label>{t('文档或照片','Document or photo')}
        <input type="file" accept={FILE_TYPES} disabled={busy||locked} onChange={event=>{
          const choice=event.target.files?.[0]||null;setFile(choice);setProgress('');setError(null);
          upload.current=choice?{file:choice,uploadId:crypto.randomUUID()}:null;
        }}/><small>{t('照片最多 32 MiB，文档最多 128 MiB。','Photos up to 32 MiB, documents up to 128 MiB.')}</small>
      </label>:<>
        <form className="wov-search" onSubmit={event=>{event.preventDefault();void search();}}>
          <input aria-label={t('搜索已有资料','Search existing files')} value={query} maxLength={200} onChange={event=>setQuery(event.target.value)}/>
          <Btn type="submit" disabled={busy||locked}><Search size={15}/>{t('搜索','Search')}</Btn>
        </form>
        <div className="wov-file-options">{matches.map(item=><button type="button" key={item.contentVersionId}
          aria-pressed={fixed?.contentVersionId===item.contentVersionId} disabled={busy||locked} onClick={()=>setFixed(item)}>
          <FileText size={15}/><span>{item.title}</span>
        </button>)}{!matches.length&&!busy&&<small>{t('暂无匹配资料','No matching files')}</small>}</div>
        {next&&<Btn disabled={busy||locked} onClick={()=>void search(next)}>{t('更多资料','More files')}</Btn>}
      </>}
      <label>{t('关联位置','Attach to')}<select value={target} disabled={busy||locked} onChange={event=>setTarget(event.target.value)}>
        <option value="">{t('整个工单','Work order')}</option>
        {records.map(row=><option key={row.recordId} value={row.recordId}>{row.text.slice(0,64)}</option>)}
      </select></label>
      {progress&&<p role="status">{progress}</p>}
      {!!error&&<p role="alert">{orderFailure(error,en)}</p>}
      <div className="wov-actions end"><Btn disabled={busy||locked} onClick={onClose}>{t('取消','Cancel')}</Btn>
        <Btn primary disabled={busy||locked||!(mode==='upload'?file:fixed)} onClick={()=>void submit()}>
          {upload.current?.fixed&&mode==='upload'?t('重试关联','Retry link'):t('加入本单','Attach to order')}
        </Btn></div>
    </div>
  </Modal>;
}

export function WorkOrderAttachmentView({api, order, item, en, onClose}:{
  api:Pick<OrderApi,'request'>&Partial<Pick<OrderApi,'content'>>; order:AttachmentOrder; item:FixedAttachment; en:boolean; onClose:()=>void;
}) {
  const t=(zh:string,english:string)=>en?english:zh;
  const [page,setPage]=useState(1);
  const [picture,setPicture]=useState('');
  const [error,setError]=useState<unknown>(null);
  const [loading,setLoading]=useState(item.previewAvailable);
  const [downloading,setDownloading]=useState(false);
  const download=useRef<AbortController|null>(null);
  const body={orderId:order.orderId,orderRevision:order.orderRevision,snapshotSha256:order.snapshotSha256,
    attachmentId:item.attachmentId};
  useEffect(()=>()=>download.current?.abort(),[]);
  useEffect(()=>{
    if(!item.previewAvailable)return;
    const abort=new AbortController();let url='';setPicture('');setLoading(true);setError(null);
    void api.request<Blob>(ATTACHMENTS+'/content',{...body,pageNumber:page},abort.signal,'source')
      .then(blob=>{if(!abort.signal.aborted){url=URL.createObjectURL(blob);setPicture(url);}})
      .catch(value=>{if(!abort.signal.aborted)setError(value);})
      .finally(()=>{if(!abort.signal.aborted)setLoading(false);});
    return()=>{abort.abort();if(url)URL.revokeObjectURL(url);};
  },[api,order.orderId,order.orderRevision,order.snapshotSha256,item.attachmentId,item.previewAvailable,page]);

  async function downloadOriginal(){
    if(!api.content)return;
    const abort=new AbortController();download.current=abort;setDownloading(true);setError(null);
    try{
      const blob=await api.content(ATTACHMENTS+'/content',body,
        {mime:'application/octet-stream',maxBytes:item.byteSize,sha256:item.sourceSha256},abort.signal);
      if(abort.signal.aborted)return;
      const url=URL.createObjectURL(blob);
      const link=document.createElement('a');link.href=url;link.download=item.filename;link.click();
      window.setTimeout(()=>URL.revokeObjectURL(url),1000);
    }catch(value){if(!abort.signal.aborted)setError(value);}
    finally{if(!abort.signal.aborted)setDownloading(false);}
  }
  return <Modal className="wov-wide-dialog" title={item.title} description={order.orderId+' · v'+item.versionNumber} onClose={onClose}>
    <div className="wov-form">
      <div className="wov-actions">
        {item.previewKind==='pdf'&&(item.pageCount||0)>1&&<label>{t('页码','Page')}<select value={page}
          onChange={event=>setPage(Number(event.target.value))}>{Array.from({length:item.pageCount||0},(_,i)=><option key={i} value={i+1}>{i+1}</option>)}</select></label>}
        {api.content&&<Btn disabled={downloading} onClick={()=>void downloadOriginal()}><Download size={16}/>{t('下载原件','Download original')}</Btn>}
      </div>
      {loading&&<p role="status">{t('正在读取固定附件','Loading fixed attachment')}</p>}
      {!!error&&<p role="alert">{orderFailure(error,en)}</p>}
      {picture&&<img className="wov-file-preview" alt={item.title} src={picture}/>}
    </div>
  </Modal>;
}
