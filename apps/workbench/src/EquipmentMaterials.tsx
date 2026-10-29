import {useEffect,useMemo,useState} from 'react';
import {FileText,Image,RefreshCw} from 'lucide-react';
import {cancelled,failureMessage,type WorkbenchApi} from './api';
import {EquipmentApi,type EquipmentMaterial,type EquipmentMaterialPage,type MaterialSelection} from './equipmentApi';
import {Btn} from './Primitives';
import {OntoBaseEquipmentLink} from './OntoBaseEquipmentLink';
import {FixedDocumentPreview} from './FixedDocumentPreview';
import './equipmentMaterials.css';

export function EquipmentMaterials({api,en,selection,specificationId}:{api:WorkbenchApi;en:boolean;selection?:MaterialSelection|null;specificationId?:string}){
 const service=useMemo(()=>new EquipmentApi(api),[api]);
 const [value,setValue]=useState<EquipmentMaterialPage|null>(null),[rows,setRows]=useState<EquipmentMaterial[]>([]),[cursor,setCursor]=useState<string|null>(null),[kind,setKind]=useState(''),[scope,setScope]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState<unknown>(null),[attempt,setAttempt]=useState(0),[chosen,setChosen]=useState<EquipmentMaterial|null>(null);
 const identity=JSON.stringify([selection,specificationId]);
 useEffect(()=>{setCursor(null);setRows([]);setValue(null);setChosen(null);},[identity,api.epoch,api.revision]);
 useEffect(()=>{const abort=new AbortController();setBusy(true);setError(null);if(!cursor)setRows([]);
  const request=specificationId?service.modelMaterials(specificationId,scope,kind,cursor,abort.signal):selection?service.deviceMaterials(selection,cursor,abort.signal):Promise.resolve(null);
  void request.then(page=>{if(abort.signal.aborted)return;if(!page){setValue(null);return;}
   setRows(previous=>cursor?[...previous,...page.items.filter(x=>!previous.some(y=>x.documentId===y.documentId&&x.contentVersionId===y.contentVersionId))]:page.items);setValue(page);
  }).catch(e=>{if(!abort.signal.aborted&&!cancelled(e)){setError(e);setValue(null);setRows([]);setChosen(null);}}).finally(()=>{if(!abort.signal.aborted)setBusy(false);});return()=>abort.abort();
 },[service,api.epoch,api.revision,identity,scope,kind,cursor,attempt]);
 const role=value?.roles.find(x=>x.value===value.role),label=role?.name||(value?.role==='root'?(en?'Whole device':'整机'):value?.role||'');
 return <section className="eq-materials" aria-label={specificationId?(en?'Model shared materials':'型号共享资料'):(en?'Applicable equipment materials':'设备适用资料')}>
  <header><div><h4>{specificationId?(en?'Project model material catalogue':'本项目型号共享目录'):(en?'Applicable equipment materials':'当前设备适用资料')}</h4>{value?.model&&<p className="eq-caption">{value.model.name} · {en?'Material revision':'共享资料修订'} r{value.revision}{label?' · '+label:''}</p>}</div><Btn disabled={busy} onClick={()=>{setCursor(null);setAttempt(v=>v+1);}}><RefreshCw size={14}/>{en?'Refresh':'刷新'}</Btn><OntoBaseEquipmentLink en={en}/></header>
  {specificationId&&<div className="eq-actions"><label>{en?'Scope':'适用范围'} <select aria-label={en?'Material scope':'资料适用范围'} value={scope} onChange={e=>{setCursor(null);setScope(e.target.value);}}><option value="">{en?'All scopes':'全部范围'}</option>{value?.roles.map(role=><option key={role.value} value={role.value}>{role.kind==='model'?(en?'Model common':'型号通用'):role.kind==='root'?(en?'Whole device':'整机'):role.name||role.value}</option>)}</select></label><label>{en?'Type':'类型'} <select aria-label={en?'Material kind':'资料类型'} value={kind} onChange={e=>{setCursor(null);setKind(e.target.value);}}><option value="">{en?'PDF and photos':'PDF与照片'}</option><option value="pdf">PDF</option><option value="photo">{en?'Photos':'照片'}</option></select></label>{value?.total!==undefined&&<small>{en?'Scope associations':'范围关联数'}：{value.total}</small>}</div>}
  {!!error&&<p role="alert">{failureMessage(error,en?'en':'zh')}</p>}
  <div className="eq-material-list">{rows.map(item=><article key={item.documentId+':'+item.contentVersionId}>{item.kind==='pdf'?<FileText size={20}/>:<Image size={20}/>}<div><strong>{item.title}</strong><small>{item.kind==='pdf'?'PDF':en?'Photo':'照片'} · v{item.versionNumber}{item.pageCount?' · '+item.pageCount+' '+(en?'pages':'页'):''}</small><small>{item.scopes.map(x=>value?.roles.find(r=>r.value===x)?.name||(x==='model'?(en?'Model common':'型号通用'):x==='root'?(en?'Whole device':'整机'):x)).join(' · ')}{item.origins.includes('legacy_application')?' · '+(en?'Fixed application material':'固定采用资料'):''}</small>{item.availability!=='available'&&<small>{item.availability==='field_record'?(en?'Device field record; not model shared':'单台现场资料，不作为型号共享资料'):(en?'Source unavailable':'来源暂不可用')}</small>}</div><Btn disabled={item.availability!=='available'} onClick={()=>setChosen(item)}>{en?'Preview':'预览'}</Btn></article>)}</div>
  {busy&&<p role="status">{en?'Loading materials…':'正在读取资料…'}</p>}
  {!busy&&!error&&!rows.length&&<p className="eq-message">{value?.model?(en?'No materials apply to this scope. Existing object photos and drawings remain available in their tabs.':'当前范围暂无适用资料。原对象定位照片和工程图纸仍可在相应页签查看。'):(en?'No reliable adopted model mapping. Existing materials remain available.':'当前设备尚无可靠的型号采用映射，原有资料仍可读取。')}</p>}
  {value?.nextCursor&&!busy&&<Btn onClick={()=>setCursor(value.nextCursor)}>{en?'More materials':'更多资料'}</Btn>}
  {chosen&&<FixedDocumentPreview api={api} item={chosen} en={en} onClose={()=>setChosen(null)}/>}
 </section>;
}
