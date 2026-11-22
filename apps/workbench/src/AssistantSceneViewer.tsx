import {lazy,Suspense,useCallback,useEffect,useMemo,useRef,useState} from 'react';
import {ApiError,type WorkbenchApi} from './api';
import {Btn,Modal} from './Primitives';
import {SceneApi} from './sceneApi';
import {canEditAssistantScene,openAssistantScene,type AssistantSceneTarget} from './assistantScene';
import {cockpitInspectionScene} from './cockpitLocation';
import {useCockpitLocation} from './useCockpitLocation';
import {sceneLoadingIdentity,sceneLoadingPlan,scenePreparationStatus,type ScenePreparationState} from './sceneLoading';

const Viewport=lazy(()=>import('./SceneViewport').then(module=>({default:module.SceneViewport})));
const idle=()=>{};
const preventMove=async()=>false;
const visibility={};

export function AssistantSceneViewer({api,target,en,onClose,onEdit,onCloseAutoFocus}:{
 api:WorkbenchApi;target:AssistantSceneTarget;en:boolean;onClose:()=>void;
 onEdit?:(target:AssistantSceneTarget)=>void;onCloseAutoFocus?:(event:Event)=>void;
}){
 const t=(zh:string,english:string)=>en?english:zh;
 const [opened,setOpened]=useState<Awaited<ReturnType<typeof openAssistantScene>>|null>(null);
 const [error,setError]=useState<unknown>(null),[reload,setReload]=useState(0);
 const [choice,setChoice]=useState(''),[requested,setRequested]=useState(''),[attempt,setAttempt]=useState(0);
 const [preparation,setPreparation]=useState<ScenePreparationState|null>(null);
 const modelUse=!!target.modelVersionId;
 const scope=JSON.stringify([api.epoch,api.revision,api.project,target]);
 const viewerApi=useMemo(()=>target.instance||modelUse?api.assistantScope():api,[api,scope,target.instance,modelUse]);
 useEffect(()=>{
  const abort=new AbortController();
  setOpened(null);setError(null);setChoice('');setRequested('');setPreparation(null);
  void openAssistantScene(new SceneApi(viewerApi),viewerApi.project,target,abort.signal)
   .then(value=>{if(!abort.signal.aborted)setOpened(value);})
   .catch(reason=>{if(!abort.signal.aborted)setError(reason);});
  return()=>abort.abort();
 },[viewerApi,scope,target,reload]);
 const scene=opened?.scene??null;
 const instances=modelUse?opened?.modelInstances??[]:scene?.snapshot.instances??[];
 const fixedInstance=opened?.instance??(modelUse&&instances.length===1?instances[0]:null);
 const fixedIds=useMemo(()=>fixedInstance?[fixedInstance.sceneModelInstanceId]:undefined,[fixedInstance]);
 const chosen=instances.find(item=>item.sceneModelInstanceId===choice);
 const selected=instances.find(item=>item.sceneModelInstanceId===requested);
 const modelFocus=modelUse?selected:undefined;
 const previewed=fixedInstance??modelFocus;
 const visibleInstances=useMemo(()=>previewed&&!previewed.visible?{[previewed.sceneModelInstanceId]:true}:visibility,[previewed]);
 const device=!modelUse&&selected?.visible?selected:undefined;
 const location=useCockpitLocation(api,scene,device,device?.rootBinding?.objectRef.entityUid??'',!!device,attempt);
 const displayed=useMemo(()=>cockpitInspectionScene(scene,device,location.representation),[scene,device,location.representation]);
 const preparationKey=useMemo(()=>displayed?sceneLoadingIdentity(sceneLoadingPlan(displayed.snapshot,displayed.resourceRefs),scope+':'+displayed.sceneRevision):'',[displayed,scope]);
 const currentKey=useRef(preparationKey);currentKey.current=preparationKey;
 const prepared=useCallback((key:string,state:ScenePreparationState['state'])=>{
  if(key===currentKey.current)setPreparation(previous=>previous?.key===key&&previous.state===state?previous:{key,state});
 },[]);
 const ready=!!displayed&&scenePreparationStatus(preparationKey,preparation)==='ready';
 const locked=!ready||location.loading;
 const result=location.value;
 const focus=ready&&result?.status==='located'&&result.worldBounds&&result.sceneModelInstanceId
  ?{token:location.token,instanceId:result.sceneModelInstanceId,bounds:result.worldBounds,componentKeys:result.componentKeys}:undefined;
 const locationMessage=location.error?t('定位读取失败，请重试。','Could not locate the equipment. Retry.'):
  location.loading?t('正在核对设备绑定和模型版本…','Checking the equipment binding and model revision…'):
  result&&result.status!=='located'?t('当前场景版本没有可用的设备定位。','This scene revision has no usable equipment location.'):
  focus?(location.representation?.model.representationType==='detailed'
   ?t('已定位 · 完整版','Located · full model'):t('已定位 · 当前可用表示','Located · available representation')):'';
 const loadError=error instanceof ApiError&&[401,403,404,410].includes(error.status)
  ?t('场景版本不可用，或当前权限无法查看。','This scene revision is unavailable or you no longer have access.')
  :(target.instance||modelUse)&&error instanceof ApiError&&error.status===409
   ?t('无法核对保存版本中的实例。请返回并重新查询。','Could not verify the instances in this saved revision. Return and search again.')
   :t('无法加载该保存版本，请重试。','Could not load this saved revision. Retry.');
 return <Modal className="ac-source-modal" title={scene?.snapshot.displayName??target.title}
  description={modelUse?t('查看模型在保存场景中的实例','Locate instances of the model in the saved scene')
   :t('查看已保存场景和定位设备','Preview a saved scene and locate equipment')} onClose={onClose} onCloseAutoFocus={onCloseAutoFocus}>
  <section className="as-scene-preview">
   <header>
    <span title={target.sceneRevision}>{t('保存版本','Saved revision')} · {target.sceneRevision.replace(/^scene:/,'').slice(0,8)}</span>
    {scene&&scene.headRevision!==scene.sceneRevision&&<span>{t('历史版本','Historical revision')}</span>}
    {onEdit&&scene&&canEditAssistantScene(scene,api.project?.projectCode,target)&&
     <Btn onClick={()=>onEdit(target)}>{t('进入场景编辑','Open scene editor')}</Btn>}
    {previewed&&<span title={previewed.sceneModelInstanceId}>{t('实例','Instance')} · {previewed.displayName}</span>}
    {!fixedInstance&&!!instances.length&&<div className="as-scene-controls">
     <select aria-label={modelUse?t('选择模型实例','Select model instance'):t('选择设备','Select equipment')}
      value={choice} disabled={locked} onChange={event=>setChoice(event.currentTarget.value)}>
      <option value="">{modelUse?t('选择模型实例','Select model instance'):t('选择设备','Select equipment')}</option>
      {instances.map(item=><option key={item.sceneModelInstanceId} value={item.sceneModelInstanceId}>{item.displayName}
       {instances.filter(other=>other.displayName===item.displayName).length>1?' · '+item.sceneModelInstanceId.slice(0,8):''}
       {!modelUse&&!item.rootBinding?' · '+t('未绑定','Unbound'):!item.visible?' · '+t('已隐藏','Hidden'):''}</option>)}
     </select>
     <Btn disabled={locked||!chosen||!modelUse&&(!chosen.visible||!chosen.rootBinding)}
      onClick={()=>{setRequested(choice);setAttempt(value=>value+1);}}>{modelUse?t('定位实例','Locate instance'):t('定位设备','Locate equipment')}</Btn>
    </div>}
   </header>
   <div className="as-scene-status" role="status">
    {previewed&&ready?t('已定位 · 固定实例','Located · fixed instance'):
     !modelUse&&chosen&&!chosen.rootBinding?t('该实例尚未绑定安装设备。','This instance has no installation binding.'):
     !modelUse&&chosen&&!chosen.visible?t('此实例在保存版本中已隐藏。','This instance is hidden in the saved revision.'):locationMessage}
   </div>
   <div className="as-scene-viewport">
    {!opened&&<div className="ac-source-state" role={error?'alert':'status'}>{error?loadError:t('正在读取保存的场景…','Loading the saved scene…')}
     {!!error&&<Btn onClick={()=>setReload(value=>value+1)}>{t('重试','Retry')}</Btn>}</div>}
    {opened&&displayed&&<Suspense fallback={<div role="status">{t('正在准备三维视图…','Preparing the 3D view…')}</div>}>
     <Viewport api={viewerApi} sceneKey={displayed.sceneRevision} snapshot={displayed.snapshot} modelRefs={displayed.resourceRefs}
      terrainVersion={opened.terrain} imageryVersion={opened.imagery} imageryVisible={!!displayed.snapshot.imagery?.visible}
      selectedId={previewed?.sceneModelInstanceId??(choice||null)} initialFocusIds={fixedIds}
      focusRequest={modelFocus?{token:attempt,instanceId:modelFocus.sceneModelInstanceId}:undefined}
      componentFocus={focus} preparationKey={preparationKey} onPreparationState={prepared}
      presentation editing={false} disabled={locked} personalVisibility={visibleInstances} terrainVisible pendingPlacement={false}
      onSelect={id=>{if(!locked&&!fixedInstance&&(!modelUse||instances.some(item=>item.sceneModelInstanceId===id)))setChoice(id??'');}}
      onPoint={idle} onMove={preventMove} onViewChange={idle}/>
    </Suspense>}
   </div>
  </section>
 </Modal>;
}
