import {useEffect,useMemo,useRef,useState} from 'react';
import {ArrowUpRight,Box,LocateFixed,Plus} from 'lucide-react';
import {cancelled,failureMessage,type WorkbenchApi} from './api';
import {EquipmentApi,type EquipmentConfigurationEdit,type EquipmentConfigurationPreview,type EquipmentConfigurationTarget} from './equipmentApi';
import {AssistantSceneViewer} from './AssistantSceneViewer';
import type {AssistantSceneTarget} from './assistantScene';
import {Btn,Modal} from './Primitives';
import {ResourcePanel} from './ResourcePanel';

export function AssistantEquipmentConfiguration({api,target,title,en,onClose,onEdit}:{
  api:WorkbenchApi;target:EquipmentConfigurationTarget;title:string;en:boolean;onClose:()=>void;
  onEdit?:(target:EquipmentConfigurationEdit)=>void;
}){
  const t=(zh:string,english:string)=>en?english:zh;
  const service=useMemo(()=>new EquipmentApi(api),[api]);
  const [preview,setPreview]=useState<EquipmentConfigurationPreview|null>(null);
  const [proposal,setProposal]=useState<string>();
  const [picker,setPicker]=useState(false);
  const [scene,setScene]=useState<AssistantSceneTarget|null>(null);
  const sceneTrigger=useRef<HTMLButtonElement|null>(null);
  const [error,setError]=useState<unknown>(null);
  const [attempt,setAttempt]=useState(0);
  useEffect(()=>{
    const abort=new AbortController();
    setPreview(null);setError(null);
    service.configurationPreview({...target,...(proposal?{proposedModelVersionId:proposal}:{})},false,abort.signal)
      .then(value=>{if(!abort.signal.aborted)setPreview(value);})
      .catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setError(e);});
    return ()=>abort.abort();
  },[service,target,proposal,attempt]);
  function selectCandidate(version:string){
    setPicker(false);
    if(version===proposal)return;
    setPreview(null);setProposal(version);
  }
  return <>
    <Modal title={t('设备采用配置','Device configuration')} description={t('核对固定模型、构件映射及场景实例。','Review fixed models, component mappings and scene instances.')}
      onClose={onClose} className="as-configuration-dialog">
      <div className="as-configuration">
        <header><strong>{title}</strong><small title={target.configurationRevision}>{t('配置版本','Configuration revision')} · {target.configurationRevision.replace(/^equipment-config:/,'').slice(0,8)}</small></header>
        {!!error&&<div className="as-configuration-status" role="alert">
          <p>{failureMessage(error,en?'en':'zh')}</p>
          {proposal?<Btn onClick={()=>setProposal(undefined)}>{t('返回现有配置','Return to current configuration')}</Btn>:
            <Btn onClick={()=>setAttempt(n=>n+1)}>{t('重试','Retry')}</Btn>}
        </div>}
        {!error&&!preview&&<p role="status">{t('正在读取配置及场景实例…','Reading configuration and scene instances…')}</p>}
        {preview&&<>
          <section aria-label={t('固定模型与构件映射','Fixed models and component mappings')}>
            <h3>{t('固定模型与构件映射','Fixed models and component mappings')}</h3>
            {preview.models.length===0&&<p>{t('此配置尚无固定模型。','This configuration has no fixed models.')}</p>}
            {preview.models.map(model=>{
              const mappings=preview.snapshot.models.find(row=>row.modelVersionId===model.modelVersionId)?.mappings??[];
              return <details key={model.modelVersionId}>
                <summary><Box size={14}/><strong>{model.displayName}</strong>
                  <small title={model.modelVersionId}>{model.modelVersionId.slice(0,8)} · {mappings.length} {t('项映射','mappings')}
                    {model.assetState==='deleted'&&' · '+t('在回收站','In trash')}</small></summary>
                {mappings.length?<dl>{mappings.map(row=><div key={row.objectRef.entityUid}>
                  <dt title={row.objectRef.entityUid}>{preview.objectNames[row.objectRef.entityUid]??row.objectRef.entityUid}</dt>
                  <dd>{row.componentKeys.join('、')||t('无构件','No components')}</dd>
                </div>)}</dl>:<p>{t('此版本尚无构件映射。','No component mappings for this version.')}</p>}
              </details>;
            })}
          </section>
          {preview.proposal&&<section className="as-configuration-proposal" aria-label={t('拟关联模型','Proposed model association')}>
            <h3>{t('拟关联模型','Proposed model association')}</h3>
            <strong>{preview.proposal.displayName}</strong> · <small title={preview.proposal.modelVersionId}>{preview.proposal.modelVersionId.slice(0,8)}</small>
            <p>{t('保存后，此固定版本会加入采用配置。可在配置页继续设置构件映射。','Saving adds this fixed version to the adoption configuration. Component mappings can be added in the editor.')}</p>
          </section>}
          <section>
            <h3>{t('已保存场景实例','Saved scene instances')}</h3>
            {preview.impact?<><p>{preview.equipmentCount} {t('台设备采用此配置','devices adopt this configuration')} · {preview.impact.total} {t('个实例引用所列模型','instances reference the listed models')}</p>
              {preview.impact.items.length>0&&<ul className="as-configuration-instances">{preview.impact.items.map(row=><li key={row.sceneId+'/'+row.instanceId}>
                <span><strong>{row.sceneName}</strong> · {row.instanceName}
                  {row.modelVersionId===preview.proposal?.modelVersionId&&<small> · {t('拟关联版本','Proposed version')}</small>}
                </span>
                <Btn aria-label={`${t('定位','Locate')} ${row.sceneName} · ${row.instanceName}`} onClick={event=>{
                  sceneTrigger.current=event.currentTarget;
                  setScene({sceneId:row.sceneId,sceneRevision:row.sceneRevision,title:row.sceneName,
                    instance:{instanceId:row.instanceId,modelVersionId:row.modelVersionId,equipmentUid:row.equipmentUid}});
                }}><LocateFixed size={14}/>{t('定位','Locate')}</Btn>
              </li>)}</ul>}
              {preview.impact.total>preview.impact.items.length&&<p>{t('显示前 20 个实例。','Showing the first 20 instances.')}</p>}
              {preview.proposal&&<p>{t('场景保留已保存的模型版本和位置。','Saved scene model versions and placements are retained.')}</p>}
            </>:<p role="status">{t('这是历史配置。请重新查询以查看当前采用。','This is a historical configuration. Search again for the current adoption.')}</p>}
          </section>
        </>}
        <footer className="as-configuration-actions">
          <Btn onClick={onClose}>{t('关闭','Close')}</Btn>
          {onEdit&&preview?.canPrepare&&<>
            <Btn onClick={()=>setPicker(true)}><Plus size={14}/>{proposal?t('更换拟关联模型','Change proposed model'):t('预览模型关联','Preview model association')}</Btn>
            <Btn primary onClick={()=>onEdit({...target,...(preview.proposal?{proposedModelVersionId:preview.proposal.modelVersionId}:{})})}><ArrowUpRight size={14}/>{t('在配置页打开','Open configuration editor')}</Btn>
          </>}
        </footer>
      </div>
    </Modal>
    {scene&&<AssistantSceneViewer api={api} target={scene} en={en} onClose={()=>setScene(null)}
      onCloseAutoFocus={event=>{
        if(!sceneTrigger.current?.isConnected)return;
        event.preventDefault();
        sceneTrigger.current.focus({preventScroll:true});
      }}/>}
    {picker&&onEdit&&<Modal title={t('选择固定模型版本','Choose a fixed model version')} description={t('从模型目录选择已保存版本。','Select a saved version from the model catalogue.')}
      onClose={()=>setPicker(false)} className="as-configuration-dialog">
      <ResourcePanel api={api} modelsOnly canPlace={false} canAcquire={false} onPlace={()=>{}} onTerrainReady={()=>{}}
        onPreview={value=>{if(value)selectCandidate(value.modelVersionId);}}/>
    </Modal>}
  </>;
}
