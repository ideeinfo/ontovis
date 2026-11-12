import {useEffect,useRef,useState} from 'react';
import {cancelled,type WorkbenchApi} from './api';
import {EquipmentApi,type EquipmentRecord} from './equipmentApi';
import {SceneApi} from './sceneApi';
import type {SceneLocation,SceneLocationRequest} from './sceneEngineeringTypes';
import type {SceneModelInstance,SceneOpen} from './sceneTypes';
import {cockpitInspectionScene,readCockpitLocation,retryCockpitRead} from './cockpitLocation';

export function useCockpitLocation(api:WorkbenchApi,opened:SceneOpen|null,instance:SceneModelInstance|undefined,uid:string,enabled:boolean,attempt:number,expectedEntityRevision?:string){
 const scope=enabled&&opened&&instance?.rootBinding&&uid?JSON.stringify([opened.sceneId,opened.sceneRevision,instance.sceneModelInstanceId,instance.modelVersionId,api.epoch,api.revision]):'';
 const key=scope?JSON.stringify([scope,uid,attempt,expectedEntityRevision]):'';
 const serial=useRef(0),[state,setState]=useState<{key:string;scope:string;value:SceneLocation|null;representation:SceneLocation['representation']|null;error:unknown;token:number}>({key:'',scope:'',value:null,representation:null,error:null,token:0});
 useEffect(()=>{if(!key||!opened||!instance?.rootBinding){setState({key:'',scope:'',value:null,representation:null,error:null,token:serial.current});return;}const abort=new AbortController(),token=++serial.current,client=new SceneApi(api);
  setState(previous=>({key,scope,value:null,representation:previous.scope===scope?previous.representation:null,error:null,token}));
  const request:SceneLocationRequest={sceneId:opened.sceneId,sceneRevision:opened.sceneRevision,selectedObjectRef:{...instance.rootBinding.objectRef,entityUid:uid},contextEpoch:crypto.randomUUID(),representationChoice:{sceneModelInstanceId:instance.sceneModelInstanceId,modelVersionId:instance.modelVersionId},preferDetailed:true};
  void retryCockpitRead(api,()=>readCockpitLocation(client,request,abort.signal,expectedEntityRevision),abort.signal).then(value=>{
   cockpitInspectionScene(opened,instance,value.representation??null);
   if(!abort.signal.aborted)setState({key,scope,value,representation:value.representation??null,error:null,token});
  }).catch(error=>{if(!abort.signal.aborted&&!cancelled(error))setState({key,scope,value:null,representation:null,error,token});});
  return()=>abort.abort();
 },[api,key]);
 return {value:key&&state.key===key?state.value:null,representation:scope&&state.scope===scope?state.representation:null,error:key&&state.key===key?state.error:null,loading:!!key&&(state.key!==key||!state.value&&!state.error),token:state.token};
}

export function useCockpitEquipment(api:WorkbenchApi,opened:SceneOpen|null,instance:SceneModelInstance|undefined,enabled:boolean,attempt=0){
 const key=enabled&&opened&&instance&&opened.sceneRevision===opened.headRevision?JSON.stringify([opened.sceneId,opened.sceneRevision,instance.sceneModelInstanceId,instance.modelVersionId,api.epoch,api.revision]):'';
 const [state,setState]=useState<{key:string;owner:WorkbenchApi;record:EquipmentRecord}|null>(null);
 useEffect(()=>{if(!key||!instance?.rootBinding){setState(null);return;}if(state?.key===key&&state.owner===api)return;const abort=new AbortController(),client=new EquipmentApi(api);
  void retryCockpitRead(api,()=>client.resolve([instance.rootBinding!.objectRef.entityUid],abort.signal),abort.signal).then(result=>{
   const record=result.items.find(item=>item.item.entityUid===instance.rootBinding?.objectRef.entityUid);
   if(record&&!abort.signal.aborted)setState({key,owner:api,record});
  }).catch(()=>{if(!abort.signal.aborted)setState(null);});return()=>abort.abort();
 },[api,key,attempt]);
 return state?.key===key&&state.owner===api?state:null;
}
