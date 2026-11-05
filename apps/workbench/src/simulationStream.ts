import {StreamReadError,type ServerEvent} from './eventStream.ts';
import type {SimulationDetail,SimulatedDataset,SimulatedTrend,TrendSample,SimulatedAlarm} from './simulatedAlarms';

export interface SimulationStreamState {
  detail:SimulationDetail|null;cursor:string|null;journal:string;sequence:number;watermark:number;
  receivedAt:number;complete:boolean;
}
export function emptySimulationStream():SimulationStreamState{
  return {detail:null,cursor:null,journal:'',sequence:-1,watermark:-1,receivedAt:0,complete:false};
}
const valid=(condition:unknown):void=>{if(!condition)throw new StreamReadError('STREAM_PROTOCOL_INVALID');};
const stamp=(profile:SimulatedDataset,second:number)=>Date.parse(profile.timeFrom)+second*1000;
function sameDataset(value:SimulatedDataset,profile:SimulatedDataset){
  return value&&value.datasetId===profile.datasetId&&value.datasetRevision===profile.datasetRevision
    &&value.sourceKind==='simulated'&&value.sourceConnectionId===profile.sourceConnectionId
    &&value.timeFrom===profile.timeFrom&&value.timeTo===profile.timeTo;
}
function sample(value:TrendSample,profile:SimulatedDataset,second:number){
  valid(value&&Date.parse(value.sourceTime)===stamp(profile,second)
    &&(value.quality==='good'&&typeof value.value==='number'&&Number.isFinite(value.value)
      ||value.quality==='bad'&&value.value===null));
}
function alarms(value:SimulatedAlarm[],baseline:SimulationDetail,sequence:number,onlyChanges=false){
  const expected=baseline.alarms.filter(row=>onlyChanges?Date.parse(row.sourceTime)===stamp(baseline.dataset,sequence):Date.parse(row.sourceTime)<=stamp(baseline.dataset,sequence));
  valid(Array.isArray(value)&&value.length===expected.length&&value.every((row,index)=>{
    const original=expected[index];
    return row.sourceEventId===original.sourceEventId&&row.sourceRevision===original.sourceRevision
      &&row.sourceTime===original.sourceTime&&row.state===original.state&&row.severity===original.severity;
  }));
}

export function applySimulationEvent(state:SimulationStreamState,event:ServerEvent,baseline:SimulationDetail,revision:string,now=Date.now()):SimulationStreamState{
  let value;try{value=JSON.parse(event.data);}catch{throw new StreamReadError('STREAM_PROTOCOL_INVALID');}
  valid(value&&typeof value==='object'&&value.sessionRevision===revision);
  if(event.event==='ready'){
    valid(sameDataset(value.dataset,baseline.dataset)&&value.sourceMode==='simulated_stream'
      &&/^[a-f0-9]{64}$/.test(value.journalRevision)&&value.accessCheckSeconds===5&&value.staleAfterSeconds===5);
    if(state.journal&&state.journal!==value.journalRevision)throw new StreamReadError('STREAM_SOURCE_CHANGED');
    return {...state,journal:value.journalRevision};
  }
  valid(state.journal&&['snapshot','sample','complete'].includes(event.event)
    &&value.datasetId===baseline.dataset.datasetId&&value.datasetRevision===baseline.dataset.datasetRevision
    &&typeof value.epoch==='string'&&value.epoch.length>0
    &&(!baseline.dataset.epoch||value.epoch===baseline.dataset.epoch)&&value.journalRevision===state.journal
    &&Number.isInteger(value.sequence)&&value.sequence>=0&&value.sequence<=180
    &&Number.isInteger(value.sourceWatermark)&&value.sourceWatermark>=value.sequence&&value.sourceWatermark<=180
    &&Date.parse(value.sourceTime)===stamp(baseline.dataset,value.sequence)&&Number.isSafeInteger(value.deliveredAt));
  if(event.event==='complete'){
    valid(state.sequence===180&&value.sequence===180&&state.detail);
    return {...state,complete:true};
  }
  const cursor=/^s1:([a-f0-9]{64}):([0-9]{13}):([0-9]{1,3})$/.exec(event.id);
  valid(cursor&&cursor[1]===state.journal&&Number(cursor[3])===value.sequence);
  if(state.cursor)valid(cursor![2]===state.cursor.split(':')[2]);
  if(value.sequence<=state.sequence)return state;
  let detail:SimulationDetail;
  if(event.event==='snapshot'){
    valid(!state.detail&&sameDataset(value.detail?.dataset,baseline.dataset)
      &&Array.isArray(value.detail?.trends)&&value.detail.trends.length===baseline.trends.length);
    alarms(value.detail.alarms,baseline,value.sequence);
    detail={dataset:baseline.dataset,alarms:value.detail.alarms,trends:baseline.trends.map((row,index)=>{
      const received:SimulatedTrend=value.detail.trends[index];
      valid(received?.metricId===row.metricId&&received.unit===row.unit
        &&Array.isArray(received.samples)&&received.samples.length===value.sequence+1);
      received.samples.forEach((point,i)=>sample(point,baseline.dataset,i));
      return {...row,samples:received.samples};
    })};
  }else{
    if(!state.detail||value.sequence!==state.sequence+1)throw new StreamReadError('STREAM_SEQUENCE_GAP');
    valid(Array.isArray(value.samples)&&value.samples.length===state.detail.trends.length);
    alarms(value.alarms,baseline,value.sequence,true);
    detail={...state.detail,alarms:[...state.detail.alarms,...value.alarms],trends:state.detail.trends.map((row,index)=>{
      const received=value.samples[index];
      valid(received?.metricId===row.metricId&&received.unit===row.unit);sample(received,baseline.dataset,value.sequence);
      return {...row,samples:[...row.samples,received]};
    })};
  }
  return {detail,cursor:event.id,journal:state.journal,sequence:value.sequence,watermark:value.sourceWatermark,receivedAt:now,complete:false};
}
