import {cockpitAlarmPresentation,replayKey,type CockpitAlarmRow,type ReplayPositions,type ReplaySelection} from './cockpitAlarms.ts';
import {displayText} from './displayText.ts';
import type {CockpitAlarmTarget} from './cockpitAlarmTarget';
import type {SceneAlarmLabel} from './sceneAlarm';

type Row=CockpitAlarmRow&{target:CockpitAlarmTarget|null};
export type CockpitSpatialAlarm=SceneAlarmLabel&{selection:ReplaySelection;target:CockpitAlarmTarget};
export function cockpitAlarmLabels(rows:Row[],sceneId:string,instanceId:string|null,en=false,focus?:ReplaySelection,resolveComponent?:(target:CockpitAlarmTarget)=>string[]|null|undefined,positions?:ReplayPositions):CockpitSpatialAlarm[]{
 const groups=new Map<string,{level:'asset'|'component';rows:{row:Row;severity:string}[];componentKeys?:string[]}>();
 const components=new Map<string,string[]|null>(),events=new Set<string>();
 for(const row of rows){
  const target=row.target;
  if(!target||target.sceneId!==sceneId||instanceId&&target.instanceId!==instanceId)continue;
  const presentation=cockpitAlarmPresentation(row,en,positions);
  if(presentation.state!=='active'||!presentation.alarm)continue;
  const event=JSON.stringify([target.instanceId,replayKey(row.dataset)]);
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
  group.rows.push({row,severity:presentation.alarm.severity});groups.set(key,group);
 }
 return [...groups].map(([id,group])=>{
  const selected=group.level==='component'&&focus?group.rows.find(({row})=>replayKey(row.dataset)===replayKey(focus)):null;
  const {row:representative,severity}=selected||group.rows.find(row=>row.severity==='critical')||group.rows[0],target=representative.target!;
  const count=group.rows.length;
  return {id,instanceId:target.instanceId,level:group.level,label:group.level==='asset'?target.rootName:target.displayName,
   detail:group.level==='asset'?(en?`${count} alarm${count===1?'':'s'}`:`${count}条报警`):selected||count===1?`${representative.dataset.faultCode} · ${displayText(representative.dataset.title)}`:(en?`${count} alarms`:`${count}条报警`),
   severity,selection:representative.dataset,target,...(group.componentKeys?{componentKeys:group.componentKeys}:{})};
 });
}
