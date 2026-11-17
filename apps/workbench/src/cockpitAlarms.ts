import {ApiError,cancelled,type WorkbenchApi} from './api.ts';
import {initialReplay,type SimulatedDataset,type SimulationCatalogue,type SimulationDetail} from './simulatedAlarms.ts';

export type ReplaySelection=Pick<SimulatedDataset,'datasetId'|'datasetRevision'>;
export type CockpitAlarmRow={dataset:SimulatedDataset;detail:SimulationDetail|null;error?:unknown};
export const HOME_REPLAY_SECOND=60;
const ROOT='/api/workbench/analysis-sessions/simulation';

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

export function cockpitAlarmPresentation(row:CockpitAlarmRow,en=false){
 const alarm=replayAlarm(row),state=!row.detail?'unavailable':alarm?.state||'pending';
 const status=state==='unavailable'?(en?'Unavailable':'暂不可用'):state==='pending'?(en?'Pending':'未发生'):state==='cleared'?(en?'Cleared':'已恢复'):alarm?.severity==='critical'?(en?'Critical':'严重'):(en?'Warning':'警告');
 return {alarm,state,status,severity:alarm?.severity};
}

export async function readCockpitAlarms(api:Pick<WorkbenchApi,'request'>,signal:AbortSignal):Promise<CockpitAlarmRow[]>{
 const catalogue=await api.request<SimulationCatalogue>(ROOT+'/catalogue',{includeDetail:true},signal);
 signal.throwIfAborted();
 return Promise.all(catalogue.items.map(async dataset=>{
  try{
   const detail=initialReplay(catalogue,dataset)||await api.request<SimulationDetail>(ROOT+'/detail',{datasetId:dataset.datasetId,datasetRevision:dataset.datasetRevision},signal);
   signal.throwIfAborted();
   if(detail.dataset.datasetId!==dataset.datasetId||detail.dataset.datasetRevision!==dataset.datasetRevision||detail.dataset.sourceKind!=='simulated')throw new ApiError(409,'SIMULATION_DATASET_CHANGED');
   return {dataset,detail};
  }catch(error){if(signal.aborted||cancelled(error))throw error;return {dataset,detail:null,error};}
 }));
}
