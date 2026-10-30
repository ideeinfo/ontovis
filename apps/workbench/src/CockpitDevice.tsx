import {useEffect,useState} from 'react';
import {ArrowLeft,ArrowRight,Box,FileText,Info,Network,SlidersHorizontal,Focus,ScanEye} from 'lucide-react';
import {ApiError,cancelled,failureMessage,type WorkbenchApi} from './api';
import {SceneApi} from './sceneApi';
import {EquipmentApi,type EquipmentRecord} from './equipmentApi';
import {cockpitParentPath} from './cockpitLocation';
import type {SceneLocation,SceneObjectContext} from './sceneEngineeringTypes';
import type {AnalysisEntry} from './analysisSources';
import {EquipmentAttributeDetails} from './EquipmentAttributeDetails';
import {EquipmentMaterials} from './EquipmentMaterials';
import {Btn,Modal} from './Primitives';
import {PageDeck,CockpitModelPreview} from './CockpitPanels';
import type {ModelResourceRef} from './sceneTypes';

export function CockpitDevice({api,uid,en,representationUid,onSelect,onAnalyze,onChoose,model,selectionToken,location,locating,previewing,locationError,isolated,onIsolate,onFocus}:{api:WorkbenchApi;uid:string;en:boolean;representationUid?:string;onSelect:(uid:string)=>void;onAnalyze:(entry:AnalysisEntry)=>void;onChoose:()=>void;model?:ModelResourceRef|null;selectionToken:number;location:SceneLocation|null;locating:boolean;previewing:boolean;locationError:unknown;isolated:boolean;onIsolate:()=>void;onFocus:()=>void}){
 const t=(zh:string,eng:string)=>en?eng:zh;
 const [value,setValue]=useState<{record:EquipmentRecord;context:SceneObjectContext}|null>(null),[error,setError]=useState<unknown>(null),[attempt,setAttempt]=useState(0),[detail,setDetail]=useState(''),[path,setPath]=useState<string[]>([representationUid||uid]),[branch,setBranch]=useState<EquipmentRecord|null>(null),[branchError,setBranchError]=useState<unknown>(null);
 useEffect(()=>{const abort=new AbortController();setValue(null);setError(null);setDetail('');
  void Promise.all([new EquipmentApi(api).resolve([uid],abort.signal),new SceneApi(api).objectContext(uid,undefined,abort.signal)]).then(([records,context])=>{
   const record=records.items.find(row=>row.item.entityUid===uid);
   if(!record||record.item.entityRevision!==context.item.entityRevision)throw new ApiError(409,'ENGINEERING_CHANGED');
   if(!abort.signal.aborted)setValue({record,context});
  }).catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setError(e);});return()=>abort.abort();
 },[api,api.epoch,api.revision,uid,attempt]);
 const browseUid=path[path.length-1],rootUid=representationUid||uid;
 useEffect(()=>{const abort=new AbortController();setBranch(null);setBranchError(null);
  void new EquipmentApi(api).resolve([browseUid],abort.signal).then(result=>{const record=result.items.find(row=>row.item.entityUid===browseUid);if(!record)throw new ApiError(409,'ENGINEERING_CHANGED');if(!abort.signal.aborted)setBranch(record);}).catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setBranchError(e);});return()=>abort.abort();
 },[api,api.epoch,api.revision,browseUid,attempt]);
 useEffect(()=>{if(!value||value.record.item.entityUid!==uid||!branch||branch.item.entityUid!==browseUid||browseUid===uid||branch.children.some(item=>item.entityUid===uid))return;
  const parent=cockpitParentPath(value.context,rootUid);if(parent.length&&parent[parent.length-1]!==browseUid)setPath(parent);
 },[value,branch,browseUid,uid,rootUid]);
 const children=branch?.children.filter((row,i,all)=>row.entityUid!==browseUid&&all.findIndex(x=>x.entityUid===row.entityUid)===i)||[];
 const record=value?.record,context=value?.context,selection=context?{entityUid:uid,expectedEntityRevision:context.item.entityRevision,installationContextId:context.context?.installationContextId||null,expectedHierarchyRevision:context.context?.hierarchyRevision||null}:null;
 const located=location?.status==='located',precise=located&&location.mode==='direct';
 const status=locating?previewing?t('核对中','Verifying'):t('正在定位','Locating'):locationError?t('定位失败','Location failed'):located?precise?t('已定位','Located'):t('所属设备','Containing equipment'):t('暂无几何','No geometry');
 return <><section className="pc-panel pc-device-tree"><header><Network size={20}/><h2>{t('设备结构','Equipment structure')}</h2><button onClick={onChoose} className="pc-text-action">{t('切换','Change')}</button></header>
 <div className="pc-tree-location"><button aria-label={t('返回上级','Parent level')} disabled={path.length<2} onClick={()=>{const next=path.slice(0,-1);setPath(next);onSelect(next[next.length-1]);}}><ArrowLeft size={16}/></button><strong title={branch?.item.displayName}>{branch?.item.displayName||t('设备结构','Equipment structure')}</strong></div>
 {branchError?<div className="pc-tree-empty" role="alert">{failureMessage(branchError,en?'en':'zh')}<button onClick={()=>setAttempt(v=>v+1)}>{t('重试','Retry')}</button></div>:!branch?<div className="pc-tree-empty" role="status">{t('正在读取结构…','Reading structure…')}</div>:children.length?<PageDeck key={browseUid} en={en} label={t('当前层级','Current level')} items={children} minimumRows={5} selectionToken={selectionToken} selectedIndex={children.findIndex(item=>item.entityUid===uid)} rowHeight={68} render={item=><div className="pc-branch" key={item.entityUid} data-selected={item.entityUid===uid||undefined}><button className="pc-branch-select" aria-pressed={item.entityUid===uid} onClick={()=>onSelect(item.entityUid)} title={item.displayName}><Box size={17}/><span>{item.displayName}</span></button>{item.hasChildren&&<button className="pc-branch-drill" aria-label={t('进入','Open ')+item.displayName} onClick={()=>{setPath(v=>[...v,item.entityUid]);onSelect(item.entityUid);}}><ArrowRight size={14}/></button>}</div>}/>:<div className="pc-tree-empty"><Box size={26}/><span>{t('当前对象无下级设备','No child equipment')}</span></div>}
 <div className="pc-tree-tools"><span role="status" title={locationError?failureMessage(locationError,en?'en':'zh'):location?.hostObject?.displayName}>{status}</span><button aria-label={t('定位所选','Focus selection')} title={t('定位所选','Focus selection')} disabled={locating} onClick={onFocus}><Focus size={16}/></button><button aria-label={isolated?t('显示全部','Show all'):t('隔离所选','Isolate selection')} title={isolated?t('显示全部','Show all'):t('隔离所选','Isolate selection')} aria-pressed={isolated} disabled={!located&&!previewing} onClick={onIsolate}><ScanEye size={16}/><span>{isolated?t('显示全部','Show all'):t('隔离','Isolate')}</span></button></div></section>
 {error?<section className="pc-panel pc-device-card" role="alert">{failureMessage(error,en?'en':'zh')} <Btn onClick={()=>setAttempt(v=>v+1)}>{t('重试','Retry')}</Btn></section>:!record||!context?<section className="pc-panel pc-device-card" role="status">{t('正在读取设备…','Reading equipment…')}</section>:<>
 <section className="pc-panel pc-device-card"><header><div><small>{record.context.purpose==='demonstration'?t('演示安装','Demonstration'):t('安装设备','Installed equipment')}</small><h2 title={record.item.displayName}>{record.item.displayName}</h2></div><button aria-label={t('设备身份与精度','Identity and accuracy')} onClick={()=>setDetail('info')}><Info size={17}/></button></header>
 <div className="pc-device-emblem">{model?<CockpitModelPreview api={api} reference={model} name={t('所属设备模型','Containing equipment model')}/>:<Box size={64} strokeWidth={.8}/>}<span>{record.model?.name||t('工程对象','Engineering object')}</span></div>
 <button className="pc-material-action" onClick={()=>setDetail('materials')}><FileText size={20}/><span>{t('图纸与资料','Drawings & materials')}</span><ArrowRight size={15}/></button>
 <button className="pc-material-action" onClick={()=>setDetail('attributes')}><SlidersHorizontal size={20}/><span>{t('设备参数','Equipment parameters')}</span><ArrowRight size={15}/></button>
 <button className="pc-material-action" onClick={()=>setDetail('info')}><Info size={20}/><span>{t('对象详情','Object details')}</span><ArrowRight size={15}/></button>
 <button className="pc-primary-action" onClick={()=>onAnalyze({entityUid:uid,expectedEntityRevision:record.item.entityRevision,timeTo:new Date().toISOString()})}><Network size={18}/>{t('进入设备分析','Analyze equipment')}<ArrowRight size={16}/></button></section>
 {detail&&<Modal className="pc-detail-dialog" title={record.item.displayName} description={t('所选设备详情','Selected equipment details')} onClose={()=>setDetail('')}>
 {detail==='info'&&<div className="pc-detail-copy"><dl><dt>{t('型号','Model')}</dt><dd>{record.model?.name||'—'}</dd><dt>{t('身份','Identity')}</dt><dd>{uid}</dd><dt>{t('几何','Geometry')}</dt><dd>{t('源候选 / 示意表示；精度未核实','Source candidate / schematic; accuracy unverified')}</dd></dl>{uid!==representationUid&&!precise&&<p>{t('空间视图显示所属设备；此部件尚无经核验的独立几何绑定。','The view shows the containing equipment; this child has no verified geometry binding.')}</p>}<p>{t('真实运行数据尚未接入，显示姿态不代表现场运行状态。','Live telemetry is not connected; displayed poses are not field operating states.')}</p></div>}
 {detail==='attributes'&&<EquipmentAttributeDetails api={api} uid={uid} en={en}/>}{detail==='materials'&&<EquipmentMaterials api={api} en={en} selection={selection!}/>}
 </Modal>}</>}</>;
}
