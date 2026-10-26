import {useEffect,useMemo,useRef,useState} from 'react';
import {ApiError,cancelled} from './api';
import {Btn,Modal} from './Primitives';
import {usePreferences} from './Preferences';
import type {SceneApi} from './sceneApi';
import type {ModelPurpose,ProjectModel,ProjectModelWrite} from './resourceTypes';
import {privateDenial,ResourceRequestGate,ResourceRequestId,resourceFailure,writeDenial} from './resourceForms';
import {resourceText} from './resourceMessages';

export function ModelBasicInfo({api,version,canEdit,onUpdated,onWriteDenied,onPrivateDenied}:{
  api:SceneApi;version:ProjectModel;canEdit:boolean;onUpdated:(value:ProjectModelWrite)=>void;
  onWriteDenied:()=>void;onPrivateDenied:()=>void;
}) {
  const {locale}=usePreferences(),text=(zh:string,en:string)=>locale==='zh'?zh:en;
  const [editing,setEditing]=useState(false),[name,setName]=useState(''),[purpose,setPurpose]=useState<ModelPurpose>('equipment');
  const [description,setDescription]=useState(''),[expected,setExpected]=useState('');
  const [busy,setBusy]=useState(false),[error,setError]=useState<unknown>(null);
  const gate=useMemo(()=>new ResourceRequestGate(),[]),requestId=useRef(new ResourceRequestId());
  useEffect(()=>()=>gate.cancel(),[gate]);
  function fill(value:ProjectModel){setName(value.displayName);setPurpose(value.purpose||'equipment');setDescription(value.description||'');setExpected(value.assetRevision||'');setError(null);requestId.current.reset();}
  function failed(value:unknown){
    if(cancelled(value))return;
    if(privateDenial(value)){onPrivateDenied();return;}
    if(writeDenial(value))onWriteDenied();
    setError(value);
  }
  async function save(){
    if(!canEdit||busy||!name.trim()||!expected)return;
    const body={modelAssetId:version.modelAssetId,modelVersionId:version.modelVersionId,
      expectedAssetRevision:expected,displayName:name.trim(),purpose,description};
    const clientRequestId=requestId.current.forPayload(body),request=gate.start();setBusy(true);setError(null);
    try{const value=await api.saveModelInfo({...body,clientRequestId},request.signal);
      if(request.isCurrent()){setEditing(false);onUpdated(value);}}
    catch(value){if(request.isCurrent())failed(value);}
    finally{if(request.isCurrent())setBusy(false);}
  }
  async function reload(){
    const request=gate.start();setBusy(true);
    try{const value=await api.model(version.modelAssetId,version.modelVersionId,request.signal);if(request.isCurrent())fill(value);}
    catch(value){if(request.isCurrent())failed(value);}
    finally{if(request.isCurrent())setBusy(false);}
  }
  const conflict=error instanceof ApiError&&error.code==='MODEL_ASSET_CHANGED';
  return <section aria-label={text('基本信息','Basic information')}>
    <div className="ov-resource-actions"><strong>{text('基本信息','Basic information')}</strong>
      {canEdit&&version.assetRevision&&<Btn onClick={()=>{fill(version);setEditing(true);}}>{text('编辑','Edit')}</Btn>}</div>
    <dl className="ov-resource-facts"><dt>{text('名称','Name')}</dt><dd>{version.displayName}</dd>
      {version.purpose&&<><dt>{text('用途','Purpose')}</dt><dd>{resourceText(locale,version.purpose)}</dd></>}
      <dt>{text('说明','Description')}</dt><dd>{version.description||'—'}</dd></dl>
    {editing&&<Modal title={text('编辑基本信息','Edit basic information')} description={text('修改模型名称、用途和说明。','Edit the model name, purpose and description.')} onClose={()=>{if(!busy)setEditing(false);}}>
      <form className="ov-resource-form" onSubmit={event=>{event.preventDefault();void save();}}>
        <label>{text('名称','Name')}<input required maxLength={200} value={name} disabled={busy} onChange={event=>setName(event.target.value)}/></label>
        <label>{text('用途','Purpose')}<select value={purpose} disabled={busy} onChange={event=>setPurpose(event.target.value as ModelPurpose)}>{(['equipment','simplified_scene','environment'] as const).map(value=><option key={value} value={value}>{resourceText(locale,value)}</option>)}</select></label>
        <label>{text('说明','Description')}<textarea rows={4} maxLength={2000} value={description} disabled={busy} onChange={event=>setDescription(event.target.value)}/></label>
        {!!error&&<p role="alert" className="ov-resource-error">{conflict?text('基本信息已更新，当前修改已保留。','Basic information has changed. Your edits are retained.'):resourceFailure(error,locale)}</p>}
        {conflict&&<><p className="ov-resource-caption">{text('重新读取将替换当前修改。','Reloading replaces your current edits.')}</p><Btn disabled={busy} onClick={()=>void reload()}>{text('重新读取','Reload')}</Btn></>}
        <div className="ov-resource-actions end"><Btn disabled={busy} onClick={()=>setEditing(false)}>{text('取消','Cancel')}</Btn>
          <button type="submit" className="ov-btn primary" disabled={busy||!canEdit||!name.trim()}>{busy?text('保存中…','Saving…'):text('保存','Save')}</button></div>
      </form>
    </Modal>}
  </section>;
}
