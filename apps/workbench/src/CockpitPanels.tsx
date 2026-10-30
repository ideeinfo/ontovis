import {useEffect,useRef,useState,type ReactNode} from 'react';
import {ChevronUp,ChevronDown,CloudSun,ArrowRight} from 'lucide-react';
import {pageWindow} from './cockpitDisplayState';
import {weatherUsable,type WeatherView} from './weather';

export function PageDeck<T>({items,render,rowHeight=100,en=false,label}:{items:T[];render:(item:T)=>ReactNode;rowHeight?:number;en?:boolean;label:string}){
 const ref=useRef<HTMLDivElement>(null),[height,setHeight]=useState(rowHeight+42),[page,setPage]=useState(0);
 useEffect(()=>{const node=ref.current;if(!node)return;const observer=new ResizeObserver(([entry])=>setHeight(entry.contentRect.height));observer.observe(node);return()=>observer.disconnect();},[]);
 const window=pageWindow(items.length,page,Math.max(1,Math.floor((height-42)/rowHeight)));
 return <div className="pc-page-deck" ref={ref} aria-label={label}><div className="pc-page-items">{items.slice(window.start,window.end).map(render)}</div><footer className="pc-pagination"><span>{items.length?`${window.start+1}–${window.end} / ${items.length}`:'0'}</span><button aria-label={en?'Previous page':'上一页'} disabled={!window.page} onClick={()=>setPage(window.page-1)}><ChevronUp size={16}/></button><button aria-label={en?'Next page':'下一页'} disabled={window.page+1>=window.pages} onClick={()=>setPage(window.page+1)}><ChevronDown size={16}/></button></footer></div>;
}
export function DisplaySwitch({label,checked,onChange,disabled=false}:{label:string;checked:boolean;onChange:(value:boolean)=>void;disabled?:boolean}){
 return <label className="pc-switch-row"><span>{label}</span><input type="checkbox" role="switch" checked={checked} disabled={disabled} onChange={e=>onChange(e.target.checked)}/></label>;
}
export function CockpitWeatherSummary({value,now,loading,error,en,onDetails}:{value:WeatherView|null;now:number;loading:boolean;error:unknown;en:boolean;onDetails:()=>void}){
 const usable=weatherUsable(value,now)&&!error,f=usable?value?.forecast:null;
 return <section className="pc-weather-summary"><button className="pc-weather-heading" onClick={onDetails}><CloudSun size={18}/><span>{en?'Weather':'天气'}</span><small>{en?'Forecast':'预报'}</small><ArrowRight size={14}/></button>
 {f?<div className="pc-weather-values"><strong>{f.temperatureC??'—'}<small> °C</small></strong><span>{f.windSpeedMs??'—'} m/s<small>{en?'10 m wind':'10 m 风速'}</small></span></div>:<button className="pc-weather-empty" onClick={onDetails}>{loading?(en?'Loading…':'读取中…'):value?.status==='unconfigured'?(en?'Not configured':'未配置'):en?'Forecast unavailable':'预报暂不可用'}</button>}
 {value?.forecast&&<div className="pc-weather-credit"><a href="https://api.met.no/" target="_blank" rel="noreferrer">MET Norway</a> · <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noreferrer">CC BY 4.0</a></div>}
 </section>;
}
