import {MOTION_SOURCE,motionProfile,type MotionRequest} from './simulatedMotion.ts';
import type {ModelResourceRef,SceneModelInstance} from './sceneTypes';
export type SimulationPreset='balanced'|'slow'|'stopped';
export type ModelSimulation={rpm:number;yaw:number;phase:number;dynamic:boolean};
export type SimulationOverride={rpm:number;yaw:number;axes:boolean};
export function modelSimulation(instanceId:string,sha256:string,preset:SimulationPreset):ModelSimulation {
 let seed=2166136261;for(const c of instanceId)seed=Math.imul(seed^c.charCodeAt(0),16777619)>>>0;
 const profile=motionProfile(sha256),fraction=(seed%997)/997;
 return {dynamic:!!profile,rpm:!profile||preset==='stopped'?0:Math.round((profile.rpm[0]+fraction*(profile.rpm[1]-profile.rpm[0]))*(preset==='slow'?.45:1)*10)/10,
  yaw:profile?(Math.round(((seed>>>8)%37)-18)+360)%360:0,phase:fraction*Math.PI*2};
}
export function simulationRequests(instances:SceneModelInstance[],refs:ModelResourceRef[],options:{epoch:string;seq:number;now:number;elapsed:number;preset:SimulationPreset;playing:boolean;excludedId?:string|null;visibility:Record<string,boolean>;overrides:Record<string,SimulationOverride>}):MotionRequest[]{
 const byVersion=new Map(refs.map(ref=>[ref.modelVersionId,ref]));
 return instances.flatMap(instance=>{
  const id=instance.sceneModelInstanceId,ref=byVersion.get(instance.modelVersionId);
  if(!ref||id===options.excludedId||!(options.visibility[id]??instance.visible))return [];
  const preset=modelSimulation(id,ref.sha256,options.preset),override=options.overrides[id];if(!preset.dynamic)return [];
  const yaw=override?.yaw??(preset.yaw+(options.preset==='stopped'?0:Math.sin(options.elapsed/90+preset.phase)*4)+360)%360;
  return [{...ref,instanceId:id,epoch:options.epoch,playing:options.playing&&options.preset!=='stopped',axes:override?.axes??false,initialPhase:preset.phase,initialYaw:preset.yaw,yawRate:.6,
   sample:{sourceId:MOTION_SOURCE,epoch:options.epoch,seq:options.seq,issuedAt:options.now,validUntil:options.now+2500,rpm:override?.rpm??preset.rpm,yawDeg:yaw,rpmUnit:'rpm',yawUnit:'deg',quality:'good'}}];
 });
}
