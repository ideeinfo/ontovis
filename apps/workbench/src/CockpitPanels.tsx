import {useEffect,useMemo,useRef,useState,type CSSProperties,type ReactNode} from 'react';
import {ChevronUp,ChevronDown,CloudSun,ArrowRight,Box} from 'lucide-react';
import {SceneApi} from './sceneApi';
import type {WorkbenchApi} from './api';
import type {ModelResourceRef} from './sceneTypes';
import type {ModelThumbnailInfo} from './resourceTypes';
import {ModelThumbnail} from './ModelThumbnail';
import {deckCapacity,pageWindow} from './cockpitDisplayState';
import {weatherUsable,type WeatherView} from './weather';

export function PageDeck<T>({items,render,rowHeight=100,minimumRows=1,selectedIndex,en=false,label}:{items:T[];render:(item:T)=>ReactNode;rowHeight?:number;minimumRows?:number;selectedIndex?:number;en?:boolean;label:string}){
 const ref=useRef<HTMLDivElement>(null),[height,setHeight]=useState(rowHeight+42),[page,setPage]=useState(0);
 useEffect(()=>{const node=ref.current;if(!node)return;const observer=new ResizeObserver(([entry])=>setHeight(entry.contentRect.height));observer.observe(node);return()=>observer.disconnect();},[]);
 const capacity=deckCapacity(height,rowHeight,minimumRows),window=pageWindow(items.length,page,capacity.count);
 useEffect(()=>{if(selectedIndex!==undefined&&selectedIndex>=0)setPage(Math.floor(selectedIndex/capacity.count));},[selectedIndex,capacity.count]);
 return <div className="pc-page-deck" ref={ref} aria-label={label} data-compact={minimumRows>1&&capacity.rowHeight<85||undefined} style={minimumRows>1?{'--pc-page-row-height':`${Math.max(1,capacity.rowHeight-10)}px`} as CSSProperties:undefined}><div className="pc-page-items">{items.slice(window.start,window.end).map(render)}</div><footer className="pc-pagination"><span>{items.length?`${window.start+1}–${window.end} / ${items.length}`:'0'}</span><button aria-label={en?'Previous page':'上一页'} disabled={!window.page} onClick={()=>setPage(window.page-1)}><ChevronUp size={16}/></button><button aria-label={en?'Next page':'下一页'} disabled={window.page+1>=window.pages} onClick={()=>setPage(window.page+1)}><ChevronDown size={16}/></button></footer></div>;
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

export function CockpitModelPreview({api,reference,name}:{api:WorkbenchApi;reference:ModelResourceRef;name:string}){
 const client=useMemo(()=>new SceneApi(api),[api]),[thumbnail,setThumbnail]=useState<ModelThumbnailInfo>(),[failed,setFailed]=useState(false);
 useEffect(()=>{const abort=new AbortController();setThumbnail(undefined);setFailed(false);void client.modelThumbnail(reference,abort.signal).then(result=>{if(!abort.signal.aborted)setThumbnail(result.thumbnail);}).catch(()=>{if(!abort.signal.aborted)setFailed(true);});return()=>abort.abort();},[client,api.epoch,api.revision,reference.modelVersionId,reference.contentRevision,reference.sha256]);
 if(failed)return <span className="pc-thumbnail-unavailable"><Box size={32}/><small>—</small></span>;
 return <ModelThumbnail api={client} version={{...reference,thumbnail}} name={name} onStatus={(sha,value)=>{if(sha===reference.sha256)setThumbnail(value);}}/>;
}
