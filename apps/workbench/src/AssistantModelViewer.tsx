import {useEffect,useMemo,useState} from 'react';
import {ApiError,cancelled,failureMessage,type WorkbenchApi} from './api';
import {AnalysisModelCard} from './AnalysisModelCard';
import {Btn,Modal} from './Primitives';
import {SceneApi} from './sceneApi';
import type {AssistantModelTarget} from './assistantTasks';
import type {ProjectModel} from './resourceTypes';
import './analysisMaterials.css';

export function AssistantModelViewer({api,target,en,onClose}:{
  api:WorkbenchApi;target:AssistantModelTarget;en:boolean;onClose:()=>void;
}){
  const service=useMemo(()=>new SceneApi(api),[api]);
  const [version,setVersion]=useState<ProjectModel|null>(null);
  const [error,setError]=useState<unknown>(null),[retry,setRetry]=useState(0);
  const t=(zh:string,english:string)=>en?english:zh;
  useEffect(()=>{
    const abort=new AbortController();
    setVersion(null);setError(null);
    void service.model(target.modelAssetId,target.modelVersionId,abort.signal).then(value=>{
      if(abort.signal.aborted)return;
      if(value.modelAssetId!==target.modelAssetId||value.modelVersionId!==target.modelVersionId){
        throw new ApiError(409,'RESOURCE_CHANGED');
      }
      setVersion(value);
    }).catch(value=>{if(!abort.signal.aborted&&!cancelled(value))setError(value);});
    return()=>abort.abort();
  },[service,target.modelAssetId,target.modelVersionId,api.epoch,api.revision,retry]);
  return <Modal className="ac-source-modal as-fixed-model" title={target.title}
    description={t('查看助手结果中的固定模型版本','View the fixed model version from this result')} onClose={onClose}>
    <p className="ap-caption">{t('固定模型版本','Fixed model version')} <code>{target.modelVersionId.slice(0,8)}</code>
      {version?.assetState==='deleted'&&' · '+t('模型在回收站','Model in trash')}</p>
    {version?<div className="ac-expanded"><AnalysisModelCard api={api} version={version} en={en} full inspectSource/></div>
      :error?<div className="ac-source-state"><p role="alert">{failureMessage(error,en?'en':'zh')}</p>
        <Btn onClick={()=>setRetry(value=>value+1)}>{t('重新读取','Read again')}</Btn></div>
      :<p role="status">{t('正在读取固定模型…','Loading the fixed model…')}</p>}
  </Modal>;
}
