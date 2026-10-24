import {useEffect, useMemo, useRef, useState} from 'react';
import {FileUp, Mountain, RefreshCw, Search} from 'lucide-react';
import {ApiError, cancelled} from './api';
import {Badge, Btn, IconBtn, Modal} from './Primitives';
import {usePreferences} from './Preferences';
import type {SceneApi} from './sceneApi';
import type {TerrainCatalog, TerrainJob, TerrainSummary, TerrainVersion} from './resourceTypes';
import type {VerticalDatum} from './sceneTypes';
import {privateDenial, ResourceFormError, ResourceRequestGate, ResourceRequestId, resourceFailure, resourceUploadBytes, terrainMetadata, terrainPending, TERRAIN_POLL_MS,
  validateResourceFile, writeDenial, type TerrainFields} from './resourceForms';
import {resourceText} from './resourceMessages';

interface Props {
  api:SceneApi; writeBlocked:boolean; canUse:boolean; activeTerrainVersion?:TerrainVersion|null;
  onTerrainReady:(version:TerrainVersion)=>void; onWriteDenied:()=>void; onPrivateDenied:()=>void;
}
const emptyFields=():TerrainFields=>({name:'',source:'',license:'',rights:false,datum:'',relativeReference:'',crop:false,bounds:['','','','']});

