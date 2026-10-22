import {useEffect,useMemo,useRef,useState} from 'react';
import {ApiError,cancelled,failureMessage,type WorkbenchApi} from './api';
import {usePreferences} from './Preferences';
import {Btn,Modal} from './Primitives';
import {SceneApi} from './sceneApi';
import {sceneEngineeringText} from './sceneEngineeringMessages';
import type {EngineeringRef} from './sceneEngineeringTypes';
import type {SceneCheck,SceneModelInstance} from './sceneTypes';
import './sceneEngineering.css';

export interface SceneBindingReviewProps {
  api:WorkbenchApi;check:SceneCheck;instances:SceneModelInstance[];previousInstances:SceneModelInstance[];
  busy:boolean;onClose:()=>void;onConfirm:()=>void;
}
export interface BindingReviewRow {
  instanceId:string;instanceName:string;from:EngineeringRef|null;to:EngineeringRef|null;
  removed:{objectRef:EngineeringRef;componentCount:number}[];
}
export interface BindingReviewPlan {rows:BindingReviewRow[];refs:EngineeringRef[]}
export type BindingReviewNames=ReadonlyMap<string,string>;

export function bindingReviewRefKey(ref:EngineeringRef) {
  return JSON.stringify([ref.ontobaseConnectionId,ref.projectCode,ref.entityUid]);
}
function text(value:unknown):value is string {return typeof value==='string'&&value.trim().length>0;}
function validRef(ref:EngineeringRef) {
  return ref&&text(ref.ontobaseConnectionId)&&text(ref.projectCode)&&text(ref.entityUid);
}
function invalid():never {throw new ApiError(502,'SOURCE_UNAVAILABLE');}

/** Prepare display data only; the original server review declarations stay intact. */
export function bindingReviewPlan(check:SceneCheck,instances:SceneModelInstance[],previousInstances:SceneModelInstance[]):BindingReviewPlan {
  const impacts=check.rootBindingImpact??check.validation.rootBindingImpact;
  if(!Array.isArray(impacts)||impacts.length===0||impacts.length>100)invalid();
  const refs=new Map<string,EngineeringRef>(),seen=new Set<string>();let count=0;
  const add=(ref:EngineeringRef|null)=>{
    if(ref===null)return;
    if(!validRef(ref))invalid();
    refs.set(bindingReviewRefKey(ref),{...ref});
  };
  const rows=impacts.map(impact=>{
    if(!text(impact.sceneModelInstanceId)||seen.has(impact.sceneModelInstanceId)
      ||!Array.isArray(impact.removedBindings)||impact.from===null&&impact.to===null)invalid();
    seen.add(impact.sceneModelInstanceId);
    const instance=instances.find(item=>item.sceneModelInstanceId===impact.sceneModelInstanceId)
      ??previousInstances.find(item=>item.sceneModelInstanceId===impact.sceneModelInstanceId);
    if(!instance||!text(instance.displayName))invalid();
    add(impact.from);add(impact.to);
    const removed=impact.removedBindings.map(binding=>{
      if(!Array.isArray(binding.componentKeys)||binding.componentKeys.length===0
        ||binding.componentKeys.some(key=>!text(key))||new Set(binding.componentKeys).size!==binding.componentKeys.length)invalid();
      count+=binding.componentKeys.length;if(count>1000)invalid();
      add(binding.objectRef);
      return {objectRef:{...binding.objectRef},componentCount:binding.componentKeys.length};
    });
    return {instanceId:impact.sceneModelInstanceId,instanceName:instance.displayName,
      from:impact.from?{...impact.from}:null,to:impact.to?{...impact.to}:null,removed};
  });
  return {rows,refs:[...refs.values()]};
}

/** Four bounded reads share a request-local map; no response becomes an approval. */
export async function readBindingReviewNames(api:WorkbenchApi,refs:EngineeringRef[],signal:AbortSignal,
  isCurrent:()=>boolean=()=>true):Promise<BindingReviewNames> {
  const epoch=api.epoch,revision=api.revision,controller=new AbortController();
  const abort=()=>controller.abort();signal.addEventListener('abort',abort,{once:true});
  const guard=()=>{
    if(signal.aborted||controller.signal.aborted||!isCurrent()||api.epoch!==epoch||api.revision!==revision)
      throw new DOMException('Aborted','AbortError');
  };
  try {
    guard();
    const unique=new Map<string,EngineeringRef>();
    for(const ref of refs){if(!validRef(ref))invalid();unique.set(bindingReviewRefKey(ref),ref);}
    if(unique.size>1200)invalid();
    const queue=[...unique.values()],names=new Map<string,string>(),client=new SceneApi(api);let next=0;
    async function worker(){
      while(next<queue.length){
        guard();const ref=queue[next++];
        const value=await client.objectContext(ref.entityUid,undefined,controller.signal);guard();
        if(!value||!validRef(value.objectRef)||bindingReviewRefKey(value.objectRef)!==bindingReviewRefKey(ref)
          ||value.item?.entityUid!==ref.entityUid||!text(value.item.displayName))invalid();
        names.set(bindingReviewRefKey(ref),value.item.displayName);
      }
    }
    await Promise.all(Array.from({length:Math.min(4,queue.length)},worker));guard();return names;
  } finally {signal.removeEventListener('abort',abort);controller.abort();}
}

