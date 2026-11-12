import type {WorkbenchApi} from './api.ts';
export interface PublicGeoRequest {
  clientRequestId:string; longitude:number; latitude:number; radiusKm:number;
  name:string; terrain:boolean; imagery:boolean;
}
export interface PublicGeoResult {terrainVersionId?:string; imageryVersionId?:string}
export interface PublicGeoJob {
  jobId:string; jobRevision:string; state:'processing'|'ready'|'failed'|'cancelled'; stage:string;
  request:PublicGeoRequest; results:PublicGeoResult; errorCode:string|null;
}
export class PublicGeoWrite {
  private pending:{encoded:string;body:PublicGeoRequest}|null=null;
  begin(body:Omit<PublicGeoRequest,'clientRequestId'>,job:PublicGeoJob|null) {
    const encoded=JSON.stringify(body);
    const completed=job&&job.state!=='processing'&&job.request.clientRequestId===this.pending?.body.clientRequestId;
    if(!this.pending||this.pending.encoded!==encoded||completed)this.pending={encoded,body:{...body,clientRequestId:crypto.randomUUID()}};
    return this.pending.body;
  }
}
export function startPublicGeo(api:WorkbenchApi, body:PublicGeoRequest, signal?:AbortSignal) {
  return api.request<PublicGeoJob>('/api/workbench/public-geodata/start',body,signal);
}
export function readPublicGeo(api:WorkbenchApi, jobId?:string, signal?:AbortSignal) {
  return api.request<PublicGeoJob>('/api/workbench/public-geodata/job',jobId?{jobId}:{},signal);
}
export function cancelPublicGeo(api:WorkbenchApi, job:PublicGeoJob, signal?:AbortSignal) {
  return api.request<PublicGeoJob>('/api/workbench/public-geodata/cancel',
    {jobId:job.jobId,expectedJobRevision:job.jobRevision},signal);
}
export function validPublicGeo(longitude:number,latitude:number,radiusKm:number) {
  if(![longitude,latitude,radiusKm].every(Number.isFinite)||longitude<=-180||longitude>=180
    ||latitude< -79.8||latitude>83.8||radiusKm<.5||radiusKm>10)return false;
  const dy=radiusKm/110.5,dx=radiusKm/(110.5*Math.cos((Math.abs(latitude)+dy)*Math.PI/180));
  return longitude-dx> -180&&longitude+dx<180&&latitude-dy> -80&&latitude+dy<84;
}
export function mapPixel(longitude:number,latitude:number,zoom:number) {
  const scale=256*2**zoom, sin=Math.sin(latitude*Math.PI/180);
  return [(longitude+180)/360*scale,(.5-Math.log((1+sin)/(1-sin))/(4*Math.PI))*scale] as const;
}
export function mapCoordinate(x:number,y:number,zoom:number) {
  const scale=256*2**zoom;
  return [x/scale*360-180,Math.atan(Math.sinh(Math.PI*(1-2*y/scale)))*180/Math.PI] as const;
}
