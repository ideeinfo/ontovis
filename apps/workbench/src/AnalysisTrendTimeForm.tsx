import {useId,useState} from 'react';
import {Clock3} from 'lucide-react';
import {Btn} from './Primitives';
import {timeWindowInput,timeWindowLabel,timeWindowValue,timeZoneLabel,type AnalysisTimeZone,type TimeWindow} from './analysisTimeWindow';
import './analysisTimeWindow.css';

export function AnalysisTimeWindowForm({initial,zone,currentCount,historicalCount,limits,busy=false,error='',unavailable=false,en=false,onApply,onCancel}:{
 initial:TimeWindow;zone:AnalysisTimeZone;currentCount:number;historicalCount:number;limits?:TimeWindow|null;busy?:boolean;error?:string;unavailable?:boolean;en?:boolean;
 onApply:(value:TimeWindow)=>void;onCancel:()=>void;
}){
 const id=useId(),t=(zh:string,eng:string)=>en?eng:zh;
 const [from,setFrom]=useState(()=>timeWindowInput(initial.from,zone)),[to,setTo]=useState(()=>timeWindowInput(initial.to,zone)),[edited,setEdited]=useState(false);
 const step=[initial.from,initial.to].some(value=>/\.\d*[1-9]/.test(value))?'0.001':'1';
 const checked=timeWindowValue(from,to,zone,limits),value=checked.value,changed=!!value&&(Date.parse(value.from)!==Date.parse(initial.from)||Date.parse(value.to)!==Date.parse(initial.to));
 const problem=checked.issue==='empty'?t('请填写完整的开始和结束时间。','Enter both start and end times.'):checked.issue==='invalid'?t('请输入有效的日期和时间。','Enter a valid date and time.'):checked.issue==='order'?t('结束时间须晚于开始时间。','End time must be after start time.'):checked.issue==='outside'?t('所选区间超出当前趋势的可用数据范围。','The selected interval exceeds the available trend data.'):'';
 return <form className="ac-time-window-form" noValidate onSubmit={event=>{event.preventDefault();setEdited(true);if(value&&changed&&!busy&&!unavailable&&currentCount>0)onApply(value);}}>
  <p className="ac-time-intro">{t('查看报警前后的测点变化，统一调整画布中的本次趋势。','Adjust current trends on this canvas to inspect measurements around the alarm.')}</p>
  <div className="ac-time-zone"><Clock3 size={15}/><span>{timeZoneLabel(zone,en)}</span></div>
  <div className="ac-time-fields">{([{key:'from',label:t('开始时间','Start time'),value:from,set:setFrom},{key:'to',label:t('结束时间','End time'),value:to,set:setTo}] as const).map(field=><label key={field.key} htmlFor={id+field.key}><span>{field.label}</span><input id={id+field.key} type="datetime-local" step={step} required disabled={busy} aria-describedby={id+'feedback'} aria-invalid={edited&&!!problem} value={field.value} onChange={event=>{field.set(event.target.value);setEdited(true);}}/></label>)}</div>
  {limits&&<p className="ac-time-available"><span>{t('数据可用区间','Available data')}</span><time>{timeWindowLabel(limits.from,zone)}</time><span>—</span><time>{timeWindowLabel(limits.to,zone)}</time></p>}
  <div className="ac-time-impact"><strong>{t(`更新 ${currentCount} 条本次趋势`,`Updates ${currentCount} current trend${currentCount===1?'':'s'}`)}</strong><span>{historicalCount?t(`${historicalCount} 条历史参考保留原时间。`,historicalCount===1?'1 historical trend keeps its original window.':`${historicalCount} historical trends keep their original windows.`):t('历史参考保留原时间。','Historical references keep their original windows.')}</span></div>
  <div id={id+'feedback'} className="ac-time-feedback" aria-live="polite">{(edited&&problem||error||unavailable||!currentCount)&&<p role="alert">{edited&&problem||error||(unavailable?t('请先展开本次趋势卡，读取可用数据后再调整。','Open current trend cards to read available data before adjusting the interval.'):t('加入本次趋势后可调整时间区间。','Add a current trend to adjust its interval.'))}</p>}</div>
  <footer><small>{t('应用后还需保存画布。','Save the canvas after applying.')}</small><div><Btn disabled={busy} onClick={onCancel}>{t('取消','Cancel')}</Btn><Btn type="submit" primary disabled={busy||unavailable||!currentCount||!value||!changed}>{busy?t('正在更新…','Updating…'):t('应用到画布','Apply to canvas')}</Btn></div></footer>
 </form>;
}
