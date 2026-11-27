import {useEffect,useMemo,useState} from 'react';
import {Check} from 'lucide-react';
import {ApiError,cancelled,failureMessage,type WorkbenchApi} from './api';
import {AnalysisModelCard} from './AnalysisModelCard';
import {Btn,Modal} from './Primitives';
import {SceneApi} from './sceneApi';
import type {AssistantModelTarget} from './assistantTasks';
import type {ModelInfoReceipt,ModelInfoTarget,ProjectModel} from './resourceTypes';
import './analysisMaterials.css';

export function AssistantModelViewer({api,target,en,infoReceipt,onClose,onEdit,onCloseAutoFocus}:{
  api:WorkbenchApi;target:AssistantModelTarget;en:boolean;infoReceipt?:ModelInfoReceipt;onClose:()=>void;
  onEdit?:(target:ModelInfoTarget)=>void;onCloseAutoFocus?:(event:Event)=>void;
}){
  const service=useMemo(()=>new SceneApi(api),[api]);
  const [version,setVersion]=useState<ProjectModel|null>(null);
  const [error,setError]=useState<unknown>(null),[retry,setRetry]=useState(0);
  const t=(zh:string,english:string)=>en?english:zh;
  const infoRevision=version?.assetRevision;
  const saved=version&&infoReceipt?.modelAssetId===version.modelAssetId&&infoReceipt.modelVersionId===version.modelVersionId?infoReceipt:null;
  const saveNumber=saved?.assetRevision.match(/^asset:[^:]+:(\d+)$/)?.[1];
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
  return <Modal className="ac-source-modal as-fixed-model" title={version?.displayName||target.title}
    description={t('查看助手结果中的固定模型版本','View the fixed model version from this result')} onClose={onClose} onCloseAutoFocus={onCloseAutoFocus}>
    <div className="as-scene-controls">
      <p className="ap-caption">{t('固定模型版本','Fixed model version')} <code>{target.modelVersionId.slice(0,8)}</code>
        {version?.assetState==='deleted'&&' · '+t('模型在回收站','Model in trash')}</p>
      {onEdit&&infoRevision&&version?.capabilities.canEditInfo===true&&version.assetState==='active'&&
        <Btn onClick={()=>onEdit({modelAssetId:version.modelAssetId,modelVersionId:version.modelVersionId,expectedAssetRevision:infoRevision})}>
          {t('编辑模型基本信息','Edit model information')}
        </Btn>}
    </div>
    {saved&&<p className="as-model-edit-receipt" role="status"><Check size={14} aria-hidden="true"/>
      {t('模型基本信息已保存','Model information saved')}
      <code title={saved.assetRevision} aria-label={`${t('资产修订','Asset revision')} ${saved.assetRevision}`}>{saveNumber?`r${saveNumber}`:saved.assetRevision.slice(0,8)}</code>
    </p>}
    {version?<div className="ac-expanded"><AnalysisModelCard api={api} version={version} en={en} full inspectSource/></div>
      :error?<div className="ac-source-state"><p role="alert">{failureMessage(error,en?'en':'zh')}</p>
        <Btn onClick={()=>setRetry(value=>value+1)}>{t('重新读取','Read again')}</Btn></div>
      :<p role="status">{t('正在读取固定模型…','Loading the fixed model…')}</p>}
  </Modal>;
}
