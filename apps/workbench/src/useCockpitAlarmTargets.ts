import {useEffect,useMemo,useState} from 'react';
import {ApiError,cancelled,type WorkbenchApi} from './api';
import {EquipmentApi,type EquipmentRecord,type ApplicationBundle} from './equipmentApi';
import {SceneApi} from './sceneApi';
import type {SceneObjectContext} from './sceneEngineeringTypes';
import type {CockpitCatalog} from './cockpitState';
import type {ProjectRef} from './projectTypes';
import type {CockpitAlarmRow} from './cockpitAlarms';
import {cockpitAlarmPlacements,cockpitAlarmTarget} from './cockpitAlarmTarget';

export function useCockpitAlarmTargets(api:WorkbenchApi,catalog:CockpitCatalog|null,project:ProjectRef,rows:CockpitAlarmRow[]|null,active:boolean){
 const placements=useMemo(()=>cockpitAlarmPlacements(catalog,project),[catalog,project]);
 const [choice,setChoice]=useState(''),[attempt,setAttempt]=useState(0);
 const placement=placements.find(row=>row.key===choice)||placements[0];
 const key=active&&placement?JSON.stringify([placement.key,placement.scene.opened?.sceneRevision,api.epoch,api.revision,attempt]):'';
 const [source,setSource]=useState<{key:string;record:EquipmentRecord;context:SceneObjectContext;bundle:ApplicationBundle}|null>(null),[failure,setFailure]=useState<{key:string;error:unknown}|null>(null);
 useEffect(()=>{if(!key||!placement)return;const abort=new AbortController(),equipment=new EquipmentApi(api),uid=placement.instance.rootBinding!.objectRef.entityUid;
  setSource(null);setFailure(null);
  void Promise.all([equipment.resolve([uid],abort.signal),new SceneApi(api).objectContext(uid,undefined,abort.signal)]).then(async([result,context])=>{
   const record=result.items.find(row=>row.item.entityUid===uid);
   if(!record?.adoption)throw new ApiError(409,'ENGINEERING_CHANGED');
   const bundle=await equipment.application(record.adoption.applicationRevisionId,abort.signal);
   if(!abort.signal.aborted)setSource({key,record,context,bundle});
  }).catch(error=>{if(!abort.signal.aborted&&!cancelled(error))setFailure({key,error});});return()=>abort.abort();
 },[api,key]);
 const current=source?.key===key?source:null,error=failure?.key===key?failure.error:null;
 return {placements,placement,choose:setChoice,loading:!!key&&!current&&!error,error,reload:()=>setAttempt(value=>value+1),
  rows:rows?.map(row=>({...row,target:current&&placement?cockpitAlarmTarget(placement,current.record,current.context,current.bundle,row.dataset):null}))||[]};
}
