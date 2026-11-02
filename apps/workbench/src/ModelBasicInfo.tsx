import {useEffect,useMemo,useRef,useState} from 'react';
import {ApiError,cancelled} from './api';
import {Btn,Modal} from './Primitives';
import {usePreferences} from './Preferences';
import type {SceneApi} from './sceneApi';
import type {ModelPurpose,ProjectModel,ProjectModelWrite,ProjectTurbineDefinition} from './resourceTypes';
import {modelRepresentationFields,privateDenial,ResourceRequestGate,ResourceRequestId,resourceFailure,writeDenial} from './resourceForms';
import {resourceText} from './resourceMessages';

export function ModelBasicInfo({api,version,canEdit,onUpdated,onWriteDenied,onPrivateDenied,turbines:initialTurbines}:{
  api:SceneApi;version:ProjectModel;canEdit:boolean;onUpdated:(value:ProjectModelWrite)=>void;
  onWriteDenied:()=>void;onPrivateDenied:()=>void;turbines?:ProjectTurbineDefinition[];
}) {
  const {locale}=usePreferences(),text=(zh:string,en:string)=>locale==='zh'?zh:en;
  const [editing,setEditing]=useState(false),[name,setName]=useState(''),[purpose,setPurpose]=useState<ModelPurpose>('equipment');
  const [description,setDescription]=useState(''),[expected,setExpected]=useState('');
  const [selectedTurbineUid,setSelectedTurbineUid]=useState<string>('');
  const [representationType,setRepresentationType]=useState<'appearance'|'detailed'|''>('');
  const [turbines,setTurbines]=useState<ProjectTurbineDefinition[]>(initialTurbines||[]);
  const [busy,setBusy]=useState(false),[error,setError]=useState<unknown>(null);
  const gate=useMemo(()=>new ResourceRequestGate(),[]),requestId=useRef(new ResourceRequestId());

  useEffect(()=>()=>gate.cancel(),[gate]);

  useEffect(()=>{
    setTurbines(initialTurbines||[]);
    if(initialTurbines)return;
    const abort=new AbortController();
    api.turbineDefinitions(undefined,abort.signal)
      .then(res=>{if(!abort.signal.aborted)setTurbines(res.items);})
      .catch(value=>{if(!abort.signal.aborted&&!cancelled(value))failed(value);});
    return()=>abort.abort();
  },[api,initialTurbines]);

  function fill(value:ProjectModel){
    setName(value.displayName);
    setPurpose(value.purpose||'equipment');
    setDescription(value.description||'');
    setExpected(value.assetRevision||'');
    setSelectedTurbineUid(value.definitionEntityUid||'');
    setRepresentationType(value.representationType||'');
    setError(null);
    requestId.current.reset();
  }

  function failed(value:unknown){
    if(cancelled(value))return;
    if(privateDenial(value)){onPrivateDenied();return;}
    if(writeDenial(value))onWriteDenied();
    setError(value);
  }

  async function save(){
    if(!canEdit||busy||!name.trim()||!expected)return;
    let association;
    try{association=modelRepresentationFields(version,selectedTurbineUid,representationType,turbines);}
    catch(value){failed(value);return;}
    const body={
      modelAssetId:version.modelAssetId,
      modelVersionId:version.modelVersionId,
      expectedAssetRevision:expected,
      displayName:name.trim(),
      purpose,
      description,
      ...association
    };
    const clientRequestId=requestId.current.forPayload(body),request=gate.start();
    setBusy(true);setError(null);
    try{
      const value=await api.saveModelInfo({...body,clientRequestId},request.signal);
      if(request.isCurrent()){
        setEditing(false);
        onUpdated(value);
      }
    }catch(value){if(request.isCurrent())failed(value);}
    finally{if(request.isCurrent())setBusy(false);}
  }

  async function reload(){
    const request=gate.start();setBusy(true);
    try{
      const value=await api.model(version.modelAssetId,version.modelVersionId,request.signal);
      if(request.isCurrent())fill(value);
    }catch(value){if(request.isCurrent())failed(value);}
    finally{if(request.isCurrent())setBusy(false);}
  }

  const conflict=error instanceof ApiError&&error.code==='MODEL_ASSET_CHANGED';

  return <section aria-label={text('基本信息','Basic information')}>
    <div className="ov-resource-actions">
      <strong>{text('基本信息','Basic information')}</strong>
      {canEdit&&version.assetRevision&&<Btn onClick={()=>{fill(version);setEditing(true);}}>{text('编辑','Edit')}</Btn>}
    </div>
    <dl className="ov-resource-facts">
      <dt>{text('名称','Name')}</dt>
      <dd>{version.displayName}</dd>
      <dt>{text('模型型号声明','Declared model type')}</dt>
      <dd>{version.modelCode||text('未声明','Unspecified')}</dd>
      {turbines.some(item=>item.projectApplicationRef&&[item.appearanceModel,item.detailedModel].some(model=>model?.modelVersionId===version.modelVersionId))&&<>
        <dt>{text('项目型号关联','Project type associations')}</dt>
        <dd>{turbines.filter(item=>item.projectApplicationRef&&[item.appearanceModel,item.detailedModel].some(model=>model?.modelVersionId===version.modelVersionId)).map(item=><div key={item.catalogueKey}>{item.displayName}</div>)}</dd>
      </>}
      <dt>{text('模型形态','Representation')}</dt>
      <dd>
        {version.representationType==='detailed'
          ?text('完整版（用户声明）','Detailed (declared)')
          :version.representationType==='appearance'?text('外观版（用户声明）','Appearance (declared)'):text('未声明','Unspecified')}
      </dd>
      {version.purpose&&<><dt>{text('用途','Purpose')}</dt><dd>{resourceText(locale,version.purpose)}</dd></>}
      <dt>{text('说明','Description')}</dt>
      <dd>{version.description||'—'}</dd>
    </dl>
    {editing&&<Modal title={text('编辑模型基本信息','Edit model information')} description={text('修改模型名称、形态与用途；项目型号关联在设备层级中管理。','Edit the model name, representation and purpose. Manage project type associations in Equipment hierarchy.')} onClose={()=>{if(!busy)setEditing(false);}}>
      <form className="ov-resource-form" onSubmit={event=>{event.preventDefault();void save();}}>
        <label>
          {text('工程对象定义（兼容关联）','Engineering object definition (legacy)')}
          <select value={selectedTurbineUid} disabled={busy} onChange={event=>{
            const uid=event.target.value;
            setSelectedTurbineUid(uid);
            const chosen=turbines.find(t=>t.definitionEntityUid===uid);
            if(chosen){
              const repLabel=representationType==='appearance'?text('外观版','Appearance'):text('完整版','Detailed');
              setName(`${chosen.displayName||chosen.modelCode} · ${repLabel}`);
            }
          }}>
            <option value="">{text('不关联（通用独立模型）','None (generic independent model)')}</option>
            {selectedTurbineUid&&!turbines.some(item=>item.definitionEntityUid===selectedTurbineUid)&&<option value={selectedTurbineUid}>{version.modelCode||text('当前关联（待核对）','Current association (review required)')}</option>}
            {turbines.filter(t=>t.definitionEntityUid).map(t=><option key={t.definitionEntityUid} value={t.definitionEntityUid!}>{t.manufacturer?`${t.manufacturer} · `:''}{t.displayName||t.modelCode} ({t.modelCode})</option>)}
          </select>
        </label>
        <label>
          {text('模型形态设置','Model representation')}
          <select value={representationType} disabled={busy} onChange={event=>{
            const rep=event.target.value as 'appearance'|'detailed'|'';
            setRepresentationType(rep);
            const chosen=turbines.find(t=>t.definitionEntityUid===selectedTurbineUid);
            if(chosen){
              const repLabel=rep==='appearance'?text('外观版','Appearance'):text('完整版','Detailed');
              setName(`${chosen.displayName||chosen.modelCode} · ${repLabel}`);
            }
          }}>
            <option value="">{text('未声明','Unspecified')}</option>
            <option value="appearance">{text('外观版','Appearance')}</option>
            <option value="detailed">{text('完整版（查看能力以实际模型为准）','Detailed (inspection depends on actual content)')}</option>
          </select>
        </label>
        <label>
          {text('名称','Name')}
          <input required maxLength={200} value={name} disabled={busy} onChange={event=>setName(event.target.value)}/>
        </label>
        <label>
          {text('用途','Purpose')}
          <select value={purpose} disabled={busy} onChange={event=>setPurpose(event.target.value as ModelPurpose)}>
            {(['equipment','simplified_scene','environment'] as const).map(value=><option key={value} value={value}>{resourceText(locale,value)}</option>)}
          </select>
        </label>
        <label>
          {text('说明','Description')}
          <textarea rows={4} maxLength={2000} value={description} disabled={busy} onChange={event=>setDescription(event.target.value)}/>
        </label>
        {!!error&&<p role="alert" className="ov-resource-error">{conflict?text('基本信息已更新，当前修改已保留。','Basic information has changed. Your edits are retained.'):resourceFailure(error,locale)}</p>}
        {conflict&&<><p className="ov-resource-caption">{text('重新读取将替换当前修改。','Reloading replaces your current edits.')}</p><Btn disabled={busy} onClick={()=>void reload()}>{text('重新读取','Reload')}</Btn></>}
        <div className="ov-resource-actions end">
          <Btn disabled={busy} onClick={()=>setEditing(false)}>{text('取消','Cancel')}</Btn>
          <button type="submit" className="ov-btn primary" disabled={busy||!canEdit||!name.trim()}>{busy?text('保存中…','Saving…'):text('保存','Save')}</button>
        </div>
      </form>
    </Modal>}
  </section>;
}
