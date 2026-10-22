import {forwardRef, lazy, Suspense, useEffect, useImperativeHandle, useMemo, useRef, useState} from 'react';
import {ArrowLeft, Check, Copy, Eye, EyeOff, Focus, Layers, LockKeyhole, PanelLeft, PanelRight, Plus, Redo2, Save, Search, Trash2, Undo2, UnlockKeyhole, X} from 'lucide-react';
import {ApiError, cancelled, failureMessage, type WorkbenchApi} from './api';
import {SceneApi} from './sceneApi';
import {ReplacementImpact} from './ReplacementImpact';
import {Badge, Btn, IconBtn, Modal} from './Primitives';
import {usePreferences} from './Preferences';
import {sceneText} from './sceneMessages';
import {cloneSnapshot, commitScene, duplicateAt, isLocalInstance, isLocalScene, moveInstance, placeModel, redoScene, sceneHistory, undoScene, updateInstance, type SceneHistory} from './sceneState';
import {fromDisplay, toDisplay} from './sceneTransforms';
import type {ProjectModelVersion, TerrainVersion} from './resourceTypes';
import type {EditableSceneSnapshot, GeographicAnchor, ModelResourceRef, SceneCheck, SceneList, SceneModelInstance, SceneOpen, SceneReplacementCheckRequest, SceneSaveRequest, SceneView, Vector3} from './sceneTypes';
import './scenes.css';

const SceneViewport=lazy(()=>import('./SceneViewport').then(module=>({default:module.SceneViewport})));
const ResourcePanel=lazy(()=>import('./ResourcePanel').then(module=>({default:module.ResourcePanel})));
export interface SceneWorkspaceHandle {requestLeave:(after:()=>void)=>void}
const modelRef=(model:ProjectModelVersion):ModelResourceRef=>({modelAssetId:model.modelAssetId,modelVersionId:model.modelVersionId,contentRevision:model.contentRevision,sha256:model.sha256});
type ReplacementOperation=Omit<Extract<SceneReplacementCheckRequest,{kind:'model'}>,'sceneId'|'expectedSceneRevision'|'snapshot'>|Omit<Extract<SceneReplacementCheckRequest,{kind:'terrain'}>,'sceneId'|'expectedSceneRevision'|'snapshot'>;
const finite=(value:string)=>value.trim()!=='' && Number.isFinite(Number(value));

