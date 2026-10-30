import {cloudDefaults,environmentPreset,type SceneEnvironmentV1} from './sceneEnvironment.ts';
import type {WeatherView} from './weather';
/** Temporary visualization only. Never writes the saved scene or equipment pose. */
export function weatherEnvironment(base:SceneEnvironmentV1|null|undefined,value:WeatherView):SceneEnvironmentV1{
 const result=structuredClone(base||environmentPreset('land-day-v1')),f=value.forecast!;
 const coverage=f.cloudPercent===null?(f.condition==='clear'?0:.65):f.cloudPercent/100;
 const night=f.symbol?.endsWith('_night')??false,overcast=['rain','snow','sleet','fog'].includes(f.condition);
 result.presetId='custom-v1';
 result.atmosphere.clouds={...(result.atmosphere.clouds||cloudDefaults()),enabled:coverage>.05,coverage:Math.max(0,Math.min(1,coverage)),defaultPlayback:'playing'};
 result.atmosphere.topColor=night?'#12232e':overcast?'#6d818b':'#8daec0';
 result.atmosphere.horizonColor=night?'#34434b':overcast?'#abb9ba':'#d7e0dd';
 result.atmosphere.fog=f.condition==='fog'?{mode:'linear',nearM:80,farM:1600}:{mode:'off',nearM:150,farM:6000};
 result.lighting.sun.enabled=!night&&!overcast;
 result.lighting.hemisphereIntensity=night?.35:overcast?.7:1;
 result.lighting.environment.intensity=night?.25:overcast?.55:.8;
 return result;
}
