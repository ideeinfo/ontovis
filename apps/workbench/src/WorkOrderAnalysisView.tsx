import {useEffect, useState} from 'react';
import {ArrowUpRight, FileText} from 'lucide-react';
import {Btn, Modal} from './Primitives';
import {ORDER_ROOT, fixedAnalysis, orderFailure, type AnalysisReference, type FixedAnalysis, type OrderApi} from './workOrderWorkflow';
import {WorkOrderRecords} from './WorkOrderRecords';
import {HistoricalWorkOrder} from './HistoricalWorkOrder';
import type {EvidenceSource} from './analysisSources';
import type {CanvasCard} from './analysisCanvas';

export function WorkOrderAnalysisView({api, fixed, en, canShare, canEdit, onEdit, onClose, onShare}:{
  api:Pick<OrderApi,'request'>; fixed:FixedAnalysis; en:boolean; canShare:boolean; canEdit:boolean;
  onEdit?:(reference:AnalysisReference)=>void; onClose:()=>void; onShare?:(reference:AnalysisReference,shared:boolean)=>Promise<boolean>;
}) {
  const t=(zh:string,english:string)=>en?english:zh;
  const [reference,setReference]=useState<AnalysisReference|null>(null);
  const [error,setError]=useState<unknown>(null);
  const [busy,setBusy]=useState(false);
  const [card,setCard]=useState<CanvasCard|null>(null);
  const [source,setSource]=useState<EvidenceSource|null>(null);
  const [picture,setPicture]=useState('');
  const [reading,setReading]=useState(false);
  useEffect(()=>{
    const abort=new AbortController();setReference(null);setCard(null);setError(null);
    void api.request<AnalysisReference>(ORDER_ROOT+'/analysis-reference',fixedAnalysis(fixed),abort.signal)
      .then(value=>{if(!abort.signal.aborted)setReference(value);})
      .catch(value=>{if(!abort.signal.aborted)setError(value);});
    return()=>abort.abort();
  },[api,fixed.analysisSessionId,fixed.analysisRevision,fixed.analysisSha256]);
  useEffect(()=>{
    if(!card?.source)return;
    const abort=new AbortController();let url='';setReading(true);setSource(null);setPicture('');setError(null);
    const body={...fixedAnalysis(fixed),evidenceRefId:card.source.id};
    void api.request<{source:EvidenceSource}>(ORDER_ROOT+'/analysis-source',body,abort.signal).then(async value=>{
      if(abort.signal.aborted)return;
      setSource(value.source);
      if(['photo','drawing','document'].includes(card.kind)){
        const blob=await api.request<Blob>(ORDER_ROOT+'/analysis-source',{...body,content:true},abort.signal,'source');
        if(!abort.signal.aborted){url=URL.createObjectURL(blob);setPicture(url);}
      }
    }).catch(value=>{if(!abort.signal.aborted)setError(value);})
      .finally(()=>{if(!abort.signal.aborted)setReading(false);});
    return()=>{abort.abort();if(url)URL.revokeObjectURL(url);};
  },[api,card,fixed.analysisSessionId,fixed.analysisRevision,fixed.analysisSha256]);
  const snapshot=reference?.snapshot;
  const reuse=snapshot?.reuse;
  return <Modal className="wov-wide-dialog" title={snapshot?.title||t('查看分析','View analysis')}
    description={'r'+fixed.analysisRevision+' · '+t('固定版本','Fixed revision')} onClose={()=>!busy&&onClose()}>
    <div className="wov-form">
      {!!error&&<p role="alert">{orderFailure(error,en)}</p>}
      {!reference&&!error&&<p role="status">{t('正在读取分析','Loading analysis')}</p>}
      {snapshot&&reference&&<>
        {reuse?.summary&&<section className="wov-panel"><h3>{t('分析摘要','Analysis summary')}</h3><p>{reuse.summary}</p></section>}
        {reuse?.advice&&<section className="wov-panel"><h3>{t('排查建议','Recommended checks')}</h3><p>{reuse.advice}</p></section>}
        {snapshot.cards.filter(item=>item.kind==='analysis').map(item=><section className="wov-panel" key={item.id}>
          <h3>{item.title}</h3><p>{item.note}</p></section>)}
        {snapshot.cards.some(item=>item.source)&&<section className="wov-panel">
          <h3>{t('固定资料','Fixed sources')}</h3>
          <div className="wov-file-options">{snapshot.cards.filter(item=>item.source).map(item=><button type="button"
            key={item.id} aria-pressed={card?.id===item.id} onClick={()=>setCard(item)}><FileText size={15}/>{item.title}</button>)}</div>
          {reading&&<p role="status">{t('正在读取资料','Loading source')}</p>}
          {source&&card?.kind==='work_order'&&(source.workflow?<WorkOrderRecords orderId={source.orderId||''}
            revision={source.orderRevision||1} state={source.state||''} simulated={source.sourceKind==='simulated'}
            workflow={source.workflow} en={en}/>:<HistoricalWorkOrder source={source} en={en} full/>)}
          {source&&card?.kind==='object'&&<p>{source.item?.displayName} · {source.item?.entityUid}</p>}
          {source&&card?.kind==='document'&&<small>{t('固定页','Fixed page')} {source.pageNumber||1}</small>}
          {source&&card?.kind==='alarm'&&<p>{source.dataset?.title}</p>}
          {source&&card?.kind==='trend'&&<p>{source.timeFrom} — {source.timeTo} · {source.samples?.length||0} {t('个样本','samples')}</p>}
          {picture&&<img className="wov-file-preview" src={picture} alt={card?.title||''}/>}
        </section>}
        {reference.owned&&canShare&&<section className="wov-panel"><h3>{t('项目参考','Project reference')}</h3>
          <p>{reference.shared?t('本项目成员可按权限使用此固定版本。','Project members can use this fixed revision within their permissions.'):
            t('分享此保存版本的内容和固定资料，供本项目成员参考。','Share the saved contents and fixed sources with this project.')}</p>
          <Btn disabled={busy} onClick={async()=>{
            setBusy(true);try{if(await onShare?.(reference,!reference.shared))
              setReference(value=>value?{...value,shared:!value.shared}:value);}
            finally{setBusy(false);}
          }}>{reference.shared?t('撤回项目参考','Withdraw project reference'):t('供本项目参考','Share this revision with project')}</Btn>
        </section>}
        {reference.owned&&canEdit&&onEdit&&<div className="wov-actions end"><Btn primary onClick={()=>onEdit(reference)}>
          <ArrowUpRight size={15}/>{t('打开画布编辑','Open canvas for editing')}</Btn></div>}
      </>}
    </div>
  </Modal>;
}
