import {useEffect, useMemo, useRef, useState} from 'react';
import {Eye, MapPin} from 'lucide-react';
import {cancelled} from './api';
import {Badge, Btn, Modal} from './Primitives';
import {usePreferences} from './Preferences';
import type {SceneApi} from './sceneApi';
import type {ModelUses, ProjectModel, ProjectModelWrite} from './resourceTypes';
import {calibrationInput, privateDenial, ResourceRequestGate, ResourceRequestId, resourceBytes, resourceFailure, writeDenial} from './resourceForms';
import {resourceText} from './resourceMessages';

interface Props {
  api: SceneApi; version: ProjectModel; libraryRevision: string; canPlace: boolean; canCalibrate: boolean;
  onPreview: () => void; onPlace: () => void;
  onUpdated: (version: ProjectModelWrite) => void; onWriteDenied: () => void; onPrivateDenied: () => void;
  onRefreshLibrary: () => Promise<string|null>;
}

export function ResourceDetails({api, version, libraryRevision, canPlace, canCalibrate,
    onPreview, onPlace, onUpdated, onWriteDenied, onPrivateDenied, onRefreshLibrary}: Props) {
  const {locale} = usePreferences(), t = (key: Parameters<typeof resourceText>[1]) => resourceText(locale,key);
  const [uses,setUses] = useState<ModelUses|null>(null), [usesOpen,setUsesOpen] = useState(false);
  const [usesBusy,setUsesBusy] = useState(false), [usesError,setUsesError] = useState<unknown>(null);
  const [calibrating,setCalibrating] = useState(false), [saving,setSaving] = useState(false), [error,setError] = useState<unknown>(null);
  const [base,setBase] = useState(['0','0','0']), [forward,setForward] = useState(['0','0','-1']), [reviewed,setReviewed] = useState(false);
  const [expectedLibrary,setExpectedLibrary] = useState(libraryRevision);
  const useGate = useMemo(()=>new ResourceRequestGate(),[]), saveGate = useMemo(()=>new ResourceRequestGate(),[]);
  const requestId = useRef(new ResourceRequestId());
  useEffect(()=>{
    setUses(null);setUsesOpen(false);setUsesError(null);setError(null);setCalibrating(false);setSaving(false);setUsesBusy(false);
    return ()=>{useGate.cancel();saveGate.cancel();};
  },[version.modelVersionId,useGate,saveGate]);
  function failed(value:unknown, usage=false) {
    if(cancelled(value))return;
    if(privateDenial(value)){onPrivateDenied();return;}
    if(writeDenial(value))onWriteDenied();
    if(usage)setUsesError(value);else setError(value);
  }
  async function readUses(cursor?:string) {
    const request=useGate.start();setUsesBusy(true);setUsesError(null);
    try {
      const value=await api.modelUses({versionId:version.modelVersionId,scope:'current_or_retained',...(cursor?{cursor}:{})},request.signal);
      if(request.isCurrent())setUses(previous=>cursor&&previous?{...value,items:[...previous.items,...value.items]}:value);
    }catch(value){if(request.isCurrent())failed(value,true);}
    finally{if(request.isCurrent())setUsesBusy(false);}
  }
  function openCalibration() {
    const calibration=version.calibration;
    setBase(calibration.state==='verified'?calibration.basePoint.map(String):['0','0','0']);
    setForward(calibration.state==='verified'?calibration.forward.map(String):['0','0','-1']);
    setReviewed(false);setError(null);setExpectedLibrary(libraryRevision);requestId.current.reset();setCalibrating(true);
  }
  async function saveCalibration() {
    if(saving||!canCalibrate||!reviewed)return;
    try {
      const calibration=calibrationInput(base,forward), body={modelVersionId:version.modelVersionId,
        expectedContentRevision:version.contentRevision,expectedLibraryRevision:expectedLibrary,calibration};
      const clientRequestId=requestId.current.forPayload(body),request=saveGate.start();setSaving(true);setError(null);
      try {
        const value=await api.calibrateModel({...body,clientRequestId},request.signal);
        if(request.isCurrent()){setCalibrating(false);onUpdated(value);}
      }catch(value){if(request.isCurrent())failed(value);}
      finally{if(request.isCurrent())setSaving(false);}
    }catch(value){failed(value);}
  }
  async function refreshCalibrationLibrary() {
    setSaving(true);
    try {const revision=await onRefreshLibrary();if(revision){setExpectedLibrary(revision);setError(null);}}
    finally {setSaving(false);}
  }
  const dimensions=version.report.bounds.max.map((maximum,index)=>maximum-version.report.bounds.min[index]);
  const counts=(value:Pick<ModelUses,'currentInstanceCount'|'retainedInstanceCount'|'retainedReferenceCount'>)=>resourceText(locale,'useCounts',{
    current:value.currentInstanceCount,retained:value.retainedInstanceCount,references:value.retainedReferenceCount});
  return <section className="ov-resource-details" aria-label={version.displayName}>
    <div className="ov-resource-title"><strong>{version.displayName}</strong><Badge tone={version.canPlace?'success':'warning'}>{t(version.canPlace?'calibrated':'unverified')}</Badge></div>
    {version.components.some(item=>item.geometryQuality==='proxy_schematic')&&<p className="ov-resource-caption">{t('proxyGeometry')}</p>}
    <div className="ov-resource-actions">
      <Btn onClick={onPreview}><Eye size={14}/>{t('preview')}</Btn>
      <Btn primary disabled={!canPlace||!version.canPlace} title={!version.canPlace?t('calibrationRequired'):!canPlace?t('sceneEditRequired'):t('dragPlace')}
        draggable={canPlace&&version.canPlace} onDragStart={event=>{
          if(!canPlace||!version.canPlace){event.preventDefault();return;}
          event.dataTransfer.effectAllowed='copy';event.dataTransfer.setData('application/x-ontovis-model-version',JSON.stringify({modelAssetId:version.modelAssetId,modelVersionId:version.modelVersionId}));
        }} onClick={onPlace}><MapPin size={14}/>{t('place')}</Btn>
      {canCalibrate&&<Btn onClick={openCalibration}>{t('calibrate')}</Btn>}
    </div>
    <dl className="ov-resource-facts">
      <dt>{t('components')}</dt><dd>{version.components.length.toLocaleString(locale)}</dd>
      <dt>{t('triangles')}</dt><dd>{version.report.triangles.toLocaleString(locale)}</dd>
      <dt>{t('dimensions')}</dt><dd>{dimensions.map(value=>value.toFixed(2)).join(' × ')} m</dd>
      <dt>{t('size')}</dt><dd>{resourceBytes(version.bytes)}</dd>
      <dt>{t('basePoint')}</dt><dd>{version.calibration.state==='verified'?version.calibration.basePoint.join(', '):t('unverified')}</dd>
      <dt>{t('forward')}</dt><dd>{version.calibration.state==='verified'?version.calibration.forward.join(', '):t('unverified')}</dd>
    </dl>
    {!!error&&!calibrating&&<p className="ov-resource-error" role="alert">{resourceFailure(error,locale)}</p>}
    <details className="ov-resource-disclosure"><summary>{t('report')}</summary><dl className="ov-resource-facts">
      <dt>{t('meshes')}</dt><dd>{version.report.activeMeshInstances.toLocaleString(locale)}</dd>
      <dt>{t('textures')}</dt><dd>{version.report.images.toLocaleString(locale)}</dd>
    </dl><p className="ov-resource-caption">{t('calibrationNote')}</p></details>
    <details className="ov-resource-disclosure"><summary>{t('source')}</summary><dl className="ov-resource-facts">
      <dt>{t('sourceNote')}</dt><dd>{version.sourceNote}</dd>
      <dt>{t('createdAt')}</dt><dd>{new Date(version.createdAt).toLocaleString(locale)}</dd>
      <dt>{t('fixedVersion')}</dt><dd className="ov-resource-id">{version.modelVersionId}</dd>
    </dl></details>
    <details className="ov-resource-disclosure" open={usesOpen} onToggle={event=>{
      const open=event.currentTarget.open;setUsesOpen(open);if(open&&!uses&&!usesBusy)void readUses();
    }}><summary>{t('uses')}</summary>
      {uses&&<><p className="ov-resource-caption">{counts(uses)}</p>{uses.items.length===0?<p className="ov-resource-caption">{t('noUses')}</p>:<ul className="ov-resource-use-list">{uses.items.map(item=><li key={item.sceneId}><span>{item.displayName}</span><small>{counts(item)}</small></li>)}</ul>}</>}
      {!!usesError&&<p className="ov-resource-error" role="alert">{resourceFailure(usesError,locale)}</p>}
      {usesBusy&&<p className="ov-resource-caption" role="status">{t('loading')}</p>}
      <div className="ov-resource-actions"><Btn disabled={usesBusy} onClick={()=>void readUses()}>{t('reloadUses')}</Btn>{uses?.nextCursor&&<Btn disabled={usesBusy} onClick={()=>void readUses(uses.nextCursor!)}>{t('more')}</Btn>}</div>
    </details>
    {calibrating&&<Modal title={t('calibrate')} description={t('calibrationDescription')} onClose={()=>{if(!saving)setCalibrating(false);}}>
      <div className="ov-resource-form">
        <p className="ov-resource-caption">{t('calibrationDescription')}</p>
        <fieldset disabled={saving}><legend>{t('basePoint')} (m)</legend><div className="ov-resource-vector">{base.map((value,index)=><label key={index}><span>{['X','Y','Z'][index]}</span><input inputMode="decimal" value={value} onChange={event=>setBase(previous=>previous.map((item,key)=>key===index?event.target.value:item))}/></label>)}</div></fieldset>
        <fieldset disabled={saving}><legend>{t('forward')}</legend><div className="ov-resource-vector">{forward.map((value,index)=><label key={index}><span>{['X','Y','Z'][index]}</span><input inputMode="decimal" value={value} onChange={event=>setForward(previous=>previous.map((item,key)=>key===index?event.target.value:item))}/></label>)}</div><p className="ov-resource-caption">{t('horizontalForward')}</p></fieldset>
        <label className="ov-resource-check"><input type="checkbox" checked={reviewed} disabled={saving} onChange={event=>setReviewed(event.target.checked)}/><span>{t('calibrationReviewed')}</span></label>
        <p className="ov-resource-caption">{t('calibrationNote')}</p>
        {!!error&&<p className="ov-resource-error" role="alert">{resourceFailure(error,locale)}</p>}
        {!!error&&<Btn disabled={saving} onClick={()=>void refreshCalibrationLibrary()}>{t('readLibrary')}</Btn>}
        <div className="ov-resource-actions end"><Btn disabled={saving} onClick={()=>setCalibrating(false)}>{t('cancel')}</Btn><Btn primary disabled={saving||!reviewed||!canCalibrate} onClick={()=>void saveCalibration()}>{t(saving?'saving':'saveCalibration')}</Btn></div>
      </div>
    </Modal>}
  </section>;
}
