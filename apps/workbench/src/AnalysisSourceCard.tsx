import {lazy,memo,Suspense,useEffect,useState} from 'react';
import {ExternalLink,RefreshCw} from 'lucide-react';
import {Btn} from './Primitives';
import {WorkOrderPhotoViewport} from './WorkOrderPhotoViewport';
import {trendDomain,trendSegments,type SimulatedTrend} from './simulatedAlarms';
import {AnalysisSources,type EvidenceDetail,type EvidenceSource} from './analysisSources';
import type {CanvasCard,CardView,ImageView,ModelView} from './analysisCanvas';
import type {WorkbenchApi} from './api';
import type {ProjectModelVersion} from './resourceTypes';
import './workOrders.css';
import './dataAlarms.css';
const ModelCard=lazy(()=>import('./AnalysisModelCard').then(module=>({default:module.AnalysisModelCard})));
export const materialNames={object:'工程对象',drawing:'图纸',document:'文档',photo:'照片',model3d:'三维模型',trend:'趋势',alarm:'故障报警',work_order:'历史工单',analysis:'分析记录'};
export function AnalysisTrend({trends,en,cursor,onCursor}:{trends:SimulatedTrend[];en:boolean;cursor?:number|null;onCursor?:(value:number|null)=>void}){
  const [localCursor,setLocalCursor]=useState<number|null>(null),position=cursor===undefined?localCursor:cursor;
  const domain=trendDomain(trends),first=trends[0],span=first?Date.parse(first.timeTo)-Date.parse(first.timeFrom):0;
  const markers=first?.dataset?[30,150].map(second=>(Date.parse(first.dataset!.timeFrom)+second*1000-Date.parse(first.timeFrom))/span).filter(value=>value>=0&&value<=1):[];
  const change=(value:number|null)=>{setLocalCursor(value);onCursor?.(value);};
  return <div className="ac-trend" data-canvas-inner>
    <svg className="da-chart" viewBox="0 0 720 225" role="img" aria-label={en?'Trends with quality gaps':'趋势对照，保留质量断点'}
      onPointerMove={event=>{const rect=event.currentTarget.getBoundingClientRect();change(Math.max(0,Math.min(1,((event.clientX-rect.left)/rect.width*720-40)/640)));}} onPointerLeave={()=>change(null)}>
      <line x1="40" y1="30" x2="40" y2="190"/><line x1="40" y1="190" x2="680" y2="190"/>
      <text x="34" y="35" textAnchor="end">{domain[1].toFixed(1)}</text><text x="34" y="190" textAnchor="end">{domain[0].toFixed(1)}</text>
      {trends.flatMap((row,index)=>trendSegments(row,domain,row.unit==='1').map((points,part)=><polyline key={`${index}:${part}`} points={points} data-series={index}/>))}
      {markers.map((value,i)=><line key={i} className="da-cursor" x1={40+value*640} x2={40+value*640} y1="25" y2="190"/>)}
      {position!==null&&<line className="ac-trend-cursor" x1={40+position*640} x2={40+position*640} y1="25" y2="190"/>}
      <text x="40" y="215">0 s</text><text x="680" y="215" textAnchor="end">{Math.round(span/1000)} s</text>
    </svg><small>{en?'Alarm occurrence / recovery · Quality gaps are not interpolated':'虚线为发生/恢复 · 质量异常处保持断点'}</small>
    {trends.map((trend,i)=>{const time=Date.parse(trend.timeFrom)+(Date.parse(trend.timeTo)-Date.parse(trend.timeFrom))*(position||0),sample=position===null?null:trend.samples.reduce<(typeof trend.samples)[number]|null>((best,item)=>!best||Math.abs(Date.parse(item.sourceTime)-time)<Math.abs(Date.parse(best.sourceTime)-time)?item:best,null);
      return <p key={i} data-series={i}>{en?trend.metricId:({sensor_temperature:'传感器温度',reference_temperature:'独立参照温度',supply_voltage:'供电电压',device_feedback:'状态反馈',overcurrent:'过流信号'} as Record<string,string>)[trend.metricId]||trend.metricId} · {trend.unit==='degC'?'°C':trend.unit}{sample&&<output> · {sample.value??'—'} · {sample.quality} · {new Date(sample.sourceTime).toLocaleTimeString(en?'en-GB':'zh-CN',{timeZone:'UTC'})} UTC</output>}<br/><small>{trend.timeFrom} — {trend.timeTo} · UTC</small></p>;})}
  </div>;
}
type Props={card:CanvasCard;sources:AnalysisSources;en:boolean;active:boolean;onActivate:()=>void;onOpen:()=>void;onRelated?:(value:EvidenceSource)=>void;onPage?:(page:number,value:EvidenceSource)=>void;onTrend?:(id:string,value:SimulatedTrend)=>void;onAvailability?:(id:string,state:string)=>void;full?:boolean;onView?:(view:CardView)=>void;cursor?:number|null;onCursor?:(value:number|null)=>void};
export const AnalysisSourceCard=memo(function AnalysisSourceCard({card,sources,en,active,onActivate,onOpen,onRelated,onPage,onTrend,onAvailability,onView,cursor,onCursor,full=false}:Props){
  const [detail,setDetail]=useState<EvidenceDetail|null>(null),[image,setImage]=useState(''),[error,setError]=useState(false),[retry,setRetry]=useState(0),[slow,setSlow]=useState(false),[authorized,setAuthorized]=useState(''),[cancelled,setCancelled]=useState(false);
  const authorizationKey=card.source!.id+':'+active+':'+retry;
  const ref=card.source!;
  useEffect(()=>{let live=true;setDetail(null);setAuthorized('');setImage('');setError(false);setSlow(false);setCancelled(false);
    const timer=setTimeout(()=>{if(live)setSlow(true);},3000);
    void sources.detail(ref).then(value=>{if(live){setDetail(value);setAuthorized(authorizationKey);onAvailability?.(ref.id,value.availability);if(value.source?.samples)onTrend?.(card.id,value.source as SimulatedTrend);}}).catch(()=>{if(live){setError(true);onAvailability?.(ref.id,'unavailable');}}).finally(()=>clearTimeout(timer));
    return()=>{live=false;clearTimeout(timer);};
  },[sources,ref.id,ref.revision,retry,active]);
  useEffect(()=>{let live=true;const abort=new AbortController();if(cancelled||authorized!==authorizationKey||!active||detail?.availability!=='available'||!['photo','drawing','document'].includes(card.kind))return;
    const timer=setTimeout(()=>{if(live)setSlow(true);},3000);
    void sources.file(ref,detail.source,abort.signal).then(url=>{if(live){setImage(url);setSlow(false);}}).catch(()=>{if(live)setError(true);}).finally(()=>clearTimeout(timer));
    return()=>{live=false;abort.abort();clearTimeout(timer);};
  },[active,sources,detail,ref.id,retry,card.kind,authorized,authorizationKey,cancelled]);
  const value=detail?.source;
  if(error||detail&&detail.availability!=='available')return <div className="ac-source-state" role="status"><strong>{detail?.availability==='restricted'?(en?'Access removed':'资料访问已撤销'):(en?'Source temporarily unavailable':'资料暂时不可用')}</strong><small>{detail?.reason}</small><Btn onClick={()=>setRetry(v=>v+1)}><RefreshCw size={13}/>{en?'Retry':'重试'}</Btn></div>;
  if(!value)return <div className="ac-source-state" role="status">{slow?(en?'The source is slow. You can continue with other cards.':'来源读取较慢，可继续操作其他卡片。'):(en?'Loading source…':'正在读取资料…')}<Btn onClick={()=>setRetry(v=>v+1)}>{en?'Retry':'重新读取'}</Btn></div>;
  const asset=['photo','drawing','document'].includes(card.kind);
  return <div className={`ac-source ac-source-${card.kind}`} data-canvas-inner>
    <div className="ac-source-toolbar"><small>{card.historical?(en?'Historical reference':'历史参考'):en?'Fixed source':'固定来源'}{value.versionNumber?' · v'+value.versionNumber:''}</small>
      {!full&&<Btn onClick={onOpen}><ExternalLink size={13}/>{en?'Expand':'展开查看'}</Btn>}</div>
    {card.kind==='object'&&<><strong>{value.item?.displayName||card.title}</strong><p>{value.item?.identifiers?.filter(i=>i.role==='primary').map(i=>i.value).join(' · ')}</p><p>{value.item?.objectKind==='cabinet'?(en?'Cabinet':'柜体'):value.item?.objectKind==='unknown'?(en?'Type not classified':'类型未分类'):value.item?.objectKind} · {value.item?.objectScope==='definition'?(en?'Project definition':'项目定义'):value.item?.objectScope==='unclassified'?(en?'Scope not classified':'范围未分类'):value.item?.objectScope}</p><Btn onClick={()=>onRelated?.(value)}>{en?'Related materials':'推荐相关资料'}</Btn></>}
    {card.kind==='alarm'&&<><span className="ad-badge">{en?'Simulated alarm':'模拟报警'}</span><p>{value.dataset?.presetCause}</p><dl>{value.items?.map(row=><div key={row.sourceRevision}><dt>{row.state==='active'?(en?'Occurred':'发生'):(en?'Recovered':'恢复')}</dt><dd>{new Date(row.sourceTime).toLocaleString(en?'en-GB':'zh-CN')} · {row.severity}</dd></div>)}</dl></>}
    {card.kind==='trend'&&value.samples&&<><span className="ad-badge">{en?'Simulation · fixed window':'模拟数据 · 固定时间窗'}</span><AnalysisTrend trends={[value as SimulatedTrend]} en={en} cursor={cursor} onCursor={onCursor}/></>}
    {card.kind==='work_order'&&<><strong>{value.orderId} · r{value.orderRevision}</strong><p>{value.title} · {en?value.state:({open:'待受理',diagnosing:'诊断中',investigating:'排查中',review:'待复核',closed:'已关闭'} as Record<string,string>)[value.state||'']||value.state}</p>{value.investigation?.hypotheses?.map(h=><p key={h.id}>{h.description}<br/><small>{h.basis}</small></p>)}{full&&value.investigation?.steps?.map(step=><p key={step.id}>{step.title}<br/><small>{step.result||'尚无结果'}</small></p>)}<ul>{(full?value.events:value.events?.slice(-4))?.map((item,i)=><li key={i}>{en?item.action:({accept:'受理',investigate:'开始排查',submit:'提交复核',close:'关闭',create:'建立工单'} as Record<string,string>)[item.action]||item.action} · {item.note}</li>)}</ul><small>{value.diagnosis?.gap}</small></>}
    {card.kind==='document'&&<label className="ac-page">{en?'Page':'页码'}<input type="number" min={1} max={value.pageCount||1} aria-label={en?'Document page':'文档页码'} value={value.pageNumber||1} onChange={event=>{const page=Number(event.target.value);if(page>=1&&page<=(value.pageCount||1))onPage?.(page,value);}}/><span>/ {value.pageCount}</span>{value.newerVersionAvailable&&<small>{en?'Newer version available; this card retains its selected version.':'已有新版，此卡保持所选版本。'}</small>}</label>}
    {card.kind==='document'&&!!value.outline?.length&&<select aria-label={en?'Document section':'文档章节'} value={value.outline.find(row=>row.page===value.pageNumber)?.page||''} onChange={event=>onPage?.(Number(event.target.value),value)}><option value="" disabled>{en?'Go to section':'定位章节'}</option>{value.outline.map((row,i)=><option key={i} value={row.page}>{row.title}</option>)}</select>}
    {asset&&!value.selector&&<small>{en?'Page/image reference; no verified object region':'定位到整页/整图；暂无可靠对象区域'}</small>}
    {asset&&(active?(image?<div className="ac-photo-view"><WorkOrderPhotoViewport embedded key={ref.id} initialView={card.view as ImageView|undefined} onViewChange={onView} image={image} decodedImage={sources.decodedImage(image)} selector={value.selector||null} label={card.title} en={en} onError={()=>setError(true)}/></div>:<div className="ac-source-state" role="status">{cancelled?(en?'Loading cancelled':'已取消加载'):slow?(en?'Transfer is taking longer. Retry or continue other work.':'图片传输较慢，可以重试或继续操作其他资料。'):(en?'Loading image…':'正在载入图片…')}<Btn onClick={()=>setRetry(v=>v+1)}>{en?'Retry':'重试'}</Btn>{!cancelled&&<Btn onClick={()=>setCancelled(true)}>{en?'Cancel':'取消加载'}</Btn>}</div>):<Btn className="ac-open-media" onClick={onActivate}>{en?'Open '+materialNames[card.kind]:'打开'+materialNames[card.kind]}</Btn>)}
    {card.kind==='model3d'&&(active?<Suspense fallback={<p role="status">{en?'Loading viewer…':'正在载入查看器…'}</p>}><ModelCard api={sources.api as WorkbenchApi} version={value as ProjectModelVersion} en={en} initialView={card.view as ModelView|undefined} onView={onView}/></Suspense>:<><p>{value.displayName||card.title}</p><Btn onClick={onActivate}>{en?'Activate 3D':'启用三维查看'}</Btn></>)}
  </div>;
},(a,b)=>a.card.id===b.card.id&&a.card.kind===b.card.kind&&a.card.title===b.card.title&&a.card.historical===b.card.historical
  &&a.card.source?.id===b.card.source?.id&&a.card.source?.revision===b.card.source?.revision&&a.sources===b.sources&&a.en===b.en&&a.active===b.active&&a.full===b.full&&a.cursor===b.cursor);
