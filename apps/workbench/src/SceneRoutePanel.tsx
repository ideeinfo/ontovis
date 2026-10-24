import {useEffect,useRef,useState} from 'react';
import {ArrowDown,ArrowUp,Pause,Play,Plus,Square,Trash2} from 'lucide-react';
import {usePreferences} from './Preferences';
import {Badge,Btn,IconBtn} from './Primitives';
import {SceneBatchError,putSceneRoute,putSceneViewpoint,removeSceneRoute,removeSceneViewpoint,sceneOrganization,viewpointIssue} from './sceneOrganization';
import {organizationText} from './sceneOrganizationMessages';
import {newRouteStep,SceneRoutePlayback,type RouteProgress} from './sceneRoute';
import type {SceneCameraControl} from './SceneViewport';
import type {EditableSceneSnapshot,SceneRouteStep,SceneView,SceneViewpoint} from './sceneTypes';
import './sceneOrganization.css';

export interface SceneRouteControl {cancel:(restore?:boolean)=>void;manual:()=>void}
interface Props {
  snapshot:EditableSceneSnapshot;identity:string;editable:boolean;canPreview:boolean;captureKind:'component'|'overview';captureInstanceId:string|null;analysisObjectName:string|null;
  camera:{current:SceneCameraControl|null};control:{current:SceneRouteControl|null};
  beforePreview:(signal:AbortSignal)=>Promise<void>;onCommit:(next:EditableSceneSnapshot)=>Promise<boolean>;
  onView:(value:SceneView)=>void;onPlaying:(value:boolean)=>void;onError:(error:unknown)=>void;
}
export function SceneRoutePanel(props:Props) {
  const {locale}=usePreferences(),t=(key:Parameters<typeof organizationText>[1])=>organizationText(locale,key);
  const latest=useRef(props);latest.current=props;const currentLocale=useRef(locale);currentLocale.current=locale;
  const [viewName,setViewName]=useState(''),[routeName,setRouteName]=useState(''),[routeId,setRouteId]=useState(''),[chosenView,setChosenView]=useState('');
  const [progress,setProgress]=useState<RouteProgress|null>(null),[checking,setChecking]=useState(false),[message,setMessage]=useState('');
  const player=useRef<SceneRoutePlayback|null>(null),frame=useRef(0),previous=useRef<number|null>(null),lastProgress=useRef(0);
  const lastView=useRef<SceneView|null>(null);
  const mounted=useRef(false),intent=useRef(0),read=useRef<AbortController|null>(null);
  const data=sceneOrganization(props.snapshot),route=data.routes.find(value=>value.routeId===routeId)??data.routes[0];
  const active=checking||progress?.status==='playing'||progress?.status==='paused';
  function stop(restore=true,manual=false){
    intent.current++;read.current?.abort();read.current=null;cancelAnimationFrame(frame.current);frame.current=0;previous.current=null;
    const value=player.current;player.current=null;
    if(value&&restore)latest.current.camera.current?.setView(value.cancel(true));else value?.cancel(false);
    if(mounted.current){setProgress(null);setChecking(false);if(manual)setMessage(organizationText(currentLocale.current,'manual'));latest.current.onPlaying(false);}
  }
  function schedule(){if(!document.hidden&&player.current?.progress.status==='playing'&&!frame.current)frame.current=requestAnimationFrame(tick);}
  function tick(now:number){
    frame.current=0;const value=player.current;if(!value||document.hidden){previous.current=null;return;}
    const seconds=previous.current===null?0:(now-previous.current)/1000;previous.current=now;
    try{
      const control=latest.current.camera.current;if(!control?.ready())throw new SceneBatchError('CAMERA_UNAVAILABLE');
      const next=value.advance(seconds),last=lastView.current;
      if(!last||next.eye.some((number,i)=>number!==last.eye[i])||next.target.some((number,i)=>number!==last.target[i])){control.setView(next);lastView.current=next;}
      if(value.progress.status==='complete'){player.current=null;setProgress(value.progress);setMessage(organizationText(currentLocale.current,'complete'));latest.current.onPlaying(false);return;}
      if(now-lastProgress.current>=100){lastProgress.current=now;setProgress(value.progress);}
      schedule();
    }catch(error){stop(false);latest.current.onError(error);}
  }
  useEffect(()=>{
    mounted.current=true;
    const control:SceneRouteControl={cancel:restore=>stop(restore),manual:()=>{if(player.current||read.current)stop(false,true);}};
    props.control.current=control;
    const visibility=()=>{previous.current=null;if(document.hidden){cancelAnimationFrame(frame.current);frame.current=0;}else schedule();};
    const escape=(event:KeyboardEvent)=>{if(event.key==='Escape'&&(player.current||read.current))stop(true);};
    document.addEventListener('visibilitychange',visibility);window.addEventListener('keydown',escape);
    return ()=>{mounted.current=false;intent.current++;read.current?.abort();read.current=null;cancelAnimationFrame(frame.current);frame.current=0;player.current=null;
      document.removeEventListener('visibilitychange',visibility);window.removeEventListener('keydown',escape);if(props.control.current===control)props.control.current=null;latest.current.onPlaying(false);};
  },[]);
  useEffect(()=>{stop(false);},[props.identity]);
  async function play(resume=false){
    if(!props.canPreview||!route?.steps.length){props.onError(new SceneBatchError('EMPTY_ROUTE'));return;}
    const ticket=++intent.current,abort=new AbortController();read.current=abort;setChecking(true);setMessage('');props.onPlaying(true);
    try{
      await props.beforePreview(abort.signal);
      if(!mounted.current||ticket!==intent.current||abort.signal.aborted)return;
      const camera=latest.current.camera.current;if(!camera?.ready())throw new SceneBatchError('CAMERA_UNAVAILABLE');
      if(resume&&player.current)player.current.resume();
      else player.current=new SceneRoutePlayback(latest.current.snapshot,route,camera.getView(),matchMedia('(prefers-reduced-motion: reduce)').matches);
      previous.current=null;lastProgress.current=0;lastView.current=null;setProgress(player.current.progress);schedule();
    }catch(error){if(!abort.signal.aborted){stop(false);latest.current.onError(error);}}
    finally{if(read.current===abort)read.current=null;if(mounted.current&&ticket===intent.current){setChecking(false);if(!player.current)props.onPlaying(false);}}
  }
  function capture(existing?:SceneViewpoint){
    try{
      const camera=props.camera.current;if(!camera?.ready())throw new SceneBatchError('CAMERA_UNAVAILABLE');
      const item=props.snapshot.instances.find(value=>value.sceneModelInstanceId===props.captureInstanceId),kind=props.captureKind;
      if(kind==='component'&&!item)throw new SceneBatchError('VIEWPOINT_STALE');
      const viewpoint:SceneViewpoint={viewpointId:existing?.viewpointId??crypto.randomUUID(),displayName:viewName.trim()||existing?.displayName||'',kind,
        view:camera.getView(),frameRevision:props.snapshot.coordinateFrame.frameRevision,
        modelTarget:kind==='component'&&item?{sceneModelInstanceId:item.sceneModelInstanceId,modelVersionId:item.modelVersionId}:null};
      void props.onCommit(putSceneViewpoint(props.snapshot,viewpoint)).then(ok=>{if(ok)setViewName('');});
    }catch(error){props.onError(error);}
  }
  function changeSteps(steps:SceneRouteStep[]){if(route)try{void props.onCommit(putSceneRoute(props.snapshot,{...route,steps}));}catch(error){props.onError(error);}}
  function moveStep(index:number,delta:number){if(!route)return;const next=structuredClone(route.steps);[next[index],next[index+delta]]=[next[index+delta],next[index]];changeSteps(next);}
  return <div className="so-tools" data-testid="scene-route-panel">
    {props.analysisObjectName&&<section className="so-context"><small>{t('analysisObject')}</small><strong>{props.analysisObjectName}</strong></section>}
    <section><h3>{t('viewpoints')}</h3><label>{t('viewName')}<input value={viewName} maxLength={80} disabled={!props.editable||active} onChange={event=>setViewName(event.target.value)}/></label>
      <div className="so-row"><small className="so-note">{t(props.captureKind==='component'?'componentDwell':'overviewDwell')}</small><Btn disabled={!props.editable||active||!viewName.trim()||data.viewpoints.length>=32} onClick={()=>capture()}><Plus size={13}/>{t('capture')}</Btn></div>
      {data.viewpoints.map(viewpoint=>{const issue=viewpointIssue(props.snapshot,viewpoint),inUse=data.routes.some(value=>value.steps.some(step=>step.viewpointId===viewpoint.viewpointId));return <div className="so-row" key={viewpoint.viewpointId}>
        <button type="button" className="so-text" disabled={active||!!issue||!props.canPreview} onClick={()=>props.onView(viewpoint.view)}>{viewpoint.displayName}{issue&&<Badge tone="warning">{t('stale')}</Badge>}<small>{t(viewpoint.kind)}</small></button>
        <Btn disabled={!props.editable||active} onClick={()=>capture(viewpoint)}>{t('recapture')}</Btn><IconBtn label={`${t('deleteView')} ${viewpoint.displayName}`} title={inUse?t('inUse'):undefined} disabled={!props.editable||active||inUse} onClick={()=>{try{void props.onCommit(removeSceneViewpoint(props.snapshot,viewpoint.viewpointId));}catch(error){props.onError(error);}}}><Trash2 size={13}/></IconBtn>
      </div>;})}
    </section>
    <section><h3>{t('routes')}</h3><div className="so-row"><input aria-label={t('routeName')} placeholder={t('routeName')} value={routeName} maxLength={80} disabled={!props.editable||active} onChange={event=>setRouteName(event.target.value)}/><Btn disabled={!props.editable||active||!routeName.trim()||data.routes.length>=8} onClick={()=>{const id=crypto.randomUUID();try{void props.onCommit(putSceneRoute(props.snapshot,{routeId:id,displayName:routeName,steps:[]})).then(ok=>{if(ok){setRouteId(id);setRouteName('');}});}catch(error){props.onError(error);}}}><Plus size={13}/>{t('create')}</Btn></div>
      {route&&<><select aria-label={t('currentRoute')} value={route.routeId} disabled={active} onChange={event=>setRouteId(event.target.value)}>{data.routes.map(value=><option key={value.routeId} value={value.routeId}>{value.displayName}</option>)}</select>
        {route.steps.map((step,index)=><div className={`so-step ${active&&progress?.index===index?'active':''}`} key={step.stepId}><strong>{index+1}. {data.viewpoints.find(viewpoint=>viewpoint.viewpointId===step.viewpointId)?.displayName||t('stale')}</strong>
          <div className="sw-field-pair">{(['flightSeconds','dwellSeconds'] as const).map(key=><label key={key}>{t(key==='flightSeconds'?'flight':'dwell')}<input type="number" step=".1" min={key==='flightSeconds'?0.2:0} max={key==='flightSeconds'?30:300} value={step[key]} disabled={!props.editable||active} onChange={event=>{const value=Number(event.target.value);if(event.target.value.trim()&&Number.isFinite(value)&&value>=(key==='flightSeconds'?0.2:0)&&value<=(key==='flightSeconds'?30:300))changeSteps(route.steps.map(item=>item.stepId===step.stepId?{...item,[key]:value}:item));}}/></label>)}</div>
          <div className="so-actions"><IconBtn label={t('up')} disabled={!props.editable||active||index===0} onClick={()=>moveStep(index,-1)}><ArrowUp size={13}/></IconBtn><IconBtn label={t('down')} disabled={!props.editable||active||index===route.steps.length-1} onClick={()=>moveStep(index,1)}><ArrowDown size={13}/></IconBtn><IconBtn label={t('removeStep')} disabled={!props.editable||active} onClick={()=>changeSteps(route.steps.filter(item=>item.stepId!==step.stepId))}><Trash2 size={13}/></IconBtn></div>
        </div>)}
        <div className="so-row"><select aria-label={t('addView')} value={chosenView} disabled={!props.editable||active} onChange={event=>setChosenView(event.target.value)}><option value="">{t('chooseView')}</option>{data.viewpoints.map(viewpoint=><option key={viewpoint.viewpointId} value={viewpoint.viewpointId}>{viewpoint.displayName}</option>)}</select><IconBtn label={t('addView')} disabled={!props.editable||active||!chosenView||route.steps.length>=32} onClick={()=>{const viewpoint=data.viewpoints.find(value=>value.viewpointId===chosenView);if(viewpoint)changeSteps([...route.steps,newRouteStep(viewpoint,crypto.randomUUID())]);}}><Plus size={13}/></IconBtn></div>
        <div className="so-actions">{!active?<Btn primary disabled={!props.canPreview||!route.steps.length||route.steps.some(step=>{const viewpoint=data.viewpoints.find(value=>value.viewpointId===step.viewpointId);return !viewpoint||!!viewpointIssue(props.snapshot,viewpoint);})} onClick={()=>void play()}><Play size={13}/>{t('preview')}</Btn>:<>
          <Btn disabled={checking} onClick={()=>{if(player.current?.progress.status==='playing'){player.current.pause();cancelAnimationFrame(frame.current);frame.current=0;previous.current=null;setProgress(player.current.progress);}else void play(true);}}>{progress?.status==='paused'?<Play size={13}/>:<Pause size={13}/>} {t(progress?.status==='paused'?'resume':'pause')}</Btn><Btn onClick={()=>stop(true)}><Square size={13}/>{t('cancel')}</Btn></>}
          <Btn disabled={!props.editable||active} onClick={()=>void props.onCommit(removeSceneRoute(props.snapshot,route.routeId))}>{t('deleteRoute')}</Btn></div>
        {checking?<p className="so-progress" role="status">{t('checking')}</p>:active&&progress&&<p className="so-progress" role="status">{progress.index+1}/{progress.count} · {t(progress.status==='paused'?'paused':progress.phase==='flight'?'playingFlight':'playingDwell')} · {progress.elapsedSeconds.toFixed(1)}/{progress.durationSeconds.toFixed(1)} s</p>}
      </>}
      <p className="so-note">{t('routeHint')}</p>{message&&<p className="so-note" role="status">{message}</p>}
    </section>
  </div>;
}