export function TerrainImport({api,writeBlocked,canUse,activeTerrainVersion,onTerrainReady,onWriteDenied,onPrivateDenied}:Props) {
  const {locale}=usePreferences(),t=(key:Parameters<typeof resourceText>[1])=>resourceText(locale,key);
  const [open,setOpen]=useState(false),[fields,setFields]=useState<TerrainFields>(emptyFields),[file,setFile]=useState<File|null>(null);
  const [uploading,setUploading]=useState(false),[uploadError,setUploadError]=useState<unknown>(null);
  const [job,setJob]=useState<TerrainJob|null>(null),[version,setVersion]=useState<TerrainVersion|null>(activeTerrainVersion||null);
  const [error,setError]=useState<unknown>(null),[loadingVersion,setLoadingVersion]=useState(false),[cancelling,setCancelling]=useState(false);
  const [pollRetry,setPollRetry]=useState(0);
  const [catalog,setCatalog]=useState<TerrainCatalog|null>(null),[catalogLoading,setCatalogLoading]=useState(false),[catalogError,setCatalogError]=useState<unknown>(null);
  const [query,setQuery]=useState(''),[filter,setFilter]=useState('');
  const uploadGate=useMemo(()=>new ResourceRequestGate(),[]),pollGate=useMemo(()=>new ResourceRequestGate(),[]);
  const versionGate=useMemo(()=>new ResourceRequestGate(),[]),cancelGate=useMemo(()=>new ResourceRequestGate(),[]);
  const catalogGate=useMemo(()=>new ResourceRequestGate(),[]);
  const uploadId=useRef(new ResourceRequestId()),cancelId=useRef(new ResourceRequestId());
  const maximum=catalog?.limits.maxUploadBytes??job?.limits.maxUploadBytes??version?.limits.maxUploadBytes;
  const hasUploadLimit=maximum!==undefined&&Number.isSafeInteger(maximum)&&maximum>=8;
  const uploadLimitText=hasUploadLimit?resourceText(locale,'tiffLimit',{maximum:resourceUploadBytes(maximum)}):t('loading');
  const canImport=!writeBlocked&&hasUploadLimit&&!!(catalog?.capabilities.canUpload??job?.capabilities.canUpload??version?.capabilities.canUpload);
  const field=<K extends keyof TerrainFields>(name:K,value:TerrainFields[K])=>setFields(previous=>({...previous,[name]:value}));
  function failed(value:unknown,upload=false) {
    if(cancelled(value))return;
    if(privateDenial(value)){
      uploadGate.cancel();pollGate.cancel();versionGate.cancel();cancelGate.cancel();catalogGate.cancel();
      setJob(null);setVersion(null);setCatalog(null);setFields(emptyFields());setFile(null);setOpen(false);setUploadError(null);setError(null);onPrivateDenied();return;
    }
    if(writeDenial(value))onWriteDenied();
    if(upload)setUploadError(value);else setError(value);
  }
  useEffect(()=>{void readCatalog(undefined,'');return()=>{uploadGate.cancel();pollGate.cancel();versionGate.cancel();cancelGate.cancel();catalogGate.cancel();};},[api,uploadGate,pollGate,versionGate,cancelGate,catalogGate]);
  useEffect(()=>{if(activeTerrainVersion&&!job)setVersion(activeTerrainVersion);},[activeTerrainVersion?.terrainVersionId,activeTerrainVersion?.contentRevision]);
  useEffect(()=>{
    if(!job||!terrainPending(job.state)||cancelling)return;
    let timer:ReturnType<typeof setTimeout>|undefined,disposed=false;
    const poll=async()=>{
      const request=pollGate.start();
      try {
        const value=await api.job(job.jobId,request.signal);
        if(!disposed&&request.isCurrent()){
          setJob(value);setError(null);
          if(terrainPending(value.state))timer=setTimeout(()=>void poll(),TERRAIN_POLL_MS);
        }
      }catch(value){if(!disposed&&request.isCurrent())failed(value);}
    };
    timer=setTimeout(()=>void poll(),TERRAIN_POLL_MS);
    return()=>{disposed=true;if(timer)clearTimeout(timer);pollGate.cancel();};
  },[api,job?.jobId,job?.state,cancelling,pollRetry,pollGate]);
  useEffect(()=>{
    if(job?.state!=='ready'||!job.terrainVersionId)return;
    const request=versionGate.start();setLoadingVersion(true);setError(null);
    void api.version(job.terrainVersionId,request.signal).then(value=>{if(request.isCurrent()){setVersion(value);void readCatalog();}})
      .catch(value=>{if(request.isCurrent())failed(value);})
      .finally(()=>{if(request.isCurrent())setLoadingVersion(false);});
    return()=>versionGate.cancel();
  },[api,job?.terrainVersionId,job?.state,pollRetry,versionGate]);
  async function upload() {
    if(uploading||!canImport)return;
    try {
      if(!file)throw new ResourceFormError('terrainFileInvalid');
      validateResourceFile(file,'terrain',maximum);
      const draft=terrainMetadata(fields,''),clientRequestId=uploadId.current.forPayload(draft,`${file.name}:${file.size}:${file.lastModified}`);
      const request=uploadGate.start();setUploading(true);setUploadError(null);
      try {
        const value=await api.uploadTerrain(file,{...draft,clientRequestId},request.signal);
        if(request.isCurrent()){
          pollGate.cancel();cancelGate.cancel();versionGate.cancel();setLoadingVersion(false);setCancelling(false);
          setJob(value);setVersion(null);setError(null);setOpen(false);setFields(emptyFields());setFile(null);uploadId.current.reset();
        }
      }catch(value){if(request.isCurrent())failed(value,true);}
      finally{if(request.isCurrent())setUploading(false);}
    }catch(value){failed(value,true);}
  }
  async function cancelJob() {
    if(!job||!canImport||!job.capabilities.canCancel||!terrainPending(job.state)||cancelling)return;
    pollGate.cancel();
    const body={jobId:job.jobId,expectedJobRevision:job.jobRevision},request=cancelGate.start();
    const clientRequestId=cancelId.current.forPayload(body);setCancelling(true);setError(null);
    try {const value=await api.cancelTerrain({...body,clientRequestId},request.signal);if(request.isCurrent())setJob(value);}
    catch(value){if(request.isCurrent())failed(value);}
    finally{if(request.isCurrent()){setCancelling(false);setPollRetry(previous=>previous+1);}}
  }
  async function readCatalog(cursor?:string,search=filter) {
    const request=catalogGate.start();setCatalogLoading(true);setCatalogError(null);
    try {const value=await api.terrains({q:search,...(cursor?{cursor}:{})},request.signal);if(request.isCurrent())setCatalog(previous=>cursor&&previous?{...value,items:[...previous.items,...value.items]}:value);}
    catch(value){if(request.isCurrent()){
      if(privateDenial(value))failed(value);else if(!cancelled(value))setCatalogError(value);
    }}finally{if(request.isCurrent())setCatalogLoading(false);}
  }
  async function selectVersion(summary:TerrainSummary) {
    const request=versionGate.start();setVersion(null);setLoadingVersion(true);setError(null);
    try {
      const value=await api.version(summary.terrainVersionId,request.signal);
      if(value.terrainVersionId!==summary.terrainVersionId||value.contentRevision!==summary.contentRevision||value.sha256!==summary.sha256)throw new ApiError(409,'RESOURCE_CHANGED');
      if(request.isCurrent())setVersion(value);
    }catch(value){if(request.isCurrent())failed(value);}
    finally{if(request.isCurrent())setLoadingVersion(false);}
  }
  const active=!!version&&version.terrainVersionId===activeTerrainVersion?.terrainVersionId;
  const source=version?.report.source,mesh=version?.report.mesh;
  return <section className="ov-terrain-panel">
    <div className="ov-resource-actions"><Btn disabled={!canImport} onClick={()=>{setUploadError(null);setOpen(true);}}><FileUp size={14}/>{t('importTerrain')}</Btn></div>
    <form className="ov-resource-search" onSubmit={event=>{event.preventDefault();setFilter(query.trim());void readCatalog(undefined,query.trim());}}><input aria-label={t('searchTerrain')} placeholder={t('searchTerrain')} value={query} maxLength={120} onChange={event=>setQuery(event.target.value)}/><IconBtn label={t('searchTerrain')} type="submit"><Search size={14}/></IconBtn><IconBtn label={t('refresh')} disabled={catalogLoading} onClick={()=>void readCatalog()}><RefreshCw size={14}/></IconBtn></form>
    {!!catalogError&&<p className="ov-resource-error" role="alert">{resourceFailure(catalogError,locale)}</p>}
    {catalogLoading&&!catalog&&<p className="ov-resource-caption" role="status">{t('loading')}</p>}
    {catalog?.items.length===0&&!catalogLoading&&<p className="ov-resource-caption">{t('noTerrainResources')}</p>}
    <ul className="ov-resource-model-list">{catalog?.items.map(item=><li key={item.terrainVersionId}><button type="button" className="ov-resource-row" aria-pressed={item.terrainVersionId===version?.terrainVersionId} onClick={()=>void selectVersion(item)}><Mountain size={15}/><span>{item.displayName}<small className="ov-resource-terrain-crs">{item.sourceHorizontalCrs||t('unknown')}</small></span></button></li>)}</ul>
    {catalog?.nextCursor&&<Btn disabled={catalogLoading} onClick={()=>void readCatalog(catalog.nextCursor!)}>{t(catalogLoading?'loading':'more')}</Btn>}
    {job&&<div className="ov-resource-job" role="status">
      <div className="ov-resource-title"><strong>{job.displayName}</strong><Badge tone={job.state==='failed'?'critical':job.state==='ready'?'success':'neutral'}>{t(job.state)}</Badge></div>
      {job.state==='failed'&&<p className="ov-resource-error">{resourceFailure(new ApiError(422,job.errorCode||'TERRAIN_PROCESSING_FAILED'),locale)}</p>}
      {terrainPending(job.state)&&job.capabilities.canCancel&&<Btn disabled={cancelling||!canImport} onClick={()=>void cancelJob()}>{t(cancelling?'saving':'cancelJob')}</Btn>}
    </div>}
    {!!error&&<div className="ov-resource-error" role="alert"><p>{resourceFailure(error,locale)}</p>{job&&<Btn onClick={()=>{setError(null);setPollRetry(previous=>previous+1);}}>{t('retryStatus')}</Btn>}</div>}
    {loadingVersion&&<p className="ov-resource-caption" role="status">{t('loading')}</p>}
    {!version&&!loadingVersion&&!job&&<p className="ov-resource-empty">{t('noTerrain')}</p>}
    {version&&source&&mesh&&<section className="ov-resource-details">
      <div className="ov-resource-title"><strong>{version.displayName}</strong>{active&&<Badge>{t('activeTerrain')}</Badge>}</div>
      <Btn primary disabled={!canUse||!version.capabilities.sceneTerrainPlacement||active} title={!version.capabilities.sceneTerrainPlacement?t('terrainPlacementUnavailable'):!canUse?t('sceneEditRequired'):undefined} onClick={()=>onTerrainReady(version)}>{t('useTerrain')}</Btn>
      <dl className="ov-resource-facts">
        <dt>{t('horizontalCrs')}</dt><dd>{source.horizontalCrs}</dd>
        <dt>{t('verticalDatum')}</dt><dd>{t(source.verticalDatum)}</dd>
        <dt>{t('heightRange')}</dt><dd>{source.heightRangeM.map(value=>value.toFixed(2)).join(' – ')} m</dd>
      </dl>
      <details className="ov-resource-disclosure"><summary>{t('terrainReport')}</summary><dl className="ov-resource-facts">
        <dt>{t('coverage')}</dt><dd>{source.samplingCentreCoverageWgs84.map(value=>value.toFixed(6)).join(', ')}</dd>
        <dt>{t('sourcePixels')}</dt><dd>{source.width.toLocaleString(locale)} × {source.height.toLocaleString(locale)}</dd>
        <dt>{t('missingPixels')}</dt><dd>{source.missingPixels.toLocaleString(locale)}</dd>
        <dt>{t('triangles')}</dt><dd>{mesh.triangles.toLocaleString(locale)}</dd>
        <dt>{t('contactError')}</dt><dd>{mesh.displayContactMaxErrorM.toPrecision(3)} m</dd>
        <dt>{t('sourceError')}</dt><dd>{t('notMeasured')}</dd>
        {source.relativeReferenceId&&<><dt>{t('relativeReference')}</dt><dd>{source.relativeReferenceId}</dd></>}
      </dl><p className="ov-resource-caption">{t('terrainAccuracy')}</p></details>
      <details className="ov-resource-disclosure"><summary>{t('source')}</summary><dl className="ov-resource-facts">
        <dt>{t('sourceNote')}</dt><dd>{source.sourceNote}</dd><dt>{t('license')}</dt><dd>{source.licenseNote}</dd>
        <dt>{t('createdAt')}</dt><dd>{new Date(version.createdAt).toLocaleString(locale)}</dd>
        <dt>{t('fixedVersion')}</dt><dd className="ov-resource-id">{version.terrainVersionId}</dd>
      </dl></details>
    </section>}
    {open&&<Modal title={t('importTerrain')} description={uploadLimitText} onClose={()=>{if(!uploading)setOpen(false);}}><div className="ov-resource-form">
      <label>{t('chooseTiff')}<input type="file" accept=".tif,.tiff,image/tiff" disabled={uploading} onChange={event=>{
        const selected=event.target.files?.[0]||null;setFile(null);field('rights',false);setUploadError(null);uploadId.current.reset();
        if(selected)try{validateResourceFile(selected,'terrain',maximum);setFile(selected);}catch(value){event.target.value='';failed(value,true);}
      }}/></label>
      <p className="ov-resource-caption">{uploadLimitText}</p>
      <label>{t('displayName')}<input value={fields.name} maxLength={120} disabled={uploading} onChange={event=>field('name',event.target.value)}/></label>
      <label>{t('sourceNote')}<textarea value={fields.source} maxLength={2000} disabled={uploading} rows={2} onChange={event=>field('source',event.target.value)}/></label>
      <label>{t('license')}<textarea value={fields.license} maxLength={2000} disabled={uploading} rows={2} onChange={event=>field('license',event.target.value)}/></label>
      <div className="ov-resource-form-grid"><label>{t('verticalDatum')}<select value={fields.datum} disabled={uploading} onChange={event=>field('datum',event.target.value as VerticalDatum|'')}><option value="">{t('chooseDatum')}</option>{(['EGM2008','EGM96','WGS84_ELLIPSOIDAL','UNKNOWN_RELATIVE'] as const).map(value=><option key={value} value={value}>{t(value)}</option>)}</select></label><label>{t('heightUnit')}<input value={t('metres')} readOnly/></label></div>
      {fields.datum==='UNKNOWN_RELATIVE'&&<label>{t('relativeReference')}<input value={fields.relativeReference} maxLength={120} disabled={uploading} onChange={event=>field('relativeReference',event.target.value)}/></label>}
      <p className="ov-resource-caption">{t('crsFromFile')}</p>
      <details className="ov-resource-disclosure"><summary>{t('crop')}</summary><label className="ov-resource-check"><input type="checkbox" checked={fields.crop} disabled={uploading} onChange={event=>field('crop',event.target.checked)}/><span>{t('cropEnabled')}</span></label>{fields.crop&&<div className="ov-resource-form-grid">{(['west','south','east','north'] as const).map((key,index)=><label key={key}>{t(key)}<input inputMode="decimal" value={fields.bounds[index]} disabled={uploading} onChange={event=>field('bounds',fields.bounds.map((value,i)=>i===index?event.target.value:value))}/></label>)}</div>}</details>
      <label className="ov-resource-check"><input type="checkbox" checked={fields.rights} disabled={uploading} onChange={event=>field('rights',event.target.checked)}/><span>{t('rights')}</span></label>
      {!!uploadError&&<p className="ov-resource-error" role="alert">{resourceFailure(uploadError,locale)}</p>}
      {uploading&&<p className="ov-resource-caption" role="status">{t('uploadingTerrain')}</p>}
      <div className="ov-resource-actions end"><Btn disabled={uploading} onClick={()=>setOpen(false)}>{t('cancel')}</Btn><Btn primary disabled={uploading||!file||!canImport} onClick={()=>void upload()}>{t(uploading?'uploadingTerrain':'submitTerrain')}</Btn></div>
    </div></Modal>}
  </section>;
}
