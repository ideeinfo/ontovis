import {useEffect,useMemo,useRef,useState} from 'react';
import {Image,RefreshCw} from 'lucide-react';
import {ApiError,cancelled} from './api';
import {Btn,IconBtn,Modal} from './Primitives';
import {usePreferences} from './Preferences';
import {privateDenial,ResourceRequestGate,ResourceRequestId,writeDenial} from './resourceForms';
import type {SceneApi} from './sceneApi';
import type {ImageryCatalog,ImageryRecord,ImageryVersion,UploadImageryMetadata} from './resourceTypes';
import {imageryFailure,imageryText} from './imageryMessages';

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
  const listGate=useMemo(()=>new ResourceRequestGate(),[]),versionGate=useMemo(()=>new ResourceRequestGate(),[]),uploadGate=useMemo(()=>new ResourceRequestGate(),[]),id=useRef(new ResourceRequestId());
  function failed(value:unknown){if(cancelled(value))return;if(privateDenial(value)){listGate.cancel();versionGate.cancel();uploadGate.cancel();setCatalog(null);setVersion(null);setFile(null);setOpen(false);onPrivateDenied();return;}if(writeDenial(value))onWriteDenied();setError(value);}
  async function read(){const request=listGate.start();setBusy(true);setError(null);try{const result=await api.imagery(query,request.signal);if(request.isCurrent())setCatalog(result);}catch(value){if(request.isCurrent())failed(value);}finally{if(request.isCurrent())setBusy(false);}}
  useEffect(()=>{void read();return()=>{listGate.cancel();versionGate.cancel();uploadGate.cancel();};},[api]);
  async function select(item:ImageryRecord){const request=versionGate.start();setBusy(true);setVersion(null);setError(null);try{const value=await api.imageryVersion(item.imageryVersionId,request.signal);if(value.contentRevision!==item.contentRevision||value.expectedReportSha256!==item.expectedReportSha256)throw new ApiError(409,'RESOURCE_CHANGED');if(request.isCurrent())setVersion(value);}catch(value){if(request.isCurrent())failed(value);}finally{if(request.isCurrent())setBusy(false);}}
  async function upload(){if(uploading||writeBlocked||!catalog?.capabilities.canUpload)return;setError(null);
    if(!file||!/\.tiff?$/i.test(file.name)||file.size<8||file.size>catalog.limits.maxUploadBytes||!form.rightsDeclared||Object.entries(form).some(([key,v])=>key!=='rightsDeclared'&&typeof v==='string'&&!v.trim())||!/^\d{4}-\d{2}-\d{2}$/.test(form.acquiredAt)){setError(new Error(t('fileInvalid')));return;}
    const payload={...form,rightsDeclared:true as const},clientRequestId=id.current.forPayload(payload,`${file.name}:${file.size}:${file.lastModified}`),request=uploadGate.start();setUploading(true);
    try{const value=await api.uploadImagery(file,{...payload,clientRequestId} as UploadImageryMetadata,request.signal);if(request.isCurrent()){setOpen(false);setFile(null);setVersion(value);void read();}}
    catch(value){if(request.isCurrent())failed(value);}finally{if(request.isCurrent())setUploading(false);}
  }
  return <section className="ov-terrain-panel"><div className="ov-resource-actions"><Btn disabled={writeBlocked||!catalog?.capabilities.canUpload} onClick={()=>{setOpen(true);setFile(null);setForm({displayName:'',sourceNote:'',licenseNote:'',attribution:'',acquiredAt:'',qualityNote:'',rightsDeclared:false});id.current.reset();setError(null);}}>{t('import')}</Btn><IconBtn label={t('refresh')} disabled={busy} onClick={()=>void read()}><RefreshCw size={14}/></IconBtn></div>
    <form className="ov-resource-search" onSubmit={e=>{e.preventDefault();void read();}}><input aria-label={t('search')} placeholder={t('search')} value={query} maxLength={120} onChange={e=>setQuery(e.target.value)}/></form>
    {!!error&&<p role="alert" className="ov-resource-error">{error instanceof Error&&error.message===t('fileInvalid')?error.message:imageryFailure(error,locale)}</p>}
    {busy&&<p role="status" className="ov-resource-caption">{t('loading')}</p>}{catalog?.items.length===0&&<p className="ov-resource-empty">{t('empty')}</p>}
    <ul className="ov-resource-model-list">{catalog?.items.map(item=><li key={item.imageryVersionId}><button className="ov-resource-row" aria-pressed={version?.imageryVersionId===item.imageryVersionId} onClick={()=>void select(item)}><Image size={15}/><span>{item.displayName}<small className="ov-resource-terrain-crs">{item.metadata.acquiredAt} · {item.report.horizontalCrs}</small></span></button></li>)}</ul>
    {version&&<section className="ov-resource-details"><strong>{version.displayName}</strong><p className="ov-resource-caption">{t('precision')}</p><Btn primary disabled={!canUse||busy||writeBlocked} title={!canUse?t('editRequired'):undefined} onClick={()=>onUse(version)}>{t('use')}</Btn><ImageryFacts value={version}/></section>}
    {open&&<Modal title={t('import')} description={t('fileHint')} onClose={()=>{if(!uploading)setOpen(false);}}><fieldset className="ov-resource-form" disabled={uploading}>
      <label>{t('file')}<input type="file" accept=".tif,.tiff,image/tiff" onChange={e=>{setFile(e.target.files?.[0]??null);setForm(v=>({...v,rightsDeclared:false}));id.current.reset();}}/></label>
      {(['displayName','sourceNote','licenseNote','acquiredAt','attribution','qualityNote'] as const).map(key=><label key={key}>{t(({displayName:'name',sourceNote:'source',licenseNote:'license',acquiredAt:'date',attribution:'attribution',qualityNote:'quality'} as const)[key])}<input type={key==='acquiredAt'?'date':'text'} value={form[key]} maxLength={key==='displayName'?120:key==='sourceNote'?1200:key==='licenseNote'?1000:500} onChange={e=>setForm(v=>({...v,[key]:e.target.value}))}/></label>)}
      <label className="ov-resource-check"><input type="checkbox" checked={form.rightsDeclared} onChange={e=>setForm(v=>({...v,rightsDeclared:e.target.checked}))}/><span>{t('rights')}</span></label>
      {!!error&&<p role="alert" className="ov-resource-error">{error instanceof Error&&error.message===t('fileInvalid')?error.message:imageryFailure(error,locale)}</p>}
      {uploading&&<p role="status">{t('processing')}</p>}<div className="ov-resource-actions end"><Btn disabled={uploading} onClick={()=>setOpen(false)}>{t('cancel')}</Btn><Btn primary disabled={uploading||!file||writeBlocked} onClick={()=>void upload()}>{t(uploading?'processing':'submit')}</Btn></div>
    </fieldset></Modal>}
  </section>;
}
