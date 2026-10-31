import {useEffect,useRef,useState} from 'react';
import {ApiError,cancelled,failureMessage} from './api';
import {Btn,Modal} from './Primitives';
import type {SceneApi} from './sceneApi';
import type {SceneOpen,SceneSaveRequest} from './sceneTypes';
import {prepareSceneInformationSave} from './sceneInformation';

export function SceneBasicInfoDialog({client,sceneId,projectName,locale,onClose,onSaved}:{
  client:SceneApi;sceneId:string;projectName?:string;locale:string;onClose:()=>void;onSaved:()=>void;
}) {
  const t=(zh:string,en:string)=>locale==='en'?en:zh;
  const [opened,setOpened]=useState<SceneOpen|null>(null),[info,setInfo]=useState({name:'',description:''});
  const [busy,setBusy]=useState(true),[error,setError]=useState<unknown>(null),[unknown,setUnknown]=useState(false),[reload,setReload]=useState(0);
  const pending=useRef<SceneSaveRequest|null>(null),alive=useRef(false),request=useRef<AbortController|null>(null),saving=useRef(false);
  useEffect(()=>{alive.current=true;const abort=new AbortController();request.current=abort;setBusy(true);setError(null);setOpened(null);pending.current=null;setUnknown(false);
    void client.open(sceneId,undefined,abort.signal).then(value=>{if(!abort.signal.aborted){setOpened(value);setInfo({name:value.snapshot.displayName,description:value.snapshot.description||''});}})
      .catch(value=>{if(!abort.signal.aborted&&!cancelled(value))setError(value);}).finally(()=>{if(!abort.signal.aborted)setBusy(false);});
    return()=>{alive.current=false;request.current?.abort();};
  },[client,sceneId,reload]);
  const canWrite=!!opened?.capabilities.canWrite&&opened.sceneRevision===opened.headRevision;
  const conflict=error instanceof ApiError&&error.code==='SCENE_CHANGED';
  const denied=error instanceof ApiError&&error.status===403;
  const changed=!!opened&&(info.name.trim()!==opened.snapshot.displayName||info.description!==(opened.snapshot.description||''));
  async function save(){
    if(!opened||!canWrite||busy||saving.current||conflict||denied)return;
    saving.current=true;const abort=new AbortController();request.current=abort;setBusy(true);setError(null);let submitted=false;
    try{
      if(!pending.current)pending.current=await prepareSceneInformationSave(client,opened,info,crypto.randomUUID(),abort.signal);
      submitted=true;await client.save(pending.current,abort.signal);
      if(alive.current&&!abort.signal.aborted){pending.current=null;setUnknown(false);onSaved();}
    }catch(value){if(alive.current&&!abort.signal.aborted&&!cancelled(value)){
      const uncertain=submitted&&(!(value instanceof ApiError)||value.status>=500);setUnknown(uncertain);if(!uncertain)pending.current=null;setError(value);
    }}finally{saving.current=false;if(alive.current&&!abort.signal.aborted)setBusy(false);}
  }
  return <Modal title={t('场景基本信息','Scene basic information')} description={t('编辑名称和说明后直接保存。','Edit and save the name and description.')} onClose={()=>{if(!busy)onClose();}}>
    <form className="sw-form" onSubmit={event=>{event.preventDefault();void save();}}>
      {!opened&&busy&&<p role="status">{t('正在读取…','Loading…')}</p>}
      {opened&&<><label>{t('所属项目','Project')}<input readOnly value={`${projectName||opened.projectCode} · ${opened.projectCode}`}/></label>
        <label>{t('场景名称','Scene name')}<input required value={info.name} disabled={!canWrite||busy||unknown||denied} onChange={event=>setInfo(value=>({...value,name:event.target.value}))}/></label>
        <label>{t('场景说明（选填）','Description (optional)')}<textarea value={info.description} disabled={!canWrite||busy||unknown||denied} onChange={event=>setInfo(value=>({...value,description:event.target.value}))}/></label>
        <small className="se-note">{t('名称1—200字；说明最多2000字。所属项目在创建时确定。','Name: 1–200 characters. Description: up to 2000 characters. Project ownership is fixed at creation.')}</small>
        <dl className="cw-kv"><dt>{t('场景ID','Scene identity')}</dt><dd className="ov-mono">{opened.sceneId}</dd><dt>{t('最近保存','Last saved')}</dt><dd>{new Date(opened.savedAt).toLocaleString(locale==='zh'?'zh-CN':'en-GB')}</dd></dl></>}
      {!!error&&<p role="alert">{unknown?t('保存结果尚未确认，请重试同一次保存。','The save result is unconfirmed. Retry the same save.'):conflict?t('场景已更新，当前输入已保留。重新读取后再编辑。','The scene has changed. Your input is retained. Reload before editing.'):failureMessage(error,locale)}</p>}
      {(conflict||!opened&&!busy)&&<Btn disabled={busy} onClick={()=>setReload(value=>value+1)}>{t('重新读取','Reload')}</Btn>}
      <div className="sw-actions"><Btn disabled={busy} onClick={onClose}>{t('取消','Cancel')}</Btn><button type="submit" className="ov-btn primary" disabled={!canWrite||busy||conflict||denied||(!changed&&!unknown)||!info.name.trim()}>{busy?t('保存中…','Saving…'):unknown?t('重试保存','Retry save'):t('保存','Save')}</button></div>
    </form>
  </Modal>;
}
