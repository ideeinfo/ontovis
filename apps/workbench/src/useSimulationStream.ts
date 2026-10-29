import {useEffect,useRef,useState} from 'react';
import {ApiError,cancelled,type WorkbenchApi} from './api.ts';
import {StreamReadError} from './eventStream.ts';
import {applySimulationEvent,emptySimulationStream,type SimulationStreamState} from './simulationStream.ts';
import type {SimulationDetail} from './simulatedAlarms';

type StreamApi=Pick<WorkbenchApi,'subscribeSimulation'|'revision'|'epoch'>;
export type SimulationConnectionStatus='connecting'|'connected'|'catchup'|'reconnecting'|'stopped'|'complete';
const backoff=[1000,2000,4000,8000,15000];
export function streamDelay(milliseconds:number,signal:AbortSignal){
  return new Promise<void>((resolve,reject)=>{
    const cancel=()=>{clearTimeout(timer);reject(new DOMException('Subscription stopped','AbortError'));};
    const timer=setTimeout(()=>{signal.removeEventListener('abort',cancel);resolve();},milliseconds);
    if(signal.aborted)cancel();else signal.addEventListener('abort',cancel,{once:true});
  });
}

export async function receiveSimulation(api:StreamApi,detail:SimulationDetail,initial:SimulationStreamState,fromSecond:number,
  signal:AbortSignal,onChange:(state:SimulationStreamState,status:SimulationConnectionStatus,error?:unknown)=>void,wait=streamDelay){
  let state=initial,failures=0;
  while(!signal.aborted){
    onChange(state,failures?'reconnecting':'connecting');
    try{
      await api.subscribeSimulation({datasetId:detail.dataset.datasetId,datasetRevision:detail.dataset.datasetRevision,
        ...(state.cursor?{cursor:state.cursor}:{fromSecond})},event=>{
        const next=applySimulationEvent(state,event,detail,api.revision);
        if(next!==state){
          state=next;
          if(event.event==='snapshot'||event.event==='sample')failures=0;
          onChange(state,state.complete?'complete':state.detail?(state.sequence<state.watermark?'catchup':'connected'):'connecting');
        }
      },signal);
      if(state.complete)return;
      throw new ApiError(502,'STREAM_INTERRUPTED');
    }catch(caught){
      if(signal.aborted||cancelled(caught))return;
      const error=caught instanceof StreamReadError?new ApiError(caught.message==='STREAM_SOURCE_CHANGED'?409:502,caught.message):caught;
      const terminal=error instanceof ApiError&&(error.status===401||error.status===403||error.status===409||error.status===422||error.code==='STREAM_SOURCE_CHANGED');
      if(terminal||failures>=backoff.length){onChange(state,'stopped',error);return;}
      onChange(state,'reconnecting',error);
      try{await wait(backoff[failures++],signal);}catch{ return; }
    }
  }
}

interface StreamView {scope:string;state:SimulationStreamState;status:SimulationConnectionStatus;error?:unknown;fromSecond:number}
export function useSimulationStream(api:StreamApi,detail:SimulationDetail|null){
  const scope=`${api.epoch}:${api.revision}:${detail?.dataset.datasetId}:${detail?.dataset.datasetRevision}`;
  const [view,setView]=useState<StreamView|null>(null),[request,setRequest]=useState<{scope:string;resume:boolean;second:number}|null>(null);
  const latest=useRef<StreamView|null>(null),abort=useRef<AbortController|null>(null);
  const [now,setNow]=useState(Date.now());
  const publish=(value:StreamView|null)=>{latest.current=value;setView(value);};
  useEffect(()=>{
    if(latest.current&&latest.current.scope!==scope){abort.current?.abort();publish(null);}
    if(request&&request.scope!==scope)setRequest(null);
  },[scope]);
  useEffect(()=>{
    if(!request||!detail||request.scope!==scope)return;
    const controller=new AbortController();abort.current=controller;
    const epoch=api.epoch,revision=api.revision;
    const initial=request.resume&&latest.current?.scope===scope?latest.current.state:emptySimulationStream();
    void receiveSimulation(api,detail,initial,request.second,controller.signal,(state,status,error)=>{
      if(!controller.signal.aborted&&api.epoch===epoch&&api.revision===revision){
        publish({scope,state,status,error,fromSecond:request.second});setNow(Date.now());
      }
    });
    return()=>controller.abort();
  },[api,api.epoch,api.revision,scope,request,detail]);
  const current=view?.scope===scope?view:null;
  useEffect(()=>{if(!current)return;const timer=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(timer);},[!!current]);
  const start=(second:number,resume=false)=>{
    abort.current?.abort();
    if(!resume)publish({scope,state:emptySimulationStream(),status:'connecting',fromSecond:second});
    setRequest({scope,resume,second});
  };
  const stop=()=>{
    abort.current?.abort();setRequest(null);
    if(latest.current?.scope===scope)publish({...latest.current,status:'stopped',error:undefined});
  };
  const reset=()=>{abort.current?.abort();setRequest(null);publish(null);};
  return {view:current,mode:!!current,start,stop,reset,
    stale:!!current&&current.status!=='complete'&&(!['connected','catchup'].includes(current.status)||now-current.state.receivedAt>5000)};
}
