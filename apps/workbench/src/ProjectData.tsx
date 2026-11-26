import {useCallback,useState} from 'react';
import {DataAlarms} from './DataAlarms';
import {WeatherSettings} from './WeatherSettings';
import {Btn,ConfirmationDialog} from './Primitives';
import type {WorkbenchApi} from './api';
import type {AnalysisEntry} from './analysisSources';
export function ProjectData({api,locale,active,onAnalyze,onOpenWorkOrders,onDirtyChange}:{api:WorkbenchApi;locale:'zh'|'en';active:boolean;onAnalyze:(entry:AnalysisEntry)=>void;onOpenWorkOrders:(code:string,alarm?:import('./workOrderWorkflow').OrderAlarm)=>void;onDirtyChange:(v:boolean)=>void}){
 const [tab,setTab]=useState('alarms'),[dirty,setDirty]=useState(false),[leave,setLeave]=useState(false),en=locale==='en';
 const changed=useCallback((value:boolean)=>{setDirty(value);onDirtyChange(value);},[onDirtyChange]);
 return <div className="wx-data">
  <div className="wx-tabs" role="group" aria-label={en?'Data views':'数据视图'}>
   <Btn onClick={()=>{if(dirty)setLeave(true);else setTab('alarms');}} aria-pressed={tab==='alarms'}>{en?'Alarm replay':'报警回放'}</Btn>
   <Btn onClick={()=>setTab('weather')} aria-pressed={tab==='weather'}>{en?'Weather API':'天气接口'}</Btn>
  </div>
  {tab==='alarms'?<DataAlarms active={active} api={api} locale={locale} onAnalyze={onAnalyze} onOpenWorkOrders={onOpenWorkOrders}/>:
   <WeatherSettings api={api} en={en} active={active} onDirtyChange={changed}/>}
  {leave&&<ConfirmationDialog title={en?'Unsaved weather settings':'天气配置尚未保存'}
   description={en?'Switching to alarm replay discards these edits.':'切换到报警回放会丢失当前修改。'}
   cancelLabel={en?'Keep editing':'继续编辑'} onClose={()=>setLeave(false)}>
   <Btn data-danger onClick={()=>{setLeave(false);setTab('alarms');setDirty(false);onDirtyChange(false);}}>
    {en?'Discard and switch':'放弃并切换'}
   </Btn>
  </ConfirmationDialog>}
 </div>;
}
