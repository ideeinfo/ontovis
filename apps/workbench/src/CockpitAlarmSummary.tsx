import {useEffect,useState} from 'react';
import {ArrowUpRight,RefreshCw,TriangleAlert} from 'lucide-react';
import {ApiError,cancelled,failureMessage,type WorkbenchApi} from './api';
import {PageDeck} from './CockpitPanels';
import {HOME_REPLAY_SECOND,readCockpitAlarms,replayAlarm,type CockpitAlarmRow,type ReplaySelection} from './cockpitAlarms';
import type {useCockpitAlarmTargets} from './useCockpitAlarmTargets';
import type {CockpitAlarmTarget} from './cockpitAlarmTarget';

export function useCockpitAlarms(api:WorkbenchApi,active:boolean){
 const [rows,setRows]=useState<CockpitAlarmRow[]|null>(null),[loading,setLoading]=useState(false),[error,setError]=useState<unknown>(null),[attempt,setAttempt]=useState(0);
 useEffect(()=>{
  const abort=new AbortController();setRows(null);setError(null);setLoading(active);
  if(active)void readCockpitAlarms(api,abort.signal).then(value=>{if(!abort.signal.aborted)setRows(value);})
   .catch(value=>{if(!abort.signal.aborted&&!cancelled(value))setError(value);}).finally(()=>{if(!abort.signal.aborted)setLoading(false);});
  return()=>abort.abort();
 },[api,api.epoch,api.revision,active,attempt]);
 return {rows,loading,error,reload:()=>setAttempt(value=>value+1)};
}

export function CockpitAlarmSummary({replay,targets,en,onOpen,onReplay}:{replay:ReturnType<typeof useCockpitAlarms>;targets:ReturnType<typeof useCockpitAlarmTargets>;en:boolean;onOpen:(selection:ReplaySelection,target:CockpitAlarmTarget)=>void;onReplay:()=>void}){
 const unavailable=replay.error instanceof ApiError&&replay.error.code==='SIMULATION_PROJECT_REQUIRED';
 const time=(value:string)=>new Intl.DateTimeFormat(en?'en-GB':'zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value));
 return <aside className="pc-panel pc-source pc-home-alarms" aria-label={en?'Simulated alarm overview':'模拟报警概览'}>
  <header><TriangleAlert size={19}/><h3>{en?'Simulated alarms':'模拟报警'}</h3><button className="pc-text-action" onClick={onReplay}>{en?'Replay':'回放'}</button><button className="pc-text-action" aria-label={en?'Reload home alarms':'刷新首页报警'} disabled={replay.loading} onClick={()=>{replay.reload();targets.reload();}}><RefreshCw size={14}/></button></header>
  {!!targets.placements.length&&<label className="pc-alarm-unit"><span>{en?'Exercise unit':'演练设备'}</span><select aria-label={en?'Alarm exercise unit':'报警演练设备'} value={targets.placement?.key||''} onChange={event=>targets.choose(event.target.value)}>{targets.placements.map(row=><option key={row.key} value={row.key}>{row.instance.displayName}</option>)}</select></label>}
  <div className="pc-home-replay"><span>{en?'Replay':'回放'} +{HOME_REPLAY_SECOND}s</span><small>{en?'Source time · UTC+8':'源时间 · UTC+8'}</small></div>
  {replay.loading?<p className="pc-home-alarm-state" role="status">{en?'Loading alarms…':'正在读取报警…'}</p>:replay.error?<div className="pc-home-alarm-state" role={unavailable?'status':'alert'}><p>{unavailable?(en?'No simulation configured for this project':'此项目尚未配置模拟来源'):failureMessage(replay.error,en?'en':'zh')}</p>{!unavailable&&<button onClick={replay.reload}>{en?'Retry':'重试'}</button>}</div>:!replay.rows?.length?<p className="pc-home-alarm-state">{en?'No replay cases':'暂无回放案例'}</p>:
   <PageDeck items={targets.rows} rowHeight={116} en={en} label={en?'Home alarm list':'首页报警列表'} render={row=>{
    const alarm=replayAlarm(row),critical=alarm?.severity==='critical',state=!row.detail?'unavailable':alarm?.state||'pending';
    const status=state==='unavailable'?(en?'Unavailable':'暂不可用'):state==='pending'?(en?'Pending':'未发生'):state==='cleared'?(en?'Cleared':'已恢复'):critical?(en?'Critical':'严重'):(en?'Warning':'警告');
    const targetLabel=row.target?`${row.target.rootName} / ${row.target.displayName}`:targets.loading?(en?'Resolving equipment…':'正在关联设备…'):targets.error?failureMessage(targets.error,en?'en':'zh'):(en?'No matching installed equipment':'未匹配安装设备');
    return <button key={row.dataset.datasetId} className="pc-home-alarm-row" data-state={state} data-severity={alarm?.severity} disabled={!row.target||!alarm} title={`${targetLabel} · ${alarm?time(alarm.sourceTime):'—'}`} aria-label={`${row.dataset.faultCode} · ${row.dataset.title} · ${targetLabel}`} onClick={()=>{if(row.target)onOpen(row.dataset,row.target);}}>
     <span className="pc-home-alarm-meta"><b>{row.dataset.faultCode}</b><span className="pc-home-alarm-badge">{status}</span></span>
     <strong>{row.dataset.title}</strong><span className="pc-home-alarm-time"><span>{row.target?.displayName||targetLabel}</span><ArrowUpRight size={13}/></span>
    </button>;
   }}/>
  }
 </aside>;
}
