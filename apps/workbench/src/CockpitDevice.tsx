import {useEffect,useState} from 'react';
import {ArrowLeft,ArrowRight,Box,FileText,Info,Network,SlidersHorizontal} from 'lucide-react';
import {ApiError,cancelled,failureMessage,type WorkbenchApi} from './api';
import {SceneApi} from './sceneApi';
import {EquipmentApi,type EquipmentRecord} from './equipmentApi';
import type {SceneObjectContext} from './sceneEngineeringTypes';
import type {AnalysisEntry} from './analysisSources';
import {EquipmentAttributeDetails} from './EquipmentAttributeDetails';
import {EquipmentMaterials} from './EquipmentMaterials';
import {Btn,Modal} from './Primitives';
import {PageDeck,CockpitModelPreview} from './CockpitPanels';
import type {ModelResourceRef} from './sceneTypes';

export function CockpitDevice({api,uid,en,representationUid,onSelect,onAnalyze,onChoose,model}:{api:WorkbenchApi;uid:string;en:boolean;representationUid?:string;onSelect:(uid:string)=>void;onAnalyze:(entry:AnalysisEntry)=>void;onChoose:()=>void;model?:ModelResourceRef|null}){
 const t=(zh:string,eng:string)=>en?eng:zh;
 const [value,setValue]=useState<{record:EquipmentRecord;context:SceneObjectContext}|null>(null),[error,setError]=useState<unknown>(null),[attempt,setAttempt]=useState(0),[detail,setDetail]=useState(''),[trail,setTrail]=useState<string[]>([]);
 useEffect(()=>{const abort=new AbortController();setValue(null);setError(null);setDetail('');
  void Promise.all([new EquipmentApi(api).resolve([uid],abort.signal),new SceneApi(api).objectContext(uid,undefined,abort.signal)]).then(([records,context])=>{
   const record=records.items.find(row=>row.item.entityUid===uid);
   if(!record||record.item.entityRevision!==context.item.entityRevision)throw new ApiError(409,'ENGINEERING_CHANGED');
   if(!abort.signal.aborted)setValue({record,context});
  }).catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setError(e);});return()=>abort.abort();
 },[api,api.epoch,api.revision,uid,attempt]);
 if(error)return <section className="pc-panel pc-device-card" role="alert">{failureMessage(error,en?'en':'zh')} <Btn onClick={()=>setAttempt(v=>v+1)}>{t('重试','Retry')}</Btn><button onClick={onChoose}>{t('切换设备','Choose equipment')}</button></section>;
 if(!value)return <section className="pc-panel pc-device-card" role="status">{t('正在读取设备…','Reading equipment…')}</section>;
 const {record,context}=value,selection={entityUid:uid,expectedEntityRevision:context.item.entityRevision,installationContextId:context.context?.installationContextId||null,expectedHierarchyRevision:context.context?.hierarchyRevision||null};
 const children=record.children.filter((row,i,all)=>row.entityUid!==uid&&all.findIndex(x=>x.entityUid===row.entityUid)===i);
 return <><section className="pc-panel pc-device-tree"><header><Network size={20}/><h2>{t('设备结构','Equipment structure')}</h2><button onClick={onChoose} className="pc-text-action">{t('切换','Change')}</button></header>
 <div className="pc-tree-location"><button aria-label={t('返回上级','Parent level')} disabled={!trail.length} onClick={()=>{onSelect(trail[trail.length-1]);setTrail(v=>v.slice(0,-1));}}><ArrowLeft size={16}/></button><strong title={record.item.displayName}>{record.item.displayName}</strong></div>
 {children.length?<PageDeck key={uid} en={en} label={t('当前层级','Current level')} items={children} rowHeight={68} render={item=><button className="pc-branch" key={item.entityUid} onClick={()=>{setTrail(v=>[...v,uid]);onSelect(item.entityUid);}}><Box size={18}/><span>{item.displayName}</span><ArrowRight size={14}/></button>}/>:<div className="pc-tree-empty"><Box size={26}/><span>{t('当前对象无下级设备','No child equipment')}</span></div>}
 <button className="pc-quality-link" onClick={()=>setDetail('info')}><Info size={13}/>{uid!==representationUid?t('所属设备示意','Containing equipment view'):t('模型示意','Model representation')}</button></section>
 <section className="pc-panel pc-device-card"><header><div><small>{record.context.purpose==='demonstration'?t('演示安装','Demonstration'):t('安装设备','Installed equipment')}</small><h2 title={record.item.displayName}>{record.item.displayName}</h2></div><button aria-label={t('设备身份与精度','Identity and accuracy')} onClick={()=>setDetail('info')}><Info size={17}/></button></header>
 <div className="pc-device-emblem">{model?<CockpitModelPreview api={api} reference={model} name={t('所属设备模型','Containing equipment model')}/>:<Box size={64} strokeWidth={.8}/>}<span>{record.model?.name||t('工程对象','Engineering object')}</span></div>
 <button className="pc-material-action" onClick={()=>setDetail('materials')}><FileText size={20}/><span>{t('图纸与资料','Drawings & materials')}</span><ArrowRight size={15}/></button>
 <button className="pc-material-action" onClick={()=>setDetail('attributes')}><SlidersHorizontal size={20}/><span>{t('设备参数','Equipment parameters')}</span><ArrowRight size={15}/></button>
 <button className="pc-material-action" onClick={()=>setDetail('info')}><Info size={20}/><span>{t('对象详情','Object details')}</span><ArrowRight size={15}/></button>
 <button className="pc-primary-action" onClick={()=>onAnalyze({entityUid:uid,expectedEntityRevision:record.item.entityRevision,timeTo:new Date().toISOString()})}><Network size={18}/>{t('进入设备分析','Analyze equipment')}<ArrowRight size={16}/></button></section>
 {detail&&<Modal className="pc-detail-dialog" title={record.item.displayName} description={t('所选设备详情','Selected equipment details')} onClose={()=>setDetail('')}>
 {detail==='info'&&<div className="pc-detail-copy"><dl><dt>{t('型号','Model')}</dt><dd>{record.model?.name||'—'}</dd><dt>{t('身份','Identity')}</dt><dd>{uid}</dd><dt>{t('几何','Geometry')}</dt><dd>{t('源候选 / 示意表示；精度未核实','Source candidate / schematic; accuracy unverified')}</dd></dl>{uid!==representationUid&&<p>{t('空间视图显示所属设备；此部件尚无经核验的独立几何绑定。','The view shows the containing equipment; this child has no verified geometry binding.')}</p>}<p>{t('真实运行数据尚未接入，显示姿态不代表现场运行状态。','Live telemetry is not connected; displayed poses are not field operating states.')}</p></div>}
 {detail==='attributes'&&<EquipmentAttributeDetails api={api} uid={uid} en={en}/>}{detail==='materials'&&<EquipmentMaterials api={api} en={en} selection={selection}/>}
 </Modal>}</>;
}
