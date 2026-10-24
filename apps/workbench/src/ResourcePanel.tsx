import {createPortal} from 'react-dom';
import type {ReactNode} from 'react';
import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {Eye, FileUp, LayoutGrid, List, MapPin, Plus, RefreshCw, Search} from 'lucide-react';
import {cancelled, type WorkbenchApi} from './api';
import {Badge, Btn, IconBtn, Modal} from './Primitives';
import {usePreferences} from './Preferences';
import {SceneApi} from './sceneApi';
import {ResourceDetails} from './ResourceDetails';
import {ModelThumbnail} from './ModelThumbnail';
import {TerrainImport} from './TerrainImport';
import {ImageryPanel} from './ImageryPanel';
import {PublicGeoDataPanel} from './PublicGeoDataPanel';
import {publicGeoMessages} from './publicGeoMessages';
import {imageryText} from './imageryMessages';
import type {ImageryVersion} from './resourceTypes';
import {modelMetadata, privateDenial, ResourceFormError, ResourceRequestGate, ResourceRequestId, resourceFailure,
  validateResourceFile, writeDenial, modelPlacementIssue, placementModelVersion, resourceCalibrationKey, type ModelResourceSelection} from './resourceForms';
import {resourceText} from './resourceMessages';
import type {LegacyModelCandidate, LegacyModelCatalog, ModelPurpose, ModelThumbnailInfo, ProjectModel, ProjectModelAsset, ProjectModelCatalog, ProjectModelVersion, ProjectModelWrite, TerrainVersion} from './resourceTypes';
import './resourcePanel.css';

export interface Props {
  api:WorkbenchApi;canPlace:boolean;geographic?:boolean;canReplace?:boolean;replaceTargetVersion?:string|null;onReplace?:(version:ProjectModelVersion)=>void;onPlace:(version:ProjectModelVersion)=>void;
  onPreview:(version:ProjectModelVersion|null)=>void;onTerrainReady:(version:TerrainVersion)=>void;
  activeTerrainVersion?:TerrainVersion|null;
  onImageryReady?:(value:ImageryVersion)=>void;
  detailsTarget?:HTMLElement|null;
  canAcquire?:boolean;modelsOnly?:boolean;onOpenScene?:(sceneId:string)=>void;
  modelSelection?:ModelResourceSelection|null;onModelSelected?:(value:ModelResourceSelection|null)=>void;
}
const purposes=['equipment','simplified_scene','environment'] as const;

