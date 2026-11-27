import {useEffect,useId,useMemo,useRef,useState,type MouseEvent} from 'react';
import {ArrowUpRight,Box,ChevronDown,ChevronRight,LocateFixed,Plus,Search} from 'lucide-react';
import {ApiError,cancelled,failureMessage,type WorkbenchApi} from './api';
import {EquipmentApi,type ConfigurationInstancePage,type ConfigurationInstanceQuery,type ConfigurationSceneInstance,
  type EquipmentConfigurationEdit,type EquipmentConfigurationPreview,type EquipmentConfigurationTarget} from './equipmentApi';
import {AssistantSceneViewer} from './AssistantSceneViewer';
import type {AssistantSceneTarget} from './assistantScene';
import {Btn,Modal} from './Primitives';
import {ResourcePanel} from './ResourcePanel';

function SceneInstanceRows({items,proposal,en,disabled,onLocate}:{
  items:ConfigurationSceneInstance[];proposal?:string;en:boolean;disabled:boolean;
  onLocate:(row:ConfigurationSceneInstance,event:MouseEvent<HTMLButtonElement>)=>void;
}){
  const locate=en?'Locate':'定位';
  return <ul className="as-configuration-instances">{items.map(row=>{
    const duplicate=items.some(other=>other!==row&&other.sceneName===row.sceneName&&other.instanceName===row.instanceName);
    const instance=duplicate?row.instanceName+' · '+row.instanceId.slice(0,8):row.instanceName;
    return <li key={row.sceneId+'/'+row.instanceId}>
      <span><strong>{row.sceneName}</strong> · {instance}
        {row.modelVersionId===proposal&&<small> · {en?'Proposed version':'拟关联版本'}</small>}
      </span>
      <Btn disabled={disabled} aria-label={`${locate} ${row.sceneName} · ${instance}`} onClick={event=>onLocate(row,event)}>
        <LocateFixed size={14}/>{locate}
      </Btn>
    </li>;
  })}</ul>;
}

