import {cloudDefaults,environmentPreset,type SceneEnvironmentV1} from './sceneEnvironment.ts';
import {weatherEnvironment} from './weatherEnvironment.ts';
import type {WeatherView} from './weather';
export type CockpitLight='scene'|'day'|'dusk';
export type CockpitWeather='forecast'|'off'|'clear'|'cloud'|'rain'|'snow'|'fog';
export function pageWindow(total:number,page:number,size:number){
 const count=Math.max(1,Math.floor(size)||1),pages=Math.max(1,Math.ceil(total/count)),current=Math.max(0,Math.min(pages-1,Math.floor(page)||0));
 return {page:current,pages,start:current*count,end:Math.min(total,(current+1)*count)};
}
export function deckCapacity(height:number,rowHeight:number,minimumRows=1){
 const available=Math.max(1,height-42),minimum=Math.max(1,Math.floor(minimumRows));
 const count=Math.max(minimum,Math.floor(available/rowHeight));
 return {count,rowHeight:Math.min(rowHeight,available/count)};
}
/** Presentation preferences never modify the saved scene or forecast. */
export function presentationEnvironment(base:SceneEnvironmentV1|null|undefined,forecast:WeatherView|null,light:CockpitLight,weather:CockpitWeather):{value:SceneEnvironmentV1}|null{
 if(light==='scene'&&(weather==='off'||weather==='forecast'&&!forecast))return null;
 const value=weather==='forecast'&&forecast?.forecast?weatherEnvironment(base,forecast):structuredClone(base||environmentPreset('land-day-v1'));
 if(weather!=='off'&&weather!=='forecast'){
  value.atmosphere.clouds={...(value.atmosphere.clouds||cloudDefaults()),enabled:weather!=='clear',coverage:weather==='clear'?0:weather==='cloud'?.55:.88};
  value.atmosphere.fog=weather==='fog'?{mode:'linear',nearM:80,farM:1600}:{mode:'off',nearM:150,farM:6000};
  value.atmosphere.topColor=weather==='clear'?'#8daec0':'#6d818b';value.atmosphere.horizonColor=weather==='clear'?'#d7e0dd':'#abb9ba';
  value.lighting.sun.enabled=weather==='clear'||weather==='cloud';
 }
 if(light!=='scene'){
  const preset=environmentPreset(light==='day'?'land-day-v1':'dusk-v1');
  value.lighting=structuredClone(preset.lighting);value.atmosphere.topColor=preset.atmosphere.topColor;value.atmosphere.horizonColor=preset.atmosphere.horizonColor;
 }
 return {value};
}
