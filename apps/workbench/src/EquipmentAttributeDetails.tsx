import {useEffect,useMemo,useState} from 'react';
import {cancelled,failureMessage,type WorkbenchApi} from './api';
import {EquipmentApi,type EquipmentAttributeForm} from './equipmentApi';
import {valueText} from './EquipmentApplication';
import {Btn} from './Primitives';

export function EquipmentAttributeDetails({api,uid,en}:{api:WorkbenchApi;uid:string;en:boolean}){
 const service=useMemo(()=>new EquipmentApi(api),[api]);
 const [value,setValue]=useState<EquipmentAttributeForm|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState<unknown>(null),[attempt,setAttempt]=useState(0);
 useEffect(()=>{const abort=new AbortController();setValue(null);setBusy(true);setError(null);
  void service.attributeForm(uid,abort.signal).then(v=>{if(!abort.signal.aborted)setValue(v);}).catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setError(e);}).finally(()=>{if(!abort.signal.aborted)setBusy(false);});return()=>abort.abort();
 },[service,api.epoch,api.revision,uid,attempt]);
 return <section><h4>{en?'Per-device attributes':'单台设备属性'}</h4>{busy&&<p role="status">{en?'Loading attribute context…':'正在读取单台属性上下文…'}</p>}{!!error&&<p role="alert">{failureMessage(error,en?'en':'zh')} <Btn onClick={()=>setAttempt(v=>v+1)}>{en?'Retry':'重试'}</Btn></p>}
 {value?.available?<><p className="eq-caption">{value.scope?.name} · {value.scope?.source==='common'?(en?'Common equipment fields':'设备通用字段'):(en?'Source-selected context':'源端自动确定的上下文')}</p><div className="eq-parameter-grid">{value.fields.map(field=><div key={field.propertyKey}><span>{en?field.definition.nameEn||field.definition.nameZh:field.definition.nameZh}{field.inherited&&<small>{en?'Inherited':'继承'}</small>}</span><strong>{valueText(value.values.find(v=>v.propertyRevisionId===field.propertyRevisionId),en)}</strong><span>{field.definition.unit||'—'}</span></div>)}</div>{!value.fields.length&&<p>{en?'No attribute fields in this context.':'当前上下文暂无属性字段。'}</p>}</>:value&&<p>{en?'The source has not resolved an attribute context for this equipment.':'源端尚未为本设备确定可用的属性上下文。'} <small>{value.reason}</small></p>}</section>;
}
