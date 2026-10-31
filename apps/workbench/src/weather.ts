import {ApiError,failureMessage} from './api.ts';
export interface WeatherPoint {sceneId?:string;latitude:number;longitude:number}
export interface WeatherConfig {enabled:boolean;provider:'met_no';contact:string;refreshMinutes:180|360|720}
export interface WeatherConfigView {revision:number;config:WeatherConfig;savedAt:string|null;accessRevision:string;canManage:boolean;endpoint:string}
export interface WeatherView {status:'available'|'unavailable'|'unconfigured'|'disabled'|'stale';error?:string|null;point?:WeatherPoint;revision:number;preview:boolean;fetchedAt?:string|null;nextFetchAt?:string;
 forecast?:{validFrom:string;validTo:string;updatedAt:string;intervalHours:number;symbol:string|null;condition:'clear'|'cloud'|'rain'|'snow'|'sleet'|'fog'|'unknown';temperatureC:number|null;windSpeedMs:number|null;windFromDeg:number|null;cloudPercent:number|null;precipitationMm:number|null;usable:boolean}|null;
 source:{provider:'met_no';name:string;url:string;license:string;licenseUrl:string;kind:'forecast'};}
export const WEATHER_ROOT='/api/workbench/weather/';
function validContact(contact:string){
 if(!contact||contact.length<5||contact.length>200||/[^\x21-\x7e]/.test(contact))return false;
 if(/^[^@/]+@[^@/]+\.[^@/]+$/.test(contact))return true;
 try{const u=new URL(contact);return u.protocol==='https:'&&!!u.hostname&&!u.username&&!u.password;}catch{return false;}
}
export function weatherProblems(config:WeatherConfig){
 const problems:string[]=[];
 if(!validContact(config.contact))problems.push('contact');
 if(config.refreshMinutes!==undefined&&![180,360,720].includes(config.refreshMinutes))problems.push('refreshMinutes');
 return problems;
}
export function weatherUsable(value:WeatherView|null,now=Date.now()){
 const f=value?.forecast;return value?.status==='available'&&!!f&&f.usable&&f.condition!=='unknown'&&Number.isFinite(now)&&Date.parse(f.validFrom)<=now&&now<Date.parse(f.validTo)&&Date.parse(f.updatedAt)<=now+300000&&Date.parse(f.updatedAt)>=now-43200000;
}
export function weatherMessage(error:unknown,en=false){
 const code=error instanceof ApiError?error.code:typeof error==='string'?error:'';
 const names:Record<string,[string,string]>={WEATHER_CONFIG_CHANGED:['天气配置已有更新，请重新读取后核对修改。','Weather settings changed. Reload and review your changes.'],WEATHER_WRITE_FORBIDDEN:['需要项目管理员权限。','Project administrator permission is required.'],WEATHER_RATE_LIMITED:['来源限流，已暂停外部查询。','The provider is rate limiting requests. Fetching is paused.'],WEATHER_BUSY:['天气查询正在处理，请稍后重试。','A weather query is in progress. Retry shortly.'],WEATHER_INVALID_DATA:['来源数据格式暂不支持。','The provider data format is not supported.'],WEATHER_PROVIDER_UNAVAILABLE:['天气来源暂不可用。','The weather provider is unavailable.'],WEATHER_REDIRECT_REFUSED:['来源地址发生异常跳转。','The provider returned an unexpected redirect.'],WEATHER_OUTDATED:['没有当前时段的可用预报。','No usable forecast for the current period.']};
 return names[code]?.[en?1:0]||failureMessage(error,en?'en':'zh');
}
