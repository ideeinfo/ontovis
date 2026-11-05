import {useCallback,useState} from 'react';
import {DataAlarms} from './DataAlarms';
import {WeatherSettings} from './WeatherSettings';
import {Btn,Modal} from './Primitives';
import type {WorkbenchApi} from './api';
import type {AnalysisEntry} from './analysisSources';
export function ProjectData({api,locale,active,onAnalyze,onOpenWorkOrders,onDirtyChange}:{api:WorkbenchApi;locale:'zh'|'en';active:boolean;onAnalyze:(entry:AnalysisEntry)=>void;onOpenWorkOrders:(code:string)=>void;onDirtyChange:(v:boolean)=>void}){
 const [tab,setTab]=useState('alarms'),[dirty,setDirty]=useState(false),[leave,setLeave]=useState(false),en=locale==='en';
 const changed=useCallback((value:boolean)=>{setDirty(value);onDirtyChange(value);},[onDirtyChange]);
 return <div className="wx-data"><div className="wx-tabs" role="group" aria-label={en?'Data views':'数据视图'}><Btn onClick={()=>{if(dirty)setLeave(true);else setTab('alarms');}} aria-pressed={tab==='alarms'}>{en?'Simulated alarms':'模拟报警'}</Btn><Btn onClick={()=>setTab('weather')} aria-pressed={tab==='weather'}>{en?'Weather API':'天气接口'}</Btn></div>{tab==='alarms'?<DataAlarms active={active} api={api} locale={locale} onAnalyze={onAnalyze} onOpenWorkOrders={onOpenWorkOrders}/>:<WeatherSettings api={api} en={en} active={active} onDirtyChange={changed}/>}{leave&&<Modal description={en?'Resolve unsaved settings before leaving.':'离开前处理未保存配置。'} title={en?'Unsaved settings':'配置尚未保存'} onClose={()=>setLeave(false)}><p>{en?'Leaving discards the current edits.':'离开将放弃当前修改。'}</p><Btn onClick={()=>setLeave(false)}>{en?'Keep editing':'继续编辑'}</Btn><Btn onClick={()=>{setLeave(false);setTab('alarms');setDirty(false);onDirtyChange(false);}}>{en?'Discard and leave':'放弃修改并离开'}</Btn></Modal>}</div>;
}
