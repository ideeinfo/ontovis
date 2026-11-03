import {replayAlarm,type CockpitAlarmRow,type ReplaySelection} from './cockpitAlarms.ts';
import type {CockpitAlarmTarget} from './cockpitAlarmTarget';
import type {SceneAlarmLabel} from './sceneAlarm';

type Row=CockpitAlarmRow&{target:CockpitAlarmTarget|null};
export type CockpitSpatialAlarm=SceneAlarmLabel&{selection:ReplaySelection;target:CockpitAlarmTarget};
export function cockpitAlarmLabels(rows:Row[],sceneId:string,instanceId:string|null,en=false,focus?:ReplaySelection,resolveComponent?:(target:CockpitAlarmTarget)=>string[]|null|undefined):CockpitSpatialAlarm[]{
 const active=rows.filter(row=>row.target?.sceneId===sceneId&&(!instanceId||row.target.instanceId===instanceId)&&replayAlarm(row)?.state==='active');
 const groups=new Map<string,{level:'asset'|'component';rows:Row[];componentKeys?:string[]}>();
 const components=new Map<string,string[]|null>(),events=new Set<string>();
 for(const row of active){
  const target=row.target!;
  const event=JSON.stringify([target.instanceId,row.dataset.datasetId,row.dataset.datasetRevision]);
  if(events.has(event))continue;
  events.add(event);
  const component=JSON.stringify(['component',target.instanceId,target.entityUid]);
  if(instanceId&&!components.has(component)){
   const keys=resolveComponent?.(target);
   components.set(component,keys?.length?keys:null);
  }
  const keys=instanceId?components.get(component):null,level=keys?'component':'asset';
  const key=keys?component:JSON.stringify(['asset',target.instanceId]);
  const group=groups.get(key)||{level,rows:[],...(keys?{componentKeys:keys}:{})};
  group.rows.push(row);groups.set(key,group);
 }
 return [...groups].map(([id,group])=>{
  const selected=group.level==='component'&&focus?group.rows.find(row=>row.dataset.datasetId===focus.datasetId&&row.dataset.datasetRevision===focus.datasetRevision):null;
  const representative=selected||group.rows.find(row=>replayAlarm(row)?.severity==='critical')||group.rows[0],target=representative.target!;
  const count=group.rows.length,severity=replayAlarm(representative)!.severity;
  return {id,instanceId:target.instanceId,level:group.level,label:group.level==='asset'?target.rootName:target.displayName,
   detail:group.level==='asset'?(en?`${count} alarm${count===1?'':'s'}`:`${count}条报警`):selected||count===1?`${representative.dataset.faultCode} · ${representative.dataset.title}`:(en?`${count} alarms`:`${count}条报警`),
   severity,selection:representative.dataset,target,...(group.componentKeys?{componentKeys:group.componentKeys}:{})};
 });
}
