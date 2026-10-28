import {lazy,Suspense,useEffect,useMemo,useState} from 'react';
import {Box,Boxes,Check,ChevronDown,Focus,Link2,Plus,Search,Trash2} from 'lucide-react';
import {cancelled,failureMessage,type WorkbenchApi} from './api';
import {EquipmentApi,type EquipmentConfiguration,type EquipmentConfigurations,type EquipmentConfigurationSnapshot,type EquipmentRecord,type EquipmentCatalogItem} from './equipmentApi';
import type {EngineeringObject} from './types';
import type {SceneObjectContext} from './sceneEngineeringTypes';
import type {ProjectModelVersion} from './resourceTypes';
import type {LocalSceneSnapshot} from './sceneTypes';
import type {AnalysisEntry} from './analysisSources';
import {SceneApi} from './sceneApi';
import {Btn,Modal} from './Primitives';
import {usePreferences} from './Preferences';
import {Catalog} from './ObjectsPanel';
import {ResourcePanel} from './ResourcePanel';
import {ModelComponentTree,ModelComponentProperties,ModelPreviewTools,useModelPreview} from './ModelPreviewInspector';
import {EquipmentPhotos} from './EquipmentPhotos';
import {SourceEvidence} from './SourceEvidence';
import {objectCategory} from './objectCatalog';
import './equipmentHierarchy.css';

const SceneViewport=lazy(()=>import('./SceneViewport').then(module=>({default:module.SceneViewport})));
const previewScene:LocalSceneSnapshot={displayName:'',coordinateFrame:{mode:'local_plane',frameRevision:'equipment-preview',origin:[0,0,0],unit:'m',axes:'X_EAST_Y_UP_Z_SOUTH'},
  terrain:null,instances:[],initialView:{eye:[300,200,300],target:[0,60,0]},defaults:{background:'plain',lighting:'neutral',terrainMaterial:'solid'}};
const ignore=()=>{};

function SharedCabinetObjects({api,parentUid,selectedUid,onSelect,en}:{api:WorkbenchApi;parentUid:string;selectedUid:string;onSelect:(uid:string)=>void;en:boolean}){
  const [items,setItems]=useState<EngineeringObject[]>([]),[cursor,setCursor]=useState<string|null>(null),[next,setNext]=useState<string|null>(null),[total,setTotal]=useState(0),[error,setError]=useState<unknown>(null);
  useEffect(()=>{setCursor(null);setItems([]);},[parentUid]);
  useEffect(()=>{const abort=new AbortController();setError(null);void new EquipmentApi(api).children(parentUid,cursor,abort.signal).then(value=>{if(!abort.signal.aborted){setItems(rows=>cursor?[...rows,...value.items.map(x=>x.object)]:value.items.map(x=>x.object));setNext(value.nextCursor);setTotal(value.total);}}).catch(error=>{if(!abort.signal.aborted&&!cancelled(error))setError(error);});return()=>abort.abort();},[api,api.epoch,api.revision,parentUid,cursor]);
  return <details open className="eq-shared-children"><summary>{en?'Cabinet engineering objects':'柜内共享工程对象'} ({total})</summary><div className="eq-device-children">{items.map(item=><button key={item.entityUid} aria-pressed={item.entityUid===selectedUid} onClick={()=>onSelect(item.entityUid)}><Box size={13}/>{item.displayName}</button>)}</div>{next&&<Btn onClick={()=>setCursor(next)}>{en?'Load more':'加载更多'}</Btn>}{!!error&&<p role="alert">{failureMessage(error,en?'en':'zh')}</p>}</details>;
}

