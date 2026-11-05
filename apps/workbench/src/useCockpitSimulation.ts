import {useEffect,useMemo,useRef,useState} from 'react';
import {modelSimulation,simulationRequests,type SimulationOverride,type SimulationPreset} from './cockpitSimulation';
import type {MotionRequest} from './simulatedMotion';
import type {SceneOpen} from './sceneTypes';

export function useCockpitSimulation(opened:SceneOpen|null,active:boolean,paused:boolean,visibility:Record<string,boolean>,excludedId:string|null){
 const [preset,setPreset]=useState<SimulationPreset>('balanced'),[running,setRunning]=useState(true),[overrides,setOverrides]=useState<Record<string,SimulationOverride>>({});
 const [generation,setGeneration]=useState(0),[requests,setRequests]=useState<MotionRequest[]>([]);
 const [reduced,setReduced]=useState(()=>matchMedia('(prefers-reduced-motion: reduce)').matches);
 const epoch=useMemo(()=>crypto.randomUUID(),[opened?.sceneId,opened?.sceneRevision,generation]);
 const clock=useRef({last:0,elapsed:0,seq:0});
 useEffect(()=>{clock.current={last:0,elapsed:0,seq:0};},[epoch]);
 useEffect(()=>{
  const media=matchMedia('(prefers-reduced-motion: reduce)');
  const emit=()=>{
   const now=performance.now(),playing=active&&running&&!paused&&!document.hidden&&!media.matches,c=clock.current;
   setReduced(media.matches);
   if(playing&&c.last)c.elapsed+=Math.min(1.1,(now-c.last)/1000);c.last=playing?now:0;
   setRequests(opened&&active&&!document.hidden?simulationRequests(opened.snapshot.instances,opened.resourceRefs,{epoch,seq:++c.seq,now,elapsed:c.elapsed,preset,playing,excludedId,visibility,overrides}):[]);
  };
  emit();const timer=window.setInterval(emit,1000);document.addEventListener('visibilitychange',emit);media.addEventListener('change',emit);
  return()=>{window.clearInterval(timer);document.removeEventListener('visibilitychange',emit);media.removeEventListener('change',emit);clock.current.last=0;};
 },[opened,active,paused,visibility,excludedId,epoch,preset,running,overrides]);
 const reset=()=>{setOverrides({});setPreset('balanced');setRunning(true);setGeneration(v=>v+1);};
 const setModel=(id:string,sha:string,value:Partial<SimulationOverride>)=>setOverrides(previous=>{
  const prior=previous[id]??modelSimulation(id,sha,preset);return {...previous,[id]:{rpm:prior.rpm,yaw:prior.yaw,axes:previous[id]?.axes??false,...value}};
 });
 const choosePreset=(value:SimulationPreset)=>{setOverrides({});setPreset(value);setRunning(true);};
 return {requests,preset,choosePreset,running,setRunning,overrides,setModel,reset,reduced};
}
