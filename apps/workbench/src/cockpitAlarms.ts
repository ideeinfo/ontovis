import {ApiError,cancelled,type WorkbenchApi} from './api.ts';
import {initialReplay,registeredSimulationTarget,type SimulatedAlarm,type SimulatedDataset,type SimulationCatalogue,type SimulationDetail,type SimulationTarget} from './simulatedAlarms.ts';

export type ReplaySelection=Pick<SimulatedDataset,'datasetId'|'datasetRevision'>;
export type ReplayPosition={second:number;stale:boolean};
export type ReplayPositions=Readonly<Record<string,ReplayPosition>>;
export type CockpitAlarmRow={dataset:SimulatedDataset;detail:SimulationDetail|null;registration?:SimulationTarget;error?:unknown};
export type CockpitAlarmPresentation={
 alarm:SimulatedAlarm|null;state:SimulatedAlarm['state']|'pending'|'stale'|'unavailable';
 status:string;severity:string|undefined;second:number;
};
export const HOME_REPLAY_SECOND=60;
const ROOT='/api/workbench/analysis-sessions/simulation';

export function replayKey({datasetId,datasetRevision}:ReplaySelection){return JSON.stringify([datasetId,datasetRevision]);}

export function requireReplaySelection(catalogue:SimulationCatalogue,selection:ReplaySelection){
 const match=catalogue.items.find(row=>row.datasetId===selection.datasetId);
 if(!match||match.datasetRevision!==selection.datasetRevision)throw new ApiError(409,'SIMULATION_DATASET_CHANGED');
 return match;
}

export function replayAlarm(row:CockpitAlarmRow,second=HOME_REPLAY_SECOND){
 if(!row.detail)return null;
 const time=Date.parse(row.dataset.timeFrom)+second*1000;
 return row.detail.alarms.filter(alarm=>Date.parse(alarm.updatedAt)<=time)
  .sort((a,b)=>Date.parse(a.updatedAt)-Date.parse(b.updatedAt)).at(-1)||null;
}

export function cockpitAlarmPresentation(row:CockpitAlarmRow|undefined,en=false,positions?:ReplayPositions):CockpitAlarmPresentation{
 const position=row&&positions?.[replayKey(row.dataset)];
 const alarm=row?replayAlarm(row,position?.second):null;
 const changed=row?.error instanceof ApiError&&row.error.code==='SIMULATION_DATASET_CHANGED';
 const state=changed||position?.stale?'stale':!row?.detail?'unavailable':alarm?.state||'pending';
 const status=state==='stale'?(en?'Data stale':'数据过期'):state==='unavailable'?(en?'Unavailable':'暂无数据'):
  state==='pending'?(en?'Not occurred':'未发生'):state==='cleared'?(en?'Cleared':'已恢复'):
  alarm?.severity==='critical'?(en?'Critical':'严重'):(en?'Warning':'警告');
 return {alarm,state,status,severity:state==='active'?alarm?.severity:undefined,second:position?.second??HOME_REPLAY_SECOND};
}

export async function readCockpitAlarms(api:Pick<WorkbenchApi,'request'>,signal:AbortSignal):Promise<CockpitAlarmRow[]>{
 const catalogue=await api.request<SimulationCatalogue>(ROOT+'/catalogue',{includeDetail:true},signal);
 signal.throwIfAborted();
 return Promise.all(catalogue.items.map(async dataset=>{
  const registration=registeredSimulationTarget(catalogue,dataset);
  try{
   const detail=initialReplay(catalogue,dataset)||await api.request<SimulationDetail>(ROOT+'/detail',{datasetId:dataset.datasetId,datasetRevision:dataset.datasetRevision},signal);
   signal.throwIfAborted();
   if(detail.dataset.datasetId!==dataset.datasetId||detail.dataset.datasetRevision!==dataset.datasetRevision||detail.dataset.sourceKind!=='simulated')throw new ApiError(409,'SIMULATION_DATASET_CHANGED');
   return {dataset,detail,registration};
  }catch(error){if(signal.aborted||cancelled(error))throw error;return {dataset,detail:null,registration,error};}
 }));
}