export const SceneWorkspace=forwardRef<SceneWorkspaceHandle,{api:WorkbenchApi;onProjectName?:(name:string)=>void}>(function SceneWorkspace({api,onProjectName},ref) {
  const {locale}=usePreferences(),t=(key:Parameters<typeof sceneText>[1])=>sceneText(locale,key);
  const client=useMemo(()=>new SceneApi(api),[api]);
  const [list,setList]=useState<SceneList|null>(null),[search,setSearch]=useState(''),[base,setBase]=useState<SceneOpen|null>(null);
  const [history,setHistory]=useState<SceneHistory|null>(null),[selected,setSelected]=useState<string|null>(null);
  const [editing,setEditing]=useState(false),[readOnly,setReadOnly]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState<unknown>(null);
  const [left,setLeft]=useState<'content'|'resources'>('content'),[side,setSide]=useState<'left'|'right'|null>(null);
  const [modal,setModal]=useState<'create'|'leave'|'conflict'|'anchor'|'replaceTerrain'|null>(null),[newName,setNewName]=useState('');
  const [personal,setPersonal]=useState<Record<string,boolean>>({}),[terrainVisible,setTerrainVisible]=useState(true),[update,setUpdate]=useState(false);
  const [terrain,setTerrain]=useState<TerrainVersion|null>(null),[candidate,setCandidate]=useState<TerrainVersion|null>(null);
  const [preview,setPreview]=useState<ProjectModelVersion|null>(null),[anchorResult,setAnchorResult]=useState<SceneCheck|null>(null);
  const [saveUnknown,setSaveUnknown]=useState(false);
  const [terrainStrategy,setTerrainStrategy]=useState<'keep_height'|'resample_ground'>('resample_ground');
  const [pending,setPending]=useState<{kind:'model',model:ProjectModelVersion}|{kind:'copy',sourceId:string}|null>(null);
  const [hints,setHints]=useState<Record<string,ModelResourceRef>>({});
  const [viewCommand,setViewCommand]=useState<{token:number,view:SceneView}|undefined>(),[focus,setFocus]=useState<{token:number,instanceId:string|null}|undefined>();
  const [anchor,setAnchor]=useState({x:'0',z:'0',longitude:'',latitude:'',heading:'0',offset:'0',strategy:'resample_each_ground' as GeographicAnchor['heightStrategy']});
  const [position,setPosition]=useState({name:'',mode:'local',x:'0',z:'0',longitude:'',latitude:'',heading:'0',heightMode:'relative',height:'0',source:''});
  const mounted=useRef(false),requests=useRef(new Set<AbortController>()),sequence=useRef(0),listSequence=useRef(0);
  const leave=useRef<(()=>void)|null>(null),liveView=useRef<SceneView|null>(null),beforeAnchorView=useRef<SceneView|null>(null);
  const saveRequest=useRef<{key:string,body:SceneSaveRequest,models:ModelResourceRef[],terrain:TerrainVersion|null}|null>(null);
  const editRequest=useRef<AbortController|null>(null),saveInFlight=useRef(false);
  const createRequest=useRef<{name:string,id:string}|null>(null);
  const draft=history?.present||null,current=draft?.instances.find(item=>item.sceneModelInstanceId===selected)||null;
  const dirty=!!base && !!draft && JSON.stringify(base.snapshot)!==JSON.stringify(draft);
  const unsaved=dirty||!!anchorResult||saveUnknown;
  const canWrite=!!base?.capabilities.canWrite && !readOnly,editable=editing && canWrite && !busy && !preview && !anchorResult && !saveUnknown;
  const snapshot=anchorResult?.proposedSnapshot||draft;
  const refs=useMemo(()=>{
    const known=new Map([...(base?.resourceRefs||[]),...Object.values(hints),...(anchorResult?.resourceRefs.models||[])].map(item=>[item.modelVersionId,item]));
    return [...new Set(snapshot?.instances.map(item=>item.modelVersionId)||[])].flatMap(id=>known.has(id)?[known.get(id)!]:[]);
  },[snapshot,base,hints,anchorResult]);
  function controller(){const value=new AbortController();requests.current.add(value);return value;}
  function done(value:AbortController){requests.current.delete(value);}
  function syncWrite(value:{sceneId:string,capabilities:{canWrite:boolean}}){
    setBase(previous=>previous&&previous.sceneId===value.sceneId&&previous.capabilities.canWrite!==value.capabilities.canWrite?
      {...previous,capabilities:{...previous.capabilities,canWrite:value.capabilities.canWrite}}:previous);
    setReadOnly(!value.capabilities.canWrite);
    if(!value.capabilities.canWrite){setEditing(false);setPending(null);}
  }
  function cancelPlacement(){
    if(editRequest.current){sequence.current++;editRequest.current.abort();editRequest.current=null;setBusy(false);}
    setPending(null);
  }
  function failed(value:unknown){
    if(cancelled(value)||!mounted.current)return;
    if(value instanceof ApiError && value.status===403 && ['SCENE_WRITE_FORBIDDEN','MODEL_WRITE_FORBIDDEN'].includes(value.code)){setReadOnly(true);setEditing(false);setList(previous=>previous?{...previous,capabilities:{...previous.capabilities,canWrite:false}}:previous);}
    setError(value);
  }
  function requestLeave(after:()=>void){if(busy)return;if(unsaved){leave.current=after;setModal('leave');}else after();}
  useImperativeHandle(ref,()=>({requestLeave}),[unsaved,busy]);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;sequence.current++;listSequence.current++;for(const value of requests.current)value.abort();requests.current.clear();};},[]);
  useEffect(()=>{const handler=(event:BeforeUnloadEvent)=>{if(unsaved){event.preventDefault();event.returnValue='';}};window.addEventListener('beforeunload',handler);return()=>window.removeEventListener('beforeunload',handler);},[unsaved]);
  useEffect(()=>{const handler=(event:KeyboardEvent)=>{if(event.key==='Escape'){const cancelPreflight=!!editRequest.current&&(modal==='anchor'||modal==='replaceTerrain');cancelPlacement();if(cancelPreflight){setModal(null);setCandidate(null);}if(!modal&&anchorResult&&!saveUnknown&&!saveInFlight.current)cancelAnchor();setSide(null);}};window.addEventListener('keydown',handler);return()=>window.removeEventListener('keydown',handler);},[anchorResult,saveUnknown,modal]);
  async function readList(cursor?:string){
    const token=++listSequence.current,abort=controller();setBusy(true);setError(null);
    try{const value=await client.list({q:search,...(cursor?{cursor}:{})},abort.signal);if(mounted.current&&token===listSequence.current){setList(previous=>cursor&&previous?{...value,items:[...previous.items,...value.items]}:value);if(value.projectName)onProjectName?.(value.projectName);}}
    catch(value){if(token===listSequence.current)failed(value);}finally{done(abort);if(mounted.current&&token===listSequence.current)setBusy(false);}
  }
  useEffect(()=>{void readList();},[]);
  async function adopt(value:SceneOpen){
    setBase(value);setHistory(sceneHistory(value.snapshot));setSelected(value.snapshot.instances[0]?.sceneModelInstanceId||null);
    setPersonal({});setEditing(false);setReadOnly(false);setPending(null);setPreview(null);setAnchorResult(null);setUpdate(false);setHints({});setSide(null);
    setSaveUnknown(false);saveRequest.current=null;
    liveView.current=value.snapshot.initialView;setViewCommand({token:Date.now(),view:value.snapshot.initialView});
    if(value.snapshot.terrain){const abort=controller();try{const selectedTerrain=await client.version(value.snapshot.terrain.terrainVersionId,abort.signal);if(mounted.current)setTerrain(selectedTerrain);}catch(error){failed(error);}finally{done(abort);}}
    else setTerrain(null);
  }
  async function open(sceneId:string,revision?:string){
    const token=++sequence.current,abort=controller();setBusy(true);setError(null);
    try{const value=await client.open(sceneId,revision,abort.signal);if(mounted.current&&token===sequence.current)await adopt(value);}
    catch(value){failed(value);}finally{done(abort);if(mounted.current&&token===sequence.current)setBusy(false);}
  }
  useEffect(()=>{
    if(!base)return;const abort=controller();let running=false;
    const check=async()=>{if(document.hidden||running)return;running=true;try{const value=await client.head(base.sceneId,base.sceneRevision,abort.signal);if(!abort.signal.aborted){setUpdate(value.updateAvailable);syncWrite(value);}}catch(value){if(!cancelled(value))failed(value);}finally{running=false;}};
    const timer=window.setInterval(()=>void check(),30000);document.addEventListener('visibilitychange',check);
    return()=>{window.clearInterval(timer);document.removeEventListener('visibilitychange',check);abort.abort();done(abort);};
  },[base?.sceneId,base?.sceneRevision]);
  useEffect(()=>{
    if(!current||!draft)return;
    try{const point=toDisplay(draft.coordinateFrame,current.placement.position,current.placement.height),height=current.placement.height;
      setPosition({name:current.displayName,mode:isLocalScene(draft)?'local':'geographic',x:String(point[0]),z:String(point[2]),
        longitude:isLocalInstance(current)?'':String(current.placement.position.longitude),latitude:isLocalInstance(current)?'':String(current.placement.position.latitude),heading:String(Number(current.placement.headingDeg.toFixed(8))%360),
        heightMode:height.mode==='local_relative'?'relative':height.mode==='terrain_ground'?'ground':'absolute',
        height:String(height.mode==='local_relative'?height.relativeHeightM:height.mode==='terrain_ground'?height.offsetM:height.valueM),source:height.mode==='absolute'?height.sourceNote:''});
    }catch(value){failed(value);}
  },[selected,current,draft?.coordinateFrame]);
  async function commit(next:EditableSceneSnapshot):Promise<boolean>{
    if(!history||!base||!editable)return false;
    const token=++sequence.current,abort=controller();editRequest.current=abort;setError(null);
    try{
      let proposed=next;
      if(!isLocalScene(next)){setBusy(true);const value=await client.check({kind:'validate',sceneId:base.sceneId,expectedSceneRevision:base.sceneRevision,snapshot:next},abort.signal);syncWrite(value);if(!value.capabilities.canWrite)throw new ApiError(403,'SCENE_WRITE_FORBIDDEN');proposed=value.proposedSnapshot;}
      if(!mounted.current||token!==sequence.current)return false;
      setHistory(previous=>previous?commitScene(previous,proposed):previous);return true;
    }catch(value){failed(value);return false;}finally{done(abort);if(editRequest.current===abort)editRequest.current=null;if(mounted.current&&token===sequence.current)setBusy(false);}
  }
  async function save(override?:SceneCheck):Promise<boolean>{
    if(!base||!draft||!canWrite||busy||saveInFlight.current)return false;
    saveInFlight.current=true;const token=++sequence.current,abort=controller();setBusy(true);setError(null);let submitted=false;
    try{
      const key=JSON.stringify([base.sceneId,base.sceneRevision,override?.proposedSnapshot||draft,override?.spatialChange]);
      if(saveRequest.current?.key!==key){
        const checked=override||(!isLocalScene(draft)?await client.check({kind:'validate',sceneId:base.sceneId,expectedSceneRevision:base.sceneRevision,snapshot:draft},abort.signal):null);
        if(checked){syncWrite(checked);if(!checked.capabilities.canWrite)throw new ApiError(403,'SCENE_WRITE_FORBIDDEN');}
        saveRequest.current={key,body:{sceneId:base.sceneId,expectedSceneRevision:base.sceneRevision,clientRequestId:crypto.randomUUID(),snapshot:cloneSnapshot(checked?.proposedSnapshot||draft),
          reviewedEngineering:[],rootBindingChanges:[],...(checked?.spatialChange?{spatialChange:checked.spatialChange}:{})},models:checked?.resourceRefs.models||refs,terrain:override&&override.spatialChange?.kind!=='model'?candidate:terrain};
      }
      const attempt=saveRequest.current;submitted=true;
      const value=await client.save(attempt.body,abort.signal),canonical=attempt.body.snapshot;
      if(!mounted.current||token!==sequence.current)return false;
      const known:SceneOpen={...base,...value,snapshot:cloneSnapshot(canonical),resourceRefs:attempt.models,
        terrainRefs:value.terrainRefs||[],sceneRevision:value.sceneRevision,headRevision:value.headRevision};
      setBase(known);setHistory(sceneHistory(canonical));setTerrain(attempt.terrain);setAnchorResult(null);setCandidate(null);setModal(null);setUpdate(false);setPending(null);setSaveUnknown(false);saveRequest.current=null;
      if(override)setEditing(true);return true;
    }catch(value){if(submitted&&(!(value instanceof ApiError)||value.status>=500))setSaveUnknown(true);
      if(value instanceof ApiError&&value.code==='SPATIAL_PRECHECK_INVALID'){setSaveUnknown(false);saveRequest.current=null;}
      if(value instanceof ApiError&&value.code==='SCENE_CHANGED'){setUpdate(true);setModal('conflict');}failed(value);return false;}
    finally{saveInFlight.current=false;done(abort);if(mounted.current&&token===sequence.current)setBusy(false);}
  }
  async function create(){
    const name=newName.trim();if(!name||name.length>200){setError(new Error(t('invalidName')));return;}
    const token=++sequence.current,abort=controller();setBusy(true);setError(null);
    if(createRequest.current?.name!==name)createRequest.current={name,id:crypto.randomUUID()};
    try{const value=await client.create({displayName:name,clientRequestId:createRequest.current.id},abort.signal);if(mounted.current&&token===sequence.current){await adopt(value);setEditing(true);setModal(null);setNewName('');createRequest.current=null;}}
    catch(value){failed(value);}finally{done(abort);if(mounted.current&&token===sequence.current)setBusy(false);}
  }
  async function place(point:Vector3){
    if(!draft||!base||!pending||!editable)return;
    try{const id=crypto.randomUUID(),next=pending.kind==='model'?placeModel(draft,pending.model,point,terrain,id,base.limits.maxInstances):duplicateAt(draft,pending.sourceId,point,id,base.limits.maxInstances);
      if(await commit(next)){setSelected(id);setPending(null);setLeft('content');}}
    catch(value){failed(value);}
  }
  async function resourceDrop(reference:{modelAssetId:string,modelVersionId:string},point:Vector3){
    if(!editable||!draft||!base)return;const abort=controller(),token=++sequence.current;editRequest.current=abort;setBusy(true);
    try{const value=await client.model(reference.modelAssetId,reference.modelVersionId,abort.signal);if(!mounted.current||token!==sequence.current)return;setHints(prior=>({...prior,[value.modelVersionId]:modelRef(value)}));
      const id=crypto.randomUUID(),next=placeModel(draft,value,point,terrain,id,base.limits.maxInstances);if(await commit(next)){setSelected(id);setLeft('content');}}
    catch(value){failed(value);}finally{done(abort);if(editRequest.current===abort)editRequest.current=null;if(mounted.current&&token===sequence.current)setBusy(false);}
  }
  function changeCurrent(change:(item:SceneModelInstance)=>SceneModelInstance){if(draft&&current&&editable)void commit(updateInstance(draft,change(structuredClone(current))));}
  function selectInstance(id:string|null,locate=false){
    cancelPlacement();setSelected(id);setPreview(null);setSide(null);
    if(id&&!editing)setPersonal(previous=>({...previous,[id]:true}));
    if(locate)setFocus({token:Date.now(),instanceId:id});
  }
  function removeCurrent(){
    if(!draft||!current||!editable||current.positionLocked)return;
    const next=cloneSnapshot(draft);
    if(isLocalScene(next))next.instances=next.instances.filter(item=>item.sceneModelInstanceId!==current.sceneModelInstanceId);
    else next.instances=next.instances.filter(item=>item.sceneModelInstanceId!==current.sceneModelInstanceId);
    void commit(next).then(ok=>{if(ok)setSelected(null);});
  }
  async function applyPosition(){
    if(!current||!draft||!editable)return;
    if(!position.name.trim()||position.name.trim().length>200){setError(new Error(t('invalidName')));return;}
    if(current.positionLocked){await commit(updateInstance(draft,{...current,displayName:position.name.trim()}));return;}
    const inputs=[position.heading,position.height,...(position.mode==='local'?[position.x,position.z]:[position.longitude,position.latitude])];
    if(!inputs.every(finite)){setError(new Error(t('invalidPosition')));return;}
    try{const item=structuredClone(current),heading=((Number(position.heading)%360)+360)%360;
      item.displayName=position.name.trim();item.placement.headingDeg=heading;
      if(isLocalInstance(item)){item.placement.position={mode:'local',xM:Number(position.x),zM:Number(position.z)};item.placement.height={mode:'local_relative',relativeHeightM:Number(position.height)};}
      else if(!isLocalScene(draft)){
        const coordinate=position.mode==='local'?fromDisplay(draft.coordinateFrame,[Number(position.x),0,Number(position.z)]).position:
          {mode:'geographic' as const,longitude:Number(position.longitude),latitude:Number(position.latitude),transformId:draft.coordinateFrame.transformId,frameRevision:draft.coordinateFrame.frameRevision};
        if(coordinate.mode!=='geographic')throw new Error(t('invalidPosition'));item.placement.position=coordinate;
        if(position.heightMode==='absolute'){
          if(draft.coordinateFrame.verticalDatum==='UNKNOWN_RELATIVE'||!position.source.trim())throw new Error(t('sourceRequired'));
          item.placement.height={mode:'absolute',valueM:Number(position.height),verticalDatum:draft.coordinateFrame.verticalDatum,sourceNote:position.source.trim()};
        }else{
          if(!terrain)throw new ApiError(409,'RESOURCE_CHANGED');
          item.placement.height={mode:'terrain_ground',terrainVersionId:terrain.terrainVersionId,terrainSha256:terrain.sha256,sampleLongitude:coordinate.longitude,sampleLatitude:coordinate.latitude,
            sampledHeightM:0,offsetM:Number(position.height),verticalDatum:draft.coordinateFrame.verticalDatum,samplingRule:terrain.report.mesh.placementSamplingRule};
        }
      }
      await commit(updateInstance(draft,item));
    }catch(value){failed(value);}
  }
  function adoptTerrain(value:TerrainVersion){
    if(!draft||!editable)return;
    if(dirty){setError(new Error(t('saveFirst')));return;}
    if(!isLocalScene(draft)){setCandidate(value);setTerrainStrategy('resample_ground');setModal('replaceTerrain');return;}
    const box=value.report.source.samplingCentreCoverageWgs84;
    setCandidate(value);setAnchorResult(null);setAnchor({x:'0',z:'0',longitude:String((box[0]+box[2])/2),latitude:String((box[1]+box[3])/2),heading:'0',offset:'0',strategy:'resample_each_ground'});setModal('anchor');
  }
  async function previewAnchor(){
    if(!base||!draft||!isLocalScene(draft)||!candidate||busy)return;
    if(![anchor.x,anchor.z,anchor.longitude,anchor.latitude,anchor.heading,anchor.offset].every(finite)){setError(new Error(t('invalidPosition')));return;}
    const token=++sequence.current,abort=controller();editRequest.current=abort;setBusy(true);setError(null);
    try{const value=await client.check({kind:'anchor',sceneId:base.sceneId,expectedSceneRevision:base.sceneRevision,snapshot:draft,candidateTerrainVersionId:candidate.terrainVersionId,
      anchor:{localAnchor:[Number(anchor.x),Number(anchor.z)],geographicAnchor:[Number(anchor.longitude),Number(anchor.latitude)],trueNorthHeadingDeg:Number(anchor.heading),anchorHeight:{mode:'terrain_ground',terrainVersionId:candidate.terrainVersionId,offsetM:Number(anchor.offset)},heightStrategy:anchor.strategy}},abort.signal);
      if(mounted.current&&token===sequence.current){syncWrite(value);if(!value.capabilities.canWrite)throw new ApiError(403,'SCENE_WRITE_FORBIDDEN');beforeAnchorView.current=liveView.current;setAnchorResult(value);setLeft('content');setModal(null);setViewCommand({token:Date.now(),view:value.proposedSnapshot.initialView});}}
    catch(value){failed(value);}finally{done(abort);if(editRequest.current===abort)editRequest.current=null;if(mounted.current&&token===sequence.current)setBusy(false);}
  }
  async function previewReplacement(operation:ReplacementOperation){
    if(!base||!draft||!editable)return;
    if(dirty){setError(new Error(t('saveFirst')));return;}
    cancelPlacement();const token=++sequence.current,abort=controller();editRequest.current=abort;setBusy(true);setError(null);
    try{
      const value=await client.replacementCheck({sceneId:base.sceneId,expectedSceneRevision:base.sceneRevision,
        snapshot:cloneSnapshot(draft),...operation},abort.signal);
      if(mounted.current&&token===sequence.current){syncWrite(value);if(!value.capabilities.canWrite)throw new ApiError(403,'SCENE_WRITE_FORBIDDEN');
        beforeAnchorView.current=liveView.current;setAnchorResult(value);setLeft('content');setModal(null);setPreview(null);
        if(liveView.current)setViewCommand({token:Date.now(),view:structuredClone(liveView.current)});
      }
    }catch(value){failed(value);}finally{done(abort);if(editRequest.current===abort)editRequest.current=null;if(mounted.current&&token===sequence.current)setBusy(false);}
  }
  function cancelAnchor(){if(saveInFlight.current||saveUnknown)return;setAnchorResult(null);if(beforeAnchorView.current)setViewCommand({token:Date.now(),view:beforeAnchorView.current});setCandidate(null);}
  const errorText=error instanceof ApiError?failureMessage(error,locale):error instanceof Error?('code' in error&&typeof error.code==='string'?failureMessage(new ApiError(422,error.code),locale):error.message):error?failureMessage(error,locale):'';
  const fields=(keys:('x'|'z'|'longitude'|'latitude'|'heading'|'height')[])=>keys.map(key=><label key={key}><span>{t(key==='height'?(position.heightMode==='relative'?'relativeHeight':position.heightMode==='ground'?'offset':'elevation'):key)}</span><input type="number" step="any" value={position[key]} onChange={event=>setPosition(value=>({...value,[key]:event.target.value}))}/></label>);
  const isAnchor=anchorResult?.spatialChange?.kind==='anchor',viewTerrain=anchorResult&&anchorResult.spatialChange?.kind!=='model'?candidate:terrain;
  return <section className="sw-workspace" aria-label={t('scenes')}>
    {saveUnknown&&<div className="sw-notice" role="status"><span>{t('saveUnknown')}</span><Btn disabled={busy||!canWrite} onClick={()=>void save(anchorResult||undefined)}>{t('retry')}</Btn></div>}
    {errorText&&<div className="sw-notice" role="alert"><span>{errorText}</span><IconBtn label={t('cancel')} onClick={()=>setError(null)}><X size={14}/></IconBtn></div>}
    {!base?<><div className="sw-list-toolbar"><form onSubmit={event=>{event.preventDefault();void readList();}}><Search size={15}/><input aria-label={t('search')} placeholder={t('search')} value={search} onChange={event=>setSearch(event.target.value)}/><Btn disabled={busy} onClick={()=>void readList()}>{t('search')}</Btn></form><Btn primary disabled={busy||!list?.capabilities.canWrite} onClick={()=>setModal('create')}><Plus size={15}/>{t('create')}</Btn></div>
      <div className="sw-scene-list">{!list?<p role="status">{t('loading')}</p>:list.items.length===0?<p>{t('empty')}</p>:<table><thead><tr><th>{t('name')}</th><th>{t('count')}</th><th>{t('updated')}</th><th/></tr></thead><tbody>{list.items.map(row=><tr key={row.sceneId}><td><Layers size={15}/><button type="button" onClick={()=>void open(row.sceneId)} disabled={busy}>{row.displayName}</button></td><td>{row.instanceCount}</td><td>{new Date(row.updatedAt).toLocaleString(locale==='zh'?'zh-CN':'en-GB')}</td><td><Btn disabled={busy} onClick={()=>void open(row.sceneId)}>{t('open')}</Btn></td></tr>)}</tbody></table>}{list?.nextCursor&&<Btn disabled={busy} onClick={()=>void readList(list.nextCursor!)}>{t('more')}</Btn>}</div></>:
      <><div className="sw-editor-toolbar"><IconBtn label={t('back')} disabled={busy} onClick={()=>requestLeave(()=>{setBase(null);setHistory(null);setTerrain(null);setPreview(null);setModal(null);void readList();})}><ArrowLeft size={16}/></IconBtn><strong>{draft?.displayName}</strong><Badge>{unsaved?t('unsaved'):t('saved')}</Badge>{!canWrite&&<Badge>{t('readOnly')}</Badge>}<span className="sw-grow"/>{update&&<Btn disabled={busy} onClick={()=>setModal('conflict')}>{t('updateAvailable')}</Btn>}
        <div className="sw-mode" role="group" aria-label={t('scenes')}><button type="button" aria-pressed={!editing} disabled={busy||!!anchorResult} onClick={()=>{setEditing(false);setPending(null);}}>{t('read')}</button><button type="button" aria-pressed={editing} disabled={!canWrite||busy||!!anchorResult} onClick={()=>{setEditing(true);setPreview(null);}}>{t('edit')}</button></div><Btn primary disabled={!canWrite||!dirty||busy||!!anchorResult} onClick={()=>void save()}><Save size={14}/>{busy?t('saving'):t('save')}</Btn></div>
      {snapshot&&<><div className="sw-mobile-tools"><IconBtn label={t('content')} onClick={()=>setSide(side==='left'?null:'left')}><PanelLeft size={16}/></IconBtn><span className="sw-grow"/><IconBtn label={t('position')} onClick={()=>setSide(side==='right'?null:'right')}><PanelRight size={16}/></IconBtn></div>
      <div className="sw-editor" data-side={side||undefined}><aside className="sw-left"><div className="sw-tabs" role="tablist">{(['content','resources'] as const).map(value=><button type="button" role="tab" disabled={busy||!!anchorResult} aria-selected={left===value} key={value} onClick={()=>setLeft(value)}>{t(value)}</button>)}</div>
        {left==='resources'?<Suspense fallback={<p role="status">{t('loading')}</p>}><ResourcePanel api={api} canPlace={editable} canReplace={editable&&!dirty&&!!current&&!current.positionLocked} replaceTargetVersion={current?.modelVersionId}
          onReplace={value=>{if(current)void previewReplacement({kind:'model',sceneModelInstanceId:current.sceneModelInstanceId,candidateModelVersionId:value.modelVersionId});}} onPlace={value=>{if(!editable)return;setHints(prior=>({...prior,[value.modelVersionId]:modelRef(value)}));setPending({kind:'model',model:value});setPreview(null);setSide(null);}}
          onPreview={value=>{cancelPlacement();setPreview(value);setSide(null);}} onTerrainReady={adoptTerrain} activeTerrainVersion={terrain}/></Suspense>:<div className="sw-content-list"><div className="sw-content-row"><Layers size={15}/><span>{terrain?.displayName||t('noTerrain')}</span>{terrain&&<IconBtn label={terrainVisible?t('hide'):t('show')} onClick={()=>setTerrainVisible(value=>!value)}>{terrainVisible?<Eye size={14}/>:<EyeOff size={14}/>}</IconBtn>}</div>
          {draft?.instances.length===0&&<p className="sw-empty">{t('noContents')}</p>}{draft?.instances.map(item=><div key={item.sceneModelInstanceId} className={`sw-content-row ${selected===item.sceneModelInstanceId?'selected':''}`}><button type="button" className="sw-content-name" onClick={()=>selectInstance(item.sceneModelInstanceId,true)}>{item.displayName}</button>{item.positionLocked&&<LockKeyhole size={12} aria-label={t('locked')}/>}<IconBtn label={(personal[item.sceneModelInstanceId]??item.visible)?t('hide'):t('show')} disabled={busy||!!anchorResult} onClick={()=>editing?void commit(updateInstance(draft,{...item,visible:!item.visible})):setPersonal(value=>({...value,[item.sceneModelInstanceId]:!(value[item.sceneModelInstanceId]??item.visible)}))}>{(editing?item.visible:personal[item.sceneModelInstanceId]??item.visible)?<Eye size={14}/>:<EyeOff size={14}/>}</IconBtn></div>)}
          {!editing&&Object.keys(personal).length>0&&<Btn onClick={()=>setPersonal({})}>{t('resetVisibility')}</Btn>}</div>}
      </aside><div className="sw-viewport"><Suspense fallback={<p role="status">{t('loading')}</p>}><SceneViewport api={api} snapshot={snapshot} modelRefs={refs} terrainVersion={viewTerrain} selectedId={selected} editing={editable} disabled={busy} personalVisibility={editing?{}:personal} terrainVisible={terrainVisible} pendingPlacement={!!pending} previewModel={preview} viewCommand={viewCommand} focusRequest={focus}
        onSelect={id=>selectInstance(id)} onPoint={point=>void place(point)} onMove={async(id,point)=>{try{return !!draft&&await commit(moveInstance(draft,id,point));}catch(error){failed(error);return false;}}} onViewChange={value=>{liveView.current=value;}} onResourceDrop={(reference,point)=>void resourceDrop(reference,point)} onError={failed}/></Suspense>
        {preview&&<div className="sw-floating"><span>{t('preview')} · {preview.displayName}</span><Btn onClick={()=>setPreview(null)}>{t('closePreview')}</Btn></div>}
        {pending&&<div className="sw-floating"><span>{t(pending.kind==='copy'?'copyHint':'placementHint')}</span><IconBtn label={t('cancel')} onClick={cancelPlacement}><X size={15}/></IconBtn></div>}
        {anchorResult&&<div className="sw-floating sw-anchor-result"><strong>{t(isAnchor?'anchorPending':'replacementPreview')}</strong><span>{t(isAnchor?'anchorImpact':'replacementHint')}</span><Btn disabled={busy||saveUnknown} onClick={cancelAnchor}>{t('cancel')}</Btn><Btn primary disabled={busy||!canWrite||saveUnknown} onClick={()=>void save(anchorResult)}>{t(isAnchor?'anchorSave':'confirmReplacement')}</Btn></div>}
      </div><aside className="sw-inspector"><div className="sw-inspector-title"><strong>{current?.displayName||t('position')}</strong>{current&&<IconBtn label={t('locate')} onClick={()=>selectInstance(current.sceneModelInstanceId,true)}><Focus size={15}/></IconBtn>}</div>
        {anchorResult?<ReplacementImpact result={anchorResult} snapshot={draft!}/>:current?<><fieldset disabled={!editable}><label>{t('name')}<input value={position.name} onChange={event=>setPosition(value=>({...value,name:event.target.value}))}/></label></fieldset><fieldset disabled={!editable||current.positionLocked}>
          {!isLocalScene(draft!)&&<label>{t('position')}<select value={position.mode} onChange={event=>setPosition(value=>({...value,mode:event.target.value}))}><option value="geographic">{t('geographic')}</option><option value="local">{t('local')}</option></select></label>}
          <div className="sw-field-pair">{fields(position.mode==='local'?['x','z']:['longitude','latitude'])}</div>{fields(['heading'])}
          {!isLocalScene(draft!)&&<label>{t('height')}<select value={position.heightMode} onChange={event=>setPosition(value=>({...value,heightMode:event.target.value,height:'0'}))}><option value="ground">{t('ground')}</option>{draft!.coordinateFrame.mode==='projected_site'&&draft!.coordinateFrame.verticalDatum!=='UNKNOWN_RELATIVE'&&<option value="absolute">{t('absolute')}</option>}</select></label>}{fields(['height'])}
          {position.heightMode==='absolute'&&<label>{t('heightSource')}<input value={position.source} onChange={event=>setPosition(value=>({...value,source:event.target.value}))}/></label>}
          </fieldset>{editing&&<Btn primary disabled={!editable} onClick={()=>void applyPosition()}><Check size={14}/>{t('apply')}</Btn>}
          <div className="sw-actions">{editing&&<><Btn disabled={!editable} onClick={()=>changeCurrent(item=>({...item,positionLocked:!item.positionLocked}))}>{current.positionLocked?<UnlockKeyhole size={14}/>:<LockKeyhole size={14}/>} {t(current.positionLocked?'unlock':'lock')}</Btn><Btn disabled={!editable} onClick={()=>setPending({kind:'copy',sourceId:current.sceneModelInstanceId})}><Copy size={14}/>{t('duplicate')}</Btn><Btn disabled={!editable||current.positionLocked} onClick={removeCurrent}><Trash2 size={14}/>{t('remove')}</Btn></>}</div>
          <details className="sw-details"><summary>{t('details')}</summary><p>{t('geometryNote')}</p><p>{t('noGeometryBindings')}</p></details>
        </>:<p className="sw-empty">{t('noSelection')}</p>}
        <details className="sw-details"><summary>{t('appearance')}</summary><fieldset disabled={!editable}>{(['background','lighting','terrainMaterial'] as const).map(key=><label key={key}>{t(key==='terrainMaterial'?'material':key)}<select value={draft!.defaults[key]} onChange={event=>{if(draft)void commit({...draft,defaults:{...draft.defaults,[key]:event.target.value}} as EditableSceneSnapshot);}}>{(key==='background'?['plain','sky'] as const:key==='lighting'?['neutral','dusk'] as const:['solid','grass'] as const).map(value=><option key={value} value={value}>{t(value)}</option>)}</select></label>)}</fieldset></details>
      </aside></div>
      <div className="sw-footer"><IconBtn label={t('undo')} disabled={!editable||!history?.past.length} onClick={()=>{if(history)setHistory(undoScene(history));}}><Undo2 size={15}/></IconBtn><IconBtn label={t('redo')} disabled={!editable||!history?.future.length} onClick={()=>{if(history)setHistory(redoScene(history));}}><Redo2 size={15}/></IconBtn><span>{isLocalScene(snapshot!)?t('unanchored'):snapshot!.coordinateFrame.verticalDatum}</span><span className="sw-grow"/><Btn disabled={busy||!!anchorResult} onClick={()=>setFocus({token:Date.now(),instanceId:null})}>{t('fit')}</Btn><Btn disabled={busy||!!anchorResult} onClick={()=>setViewCommand({token:Date.now(),view:draft!.initialView})}>{t('resetView')}</Btn>{editing&&<Btn disabled={!editable||!liveView.current} onClick={()=>{if(draft&&liveView.current)void commit({...draft,initialView:structuredClone(liveView.current)});}}>{t('initialView')}</Btn>}</div>
      </>}
      </>}
    {modal==='create'&&<Modal title={t('create')} description={t('createHint')} onClose={()=>{if(!busy)setModal(null);}}><form onSubmit={event=>{event.preventDefault();void create();}} className="sw-form"><label>{t('createName')}<input value={newName} onChange={event=>setNewName(event.target.value)} maxLength={200} disabled={busy} autoFocus required/></label><Btn primary disabled={busy} onClick={()=>void create()}>{t('create')}</Btn></form></Modal>}
    {modal==='leave'&&<Modal title={t('leave')} description={t(saveUnknown?'leaveUnknown':'leaveHint')} onClose={()=>setModal(null)}><p>{t(saveUnknown?'leaveUnknown':'leaveHint')}</p><div className="sw-actions"><Btn disabled={busy} onClick={()=>setModal(null)}>{t('keepEditing')}</Btn><Btn disabled={busy} onClick={()=>{setModal(null);leave.current?.();leave.current=null;}}>{t('discard')}</Btn><Btn primary disabled={busy||!canWrite} onClick={()=>void save(anchorResult||undefined).then(ok=>{if(ok){leave.current?.();leave.current=null;}})}>{t('saveLeave')}</Btn></div></Modal>}
    {modal==='conflict'&&<Modal title={t('conflict')} description={t('conflictHint')} onClose={()=>setModal(null)}><p>{t('conflictHint')}</p><div className="sw-actions"><Btn onClick={()=>setModal(null)}>{t('keepEditing')}</Btn><Btn primary disabled={busy} onClick={()=>{if(base){setModal(null);void open(base.sceneId);}}}>{t('reload')}</Btn></div></Modal>}
    {modal==='replaceTerrain'&&candidate&&<Modal title={t('replaceTerrain')} description={t('replacementHint')} onClose={()=>{if(!busy){setModal(null);setCandidate(null);}}}><fieldset className="sw-form" disabled={busy}><strong>{candidate.displayName}</strong><label>{t('terrainStrategy')}<select value={terrainStrategy} onChange={event=>setTerrainStrategy(event.target.value as 'keep_height'|'resample_ground')}><option value="resample_ground">{t('resampleGround')}</option><option value="keep_height">{t('keepHeight')}</option></select></label><Btn primary onClick={()=>void previewReplacement({kind:'terrain',candidateTerrainVersionId:candidate.terrainVersionId,strategy:terrainStrategy})}>{t('previewReplacement')}</Btn></fieldset></Modal>}
    {modal==='anchor'&&candidate&&<Modal title={t('anchor')} description={t('anchorHint')} onClose={()=>{if(!busy){setModal(null);setCandidate(null);}}}><p>{t('anchorHint')}</p><fieldset className="sw-form" disabled={busy}><strong>{candidate.displayName}</strong><div className="sw-field-pair">{(['x','z','longitude','latitude','heading','offset'] as const).map(key=><label key={key}>{t(key==='heading'?'anchorHeading':key==='offset'?'offset':key)}<input type="number" step="any" value={anchor[key]} onChange={event=>setAnchor(value=>({...value,[key]:event.target.value}))}/></label>)}</div><label>{t('height')}<select value={anchor.strategy} onChange={event=>setAnchor(value=>({...value,strategy:event.target.value as GeographicAnchor['heightStrategy']}))}><option value="resample_each_ground">{t('resample')}</option><option value="keep_relative_to_anchor">{t('keepRelative')}</option></select></label><Btn primary onClick={()=>void previewAnchor()}>{t('anchorPreview')}</Btn></fieldset></Modal>}
  </section>;
});
