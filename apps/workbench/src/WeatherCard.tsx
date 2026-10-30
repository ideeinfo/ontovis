import {CloudSun,CloudRain,CloudSnow,CloudFog,Cloud,Sun,MapPin} from 'lucide-react';
import {weatherMessage,weatherUsable,type WeatherView} from './weather';
export function WeatherCard({value,en=false,loading=false,error,now=Date.now()}:{value:WeatherView|null;en?:boolean;loading?:boolean;error?:unknown;now?:number}){
 const t=(zh:string,eng:string)=>en?eng:zh,f=value?.forecast,usable=weatherUsable(value,now),kind=f?.condition;
 const Icon=kind==='rain'?CloudRain:kind==='snow'||kind==='sleet'?CloudSnow:kind==='fog'?CloudFog:kind==='clear'?Sun:kind==='cloud'?Cloud:CloudSun;
 const date=(s:string)=>new Date(s).toLocaleString(en?'en-GB':'zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
 const n=(v:number|null|undefined)=>v===null||v===undefined?'—':String(v);
 const states={unconfigured:t('尚未配置天气','Weather not configured'),disabled:t('项目天气已停用','Project weather disabled'),unavailable:t('暂无可用预报','Forecast unavailable'),stale:t('预报暂不可用','Forecast not current'),available:t('天气预报','Weather forecast')};
 return <section className="wx-weather-card" aria-label={t('天气预报','Weather forecast')}><header><Icon size={18}/><h3>{loading?t('正在读取天气…','Loading weather…'):states[value?.status||'unavailable']}</h3><span className="wx-label">{t('预报','Forecast')}</span></header>
  {!!error&&<p role="alert">{weatherMessage(error,en)}</p>}{value?.error&&<p role="status">{weatherMessage(value.error,en)}</p>}
  {value?.status==='available'&&!usable&&<p role="status">{t('有效时段已结束，特效已停止。','The valid period ended; effects stopped.')}</p>}
  {value?.point&&<p className="wx-location"><MapPin size={13}/>{value.point.label}</p>}
  {f&&<><div className="wx-temperature"><Icon size={36}/><strong>{n(f.temperatureC)}<small> °C</small></strong></div><dl><dt>{t('10 m 风速','10 m wind')}</dt><dd>{n(f.windSpeedMs)} m/s</dd><dt>{t('风向（来向）','Wind from')}</dt><dd>{n(f.windFromDeg)}°</dd><dt>{f.intervalHours} h {t('时段降水','precipitation')}</dt><dd>{n(f.precipitationMm)} mm</dd></dl><p className="wx-caption">{t('有效','Valid')} {date(f.validFrom)}–{date(f.validTo)}<br/>{t('发布','Issued')} {date(f.updatedAt)}{value.fetchedAt&&<><br/>{t('获取','Fetched')} {date(value.fetchedAt)}</>}</p></>}
  {value?.status==='unconfigured'&&<p>{t('在工作台“数据与报警 → 天气接口”配置此场景查询点。','Configure this scene in Data & alarms → Weather API.')}</p>}
  <footer><a href="https://api.met.no/" target="_blank" rel="noreferrer">MET Norway</a> · <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noreferrer">CC BY 4.0</a><p>{t('按预报时段归一化展示；不是现场实测。','Normalized forecast periods; not on-site observations.')}</p></footer>
 </section>;
}
