import {useEffect,useMemo,useRef,useState} from 'react';
import {Image,RefreshCw} from 'lucide-react';
import {ApiError,cancelled} from './api';
import {Btn,IconBtn,Modal} from './Primitives';
import {usePreferences} from './Preferences';
import {RowContext} from './ListMenus';
import {privateDenial,ResourceRequestGate,ResourceRequestId,writeDenial} from './resourceForms';
import type {SceneApi} from './sceneApi';
import type {ImageryCatalog,ImageryRecord,ImageryVersion,UploadImageryMetadata,ImageryUploadSession} from './resourceTypes';
import {imageryFailure,imageryText} from './imageryMessages';
import {checkImageryUpload,prepareImageryUpload,sendImageryUpload,uncertainImageryUpload,type PendingImageryUpload,type ImageryUploadProgress} from './imageryUpload';

export function ImageryFacts({value}:{value:ImageryRecord}) {
  const {locale}=usePreferences(),t=(key:Parameters<typeof imageryText>[1])=>imageryText(locale,key),r=value.report,m=value.metadata;
  return <details className="ov-resource-disclosure"><summary>{t('details')}</summary><dl className="ov-resource-facts">
    <dt>{t('date')}</dt><dd>{m.acquiredAt}</dd><dt>{t('source')}</dt><dd>{m.sourceNote}</dd><dt>{t('license')}</dt><dd>{m.licenseNote}</dd>
    <dt>{t('quality')}</dt><dd>{m.qualityNote}</dd><dt>{t('attribution')}</dt><dd>{m.attribution}</dd>
    <dt>{t('report')}</dt><dd>{r.horizontalCrs} · {r.width} × {r.height}<br/>{r.coverageWgs84.map(v=>v.toFixed(6)).join(', ')}</dd>
    <dt>{t('transparent')}</dt><dd>{r.transparentPixels.toLocaleString(locale)}</dd><dt>{t('pinned')}</dt><dd className="ov-resource-id">{value.imageryVersionId}</dd>
  </dl><p className="ov-resource-caption">{t('precision')} · {t('height')}</p></details>;
}

