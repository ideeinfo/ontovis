import {cloudDefaults,environmentPreset,type SceneEnvironmentV1} from './sceneEnvironment.ts';
import type {WeatherView} from './weather';
export function nightPresentation(value:SceneEnvironmentV1){
 value.atmosphere.topColor='#070e23';value.atmosphere.horizonColor='#25344f';
 value.lighting.sun.enabled=false;value.lighting.hemisphereIntensity=1.35;value.lighting.environment.intensity=.6;
 value.surface.imageryShading='lit';
}
/** Temporary visualization only. Never writes the saved scene or equipment pose. */
export function weatherEnvironment(base:SceneEnvironmentV1|null|undefined,value:WeatherView):SceneEnvironmentV1{
 const result=structuredClone(base||environmentPreset('land-day-v1')),f=value.forecast!;
 const coverage=f.cloudPercent===null?(f.condition==='clear'?0:.65):f.cloudPercent/100;
 const night=f.symbol?.endsWith('_night')??false,overcast=['rain','snow','sleet','fog'].includes(f.condition);
 result.presetId='custom-v1';
 result.atmosphere.clouds={...(result.atmosphere.clouds||cloudDefaults()),enabled:coverage>.05,coverage:Math.max(0,Math.min(1,coverage)),defaultPlayback:'playing'};
 result.atmosphere.topColor=overcast?'#6d818b':'#8daec0';
 result.atmosphere.horizonColor=overcast?'#abb9ba':'#d7e0dd';
 result.atmosphere.fog=f.condition==='fog'?{mode:'linear',nearM:80,farM:1600}:{mode:'off',nearM:150,farM:6000};
 result.lighting.sun.enabled=!night&&!overcast;
 result.lighting.hemisphereIntensity=overcast?.7:1;
 result.lighting.environment.intensity=overcast?.55:.8;
 if(night)nightPresentation(result);
 return result;
}
