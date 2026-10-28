import {useEffect,useMemo,useState} from 'react';
import {cancelled,failureMessage,type WorkbenchApi} from './api';
import {EquipmentApi,type ApplicationBundle,type ApplicationSummary,type PropertyValue} from './equipmentApi';
import {Btn,Modal} from './Primitives';

function valueText(value:PropertyValue|undefined,en:boolean){
  if(value?.status==='not_applicable')return en?'Not applicable':'不适用';
  if(!value||value.status!=='known')return en?'Unknown':'未知';
  const raw=value.value;
  if(raw&&typeof raw==='object'&&'min' in raw&&'max' in raw)return `${raw.min} – ${raw.max}`;
  return typeof raw==='boolean'?(raw?(en?'Yes':'是'):(en?'No':'否')):String(raw??'');
}
export function EquipmentApplicationDetails({value,en}:{value:ApplicationBundle;en:boolean}){
  const {application:app,specification:spec,template}=value,snapshot=spec.snapshot;
  return <section className="eq-source-details"><dl className="eq-metadata">
    <dt>{en?'Specification':'设备规格'}</dt><dd>{snapshot.name} / r{spec.revision}</dd>
    <dt>{en?'Manufacturer':'制造商'}</dt><dd>{snapshot.manufacturer||(en?'Unknown':'未知')}</dd>
    <dt>{en?'Nature':'性质'}</dt><dd>{snapshot.nature==='teaching'?(en?'Teaching specification':'教学规格'):snapshot.nature==='manufacturer'?(en?'Manufacturer specification':'厂家型号'):(en?'Custom specification':'自定义规格')}</dd>
    <dt>{en?'Classification':'分类'}</dt><dd>{snapshot.classificationRef.code}</dd>
    <dt>{en?'Project application':'项目采用'}</dt><dd>{app.snapshot.name} / r{app.revision}</dd>
    <dt>{en?'Variant':'配置变体'}</dt><dd>{app.snapshot.variant}<small>{app.snapshot.variantBasis}</small></dd>
  </dl>
  {(app.revisionId!==app.headRevisionId||spec.revisionId!==spec.headRevisionId)&&<p className="eq-message">{en?'A newer source revision exists. This equipment keeps its fixed adopted revision.':'源端已有新修订；此设备仍保留已采用的固定版本。'}</p>}
  <h4>{en?'Specification parameters':'规格参数'}</h4><div className="eq-parameter-grid">{template.fields.map(field=>{const v=snapshot.values.find(row=>row.propertyRevisionId===field.propertyRevisionId);return <div key={field.propertyKey}><span>{en?field.definition.nameEn||field.definition.nameZh:field.definition.nameZh}{field.inherited&&<small>{en?'Inherited':'继承'}</small>}</span><strong>{valueText(v,en)}</strong><span>{field.definition.unit||'—'}</span></div>;})}</div>
  <details><summary>{en?'Roles and sources':'内部角色与来源'}</summary><dl className="eq-metadata">{snapshot.roles.map(role=><div className="eq-metadata-row" key={role.roleKey}><dt>{role.name}</dt><dd>{role.quantity} · {role.optional?(en?'Optional':'可选'):(en?'Required':'必需')}</dd></div>)}</dl>
    {snapshot.sources.map((source,index)=><p key={index}>{source.url&&/^https?:\/\//.test(source.url)?<a href={source.url} target="_blank" rel="noreferrer">{source.provider||source.url}</a>:source.provider||'—'}{source.note&&<small>{source.note}</small>}</p>)}</details>
  <p className="eq-caption">{en?'Edit specification, parameters, roles and equipment adoption in OntoBase.':'型号、参数、内部角色和单台设备采用由 OntoBase 管理。'}</p></section>;
}

export function EquipmentApplicationPicker({api,en,onClose,onSelect,continuing=false}:{api:WorkbenchApi;en:boolean;onClose:()=>void;onSelect:(value:ApplicationBundle)=>void;continuing?:boolean}){
  const service=useMemo(()=>new EquipmentApi(api),[api]);
  const [items,setItems]=useState<ApplicationSummary[]>([]),[offset,setOffset]=useState(0),[total,setTotal]=useState(0),[revision,setRevision]=useState('');
  const [bundle,setBundle]=useState<ApplicationBundle|null>(null),[error,setError]=useState<unknown>(null),[busy,setBusy]=useState(true);
  useEffect(()=>{const abort=new AbortController();setBusy(true);setError(null);
    service.applications(offset,abort.signal).then(page=>{if(!abort.signal.aborted){setItems(page.items);setTotal(page.total);setRevision('');setBundle(null);}})
      .catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setError(e);}).finally(()=>{if(!abort.signal.aborted)setBusy(false);});return()=>abort.abort();
  },[service,api.epoch,api.revision,offset]);
  useEffect(()=>{const abort=new AbortController();setBundle(null);if(!revision)return;setBusy(true);setError(null);
    service.application(revision,abort.signal).then(value=>{if(!abort.signal.aborted)setBundle(value);}).catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setError(e);}).finally(()=>{if(!abort.signal.aborted)setBusy(false);});return()=>abort.abort();
  },[service,api.epoch,api.revision,revision]);
  return <Modal className="eq-application-modal" title={continuing?(en?'Continue existing bindings':'接续已有构件绑定'):(en?'Choose project application':'选择项目采用')} description={en?'Read fixed specification and role mappings from OntoBase':'读取 OntoBase 固定规格与角色映射'} onClose={onClose}>
    <div className="eq-form"><label>{en?'OntoBase project application':'OntoBase 项目采用'}<select aria-label={en?'OntoBase project application':'OntoBase 项目采用'} value={revision} onChange={e=>setRevision(e.target.value)}><option value="">{en?'Select…':'请选择…'}</option>{items.map(item=><option key={item.revisionId} value={item.revisionId}>{item.name} · {item.variant} / r{item.revision}</option>)}</select></label>
    {total>50&&<div className="eq-actions"><Btn disabled={!offset||busy} onClick={()=>setOffset(v=>Math.max(0,v-50))}>{en?'Previous':'上一页'}</Btn><span>{offset+1}–{Math.min(offset+50,total)} / {total}</span><Btn disabled={offset+50>=total||busy} onClick={()=>setOffset(v=>v+50)}>{en?'Next':'下一页'}</Btn></div>}
    {busy&&<p role="status">{en?'Loading source…':'正在读取源端…'}</p>}{!!error&&<p role="alert">{failureMessage(error,en?'en':'zh')}</p>}
    {!busy&&!error&&!items.length&&<p>{en?'Create a specification and project application in OntoBase first.':'请先在 OntoBase 建立型号规格和项目采用。'}</p>}
    {bundle&&<EquipmentApplicationDetails value={bundle} en={en}/>}
    {continuing&&<p className="eq-caption">{en?'Original object identities and component mappings must match. Existing history remains readable.':'原对象 UID 和构件映射必须一致；已有绑定历史继续保留。'}</p>}
    <div className="eq-actions"><Btn onClick={onClose}>{en?'Cancel':'取消'}</Btn><Btn primary disabled={!bundle||busy} onClick={()=>bundle&&onSelect(bundle)}>{en?'Use this application':'使用此项目采用'}</Btn></div></div>
  </Modal>;
}
