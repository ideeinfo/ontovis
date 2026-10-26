export interface SimulatedDataset {
  datasetId:string;datasetRevision:string;faultCode:string;title:string;presetCause:string;
  cabinet:string;primaryRds:string;timeFrom:string;timeTo:string;retainedEvidenceGap:string;
  sourceKind:'simulated';sourceConnectionId:string;mode?:'replay';engineeringConfirmation:false;
}
export interface SimulatedAlarm {
  sourceEventId:string;sourceRevision:string;state:'active'|'cleared';severity:string;
  updatedAt:string;sourceTime:string;receivedAt:string;acknowledgement:string;
}
export interface TrendSample {sourceTime:string;value:number|null;quality:string}
export interface SimulatedTrend {metricId:string;unit:string;timeFrom:string;timeTo:string;samples:TrendSample[]}
export interface SimulationDetail {dataset:SimulatedDataset;alarms:SimulatedAlarm[];trends:SimulatedTrend[]}
export interface SimulationCatalogue {items:SimulatedDataset[];sourceKind:'simulated';initialDetail?:SimulationDetail}

export function initialReplay(catalogue:SimulationCatalogue|null,dataset?:SimulatedDataset){
  const detail=catalogue?.initialDetail;
  return detail&&dataset&&detail.dataset.datasetId===dataset.datasetId&&detail.dataset.datasetRevision===dataset.datasetRevision?detail:null;
}

export function alarmAt(value:SimulationDetail,second:number):'pending'|'active'|'cleared'{
  const time=Date.parse(value.dataset.timeFrom)+second*1000;
  return value.alarms.filter(row=>Date.parse(row.updatedAt)<=time)
    .sort((a,b)=>Date.parse(a.updatedAt)-Date.parse(b.updatedAt)).at(-1)?.state||'pending';
}
export function sampleAt(trend:SimulatedTrend,second:number){
  const time=Date.parse(trend.timeFrom)+second*1000;
  return trend.samples.find(row=>Date.parse(row.sourceTime)===time)||null;
}
export function trendDomain(trends:SimulatedTrend[]):[number,number]{
  const values=trends.flatMap(row=>row.samples.filter(point=>point.quality==='good'&&typeof point.value==='number'&&Number.isFinite(point.value)).map(point=>point.value!));
  if(!values.length)return [0,1];
  const low=Math.min(...values),high=Math.max(...values),padding=Math.max((high-low)*.12,.1);
  return [low-padding,high+padding];
}
export function trendSegments(trend:SimulatedTrend,domain:[number,number]){
  const span=Date.parse(trend.timeTo)-Date.parse(trend.timeFrom),height=domain[1]-domain[0];
  if(!(span>0&&height>0))return [];
  const result:string[][]=[];let segment:string[]=[];
  for(const point of trend.samples){
    if(point.quality!=='good'||point.value===null||!Number.isFinite(point.value)){
      if(segment.length)result.push(segment);segment=[];continue;
    }
    segment.push(`${40+(Date.parse(point.sourceTime)-Date.parse(trend.timeFrom))/span*640},${190-(point.value-domain[0])/height*160}`);
  }
  if(segment.length)result.push(segment);
  return result.map(points=>points.join(' '));
}
