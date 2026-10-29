import {lazy,Suspense,useEffect,useMemo,useState} from 'react';
import {Box,Boxes,Check,ChevronDown,Focus,Link2,Plus,Search,Trash2} from 'lucide-react';
import {cancelled,failureMessage,type WorkbenchApi} from './api';
import {EquipmentApi,type EquipmentConfiguration,type EquipmentConfigurations,type EquipmentConfigurationSnapshot,type SourceAdoption,type ApplicationBundle} from './equipmentApi';
import type {EngineeringObject} from './types';
import type {SceneObjectContext} from './sceneEngineeringTypes';
import type {ProjectModelVersion} from './resourceTypes';
import type {LocalSceneSnapshot} from './sceneTypes';
import type {AnalysisEntry} from './analysisSources';
import {SceneApi} from './sceneApi';
import {Btn,Modal} from './Primitives';
import {usePreferences} from './Preferences';
import {EquipmentDevices} from './EquipmentDevices';
import {EquipmentApplicationPicker,EquipmentApplicationDetails} from './EquipmentApplication';
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
  const [tab,setTab]=useState<'configuration'|'equipment'>('equipment'),[reload,setReload]=useState(0);
  const [data,setData]=useState<EquipmentConfigurations|null>(null),[configurationId,setConfigurationId]=useState(''),[draft,setDraft]=useState<EquipmentConfigurationSnapshot|null>(null),[dirty,setDirty]=useState(false);
  const [versions,setVersions]=useState<ProjectModelVersion[]>([]),[versionId,setVersionId]=useState('');
  const [selectedUid,setSelectedUid]=useState(''),[definition,setDefinition]=useState<SceneObjectContext|null>(null),[extraObjects,setExtraObjects]=useState<EngineeringObject[]>([]);
  const [bundle,setBundle]=useState<ApplicationBundle|null>(null),[pending,setPending]=useState<{device:SceneObjectContext;adoption:SourceAdoption|null}|null>(null);
  const [error,setError]=useState<unknown>(null),[busy,setBusy]=useState(false),[notice,setNotice]=useState(''),[reading,setReading]=useState(false),[sourceBusy,setSourceBusy]=useState(false);
  const [picker,setPicker]=useState<'model'|'source'|'details'|null>(null),[continuing,setContinuing]=useState(false),[keys,setKeys]=useState<string[]>([]);
  const configuration=data?.items.find(row=>row.configurationId===configurationId),model=versions.find(row=>row.modelVersionId===versionId)??null;
  const inspection=useModelPreview(model),mapping=draft?.models.find(row=>row.modelVersionId===versionId)?.mappings??[];
  const objects=[...(data?.objects??[]),...extraObjects],byUid=new Map(objects.map(item=>[item.entityUid,item]));
  const canWrite=data?.capabilities.canWrite??false,editable=canWrite&&!!draft?.projectApplicationRef&&!!bundle&&!sourceBusy;
  const allowed=bundle?[...(bundle.application.snapshot.rootDefinition?[bundle.application.snapshot.rootDefinition]:[]),...bundle.application.snapshot.mappings].map(row=>row.entityUid):[];
  const selectedAllowed=allowed.includes(selectedUid);
  const parentUid=definition?.item.objectKind==='cabinet'?definition.item.entityUid:definition?.item.definitionParentEntityUid??'';
  function chooseModelNode(nodeId:string|null,focus=true){inspection.choose(nodeId,focus);const node=inspection.structure?.nodes.find(row=>row.id===nodeId);if(node?.componentKeys.length)setKeys([...node.componentKeys]);}
  const editableInspection={...inspection,choose:chooseModelNode};
  useEffect(()=>{if(tab!=='configuration'||data)return;const abort=new AbortController();setReading(true);setError(null);
    service.configurations(abort.signal).then(value=>{if(!abort.signal.aborted){setReading(false);setData(value);setVersions(value.models);setConfigurationId(value.items[0]?.configurationId??'');}})
      .catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setError(e);}).finally(()=>{if(!abort.signal.aborted)setReading(false);});return()=>abort.abort();
  },[service,api.epoch,api.revision,tab,data,reload]);
  useEffect(()=>{setData(null);setDraft(null);setConfigurationId('');setBundle(null);setVersions([]);setPending(null);},[api,api.epoch,api.revision]);
  useEffect(()=>{if(!configuration)return;setDraft(structuredClone(configuration.snapshot));setVersionId(configuration.snapshot.models[0]?.modelVersionId??'');setDirty(false);setSelectedUid(configuration.snapshot.models[0]?.mappings[0]?.objectRef.entityUid??'');},[configuration?.configurationId,configuration?.configurationRevision]);
  useEffect(()=>{const abort=new AbortController();setBundle(null);setSourceBusy(false);if(!draft?.projectApplicationRef)return;setSourceBusy(true);
    service.application(draft.projectApplicationRef.applicationRevisionId,abort.signal).then(value=>{if(!abort.signal.aborted){setBundle(value);setExtraObjects(value.objects);}})
      .catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setError(e);}).finally(()=>{if(!abort.signal.aborted)setSourceBusy(false);});return()=>abort.abort();
  },[service,api.epoch,api.revision,draft?.projectApplicationRef?.applicationRevisionId]);
  useEffect(()=>{if(!pending||!data)return;const root=pending.device.root?.entityUid??pending.device.item.entityUid;
    const legacy=data.assignments.find(row=>row.equipment_uid===root);
    const target=pending.adoption?data.items.find(row=>row.snapshot.projectApplicationRef?.applicationRevisionId===pending.adoption!.applicationRevisionId):data.items.find(row=>row.configurationId===legacy?.configuration_id);
    if(target&&target.configurationId!==configurationId){setConfigurationId(target.configurationId);return;}
    if(target){setSelectedUid(pending.device.item.sourceTemplateEntityUid??target.snapshot.rootDefinition?.objectRef.entityUid??'');}
    else setNotice(t('该项目采用尚未建立共享构件绑定，请选择项目采用后配置。','This application has no component binding yet. Choose its project application to configure it.'));
    setPending(null);
  },[pending,data,configurationId]);
  useEffect(()=>{const abort=new AbortController();setDefinition(null);if(tab==='configuration'&&selectedUid)void new SceneApi(api).objectContext(selectedUid,undefined,abort.signal).then(row=>{if(!abort.signal.aborted){setDefinition(row);setExtraObjects(items=>[...items.filter(x=>x.entityUid!==row.item.entityUid),row.item]);}}).catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setError(e);});
    setKeys(mapping.find(m=>m.objectRef.entityUid===selectedUid)?.componentKeys??[]);return()=>abort.abort();
  },[api,api.epoch,api.revision,selectedUid,configurationId,configuration?.configurationRevision,versionId,tab]);
  useEffect(()=>{const focused=keys.length?keys:mapping.find(row=>row.objectRef.entityUid===parentUid)?.componentKeys??[];if(!inspection.structure||!focused.length)return;
    const node=inspection.structure.nodes.find(node=>focused.every(key=>node.componentKeys.includes(key)))??inspection.structure.nodes.find(node=>node.componentKeys.some(key=>focused.includes(key)));if(node)inspection.choose(node.id);
  },[inspection.structure,keys.join('|'),parentUid]);
  useEffect(()=>{onDirtyChange?.(dirty);},[dirty,onDirtyChange]);useEffect(()=>()=>onDirtyChange?.(false),[onDirtyChange]);
  const change=(value:EquipmentConfigurationSnapshot)=>{setDraft(value);setDirty(true);setNotice('');};
  function chooseModel(value:ProjectModelVersion|null){if(!value)return;setVersions(rows=>[...rows.filter(row=>row.modelVersionId!==value.modelVersionId),value]);setVersionId(value.modelVersionId);setPicker(null);
    if(draft&&!draft.models.some(row=>row.modelVersionId===value.modelVersionId))change({...draft,models:[...draft.models,{modelVersionId:value.modelVersionId,mappings:[]}]});}
  function updateMapping(remove=false){if(!draft||!definition||!model||!editable||!selectedAllowed)return;const others=mapping.filter(row=>row.objectRef.entityUid!==selectedUid);
    if(!remove&&others.some(row=>row.componentKeys.some(key=>keys.includes(key)))){setError(new Error(t('所选构件已有其他工程对象映射','A component is already mapped')));return;}
    const expected=[bundle!.application.snapshot.rootDefinition,...bundle!.application.snapshot.mappings].find(row=>row?.entityUid===selectedUid)?.expectedEntityRevision;
    if(expected!==definition.item.entityRevision){setError(new Error(t('工程定义已变化，请在源端核对项目采用。','The engineering definition changed. Review the source application.')));return;}
    const rows=remove?others:[...others,{objectRef:definition.objectRef,expectedEntityRevision:expected,componentKeys:[...keys]}];change({...draft,models:draft.models.map(row=>row.modelVersionId===versionId?{...row,mappings:rows}:row)});setError(null);}
  function chooseApplication(value:ApplicationBundle){if(!api.project)return;const app=value.application,source=app.snapshot;
    const ref={applicationId:app.applicationId,applicationRevisionId:app.revisionId,specificationRevisionId:source.specificationRevisionId};
    if(!continuing){setConfigurationId(crypto.randomUUID());setVersionId('');setSelectedUid(source.mappings[0]?.entityUid??source.rootDefinition?.entityUid??'');}
    change({displayName:source.name,objectKind:app.specification.objectKind,projectApplicationRef:ref,
      rootDefinition:source.rootDefinition?{objectRef:{...api.project,entityUid:source.rootDefinition.entityUid},expectedEntityRevision:source.rootDefinition.expectedEntityRevision}:null,
      models:continuing&&draft?draft.models:[]});setBundle(value);setExtraObjects(value.objects);setPicker(null);}
  async function save(){if(!draft||!editable)return;setBusy(true);setError(null);try{const result=await service.save(configurationId,configuration?.configurationRevision??null,draft);setData(value=>value?{...value,items:[...value.items.filter(c=>c.configurationId!==configurationId),result]}:value);setDirty(false);setNotice(t('构件绑定已保存，设备采用由源端管理。','Component binding saved. Equipment adoption is managed at the source.'));}catch(e){setError(e);}finally{setBusy(false);}}
  return <section className="eq-hierarchy" aria-label={t('设备层级','Equipment hierarchy')}>
    <header className="eq-heading"><div className="eq-tabs" role="tablist"><button role="tab" aria-selected={tab==='equipment'} onClick={()=>setTab('equipment')}>{t('项目设备','Project equipment')}</button><button role="tab" aria-selected={tab==='configuration'} onClick={()=>setTab('configuration')}>{t('构件绑定','Component binding')}</button></div>
    <div className="eq-actions">{tab==='configuration'&&<><Btn disabled={!canWrite||busy||dirty} onClick={()=>{setContinuing(false);setPicker('source');}}><Plus size={14}/>{t('选择项目采用','Choose project application')}</Btn><Btn primary disabled={!dirty||busy||!editable||!draft?.models.length} onClick={()=>void save()}><Check size={14}/>{busy?t('正在保存…','Saving…'):t('保存构件绑定','Save binding')}</Btn></>}</div></header>
    <div hidden={tab!=='equipment'} className="eq-device-host"><EquipmentDevices api={api} en={en} active={tab==='equipment'} onAnalyze={onAnalyze} onOpenScene={onOpenScene} onBinding={(device,adoption)=>{setPending({device,adoption});setTab('configuration');}}/></div>
    {tab==='configuration'&&<>{!!error&&<div role="alert" className="eq-message">{error instanceof Error&&!(error as {code?:string}).code?error.message:failureMessage(error,locale)}<Btn onClick={()=>{setData(null);setReload(value=>value+1);}}>{t('重新读取','Reload')}</Btn></div>}{notice&&<div role="status" className="eq-message">{notice}</div>}
    {reading?<p role="status">{t('正在读取共享绑定…','Loading shared bindings…')}</p>:draft?<>
    <div className="eq-config-bar"><label>{t('固定项目采用','Fixed project application')}<select value={configurationId} onChange={event=>{if(dirty){setNotice(t('请先保存当前修改再切换配置','Save changes before switching'));return;}setConfigurationId(event.target.value);}}>{data?.items.map(row=><option key={row.configurationId} value={row.configurationId}>{row.snapshot.displayName}</option>)}{!configuration&&<option value={configurationId}>{draft.displayName}</option>}</select></label>
    <label>{t('固定模型版本','Fixed model version')}<select value={versionId} onChange={event=>setVersionId(event.target.value)}>{draft.models.map(entry=><option key={entry.modelVersionId} value={entry.modelVersionId}>{versions.find(m=>m.modelVersionId===entry.modelVersionId)?.displayName??entry.modelVersionId}</option>)}</select></label>
    <Btn disabled={!editable||busy} onClick={()=>setPicker('model')}><Boxes size={14}/>{t('关联模型','Link model')}</Btn><Btn disabled={!bundle} onClick={()=>setPicker('details')}>{t('规格与采用详情','Specification and adoption')}</Btn></div>
    {!draft.projectApplicationRef&&<div className="eq-message">{t('旧共享绑定继续可读。选择源端项目采用并核对原映射后接续。','Legacy bindings remain readable. Select the source application to continue with the original mappings.')} <Btn disabled={!canWrite||busy} onClick={()=>{setContinuing(true);setPicker('source');}}>{t('接续项目采用','Link source application')}</Btn></div>}
    {sourceBusy&&<p role="status">{t('正在读取源端固定规格…','Loading fixed source specification…')}</p>}
    <div className="eq-workspace"><aside className="eq-object-panel"><header><strong>{t('共享工程对象','Shared engineering objects')}</strong></header><button className="eq-root" onClick={()=>draft.rootDefinition&&setSelectedUid(draft.rootDefinition.objectRef.entityUid)}><ChevronDown size={14}/><Box size={15}/>{draft.displayName}</button>
    <div className="eq-object-list">{[...new Set([...allowed,...mapping.map(m=>m.objectRef.entityUid)])].filter(uid=>uid!==draft.rootDefinition?.objectRef.entityUid).map(uid=><button key={uid} aria-pressed={selectedUid===uid} onClick={()=>setSelectedUid(uid)}><Box size={14}/><span>{byUid.get(uid)?.displayName??uid}<small>{mapping.find(m=>m.objectRef.entityUid===uid)?.componentKeys.length??0} {t('个直接构件','direct components')}</small></span></button>)}</div>
    {parentUid&&<SharedCabinetObjects key={parentUid} api={api} parentUid={parentUid} selectedUid={selectedUid} onSelect={setSelectedUid} en={en}/>}</aside>
    <main className="eq-model-panel">{model?<><ModelPreviewTools inspection={inspection}/><div className="eq-model-view"><Suspense fallback={<p role="status">{t('正在读取模型…','Loading model…')}</p>}><SceneViewport api={api} snapshot={previewScene} modelRefs={[]} terrainVersion={null} selectedId={null} editing={false} personalVisibility={{}} terrainVisible={false} pendingPlacement={false}
          previewModel={model} previewSelection={inspection.selection} onPreviewStructure={inspection.ready} onPreviewPick={(identity,nodeId)=>{inspection.pick(identity,nodeId);if(identity===inspection.selection.identity)chooseModelNode(nodeId);}} onSelect={ignore} onPoint={ignore} onMove={async()=>false} onViewChange={ignore} onError={setError}/></Suspense></div>
          <details className="eq-component-tree"><summary>{t('模型构件树与属性','Model component tree and properties')}</summary><ModelComponentTree version={model} inspection={editableInspection} onClose={()=>setPicker('model')}/>{inspection.node&&<ModelComponentProperties version={model} inspection={inspection}/>}</details></>:<div className="eq-empty"><Boxes size={30}/><p>{t('关联一个模型固定版本','Link a fixed model version')}</p><Btn onClick={()=>setPicker('model')}>{t('选择模型','Select model')}</Btn></div>}</main>

    <aside className="eq-mapping-panel"><header><strong>{definition?.item.displayName??t('选择工程对象','Select an engineering object')}</strong></header>{definition&&<><p className="eq-caption">{objectCategory(definition.item,locale)}</p><div className="eq-component-options">{model?.components.map(component=><label key={component.componentKey}><input type="checkbox" checked={keys.includes(component.componentKey)} disabled={!editable||!selectedAllowed} onChange={()=>setKeys(previous=>previous.includes(component.componentKey)?previous.filter(k=>k!==component.componentKey):[...previous,component.componentKey])}/><span>{component.displayName}{component.geometryQuality==='proxy_schematic'&&<small>{t('示意代理','Schematic proxy')}</small>}</span></label>)}</div>
    <div className="eq-actions"><Btn disabled={!editable||!selectedAllowed||!model||busy} onClick={()=>updateMapping()}><Link2 size={14}/>{t('更新构件映射','Update mapping')}</Btn>{mapping.some(m=>m.objectRef.entityUid===selectedUid)&&<Btn disabled={!editable||!selectedAllowed||busy} onClick={()=>updateMapping(true)}><Trash2 size={14}/>{t('解除','Unlink')}</Btn>}<Btn onClick={()=>setPicker('details')}>{t('图纸与工程资料','Drawings and materials')}</Btn></div><p className="eq-caption">{!selectedAllowed?t('柜内成员保留原工程身份；通过所属柜体定位。','Cabinet members keep their original identity and cabinet location.'):t('无直接几何时保留空映射，通过所属柜体或总成定位。','Keep an empty mapping for objects without direct geometry.')}</p></>}</aside></div>
    </>:<div className="eq-empty"><Boxes size={30}/><p>{t('选择 OntoBase 已建立的项目采用，再配置三维绑定。','Choose an OntoBase project application to configure geometry bindings.')}</p><Btn disabled={!canWrite} onClick={()=>{setContinuing(false);setPicker('source');}}>{t('选择项目采用','Choose project application')}</Btn></div>}</>}
    {picker==='model'&&<Modal title={t('选择共享模型','Select a shared model')} description={t('固定版本用于当前项目采用','Use a fixed version for this project application')} onClose={()=>setPicker(null)}><ResourcePanel api={api} modelsOnly canPlace={false} canAcquire={false} onPlace={ignore} onPreview={chooseModel} onTerrainReady={ignore}/></Modal>}
    {picker==='source'&&<EquipmentApplicationPicker api={api} en={en} continuing={continuing} onClose={()=>setPicker(null)} onSelect={chooseApplication}/>}
    {picker==='details'&&<Modal className="eq-application-modal" title={t('源端规格与工程资料','Source specification and materials')} description={t('只读固定来源','Read-only fixed source')} onClose={()=>setPicker(null)}>{bundle&&<EquipmentApplicationDetails value={bundle} en={en}/>} {definition&&<><EquipmentPhotos key={definition.item.entityUid} api={api} definition={definition} device={null} en={en}/><SourceEvidence api={api} object={definition.item} context={null} host="—" endpointPrefix="/api/workbench/objects/evidence"/></>}</Modal>}
  </section>;
}
