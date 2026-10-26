import {useEffect,useState} from 'react';
import {ClipboardList,Pause,Play,RefreshCw,Search} from 'lucide-react';
import {ApiError,cancelled,failureMessage,type WorkbenchApi} from './api';
import {Badge,Btn,IconBtn} from './Primitives';
import {RowActions,RowContext} from './ListMenus';
import {alarmAt,initialReplay,sampleAt,trendDomain,trendSegments,type SimulationCatalogue,type SimulationDetail} from './simulatedAlarms';
import './dataAlarms.css';

const ROOT='/api/workbench/analysis-sessions/simulation';
type DataApi=Pick<WorkbenchApi,'request'|'revision'|'epoch'>;
export function DataAlarms({api,locale='zh',onOpenWorkOrders}:{api:DataApi;locale?:string;onOpenWorkOrders:(faultCode:string)=>void}){
  const en=locale==='en',[catalogue,setCatalogue]=useState<SimulationCatalogue|null>(null),[detail,setDetail]=useState<SimulationDetail|null>(null);
  const [selected,setSelected]=useState(''),[query,setQuery]=useState(''),[metric,setMetric]=useState('sensor_temperature');
  const [second,setSecond]=useState(60),[playing,setPlaying]=useState(false),[refresh,setRefresh]=useState(0);
  const [loading,setLoading]=useState(true),[error,setError]=useState<unknown>(null),[unavailable,setUnavailable]=useState(false);
  const [reading,setReading]=useState(false);
  useEffect(()=>{
    const abort=new AbortController();setCatalogue(null);setDetail(null);setLoading(true);setError(null);setUnavailable(false);setPlaying(false);
    void api.request<SimulationCatalogue>(ROOT+'/catalogue',{includeDetail:true,...(selected?{datasetId:selected}:{})},abort.signal).then(value=>{
      if(!abort.signal.aborted){setCatalogue(value);setSelected(previous=>value.items.some(row=>row.datasetId===previous)?previous:value.items[0]?.datasetId||'');}
    }).catch(value=>{if(!abort.signal.aborted&&!cancelled(value)){
      if(value instanceof ApiError&&value.code==='SIMULATION_PROJECT_REQUIRED')setUnavailable(true);else setError(value);
    }}).finally(()=>{if(!abort.signal.aborted)setLoading(false);});
    return()=>abort.abort();
  },[api,api.revision,api.epoch,refresh]);
  const profile=catalogue?.items.find(row=>row.datasetId===selected);
  useEffect(()=>{
    const abort=new AbortController();setDetail(null);setError(null);setPlaying(false);setSecond(60);
    const initial=initialReplay(catalogue,profile);
    if(initial){setDetail(initial);setMetric(initial.trends[0]?.metricId||'');setReading(false);}
    else if(profile){setReading(true);void api.request<SimulationDetail>(ROOT+'/detail',{datasetId:profile.datasetId,datasetRevision:profile.datasetRevision},abort.signal)
      .then(value=>{if(!abort.signal.aborted){setDetail(value);setMetric(value.trends[0]?.metricId||'');}})
      .catch(value=>{if(!abort.signal.aborted&&!cancelled(value))setError(value);})
      .finally(()=>{if(!abort.signal.aborted)setReading(false);});}
    else setReading(false);
    return()=>abort.abort();
  },[api,api.revision,api.epoch,profile?.datasetId,profile?.datasetRevision,catalogue?.initialDetail]);
  const visible=detail&&detail.dataset.datasetId===profile?.datasetId&&detail.dataset.datasetRevision===profile.datasetRevision?detail:null;
  useEffect(()=>{
    if(!playing||!visible)return;
    const timer=window.setInterval(()=>setSecond(value=>Math.min(180,value+1)),1000);
    return()=>window.clearInterval(timer);
  },[playing,visible]);
  useEffect(()=>{if(second>=180)setPlaying(false);},[second]);
  const time=(value:string)=>new Intl.DateTimeFormat(en?'en-GB':'zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date(value));
  const date=(value:string)=>new Intl.DateTimeFormat(en?'en-CA':'zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));
  const names:Record<string,string>={sensor_temperature:en?'Sensor temperature':'传感器温度',reference_temperature:en?'Independent reference':'独立参照温度',device_feedback:en?'State feedback':'状态反馈',supply_voltage:en?'Supply voltage':'供电电压',overcurrent:en?'Overcurrent signal':'过流信号'};
  const states={pending:en?'Not occurred':'未发生',active:en?'Active':'报警中',cleared:en?'Cleared':'已恢复'};
  const trends=visible?.trends.filter(row=>row.metricId===metric||metric==='sensor_temperature'&&row.metricId==='reference_temperature')||[];
  const domain=trendDomain(trends),state=visible?alarmAt(visible,second):'pending';
  return <section className="da-workspace" aria-label={en?'Data and alarms':'数据与告警'}>
    <header className="da-toolbar"><strong>{en?'Fault alarms':'故障报警'}</strong><Badge tone="amber">{en?'Simulated replay':'模拟回放'}</Badge><span className="cw-grow"/><IconBtn label={en?'Reload alarms':'重新读取报警'} disabled={loading||reading} onClick={()=>setRefresh(value=>value+1)}><RefreshCw size={15}/></IconBtn></header>
    {!!error&&<p className="cw-notice" role="alert">{failureMessage(error,locale)} <Btn onClick={()=>setRefresh(value=>value+1)}>{en?'Retry':'重试'}</Btn></p>}
    {loading?<p className="cw-state" role="status">{en?'Loading alarms…':'正在读取报警…'}</p>:unavailable?<p className="cw-state">{en?'This project has no configured alarm source. The current simulated source belongs to Demo-PDS.':'该项目尚未配置报警来源；当前模拟源属于Demo-PDS。'}</p>:catalogue&&<div className="da-columns">
      <aside className="da-list"><label className="da-search"><Search size={14}/><input aria-label={en?'Search fault codes':'搜索故障码'} placeholder={en?'Code or alarm title':'故障码或报警名称'} value={query} maxLength={120} onChange={event=>setQuery(event.target.value)}/></label>
        <ul className="ov-list" aria-label={en?'Simulated faults':'模拟故障列表'}>{catalogue.items.filter(row=>`${row.faultCode} ${row.title}`.toLowerCase().includes(query.trim().toLowerCase())).map(row=>{
          const actions=[{id:'view',label:en?'View alarm':'查看报警',icon:<Search size={15}/>,onSelect:()=>setSelected(row.datasetId)},
            {id:'orders',label:en?'Related work orders':'相关工单',icon:<ClipboardList size={15}/>,onSelect:()=>onOpenWorkOrders(row.faultCode)}];
          return <RowContext key={row.datasetId} name={row.title} actions={actions}><li className={`ov-list-item ${selected===row.datasetId?'selected':''}`}><button type="button" className="ov-list-main" aria-pressed={selected===row.datasetId} onClick={()=>setSelected(row.datasetId)}><span className="ov-list-copy"><strong>{row.faultCode} · {row.title}</strong><small>{row.cabinet} · {en?'3-minute replay':'3分钟回放'}</small></span></button><RowActions name={row.title} actions={actions} locale={locale}/></li></RowContext>;
        })}</ul>{!catalogue.items.some(row=>`${row.faultCode} ${row.title}`.toLowerCase().includes(query.trim().toLowerCase()))&&<p className="cw-state">{en?'No matching faults':'没有匹配的故障'}</p>}</aside>
      <div className="da-detail">{reading?<p className="cw-state" role="status">{en?'Loading replay…':'正在读取回放…'}</p>:visible&&<>
        <div className="da-heading"><div><h2>{visible.dataset.title}</h2><p>{visible.dataset.faultCode} · {visible.dataset.primaryRds}</p></div><Badge tone={state==='active'?'amber':'neutral'}>{states[state]}</Badge><Btn onClick={()=>onOpenWorkOrders(visible.dataset.faultCode)}><ClipboardList size={14}/>{en?'Related work orders':'相关工单'}</Btn></div>
        <section className="da-card"><header><h3>{en?'Replay timeline':'回放时间轴'}</h3><span>{date(visible.dataset.timeFrom)} · UTC+8</span></header><div className="da-replay"><IconBtn label={playing?(en?'Pause replay':'暂停回放'):(en?'Play replay':'播放回放')} onClick={()=>{if(second>=180)setSecond(0);setPlaying(value=>!value);}}>{playing?<Pause size={15}/>:<Play size={15}/>}</IconBtn><input type="range" aria-label={en?'Replay position':'回放位置'} min="0" max="180" step="1" value={second} onChange={event=>{setPlaying(false);setSecond(Number(event.target.value));}}/><output>{time(new Date(Date.parse(visible.dataset.timeFrom)+second*1000).toISOString())}</output></div><p className="da-caption">{time(visible.dataset.timeFrom)} — {time(visible.dataset.timeTo)} · {en?'Alarm occurs at +30s and clears at +150s':'第30秒发生，第150秒恢复'}</p></section>
        <section className="da-card"><header><h3>{en?'Signal trends':'信号趋势'}</h3><select aria-label={en?'Signal':'查看信号'} value={metric} onChange={event=>setMetric(event.target.value)}>{visible.trends.filter(row=>row.metricId!=='reference_temperature').map(row=><option key={row.metricId} value={row.metricId}>{names[row.metricId]||row.metricId}</option>)}</select></header>
          <div className="da-values">{trends.map((row,index)=>{const sample=sampleAt(row,second);return <div key={row.metricId} data-series={index}><span>{names[row.metricId]||row.metricId}</span><strong className={sample?.quality==='good'?'':'da-missing'}>{sample?.quality==='good'&&sample.value!==null?`${sample?.value} ${row.unit==='degC'?'°C':row.unit==='1'?'':row.unit}`.trim():en?'Quality gap':'质量异常'}</strong></div>;})}</div>
          <svg className="da-chart" viewBox="0 0 720 225" role="img" aria-label={en?'Signal trends with an explicit quality gap':'信号趋势，质量异常处保留断点'}><line x1="40" y1="30" x2="40" y2="190"/><line x1="40" y1="190" x2="680" y2="190"/><text x="34" y="35" textAnchor="end">{domain[1].toFixed(1)}</text><text x="34" y="190" textAnchor="end">{domain[0].toFixed(1)}</text>{trends.flatMap((row,index)=>trendSegments(row,domain).map((points,part)=><polyline key={`${row.metricId}:${part}`} points={points} data-series={index}/>))}<line className="da-cursor" x1={40+second/180*640} x2={40+second/180*640} y1="25" y2="190"/><text x="40" y="215">{time(visible.dataset.timeFrom)}</text><text x="680" y="215" textAnchor="end">{time(visible.dataset.timeTo)}</text></svg><p className="da-caption">{en?'181 one-second samples. Quality is bad at +90s; the gap is not interpolated.':'181个1秒样本；第90秒质量异常，保留断点。'}</p>
        </section>
        <section className="da-card"><header><h3>{en?'Alarm lifecycle':'报警生命周期'}</h3></header><div className="da-table-scroll"><table className="ov-list-table"><thead><tr><th>{en?'Source time':'源时间'}</th><th>{en?'State':'状态'}</th><th>{en?'Severity':'严重性'}</th><th>{en?'Version':'版本'}</th></tr></thead><tbody>{visible.alarms.map(row=><tr key={row.sourceRevision}><td>{time(row.sourceTime)}</td><td>{states[row.state]}</td><td>{row.severity==='critical'?(en?'Critical':'严重'):(en?'Warning':'警告')}</td><td>{row.sourceRevision}</td></tr>)}</tbody></table></div></section>
        <details className="da-source"><summary>{en?'Test preset and source':'测试预设与来源'}</summary><p>{visible.dataset.presetCause}</p><p>{visible.dataset.retainedEvidenceGap}</p><p>{en?'Replay status does not acknowledge a source alarm or confirm a field cause.':'回放状态不代表源报警确认或现场根因结论。'}</p><p className="ov-mono">{visible.dataset.sourceConnectionId} · {visible.dataset.datasetId} · {visible.dataset.datasetRevision}</p></details>
      </>}</div>
    </div>}
  </section>;
}
