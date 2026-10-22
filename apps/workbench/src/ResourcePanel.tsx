import {useEffect, useMemo, useRef, useState} from 'react';
import {Box, ChevronDown, ChevronRight, FileUp, Plus, RefreshCw, Search} from 'lucide-react';
import {cancelled, type WorkbenchApi} from './api';
import {Badge, Btn, IconBtn, Modal} from './Primitives';
import {usePreferences} from './Preferences';
import {SceneApi} from './sceneApi';
import {ResourceDetails} from './ResourceDetails';
import {TerrainImport} from './TerrainImport';
import {modelMetadata, privateDenial, ResourceFormError, ResourceRequestGate, ResourceRequestId, resourceFailure,
  validateResourceFile, writeDenial} from './resourceForms';
import {resourceText} from './resourceMessages';
import type {LegacyModelCandidate, LegacyModelCatalog, ModelPurpose, ProjectModel, ProjectModelAsset, ProjectModelCatalog, ProjectModelVersion, ProjectModelWrite, TerrainVersion} from './resourceTypes';
import './resourcePanel.css';

export interface Props {
  api:WorkbenchApi;canPlace:boolean;onPlace:(version:ProjectModelVersion)=>void;
  onPreview:(version:ProjectModelVersion|null)=>void;onTerrainReady:(version:TerrainVersion)=>void;
  activeTerrainVersion?:TerrainVersion|null;
}
const purposes=['equipment','simplified_scene','environment'] as const;