const labels={
  zh:{previous:'原关联设备',next:'新关联设备',none:'无内部关联需要清除',components:(count:number)=>`${count} 个构件`},
  en:{previous:'Previous equipment',next:'New equipment',none:'No internal links to clear',components:(count:number)=>`${count} component${count===1?'':'s'}`},
};

/** Ready-only details are separate so long engineering names have one renderer. */
export function BindingReviewDetails({plan,names}:{plan:BindingReviewPlan;names:BindingReviewNames}) {
  const {locale}=usePreferences(),t=(key:Parameters<typeof sceneEngineeringText>[1])=>sceneEngineeringText(locale,key),l=labels[locale];
  const name=(ref:EngineeringRef|null)=>ref?names.get(bindingReviewRefKey(ref)):t('unbound');
  return <div className="se-root-review">{plan.rows.map(row=><div key={row.instanceId}>
    <strong>{row.instanceName}</strong>
    <p>{l.previous}：{name(row.from)}</p><p>{l.next}：{name(row.to)}</p>
    <p>{t('removedLinks')}：</p>{row.removed.length===0?<p>{l.none}</p>:<ul>{row.removed.map(link=><li key={bindingReviewRefKey(link.objectRef)}>
      <span>{name(link.objectRef)}</span><span> · {l.components(link.componentCount)}</span>
    </li>)}</ul>}
  </div>)}</div>;
}

export function SceneBindingReview({api,check,instances,previousInstances,busy,onClose,onConfirm}:SceneBindingReviewProps) {
  const {locale}=usePreferences(),t=(key:Parameters<typeof sceneEngineeringText>[1])=>sceneEngineeringText(locale,key);
  const prepared=useMemo(()=>{try{return {plan:bindingReviewPlan(check,instances,previousInstances),error:null};}
    catch(error){return {plan:null,error};}},[check,instances,previousInstances]);
  const identity=useMemo(()=>({}),[api,api.epoch,api.revision,check,instances,previousInstances]);
  const current=useRef(identity);current.current=identity;
  const ticket=useRef(0),abort=useRef<AbortController|null>(null);
  const [retry,setRetry]=useState(0),[state,setState]=useState<{identity:object;names:BindingReviewNames|null;error:unknown;loading:boolean}|null>(null);
  useEffect(()=>{
    const controller=new AbortController();abort.current=controller;const request=++ticket.current;
    const active=()=>current.current===identity&&ticket.current===request&&!controller.signal.aborted;
    if(!prepared.plan){setState({identity,names:null,error:prepared.error,loading:false});return ()=>controller.abort();}
    setState({identity,names:null,error:null,loading:true});
    void readBindingReviewNames(api,prepared.plan.refs,controller.signal,active)
      .then(names=>{if(active())setState({identity,names,error:null,loading:false});})
      .catch(error=>{if(active()&&!cancelled(error))setState({identity,names:null,error,loading:false});});
    return ()=>{controller.abort();if(abort.current===controller)abort.current=null;};
  },[api,identity,prepared,retry]);
  const shown=state?.identity===identity?state:null;
  const ready=!!prepared.plan&&!!shown?.names&&!shown.error&&!shown.loading
    &&prepared.plan.refs.every(ref=>shown.names!.has(bindingReviewRefKey(ref)));
  function close(){if(busy)return;ticket.current++;abort.current?.abort();setState(null);onClose();}
  return <Modal title={t('reviewTitle')} description={t('reviewHint')} onClose={close}>
    <p className="se-note">{t('reviewHint')}</p>
    {!shown||shown.loading?<p className="se-note" role="status">{t('loading')}</p>:shown.error?<>
      <p className="se-state" role="alert">{failureMessage(shown.error,locale)}</p>
      <Btn disabled={busy} onClick={()=>setRetry(value=>value+1)}>{t('retry')}</Btn>
    </>:ready&&prepared.plan&&shown.names?<BindingReviewDetails plan={prepared.plan} names={shown.names}/>:null}
    <div className="se-actions"><Btn disabled={busy} onClick={close}>{t('cancel')}</Btn>
      <Btn primary disabled={busy||!ready} onClick={()=>{if(!busy&&ready)onConfirm();}}>{t('confirmSave')}</Btn></div>
  </Modal>;
}
