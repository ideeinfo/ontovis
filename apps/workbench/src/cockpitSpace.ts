import type {CockpitScene} from './cockpitState.ts';

export type GlobePoint={sceneId:string;revision:string;name:string;longitude:number;latitude:number};
export type GlobeCluster={id:string;points:GlobePoint[];longitude:number;latitude:number};
export function globeVector(longitude:number,latitude:number):[number,number,number]{
 const lon=longitude*Math.PI/180,lat=latitude*Math.PI/180;
 return [Math.cos(lat)*Math.cos(lon),Math.sin(lat),-Math.cos(lat)*Math.sin(lon)];
}
export function sceneGlobePoint(row:CockpitScene):GlobePoint|null{
 const frame=row.opened?.snapshot.coordinateFrame;
 if(!row.opened||row.error||frame?.mode!=='projected_site')return null;
 const [longitude,latitude]=frame.anchor.geographicAnchor;
 if(!Number.isFinite(longitude)||!Number.isFinite(latitude)||Math.abs(longitude)>180||Math.abs(latitude)>90)return null;
 return {sceneId:row.summary.sceneId,revision:row.opened.sceneRevision,name:row.summary.displayName,longitude,latitude};
}
/** Angular distance keeps clusters near the date line together without moving them to Greenwich. */
export function clusterGlobePoints(points:GlobePoint[],degrees=4):GlobeCluster[]{
 const clusters:{points:GlobePoint[];sum:[number,number,number]}[]=[],limit=Math.cos(degrees*Math.PI/180);
 for(const point of points){const v=globeVector(point.longitude,point.latitude);
  const group=clusters.find(item=>{const length=Math.hypot(...item.sum);return v.reduce((sum,x,i)=>sum+x*item.sum[i]/length,0)>=limit;});
  if(group){group.points.push(point);for(let i=0;i<3;i++)group.sum[i]+=v[i];}else clusters.push({points:[point],sum:[...v]});
 }
 return clusters.map(({points,sum})=>({id:points.map(p=>p.sceneId).sort().join('|'),points,
  longitude:Math.atan2(-sum[2],sum[0])*180/Math.PI,latitude:Math.atan2(sum[1],Math.hypot(sum[0],sum[2]))*180/Math.PI}));
}
export type SpaceNavigation={token:number;key:string;sceneId:string;revision:string;phase:'loading'|'arriving'|'failed'};
export function preparedNavigation(current:SpaceNavigation|null,key:string,state:'loading'|'ready'|'error'):SpaceNavigation|null{
 if(!current||current.key!==key||current.phase!=='loading'||state==='loading')return current;
 return {...current,phase:state==='ready'?'arriving':'failed'};
}
export function mayFinishNavigation(current:SpaceNavigation|null,token:number){return current?.token===token&&current.phase==='arriving';}

/** A display orbit, capped after a stalled frame and eased back in after interaction. */
export function globeDriftRadians(elapsedMs:number,resumedMs:number,enabled:boolean){
 if(!enabled||!Number.isFinite(elapsedMs)||!Number.isFinite(resumedMs))return 0;
 const phase=Math.max(0,Math.min(1,resumedMs/1400)),ease=phase*phase*(3-2*phase);
 return Math.max(0,Math.min(elapsedMs,100))/1000*(Math.PI/100)*ease;
}

/** New flights start now; only a flight already running when hidden is suspended. */
export function resumedGlobeFlightStart(start:number,hiddenAt:number|null,now:number,newFlight:boolean){
 return newFlight?now:hiddenAt===null?start:start+Math.max(0,now-hiddenAt);
}
export function globeFlightProgress(start:number,now:number){return Math.max(0,Math.min(1,(now-start)/900));}

/** A flight's final frame must hand the loop back to idle drift even without a controls-change event. */
export function globeFramePlan(hasFlight:boolean,driftAllowed:boolean){return {drift:driftAllowed&&!hasFlight,continue:hasFlight||driftAllowed};}
