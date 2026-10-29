import type {EditableSceneSnapshot} from './sceneTypes';
export interface SceneAlarm {instanceId:string;state:'active'|'cleared'|'pending'|'stale';label:string;target:string}
/** A shared definition never identifies a physical scene instance. */
export function sceneAlarmInstances(snapshot:EditableSceneSnapshot){
 const counts=new Map<string,number>();
 for(const item of snapshot.instances){const ref=item.rootBinding?.objectRef;if(ref){const key=[ref.ontobaseConnectionId,ref.projectCode,ref.entityUid].join('\0');counts.set(key,(counts.get(key)||0)+1);}}
 return snapshot.instances.filter(item=>item.rootBinding&&counts.get([item.rootBinding.objectRef.ontobaseConnectionId,item.rootBinding.objectRef.projectCode,item.rootBinding.objectRef.entityUid].join('\0'))===1);
}
export function alarmLabel(state:SceneAlarm['state'],en=false){return ({active:en?'Active':'报警中',cleared:en?'Cleared':'已恢复',pending:en?'Not occurred':'未发生',stale:en?'Data stale':'数据过期'})[state];}
export function sceneAlarmState(sequence:number|undefined,stale:boolean,alarm:'active'|'cleared'|'pending'):SceneAlarm['state']|null{
 return sequence===undefined||sequence<0?null:stale?'stale':alarm;
}
