import type {CoordinateFrame} from './sceneTypes';
import type {PublicGeoJob} from './publicGeoApi';

export interface PublicGeoCenter {longitude:number;latitude:number}
function validCenter(center:PublicGeoCenter|undefined):center is PublicGeoCenter {
 return !!center&&Number.isFinite(center.longitude)&&Number.isFinite(center.latitude)
  &&Math.abs(center.longitude)<=180&&Math.abs(center.latitude)<=90;
}
export function scenePublicGeoCenter(frame:CoordinateFrame):PublicGeoCenter|undefined {
 if(frame.mode!=='projected_site')return;
 const [longitude,latitude]=frame.anchor.geographicAnchor,center={longitude,latitude};
 return validCenter(center)?center:undefined;
}
export function publicGeoInitialForm(center?:PublicGeoCenter,job?:PublicGeoJob) {
 // A running request is immutable. Completed jobs must not replace a new scene's location.
 const active=job?.state==='processing'?job.request:undefined;
 const point=active||center;
 return {name:active?.name||'',longitude:validCenter(point)?point.longitude.toFixed(7):'',
  latitude:validCenter(point)?point.latitude.toFixed(7):'',radius:String(active?.radiusKm??3),
  terrain:active?.terrain??true,imagery:active?.imagery??true};
}
