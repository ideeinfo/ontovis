import {useEffect,useState} from 'react';
import * as Tabs from '@radix-ui/react-tabs';
import {ApiError,cancelled,failureMessage,type WorkbenchApi} from './api';
import {EquipmentMaterials} from './EquipmentMaterials';
import {EquipmentDrawings} from './EquipmentDrawings';
import type {SceneObjectContext} from './sceneEngineeringTypes';
import {Btn,Modal} from './Primitives';
import {SceneApi} from './sceneApi';
import './cockpitDevice.css';

export type DeviceMaterialsTarget={entityUid:string;entityRevision:string;title:string;showDrawings?:boolean};

export function AssistantDeviceMaterials({api,target,en,onClose}:{api:WorkbenchApi;target:DeviceMaterialsTarget;en:boolean;onClose:()=>void}){
 const [record,setRecord]=useState<SceneObjectContext|null>(null);
 const [error,setError]=useState<unknown>(null),[attempt,setAttempt]=useState(0);
 useEffect(()=>{
  const abort=new AbortController();
  setRecord(null);setError(null);
  const project=api.project;
  void new SceneApi(api).objectContext(target.entityUid,target.entityRevision,abort.signal).then(value=>{
   if(abort.signal.aborted)return;
   const {item,context,objectRef}=value;
   if(!context||item.objectScope!=='installation'||item.entityUid!==target.entityUid||item.entityRevision!==target.entityRevision
    ||objectRef.projectCode!==project?.projectCode||objectRef.ontobaseConnectionId!==project?.ontobaseConnectionId
    ||context.projectCode!==project?.projectCode||item.installationContextId!==context.installationContextId)
    throw new ApiError(409,'ENGINEERING_CHANGED');
   setRecord(value);
  }).catch(reason=>{if(!abort.signal.aborted&&!cancelled(reason))setError(reason);});
  return()=>abort.abort();
 },[api,api.epoch,api.revision,target,attempt]);
 const selection=record?.context?{entityUid:record.item.entityUid,expectedEntityRevision:record.item.entityRevision,
  installationContextId:record.context.installationContextId,expectedHierarchyRevision:record.context.hierarchyRevision}:null;
 const materials=selection&&<EquipmentMaterials api={api} en={en} selection={selection} presentation/>;
 return <Modal className={target.showDrawings?'ac-source-modal':'pc-device-resource-dialog ac-source-modal'} title={target.title}
  description={en?'Materials applicable to this installation':'查看该安装设备的适用资料'} onClose={onClose}>
  {record&&selection?target.showDrawings?<Tabs.Root defaultValue="drawings">
   <Tabs.List className="pc-parameter-tabs" aria-label={en?'Equipment resources':'设备资料'}><Tabs.Trigger value="drawings">{en?'Drawings':'图纸'}</Tabs.Trigger><Tabs.Trigger value="materials">{en?'Applicable materials':'适用资料'}</Tabs.Trigger></Tabs.List>
   <Tabs.Content value="drawings"><EquipmentDrawings api={api} object={record.item} context={record.context} en={en} onReload={()=>setAttempt(value=>value+1)}/></Tabs.Content>
   <Tabs.Content value="materials">{materials}</Tabs.Content>
  </Tabs.Root>:materials:<div role={error?'alert':'status'}>
   {error?failureMessage(error,en?'en':'zh'):en?'Reading equipment identity…':'正在核对设备身份…'}
   {!!error&&<Btn onClick={()=>setAttempt(value=>value+1)}>{en?'Retry':'重试'}</Btn>}
  </div>}
 </Modal>;
}
