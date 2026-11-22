import {useEffect,useState} from 'react';
import {MapPin,Search} from 'lucide-react';
import {ApiError,cancelled,failureMessage,type WorkbenchApi} from './api';
import {Btn,Modal} from './Primitives';
import type {GlobePoint} from './cockpitSpace';

type Source='emodnet'|'repd';
type Observation={id:string;source:Source;sourceId:string;name:string;country:string|null;status:string|null;
  installation:string|null;capacityMw:number|null;turbineCount:number|null;sourceUpdated:string|null;
  locationAccuracy:string;longitude:number|null;latitude:number|null};
type Publication={retrievedAt:string;repdRelease:string;sources:Record<Source,{attribution:string;metadataUrl:string;licenseUrl:string}>};
type Page={items:Observation[];nextOffset:number|null;total:number;catalogRevision:string;publication:Publication};
type Detail={item:Observation&{bounds:number[]|null};catalogRevision:string;publication:Publication};
const ROOT='/api/workbench/regional-catalog';
const labels={emodnet:'EMODnet / CETMAR',repd:'UK REPD'};
const PAGE_SIZE=20;

export function RegionalCatalog({api,en,onClose,onLocate}:{api:WorkbenchApi;en:boolean;onClose:()=>void;onLocate:(point:GlobePoint)=>void}){
 const t=(zh:string,english:string)=>en?english:zh;
 const [input,setInput]=useState(''),[source,setSource]=useState<Source|''>('');
 const [query,setQuery]=useState<{q:string;source:Source|'';offset:number;catalogRevision?:string}>({q:'',source:'',offset:0});
 const [page,setPage]=useState<Page|null>(null),[selection,setSelection]=useState('');
 const [detail,setDetail]=useState<Detail|null>(null),[error,setError]=useState<unknown>(null),[detailError,setDetailError]=useState<unknown>(null);
 const [retry,setRetry]=useState(0);
 useEffect(()=>{
  const controller=new AbortController();
  setPage(null);setDetail(null);setSelection('');setError(null);
  void api.request<Page>(ROOT,{...query,limit:PAGE_SIZE},controller.signal)
   .then(value=>{if(!controller.signal.aborted)setPage(value);})
   .catch(value=>{if(!controller.signal.aborted&&!cancelled(value))setError(value);});
  return()=>controller.abort();
 },[api,api.epoch,api.revision,query,retry]);
 useEffect(()=>{
  setDetail(null);setDetailError(null);
  if(!page||!selection)return;
  const controller=new AbortController();
  void api.request<Detail>(ROOT,{id:selection,catalogRevision:page.catalogRevision},controller.signal)
   .then(value=>{if(!controller.signal.aborted)setDetail(value);})
   .catch(value=>{if(!controller.signal.aborted&&!cancelled(value))setDetailError(value);});
  return()=>controller.abort();
 },[api,api.epoch,api.revision,page,selection]);
 function search(){setQuery({q:input.trim(),source,offset:0});}
 function turn(offset:number){if(page)setQuery({...query,offset,catalogRevision:page.catalogRevision});}
 function retryList(){
  if(query.catalogRevision||query.offset)setQuery({q:query.q,source:query.source,offset:0});
  else setRetry(value=>value+1);
 }
 const location=(item:Observation)=>item.longitude!==null?t('来源参考点','Source reference point'):
  item.locationAccuracy==='unresolved_source_grid'?t('格网坐标待核对','Grid coordinates unverified'):
  item.locationAccuracy==='source_site_boundary'?t('来源边界','Source boundary'):t('暂无位置','No available location');
 const errorText=(value:unknown)=>value instanceof ApiError&&value.code==='CATALOG_CHANGED'
  ?t('目录版本已更新，请重新读取首页。','The directory was updated. Reload the first page.')
  :value instanceof ApiError&&value.code==='REGIONAL_CATALOG_UNAVAILABLE'
   ?t('区域目录暂不可用。','The regional directory is unavailable.'):failureMessage(value,en?'en':'zh');
 const item=detail?.item;
 const point=detail&&item&&item.longitude!==null&&item.latitude!==null?{
  sceneId:'regional:'+item.id,revision:detail.catalogRevision,name:item.name,
  longitude:item.longitude,latitude:item.latitude,reference:labels[item.source],
 }:null;
 return <Modal title={t('区域风电目录','Regional wind directory')}
  description={t('欧洲海上风场和英国规划来源。','European offshore wind farms and UK planning sources.')}
  className="pc-regional-dialog" onClose={onClose}>
  <form className="pc-regional-form" onSubmit={event=>{event.preventDefault();search();}}>
   <input aria-label={t('风场名称','Wind farm name')} placeholder={t('搜索名称','Search by name')} value={input} maxLength={120} onChange={event=>setInput(event.currentTarget.value)}/>
   <select aria-label={t('区域目录来源','Directory source')} value={source} onChange={event=>setSource(event.currentTarget.value as Source|'')}>
    <option value="">{t('全部来源','All sources')}</option><option value="emodnet">EMODnet</option><option value="repd">UK REPD</option>
   </select>
   <button type="submit" className="ov-btn"><Search size={15}/>{t('搜索','Search')}</button>
  </form>
  {!!error?<p role="alert">{errorText(error)} <Btn onClick={retryList}>{t('重新读取','Reload')}</Btn></p>:
   !page?<p role="status">{t('正在读取目录…','Loading directory…')}</p>:<>
    <p className="pc-regional-meta">{page.total} {t('条观测','observations')} · {t('采集','Collected')} {new Date(page.publication.retrievedAt).toLocaleDateString(en?'en-GB':'zh-CN')}</p>
    {page.items.length===0?<p role="status">{t('没有符合条件的观测。','No matching observations.')}</p>:
     <ul className="pc-regional-list">{page.items.map(row=><li key={row.id}>
      <button type="button" aria-expanded={row.id===selection} onClick={()=>setSelection(previous=>previous===row.id?'':row.id)}>
       <strong>{row.name}</strong><small>{[labels[row.source],row.country,row.status,location(row)].filter(Boolean).join(' · ')}</small>
      </button>
      {selection===row.id&&<div className="pc-regional-detail">
       {!!detailError?<p role="alert">{errorText(detailError)} <Btn onClick={retryList}>{t('重新读取','Reload')}</Btn></p>:
        item?.id!==row.id?<p role="status">{t('正在读取观测详情…','Loading observation…')}</p>:<>
         <dl className="cw-kv">
          <dt>{t('来源编号','Source record')}</dt><dd>{item.sourceId}</dd>
          <dt>{t('来源状态','Source status')}</dt><dd>{item.status||'—'}</dd>
          <dt>{t('装机容量','Reported capacity')}</dt><dd>{item.capacityMw===null?'—':item.capacityMw+' MW'}</dd>
          <dt>{t('风机数量','Reported turbines')}</dt><dd>{item.turbineCount??'—'}</dd>
          {item.sourceUpdated&&<><dt>{t('来源更新','Source update')}</dt><dd>{item.sourceUpdated}</dd></>}
          {item.bounds&&<><dt>{point?t('经纬度','Longitude / latitude'):t('边界范围','Boundary extent')}</dt>
           <dd>{point?[point.longitude,point.latitude].join(', '):item.bounds.join(', ')}</dd></>}
         </dl>
         {point&&<Btn onClick={()=>onLocate(point)}><MapPin size={14}/>{t('在地球上定位','Locate on globe')}</Btn>}
         <p className="pc-regional-meta">{page.publication.sources[item.source].attribution} <a href={page.publication.sources[item.source].metadataUrl} target="_blank" rel="noreferrer">{t('官方来源','Official source')}</a>
          {' · '}<a href={page.publication.sources[item.source].licenseUrl} target="_blank" rel="noreferrer">{t('许可','Licence')}</a></p>
        </>}
      </div>}
     </li>)}</ul>}
    {(query.offset>0||page.nextOffset!==null)&&<div className="pc-regional-pages">
     <Btn disabled={query.offset===0} onClick={()=>turn(Math.max(0,query.offset-PAGE_SIZE))}>{t('上一页','Previous')}</Btn>
     <Btn disabled={page.nextOffset===null} onClick={()=>{if(page.nextOffset!==null)turn(page.nextOffset);}}>{t('下一页','Next')}</Btn>
    </div>}
   </>}
 </Modal>;
}
