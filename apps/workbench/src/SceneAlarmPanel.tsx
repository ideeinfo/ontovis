import {displayText} from './displayText';
import {useEffect,useMemo,useState} from 'react';
import {Activity,ChevronDown,ChevronUp,Focus,Pause,Play,RefreshCw,X} from 'lucide-react';
import {ApiError,cancelled,failureMessage,type WorkbenchApi} from './api';
import {Btn,IconBtn} from './Primitives';
import {SceneApi} from './sceneApi';
import {EquipmentApi,type EquipmentRecord,type ApplicationBundle} from './equipmentApi';
import type {SceneObjectContext} from './sceneEngineeringTypes';
import type {EditableSceneSnapshot} from './sceneTypes';
import {equipmentSimulationTarget} from './equipmentSimulationTarget';
import {useSimulationStream} from './useSimulationStream';
import {alarmAt,initialReplay,type SimulationCatalogue,type SimulationDetail} from './simulatedAlarms';
import {alarmLabel,sceneAlarmInstances,sceneAlarmState,type SceneAlarm} from './sceneAlarm';
import './sceneAlarm.css';
const ROOT='/api/workbench/analysis-sessions/simulation';
export function SceneAlarmPanel({api,snapshot,en,onAlarm,onFocus,onClose}:{api:WorkbenchApi;snapshot:EditableSceneSnapshot;en:boolean;
 onAlarm:(alarm:SceneAlarm|null)=>void;onFocus:(id:string)=>void;onClose:()=>void}){
 const instances=useMemo(()=>sceneAlarmInstances(snapshot),[snapshot.instances]);
 const [collapsed,setCollapsed]=useState(false);
 const [instanceId,setInstance]=useState(instances[0]?.sceneModelInstanceId||''),[datasetId,setDataset]=useState('');
 const [catalogue,setCatalogue]=useState<SimulationCatalogue|null>(null),[detail,setDetail]=useState<SimulationDetail|null>(null);
 const [source,setSource]=useState<{record:EquipmentRecord;context:SceneObjectContext;bundle:ApplicationBundle}|null>(null);
 const [error,setError]=useState<unknown>(null),[loading,setLoading]=useState(false),[reload,setReload]=useState(0);
 const instance=instances.find(item=>item.sceneModelInstanceId===instanceId),uid=instance?.rootBinding?.objectRef.entityUid;
 useEffect(()=>{const abort=new AbortController();setCatalogue(null);setError(null);
  void api.request<SimulationCatalogue>(ROOT+'/catalogue',{includeDetail:true},abort.signal).then(value=>{if(!abort.signal.aborted){setCatalogue(value);setDataset(value.items[0]?.datasetId||'');}}).catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setError(e);});
  return()=>abort.abort();
 },[api,api.epoch,api.revision,reload]);
 useEffect(()=>{const abort=new AbortController();setSource(null);setError(null);if(!uid)return;setLoading(true);
  const equipment=new EquipmentApi(api);
  void Promise.all([equipment.resolve([uid],abort.signal),new SceneApi(api).objectContext(uid,undefined,abort.signal)]).then(async([value,context])=>{
   const record=value.items.find(row=>row.item.entityUid===uid);
   if(!record?.adoption||record.context.rootEntityUid!==uid)throw new ApiError(409,'ENGINEERING_CHANGED');
   const bundle=await equipment.application(record.adoption.applicationRevisionId,abort.signal);
   if(!abort.signal.aborted)setSource({record,context,bundle});
  }).catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setError(e);}).finally(()=>{if(!abort.signal.aborted)setLoading(false);});
  return()=>abort.abort();
 },[api,api.epoch,api.revision,uid,reload]);
 const profile=catalogue?.items.find(row=>row.datasetId===datasetId);
 useEffect(()=>{const abort=new AbortController();setDetail(null);if(!profile)return;
  const first=initialReplay(catalogue,profile);if(first)setDetail(first);
  else void api.request<SimulationDetail>(ROOT+'/detail',{datasetId:profile.datasetId,datasetRevision:profile.datasetRevision},abort.signal).then(value=>{if(!abort.signal.aborted)setDetail(value);}).catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setError(e);});
  return()=>abort.abort();
 },[api,profile?.datasetId,profile?.datasetRevision,catalogue]);
 // Remount the stream hook on identity changes in the parent; data never follows a shared model name.
 const stream=useSimulationStream(api,detail),view=stream.view,visible=view?.state.detail;
 const target=source&&profile?equipmentSimulationTarget(source.record,source.context,source.bundle,profile):null;
 const state=sceneAlarmState(view?.state.sequence,stream.stale,visible?alarmAt(visible,view!.state.sequence):'pending');
 const receiving=!!view&&['connecting','connected','catchup','reconnecting'].includes(view.status);
 useEffect(()=>{onAlarm(view&&target&&instance&&state?{instanceId:instance.sceneModelInstanceId,state,
  label:`${en?'Test data':'测试'} · ${profile?.faultCode} · ${alarmLabel(state,en)}`,target:target.item.displayName}:null);
 },[!!view,view?.status,target?.item.entityUid,instance?.sceneModelInstanceId,profile?.faultCode,state,en,onAlarm]);
 useEffect(()=>()=>onAlarm(null),[onAlarm]);
 const changeInstance=(id:string)=>{stream.reset();setInstance(id);};
 return <section className={`sw-alarm-panel${collapsed?' collapsed':''}`} aria-label={en?'Scene alarm replay':'场景告警回放'}>
  <header><Activity size={16}/><strong>{en?'Alarm replay':'告警回放'}</strong><span className="ad-badge amber">{en?'Test data':'测试'}</span><IconBtn label={collapsed?(en?'Expand alarm panel':'展开告警面板'):(en?'Collapse alarm panel':'收起告警面板')} onClick={()=>setCollapsed(v=>!v)}>{collapsed?<ChevronDown size={14}/>:<ChevronUp size={14}/>}</IconBtn><IconBtn label={en?'Close alarm replay':'关闭告警回放'} onClick={onClose}><X size={14}/></IconBtn></header>
  {!collapsed&&<><label>{en?'Placed device':'已布置设备'}<select aria-label={en?'Scene alarm device':'场景告警设备'} value={instanceId} onChange={e=>changeInstance(e.target.value)}>{instances.map(item=><option key={item.sceneModelInstanceId} value={item.sceneModelInstanceId}>{displayText(item.displayName)}</option>)}</select></label>
  <label>{en?'Fault to replay':'回放故障'}<select aria-label={en?'Scene fault to replay':'场景回放故障'} value={datasetId} onChange={e=>{stream.reset();setDataset(e.target.value);}}>{catalogue?.items.map(row=><option key={row.datasetId} value={row.datasetId}>{row.faultCode} · {displayText(row.title)}</option>)}</select></label>
  {loading?<p role="status">{en?'Resolving the installed target…':'正在核对安装目标…'}</p>:target?<p className="sw-alarm-target">{target.rootName} / {displayText(target.item.displayName)}<small>{en?'Replay state is shown on this instance only. Location is at cabinet level.':'回放状态只显示在此实例，定位到柜体。'}</small></p>:<p>{en?'No unique installed target. No state was assigned.':'未找到唯一安装目标，未赋予告警状态。'}</p>}
  {!!error&&<p role="alert">{failureMessage(error,en?'en':'zh')}<Btn onClick={()=>setReload(v=>v+1)}><RefreshCw size={13}/>{en?'Retry':'重试'}</Btn></p>}
  <div className="sw-alarm-controls">{receiving?<Btn onClick={stream.stop}><Pause size={14}/>{en?'Stop':'停止订阅'}</Btn>:<Btn primary disabled={!target||!detail||loading||!!error} onClick={()=>stream.start(view?.status==='complete'?0:view?.fromSecond??60,!!view&&view.status!=='complete')}><Play size={14}/>{view?(en?'Continue':'继续回放'):(en?'Start replay':'开始回放')}</Btn>}
   <Btn disabled={!instance} onClick={()=>{if(instance){onFocus(instance.sceneModelInstanceId);setCollapsed(true);}}}><Focus size={14}/>{en?'Locate device':'定位设备'}</Btn>{view&&<Btn onClick={()=>{stream.reset();stream.start(0);}}><RefreshCw size={14}/>{en?'Restart':'重新回放'}</Btn>}</div>
  </>}{view&&<p className={`sw-alarm-status ${state||'pending'}`} role="status">{state?`${alarmLabel(state,en)} · ${view.state.sequence} s`:(en?'Waiting for the first frame…':'等待首帧…')}{view.error?` · ${failureMessage(view.error,en?'en':'zh')}`:''}</p>}
  {!collapsed&&<small>{en?'The clock uses replay data. Scene changes require a manual save. Live monitoring points are unconnected.':'时钟来自回放数据。场景需手动保存，现场测点尚未接入。'} {en?'Hidden or unloaded models stay unchanged.':'隐藏或未加载的模型不会自动加载。'}</small>}
 </section>;
}
