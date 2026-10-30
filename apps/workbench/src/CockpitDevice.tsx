import {useEffect,useState} from 'react';
import {ApiError,cancelled,failureMessage,type WorkbenchApi} from './api';
import {SceneApi} from './sceneApi';
import {EquipmentApi,type EquipmentRecord} from './equipmentApi';
import type {SceneObjectContext} from './sceneEngineeringTypes';
import type {AnalysisEntry} from './analysisSources';
import {EquipmentAttributeDetails} from './EquipmentAttributeDetails';
import {EquipmentMaterials} from './EquipmentMaterials';
import {Btn} from './Primitives';

export function CockpitDevice({api,uid,en,representationUid,onSelect,onAnalyze}:{api:WorkbenchApi;uid:string;en:boolean;representationUid?:string;onSelect:(uid:string)=>void;onAnalyze:(entry:AnalysisEntry)=>void}){
 const [value,setValue]=useState<{record:EquipmentRecord;context:SceneObjectContext}|null>(null),[error,setError]=useState<unknown>(null),[attempt,setAttempt]=useState(0),[tab,setTab]=useState('info');
 useEffect(()=>{const abort=new AbortController();setValue(null);setError(null);
  void Promise.all([new EquipmentApi(api).resolve([uid],abort.signal),new SceneApi(api).objectContext(uid,undefined,abort.signal)]).then(([records,context])=>{
   const record=records.items.find(row=>row.item.entityUid===uid);
   if(!record||record.item.entityRevision!==context.item.entityRevision)throw new ApiError(409,'ENGINEERING_CHANGED');
   if(!abort.signal.aborted)setValue({record,context});
  }).catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setError(e);});return()=>abort.abort();
 },[api,api.epoch,api.revision,uid,attempt]);
 if(error)return <p role="alert">{failureMessage(error,en?'en':'zh')} <Btn onClick={()=>setAttempt(v=>v+1)}>{en?'Retry':'重试'}</Btn></p>;
 if(!value)return <p role="status">{en?'Reading equipment…':'正在读取设备…'}</p>;
 const {record,context}=value,selection={entityUid:uid,expectedEntityRevision:context.item.entityRevision,installationContextId:context.context?.installationContextId||null,expectedHierarchyRevision:context.context?.hierarchyRevision||null};
 return <><header className="pc-device-title"><span>{en?'Installed equipment':'安装设备'}</span><h2>{record.item.displayName}</h2><small>{record.context.purpose==='demonstration'?(en?'Demonstration installation':'演示安装'):(en?'Engineering installation':'工程安装')}</small></header>
  <div className="pc-tabs" role="group" aria-label={en?'Device details':'设备详情'}>{[['info',en?'Details':'信息'],['attributes',en?'Parameters':'参数'],['materials',en?'Materials':'资料']].map(([id,label])=><button key={id} aria-pressed={tab===id} onClick={()=>setTab(id)}>{label}</button>)}</div>
  {tab==='info'&&<>{uid!==representationUid&&<p className="pc-muted">{en?'The spatial view shows the containing equipment; this child has no verified geometry binding.':'空间视图仍显示所属设备；此部件尚无经核验的独立几何绑定。'}</p>}<dl><dt>{en?'Model':'型号'}</dt><dd>{record.model?.name||'—'}</dd><dt>{en?'Identity':'身份'}</dt><dd className="pc-uid">{uid}</dd><dt>{en?'Geometry':'几何'}</dt><dd>{en?'Source candidate / schematic; accuracy unverified':'源候选 / 示意表示；精度未核实'}</dd></dl><p className="pc-muted">{en?'Operating data is not connected. Static orientation does not indicate operating state.':'运行数据尚未接入，静态姿态不代表设备运行状态。'}</p>
   <h3>{en?'Equipment hierarchy':'设备层级'}</h3><ul className="pc-tree">{[record.item,...record.children].filter((row,i,all)=>all.findIndex(x=>x.entityUid===row.entityUid)===i).map(row=><li key={row.entityUid}><button aria-pressed={uid===row.entityUid} onClick={()=>onSelect(row.entityUid)}>{row.displayName}</button></li>)}</ul>
   <Btn onClick={()=>onAnalyze({entityUid:uid,expectedEntityRevision:record.item.entityRevision,timeTo:new Date().toISOString()})}>{en?'Prepare equipment analysis':'进入设备分析'}</Btn>
  </>}
  {tab==='attributes'&&<EquipmentAttributeDetails api={api} uid={uid} en={en}/>}
  {tab==='materials'&&<EquipmentMaterials api={api} en={en} selection={selection}/>}
 </>;
}