export function ResourcePanel({api,canPlace,onPlace,onPreview,onTerrainReady,activeTerrainVersion}:Props) {
  const {locale}=usePreferences(),t=(key:Parameters<typeof resourceText>[1])=>resourceText(locale,key);
  const client=useMemo(()=>new SceneApi(api),[api]);
  const [tab,setTab]=useState<'models'|'terrains'>('models'),[catalog,setCatalog]=useState<ProjectModelCatalog|null>(null);
  const [query,setQuery]=useState(''),[purpose,setPurpose]=useState<ModelPurpose|''>('');
  const [filters,setFilters]=useState<{q:string;purpose:ModelPurpose|''}>({q:'',purpose:''});
  const [loading,setLoading]=useState(false),[error,setError]=useState<unknown>(null),[denied,setDenied]=useState(false);
  const [assetId,setAssetId]=useState<string|null>(null),[versionId,setVersionId]=useState(''),[version,setVersion]=useState<ProjectModel|null>(null);
  const [detailLoading,setDetailLoading]=useState(false);
  const [upload,setUpload]=useState<{asset?:ProjectModelAsset;revision:string}|null>(null);
  const [file,setFile]=useState<File|null>(null),[name,setName]=useState(''),[use,setUse]=useState<ModelPurpose>('equipment');
  const [source,setSource]=useState(''),[rights,setRights]=useState(false),[uploading,setUploading]=useState(false);
  const [uploadError,setUploadError]=useState<unknown>(null),[notice,setNotice]=useState('');
  const [privacyEpoch,setPrivacyEpoch]=useState(0);
  const [privateUnavailable,setPrivateUnavailable]=useState(false);
  const [legacy,setLegacy]=useState<LegacyModelCatalog|null>(null),[legacyOpen,setLegacyOpen]=useState(false),[legacyLoading,setLegacyLoading]=useState(false),[legacyError,setLegacyError]=useState<unknown>(null);
  const [existing,setExisting]=useState<{model:LegacyModelCandidate;revision:string}|null>(null),[existingPurpose,setExistingPurpose]=useState<ModelPurpose>('equipment');
  const [importing,setImporting]=useState(false),[importError,setImportError]=useState<unknown>(null);
  const catalogGate=useMemo(()=>new ResourceRequestGate(),[]),detailGate=useMemo(()=>new ResourceRequestGate(),[]),uploadGate=useMemo(()=>new ResourceRequestGate(),[]);
  const legacyGate=useMemo(()=>new ResourceRequestGate(),[]),importGate=useMemo(()=>new ResourceRequestGate(),[]),importId=useRef(new ResourceRequestId());
  const requestId=useRef(new ResourceRequestId()),previewCallback=useRef(onPreview);previewCallback.current=onPreview;
  const canUpload=!!catalog?.capabilities.canUpload&&!denied;
  const canCalibrate=!!catalog?.capabilities.canCalibrate&&!!version?.capabilities.canCalibrate&&!denied;
  const selectedAsset=catalog?.items.find(item=>item.modelAssetId===assetId);
  function clearPrivate() {
    catalogGate.cancel();detailGate.cancel();uploadGate.cancel();legacyGate.cancel();importGate.cancel();setCatalog(null);setVersion(null);setAssetId(null);setVersionId('');
    previewCallback.current(null);setUpload(null);setFile(null);setName('');setSource('');setRights(false);setError(null);setUploadError(null);
    setLoading(false);setDetailLoading(false);setUploading(false);setPrivacyEpoch(previous=>previous+1);
    setPrivateUnavailable(true);
    setLegacy(null);setLegacyError(null);setLegacyOpen(false);setExisting(null);setImportError(null);setImporting(false);setLegacyLoading(false);
  }
  function failed(value:unknown,inUpload=false) {
    if(cancelled(value))return;
    if(privateDenial(value)){clearPrivate();return;}
    if(writeDenial(value))setDenied(true);
    if(inUpload)setUploadError(value);else setError(value);
  }
  async function readCatalog(cursor?:string,choice=filters):Promise<string|null> {
    const request=catalogGate.start();setLoading(true);setError(null);
    try {
      const value=await client.models({q:choice.q,...(choice.purpose?{purpose:choice.purpose}:{}),
        ...(cursor?{cursor,expectedLibraryRevision:catalog?.libraryRevision}:{})},request.signal);
      if(!request.isCurrent())return null;
      setCatalog(previous=>cursor&&previous?{...value,items:[...previous.items,...value.items]}:value);setDenied(false);
      return value.libraryRevision;
    }catch(value){if(request.isCurrent())failed(value);return null;}
    finally{if(request.isCurrent())setLoading(false);}
  }
  useEffect(()=>{void readCatalog(undefined,{q:'',purpose:''});return()=>{
    catalogGate.cancel();detailGate.cancel();uploadGate.cancel();legacyGate.cancel();importGate.cancel();previewCallback.current(null);
  };},[client,catalogGate,detailGate,uploadGate,legacyGate,importGate]);
  function changeFilters(q:string,nextPurpose:ModelPurpose|'') {
    const next={q:q.trim(),purpose:nextPurpose};setFilters(next);setVersion(null);setVersionId('');setAssetId(null);
    detailGate.cancel();setDetailLoading(false);onPreview(null);void readCatalog(undefined,next);
  }
  function selectAsset(value:string) {
    detailGate.cancel();setDetailLoading(false);setAssetId(value===assetId?null:value);setVersionId('');setVersion(null);onPreview(null);setError(null);
  }
  async function selectVersion(asset:string,id:string) {
    const request=detailGate.start();setVersionId(id);setVersion(null);onPreview(null);setError(null);
    if(!id){setDetailLoading(false);return;}
    setDetailLoading(true);
    try {const value=await client.model(asset,id,request.signal);if(request.isCurrent())setVersion(value);}
    catch(value){if(request.isCurrent())failed(value);}
    finally{if(request.isCurrent())setDetailLoading(false);}
  }
  function openUpload(asset?:ProjectModelAsset) {
    if(!catalog||!canUpload)return;
    setUpload({asset,revision:catalog.libraryRevision});setName(asset?.displayName||'');setUse(asset?.purpose||'equipment');
    setSource('');setRights(false);setFile(null);setUploadError(null);setNotice('');requestId.current.reset();
  }
  async function uploadModel() {
    if(!upload||!canUpload||uploading)return;
    try {
      if(!file)throw new ResourceFormError('modelFileInvalid');
      validateResourceFile(file,'model',catalog?.limits.maxUploadBytes);
      const draft=modelMetadata({name,purpose:use,source,rights},upload.revision,'',upload.asset);
      const clientRequestId=requestId.current.forPayload(draft,`${file.name}:${file.size}:${file.lastModified}`);
      const request=uploadGate.start();setUploading(true);setUploadError(null);setNotice('');
      try {
        const value=await client.uploadModel(file,{...draft,clientRequestId},request.signal);
        if(request.isCurrent()){setUpload(null);setFile(null);setName('');setSource('');setRights(false);updated(value);}
      }catch(value){if(request.isCurrent())failed(value,true);}
      finally{if(request.isCurrent())setUploading(false);}
    }catch(value){failed(value,true);}
  }
  function updated(value:ProjectModelWrite) {
    detailGate.cancel();setAssetId(value.modelAssetId);setVersionId(value.modelVersionId);setVersion(value);onPreview(null);
    setCatalog(previous=>previous?{...previous,libraryRevision:value.libraryRevision}:previous);void readCatalog();
  }
  async function updateFormLibrary() {
    const revision=await readCatalog();
    if(revision){setUpload(previous=>previous?{...previous,revision}:previous);setUploadError(null);setNotice(t('libraryUpdated'));}
  }
  async function readLegacy() {
    const request=legacyGate.start();setLegacyLoading(true);setLegacyError(null);
    try {const value=await client.legacyModels(request.signal);if(request.isCurrent())setLegacy(value);}
    catch(value){if(request.isCurrent()){if(privateDenial(value))clearPrivate();else if(!cancelled(value))setLegacyError(value);}}
    finally{if(request.isCurrent())setLegacyLoading(false);}
  }
  async function importExisting() {
    if(!existing||!existing.model.canImport||!canUpload||importing)return;
    const model=existing.model,body={legacyModelVersionId:model.modelVersionId,expectedModelRevision:model.modelRevision,
      expectedSha256:model.sha256,expectedLibraryRevision:existing.revision,purpose:existingPurpose};
    const request=importGate.start(),clientRequestId=importId.current.forPayload(body);setImporting(true);setImportError(null);
    try {const value=await client.importExistingModel({...body,clientRequestId},request.signal);if(request.isCurrent()){setExisting(null);updated(value);void readLegacy();}}
    catch(value){if(request.isCurrent()){
      if(privateDenial(value))clearPrivate();else if(!cancelled(value)){if(writeDenial(value))setDenied(true);setImportError(value);void readLegacy();}
    }}finally{if(request.isCurrent())setImporting(false);}
  }
  async function refreshExistingLibrary() {
    const revision=await readCatalog();
    if(revision){setExisting(previous=>previous?{...previous,revision}:previous);setImportError(null);void readLegacy();}
  }
  if(privateUnavailable)return <div className="ov-resource-panel"/>;
  return <div className="ov-resource-panel">
    <div className="ov-resource-tabs" role="tablist" aria-label={t('resources')}>
      <button id="ov-resource-models-tab" role="tab" aria-selected={tab==='models'} aria-controls="ov-resource-models" onClick={()=>setTab('models')}>{t('models')}</button>
      <button id="ov-resource-terrain-tab" role="tab" aria-selected={tab==='terrains'} aria-controls="ov-resource-terrains" onClick={()=>setTab('terrains')}>{t('terrains')}</button>
    </div>
    <section id="ov-resource-models" role="tabpanel" aria-labelledby="ov-resource-models-tab" hidden={tab!=='models'} className="ov-resource-tab-body">
      <form className="ov-resource-search" onSubmit={event=>{event.preventDefault();changeFilters(query,purpose);}}>
        <input aria-label={t('search')} placeholder={t('search')} value={query} maxLength={120} onChange={event=>setQuery(event.target.value)}/>
        <IconBtn label={t('search')} type="submit"><Search size={15}/></IconBtn>
      </form>
      <div className="ov-resource-toolbar"><select aria-label={t('purpose')} value={purpose} onChange={event=>{const value=event.target.value as ModelPurpose|'';setPurpose(value);changeFilters(query,value);}}><option value="">{t('allPurposes')}</option>{purposes.map(value=><option key={value} value={value}>{t(value)}</option>)}</select>
        <IconBtn label={t('refresh')} disabled={loading} onClick={()=>void readCatalog()}><RefreshCw size={14}/></IconBtn>
        <IconBtn label={t('uploadModel')} disabled={!canUpload} onClick={()=>openUpload()}><Plus size={16}/></IconBtn>
      </div>
      {catalog&&!canUpload&&<div className="ov-resource-readonly"><Badge>{t('readonly')}</Badge><span>{t('readOnlyDescription')}</span></div>}
      {!!error&&<p className="ov-resource-error" role="alert">{resourceFailure(error,locale)}</p>}
      {loading&&!catalog&&<p className="ov-resource-caption" role="status">{t('loading')}</p>}
      {catalog?.items.length===0&&!loading&&<p className="ov-resource-empty">{t('noModels')}</p>}
      <ul className="ov-resource-model-list">{catalog?.items.map(asset=><li key={asset.modelAssetId}>
        <button className="ov-resource-row" aria-expanded={assetId===asset.modelAssetId} onClick={()=>selectAsset(asset.modelAssetId)}>{assetId===asset.modelAssetId?<ChevronDown size={14}/>:<ChevronRight size={14}/>}<Box size={15}/><span>{asset.displayName}</span><small>{asset.versions.length}</small></button>
        {assetId===asset.modelAssetId&&<div className="ov-resource-version-choice"><label>{t('chooseVersion')}<select value={versionId} onChange={event=>void selectVersion(asset.modelAssetId,event.target.value)}><option value="">{t('chooseVersion')}</option>{asset.versions.map(item=><option key={item.modelVersionId} value={item.modelVersionId}>{new Date(item.createdAt).toLocaleString(locale)} · {item.modelVersionId.slice(0,8)} · {t(item.canPlace?'calibrated':'unverified')}</option>)}</select></label>{canUpload&&<Btn onClick={()=>openUpload(asset)}>{t('appendVersion')}</Btn>}</div>}
      </li>)}</ul>
      {catalog?.nextCursor&&<Btn disabled={loading} onClick={()=>void readCatalog(catalog.nextCursor!)}>{t(loading?'loading':'more')}</Btn>}
      {detailLoading&&<p className="ov-resource-caption" role="status">{t('loading')}</p>}
      {version&&<ResourceDetails key={version.modelVersionId} api={client} version={version} libraryRevision={catalog?.libraryRevision||''} canPlace={canPlace} canCalibrate={canCalibrate}
        onPreview={()=>onPreview(version)}
        onPlace={()=>{if(canPlace&&version.canPlace){onPreview(null);onPlace(version);}}} onUpdated={updated}
        onWriteDenied={()=>setDenied(true)} onPrivateDenied={clearPrivate} onRefreshLibrary={async()=>await readCatalog()}/>} 
      {!version&&!detailLoading&&selectedAsset&&<p className="ov-resource-caption">{t('chooseModel')}</p>}
      <details className="ov-resource-disclosure" open={legacyOpen} onToggle={event=>{const value=event.currentTarget.open;setLegacyOpen(value);if(value&&!legacy&&!legacyLoading)void readLegacy();}}><summary>{t('existingModels')}</summary>
        {legacyLoading&&<p className="ov-resource-caption" role="status">{t('loading')}</p>}
        {!!legacyError&&<p className="ov-resource-error" role="alert">{resourceFailure(legacyError,locale)}</p>}
        {legacy?.items.length===0&&<p className="ov-resource-caption">{t('noExisting')}</p>}
        <ul className="ov-resource-existing-list">{legacy?.items.map(item=><li key={item.modelVersionId}><strong>{item.displayName}</strong><div className="ov-resource-caption">{t('existingBindings')} {item.legacyBindingCount}</div>
          {item.importedResource?<Btn onClick={()=>{setAssetId(item.importedResource!.modelAssetId);void selectVersion(item.importedResource!.modelAssetId,item.importedResource!.modelVersionId);}}>{t('openResource')}</Btn>:
            item.canImport?<Btn disabled={!canUpload||!legacy.capabilities.canUpload} onClick={()=>{setExisting({model:item,revision:catalog?.libraryRevision||legacy.libraryRevision});setExistingPurpose('equipment');setImportError(null);importId.current.reset();}}>{t('useExisting')}</Btn>:<p className="ov-resource-caption">{t('sourcePending')}</p>}
        </li>)}</ul><Btn disabled={legacyLoading} onClick={()=>void readLegacy()}>{t('refresh')}</Btn>
      </details>
    </section>
    <section id="ov-resource-terrains" role="tabpanel" aria-labelledby="ov-resource-terrain-tab" hidden={tab!=='terrains'} className="ov-resource-tab-body">
      <TerrainImport key={privacyEpoch} api={client} writeBlocked={denied} canUse={canPlace} activeTerrainVersion={activeTerrainVersion} onTerrainReady={onTerrainReady} onWriteDenied={()=>setDenied(true)} onPrivateDenied={clearPrivate}/>
    </section>
    {upload&&<Modal title={t(upload.asset?'appendVersion':'uploadModel')} description={t('glbLimit')} onClose={()=>{if(!uploading)setUpload(null);}}><div className="ov-resource-form">
      <label>{t('chooseGlb')}<input type="file" accept=".glb,model/gltf-binary" disabled={uploading} onChange={event=>{setFile(event.target.files?.[0]||null);setRights(false);setUploadError(null);requestId.current.reset();}}/></label>
      <p className="ov-resource-caption">{t('glbLimit')}</p>
      <label>{t('displayName')}<input value={name} maxLength={120} disabled={uploading||!!upload.asset} onChange={event=>setName(event.target.value)}/></label>
      <label>{t('purpose')}<select value={use} disabled={uploading||!!upload.asset} onChange={event=>setUse(event.target.value as ModelPurpose)}>{purposes.map(value=><option key={value} value={value}>{t(value)}</option>)}</select></label>
      <label>{t('sourceNote')}<textarea value={source} rows={3} maxLength={2000} disabled={uploading} onChange={event=>setSource(event.target.value)}/></label>
      <label className="ov-resource-check"><input type="checkbox" checked={rights} disabled={uploading} onChange={event=>setRights(event.target.checked)}/><span>{t('rights')}</span></label>
      {!!uploadError&&<p className="ov-resource-error" role="alert">{resourceFailure(uploadError,locale)}</p>}
      {notice&&<p className="ov-resource-caption" role="status">{notice}</p>}
      {uploading&&<p className="ov-resource-caption" role="status">{t('uploadingModel')}</p>}
      {!!uploadError&&<Btn disabled={uploading||loading} onClick={()=>void updateFormLibrary()}>{t('readLibrary')}</Btn>}
      <div className="ov-resource-actions end"><Btn disabled={uploading} onClick={()=>setUpload(null)}>{t('cancel')}</Btn><Btn primary disabled={uploading||!file||!canUpload} onClick={()=>void uploadModel()}><FileUp size={14}/>{t(uploading?'uploadingModel':'submitModel')}</Btn></div>
    </div></Modal>}
    {existing&&<Modal title={t('useExisting')} description={t('existingDescription')} onClose={()=>{if(!importing)setExisting(null);}}><div className="ov-resource-form">
      <strong>{existing.model.displayName}</strong><p className="ov-resource-caption">{t('existingDescription')}</p>
      <label>{t('purpose')}<select value={existingPurpose} disabled={importing} onChange={event=>setExistingPurpose(event.target.value as ModelPurpose)}>{purposes.map(value=><option key={value} value={value}>{t(value)}</option>)}</select></label>
      <details className="ov-resource-disclosure"><summary>{t('source')}</summary><p className="ov-resource-caption">{existing.model.sourceNote}</p></details>
      {!!importError&&<p className="ov-resource-error" role="alert">{resourceFailure(importError,locale)}</p>}
      {!!importError&&<Btn disabled={importing||loading} onClick={()=>void refreshExistingLibrary()}>{t('readLibrary')}</Btn>}
      <div className="ov-resource-actions end"><Btn disabled={importing} onClick={()=>setExisting(null)}>{t('cancel')}</Btn><Btn primary disabled={importing||!canUpload} onClick={()=>void importExisting()}>{t(importing?'saving':'useExisting')}</Btn></div>
    </div></Modal>}
  </div>;
}
