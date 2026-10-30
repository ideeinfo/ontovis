import {useEffect,useRef,useState} from 'react';
import {ApiError,cancelled,type WorkbenchApi} from './api';
import {SceneApi} from './sceneApi';
import type {SceneLocation,SceneLocationRequest} from './sceneEngineeringTypes';
import type {SceneModelInstance,SceneOpen} from './sceneTypes';
import {cockpitLocationCurrent} from './cockpitLocation';

export function useCockpitLocation(api:WorkbenchApi,opened:SceneOpen|null,instance:SceneModelInstance|undefined,uid:string,enabled:boolean,attempt:number){
 const key=enabled&&opened&&instance&&uid?JSON.stringify([opened.sceneId,opened.sceneRevision,instance.sceneModelInstanceId,instance.modelVersionId,uid,api.epoch,api.revision,attempt]):'';
 const serial=useRef(0),[state,setState]=useState<{key:string;value:SceneLocation|null;error:unknown;token:number}>({key:'',value:null,error:null,token:0});
 useEffect(()=>{if(!key||!opened||!instance)return;const abort=new AbortController(),token=++serial.current,client=new SceneApi(api);
  setState({key,value:null,error:null,token});
  void client.objectContext(uid,undefined,abort.signal).then(async context=>{
   if(context.item.entityUid!==uid||context.objectRef.entityUid!==uid)throw new ApiError(409,'ENGINEERING_CHANGED');
   const request:SceneLocationRequest={sceneId:opened.sceneId,sceneRevision:opened.sceneRevision,selectedObjectRef:context.objectRef,contextEpoch:crypto.randomUUID(),representationChoice:{sceneModelInstanceId:instance.sceneModelInstanceId,modelVersionId:instance.modelVersionId}};
   const value=await client.locate(request,abort.signal);
   if(!cockpitLocationCurrent(value,request,context))throw new ApiError(409,'ENGINEERING_CHANGED');
   if(!abort.signal.aborted)setState({key,value,error:null,token});
  }).catch(error=>{if(!abort.signal.aborted&&!cancelled(error))setState({key,value:null,error,token});});
  return()=>abort.abort();
 },[api,key]);
 return {value:key&&state.key===key?state.value:null,error:key&&state.key===key?state.error:null,loading:!!key&&(state.key!==key||!state.value&&!state.error),token:state.token};
}
