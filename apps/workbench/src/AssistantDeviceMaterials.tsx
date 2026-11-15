import {useEffect,useState} from 'react';
import {ApiError,cancelled,failureMessage,type WorkbenchApi} from './api';
import {EquipmentMaterials} from './EquipmentMaterials';
import type {MaterialSelection} from './equipmentApi';
import {Btn,Modal} from './Primitives';
import {SceneApi} from './sceneApi';

export type DeviceMaterialsTarget={entityUid:string;entityRevision:string;title:string};

export function AssistantDeviceMaterials({api,target,en,onClose}:{api:WorkbenchApi;target:DeviceMaterialsTarget;en:boolean;onClose:()=>void}){
 const [selection,setSelection]=useState<MaterialSelection|null>(null);
 const [error,setError]=useState<unknown>(null),[attempt,setAttempt]=useState(0);
 useEffect(()=>{
  const abort=new AbortController();
  setSelection(null);setError(null);
  const project=api.project;
  void new SceneApi(api).objectContext(target.entityUid,target.entityRevision,abort.signal).then(value=>{
   if(abort.signal.aborted)return;
   const {item,context,objectRef}=value;
   if(!context||item.objectScope!=='installation'||item.entityUid!==target.entityUid||item.entityRevision!==target.entityRevision
    ||objectRef.projectCode!==project?.projectCode||objectRef.ontobaseConnectionId!==project?.ontobaseConnectionId
    ||context.projectCode!==project?.projectCode||item.installationContextId!==context.installationContextId)
    throw new ApiError(409,'ENGINEERING_CHANGED');
   setSelection({entityUid:item.entityUid,expectedEntityRevision:item.entityRevision,
    installationContextId:context.installationContextId,expectedHierarchyRevision:context.hierarchyRevision});
  }).catch(reason=>{if(!abort.signal.aborted&&!cancelled(reason))setError(reason);});
  return()=>abort.abort();
 },[api,api.epoch,api.revision,target,attempt]);
 return <Modal className="pc-device-resource-dialog ac-source-modal" title={target.title}
  description={en?'Materials applicable to this installation':'查看该安装设备的适用资料'} onClose={onClose}>
  {selection?<EquipmentMaterials api={api} en={en} selection={selection} presentation/>:<div role={error?'alert':'status'}>
   {error?failureMessage(error,en?'en':'zh'):en?'Reading equipment identity…':'正在核对设备身份…'}
   {!!error&&<Btn onClick={()=>setAttempt(value=>value+1)}>{en?'Retry':'重试'}</Btn>}
  </div>}
 </Modal>;
}
