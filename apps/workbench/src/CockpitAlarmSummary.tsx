import {displayText} from './displayText';
import {useEffect,useState} from 'react';
import {ArrowUpRight,CircleCheck,CircleMinus,Clock3,RefreshCw,TriangleAlert,WifiOff} from 'lucide-react';
import {ApiError,cancelled,failureMessage,type WorkbenchApi} from './api';
import {PageDeck} from './CockpitPanels';
import {readCockpitAlarms,cockpitAlarmPresentation,type CockpitAlarmPresentation,type CockpitAlarmRow,type ReplayPositions,type ReplaySelection} from './cockpitAlarms';
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

const statusIcon={active:TriangleAlert,cleared:CircleCheck,pending:Clock3,stale:WifiOff,unavailable:CircleMinus};

export function CockpitAlarmStatus({value}:{value:Pick<CockpitAlarmPresentation,'state'|'status'|'severity'>}){
 const Icon=statusIcon[value.state];
 return <span className="pc-alarm-status pc-alarm-appearance" data-state={value.state} data-severity={value.severity}>
  <Icon size={13} aria-hidden="true"/>{value.status}
 </span>;
}

export function CockpitAlarmSummary({replay,targets,positions,en,onOpen,onReplay}:{replay:ReturnType<typeof useCockpitAlarms>;targets:ReturnType<typeof useCockpitAlarmTargets>;positions:ReplayPositions;en:boolean;onOpen:(selection:ReplaySelection,target:CockpitAlarmTarget)=>void;onReplay:()=>void}){
 const unavailable=replay.error instanceof ApiError&&replay.error.code==='SIMULATION_PROJECT_REQUIRED';
 return <aside className="pc-panel pc-source pc-home-alarms" aria-label={en?'Alarm replay overview':'报警回放概览'}>
  <header><TriangleAlert size={19}/><h3>{en?'Alarms':'报警'}</h3><small className="pc-sim-label">{en?'Test':'测试'}</small><button className="pc-text-action" onClick={onReplay}>{en?'Replay':'回放'}</button><button className="pc-text-action" aria-label={en?'Refresh alarms':'刷新首页报警'} disabled={replay.loading} onClick={replay.reload}><RefreshCw size={14}/></button></header>
  {!!targets.units.length&&<label className="pc-alarm-unit"><span>{en?'Equipment filter':'按风机筛选'}</span><select aria-label={en?'Alarm target equipment':'报警目标设备'} value={targets.selected} onChange={event=>targets.choose(event.target.value)}><option value="">{en?'All equipment':'全部风机'}</option>{targets.units.map(([id,name])=><option key={id} value={id}>{name}</option>)}</select></label>}
  <div className="pc-home-replay"><span>{en?'Replay position':'回放位置'}</span><small>{en?'Source time · UTC+8':'源时间 · UTC+8'}</small></div>
  {replay.loading?<p className="pc-home-alarm-state" role="status">{en?'Loading alarms…':'正在读取报警…'}</p>:replay.error?<div className="pc-home-alarm-state" role={unavailable?'status':'alert'}><p>{unavailable?(en?'No alarm replay data configured for this project':'此项目尚未配置报警回放数据'):failureMessage(replay.error,en?'en':'zh')}</p>{!unavailable&&<button onClick={replay.reload}>{en?'Retry':'重试'}</button>}</div>:!replay.rows?.length?<p className="pc-home-alarm-state">{en?'No replay cases':'暂无回放案例'}</p>:
   <PageDeck key={targets.selected} items={targets.visibleRows} rowHeight={116} en={en} label={en?'Home alarm list':'首页报警列表'} render={row=>{
    const targetLabel=row.registration?`${row.registration.rootName} / ${row.registration.displayName}`:(en?'No matching installed equipment':'未匹配安装设备');
    return <CockpitAlarmCard key={row.dataset.datasetId} row={row} positions={positions} en={en} targetLabel={targetLabel} onOpen={onOpen}/>;
   }}/>
  }
 </aside>;
}

export function CockpitAlarmCard({row,positions,en,targetLabel,compact=false,disabled=false,onOpen}:{row:CockpitAlarmRow&{target:CockpitAlarmTarget|null};positions:ReplayPositions;en:boolean;targetLabel?:string;compact?:boolean;disabled?:boolean;onOpen:(selection:ReplaySelection,target:CockpitAlarmTarget)=>void}){
 const {alarm,state,status,severity,second}=cockpitAlarmPresentation(row,en,positions);
 const Icon=statusIcon[state],canLocate=!!row.target&&!!alarm&&(state==='active'||state==='cleared');
 const label=targetLabel||row.target?.displayName||(en?'No matching installed equipment':'未匹配安装设备');
 const time=alarm?new Intl.DateTimeFormat(en?'en-GB':'zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(alarm.sourceTime)):'—';
 return <button className={'pc-alarm-card pc-alarm-appearance'+(compact?' pc-alarm-card-compact':' pc-home-alarm-row')} data-state={state} data-severity={severity} disabled={disabled||!canLocate} title={displayText(`${row.dataset.title} · ${label} · ${time}`)} aria-label={displayText(`${row.dataset.faultCode} · ${row.dataset.title} · ${label}`)} aria-description={displayText(status)} onClick={()=>{if(!disabled&&canLocate&&row.target)onOpen(row.dataset,row.target);}}>
  <Icon className="pc-alarm-card-icon" size={18} aria-hidden="true"/><span className="pc-alarm-card-copy"><span className="pc-home-alarm-meta"><b>{row.dataset.faultCode}</b><span className="pc-home-alarm-badge">{displayText(status)}</span><small>+{second}s</small></span><strong>{displayText(row.dataset.title)}</strong><span className="pc-home-alarm-time"><span>{displayText(label)}</span></span></span>{canLocate&&<ArrowUpRight className="pc-alarm-card-arrow" size={14} aria-hidden="true"/>}
 </button>;
}
