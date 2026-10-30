import {useEffect,useRef,useState} from 'react';
import {ArrowDown,ArrowLeft,ArrowRight,ArrowUp,Minus,Plus} from 'lucide-react';
import {ApiError,type WorkbenchApi} from './api.ts';
import {usePreferences} from './Preferences';
import {Btn,IconBtn} from './Primitives';
import {PublicGeoWrite,cancelPublicGeo,mapCoordinate,mapPixel,readPublicGeo,startPublicGeo,validPublicGeo,type PublicGeoJob,type PublicGeoResult} from './publicGeoApi';
import {publicGeoFailure,publicGeoMessages} from './publicGeoMessages';
import {publicGeoInitialForm,type PublicGeoCenter} from './publicGeoForm';
import {tileLoadResult,visibleTileFailures} from './mapTileState';
import './publicGeoData.css';

const pendingJobs=new WeakMap<WorkbenchApi,{revision:string;id:string}>();
export interface PublicGeoDataPanelProps {
 api:WorkbenchApi;canWrite:boolean;onImported:(result:PublicGeoResult)=>void;onClose?:()=>void;
 initialCenter?:PublicGeoCenter;
}
function QueryMap({longitude,latitude,radius,onPick,disabled}:{longitude:number;latitude:number;radius:number;onPick:(lon:number,lat:number)=>void;disabled:boolean}) {
 const {locale}=usePreferences(),t=publicGeoMessages[locale];
 const [view,setView]=useState({longitude:Number.isFinite(longitude)&&longitude>-180&&longitude<180?longitude:105,latitude:Number.isFinite(latitude)&&latitude>=-79.8&&latitude<=83.8?latitude:35,zoom:6});
 const [width,setWidth]=useState(400);const box=useRef<HTMLDivElement>(null),height=230;
 const [failedTiles,setFailedTiles]=useState<ReadonlySet<string>>(()=>new Set());
 useEffect(()=>{if(!box.current)return;const observer=new ResizeObserver(entries=>setWidth(entries[0].contentRect.width));observer.observe(box.current);return()=>observer.disconnect();},[]);
 const [cx,cy]=mapPixel(view.longitude,view.latitude,view.zoom),tiles=[];
 const nx=2**view.zoom;
 for(let y=Math.floor((cy-height/2)/256);y<=Math.floor((cy+height/2)/256);y++)for(let x=Math.floor((cx-width/2)/256);x<=Math.floor((cx+width/2)/256);x++)if(y>=0&&y<nx)tiles.push({x,y,url:`https://tile.openstreetmap.org/${view.zoom}/${((x%nx)+nx)%nx}/${y}.png`});
 const visibleTiles=new Set(tiles.map(tile=>tile.url)),visibleKey=[...visibleTiles].sort().join('\n'),visibleTilesRef=useRef<ReadonlySet<string>>(visibleTiles);
 visibleTilesRef.current=visibleTiles;
 useEffect(()=>setFailedTiles(failures=>visibleTileFailures(failures,visibleTilesRef.current)),[visibleKey]);
 const mapFailed=[...failedTiles].some(url=>visibleTiles.has(url));
 const marker=Number.isFinite(longitude)&&Number.isFinite(latitude)&&longitude>-180&&longitude<180&&latitude>=-79.8&&latitude<=83.8?mapPixel(longitude,latitude,view.zoom):null;
 const metersPerPixel=156543.03392*Math.cos(view.latitude*Math.PI/180)/2**view.zoom;
 const move=(dx:number,dy:number)=>{const [lon,lat]=mapCoordinate(cx+dx,cy+dy,view.zoom);setView(v=>({...v,longitude:Math.max(-179.9,Math.min(179.9,lon)),latitude:Math.max(-79.8,Math.min(83.8,lat))}));};
 useEffect(()=>{if(Number.isFinite(longitude)&&Number.isFinite(latitude)&&longitude>-180&&longitude<180&&latitude>=-79.8&&latitude<=83.8)setView(v=>({...v,longitude,latitude}));},[longitude,latitude]);
 return <div className="ov-public-map" ref={box} role="application" aria-label={t.map} tabIndex={0} onKeyDown={e=>{if(disabled)return;const keys:Record<string,[number,number]>={ArrowLeft:[-100,0],ArrowRight:[100,0],ArrowUp:[0,-100],ArrowDown:[0,100]};if(keys[e.key]){e.preventDefault();move(...keys[e.key]);}}} onClick={e=>{if(disabled)return;const rect=e.currentTarget.getBoundingClientRect();const [lon,lat]=mapCoordinate(cx+e.clientX-rect.left-width/2,cy+e.clientY-rect.top-height/2,view.zoom);if(lon>-180&&lon<180&&lat>=-79.8&&lat<=83.8)onPick(lon,lat);}}>
  {tiles.map(tile=><img key={`${view.zoom}/${tile.x}/${tile.y}`} src={tile.url} referrerPolicy="strict-origin-when-cross-origin" width="256" height="256" alt="" draggable={false} onError={()=>setFailedTiles(failures=>tileLoadResult(failures,visibleTilesRef.current,tile.url,false))} onLoad={()=>setFailedTiles(failures=>tileLoadResult(failures,visibleTilesRef.current,tile.url,true))} style={{left:tile.x*256-cx+width/2,top:tile.y*256-cy+height/2}}/>)}
  {marker&&<div className="ov-public-map-radius" style={{left:marker[0]-cx+width/2,top:marker[1]-cy+height/2,width:Math.max(4,radius*2000/metersPerPixel),height:Math.max(4,radius*2000/metersPerPixel)}}><span/></div>}
  {mapFailed&&<span className="ov-public-map-failure" role="status">{locale==='zh'?'底图暂不可用，仍可输入经纬度。':'Map unavailable. You can still enter coordinates.'}</span>}
  <div className="ov-public-map-controls" onClick={e=>e.stopPropagation()}><IconBtn label={t.zoomIn} disabled={disabled||view.zoom>=15} onClick={()=>setView(v=>({...v,zoom:v.zoom+1}))}><Plus size={15}/></IconBtn><IconBtn label={t.zoomOut} disabled={disabled||view.zoom<=2} onClick={()=>setView(v=>({...v,zoom:v.zoom-1}))}><Minus size={15}/></IconBtn><IconBtn label={locale==='zh'?'向西移动':'Move west'} disabled={disabled} onClick={()=>move(-150,0)}><ArrowLeft size={15}/></IconBtn><IconBtn label={locale==='zh'?'向东移动':'Move east'} disabled={disabled} onClick={()=>move(150,0)}><ArrowRight size={15}/></IconBtn><IconBtn label={locale==='zh'?'向北移动':'Move north'} disabled={disabled} onClick={()=>move(0,-100)}><ArrowUp size={15}/></IconBtn><IconBtn label={locale==='zh'?'向南移动':'Move south'} disabled={disabled} onClick={()=>move(0,100)}><ArrowDown size={15}/></IconBtn></div>
  <a className="ov-public-map-credit" href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer" onClick={e=>e.stopPropagation()}>© OpenStreetMap contributors</a>
 </div>;
}
export function PublicGeoDataPanel({api,canWrite,onImported,onClose,initialCenter}:PublicGeoDataPanelProps) {
 const {locale}=usePreferences(),t=publicGeoMessages[locale];
 const initial=publicGeoInitialForm(initialCenter);
 const [name,setName]=useState(initial.name),[longitude,setLongitude]=useState(initial.longitude),[latitude,setLatitude]=useState(initial.latitude),[radius,setRadius]=useState(initial.radius);
 const [reading,setReading]=useState(true);
 const [terrain,setTerrain]=useState(true),[imagery,setImagery]=useState(true),[job,setJob]=useState<PublicGeoJob|null>(null),[error,setError]=useState<unknown>(null),[sending,setSending]=useState(false);
 const intent=useRef(0),pollFailures=useRef(0),alive=useRef(true),request=useRef(new PublicGeoWrite()),notified=useRef(''),onImportedRef=useRef(onImported),revision=useRef(api.revision),controller=useRef(new AbortController());
 onImportedRef.current=onImported;
 const working=reading||sending||job?.state==='processing';
 const numericLon=longitude.trim()?Number(longitude):NaN,numericLat=latitude.trim()?Number(latitude):NaN,numericRadius=Number(radius);
 const receive=(value:PublicGeoJob,token=intent.current)=>{if(token!==intent.current)return;setJob(value);if(value.state==='processing')pendingJobs.set(api,{revision:api.revision,id:value.jobId});else pendingJobs.delete(api);if(value.state!=='processing'&&notified.current!==value.jobId&&(value.results.terrainVersionId||value.results.imageryVersionId)){notified.current=value.jobId;onImportedRef.current(value.results);}};
 useEffect(()=>{
  alive.current=true;controller.current=new AbortController();setReading(true);
  const token=++intent.current,pending=pendingJobs.get(api);
  if(pending?.revision!==api.revision)pendingJobs.delete(api);
  void readPublicGeo(api,pending?.revision===api.revision?pending.id:undefined,controller.current.signal).then(value=>{
   if(!alive.current||token!==intent.current)return;
   if(value.state!=='processing'){pendingJobs.delete(api);return;}
   receive(value,token);const restored=publicGeoInitialForm(undefined,value);
   setName(restored.name);setLongitude(restored.longitude);setLatitude(restored.latitude);setRadius(restored.radius);setTerrain(restored.terrain);setImagery(restored.imagery);
  }).catch(reason=>{if(alive.current&&token===intent.current&&reason?.name!=='AbortError'&&!(reason instanceof ApiError&&reason.code==='NOT_FOUND_OR_FORBIDDEN'))setError(reason);})
   .finally(()=>{if(alive.current&&token===intent.current)setReading(false);});
  return()=>{alive.current=false;controller.current.abort();};
 },[api]);
 useEffect(()=>{if(job?.state!=='processing')return;const token=intent.current,timer=setTimeout(()=>{void readPublicGeo(api,job.jobId,controller.current.signal).then(value=>{if(alive.current&&token===intent.current){pollFailures.current=0;setError(null);receive(value,token);}}).catch(reason=>{if(alive.current&&token===intent.current&&reason?.name!=='AbortError'){pollFailures.current+=1;setError(reason);}});},Math.min(10000,1800*2**Math.min(3,pollFailures.current)));return()=>clearTimeout(timer);},[job,api,error]);
 async function start(){
  if(!canWrite||working)return;
  if(!name.trim()||!longitude.trim()||!latitude.trim()||!validPublicGeo(numericLon,numericLat,numericRadius)||!terrain&&!imagery){setError(new ApiError(422,'INVALID_REQUEST'));return;}
  const body=request.current.begin({name:name.trim(),longitude:numericLon,latitude:numericLat,radiusKm:numericRadius,terrain,imagery},job),token=++intent.current;
  setSending(true);setError(null);
  try{const value=await startPublicGeo(api,body,controller.current.signal);if(alive.current&&revision.current===api.revision)receive(value,token);}
  catch(reason){if(alive.current&&token===intent.current&&(reason as Error)?.name!=='AbortError')setError(reason);}
  finally{if(alive.current&&token===intent.current)setSending(false);}
 }
 async function cancel(){if(!job||job.state!=='processing')return;const token=++intent.current;setSending(true);setError(null);try{const value=await cancelPublicGeo(api,job,controller.current.signal);if(alive.current)receive(value,token);}catch(reason){if(alive.current&&token===intent.current&&(reason as Error)?.name!=='AbortError'){setError(reason);if(reason instanceof ApiError&&reason.code==='PUBLIC_JOB_CHANGED'){try{const latest=await readPublicGeo(api,job.jobId,controller.current.signal);if(alive.current)receive(latest,token);}catch(refreshError){if(alive.current&&token===intent.current&&(refreshError as Error)?.name!=='AbortError')setError(refreshError);}}}}finally{if(alive.current&&token===intent.current)setSending(false);}}
 return <section className="ov-public-geodata">
  <p className="ov-resource-caption">{t.hint}</p><fieldset disabled={working||!canWrite}>
   <label>{t.name}<input value={name} maxLength={120} onChange={e=>setName(e.target.value)}/></label>
   <div className="ov-public-geo-pair"><label>{t.longitude}<input inputMode="decimal" value={longitude} onChange={e=>setLongitude(e.target.value)}/></label><label>{t.latitude}<input inputMode="decimal" value={latitude} onChange={e=>setLatitude(e.target.value)}/></label></div>
   <label>{t.radius}<input type="number" min="0.5" max="10" step="0.5" value={radius} onChange={e=>setRadius(e.target.value)}/></label>
   <QueryMap longitude={numericLon} latitude={numericLat} radius={Number.isFinite(numericRadius)?Math.max(0,Math.min(10,numericRadius)):0} disabled={working||!canWrite} onPick={(lon,lat)=>{setLongitude(lon.toFixed(7));setLatitude(lat.toFixed(7));}}/>
   <p className="ov-resource-caption">{t.mapHint} <a href="https://www.openstreetmap.org/" target="_blank" rel="noopener noreferrer">{t.osm}</a></p>
   <label className="ov-resource-check"><input type="checkbox" checked={terrain} onChange={e=>setTerrain(e.target.checked)}/><span>{t.terrain}</span></label>
   <label className="ov-resource-check"><input type="checkbox" checked={imagery} onChange={e=>setImagery(e.target.checked)}/><span>{t.imagery}</span></label>
  </fieldset>
  <details><summary>{t.sources}</summary><p className="ov-resource-caption">{t.precision}</p><p className="ov-resource-caption">{t.range}</p><a href="https://registry.opendata.aws/copernicus-dem/" target="_blank" rel="noreferrer">Copernicus DEM</a> · <a href="https://registry.opendata.aws/sentinel-2-l2a-cogs/" target="_blank" rel="noreferrer">Sentinel-2 COGs</a></details>
  {(sending||job?.state==='processing')&&<p role="status">{t.working} {t.progress[job?.stage as keyof typeof t.progress]??''}</p>}
  {job&&job.state!=='processing'&&<p role="status">{t[job.state]}{job.errorCode&&' '+publicGeoFailure(new ApiError(422,job.errorCode),locale)}</p>}
  {!!error&&<p role="alert" className="ov-resource-error">{publicGeoFailure(error,locale)}</p>}
  <div className="ov-public-geo-actions">{onClose&&<Btn onClick={onClose}>{t.close}</Btn>}{job?.state==='processing'?<Btn disabled={sending||!canWrite} onClick={()=>void cancel()}>{t.cancel}</Btn>:<Btn primary disabled={working||!canWrite} onClick={()=>void start()}>{t.submit}</Btn>}</div>
 </section>;
}
