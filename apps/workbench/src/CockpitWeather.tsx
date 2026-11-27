import {useEffect,useState} from 'react';
import {cancelled,type WorkbenchApi} from './api';
import {WEATHER_ROOT,weatherUsable,type WeatherView} from './weather';
export function useCockpitWeather(api:WorkbenchApi,sceneId:string,active:boolean){
 const [value,setValue]=useState<WeatherView|null>(null),[error,setError]=useState<unknown>(null),[loading,setLoading]=useState(false),[now,setNow]=useState(Date.now()),[visible,setVisible]=useState(!document.hidden);
 useEffect(()=>{const update=()=>setVisible(!document.hidden);document.addEventListener('visibilitychange',update);return()=>document.removeEventListener('visibilitychange',update);},[]);
 useEffect(()=>{setValue(null);setError(null);if(!active||!visible||!sceneId)return;
  const abort=new AbortController();let timer:ReturnType<typeof setTimeout>;
  const read=async()=>{setLoading(true);try{const result=await api.request<WeatherView>(WEATHER_ROOT+'current',{sceneId},abort.signal);if(!abort.signal.aborted){setValue(result);setError(null);setNow(Date.now());}}
   catch(e){if(!abort.signal.aborted&&!cancelled(e)){setValue(null);setError(e);}}
   finally{if(!abort.signal.aborted){setLoading(false);timer=setTimeout(()=>void read(),300000);}}};
  void read();return()=>{abort.abort();clearTimeout(timer);};
 },[api,api.epoch,api.revision,sceneId,active,visible]);
 useEffect(()=>{if(!active||!visible)return;const timer=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(timer);},[active,visible]);
 return {value,error,loading,now,usable:active&&visible&&weatherUsable(value,now)};
}
export function WeatherEffects({value,enabled,condition:override,paused=false}:{value:WeatherView|null;enabled:boolean;condition?:string;paused?:boolean}){
 const condition=override||value?.forecast?.condition;if(!enabled||!condition)return null;
 return <div className={'wx-effects wx-'+condition} aria-hidden="true" data-paused={paused}><div className="wx-atmosphere"/>{['rain','snow','sleet'].includes(condition)&&Array.from({length:40},(_,i)=><i key={i} style={{left:((i*37)%101)+'%',animationDelay:-(i%13)*.31+'s',animationDuration:(condition==='rain'?.7+(i%4)*.1:4+(i%7)*.6)+'s',opacity:.2+(i%5)*.1}}/>)}</div>;
}
