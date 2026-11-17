import {useEffect,useId,useRef,useState} from 'react';
import {ArrowLeft,Link2,Search} from 'lucide-react';
import {cancelled,failureMessage,type WorkbenchApi} from './api';
import {EquipmentList} from './EquipmentList';
import {usePreferences} from './Preferences';
import {Badge,Btn,Modal} from './Primitives';
import {SceneApi} from './sceneApi';
import {sceneEngineeringText} from './sceneEngineeringMessages';
import {pendingComponentPick,type SceneComponentPickRequest} from './sceneComponentPick';
import type {EngineeringRef,SceneComponentBinding,SceneObjectContext,SceneRootBinding} from './sceneEngineeringTypes';
import type {ProjectModelComponent} from './resourceTypes';
import './sceneEngineering.css';

export interface SceneInstanceLinksProps {
  api:WorkbenchApi;instanceId:string;modelVersionId:string;root:SceneObjectContext|null;rootBinding:SceneRootBinding|null;
  rootReading?:boolean;
  componentBindings:SceneComponentBinding[];components:ProjectModelComponent[];
  selectedObject:SceneObjectContext|null;internal:boolean;readOnly?:boolean;disabled?:boolean;
  pickedComponent?:SceneComponentPickRequest|null;
  onChooseRoot:(selection:SceneObjectContext|null)=>Promise<void>;
  onEnterInternal:()=>void;onReturnToScene:()=>void;
  onBindComponents:(selection:SceneObjectContext,keys:string[])=>Promise<void>;
  sharedConfiguration?:{displayName:string;configurationRevision:string};onConfigure?:()=>void;
}

function sameRef(first:EngineeringRef,second:EngineeringRef) {
  return first.entityUid===second.entityUid&&first.projectCode===second.projectCode
    &&first.ontobaseConnectionId===second.ontobaseConnectionId;
}
function linkable(value:SceneObjectContext|null) {
  return !!value&&value.item.objectScope==='installation'&&!!value.context&&value.bindingEligible
    &&!!value.expectation&&value.item.installationContextId===value.context.installationContextId;
}
function inEquipment(root:SceneObjectContext|null,selected:SceneObjectContext|null) {
  return !!root&&!!selected&&!!root.context&&!!selected.context
    &&root.context.installationContextId===selected.context.installationContextId
    &&root.objectRef.projectCode===selected.objectRef.projectCode
    &&root.objectRef.ontobaseConnectionId===selected.objectRef.ontobaseConnectionId
    &&(sameRef(root.objectRef,selected.objectRef)||selected.ancestors.path.some(row=>row.object.entityUid===root.item.entityUid));
}

