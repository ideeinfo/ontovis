import {SceneBatchError, sceneOrganization, viewpointIssue} from './sceneOrganization.ts';
import type {EditableSceneSnapshot, SceneRoute, SceneRouteStep, SceneView, SceneViewpoint, Vector3} from './sceneTypes';

export function newRouteStep(viewpoint:SceneViewpoint,stepId:string):SceneRouteStep {
  return {stepId,viewpointId:viewpoint.viewpointId,flightSeconds:1.2,dwellSeconds:viewpoint.kind==='component'?2:3};
}
export type RouteStatus='playing'|'paused'|'complete'|'cancelled';
export interface RouteProgress {status:RouteStatus;index:number;count:number;phase:'flight'|'dwell';elapsedSeconds:number;durationSeconds:number}
type FixedStep=SceneRouteStep&{view:SceneView};
const mix=(a:Vector3,b:Vector3,t:number):Vector3=>[a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t,a[2]+(b[2]-a[2])*t];
function cameraBetween(from:SceneView,to:SceneView,t:number):SceneView {
  const a=from.eye.map((value,i)=>value-from.target[i]) as Vector3,b=to.eye.map((value,i)=>value-to.target[i]) as Vector3;
  const lengthA=Math.hypot(...a),lengthB=Math.hypot(...b),unitA=a.map(value=>value/lengthA) as Vector3,unitB=b.map(value=>value/lengthB) as Vector3;
  const dot=Math.max(-1,Math.min(1,unitA.reduce((sum,value,i)=>sum+value*unitB[i],0)));
  let tangent=unitB.map((value,i)=>value-dot*unitA[i]) as Vector3,length=Math.hypot(...tangent);
  // Opposite view directions need a deterministic arc instead of crossing eye == target.
  if(length<1e-10){const axis=unitA.map(Math.abs).indexOf(Math.min(...unitA.map(Math.abs)));tangent=unitA.map((value,i)=>(i===axis?1:0)-unitA[axis]*value) as Vector3;length=Math.hypot(...tangent);}
  const theta=Math.acos(dot)*t,distance=lengthA+(lengthB-lengthA)*t,target=mix(from.target,to.target,t);
  const eye=target.map((value,i)=>value+distance*(unitA[i]*Math.cos(theta)+tangent[i]/length*Math.sin(theta))) as Vector3;
  return {eye,target};
}

/** A fixed route clock. The caller excludes background time and owns the single RAF. */
export class SceneRoutePlayback {
  readonly routeId:string;
  private readonly steps:FixedStep[];
  private readonly origin:SceneView;
  private readonly reducedMotion:boolean;
  private from:SceneView;
  private index=0;
  private phase:'flight'|'dwell'='flight';
  private elapsed=0;
  private status:RouteStatus='playing';
  private stoppedView:SceneView|null=null;
  constructor(snapshot:EditableSceneSnapshot,route:SceneRoute,origin:SceneView,reducedMotion=false){
    if(!route.steps.length||route.steps.length>32)throw new SceneBatchError('EMPTY_ROUTE');
    this.steps=route.steps.map(step=>{
      const viewpoint=sceneOrganization(snapshot).viewpoints.find(value=>value.viewpointId===step.viewpointId);
      if(!viewpoint||viewpointIssue(snapshot,viewpoint))throw new SceneBatchError('VIEWPOINT_STALE');
      if(!Number.isFinite(step.flightSeconds)||step.flightSeconds<.2||step.flightSeconds>30||
        !Number.isFinite(step.dwellSeconds)||step.dwellSeconds<0||step.dwellSeconds>300)throw new SceneBatchError('INVALID_SCENE_ORGANIZATION');
      return {...structuredClone(step),view:structuredClone(viewpoint.view)};
    });
    this.routeId=route.routeId;this.origin=structuredClone(origin);this.from=structuredClone(origin);this.reducedMotion=reducedMotion;
  }
  get view():SceneView {
    if(this.stoppedView)return structuredClone(this.stoppedView);
    const target=this.steps[this.index].view;
    if(this.phase==='dwell'||this.reducedMotion||this.status==='complete')return structuredClone(target);
    const progress=Math.min(1,this.elapsed/this.steps[this.index].flightSeconds),ease=progress*progress*(3-2*progress);
    return cameraBetween(this.from,target,ease);
  }
  get progress():RouteProgress {
    const step=this.steps[this.index];
    return {status:this.status,index:this.index,count:this.steps.length,phase:this.phase,elapsedSeconds:this.elapsed,
      durationSeconds:this.phase==='flight'?(this.reducedMotion?0:step.flightSeconds):step.dwellSeconds};
  }
  advance(seconds:number):SceneView {
    if(!Number.isFinite(seconds)||seconds<0)throw new SceneBatchError('INVALID_ROUTE_TIME');
    if(this.status!=='playing')return this.view;
    let remaining=seconds;
    while(this.status==='playing'){
      const duration=this.progress.durationSeconds,available=duration-this.elapsed;
      if(remaining<available){this.elapsed+=remaining;break;}
      remaining-=Math.max(0,available);this.elapsed=0;
      if(this.phase==='flight'){this.phase='dwell';continue;}
      if(this.index===this.steps.length-1){this.elapsed=duration;this.status='complete';break;}
      this.from=structuredClone(this.steps[this.index].view);this.index++;this.phase='flight';
    }
    return this.view;
  }
  pause():void {if(this.status==='playing')this.status='paused';}
  resume():void {if(this.status==='paused')this.status='playing';}
  cancel(restore=true):SceneView {
    this.stoppedView=restore?structuredClone(this.origin):this.view;this.status='cancelled';return this.view;
  }
}
