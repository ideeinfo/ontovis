import {useEffect,useMemo,useRef,useState} from 'react';
import {Box,ChevronDown,ChevronRight,PanelLeftClose,PanelLeftOpen,Search} from 'lucide-react';
import * as Tabs from '@radix-ui/react-tabs';
import {ApiError,cancelled,failureMessage,type WorkbenchApi} from './api';
import {EquipmentApi,type EquipmentCatalogItem,type EquipmentRecord,type ApplicationBundle,type SourceAdoption} from './equipmentApi';
import type {EngineeringObject} from './types';
import type {SceneObjectContext} from './sceneEngineeringTypes';
import type {AnalysisEntry} from './analysisSources';
import {SceneApi} from './sceneApi';
import {Btn} from './Primitives';
import {EquipmentApplicationDetails} from './EquipmentApplication';
import {EquipmentPhotos} from './EquipmentPhotos';
import {EquipmentMaterials} from './EquipmentMaterials';
import {EquipmentAttributeDetails} from './EquipmentAttributeDetails';
import {SourceEvidence} from './SourceEvidence';
import {OntoBaseEquipmentLink} from './OntoBaseEquipmentLink';
import {EquipmentSimulation} from './EquipmentSimulation.tsx';

function DeviceTreeNode({api,item,selected,onSelect,en,context,depth=0}:{api:WorkbenchApi;item:EngineeringObject;selected:string;onSelect:(uid:string)=>void;en:boolean;context?:SceneObjectContext;depth?:number}){
  const [expanded,setExpanded]=useState(false),[rows,setRows]=useState<EngineeringObject[]>([]),[cursor,setCursor]=useState<string|null>(null),[next,setNext]=useState<string|null>(null),[known,setKnown]=useState<SceneObjectContext|undefined>(context),[busy,setBusy]=useState(false),[error,setError]=useState<unknown>(null);
  useEffect(()=>{if(!expanded)return;const abort=new AbortController();setBusy(true);setError(null);const scene=new SceneApi(api);
    void (async()=>{const selection=known??await scene.objectContext(item.entityUid,undefined,abort.signal);if(!selection.context)return;
      const value=await scene.objectChildren({entityUid:item.entityUid,installationContextId:selection.context.installationContextId,expectedHierarchyRevision:selection.context.hierarchyRevision,cursor},abort.signal);
      if(!abort.signal.aborted){setKnown(selection);setRows(previous=>cursor?[...previous,...value.items.map(row=>row.object)]:value.items.map(row=>row.object));setNext(value.nextCursor);}
    })().catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setError(e);}).finally(()=>{if(!abort.signal.aborted)setBusy(false);});return()=>abort.abort();
  },[api,api.epoch,api.revision,item.entityUid,expanded,cursor]);
  return <li><div className="eq-tree-row" style={{paddingInlineStart:8+depth*16}}><button className="eq-tree-toggle" aria-label={`${expanded?(en?'Collapse':'收起'):(en?'Expand':'展开')} ${item.displayName}`} aria-expanded={expanded} disabled={!item.hasChildren} onClick={()=>setExpanded(value=>!value)}>{item.hasChildren?(expanded?<ChevronDown size={14}/>:<ChevronRight size={14}/>):null}</button><button aria-pressed={selected===item.entityUid} onClick={()=>onSelect(item.entityUid)} draggable={depth===0} onDragStart={event=>{event.dataTransfer.setData('application/x-ontovis-equipment',JSON.stringify({entityUid:item.entityUid}));event.dataTransfer.effectAllowed='copy';}}><Box size={14}/><span>{item.displayName}{'sceneUseCount' in item&&<small>{item.sceneUseCount?(en?'Placed':'已布置'):(en?'Not placed':'未布置')}</small>}</span></button></div>
    {expanded&&<ul>{rows.map(child=><DeviceTreeNode key={child.entityUid} api={api} item={child} selected={selected} onSelect={onSelect} en={en} context={known} depth={depth+1}/>)}{busy&&<li role="status">{en?'Loading…':'正在读取…'}</li>}{!!error&&<li role="alert">{failureMessage(error,en?'en':'zh')}</li>}{next&&!busy&&<li><Btn onClick={()=>setCursor(next)}>{en?'Load more':'加载更多'}</Btn></li>}</ul>}</li>;
}