/** Association callbacks change a parent-owned draft; this component never saves. */
export function SceneInstanceLinks(props:SceneInstanceLinksProps) {
  const {api,instanceId,modelVersionId,root,rootBinding,componentBindings,components,selectedObject,internal,rootReading=false,readOnly=false,disabled=false,pickedComponent}=props;
  const {locale}=usePreferences(),t=(key:Parameters<typeof sceneEngineeringText>[1])=>sceneEngineeringText(locale,key),id=useId();
  const latest=useRef(props);latest.current=props;
  const alive=useRef(true),intent=useRef(0),readAbort=useRef<AbortController|null>(null);
  const [choosing,setChoosing]=useState(false),[candidate,setCandidate]=useState<SceneObjectContext|null>(null);
  const [query,setQuery]=useState(''),[settled,setSettled]=useState(''),[reading,setReading]=useState(false);
  const [working,setWorking]=useState(false),[error,setError]=useState<unknown>(null);
  const lastPick=useRef(0),[pickOccupied,setPickOccupied]=useState(false);
  const own=selectedObject?componentBindings.find(value=>sameRef(value.objectRef,selectedObject.objectRef))?.componentKeys||[]:[];
  const [keys,setKeys]=useState<string[]>(()=>[...own]);
  const selectionIdentity=JSON.stringify([api.epoch,api.revision,instanceId,modelVersionId,selectedObject?.objectRef,selectedObject?.item.entityRevision,
    selectedObject?.context?.hierarchyRevision,own,components.map(value=>value.componentKey)]);
  const objectIdentity=JSON.stringify([instanceId,selectedObject?.objectRef,selectedObject?.item.entityRevision,selectedObject?.context?.hierarchyRevision]);
  useEffect(()=>{setKeys([...own]);setPickOccupied(false);},[selectionIdentity]);
  useEffect(()=>{const timer=window.setTimeout(()=>setSettled(query.trim()),250);return ()=>clearTimeout(timer);},[query]);
  useEffect(()=>{
    alive.current=true;intent.current++;readAbort.current?.abort();readAbort.current=null;
    setChoosing(false);setCandidate(null);setReading(false);setWorking(false);setError(null);
    return ()=>{alive.current=false;intent.current++;readAbort.current?.abort();readAbort.current=null;};
  },[api,api.epoch,api.revision,instanceId]);
  useEffect(()=>{if(readOnly||disabled){intent.current++;readAbort.current?.abort();setReading(false);setWorking(false);setChoosing(false);setCandidate(null);}},[readOnly,disabled]);
  useEffect(()=>{intent.current++;readAbort.current?.abort();setReading(false);setWorking(false);setError(null);setChoosing(false);setCandidate(null);},[objectIdentity]);
  const active=(ticket:number,epoch:number,revision:string)=>alive.current&&intent.current===ticket
    &&api.epoch===epoch&&api.revision===revision&&latest.current.instanceId===instanceId;
  function closePicker(){intent.current++;readAbort.current?.abort();readAbort.current=null;setChoosing(false);setCandidate(null);setReading(false);setError(null);}
  function openPicker(){intent.current++;readAbort.current?.abort();setError(null);setCandidate(null);setQuery('');setSettled('');setChoosing(true);}
  async function readCandidate(uid:string){
    readAbort.current?.abort();const controller=new AbortController();readAbort.current=controller;
    const ticket=++intent.current,epoch=api.epoch,revision=api.revision;setCandidate(null);setReading(true);setError(null);
    try{const value=await new SceneApi(api).objectContext(uid,undefined,controller.signal);
      if(active(ticket,epoch,revision)&&!controller.signal.aborted)setCandidate(value);
    }catch(value){if(active(ticket,epoch,revision)&&!controller.signal.aborted&&!cancelled(value))setError(value);}
    finally{if(active(ticket,epoch,revision)&&!controller.signal.aborted)setReading(false);}
  }
  async function changeRoot(value:SceneObjectContext|null){
    if(readOnly||disabled||working||value&&!linkable(value))return;
    const ticket=++intent.current,epoch=api.epoch,revision=api.revision;readAbort.current?.abort();setWorking(true);setError(null);
    try{await latest.current.onChooseRoot(value);if(active(ticket,epoch,revision)){setChoosing(false);setCandidate(null);}}
    catch(value){if(active(ticket,epoch,revision)&&!cancelled(value))setError(value);}
    finally{if(active(ticket,epoch,revision))setWorking(false);}
  }
  const validRoot=!rootReading&&!!root&&!!rootBinding&&sameRef(root.objectRef,rootBinding.objectRef);
  const inside=inEquipment(validRoot?root:null,selectedObject);
  const canBind=validRoot&&linkable(root)&&linkable(selectedObject)&&inside;
  useEffect(()=>{
    const outcome=pendingComponentPick(pickedComponent,{instanceId,modelVersionId,selectedObject,components,componentBindings,
      enabled:internal&&canBind&&!readOnly&&!disabled&&!working&&!props.sharedConfiguration,lastToken:lastPick.current});
    if(pickedComponent&&Number.isSafeInteger(pickedComponent.token))lastPick.current=Math.max(lastPick.current,pickedComponent.token);
    if(outcome.status==='selected'){setKeys(outcome.keys);setPickOccupied(false);setError(null);}
    else if(outcome.status==='occupied')setPickOccupied(true);
  },[pickedComponent,instanceId,modelVersionId,objectIdentity,selectionIdentity,internal,canBind,readOnly,disabled,working]);
  const owners=(key:string)=>componentBindings.some(value=>value.componentKeys.includes(key)
    &&(!selectedObject||!sameRef(value.objectRef,selectedObject.objectRef)));
  const missing=own.some(key=>!components.some(component=>component.componentKey===key));
  const collides=keys.some(owners);
  const changed=JSON.stringify([...keys].sort())!==JSON.stringify([...own].sort());
  async function bind(nextKeys:string[]){
    if(!selectedObject||!canBind||readOnly||disabled||working||nextKeys.some(owners))return;
    const selection=selectedObject,ticket=++intent.current,epoch=api.epoch,revision=api.revision;
    setWorking(true);setError(null);
    try{await latest.current.onBindComponents(selection,[...nextKeys].sort());}
    catch(value){if(active(ticket,epoch,revision)&&!cancelled(value))setError(value);}
    finally{if(active(ticket,epoch,revision))setWorking(false);}
  }
  const blocked=readOnly||disabled||working;
  if(props.sharedConfiguration&&internal)return <section className="se-links"><Btn onClick={props.onReturnToScene}><ArrowLeft size={14}/>{t('returnToScene')}</Btn><strong>{props.sharedConfiguration.displayName}</strong>
    <p className="se-note">{locale==='zh'?'内部构件共用项目型号配置。':'Internal components use the shared project configuration.'}</p>
    {selectedObject&&<p>{selectedObject.item.displayName}</p>}<Btn disabled={disabled||!props.onConfigure} onClick={props.onConfigure}>{locale==='zh'?'在设备层级配置':'Configure in equipment hierarchy'}</Btn></section>;
  return <section className="se-links" aria-label={t('deviceLink')}>
    <div><div className="se-link-title"><span>{t('deviceLink')}</span></div>
      <strong>{validRoot?root.item.displayName:rootBinding?t(rootReading?'loading':'unavailable'):t('unbound')}</strong>
      {!internal&&validRoot&&<div className="se-link-status"><Badge>{t(root.item.reviewStatus==='confirmed'?'objectConfirmed':'objectUnreviewed')}</Badge>
        {root.context?.purpose==='demonstration'&&<Badge tone="warning">{t('demonstration')}</Badge>}</div>}
    </div>
    {!internal?<><div className="se-actions"><Btn disabled={blocked} onClick={openPicker}><Link2 size={14}/>{t(rootBinding?'changeDevice':'chooseDevice')}</Btn>
      {rootBinding&&<Btn disabled={blocked} onClick={()=>void changeRoot(null)}>{t('clearDevice')}</Btn>}</div>
      <Btn disabled={disabled||!validRoot||!root.context} onClick={props.onEnterInternal}>{props.sharedConfiguration?(locale==='zh'?'查看共享构件配置':'View shared component configuration'):t('enterInternal')}</Btn></>:
      <><Btn disabled={disabled} onClick={props.onReturnToScene}><ArrowLeft size={14}/>{t('returnToScene')}</Btn>
      {!selectedObject?<p className="se-state">{t('noSelection')}</p>:<>
        {!inside?<p className="se-state" role="status">{t('outsideRoot')}</p>:!linkable(selectedObject)?<p className="se-state" role="status">{t(selectedObject.item.objectScope==='installation'?'incomplete':'readOnlyObject')}</p>:null}
        {own.length===0&&(!rootBinding||!sameRef(rootBinding.objectRef,selectedObject.objectRef))&&<p className="se-note">{t('noGeometry')}</p>}
        {missing&&<p className="se-state" role="alert">{t('missingComponents')}</p>}
        {pickOccupied&&<p className="se-state" role="alert">{t('usedElsewhere')}</p>}
        <fieldset className="se-component-list" disabled={blocked||!canBind}><legend>{t('components')}</legend>
          {components.map((component,index)=>{const elsewhere=owners(component.componentKey);return <label className="se-component" key={component.componentKey} htmlFor={`${id}-${index}`}>
            <input id={`${id}-${index}`} type="checkbox" checked={keys.includes(component.componentKey)} disabled={elsewhere}
              onChange={event=>{setPickOccupied(false);setKeys(value=>event.target.checked?[...new Set([...value,component.componentKey])]:value.filter(key=>key!==component.componentKey));}}/>
            <span><span className="se-component-name">{component.displayName}</span><small>{t(component.geometryQuality==='proxy_schematic'?'proxyGeometry':'sourceGeometry')}</small>{elsewhere&&<small>{t('usedElsewhere')}</small>}</span>
          </label>;})}
          {components.length===0&&<p className="se-note">{t('noComponents')}</p>}
        </fieldset>
        <div className="se-actions"><Btn primary disabled={blocked||!canBind||!changed||missing||collides} onClick={()=>void bind(keys)}>{t(working?'working':'applyComponents')}</Btn>
          {own.length>0&&<Btn disabled={blocked||!canBind} onClick={()=>void bind([])}>{t('clearComponents')}</Btn>}</div>
      </>}
      </>}
    {!!error&&<p className="se-state" role="alert">{failureMessage(error,locale)}</p>}
    {choosing&&<Modal title={t('chooseRootTitle')} description={t('chooseRootHint')} onClose={()=>{if(!working)closePicker();}}><div className="se-device-picker">
      <label className="se-search"><Search size={14}/><input value={query} disabled={working} aria-label={t('search')} placeholder={t('search')} onChange={event=>{intent.current++;readAbort.current?.abort();setCandidate(null);setReading(false);setQuery(event.target.value);}}/></label>
      <fieldset className="se-picker-catalog" disabled={working}>{query.trim()!==settled?<p className="se-state" role="status">{t('loading')}</p>:
        <EquipmentList key={`${api.epoch}:${api.revision}:${settled}`} api={api} query={settled} selected={candidate?.item.entityUid||''} onSelect={uid=>void readCandidate(uid)}/>}</fieldset>
      {reading&&<p className="se-state" role="status">{t('loading')}</p>}
      {candidate&&<div className="se-candidate"><strong>{candidate.item.displayName}</strong>{!linkable(candidate)&&<p className="se-note">{t(candidate.item.objectScope==='installation'?'incomplete':'readOnlyObject')}</p>}</div>}
      {!!error&&<p className="se-state" role="alert">{failureMessage(error,locale)}</p>}
      <div className="se-actions"><Btn disabled={working} onClick={closePicker}>{t('cancel')}</Btn><Btn primary disabled={blocked||reading||!linkable(candidate)||!!candidate&&!!rootBinding&&sameRef(candidate.objectRef,rootBinding.objectRef)} onClick={()=>void changeRoot(candidate)}>{t(working?'working':'useDevice')}</Btn></div>
    </div></Modal>}
  </section>;
}
