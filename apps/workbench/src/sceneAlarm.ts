import type {EditableSceneSnapshot,Bounds3} from './sceneTypes';
export interface SceneAlarm {instanceId:string;state:'active'|'cleared'|'pending'|'stale';label:string;target:string;bounds?:Bounds3}
export interface SceneAlarmLabel {id:string;instanceId:string;level:'asset'|'component';label:string;detail:string;severity:string;componentKeys?:string[]}
export function layoutAlarmLabels(items:{id:string;x:number;y:number;width:number;height:number}[],width:number,height:number,frame={left:0,right:0}){
 const placed:{id:string;left:number;top:number;width:number;height:number}[]=[];
 const overlaps=(left:number,top:number,w:number,h:number)=>placed.some(row=>left<row.left+row.width+8&&left+w+8>row.left&&top<row.top+row.height+8&&top+h+8>row.top);
 for(const item of items){
  const minimum=width*frame.left+10,maximum=width*(1-frame.right)-item.width-10;
  const left=maximum>=minimum?Math.max(minimum,Math.min(maximum,item.x-item.width/2)):Math.max(10,Math.min(width-item.width-10,item.x-item.width/2));
  let top=Math.max(10,Math.min(height-item.height-10,item.y-item.height-22));
  for(let i=0;i<placed.length+1&&overlaps(left,top,item.width,item.height);i++){
   const next=top-item.height-8;
   if(next>=10)top=next;else {top=Math.min(height-item.height-10,item.y+22);break;}
  }
  placed.push({id:item.id,left,top,width:item.width,height:item.height});
 }
 return placed;
}
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
