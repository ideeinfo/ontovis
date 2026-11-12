import {useEffect,useState} from 'react';
import {Activity,Focus,Pause,Play,RefreshCw,Wifi,WifiOff} from 'lucide-react';
import {ApiError,cancelled,failureMessage,type WorkbenchApi} from './api';
import {Badge,Btn} from './Primitives';
import {useSimulationStream} from './useSimulationStream';
import {alarmAt,initialReplay,sampleAt,type SimulationCatalogue,type SimulationDetail} from './simulatedAlarms';
import type {EquipmentRecord,ApplicationBundle} from './equipmentApi';
import type {SceneObjectContext} from './sceneEngineeringTypes';
import {equipmentSimulationTarget} from './equipmentSimulationTarget';
import './equipmentSimulation.css';

const ROOT='/api/workbench/analysis-sessions/simulation';
export function EquipmentSimulation({api,record,context,bundle,en,onLocate}:{api:WorkbenchApi;record:EquipmentRecord;context:SceneObjectContext;
  bundle:ApplicationBundle|null;en:boolean;onLocate:(uid:string,revision:string)=>void}){
  const [catalogue,setCatalogue]=useState<SimulationCatalogue|null>(null),[detail,setDetail]=useState<SimulationDetail|null>(null);
  const [selected,setSelected]=useState(''),[error,setError]=useState<unknown>(null),[loading,setLoading]=useState(true),[reload,setReload]=useState(0);
  useEffect(()=>{const abort=new AbortController();setCatalogue(null);setDetail(null);setError(null);setLoading(true);
    void api.request<SimulationCatalogue>(ROOT+'/catalogue',{includeDetail:true},abort.signal).then(value=>{
      if(!abort.signal.aborted){setCatalogue(value);setSelected(value.items[0]?.datasetId||'');}
    }).catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setError(e);}).finally(()=>{if(!abort.signal.aborted)setLoading(false);});
    return()=>abort.abort();
  },[api,api.epoch,api.revision,record.item.entityUid,reload]);
  const profile=catalogue?.items.find(row=>row.datasetId===selected);
  useEffect(()=>{const abort=new AbortController();setDetail(null);if(!profile)return;
    const first=initialReplay(catalogue,profile);
    if(first)setDetail(first);
    else void api.request<SimulationDetail>(ROOT+'/detail',{datasetId:profile.datasetId,datasetRevision:profile.datasetRevision},abort.signal)
      .then(value=>{if(!abort.signal.aborted)setDetail(value);}).catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setError(e);});
    return()=>abort.abort();
  },[api,api.epoch,api.revision,profile?.datasetId,profile?.datasetRevision,catalogue?.initialDetail]);
  const current=detail&&detail.dataset.datasetId===profile?.datasetId?detail:null;
  const target=profile?equipmentSimulationTarget(record,context,bundle,profile):null;
  const stream=useSimulationStream(api,target?current:null),view=stream.view;
  const position=Math.max(0,view?.state.sequence??0),visible=view?.state.detail;
  const state=visible?alarmAt(visible,position):null;
  const receiving=!!view&&['connecting','connected','catchup','reconnecting'].includes(view.status);
  const restart=view?.status==='complete'||view?.error instanceof ApiError&&view.error.status===409;
  const stateName=state==='active'?(en?'Active alarm':'报警中'):state==='cleared'?(en?'Cleared':'已恢复'):(en?'Not occurred':'未发生');
  const labels={connecting:en?'Connecting':'连接中',connected:en?'Receiving':'接收中',catchup:en?'Catching up':'正在补数',reconnecting:en?'Reconnecting':'重连中',stopped:en?'Stopped':'已停止',complete:en?'Exercise complete':'演练结束'};
  const names:Record<string,string>={sensor_temperature:en?'Sensor temperature':'传感器温度',reference_temperature:en?'Independent reference':'独立参照温度',device_feedback:en?'State feedback':'状态反馈',supply_voltage:en?'Supply voltage':'供电电压',overcurrent:en?'Overcurrent':'过流信号'};
  if(loading)return <p role="status">{en?'Loading simulation source…':'正在读取模拟来源…'}</p>;
  if(error instanceof ApiError&&error.code==='SIMULATION_PROJECT_REQUIRED')return <p className="eq-caption">{en?'This project has no simulated monitoring source.':'本项目尚未配置模拟监测来源。'}</p>;
  if(error)return <p className="eq-message" role="alert">{failureMessage(error,en?'en':'zh')} <Btn onClick={()=>setReload(v=>v+1)}>{en?'Retry':'重试'}</Btn></p>;
  return <section className="eq-simulation" aria-label={en?'Per-device simulated monitoring':'单台设备模拟监测'}>
    <header><div><h4>{en?'Per-device simulated monitoring':'单台设备模拟监测'}</h4><p>{en?'No production point mapping is configured. This exercise applies only to the selected device.':'正式测点映射尚未配置；本次演练只展示所选设备，不扩散到同型号其他实例。'}</p></div><Badge tone="amber">{en?'Simulation':'模拟'}</Badge></header>
    <div className="eq-simulation-controls"><label>{en?'Simulated fault':'模拟故障'}<select aria-label={en?'Equipment simulated fault':'设备模拟故障'} value={selected} disabled={receiving} onChange={event=>{stream.reset();setError(null);setSelected(event.target.value);}}>{catalogue?.items.map(row=><option key={row.datasetId} value={row.datasetId}>{row.faultCode} · {row.title}</option>)}</select></label>
      {target&&<>{receiving?<Btn onClick={stream.stop}><Pause size={14}/>{en?'Stop subscription':'停止订阅'}</Btn>:<Btn primary disabled={!current} onClick={()=>stream.start(restart?0:view?.fromSecond??60,!!view&&!restart)}><Play size={14}/>{view?(restart?(en?'Restart exercise':'重新演练'):(en?'Continue exercise':'继续演练')):(en?'Start exercise':'开始演练')}</Btn>}
        <Btn onClick={()=>onLocate(target.item.entityUid,target.item.entityRevision)}><Focus size={14}/>{en?'Locate component':'定位构件'}</Btn>{view&&!restart&&<Btn onClick={()=>{stream.reset();stream.start(0);}}><RefreshCw size={14}/>{en?'Restart':'重新演练'}</Btn>}</>}
    </div>
    {!target?<p className="eq-message"><Activity size={15}/> {en?'This source has no unique declared target in this device’s adopted application. No alarm state was assigned.':'当前来源在此设备的固定采用中没有唯一演练目标，未赋予报警状态。'}</p>:<>
      <dl className="eq-metadata"><dt>{en?'Installed target':'安装目标'}</dt><dd>{target.rootName} / {target.item.displayName}<small className="cw-caption">{target.item.entityUid}</small></dd><dt>{en?'Engineering object':'共享资料对象'}</dt><dd>{target.engineeringRds}<small className="cw-caption">{en?'Location follows the recorded cabinet mapping.':'空间定位使用已登记柜体映射。'}</small></dd></dl>
      <p className={`eq-simulation-status ${stream.stale?'stale':''}`} role="status">{stream.stale?<WifiOff size={14}/>:<Wifi size={14}/>} {view?labels[view.status]:(en?'Not subscribed':'尚未订阅')}{stream.stale?(en?' · Last data is stale':' · 最后数据已过期'):''}{view?.error?` · ${failureMessage(view.error,en?'en':'zh')}`:''}</p>
      {visible&&<><div className="eq-simulation-summary"><div><span>{stream.stale?(en?'Last simulated state':'最后模拟状态'):(en?'Visible simulated event':'本次模拟事件')}</span><strong>{stateName}</strong><small>{visible.dataset.faultCode} · {en?'Not a confirmed device fault':'不代表设备确诊故障'}</small></div><div><span>{en?'Source clock':'模拟源时钟'}</span><strong>{new Date(Date.parse(visible.dataset.timeFrom)+position*1000).toLocaleTimeString(en?'en-GB':'zh-CN',{timeZone:'Asia/Shanghai',hour12:false})}</strong><small>{visible.dataset.timeFrom.slice(0,10)} · UTC+8</small></div></div>
        <div className="eq-simulation-values">{visible.trends.map(row=>{const point=sampleAt(row,position);return <div key={row.metricId}><span>{names[row.metricId]||row.metricId}</span><strong>{point?.quality==='good'?`${point.value} ${row.unit==='degC'?'°C':row.unit==='1'?'':row.unit}`:(en?'Quality gap':'质量异常')}</strong></div>;})}</div></>}
      <h4>{en?'Visible internal equipment':'内部设备状态'}</h4><ul className="eq-simulation-children">{[record.item,...record.children].filter((row,i,all)=>row.entityUid!==record.context.rootEntityUid&&all.findIndex(v=>v.entityUid===row.entityUid)===i).map(row=><li key={row.entityUid}><span>{row.displayName}</span><Badge tone={row.entityUid===target.item.entityUid&&state==='active'?'amber':'neutral'}>{row.entityUid===target.item.entityUid?(state?`${en?'Simulated':'模拟'} · ${stateName}`:(en?'Not subscribed':'尚未订阅')):(en?'No data for this exercise':'无此模拟数据')}</Badge></li>)}</ul>
    </>}
  </section>;
}
