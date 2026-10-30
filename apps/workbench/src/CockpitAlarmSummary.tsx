import {useEffect,useState} from 'react';
import {ArrowUpRight,RefreshCw,TriangleAlert} from 'lucide-react';
import {ApiError,cancelled,failureMessage,type WorkbenchApi} from './api';
import {PageDeck} from './CockpitPanels';
import {HOME_REPLAY_SECOND,readCockpitAlarms,replayAlarm,type CockpitAlarmRow,type ReplaySelection} from './cockpitAlarms';

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

export function CockpitAlarmSummary({replay,en,onOpen}:{replay:ReturnType<typeof useCockpitAlarms>;en:boolean;onOpen:(selection:ReplaySelection)=>void}){
 const unavailable=replay.error instanceof ApiError&&replay.error.code==='SIMULATION_PROJECT_REQUIRED';
 const time=(value:string)=>new Intl.DateTimeFormat(en?'en-GB':'zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value));
 return <aside className="pc-panel pc-source pc-home-alarms" aria-label={en?'Simulated alarm overview':'模拟报警概览'}>
  <header><TriangleAlert size={19}/><h3>{en?'Simulated alarms':'模拟报警'}</h3><button className="pc-text-action" aria-label={en?'Reload home alarms':'刷新首页报警'} disabled={replay.loading} onClick={replay.reload}><RefreshCw size={14}/></button></header>
  <div className="pc-home-replay"><span>{en?'Replay':'回放'} +{HOME_REPLAY_SECOND}s</span><small>{en?'Source time · UTC+8':'源时间 · UTC+8'}</small></div>
  {replay.loading?<p className="pc-home-alarm-state" role="status">{en?'Loading alarms…':'正在读取报警…'}</p>:replay.error?<div className="pc-home-alarm-state" role={unavailable?'status':'alert'}><p>{unavailable?(en?'No simulation configured for this project':'此项目尚未配置模拟来源'):failureMessage(replay.error,en?'en':'zh')}</p>{!unavailable&&<button onClick={replay.reload}>{en?'Retry':'重试'}</button>}</div>:!replay.rows?.length?<p className="pc-home-alarm-state">{en?'No replay cases':'暂无回放案例'}</p>:
   <PageDeck items={replay.rows} rowHeight={116} en={en} label={en?'Home alarm list':'首页报警列表'} render={row=>{
    const alarm=replayAlarm(row),critical=alarm?.severity==='critical',state=!row.detail?'unavailable':alarm?.state||'pending';
    const status=state==='unavailable'?(en?'Unavailable':'暂不可用'):state==='pending'?(en?'Pending':'未发生'):state==='cleared'?(en?'Cleared':'已恢复'):critical?(en?'Critical':'严重'):(en?'Warning':'警告');
    return <button key={row.dataset.datasetId} className="pc-home-alarm-row" data-state={state} data-severity={alarm?.severity} aria-label={`${row.dataset.faultCode} · ${row.dataset.title}`} onClick={()=>onOpen(row.dataset)}>
     <span className="pc-home-alarm-meta"><b>{row.dataset.faultCode}</b><span className="pc-home-alarm-badge">{status}</span></span>
     <strong>{row.dataset.title}</strong><span className="pc-home-alarm-time">{row.dataset.cabinet} · {alarm?time(alarm.sourceTime):'—'}<ArrowUpRight size={13}/></span>
    </button>;
   }}/>
  }
 </aside>;
}