export function EquipmentHierarchy({api,onAnalyze,onOpenScene,onDirtyChange}:{api:WorkbenchApi;onAnalyze?:(entry:AnalysisEntry)=>void;onOpenScene?:()=>void;onDirtyChange?:(dirty:boolean)=>void}){
  const {locale}=usePreferences(),en=locale==='en',t=(zh:string,english:string)=>en?english:zh;
  const service=useMemo(()=>new EquipmentApi(api),[api]);
  const [tab,setTab]=useState<'configuration'|'equipment'>('configuration'),[reload,setReload]=useState(0);
  const [data,setData]=useState<EquipmentConfigurations|null>(null),[equipment,setEquipment]=useState<EquipmentCatalogItem[]>([]),[next,setNext]=useState<string|null>(null);
  const [configurationId,setConfigurationId]=useState(''),[draft,setDraft]=useState<EquipmentConfigurationSnapshot|null>(null),[dirty,setDirty]=useState(false);
  const [versions,setVersions]=useState<ProjectModelVersion[]>([]),[versionId,setVersionId]=useState('');
  const [selectedUid,setSelectedUid]=useState(''),[definition,setDefinition]=useState<SceneObjectContext|null>(null),[extraObjects,setExtraObjects]=useState<EngineeringObject[]>([]);
  const [record,setRecord]=useState<EquipmentRecord|null>(null),[device,setDevice]=useState<SceneObjectContext|null>(null),[deviceUid,setDeviceUid]=useState('');
  const [error,setError]=useState<unknown>(null),[busy,setBusy]=useState(false),[notice,setNotice]=useState(''),[reading,setReading]=useState(true);
  const [picker,setPicker]=useState<'model'|'object'|'adoption'|'create'|null>(null),[query,setQuery]=useState(''),[settled,setSettled]=useState('');
  const [newName,setNewName]=useState(''),[newKind,setNewKind]=useState('equipment'),[adopt,setAdopt]=useState<string[]>([]),[keys,setKeys]=useState<string[]>([]);
  const configuration=data?.items.find(row=>row.configurationId===configurationId),model=versions.find(row=>row.modelVersionId===versionId)??null;
  const inspection=useModelPreview(model);
  const mapping=draft?.models.find(row=>row.modelVersionId===versionId)?.mappings??[];
  const objects=[...(data?.objects??[]),...extraObjects];
  const byUid=new Map(objects.map(item=>[item.entityUid,item]));
  const selected=byUid.get(selectedUid),canWrite=data?.capabilities.canWrite??false;
  const parentUid=definition?.item.objectKind==='cabinet'?definition.item.entityUid:definition?.item.definitionParentEntityUid??'';
  function chooseModelNode(nodeId:string|null,focus=true){inspection.choose(nodeId,focus);const node=inspection.structure?.nodes.find(row=>row.id===nodeId);if(node?.componentKeys.length)setKeys([...node.componentKeys]);}
  const editableInspection={...inspection,choose:chooseModelNode};
  useEffect(()=>{const timer=setTimeout(()=>setSettled(query.trim()),250);return()=>clearTimeout(timer);},[query]);
  useEffect(()=>{
    const abort=new AbortController();setReading(true);setError(null);
    void Promise.allSettled([service.configurations(abort.signal),service.catalogue('',null,abort.signal)]).then(results=>{
      if(abort.signal.aborted)return;
      const [configs,devices]=results;
      if(configs.status==='fulfilled'){
        setData(configs.value);setVersions(configs.value.models);
        setConfigurationId(previous=>configs.value.items.some(row=>row.configurationId===previous)?previous:configs.value.items[0]?.configurationId??'');
      }else if(!cancelled(configs.reason))setError(configs.reason);
      if(devices.status==='fulfilled'){setEquipment(devices.value.items);setNext(devices.value.nextCursor);}else if(!cancelled(devices.reason))setError(devices.reason);
      setReading(false);
    });return()=>abort.abort();
  },[service,api.epoch,api.revision,reload]);
  useEffect(()=>{
    if(!configuration)return;
    setDraft(structuredClone(configuration.snapshot));setVersionId(previous=>configuration.snapshot.models.some(m=>m.modelVersionId===previous)?previous:configuration.snapshot.models[0]?.modelVersionId??'');
    setDirty(false);setSelectedUid(previous=>configuration.snapshot.models.some(model=>model.mappings.some(mapping=>mapping.objectRef.entityUid===previous))||configuration.snapshot.rootDefinition?.objectRef.entityUid===previous?previous:configuration.snapshot.models[0]?.mappings[0]?.objectRef.entityUid??'');
  },[configuration?.configurationId,configuration?.configurationRevision]);
  useEffect(()=>{
    const abort=new AbortController();setDefinition(null);
    if(selectedUid)void new SceneApi(api).objectContext(selectedUid,undefined,abort.signal).then(row=>{if(!abort.signal.aborted){setDefinition(row);setExtraObjects(items=>[...items.filter(x=>x.entityUid!==row.item.entityUid),row.item]);}}).catch(error=>{if(!abort.signal.aborted&&!cancelled(error))setError(error);});
    setKeys(mapping.find(m=>m.objectRef.entityUid===selectedUid)?.componentKeys??[]);
    return()=>abort.abort();
  },[api,api.epoch,api.revision,selectedUid,configurationId,configuration?.configurationRevision,versionId]);
  useEffect(()=>{
    const abort=new AbortController();setRecord(null);setDevice(null);
    if(deviceUid)void Promise.all([service.resolve([deviceUid],abort.signal),new SceneApi(api).objectContext(deviceUid,undefined,abort.signal)])
      .then(([resolved,context])=>{if(abort.signal.aborted)return;setRecord(resolved.items[0]);setDevice(context);
        const source=context.item.sourceTemplateEntityUid;setSelectedUid(source??configuration?.snapshot.rootDefinition?.objectRef.entityUid??'');})
      .catch(error=>{if(!abort.signal.aborted&&!cancelled(error))setError(error);});
    return()=>abort.abort();
  },[api,api.epoch,api.revision,service,deviceUid]);
  useEffect(()=>{
    const focused=keys.length?keys:mapping.find(row=>row.objectRef.entityUid===parentUid)?.componentKeys??[];
    if(!inspection.structure||!focused.length)return;
    const node=inspection.structure.nodes.find(node=>focused.every(key=>node.componentKeys.includes(key)))??inspection.structure.nodes.find(node=>node.componentKeys.some(key=>focused.includes(key)));
    if(node)inspection.choose(node.id);
  },[inspection.structure,keys.join('|'),parentUid]);
  useEffect(()=>{onDirtyChange?.(dirty);},[dirty,onDirtyChange]);
  useEffect(()=>()=>onDirtyChange?.(false),[onDirtyChange]);
  const change=(value:EquipmentConfigurationSnapshot)=>{setDraft(value);setDirty(true);setNotice('');};
  function chooseModel(value:ProjectModelVersion|null){
    if(!value)return;
    setVersions(rows=>[...rows.filter(row=>row.modelVersionId!==value.modelVersionId),value]);setVersionId(value.modelVersionId);setPicker(null);
    if(draft&&!draft.models.some(row=>row.modelVersionId===value.modelVersionId))change({...draft,models:[...draft.models,{modelVersionId:value.modelVersionId,mappings:[]}]});
  }
  function updateMapping(remove=false){
    if(!draft||!definition||!model)return;
    const others=mapping.filter(row=>row.objectRef.entityUid!==selectedUid);
    if(!remove&&others.some(row=>row.componentKeys.some(key=>keys.includes(key)))){setError(new Error(t('所选构件已有其他工程对象映射','A component is already mapped')));return;}
    const rows=remove?others:[...others,{objectRef:definition.objectRef,expectedEntityRevision:definition.item.entityRevision,componentKeys:[...keys]}];
    change({...draft,models:draft.models.map(row=>row.modelVersionId===versionId?{...row,mappings:rows}:row)});setError(null);
  }
  async function save(){if(!draft)return;setBusy(true);setError(null);
    try{const result=await service.save(configurationId,configuration?.configurationRevision??null,draft);setData(value=>value?{...value,items:[...value.items.filter(c=>c.configurationId!==configurationId),result]}:value);setDirty(false);setNotice(t('共享配置已保存并应用','Shared configuration saved and applied'));}
    catch(error){setError(error);}finally{setBusy(false);}}
  async function assign(){if(!configuration)return;setBusy(true);setError(null);
    try{const rows=(await service.resolve(adopt)).items;await service.assign(configuration,rows,data?.assignments??[]);setPicker(null);setReload(v=>v+1);setNotice(t('设备已采用共享配置','Equipment now uses the shared configuration'));}
    catch(error){setError(error);}finally{setBusy(false);}}
  return <section className="eq-hierarchy" aria-label={t('设备层级','Equipment hierarchy')}>
    <header className="eq-heading"><div className="eq-tabs" role="tablist"><button role="tab" aria-selected={tab==='configuration'} onClick={()=>setTab('configuration')}>{t('型号配置','Type configurations')}</button><button role="tab" aria-selected={tab==='equipment'} onClick={()=>setTab('equipment')}>{t('项目设备','Project equipment')} <small>{equipment.length}{next?'+':''}</small></button></div>
      <div className="eq-actions">{tab==='configuration'&&<><Btn disabled={!canWrite||busy} onClick={()=>{setNewName('');setPicker('create');}}><Plus size={14}/>{t('新建型号配置','New configuration')}</Btn><Btn primary disabled={!dirty||busy||!draft?.models.length} onClick={()=>void save()}><Check size={14}/>{busy?t('正在保存…','Saving…'):t('保存并应用','Save & apply')}</Btn></>}{onOpenScene&&<Btn onClick={onOpenScene}>{t('进入场景布置','Open scene placement')}</Btn>}</div></header>
    {!!error&&<div role="alert" className="eq-message">{error instanceof Error&&!(error as {code?:string}).code?error.message:failureMessage(error,locale)}</div>}{notice&&<div role="status" className="eq-message">{notice}</div>}
    {reading?<p role="status">{t('正在读取设备与配置…','Loading equipment and configurations…')}</p>:tab==='configuration'?draft?<>
      <div className="eq-config-bar"><label>{t('项目型号配置','Project configuration')}<select value={configurationId} onChange={event=>{if(dirty){setNotice(t('请先保存当前修改再切换配置','Save changes before switching'));return;}setConfigurationId(event.target.value);}}>{data?.items.map(row=><option key={row.configurationId} value={row.configurationId}>{row.snapshot.displayName}</option>)}{!configuration&&<option value={configurationId}>{draft.displayName}</option>}</select></label>
        <label>{t('固定模型版本','Fixed model version')}<select value={versionId} onChange={event=>setVersionId(event.target.value)}>{draft.models.map(entry=><option key={entry.modelVersionId} value={entry.modelVersionId}>{versions.find(m=>m.modelVersionId===entry.modelVersionId)?.displayName??entry.modelVersionId}</option>)}</select></label>
        <Btn disabled={!canWrite||busy} onClick={()=>setPicker('model')}><Boxes size={14}/>{t('关联模型','Link model')}</Btn><span>{t('用于','Used by ')} {configuration?.equipmentCount??0} {t('台设备','devices')}{dirty?t(' · 有未保存修改',' · Unsaved changes'):''}</span>
        <Btn disabled={!configuration||dirty||!canWrite||busy} onClick={()=>{setAdopt(equipment.filter(item=>item.objectKind===draft.objectKind).map(item=>item.entityUid));setPicker('adoption');}}>{t('应用到设备','Apply to equipment')}</Btn></div>
      <div className="eq-workspace"><aside className="eq-object-panel"><header><strong>{t('共享工程对象','Shared engineering objects')}</strong><Btn aria-label={t('加入共享工程对象','Add a shared engineering object')} disabled={!canWrite} onClick={()=>{setQuery('');setPicker('object');}}><Plus size={14}/></Btn></header>
        <button className="eq-root" onClick={()=>draft.rootDefinition&&setSelectedUid(draft.rootDefinition.objectRef.entityUid)}><ChevronDown size={14}/><Box size={15}/>{draft.displayName}</button>
        <div className="eq-object-list">{[...new Set([...mapping.map(m=>m.objectRef.entityUid),...(selectedUid?[selectedUid]:[])])].map(uid=><button key={uid} aria-pressed={selectedUid===uid} onClick={()=>setSelectedUid(uid)}><Box size={14}/><span>{byUid.get(uid)?.displayName??uid}<small>{mapping.find(m=>m.objectRef.entityUid===uid)?.componentKeys.length??0} {t('个直接构件','direct components')}</small></span></button>)}</div>
        {parentUid&&<SharedCabinetObjects api={api} parentUid={parentUid} selectedUid={selectedUid} onSelect={setSelectedUid} en={en}/>}
        {!mapping.length&&<p className="eq-caption">{t('加入工程对象并选择对应构件。','Add engineering objects and map their components.')}</p>}</aside>
        <main className="eq-model-panel">{model?<><ModelPreviewTools inspection={inspection}/><div className="eq-model-view"><Suspense fallback={<p role="status">{t('正在读取模型…','Loading model…')}</p>}><SceneViewport api={api} snapshot={previewScene} modelRefs={[]} terrainVersion={null} selectedId={null} editing={false} personalVisibility={{}} terrainVisible={false} pendingPlacement={false}
          previewModel={model} previewSelection={inspection.selection} onPreviewStructure={inspection.ready} onPreviewPick={(identity,nodeId)=>{inspection.pick(identity,nodeId);if(identity===inspection.selection.identity)chooseModelNode(nodeId);}} onSelect={ignore} onPoint={ignore} onMove={async()=>false} onViewChange={ignore} onError={setError}/></Suspense></div>
          <details className="eq-component-tree"><summary>{t('模型构件树与属性','Model component tree and properties')}</summary><ModelComponentTree version={model} inspection={editableInspection} onClose={()=>setPicker('model')}/>{inspection.node&&<ModelComponentProperties version={model} inspection={inspection}/>}</details></>:<div className="eq-empty"><Boxes size={30}/><p>{t('关联一个模型固定版本','Link a fixed model version')}</p><Btn onClick={()=>setPicker('model')}>{t('选择模型','Select model')}</Btn></div>}</main>
        <aside className="eq-mapping-panel"><header><strong>{definition?.item.displayName??t('选择工程对象','Select an engineering object')}</strong></header>
          {definition&&<><p className="eq-caption">{t('同型号共享映射','Shared type mapping')} · {objectCategory(definition.item,locale)}</p><div className="eq-component-options">{model?.components.map(component=><label key={component.componentKey}><input type="checkbox" checked={keys.includes(component.componentKey)} disabled={!canWrite} onChange={()=>setKeys(previous=>previous.includes(component.componentKey)?previous.filter(k=>k!==component.componentKey):[...previous,component.componentKey])}/><span>{component.displayName}{component.geometryQuality==='proxy_schematic'&&<small>{t('示意代理','Schematic proxy')}</small>}</span></label>)}</div>
          <div className="eq-actions"><Btn disabled={!canWrite||!model||busy} onClick={()=>updateMapping()}><Link2 size={14}/>{t('更新构件映射','Update mapping')}</Btn>{mapping.some(m=>m.objectRef.entityUid===selectedUid)&&<Btn disabled={!canWrite||busy} onClick={()=>updateMapping(true)}><Trash2 size={14}/>{t('解除','Unlink')}</Btn>}</div>
          {definition.item.objectKind===draft.objectKind&&<Btn disabled={!canWrite} onClick={()=>change({...draft,rootDefinition:{objectRef:definition.objectRef,expectedEntityRevision:definition.item.entityRevision}})}>{t('设为整机工程定义','Use as root engineering definition')}</Btn>}
          <p className="eq-caption">{t('无直接几何的对象可通过所属柜体或总成定位。','Objects without direct geometry use their cabinet or assembly.')}</p><EquipmentPhotos api={api} definition={definition} device={device} en={en} canWrite={canWrite}/>
          <details><summary>{t('工程图纸','Engineering drawings')}</summary><SourceEvidence api={api} object={definition.item} context={null} host="—" endpointPrefix="/api/workbench/objects/evidence"/></details></>}
        </aside></div></>:<div className="eq-empty"><Boxes size={30}/><p>{t('为本项目建立型号共享配置','Create a shared equipment configuration for this project')}</p><Btn disabled={!canWrite} onClick={()=>setPicker('create')}>{t('新建型号配置','New configuration')}</Btn></div>:<div className="eq-device-workspace"><aside className="eq-device-list"><header><strong>{t('项目设备','Project equipment')}</strong><small>{equipment.filter(item=>item.sceneUseCount>0).length} {t('已布置','placed')} · {equipment.filter(item=>!item.sceneUseCount).length} {t('未布置','not placed')}{next?'+':''}</small></header>{[...equipment].sort((a,b)=>a.displayName.localeCompare(b.displayName,en?'en':'zh',{numeric:true})).map(item=>{const adopted=data?.assignments.find(a=>a.equipment_uid===item.entityUid),cfg=data?.items.find(c=>c.configurationId===adopted?.configuration_id);return <button key={item.entityUid} aria-pressed={deviceUid===item.entityUid} onClick={()=>setDeviceUid(item.entityUid)} draggable onDragStart={event=>{event.dataTransfer.setData('application/x-ontovis-equipment',JSON.stringify({entityUid:item.entityUid}));event.dataTransfer.effectAllowed='copy';}}><Box size={16}/><span>{item.displayName}<small>{cfg?.snapshot.displayName??t('未采用型号配置','No configuration')} · {item.sceneUseCount?t('已布置','Placed'):t('未布置','Not placed')}</small></span></button>;})}
        {next&&<Btn onClick={()=>void service.catalogue('',next).then(value=>{setEquipment(rows=>[...rows,...value.items]);setNext(value.nextCursor);}).catch(setError)}>{t('加载更多','Load more')}</Btn>}</aside>
        <main className="eq-device-detail">{record&&device?<><header><h3>{device.item.displayName}</h3>{onAnalyze&&<Btn onClick={()=>onAnalyze({entityUid:device.item.entityUid,expectedEntityRevision:device.item.entityRevision,timeTo:new Date().toISOString()})}>{t('进入分析','Analyze')}</Btn>}</header>
          <p>{device.context?.displayName} · {data?.items.find(c=>c.configurationId===data?.assignments.find(a=>a.equipment_uid===(device.root?.entityUid??device.item.entityUid))?.configuration_id)?.snapshot.displayName??t('未采用型号配置','No type configuration')}</p>
          {device.root&&device.root.entityUid!==device.item.entityUid&&<Btn onClick={()=>setDeviceUid(device.root!.entityUid)}>{t('返回整机','Back to equipment root')}</Btn>}
          <details open><summary>{t('内部设备','Internal equipment')} ({record.children.length})</summary><div className="eq-device-children">{record.children.map(item=><button key={item.entityUid} onClick={()=>setDeviceUid(item.entityUid)}><Box size={14}/>{item.displayName}</button>)}</div></details>
          {parentUid&&<SharedCabinetObjects api={api} parentUid={parentUid} selectedUid={selectedUid} onSelect={setSelectedUid} en={en}/>}<EquipmentPhotos api={api} definition={definition} device={device} en={en} canWrite={canWrite}/>
          <details><summary>{t('工程图纸','Engineering drawings')}</summary><SourceEvidence api={api} object={device.item} context={device.context} host="—" endpointPrefix="/api/workbench/objects/evidence"/></details>
        </>:<p>{t('选择一台设备，查看配置、内部设备和照片。','Select equipment to inspect its configuration, children and photos.')}</p>}</main></div>}
    {picker==='model'&&<Modal title={t('选择共享模型','Select a shared model')} description={t('固定版本用于当前项目配置','Use a fixed version for this project configuration')} onClose={()=>setPicker(null)}><ResourcePanel api={api} modelsOnly canPlace={false} canAcquire={false} onPlace={ignore} onPreview={chooseModel} onTerrainReady={ignore}/></Modal>}
    {picker==='object'&&<Modal title={t('选择共享工程对象','Select a shared engineering object')} description={t('项目工程对象，不含设备实例','Project engineering definitions')} onClose={()=>setPicker(null)}><label className="eq-search"><Search size={14}/><input value={query} onChange={event=>setQuery(event.target.value)} placeholder={t('名称、位号或类型','Name, identifier or type')}/></label><Catalog key={settled} api={api} query={settled} scope="project" selected={selectedUid} onSelect={uid=>{setSelectedUid(uid);setPicker(null);}}/></Modal>}
    {picker==='create'&&<Modal title={t('新建型号配置','New type configuration')} description={t('仅在当前项目内共享','Shared within this project')} onClose={()=>setPicker(null)}><form className="eq-form" onSubmit={event=>{event.preventDefault();setConfigurationId(crypto.randomUUID());setDraft({displayName:newName.trim(),objectKind:newKind,rootDefinition:null,models:[]});setVersionId('');setSelectedUid('');setDirty(true);setPicker(null);}}><label>{t('配置名称','Configuration name')}<input value={newName} maxLength={200} required onChange={event=>setNewName(event.target.value)}/></label><label>{t('整机类型','Equipment kind')}<select value={newKind} onChange={event=>setNewKind(event.target.value)}>{[['equipment','设备 / Equipment'],['turbine','风机 / Turbine'],['cabinet','柜体 / Cabinet'],['pump','泵 / Pump'],['assembly','总成 / Assembly']].map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label><Btn type="submit" primary disabled={!newName.trim()}>{t('创建配置','Create configuration')}</Btn></form></Modal>}
    {picker==='adoption'&&<Modal title={t('应用到项目设备','Apply to project equipment')} description={t('设备采用同一份当前型号配置','Equipment shares the current configuration')} onClose={()=>setPicker(null)}><label><input type="checkbox" checked={equipment.filter(item=>item.objectKind===draft?.objectKind).every(item=>adopt.includes(item.entityUid))} onChange={event=>setAdopt(event.target.checked?equipment.filter(item=>item.objectKind===draft?.objectKind).map(item=>item.entityUid):[])}/>{t('全选同类型设备','Select all matching equipment')}</label><div className="eq-adoption-list">{equipment.filter(item=>item.objectKind===draft?.objectKind).map(item=><label key={item.entityUid}><input type="checkbox" checked={adopt.includes(item.entityUid)} onChange={event=>setAdopt(rows=>event.target.checked?[...rows,item.entityUid]:rows.filter(uid=>uid!==item.entityUid))}/>{item.displayName}</label>)}</div><Btn primary disabled={!adopt.length||busy} onClick={()=>void assign()}>{t('应用到','Apply to')} {adopt.length} {t('台设备','devices')}</Btn></Modal>}
  </section>;
}
