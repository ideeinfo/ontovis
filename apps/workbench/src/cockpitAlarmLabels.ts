import {replayAlarm,type CockpitAlarmRow,type ReplaySelection} from './cockpitAlarms.ts';
import type {CockpitAlarmTarget} from './cockpitAlarmTarget';
import type {SceneAlarmLabel} from './sceneAlarm';

type Row=CockpitAlarmRow&{target:CockpitAlarmTarget|null};
export type CockpitSpatialAlarm=SceneAlarmLabel&{selection:ReplaySelection;target:CockpitAlarmTarget};
export function cockpitAlarmLabels(rows:Row[],sceneId:string,instanceId:string|null,en=false,focus?:ReplaySelection):CockpitSpatialAlarm[]{
 const active=rows.filter(row=>row.target?.sceneId===sceneId&&(!instanceId||row.target.instanceId===instanceId)&&replayAlarm(row)?.state==='active');
 const groups=new Map<string,{level:'asset'|'component';rows:Row[]}>();
 for(const row of active){
  const target=row.target!;
  for(const [key,level] of [[JSON.stringify(['asset',target.instanceId]),'asset'],...(instanceId?[[JSON.stringify(['component',target.instanceId,target.entityUid]),'component']]:[])] as [string,'asset'|'component'][]){
   const group=groups.get(key)||{level,rows:[]};
   if(!group.rows.some(item=>item.dataset.datasetId===row.dataset.datasetId&&item.dataset.datasetRevision===row.dataset.datasetRevision))group.rows.push(row);
   groups.set(key,group);
  }
 }
 return [...groups].map(([id,group])=>{
  const selected=group.level==='component'&&focus?group.rows.find(row=>row.dataset.datasetId===focus.datasetId&&row.dataset.datasetRevision===focus.datasetRevision):null;
  const representative=selected||group.rows.find(row=>replayAlarm(row)?.severity==='critical')||group.rows[0],target=representative.target!;
  const count=group.rows.length,severity=replayAlarm(representative)!.severity;
  return {id,instanceId:target.instanceId,level:group.level,label:group.level==='asset'?target.rootName:target.displayName,
   detail:group.level==='asset'?(en?`${count} alarm${count===1?'':'s'}`:`${count}条报警`):selected||count===1?`${representative.dataset.faultCode} · ${representative.dataset.title}`:(en?`${count} alarms`:`${count}条报警`),
   severity,selection:representative.dataset,target};
 });
}
