import { useEffect, useRef, useState } from 'react';
import { FileBox, Upload } from 'lucide-react';
import { ApiError, cancelled, failureMessage, type WorkbenchApi } from './api';
import { Badge, Btn, Modal } from './Primitives';
import { usePreferences } from './Preferences';
import type { ModelLibraryView, ModelReport, ModelVersion } from './types';

export function ProcessingReport({report}:{report:ModelReport}) {
  const {t} = usePreferences();
  return <><dl className="cw-kv"><dt>{t('byteSize')}</dt><dd>{(report.bytes/1024/1024).toFixed(2)} MiB</dd><dt>{t('meshCount')}</dt><dd>{report.activeMeshInstances.toLocaleString()}</dd><dt>{t('triangleCount')}</dt><dd>{report.triangles.toLocaleString()}</dd><dt>{t('textureCount')}</dt><dd>{report.images}</dd></dl><Badge tone="amber">{t('coordinateUnverified')}</Badge></>;
}

function UploadModel({api,library,onClose,onRefresh,onPreview}:{api:WorkbenchApi;library:ModelLibraryView;onClose:()=>void;onRefresh:()=>void;onPreview:(id:string)=>void}) {
  const {t,locale} = usePreferences();
  const [step,setStep] = useState(1), [file,setFile] = useState<File|null>(null);
  const [name,setName] = useState(''),[note,setNote] = useState(''),[rights,setRights] = useState(false);
  const [error,setError] = useState<unknown>(null),[busy,setBusy] = useState(false),[result,setResult] = useState<ModelVersion|null>(null);
  const requestId = useRef(crypto.randomUUID()), abort = useRef<AbortController|null>(null);
  useEffect(()=>()=>abort.current?.abort(),[]);
  function choose(value:File|undefined) {
    if(!value)return;
    setError(null);
    if (!/\.glb$/i.test(value.name)) {setFile(null);setError(new ApiError(422,'UNSUPPORTED_MODEL'));return;}
    if (value.size>library.maxBytes || value.size<24) {setFile(null);setError(new ApiError(413,'MODEL_LIMIT_EXCEEDED'));return;}
    setFile(value);setName(value.name.replace(/\.glb$/i,'').slice(0,200));setNote('');setRights(false);requestId.current=crypto.randomUUID();
  }
  async function upload() {
    if (!file || !rights || !name.trim() || !note.trim()) return;
    abort.current?.abort();abort.current=new AbortController();setBusy(true);setStep(3);setError(null);
    try {
      const value=await api.upload<{item:ModelVersion}>(file,{expectedLibraryRevision:library.libraryRevision,clientRequestId:requestId.current,displayName:name.trim(),sourceNote:note.trim(),rightsDeclared:rights},abort.current.signal);
      setResult(value.item);onRefresh();
    } catch (value) {if (!cancelled(value)) {setError(value);setStep(2);if(value instanceof ApiError && value.code==='MODEL_WRITE_FORBIDDEN')onRefresh();}}
    finally {if (!abort.current?.signal.aborted) setBusy(false);}
  }
  return <Modal title={t('uploadModel')} description={t('uploadLimit')} onClose={onClose}><div className="cw-upload-steps" aria-label={t('uploadModel')}>{(['fileStep','infoStep','validationStep','resultStep'] as const).map((key,index)=><span key={key} className={step===index+1?'active':''} aria-current={step===index+1?'step':undefined}>{index+1}. {t(key)}</span>)}</div>
    {step===1 ? <div className="cw-upload-fields"><label className="cw-file-field"><Upload size={24}/><strong>{file?.name || t('chooseGlb')}</strong><span className="cw-caption">{t('uploadLimit')}</span><input type="file" accept=".glb" aria-label={t('chooseGlb')} onChange={event=>choose(event.target.files?.[0])}/></label>{error ? <p role="alert">{failureMessage(error,locale)}</p> : null}<Btn primary disabled={!file} onClick={()=>setStep(2)}>{t('next')}</Btn></div>
      : step===2 ? <form className="cw-upload-fields" onSubmit={event=>{event.preventDefault();void upload();}}><label>{t('modelDisplayName')}<input value={name} maxLength={200} required onChange={event=>{setName(event.target.value);requestId.current=crypto.randomUUID();}}/></label><label>{t('sourceDeclaration')}<textarea value={note} maxLength={1000} required rows={3} onChange={event=>{setNote(event.target.value);requestId.current=crypto.randomUUID();}}/></label><label className="cw-checkbox"><input type="checkbox" checked={rights} onChange={event=>setRights(event.target.checked)}/>{t('rightsDeclaration')}</label>{error ? <p role="alert">{failureMessage(error,locale)}</p> : null}<div className="cw-inline-actions"><Btn onClick={()=>setStep(1)}>{t('previous')}</Btn><button type="submit" className="ov-btn primary" disabled={!library.canUpload || !rights || !name.trim() || !note.trim()}>{t('uploadValidate')}</button></div></form>
      : step===3 ? <div className="cw-upload-fields">{busy ? <p role="status">{t('uploadingModel')}</p> : result && <><ProcessingReport report={result.report}/><Btn primary onClick={()=>setStep(4)}>{t('next')}</Btn></>}</div>
      : result && <div className="cw-upload-fields"><strong>{result.displayName}</strong><div className="cw-inline-actions"><Badge>{t('technicalReady')}</Badge><Badge tone="amber">{t('notPublished')}</Badge></div><p className="cw-caption">{t('sourceDeclarationNote')}</p><Btn primary onClick={()=>onPreview(result.versionId)}>{t('previewModel')}</Btn></div>}
  </Modal>;
}