export function ImageryPanel({api,canUse,writeBlocked,onUse,onPrivateDenied,onWriteDenied}:{api:SceneApi;canUse:boolean;writeBlocked:boolean;
  onUse:(value:ImageryVersion)=>void;onPrivateDenied:()=>void;onWriteDenied:()=>void}){
  const {locale}=usePreferences(),t=(key:Parameters<typeof imageryText>[1])=>imageryText(locale,key);
  const [catalog,setCatalog]=useState<ImageryCatalog|null>(null),[version,setVersion]=useState<ImageryVersion|null>(null);
  const [query,setQuery]=useState(''),[error,setError]=useState<unknown>(null),[busy,setBusy]=useState(false),[open,setOpen]=useState(false),[uploading,setUploading]=useState(false);
  const [file,setFile]=useState<File|null>(null),[form,setForm]=useState({displayName:'',sourceNote:'',licenseNote:'',attribution:'',acquiredAt:'',qualityNote:'',rightsDeclared:false});
  const [pending,setPending]=useState<PendingImageryUpload|null>(null);
  const [checking,setChecking]=useState(false);
  const [resuming,setResuming]=useState<ImageryUploadSession|null>(null),[progress,setProgress]=useState<ImageryUploadProgress|null>(null);
  const listGate=useMemo(()=>new ResourceRequestGate(),[]),versionGate=useMemo(()=>new ResourceRequestGate(),[]),uploadGate=useMemo(()=>new ResourceRequestGate(),[]),id=useRef(new ResourceRequestId());
  function failed(value:unknown){if(cancelled(value))return;if(privateDenial(value)){listGate.cancel();versionGate.cancel();uploadGate.cancel();setCatalog(null);setVersion(null);setFile(null);setPending(null);setResuming(null);setProgress(null);setOpen(false);onPrivateDenied();return;}if(writeDenial(value))onWriteDenied();setError(value);}
  async function read(){const request=listGate.start();setBusy(true);setError(null);try{const result=await api.imagery(query,request.signal);if(request.isCurrent())setCatalog(result);}catch(value){if(request.isCurrent())failed(value);}finally{if(request.isCurrent())setBusy(false);}}
  useEffect(()=>{void read();return()=>{listGate.cancel();versionGate.cancel();uploadGate.cancel();};},[api]);
  async function select(item:ImageryRecord){const request=versionGate.start();setBusy(true);setVersion(null);setError(null);try{const value=await api.imageryVersion(item.imageryVersionId,request.signal);if(value.contentRevision!==item.contentRevision||value.expectedReportSha256!==item.expectedReportSha256)throw new ApiError(409,'RESOURCE_CHANGED');if(request.isCurrent())setVersion(value);}catch(value){if(request.isCurrent())failed(value);}finally{if(request.isCurrent())setBusy(false);}}
  function finished(value:ImageryVersion){setOpen(false);setFile(null);setPending(null);setResuming(null);setProgress(null);id.current.reset();setVersion(value);void read();}
  function pause(){uploadGate.cancel();setUploading(false);setChecking(false);setError(new ApiError(503,'IMAGERY_UPLOAD_PAUSED'));}
  function resume(item:ImageryUploadSession){if(uploading||pending)return;const {clientRequestId:_,...fields}=item.metadata;
    setResuming(item);setForm(fields);setFile(null);setProgress({receivedBytes:item.receivedBytes,bytes:item.bytes,phase:'receiving',upload:item});setError(null);setOpen(true);}
  async function discard(item?:ImageryUploadSession){if(uploading)return;const request=uploadGate.start();setUploading(true);setChecking(true);setError(null);
    try{let target=item;
      if(!target&&pending){try{const value=await checkImageryUpload(api,pending,request.signal);if(request.isCurrent())finished(value);return;}
        catch(error){if(!(error instanceof ApiError&&error.code==='IMAGERY_UPLOAD_UNCONFIRMED'))throw error;}
        const current=await api.imagery('',request.signal);target=current.uploads?.find(row=>row.metadata.clientRequestId===pending.metadata.clientRequestId);}
      if(target){const current=await api.imageryUploadStatus(target.uploadId,request.signal);
        if(current.state==='completed'){if(request.isCurrent())finished(current);return;}
        const result=await api.imageryUploadCancel(current.uploadId,current.uploadRevision,request.signal);
        if(result.state==='completed'){if(request.isCurrent())finished(result);return;}}
      if(request.isCurrent()){setPending(null);setResuming(null);setProgress(null);setFile(null);setOpen(false);id.current.reset();void read();}
    }catch(value){if(request.isCurrent())failed(value);}finally{if(request.isCurrent()){setUploading(false);setChecking(false);}}
  }
  function unresolved(value:unknown){if(cancelled(value))return;
    if(value instanceof ApiError&&value.status<500&&value.status!==429){failed(value);}
    else setError(new ApiError(503,'IMAGERY_UPLOAD_UNCONFIRMED'));
  }
  async function checkResult(){if(!pending||uploading)return;const request=uploadGate.start();setUploading(true);setChecking(true);setError(null);
    try{const value=await checkImageryUpload(api,pending,request.signal);if(request.isCurrent())finished(value);}
    catch(value){if(request.isCurrent())unresolved(value);}finally{if(request.isCurrent()){setUploading(false);setChecking(false);}}
  }
  async function upload(){if(uploading||writeBlocked||!catalog?.capabilities.canUpload)return;setError(null);
    if(!pending&&(!file||!/\.tiff?$/i.test(file.name)||file.size<8||file.size>catalog.limits.maxUploadBytes||!form.rightsDeclared||Object.entries(form).some(([key,v])=>key!=='rightsDeclared'&&typeof v==='string'&&!v.trim())||!/^\d{4}-\d{2}-\d{2}$/.test(form.acquiredAt))){setError(new Error(t('fileInvalid')));return;}
    const request=uploadGate.start();setUploading(true);let attempt=pending;
    try{
      if(!attempt){const payload={...form,rightsDeclared:true as const},clientRequestId=resuming?.metadata.clientRequestId??id.current.forPayload(payload,`${file!.name}:${file!.size}:${file!.lastModified}`);
        attempt=await prepareImageryUpload(file!,{...payload,clientRequestId} as UploadImageryMetadata,request.signal);if(!request.isCurrent())return;
        if(resuming&&(attempt.expectedSourceSha256!==resuming.sha256||attempt.file.size!==resuming.bytes))throw new ApiError(409,'IMAGERY_CHUNK_CHANGED');setPending(attempt);}
      else{setChecking(true);try{const value=await checkImageryUpload(api,attempt,request.signal);if(request.isCurrent())finished(value);return;}
        catch(value){if(!(value instanceof ApiError&&value.code==='IMAGERY_UPLOAD_UNCONFIRMED'))throw value;}if(!request.isCurrent())return;setChecking(false);}
      try{const value=await sendImageryUpload(api,attempt,{signal:request.signal,progress:value=>{if(request.isCurrent())setProgress(value);}});if(request.isCurrent())finished(value);}
      catch(value){if(!request.isCurrent())return;if(!uncertainImageryUpload(value)){throw value;}
        setChecking(true);const recovered=await checkImageryUpload(api,attempt,request.signal);if(request.isCurrent())finished(recovered);}
    }catch(value){if(request.isCurrent()){if(attempt)unresolved(value);else failed(value);}}finally{if(request.isCurrent()){setUploading(false);setChecking(false);}}
  }
  return <section className="ov-terrain-panel"><div className="ov-resource-actions"><Btn disabled={!pending&&(writeBlocked||!catalog?.capabilities.canUpload)} onClick={()=>{setOpen(true);if(!pending&&!file&&!resuming){setProgress(null);setForm({displayName:'',sourceNote:'',licenseNote:'',attribution:'',acquiredAt:'',qualityNote:'',rightsDeclared:false});id.current.reset();setError(null);}}}>{t(pending?'checkResult':'import')}</Btn><IconBtn label={t('refresh')} disabled={busy} onClick={()=>void read()}><RefreshCw size={14}/></IconBtn></div>
    {!!catalog?.uploads?.length&&<section aria-label={t('unfinished')}><strong>{t('unfinished')}</strong>{catalog.uploads.map(item=><div key={item.uploadId} className="ov-resource-details"><span>{item.metadata.displayName}</span><p className="ov-resource-caption">{t('confirmed')} {Math.floor(item.receivedBytes/item.bytes*100)}% · {t('sameFile')}</p><div className="ov-resource-actions"><Btn disabled={uploading||!!pending||writeBlocked||!catalog.capabilities.canUpload} onClick={()=>resume(item)}>{t('resume')}</Btn><Btn disabled={uploading||!!pending||writeBlocked||!catalog.capabilities.canUpload} onClick={()=>void discard(item)}>{t('discard')}</Btn></div></div>)}</section>}
    <form className="ov-resource-search" onSubmit={e=>{e.preventDefault();void read();}}><input aria-label={t('search')} placeholder={t('search')} value={query} maxLength={120} onChange={e=>setQuery(e.target.value)}/></form>
    {!!error&&<p role="alert" className="ov-resource-error">{error instanceof Error&&error.message===t('fileInvalid')?error.message:imageryFailure(error,locale)}</p>}
    {busy&&<p role="status" className="ov-resource-caption">{t('loading')}</p>}{catalog?.items.length===0&&<p className="ov-resource-empty">{t('empty')}</p>}
    <ul className="ov-resource-model-list" aria-label={t('imagery')}>{catalog?.items.map(item=><RowContext key={item.imageryVersionId} name={item.displayName} actions={[{id:'open',label:locale==='zh'?'查看影像':'View imagery',icon:<Image/>,onSelect:()=>void select(item)}]}><li><button type="button" className="ov-resource-row" aria-pressed={version?.imageryVersionId===item.imageryVersionId} onClick={()=>void select(item)}><Image size={15}/><span>{item.displayName}<small className="ov-resource-terrain-crs">{item.metadata.acquiredAt} · {item.report.horizontalCrs}</small></span></button></li></RowContext>)}</ul>
    {version&&<section className="ov-resource-details"><strong>{version.displayName}</strong><p className="ov-resource-caption">{t('precision')}</p><Btn primary disabled={!canUse||busy||writeBlocked} title={!canUse?t('editRequired'):undefined} onClick={()=>onUse(version)}>{t('use')}</Btn><ImageryFacts value={version}/></section>}
    {open&&<Modal title={t('import')} description={t('fileHint')} onClose={()=>{if(uploading)pause();setOpen(false);}}><fieldset className="ov-resource-form" disabled={uploading}>
      <label>{t('file')}<input type="file" disabled={!!pending} accept=".tif,.tiff,image/tiff" onChange={e=>{setFile(e.target.files?.[0]??null);if(!resuming){setForm(v=>({...v,rightsDeclared:false}));id.current.reset();}}}/></label>
      {pending&&file&&<p className="ov-resource-caption">{file.name}</p>}
      {(['displayName','sourceNote','licenseNote','acquiredAt','attribution','qualityNote'] as const).map(key=><label key={key}>{t(({displayName:'name',sourceNote:'source',licenseNote:'license',acquiredAt:'date',attribution:'attribution',qualityNote:'quality'} as const)[key])}<input disabled={!!pending||!!resuming} type={key==='acquiredAt'?'date':'text'} value={form[key]} maxLength={key==='displayName'?120:key==='sourceNote'?1200:key==='licenseNote'?1000:500} onChange={e=>setForm(v=>({...v,[key]:e.target.value}))}/></label>)}
      <label className="ov-resource-check"><input type="checkbox" disabled={!!pending||!!resuming} checked={form.rightsDeclared} onChange={e=>setForm(v=>({...v,rightsDeclared:e.target.checked}))}/><span>{t('rights')}</span></label>
      {!!error&&<p role="alert" className="ov-resource-error">{error instanceof Error&&error.message===t('fileInvalid')?error.message:imageryFailure(error,locale)}</p>}
      {progress&&<><p role="status">{t('confirmed')} {(progress.receivedBytes/1048576).toFixed(1)} / {(progress.bytes/1048576).toFixed(1)} MiB</p><progress aria-label={t('confirmed')} value={progress.receivedBytes} max={progress.bytes} style={{width:'100%',accentColor:'var(--primary)'}}/></>}
      {uploading&&<p role="status">{t(checking?'checking':progress?.phase==='processing'?'validating':'processing')}</p>}
    </fieldset><div className="ov-resource-actions end"><Btn onClick={()=>{if(uploading)pause();else setOpen(false);}}>{t(uploading?'pause':'cancel')}</Btn>{pending&&!uploading&&<><Btn disabled={writeBlocked||!catalog?.capabilities.canUpload} onClick={()=>void discard()}>{t('discard')}</Btn><Btn primary onClick={()=>void checkResult()}>{t('checkResult')}</Btn></>}<Btn primary={!pending} disabled={uploading||!file||writeBlocked||!catalog?.capabilities.canUpload} onClick={()=>void upload()}>{t(uploading?(checking?'checking':'processing'):pending||resuming?'resume':'submit')}</Btn></div></Modal>}
  </section>;
}
