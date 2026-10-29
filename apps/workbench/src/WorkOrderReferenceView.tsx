import {lazy,Suspense,useEffect,useMemo,useState} from 'react';
import {ArrowLeft,BookOpen,RefreshCw} from 'lucide-react';
import {Btn} from './Primitives';
import {ApiError,cancelled,failureMessage} from './api';
import {AnalysisSourceCard} from './AnalysisSourceCard';
import {AnalysisSources,ANALYSIS_ROOT,type EvidenceSource} from './analysisSources';
import {referenceNames,workOrderReferenceCard,workOrderReferenceMaterial,type WorkOrderReferenceEntry} from './workOrderReferences';
import type {CanvasCard,CanvasSnapshot} from './analysisCanvas';
import type {DraftReceipt} from './analysisDraftState';
import type {DraftApi} from './AnalysisWorkspace';
import './analysisWorkspace.css';
import './analysisMaterials.css';
import './workOrderReferences.css';
const EvidenceViewer=lazy(()=>import('./AnalysisEvidenceViewer').then(module=>({default:module.AnalysisEvidenceViewer})));

export function WorkOrderReferenceView({api,entry,en,onReturn}:{api:DraftApi;entry:WorkOrderReferenceEntry;en:boolean;onReturn?:()=>void}){
 const t=(zh:string,english:string)=>en?english:zh,ref=entry.workOrderReference;
 const [loaded,setLoaded]=useState<{card:CanvasCard;source:EvidenceSource|null}|null>(null),[error,setError]=useState<unknown>(null),[attempt,setAttempt]=useState(0);
 const sources=useMemo(()=>new AnalysisSources(api,entry.analysisSessionId),[api,api.revision,api.epoch,entry.analysisSessionId,attempt]);
 useEffect(()=>()=>sources.dispose(),[sources]);
 useEffect(()=>{
  const abort=new AbortController();setLoaded(null);setError(null);
  const preview=['drawing','document'].includes(ref.kind)&&api.project?sources.detail({...api.project,system:'ontobase',id:ref.evidenceRefId,revision:ref.sourceRevision}):Promise.resolve(null);
  void Promise.all([api.request<DraftReceipt&{snapshot:CanvasSnapshot}>(ANALYSIS_ROOT+'/detail',{analysisSessionId:entry.analysisSessionId,analysisRevision:entry.analysisRevision},abort.signal),preview])
   .then(([detail,material])=>{if(!abort.signal.aborted)setLoaded({card:workOrderReferenceCard(entry,detail,api.project),source:material?workOrderReferenceMaterial(entry,material):null});})
   .catch(value=>{if(!abort.signal.aborted&&!cancelled(value))setError(value);});
  return()=>abort.abort();
 },[api,api.revision,api.epoch,entry,attempt,sources]);
 const message=error instanceof ApiError&&error.code==='WORK_ORDER_REFERENCE_CHANGED'?t('原引用与固定分析不一致，未替换为其他资料。请回到工单核对原采纳记录。','The reference does not match the fixed analysis. No substitute was opened. Return to the adoption record.'):error instanceof ApiError&&error.code==='WORK_ORDER_REFERENCE_UNAVAILABLE'?t('原资料当前不可读取，可能已撤权或版本不可用。未替换为其他资料。','The original source is not currently readable. Access or its fixed version may be unavailable. No substitute was opened.'):failureMessage(error,en?'en':'zh');
 return <section className="wr-review" aria-label={t('工单引用资料核对','Work order reference review')}>
  <header className="wr-heading">{onReturn&&<Btn onClick={onReturn}><ArrowLeft size={15}/>{t('返回工单','Return to order')}</Btn>}<div><h2><BookOpen size={17}/>{ref.key} · {referenceNames[ref.kind]?.[en?1:0]??t('引用资料','Reference')}</h2><small>{ref.orderId} · {t('采纳时','At adoption')} r{ref.orderRevision} · {t('分析','Analysis')} r{entry.analysisRevision}</small></div><span className="ad-badge">{t('原引用 · 只读','Original reference · read only')}</span></header>
  <p className="wr-caption">{t('按原资料身份与版本打开；浏览不修改工单，不调用助手。','Opened by its original identity and revision. Viewing does not change the order or call the assistant.')}</p>
  {!!error?<div className="wr-state" role="alert"><p>{message}</p><Btn onClick={()=>setAttempt(v=>v+1)}><RefreshCw size={14}/>{t('重新读取原引用','Retry original reference')}</Btn></div>:loaded?<div className="wr-source ac-expanded">{loaded.source?<Suspense fallback={<p role="status">{t('正在载入查看器…','Loading viewer…')}</p>}><EvidenceViewer key={loaded.card.source!.id+':'+attempt} card={loaded.card} source={loaded.source} anchor={ref.anchor} sources={sources} en={en}/></Suspense>:<AnalysisSourceCard key={loaded.card.source!.id+':'+attempt} card={loaded.card} sources={sources} en={en} active full onActivate={()=>{}} onDeactivate={()=>{}} onOpen={()=>{}}/>}</div>:<div className="wr-state" role="status">{t('正在读取原引用…','Loading original reference…')}</div>}
 </section>;
}
