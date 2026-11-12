export type AnalysisTimeZone='Asia/Shanghai'|'UTC';
export type TimeWindow={from:string;to:string};
const offset=(zone:AnalysisTimeZone)=>zone==='Asia/Shanghai'?8*60*60*1000:0;

export function timeWindowInput(utc:string,zone:AnalysisTimeZone){
 const time=Date.parse(utc);return Number.isFinite(time)?new Date(time+offset(zone)).toISOString().slice(0,23).replace(/\.000$/,''):'';
}
/** Only the two supported display zones are accepted; the computer's local zone is never used. */
export function timeWindowUtc(local:string,zone:AnalysisTimeZone):string|null{
 const match=/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,3}))?)?$/.exec(local);
 if(!match||!['Asia/Shanghai','UTC'].includes(zone))return null;
 const [year,month,day,hour,minute,second]=match.slice(1,7).map(value=>Number(value||0)),millisecond=Number((match[7]||'').padEnd(3,'0'));
 const date=new Date(0);date.setUTCFullYear(year,month-1,day);date.setUTCHours(hour,minute,second,millisecond);
 if(year<1||date.getUTCFullYear()!==year||date.getUTCMonth()!==month-1||date.getUTCDate()!==day||date.getUTCHours()!==hour||date.getUTCMinutes()!==minute||date.getUTCSeconds()!==second)return null;
 const utc=new Date(date.getTime()-offset(zone));return utc.getUTCFullYear()>=1?utc.toISOString():null;
}
export function timeWindowLabel(utc:string,zone:AnalysisTimeZone){return timeWindowInput(utc,zone).replace('T',' ').replace(/-/g,'/')||'—';}
export function timeZoneLabel(zone:AnalysisTimeZone,en=false){return zone==='Asia/Shanghai'?(en?'Beijing time · UTC+08:00':'北京时间 · UTC+08:00'):'UTC · UTC+00:00';}
export function timeWindowValue(from:string,to:string,zone:AnalysisTimeZone,limits?:TimeWindow|null):{value:TimeWindow|null;issue:'empty'|'invalid'|'order'|'outside'|null}{
 if(!from||!to)return {value:null,issue:'empty'};
 const start=timeWindowUtc(from,zone),end=timeWindowUtc(to,zone);
 if(!start||!end)return {value:null,issue:'invalid'};
 if(Date.parse(start)>=Date.parse(end))return {value:null,issue:'order'};
 if(limits&&(Date.parse(start)<Date.parse(limits.from)||Date.parse(end)>Date.parse(limits.to)))return {value:null,issue:'outside'};
 return {value:{from:start,to:end},issue:null};
}
export function intersectTimeWindows(windows:readonly TimeWindow[]):TimeWindow|null{
 if(!windows.length||windows.some(value=>!Number.isFinite(Date.parse(value.from))||!Number.isFinite(Date.parse(value.to))))return null;
 return {from:new Date(Math.max(...windows.map(value=>Date.parse(value.from)))).toISOString(),to:new Date(Math.min(...windows.map(value=>Date.parse(value.to)))).toISOString()};
}