export function ResourcePanel({api,canPlace,canAcquire=canPlace,modelsOnly=false,detailsTarget,onOpenScene,canReplace,replaceTargetVersion,onReplace,onPlace,onPreview,onTerrainReady,activeTerrainVersion,onImageryReady,geographic=false,modelSelection,onModelSelected}:Props) {
  const {locale}=usePreferences(),t=(key:Parameters<typeof resourceText>[1])=>resourceText(locale,key);
  const client=useMemo(()=>new SceneApi(api),[api]);
  const [tab,setTab]=useState<'models'|'terrains'|'imagery'>('models'),[catalog,setCatalog]=useState<ProjectModelCatalog|null>(null);
  const [publicAcquisition,setPublicAcquisition]=useState(false),[resourceRefresh,setResourceRefresh]=useState(0);
  const [query,setQuery]=useState(''),[purpose,setPurpose]=useState<ModelPurpose|''>('');
  const [filters,setFilters]=useState<{q:string;purpose:ModelPurpose|''}>({q:'',purpose:''});
  const [catalogView,setCatalogView]=useState<'grid'|'list'>('grid');
  const text=(zh:string,en:string)=>locale==='zh'?zh:en;
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
  const initialSelection=useRef(modelSelection),cardIntent=useRef(0);
  const cardCallbacks=useRef({canPlace,onPreview,onPlace});cardCallbacks.current={canPlace,onPreview,onPlace};
  const canUpload=!!catalog?.capabilities.canUpload&&!denied;
  const canCalibrate=!!catalog?.capabilities.canCalibrate&&!!version?.capabilities.canCalibrate&&!denied;
  const selectedAsset=catalog?.items.find(item=>item.modelAssetId===assetId);
  const selectedThumbnail=selectedAsset?.versions.find(item=>item.modelVersionId===version?.modelVersionId)?.thumbnail;
  const detailVersion=version&&selectedThumbnail?{...version,thumbnail:selectedThumbnail}:version;
  const thumbnailUpdated=useCallback((sha256:string,thumbnail:ModelThumbnailInfo)=>{
    setCatalog(previous=>previous?{...previous,items:previous.items.map(asset=>({...asset,
      versions:asset.versions.map(item=>item.sha256===sha256?{...item,thumbnail}:item)}))}:previous);
    setVersion(previous=>previous?.sha256===sha256?{...previous,thumbnail}:previous);
  },[]);
  function clearPrivate() {
    cardIntent.current++;
    setPublicAcquisition(false);setResourceRefresh(0);
    catalogGate.cancel();detailGate.cancel();uploadGate.cancel();legacyGate.cancel();importGate.cancel();setCatalog(null);setVersion(null);setAssetId(null);setVersionId('');
    previewCallback.current(null);setUpload(null);setFile(null);setName('');setSource('');setRights(false);setError(null);setUploadError(null);
    setLoading(false);setDetailLoading(false);setUploading(false);setPrivacyEpoch(previous=>previous+1);
    setPrivateUnavailable(true);
    initialSelection.current=null;onModelSelected?.(null);
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
  useEffect(()=>{void readCatalog(undefined,{q:'',purpose:''}).then(revision=>{
    const selected=initialSelection.current;
    if(revision&&selected){setAssetId(selected.modelAssetId);void selectVersion(selected.modelAssetId,selected.modelVersionId);}
  });return()=>{
    cardIntent.current++;catalogGate.cancel();detailGate.cancel();uploadGate.cancel();legacyGate.cancel();importGate.cancel();previewCallback.current(null);
  };},[client,catalogGate,detailGate,uploadGate,legacyGate,importGate]);
  function changeFilters(q:string,nextPurpose:ModelPurpose|'') {
    cardIntent.current++;
    const next={q:q.trim(),purpose:nextPurpose};setFilters(next);setCatalog(null);setVersion(null);setVersionId('');setAssetId(null);
    detailGate.cancel();setDetailLoading(false);onPreview(null);void readCatalog(undefined,next);
  }
  function selectAsset(value:string) {
    cardIntent.current++;
    detailGate.cancel();setDetailLoading(false);setAssetId(value===assetId?null:value);setVersionId('');setVersion(null);onPreview(null);setError(null);
    const asset=value!==assetId?catalog?.items.find(item=>item.modelAssetId===value):null;
    if(asset){const selected=placementModelVersion(asset,geographic,modelSelection?.modelAssetId===value?modelSelection.modelVersionId:undefined);
      if(selected)void selectVersion(value,selected.modelVersionId);}
  }
  async function selectVersion(asset:string,id:string):Promise<ProjectModel|null> {
    const request=detailGate.start();setVersionId(id);setVersion(null);onPreview(null);setError(null);
    if(!id){setDetailLoading(false);return null;}
    setDetailLoading(true);
    try {const value=await client.model(asset,id,request.signal);if(request.isCurrent()){setVersion(value);onModelSelected?.({modelAssetId:value.modelAssetId,modelVersionId:value.modelVersionId});return value;}}
    catch(value){if(request.isCurrent())failed(value);}
    finally{if(request.isCurrent())setDetailLoading(false);}
    return null;
  }
  async function activateCard(asset:ProjectModelAsset,action:'preview'|'place',fixedVersionId?:string) {
    const choice=placementModelVersion(asset,geographic,fixedVersionId??(assetId===asset.modelAssetId?versionId:
      modelSelection?.modelAssetId===asset.modelAssetId?modelSelection.modelVersionId:undefined));
    if(!choice)return;
    const ticket=++cardIntent.current;setAssetId(asset.modelAssetId);
    const value=version?.modelVersionId===choice.modelVersionId?version:await selectVersion(asset.modelAssetId,choice.modelVersionId);
    if(!value||ticket!==cardIntent.current)return;
    const callbacks=cardCallbacks.current;
    if(action==='preview')callbacks.onPreview(value);
    else if(callbacks.canPlace&&!modelPlacementIssue(value,geographic)){callbacks.onPreview(null);callbacks.onPlace(value);}
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
    onModelSelected?.({modelAssetId:value.modelAssetId,modelVersionId:value.modelVersionId});
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
  return <div className={`ov-resource-panel${modelsOnly?` pm-model-browser pm-model-browser-${catalogView}`:''}`}>
    <div hidden={modelsOnly} className="ov-resource-tabs" role="tablist" aria-label={t('resources')}>
      <button id="ov-resource-models-tab" role="tab" aria-selected={tab==='models'} aria-controls="ov-resource-models" onClick={()=>{cardIntent.current++;setTab('models');}}>{t('models')}</button>
      <button id="ov-resource-terrain-tab" role="tab" aria-selected={tab==='terrains'} aria-controls="ov-resource-terrains" onClick={()=>{cardIntent.current++;setTab('terrains');}}>{t('terrains')}</button>
      <button id="ov-resource-imagery-tab" role="tab" aria-selected={tab==='imagery'} aria-controls="ov-resource-imagery" onClick={()=>{cardIntent.current++;setTab('imagery');}}>{imageryText(locale,'imagery')}</button>
    </div>
    <div hidden={modelsOnly} className="ov-resource-public-entry"><Btn disabled={!canAcquire||denied} onClick={()=>setPublicAcquisition(true)}>{publicGeoMessages[locale].title}</Btn></div>
    <section id="ov-resource-models" role={modelsOnly?undefined:"tabpanel"} aria-label={modelsOnly?t("models"):undefined} aria-labelledby={modelsOnly?undefined:"ov-resource-models-tab"} hidden={tab!=='models'} className="ov-resource-tab-body">
      <div className={modelsOnly?'pm-library-tools':undefined}><form className="ov-resource-search" onSubmit={event=>{event.preventDefault();changeFilters(query,purpose);}}>
        <input aria-label={t('search')} placeholder={t('search')} value={query} maxLength={120} onChange={event=>setQuery(event.target.value)}/>
        <IconBtn label={t('search')} type="submit"><Search size={15}/></IconBtn>
      </form>
      <div className="ov-resource-toolbar">{!modelsOnly&&<select aria-label={t('purpose')} value={purpose} onChange={event=>{const value=event.target.value as ModelPurpose|'';setPurpose(value);changeFilters(query,value);}}><option value="">{t('allPurposes')}</option>{purposes.map(value=><option key={value} value={value}>{t(value)}</option>)}</select>}
        {modelsOnly&&<div className="pm-view-switch" role="group" aria-label={text('模型目录视图','Model catalog view')}>
          <button type="button" aria-pressed={catalogView==='grid'} onClick={()=>setCatalogView('grid')}><LayoutGrid size={15}/>{text('缩略图','Thumbnails')}</button>
          <button type="button" aria-pressed={catalogView==='list'} onClick={()=>setCatalogView('list')}><List size={15}/>{text('列表','List')}</button>
        </div>}
        <IconBtn label={t('refresh')} disabled={loading} onClick={()=>void readCatalog()}><RefreshCw size={14}/></IconBtn>
        {modelsOnly?<Btn primary disabled={!canUpload} onClick={()=>openUpload()}><FileUp size={15}/>{t('uploadModel')}</Btn>:<IconBtn label={t('uploadModel')} disabled={!canUpload} onClick={()=>openUpload()}><Plus size={16}/></IconBtn>}
      </div></div>
      {modelsOnly&&<div className="pm-library-filter-bar"><div className="pm-category-filter" role="group" aria-label={text('模型分类','Model category')}>
        <span>{text('用途分类','Purpose')}</span>{(['',...purposes] as const).map(value=><button type="button" key={value} aria-pressed={purpose===value} onClick={()=>{setPurpose(value);changeFilters(query,value);}}>{value?t(value):text('全部','All')}</button>)}
      </div><span className="ov-resource-caption" role="status">{loading?t('loading'):text(`已显示 ${catalog?.items.length||0} 个模型资源`,`${catalog?.items.length||0} model resources shown`)}</span></div>}
      {catalog&&!canUpload&&<div className="ov-resource-readonly"><Badge>{t('readonly')}</Badge><span>{t('readOnlyDescription')}</span></div>}
      {!!error&&<p className="ov-resource-error" role="alert">{resourceFailure(error,locale)}</p>}
      {loading&&!catalog&&<p className="ov-resource-caption" role="status">{t('loading')}</p>}
      {catalog?.items.length===0&&!loading&&<p className="ov-resource-empty">{t('noModels')}</p>}
      {modelsOnly&&catalogView==='list'&&<div className="pm-catalog-columns" aria-hidden="true"><span>{t('models')}</span><span>{text('用途分类','Purpose')}</span><span>{t('versions')}</span><span className="pm-meta-size">{t('size')}</span><span className="pm-meta-created">{text('版本创建时间','Version created')}</span></div>}
      <ul className="ov-resource-model-list" aria-label={modelsOnly?text('模型资源目录','Model resource catalog'):undefined}>{catalog?.items.map(asset=>{
        const active=assetId===asset.modelAssetId,choice=placementModelVersion(asset,geographic,active?versionId:
          modelSelection?.modelAssetId===asset.modelAssetId?modelSelection.modelVersionId:undefined);
        const usable=!!choice&&choice.canPlace&&(!geographic||choice.canPlaceGeographic);
        const waiting=active&&detailLoading;
        return <li className={`ov-resource-card ${active?'selected':''}`} key={asset.modelAssetId} aria-label={asset.displayName}>
          <button type="button" className="ov-resource-card-heading" aria-expanded={modelsOnly?undefined:active}
            aria-label={modelsOnly?`${t('preview')} ${asset.displayName}`:undefined}
            onClick={()=>modelsOnly?void activateCard(asset,'preview'):selectAsset(asset.modelAssetId)}>
            <ModelThumbnail api={client} version={choice} name={asset.displayName} onStatus={thumbnailUpdated}/>
            <span className="ov-resource-card-label"><strong>{asset.displayName}</strong><span className={`ov-resource-card-state ${choice?.calibrationState==='verified'?'verified':'pending'}`}>{choice?t(resourceCalibrationKey(choice.calibrationState)):t('noModelVersion')}</span></span>
            {modelsOnly&&<><span className="pm-meta-purpose">{t(asset.purpose)}</span><span className="pm-meta-versions">{asset.versions.length}</span><span className="pm-meta-size">{choice?`${(choice.bytes/1048576).toFixed(2)} MiB`:'—'}</span><span className="pm-meta-created">{choice?new Date(choice.createdAt).toLocaleDateString(locale):'—'}</span></>}
          </button>
          {!modelsOnly&&<div className="ov-resource-card-actions">
            <Btn disabled={!choice||waiting} onClick={()=>void activateCard(asset,'preview')}><Eye size={14}/>{t('preview')}</Btn>
            {!modelsOnly&&<Btn disabled={!canPlace||!usable||waiting} title={!usable?t(geographic?'geographicCalibrationRequired':'calibrationRequired'):!canPlace?t('sceneEditRequired'):t('dragPlace')}
              draggable={canPlace&&usable&&!waiting} onDragStart={event=>{
                if(!canPlace||!usable||!choice||waiting){event.preventDefault();return;}
                event.dataTransfer.effectAllowed='copy';event.dataTransfer.setData('application/x-ontovis-model-version',JSON.stringify({modelAssetId:asset.modelAssetId,modelVersionId:choice.modelVersionId}));
              }} onClick={()=>void activateCard(asset,'place')}><MapPin size={14}/>{t('place')}</Btn>}
          </div>}
          <details className="ov-resource-disclosure ov-resource-card-history"><summary>{modelsOnly&&catalogView==='list'?text('版本与更新','Versions and updates'):resourceText(locale,'modelVersionHistory',{count:asset.versions.length})}</summary><div className="ov-resource-version-choice"><p className="ov-resource-caption">{t('modelVersionHint')}</p><label>{t('chooseVersion')}<select value={choice?.modelVersionId||''} onChange={event=>{const id=event.target.value;if(modelsOnly&&id)void activateCard(asset,'preview',id);else{cardIntent.current++;setAssetId(asset.modelAssetId);void selectVersion(asset.modelAssetId,id);}}}><option value="">{t('chooseVersion')}</option>{asset.versions.map(item=><option key={item.modelVersionId} value={item.modelVersionId}>{new Date(item.createdAt).toLocaleString(locale)} · {item.modelVersionId.slice(0,8)} · {t(resourceCalibrationKey(item.calibrationState))}</option>)}</select></label>{canUpload&&<Btn onClick={()=>openUpload(asset)}>{t('appendVersion')}</Btn>}</div></details>
          {waiting&&<p className="ov-resource-caption" role="status">{t('loading')}</p>}
          {active&&version&&detailVersion&&(!modelsOnly||detailsTarget)&&<ResourceDetailHost target={detailsTarget} title={t('modelDetails')}><ResourceDetails compact={!detailsTarget} hidePlacement={modelsOnly} hidePreview={modelsOnly} key={detailVersion.modelVersionId} api={client} version={detailVersion} libraryRevision={catalog?.libraryRevision||''} canPlace={canPlace} geographic={geographic} canCalibrate={canCalibrate}
            canReplace={canReplace&&version.modelVersionId!==replaceTargetVersion} onReplace={onReplace?()=>onReplace(version):undefined}
            onOpenScene={onOpenScene} onPreview={()=>onPreview(version)} onPlace={()=>{if(canPlace&&!modelPlacementIssue(version,geographic)){onPreview(null);onPlace(version);}}} onUpdated={updated}
            canGenerateThumbnail={catalog?.capabilities.canGenerateThumbnails===true&&!denied} onThumbnailUpdated={thumbnailUpdated}
            onWriteDenied={()=>setDenied(true)} onPrivateDenied={clearPrivate} onRefreshLibrary={async()=>await readCatalog()}/></ResourceDetailHost>}
        </li>;
      })}</ul>
      {catalog?.nextCursor&&<Btn disabled={loading} onClick={()=>void readCatalog(catalog.nextCursor!)}>{t(loading?'loading':'more')}</Btn>}
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
      <TerrainImport key={`${privacyEpoch}:${resourceRefresh}`} api={client} writeBlocked={denied} canUse={canPlace} activeTerrainVersion={activeTerrainVersion} onTerrainReady={onTerrainReady} onWriteDenied={()=>setDenied(true)} onPrivateDenied={clearPrivate}/>
    </section>
    <section id="ov-resource-imagery" role="tabpanel" aria-labelledby="ov-resource-imagery-tab" hidden={tab!=='imagery'} className="ov-resource-tab-body">
      {tab==='imagery'&&<ImageryPanel key={resourceRefresh} api={client} writeBlocked={denied} canUse={canPlace&&geographic&&!!onImageryReady} onUse={value=>onImageryReady?.(value)} onWriteDenied={()=>setDenied(true)} onPrivateDenied={clearPrivate}/>}
    </section>
    {publicAcquisition&&<Modal title={publicGeoMessages[locale].title} description={publicGeoMessages[locale].hint} onClose={()=>setPublicAcquisition(false)}>
      <PublicGeoDataPanel api={api} canWrite={canAcquire&&!denied} onClose={()=>setPublicAcquisition(false)}
        initialCenter={activeTerrainVersion?{longitude:(activeTerrainVersion.report.source.samplingCentreCoverageWgs84[0]+activeTerrainVersion.report.source.samplingCentreCoverageWgs84[2])/2,latitude:(activeTerrainVersion.report.source.samplingCentreCoverageWgs84[1]+activeTerrainVersion.report.source.samplingCentreCoverageWgs84[3])/2}:undefined}
        onImported={result=>{setResourceRefresh(value=>value+1);setTab(result.terrainVersionId?'terrains':'imagery');}}/>
    </Modal>}
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

function ResourceDetailHost({target,title,children}:{target?:HTMLElement|null;title:string;children:ReactNode}) {
  return target?createPortal(children,target):<details className="ov-resource-disclosure ov-resource-card-details"><summary>{title}</summary>{children}</details>;
}
