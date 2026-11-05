import type {CockpitScene} from './cockpitState.ts';

export type GlobePoint={sceneId:string;revision:string;name:string;longitude:number;latitude:number};
export type GlobeCluster={id:string;points:GlobePoint[];longitude:number;latitude:number;spanDegrees:number;coincident:boolean};
export function globeVector(longitude:number,latitude:number):[number,number,number]{
 const lon=longitude*Math.PI/180,lat=latitude*Math.PI/180;
 return [Math.cos(lat)*Math.cos(lon),Math.sin(lat),-Math.cos(lat)*Math.sin(lon)];
}
export function globeAngleDegrees(a:[number,number,number],b:[number,number,number]):number{
 const la=Math.hypot(...a),lb=Math.hypot(...b);
 if(!la||!lb)return 0;
 const dot=Math.max(-1,Math.min(1,(a[0]*b[0]+a[1]*b[1]+a[2]*b[2])/(la*lb)));
 return dot>=1-1e-12?0:Math.acos(dot)*180/Math.PI;
}
/** Screen pixel separation mapped to spherical degrees at the current camera distance. */
export function globeClusterDegrees(cameraDistance=3.65,viewportHeight=900,minPixelGap=40):number{
 const surface=Math.max(.12,(Number.isFinite(cameraDistance)?cameraDistance:3.65)-1);
 const height=Math.max(240,Number.isFinite(viewportHeight)?viewportHeight:900);
 const gap=Math.max(12,Number.isFinite(minPixelGap)?minPixelGap:40);
 const raw=gap/height*surface*2*Math.tan(17*Math.PI/180)*180/Math.PI;
 return Math.max(.02,Math.min(5.5,Math.round(raw*20)/20));
}
export function sceneGlobePoint(row:CockpitScene):GlobePoint|null{
 const frame=row.opened?.snapshot.coordinateFrame;
 if(!row.opened||row.error||frame?.mode!=='projected_site')return null;
 const [longitude,latitude]=frame.anchor.geographicAnchor;
 if(!Number.isFinite(longitude)||!Number.isFinite(latitude)||Math.abs(longitude)>180||Math.abs(latitude)>90)return null;
 return {sceneId:row.summary.sceneId,revision:row.opened.sceneRevision,name:row.summary.displayName,longitude,latitude};
}
/** Angular distance with pairwise linkage keeps date-line groups intact and prevents chain drift. */
export function clusterGlobePoints(points:GlobePoint[],degrees=4):GlobeCluster[]{
 const threshold=Math.max(.02,Number.isFinite(degrees)?degrees:4),limit=Math.cos(threshold*Math.PI/180);
 const clusters:{points:GlobePoint[];vectors:[number,number,number][];sum:[number,number,number]}[]=[];
 for(const point of points){
  const v=globeVector(point.longitude,point.latitude);
  let best:{points:GlobePoint[];vectors:[number,number,number][];sum:[number,number,number]}|null=null,bestDot=-1;
  for(const item of clusters){
   const length=Math.hypot(...item.sum),centerDot=length?v.reduce((sum,x,i)=>sum+x*item.sum[i]/length,0):1;
   if(centerDot>=limit&&item.vectors.every(u=>u[0]*v[0]+u[1]*v[1]+u[2]*v[2]>=limit)&&centerDot>bestDot){best=item;bestDot=centerDot;}
  }
  if(best){best.points.push(point);best.vectors.push(v);for(let i=0;i<3;i++)best.sum[i]+=v[i];}
  else clusters.push({points:[point],vectors:[v],sum:[...v]});
 }
 return clusters.map(({points,vectors,sum})=>{
  let spanDegrees=0;
  for(let i=0;i<vectors.length;i++)for(let j=i+1;j<vectors.length;j++)spanDegrees=Math.max(spanDegrees,globeAngleDegrees(vectors[i],vectors[j]));
  return {id:points.map(p=>p.sceneId).sort().join('|'),points,longitude:Math.atan2(-sum[2],sum[0])*180/Math.PI,latitude:Math.atan2(sum[1],Math.hypot(sum[0],sum[2]))*180/Math.PI,spanDegrees,coincident:points.length>1&&spanDegrees<=.02};
 });
}
/** Camera distance that splits an expandable regional cluster while framing its members. */
export function globeClusterFocusDistance(cluster:Pick<GlobeCluster,'points'|'spanDegrees'|'coincident'>,viewportHeight=900,minPixelGap=40):number{
 if(cluster.points.length<=1)return 2.1;
 if(cluster.coincident||cluster.spanDegrees<=.02)return 1.32;
 const vectors=cluster.points.map(p=>globeVector(p.longitude,p.latitude));
 let minSplit=cluster.spanDegrees;
 for(let i=0;i<vectors.length;i++)for(let j=i+1;j<vectors.length;j++){const d=globeAngleDegrees(vectors[i],vectors[j]);if(d>.02&&d<minSplit)minSplit=d;}
 const height=Math.max(240,Number.isFinite(viewportHeight)?viewportHeight:900),gap=Math.max(12,Number.isFinite(minPixelGap)?minPixelGap:40);
 const degPerUnit=gap/height*2*Math.tan(17*Math.PI/180)*180/Math.PI;
 const splitSurface=minSplit*.72/Math.max(.05,degPerUnit);
 const fitSurface=(cluster.spanDegrees*Math.PI/180)/(.48*2*Math.tan(17*Math.PI/180));
 return Math.round((1+Math.max(.22,Math.min(1.15,Math.max(Math.min(splitSurface,.42),fitSurface))))*100)/100;
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