export function EquipmentDevices({api,en,onAnalyze,onBinding,onOpenScene,active=true}:{api:WorkbenchApi;en:boolean;onAnalyze?:(entry:AnalysisEntry)=>void;onBinding:(device:SceneObjectContext,adoption:SourceAdoption|null)=>void;onOpenScene?:()=>void;active?:boolean}){
  const service=useMemo(()=>new EquipmentApi(api),[api]),scene=useMemo(()=>new SceneApi(api),[api]);
  const [items,setItems]=useState<EquipmentCatalogItem[]>([]),[query,setQuery]=useState(''),[settled,setSettled]=useState(''),[cursor,setCursor]=useState<string|null>(null),[next,setNext]=useState<string|null>(null),[tree,setTree]=useState(true),[listBusy,setListBusy]=useState(false);
  const [uid,setUid]=useState(''),[device,setDevice]=useState<SceneObjectContext|null>(null),[record,setRecord]=useState<EquipmentRecord|null>(null),[bundle,setBundle]=useState<ApplicationBundle|null>(null),[tab,setTab]=useState('overview'),[materialTab,setMaterialTab]=useState('current'),[busy,setBusy]=useState(false),[error,setError]=useState<unknown>(null),[listError,setListError]=useState<unknown>(null);
  const cache=useRef(new Map<string,ApplicationBundle>());
  const selection=useRef(uid),locateAbort=useRef<AbortController|null>(null);selection.current=uid;
  useEffect(()=>()=>locateAbort.current?.abort(),[uid,tab,active,api.epoch,api.revision]);
  async function locateSimulation(targetUid:string,revision:string){
    locateAbort.current?.abort();const abort=new AbortController();locateAbort.current=abort;
    setBusy(true);setError(null);const epoch=api.epoch,selectedUid=uid;
    try{const [selected,resolved]=await Promise.all([scene.objectContext(targetUid,revision,abort.signal),service.resolve([targetUid],abort.signal)]);
      if(abort.signal.aborted||api.epoch!==epoch||selectedUid!==selection.current)return;
      if(selected.context?.installationContextId!==record?.context.installationContextId
        ||selected.context?.hierarchyRevision!==record?.context.hierarchyRevision
        ||resolved.items[0].adoption?.applicationRevisionId!==record?.adoption?.applicationRevisionId)throw new ApiError(409,'ENGINEERING_CHANGED');
      onBinding(selected,resolved.items[0].adoption);
    }catch(e){if(!abort.signal.aborted&&!cancelled(e))setError(e);}finally{if(!abort.signal.aborted&&selectedUid===selection.current)setBusy(false);}
  }
  useEffect(()=>{cache.current.clear();setUid('');},[api,api.epoch,api.revision]);
  useEffect(()=>{const timer=setTimeout(()=>{setSettled(query.trim());setCursor(null);},250);return()=>clearTimeout(timer);},[query]);
  useEffect(()=>{const abort=new AbortController();setListBusy(true);setListError(null);if(!cursor)setItems([]);
    service.catalogue(settled,cursor,abort.signal).then(value=>{if(!abort.signal.aborted){setItems(rows=>cursor?[...rows,...value.items]:value.items);setNext(value.nextCursor);}}).catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setListError(e);}).finally(()=>{if(!abort.signal.aborted)setListBusy(false);});return()=>abort.abort();
  },[service,api.epoch,api.revision,settled,cursor]);
  useEffect(()=>{const abort=new AbortController();setDevice(null);setRecord(null);setBundle(null);setError(null);if(!uid)return;setBusy(true);
    Promise.all([service.resolve([uid],abort.signal),scene.objectContext(uid,undefined,abort.signal)]).then(async([resolved,selected])=>{
      if(abort.signal.aborted)return;const row=resolved.items[0];setDevice(selected);setRecord(row);
      if(row.adoption){const id=row.adoption.applicationRevisionId;let fixed=cache.current.get(id);if(!fixed){fixed=await service.application(id,abort.signal);if(cache.current.size>=8)cache.current.delete(cache.current.keys().next().value!);cache.current.set(id,fixed);}if(!abort.signal.aborted)setBundle(fixed);}
    }).catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setError(e);}).finally(()=>{if(!abort.signal.aborted)setBusy(false);});return()=>abort.abort();
  },[service,scene,api.epoch,api.revision,uid]);
  return <><div className="eq-device-toolbar"><label className="eq-search"><Search size={14}/><input aria-label={en?'Search equipment':'搜索项目设备'} placeholder={en?'Equipment name or identifier':'设备名称或标识'} value={query} onChange={event=>setQuery(event.target.value)}/></label><span className="eq-caption">{items.length}{next?'+':''} {en?'loaded':'台已读取'}</span><Btn onClick={()=>setTree(value=>!value)}>{tree?<PanelLeftClose size={14}/>:<PanelLeftOpen size={14}/>} {tree?(en?'Hide tree':'隐藏设备树'):(en?'Show tree':'显示设备树')}</Btn><OntoBaseEquipmentLink en={en}/></div>
  <div className={`eq-device-workspace ${tree?'':'eq-tree-hidden'}`}><aside className="eq-device-list" hidden={!tree}><header><strong>{en?'Project equipment':'项目设备'}</strong></header><ul className="eq-device-tree">{[...items].sort((a,b)=>a.displayName.localeCompare(b.displayName,en?'en':'zh',{numeric:true})).map(item=><DeviceTreeNode key={item.entityUid} api={api} item={item} selected={uid} onSelect={setUid} en={en}/>)}</ul>{listBusy&&<p role="status">{en?'Loading…':'正在读取…'}</p>}{!!listError&&<p role="alert">{failureMessage(listError,en?'en':'zh')}</p>}{next&&!listBusy&&<Btn onClick={()=>setCursor(next)}>{en?'Load more':'加载更多'}</Btn>}</aside>
  <main className="eq-device-detail">{device&&record?<><header><div><p className="eq-caption">{[device.root?.displayName,...device.ancestors.path.map(value=>value.object.displayName)].filter((v,i,a)=>v&&a.indexOf(v)===i).join(' / ')}</p><h3>{device.item.displayName}</h3><p className="eq-caption">{record.adoption?.name||(en?'No source application linked':'尚未接续源端项目采用')}</p></div><div className="eq-actions">{onAnalyze&&<Btn onClick={()=>onAnalyze({entityUid:device.item.entityUid,expectedEntityRevision:device.item.entityRevision,timeTo:new Date().toISOString()})}>{en?'Analyze':'进入分析'}</Btn>}{onOpenScene&&<Btn onClick={onOpenScene}>{en?'Open scene':'打开场景'}</Btn>}</div></header>
    <Tabs.Root value={tab} onValueChange={setTab}><Tabs.List className="eq-tabs" aria-label={en?'Equipment details':'设备详情'}>{[['overview',en?'Overview':'概览'],['shared',en?'Shared materials':'共享工程资料'],['field',en?'Field photos':'现场照片'],['monitoring',en?'Simulated monitoring':'模拟监测'],['binding',en?'Component binding':'构件定位']].map(([value,label])=><Tabs.Trigger key={value} value={value}>{label}</Tabs.Trigger>)}</Tabs.List>
      <Tabs.Content value="overview">{bundle&&record.adoption?.roleKey===null&&record.model?.revisionId===bundle.specification.revisionId?<EquipmentApplicationDetails value={bundle} en={en} api={api}/>:<dl className="eq-metadata"><dt>{en?'Equipment model':'本设备型号'}</dt><dd>{record.model?record.model.name+' / r'+record.model.revision:(en?'No model registered for this equipment':'尚未登记本设备自身型号')}</dd>{record.model&&<><dt>{en?'Model classification':'型号分类'}</dt><dd>{record.model.classificationRef.code}</dd></>}<dt>{en?'Assembly project application':'整机项目采用'}</dt><dd>{record.adoption?.name||'—'}</dd></dl>}<dl className="eq-metadata"><dt>{en?'Equipment UID':'设备 UID'}</dt><dd>{device.item.entityUid}</dd><dt>{en?'Purpose':'用途'}</dt><dd>{device.context?.purpose==='demonstration'?(en?'Demonstration':'演示设备'):(en?'Engineering':'工程设备')}</dd><dt>{en?'Source definition':'共享定义'}</dt><dd>{device.item.sourceTemplateEntityUid||'—'}</dd></dl><EquipmentAttributeDetails key={uid} api={api} uid={uid} en={en}/></Tabs.Content>
      <Tabs.Content value="shared"><Tabs.Root value={materialTab} onValueChange={setMaterialTab}><Tabs.List className="eq-tabs" aria-label={en?'Shared materials':'共享资料'}><Tabs.Trigger value="current">{en?'Applicable materials':'适用资料'}</Tabs.Trigger><Tabs.Trigger value="photos">{en?'Object location photos':'对象定位照片'}</Tabs.Trigger><Tabs.Trigger value="drawings">{en?'Drawings and evidence':'工程图纸与资料'}</Tabs.Trigger></Tabs.List><Tabs.Content value="current"><EquipmentMaterials key={uid} api={api} en={en} selection={{entityUid:record.item.entityUid,expectedEntityRevision:record.item.entityRevision,installationContextId:record.context.installationContextId,expectedHierarchyRevision:record.context.hierarchyRevision}}/></Tabs.Content><Tabs.Content value="photos"><EquipmentPhotos key={uid} api={api} definition={null} device={device} en={en}/></Tabs.Content><Tabs.Content value="drawings"><SourceEvidence api={api} object={device.item} context={device.context} host="—" endpointPrefix="/api/workbench/objects/evidence"/></Tabs.Content></Tabs.Root></Tabs.Content>
      <Tabs.Content value="field"><EquipmentPhotos key={uid} api={api} definition={null} device={device} en={en} purpose="field_record"/></Tabs.Content>
      <Tabs.Content value="monitoring">{active&&<EquipmentSimulation key={uid} api={api} record={record} context={device} bundle={bundle} en={en} onLocate={(targetUid,revision)=>void locateSimulation(targetUid,revision)}/>}</Tabs.Content>
      <Tabs.Content value="binding"><p className="eq-caption">{en?'Components use the shared mapping for this fixed project application. Objects without geometry retain their cabinet or assembly context.':'构件使用本次项目采用的共享映射。没有直接几何的对象保留所属柜体或总成定位关系。'}</p><Btn onClick={()=>onBinding(device,record.adoption)}>{en?'Open component binding':'查看构件绑定'}</Btn></Tabs.Content>
    </Tabs.Root></>:!busy&&<p className="eq-caption">{en?'Select equipment from the tree.':'从左侧设备树选择设备。'}</p>}{busy&&<p role="status">{en?'Loading equipment details…':'正在读取设备详情…'}</p>}{!!error&&<p role="alert">{failureMessage(error,en?'en':'zh')}</p>}</main></div></>;
}
