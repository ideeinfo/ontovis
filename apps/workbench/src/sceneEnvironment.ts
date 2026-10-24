import type {CoordinateFrame} from './sceneTypes';
import type {TerrainVersion} from './resourceTypes';
export interface SceneEnvironmentV1 {
  schemaVersion:1;renderProfile:'standard-v1';presetId:'land-day-v1'|'offshore-overview-v1'|'dusk-v1'|'custom-v1';
  surroundings?:{mode:'auto'|'off';profile:'land'|'offshore'};
  color:{toneMapping:'none'|'aces';exposure:number};
  lighting:{hemisphereIntensity:number;environment:{source:'procedural-sky-v1';intensity:number};sun:{enabled:boolean;azimuthDeg:number;elevationDeg:number;intensity:number;color:string}};
  atmosphere:{sky:'gradient-v1';topColor:string;horizonColor:string;fog:{mode:'off'|'linear';nearM:number;farM:number}};
  shadows:{mode:'off'|'sun-local';quality:'balanced';radiusM:number};
  surface:{imageryShading:'source-color'|'lit';textureSet:null;terrainRoughness:number;textureRepeatM:number};
  water:{enabled:boolean;baseSurface:'active-flat-relative-terrain';mode:'normal-waves';travelHeadingDeg:number;rippleStrength:number;amplitudeM:0;wavelengthM:number;travelSpeedMps:number;color:string;roughness:number;reflection:'procedural-sky';seed:number};
  animation:{defaultPlayback:'playing'|'paused';initialPhase:number};
}
export function environmentPreset(id:Exclude<SceneEnvironmentV1['presetId'],'custom-v1'>):SceneEnvironmentV1 {
  const dusk=id==='dusk-v1';
  return {schemaVersion:1,renderProfile:'standard-v1',presetId:id,surroundings:{mode:'auto',profile:id==='offshore-overview-v1'?'offshore':'land'},color:{toneMapping:'aces',exposure:1},
    lighting:{hemisphereIntensity:1,environment:{source:'procedural-sky-v1',intensity:.8},sun:{enabled:true,azimuthDeg:135,elevationDeg:dusk?12:35,intensity:dusk?1.6:2.5,color:dusk?'#ffca93':'#fff3df'}},
    atmosphere:{sky:'gradient-v1',topColor:dusk?'#7b849a':'#8daec0',horizonColor:dusk?'#e2bba0':'#d7e0dd',fog:{mode:id==='offshore-overview-v1'?'off':'linear',nearM:1500,farM:13000}},
    shadows:{mode:'sun-local',quality:'balanced',radiusM:500},surface:{imageryShading:'source-color',textureSet:null,terrainRoughness:1,textureRepeatM:20},
    water:{enabled:id==='offshore-overview-v1',baseSurface:'active-flat-relative-terrain',mode:'normal-waves',travelHeadingDeg:20,rippleStrength:.35,amplitudeM:0,wavelengthM:20,travelSpeedMps:.6,color:'#507d91',roughness:.3,reflection:'procedural-sky',seed:771},
    animation:{defaultPlayback:'playing',initialPhase:0}};
}
export function waterSurfaceSupported(frame:CoordinateFrame,terrain:TerrainVersion|null):boolean {
  const range=terrain?.report.source.heightRangeM;
  return frame.mode==='projected_site'&&frame.verticalDatum==='UNKNOWN_RELATIVE'&&!!range&&range.every(Number.isFinite)&&Math.abs(range[1]-range[0])<=.0001;
}
/** Pure visible-time clock. First visible sample never includes hidden or paused time. */
export class EnvironmentClock {
  private last:number|null=null;private phase:number;
  constructor(initial=0){this.phase=initial;}
  step(now:number,playing:boolean){
    if(!playing){this.last=null;return this.phase;}
    if(this.last!==null)this.phase+=Math.max(0,Math.min(100,now-this.last))/1000;
    this.last=now;return this.phase;
  }
  suspend(){this.last=null;}
  value(){return this.phase;}
}