function InstancePage({page,limit,group,proposal,en,disabled,onLocate,onPage,empty}:{
  page:ConfigurationInstancePage;limit:number;group:string;proposal?:string;en:boolean;disabled:boolean;empty:string;
  onLocate:(row:ConfigurationSceneInstance,event:MouseEvent<HTMLButtonElement>)=>void;onPage:(page:number)=>void;
}){
  const current=page.page??1,start=(current-1)*limit;
  if(!page.items.length)return <p>{empty}</p>;
  return <>
    <SceneInstanceRows items={page.items} proposal={proposal} en={en} disabled={disabled} onLocate={onLocate}/>
    {page.total>limit&&<nav className="as-instance-pagination" aria-label={group}>
      <Btn disabled={disabled||current===1} onClick={()=>onPage(current-1)}>{en?'Previous':'上一页'}</Btn>
      <small aria-live="polite">{start+1}–{start+page.items.length} / {page.total}</small>
      <Btn disabled={disabled||start+limit>=page.total} onClick={()=>onPage(current+1)}>{en?'Next':'下一页'}</Btn>
    </nav>}
  </>;
}

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
  const otherId=useId();
  const [search,setSearch]=useState('');
  const [query,setQuery]=useState<ConfigurationInstanceQuery>({devicePage:1});
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState<unknown>(null);
  useEffect(()=>{
    const abort=new AbortController();
    setLoading(true);setError(null);
    service.configurationPreview({...target,...(proposal?{proposedModelVersionId:proposal}:{})},false,abort.signal,target.device?query:undefined)
      .then(value=>{if(!abort.signal.aborted)setPreview(value);})
      .catch(e=>{
        if(abort.signal.aborted||cancelled(e))return;
        if(e instanceof ApiError&&[401,403].includes(e.status))setPreview(null);
        setError(e);
      })
      .finally(()=>{if(!abort.signal.aborted)setLoading(false);});
    return ()=>abort.abort();
  },[service,target,proposal,query]);

  const pages=preview?.instancePages;
  const busy=loading||!!error;
  const otherOpen=query.otherPage!==undefined;
  const snapshotChanged=error instanceof ApiError&&error.code==='SNAPSHOT_CHANGED';
  const currentGroup=t('当前设备','Current device');
  const othersGroup=t('其他采用设备','Other equipment using this configuration');
  const emptyFilter=t('没有匹配的场景。','No scenes match this filter.');
  function browse(next:ConfigurationInstanceQuery,refresh=false){
    setLoading(true);
    setQuery({...next,expectedSnapshotRevision:refresh?undefined:pages?.snapshotRevision});
  }
  function firstPages(sceneName=query.sceneName){
    return {sceneName,devicePage:1,otherPage:otherOpen?1:undefined};
  }
  function selectCandidate(version:string){
    setPicker(false);
    if(version===proposal)return;
    setPreview(null);setProposal(version);browse(firstPages(),true);
  }
  function locate(row:ConfigurationSceneInstance,event:MouseEvent<HTMLButtonElement>){
    sceneTrigger.current=event.currentTarget;
    setScene({sceneId:row.sceneId,sceneRevision:row.sceneRevision,title:row.sceneName,
      instance:{instanceId:row.instanceId,modelVersionId:row.modelVersionId,equipmentUid:row.equipmentUid}});
  }

  return <>
    <Modal title={t('设备采用配置','Device configuration')} description={t('核对固定模型、构件映射及场景实例。','Review fixed models, component mappings and scene instances.')}
      onClose={onClose} className="as-configuration-dialog">
      <div className="as-configuration">
        <header><strong>{title}</strong><small title={target.configurationRevision}>{t('配置版本','Configuration revision')} · {target.configurationRevision.replace(/^equipment-config:/,'').slice(0,8)}</small></header>
        {!!error&&<div className="as-configuration-status" role="alert">
          <p>{snapshotChanged?t('场景实例列表已更新，请重新读取。','The scene instance list changed. Reload it.'):
            failureMessage(error,en?'en':'zh')}</p>
          <Btn disabled={loading} onClick={()=>browse(firstPages(),true)}>{snapshotChanged?t('重新读取','Reload'):t('重试','Retry')}</Btn>
          {proposal&&!snapshotChanged&&<Btn disabled={loading} onClick={()=>{
            setPreview(null);setProposal(undefined);browse(firstPages(),true);
          }}>{t('返回现有配置','Return to current configuration')}</Btn>}
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
            {pages?<div className="as-instance-browser">
              <form onSubmit={event=>{event.preventDefault();browse(firstPages(search.trim()));}}>
                <input type="search" aria-label={t('按场景名称筛选','Filter by scene name')}
                  placeholder={t('按场景名称筛选','Filter by scene name')} maxLength={200}
                  value={search} onChange={event=>setSearch(event.currentTarget.value)}/>
                <Btn type="submit" disabled={busy}><Search size={14}/>{t('筛选','Filter')}</Btn>
              </form>
              {loading&&<p role="status">{t('正在读取场景实例…','Loading scene instances…')}</p>}
              <div role="region" aria-label={currentGroup} className="as-instance-device">
                <h4>{currentGroup} <small>{pages.device.total} {t('个实例','instances')}</small></h4>
                <InstancePage page={pages.device} limit={pages.limit} group={currentGroup} proposal={preview.proposal?.modelVersionId}
                  en={en} disabled={busy} onLocate={locate} onPage={devicePage=>browse({...query,devicePage})}
                  empty={query.sceneName?emptyFilter:t('此设备暂无保存的场景实例。','This device has no saved scene instances.')}/>
              </div>
              <button type="button" className="as-instance-disclosure" aria-expanded={otherOpen} aria-controls={otherId} disabled={busy}
                onClick={()=>browse({...query,otherPage:otherOpen?undefined:1})}>
                {otherOpen?<ChevronDown size={15}/>:<ChevronRight size={15}/>}
                <span>{othersGroup}</span><small>{pages.others.total} {t('个实例','instances')}</small>
              </button>
              <div id={otherId} role="region" aria-label={othersGroup} hidden={!otherOpen}>
                {pages.others.page!==null&&<InstancePage page={pages.others} limit={pages.limit} group={othersGroup}
                  proposal={preview.proposal?.modelVersionId} en={en} disabled={busy} onLocate={locate}
                  onPage={otherPage=>browse({...query,otherPage})}
                  empty={query.sceneName?emptyFilter:t('其他采用设备暂无保存的场景实例。','Other equipment has no saved scene instances.')}/>}
              </div>
            </div>:preview.impact?<><p>{preview.equipmentCount} {t('台设备采用此配置','devices adopt this configuration')} · {preview.impact.total} {t('个实例引用所列模型','instances reference the listed models')}</p>
              {preview.impact.items.length>0&&<SceneInstanceRows items={preview.impact.items} proposal={preview.proposal?.modelVersionId}
                en={en} disabled={busy} onLocate={locate}/>}
              {preview.impact.total>preview.impact.items.length&&<p>{t('显示前 20 个实例。','Showing the first 20 instances.')}</p>}
            </>:<p role="status">{t('这是历史配置。请重新查询以查看当前采用。','This is a historical configuration. Search again for the current adoption.')}</p>}
            {preview.proposal&&<p>{t('场景保留已保存的模型版本和位置。','Saved scene model versions and placements are retained.')}</p>}
          </section>
        </>}
        <footer className="as-configuration-actions">
          <Btn onClick={onClose}>{t('关闭','Close')}</Btn>
          {onEdit&&preview?.canPrepare&&<>
            <Btn disabled={busy} onClick={()=>setPicker(true)}><Plus size={14}/>{proposal?t('更换拟关联模型','Change proposed model'):t('预览模型关联','Preview model association')}</Btn>
            <Btn disabled={busy} primary onClick={()=>onEdit({...target,...(preview.proposal?{proposedModelVersionId:preview.proposal.modelVersionId}:{})})}><ArrowUpRight size={14}/>{t('在配置页打开','Open configuration editor')}</Btn>
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
      <ResourcePanel api={api} modelsOnly canPlace={false} onPlace={()=>{}} onTerrainReady={()=>{}}
        onPreview={value=>{if(value)selectCandidate(value.modelVersionId);}}/>
    </Modal>}
  </>;
}