export function ModelLibraryPanel({api,onPreview}:{api:WorkbenchApi;onPreview:(id:string|null)=>void}) {
  const {t,locale} = usePreferences();
  const [library,setLibrary] = useState<ModelLibraryView|null>(null),[error,setError] = useState<unknown>(null);
  const [reload,setReload] = useState(0),[upload,setUpload] = useState(false),[tab,setTab] = useState('modelList'),[selected,setSelected] = useState('');
  useEffect(()=>{
    const abort=new AbortController();setError(null);
    api.request<ModelLibraryView>('/api/workbench/models',{},abort.signal).then(setLibrary).catch(value=>{if(!cancelled(value))setError(value);});
    return ()=>abort.abort();
  },[api,reload]);
  const item=library?.items.find(row=>row.versionId===selected);
  return <section className="cw-panel cw-model-library"><header><strong>{t('modelCenter')}</strong><span className="cw-grow"/><Btn disabled={!library?.canUpload} title={library?.canUpload?t('uploadModel'):t('adminRequired')} onClick={()=>setUpload(true)}><Upload size={14}/>{t('uploadModel')}</Btn></header><div className="cw-tabs" role="tablist" aria-label={t('modelCenter')}>{(['modelList','processingReport','versions'] as const).map(value=><button type="button" role="tab" aria-selected={tab===value} key={value} className={tab===value?'active':''} onClick={()=>setTab(value)}>{t(value)}</button>)}</div>
    <div className="cw-library-body">{error ? <div className="cw-upload-fields"><p role="alert">{failureMessage(error,locale)}</p><Btn onClick={()=>setReload(v=>v+1)}>{t('refresh')}</Btn></div> : !library ? <p role="status">{t('loading')}</p> : tab==='modelList' ? <><div className="cw-model-table">{library.hasCurrentModel && <div className="cw-model-row"><FileBox size={18}/><strong>{t('currentModel')}</strong><Badge>{t('configured')}</Badge><Btn onClick={()=>onPreview(null)}>{t('viewCurrentModel')}</Btn></div>}{library.items.map(row=><div className="cw-model-row" key={row.versionId}><FileBox size={18}/><button type="button" className="cw-model-name" onClick={()=>{setSelected(row.versionId);setTab('processingReport');}}>{row.displayName}</button><span className="cw-caption">{t('linkedCabinets')} {row.bindingCount}</span><Badge>{t('technicalReady')}</Badge><Btn onClick={()=>onPreview(row.versionId)}>{t('previewModel')}</Btn></div>)}</div>{!library.items.length && <p className="cw-state">{t('noUploadedModel')}</p>}</> : !item ? <p className="cw-state">{t('noReport')}</p> : tab==='processingReport' ? <div className="cw-report"><h2>{item.displayName}</h2><ProcessingReport report={item.report}/><details className="cw-details"><summary>{t('modelSource')}</summary><p>{item.sourceNote}</p></details></div> : <div className="cw-report"><h2>{item.displayName}</h2><dl className="cw-kv"><dt>{t('modelVersion')}</dt><dd>{t('versionOne')}</dd><dt>{t('contentDigest')}</dt><dd className="ov-mono">{item.sha256}</dd></dl><Badge tone="amber">{t('notPublished')}</Badge><Btn onClick={()=>onPreview(item.versionId)}>{t('previewModel')}</Btn></div>}</div>
    {upload && library && <UploadModel api={api} library={library} onClose={()=>setUpload(false)} onRefresh={()=>setReload(v=>v+1)} onPreview={id=>{setUpload(false);onPreview(id);}}/>}
  </section>;
}
