import {useEffect,useMemo,useState} from 'react';
import {ApiError,cancelled,failureMessage,type WorkbenchApi} from './api';
import {EquipmentApi,type EquipmentAttributeForm} from './equipmentApi';
import {valueText} from './EquipmentApplication';
import {Btn} from './Primitives';
import {PageDeck} from './CockpitPanels';

export function EquipmentAttributeDetails({api,uid,en,modelContext,onReload}:{api:WorkbenchApi;uid:string;en:boolean;modelContext?:{expectedEntityRevision:string};onReload?:()=>void}){
 const service=useMemo(()=>new EquipmentApi(api),[api]);
 const [value,setValue]=useState<EquipmentAttributeForm|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState<unknown>(null),[attempt,setAttempt]=useState(0);
 const [tab,setTab]=useState(modelContext?'model':'device');
 useEffect(()=>{const abort=new AbortController();setValue(null);setBusy(true);setError(null);
  const request=modelContext?service.deviceParameters({entityUid:uid,expectedEntityRevision:modelContext.expectedEntityRevision},abort.signal):service.attributeForm(uid,abort.signal);
  void request.then(v=>{if(!abort.signal.aborted)setValue(v);}).catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setError(e);}).finally(()=>{if(!abort.signal.aborted)setBusy(false);});return()=>abort.abort();
 },[service,api.epoch,api.revision,uid,modelContext?.expectedEntityRevision,attempt]);
 const retry=()=>error instanceof ApiError&&error.status===409&&onReload?onReload():setAttempt(v=>v+1);
 const model=value?.modelAttributes,rows=tab==='model'?model?.fields||[]:value?.fields||[],values=tab==='model'?model?.values||[]:value?.values||[];
 const row=(field:EquipmentAttributeForm['fields'][number])=><div className="pc-parameter-row" key={field.propertyKey}><span>{en?field.definition.nameEn||field.definition.nameZh:field.definition.nameZh}</span><strong>{valueText(values.find(v=>v.propertyRevisionId===field.propertyRevisionId),en)}</strong><small>{field.definition.unit||'—'}</small></div>;
 return <section className={modelContext?'pc-device-parameters':undefined}>
 {modelContext?<div className="pc-parameter-tabs" role="tablist" aria-label={en?'Parameter scope':'参数范围'}>{[['model',en?'Model attributes':'型号属性'],['device',en?'Device attributes':'单台属性']].map(([id,label])=><button key={id} role="tab" aria-selected={tab===id} onClick={()=>setTab(id)}>{label}</button>)}</div>:<h4>{en?'Per-device attributes':'单台设备属性'}</h4>}
 {busy&&<p role="status">{en?'Loading parameters…':'正在读取参数…'}</p>}{!!error&&<p role="alert">{failureMessage(error,en?'en':'zh')} <Btn onClick={retry}>{en?'Read again':'重新读取'}</Btn></p>}
 {modelContext&&value?<div role="tabpanel" aria-label={tab==='model'?(en?'Model attributes':'型号属性'):(en?'Device attributes':'单台属性')}>
  {tab==='model'?model?.available&&model.model?<><header className="pc-parameter-model"><div><strong>{model.model.name}</strong><small>r{model.model.revision}{model.model.manufacturer?' · '+model.model.manufacturer:''}</small></div><span>{model.relation==='assembly'?(en?'Assembly model':'所属整机型号'):(en?'Device model':'本设备型号')}</span></header>{model.relation==='assembly'&&<p className="eq-caption">{model.equipmentName}</p>}</>:<p className="eq-message">{model?.reason==='MODEL_NOT_REGISTERED'?(en?'No model parameters are registered.':'尚未登记可读取的型号参数。'):(en?'Model parameters are temporarily unavailable.':'型号参数暂不可用。')}</p>:value.available?<p className="eq-caption">{value.scope?.name} · {value.scope?.source==='common'?(en?'Common equipment fields':'设备通用字段'):(en?'Device attribute context':'单台属性')}</p>:<p className="eq-message">{en?'No device attribute context is available.':'当前设备尚无可用的单台属性上下文。'}</p>}
  {rows.length>0?<div className="pc-parameter-list" style={{'--pc-parameter-height':Math.min(500,rows.length*48+42)+'px'} as import('react').CSSProperties}><PageDeck key={tab+':'+uid} items={rows} en={en} label={tab==='model'?(en?'Model parameter list':'型号参数清单'):(en?'Device parameter list':'单台参数清单')} rowHeight={48} render={row}/></div>:(tab==='model'?model?.available:value.available)&&<p className="eq-message">{en?'No parameter values are registered.':'暂无已登记的参数值。'}</p>}
 </div>:!modelContext&&<>
 {value?.available?<><p className="eq-caption">{value.scope?.name} · {value.scope?.source==='common'?(en?'Common equipment fields':'设备通用字段'):(en?'Source-selected context':'源端自动确定的上下文')}</p><div className="eq-parameter-grid">{value.fields.map(field=><div key={field.propertyKey}><span>{en?field.definition.nameEn||field.definition.nameZh:field.definition.nameZh}{field.inherited&&<small>{en?'Inherited':'继承'}</small>}</span><strong>{valueText(value.values.find(v=>v.propertyRevisionId===field.propertyRevisionId),en)}</strong><span>{field.definition.unit||'—'}</span></div>)}</div>{!value.fields.length&&<p>{en?'No attribute fields in this context.':'当前上下文暂无属性字段。'}</p>}</>:value&&<p>{en?'The source has not resolved an attribute context for this equipment.':'源端尚未为本设备确定可用的属性上下文。'} <small>{value.reason}</small></p>}
 </>}
 </section>;
}
