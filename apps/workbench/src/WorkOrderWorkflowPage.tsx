import {lazy, Suspense, useEffect, useMemo, useRef, useState} from 'react';
import {ArrowRight, FileText, Paperclip, Plus, RefreshCw, Search} from 'lucide-react';
import {ApiError, cancelled} from './api';
import {Btn, Modal} from './Primitives';
import {WorkOrderRecords} from './WorkOrderRecords';
import {WorkOrderAttachmentForm, WorkOrderAttachmentView} from './WorkOrderAttachments';
import {WorkOrderAnalysisView} from './WorkOrderAnalysisView';
import {orderRecordTime, orderActionLabel} from './workOrderHistory';
import {ORDER_ROOT, cockpitOrderApi, fixedAnalysis, orderFailure, workflowLabel, workflowState, workflowStates,
  type AnalysisCandidate, type DocumentVersion, type FixedAnalysis, type FixedAttachment, type Member,
  type OrderAlarm, type OrderApi, type TreatmentRecord, type WorkflowDetail, type WorkflowListing} from './workOrderWorkflow';
import type {WorkOrderReferenceEntry} from './workOrderReferences';
import './workOrderWorkflow.css';

const LegacyRecords=lazy(()=>import('./WorkOrders').then(module=>({default:module.WorkOrders})));
type Tab='record'|'analysis'|'attachments';
type Dialog='new'|'assign'|'complete'|'archive'|'reopen'|'void'|'copy'|'adopt'|'remove'|'clear';
type Mutation={path:string;body:object;success:(value:any)=>void};

export function WorkOrderWorkflowPage({api:workbenchApi, locale='zh', initialQuery='', initialAlarm, readOnly=false,
  onDirtyChange, onAnalyze, onOpenAnalysis, onOpenEditor, onOpenReference, initialRecord}:{
  api:OrderApi; locale?:string; initialQuery?:string; initialAlarm?:OrderAlarm|null; readOnly?:boolean;
  onDirtyChange?:(dirty:boolean)=>void; onAnalyze?:(orderId:string)=>void;
  onOpenAnalysis?:(id:string,revision:number,runId?:string)=>void;
  onOpenEditor?:(id:string,revision:number,saved?:boolean)=>void; onOpenReference?:(entry:WorkOrderReferenceEntry)=>void;
  initialRecord?:string;
}) {
  const api=useMemo(()=>readOnly?cockpitOrderApi(workbenchApi):workbenchApi,[workbenchApi,readOnly]);
  const en=locale==='en',t=(zh:string,english:string)=>en?english:zh;
  const [list,setList]=useState<WorkflowListing|null>(null);
  const [selected,setSelected]=useState(/^WO-|^DEMO-PDS-WO-/.test(initialQuery)?initialQuery:'');
  const [query,setQuery]=useState(initialQuery);
  const [filter,setFilter]=useState({q:initialQuery,state:'',mine:false});
  const [detail,setDetail]=useState<WorkflowDetail|null>(null);
  const [reload,setReload]=useState(0);
  const [busy,setBusy]=useState(false);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState<unknown>(null);
  const [unknown,setUnknown]=useState(false);
  const [tab,setTab]=useState<Tab>('record');
  const [dialog,setDialog]=useState<Dialog|null>(null);
  const [title,setTitle]=useState('');
  const [issue,setIssue]=useState('');
  const [faultCode,setFaultCode]=useState('');
  const [faultSystem,setFaultSystem]=useState('');
  const [equipment,setEquipment]=useState('');
  const [simulated,setSimulated]=useState(false);
  const [fromAlarm,setFromAlarm]=useState<OrderAlarm|null>(null);
  const [members,setMembers]=useState<Member[]>([]);
  const [handler,setHandler]=useState('');
  const [reason,setReason]=useState('');
  const [recordText,setRecordText]=useState(initialRecord||'');
  const [occurredAt,setOccurredAt]=useState('');
  const [correcting,setCorrecting]=useState<TreatmentRecord|null>(null);
  const [recordHistory,setRecordHistory]=useState<TreatmentRecord[]|null>(null);
  const [completionRecord,setCompletionRecord]=useState('');
  const [attachmentForm,setAttachmentForm]=useState<string|null>(null);
  const [attachment,setAttachment]=useState<FixedAttachment|null>(null);
  const [analysis,setAnalysis]=useState<FixedAnalysis|null>(null);
  const [choice,setChoice]=useState<AnalysisCandidate|null>(null);
  const [analyses,setAnalyses]=useState<AnalysisCandidate[]>([]);
  const [analysisQuery,setAnalysisQuery]=useState('');
  const [analysisFilter,setAnalysisFilter]=useState({q:'',all:false});
  const [analysisNext,setAnalysisNext]=useState<number|null>(null);
  const [analysisError,setAnalysisError]=useState<unknown>(null);
  const [readingAnalyses,setReadingAnalyses]=useState(false);
  const [legacy,setLegacy]=useState(false);
  const pending=useRef<Mutation|null>(null);
  const operation=useRef<AbortController|null>(null);
  const selectedRef=useRef(selected);selectedRef.current=selected;
  const alive=useRef(true);
  const read=useRef<AbortController|null>(null);
  const analysisRead=useRef<AbortController|null>(null);
  const workflow=detail?.workflow;
  const records=workflow?.records||[];
  const state=detail?workflowState(detail.state):null;
  const manage=!!detail?.canManage&&!readOnly;
  const process=!!detail?.canProcess&&!readOnly;
  const attach=!!detail?.canAttach&&!readOnly;
  const canCreate=!!list?.capabilities.canWrite&&!readOnly;
  const dirty=!!recordText.trim()||!!(dialog&&(title.trim()||issue.trim()||reason.trim()))||attachmentForm!==null||unknown;

  useEffect(()=>{alive.current=true;return()=>{alive.current=false;operation.current?.abort();read.current?.abort();analysisRead.current?.abort();};},[]);
  useEffect(()=>{onDirtyChange?.(dirty);return()=>onDirtyChange?.(false);},[dirty,onDirtyChange]);
  useEffect(()=>{
    const abort=new AbortController();read.current?.abort();read.current=abort;setLoading(true);
    void api.request<WorkflowListing>(ORDER_ROOT,{q:filter.q,state:filter.state,limit:30,
      ...(filter.mine&&detail?.actorId?{handlerId:detail.actorId}:{})},abort.signal).then(value=>{
      if(abort.signal.aborted)return;
      setList(value);
      if(!selectedRef.current&&value.items[0])setSelected(value.items[0].orderId);
    }).catch(value=>{if(!abort.signal.aborted)setError(value);}).finally(()=>{if(!abort.signal.aborted)setLoading(false);});
    return()=>abort.abort();
  },[api,api.epoch,api.revision,filter,reload,filter.mine?detail?.actorId:undefined]);
  useEffect(()=>{
    if(!selected)return;
    const abort=new AbortController();
    void api.request<WorkflowDetail>(ORDER_ROOT+'/workflow-detail',{orderId:selected},abort.signal)
      .then(value=>{if(!abort.signal.aborted)setDetail(value);})
      .catch(value=>{if(!abort.signal.aborted){setDetail(null);setError(value);}});
    return()=>abort.abort();
  },[api,api.epoch,api.revision,selected,reload]);
  useEffect(()=>{
    if(!selected)return;
    const abort=new AbortController();analysisRead.current?.abort();analysisRead.current=abort;
    setReadingAnalyses(true);setAnalyses([]);setAnalysisError(null);setAnalysisNext(null);
    void api.request<{items:AnalysisCandidate[];nextCursor:number|null}>(ORDER_ROOT+'/analyses',
      {orderId:selected,...analysisFilter},abort.signal).then(value=>{
      if(!abort.signal.aborted){setAnalyses(value.items);setAnalysisNext(value.nextCursor);}
    }).catch(value=>{if(!abort.signal.aborted)setAnalysisError(value);})
      .finally(()=>{if(!abort.signal.aborted)setReadingAnalyses(false);});
    return()=>abort.abort();
  },[api,api.epoch,api.revision,selected,reload,analysisFilter]);

  function select(id:string) {
    if(id===selected)return;
    setSelected(id);setDetail(null);setTab('record');setLegacy(false);
    setAnalysisQuery('');setAnalysisFilter({q:'',all:false});
    setRecordText('');setOccurredAt('');setCorrecting(null);setError(null);
  }

  async function moreOrders(){
    if(loading||!list?.nextCursor)return;
    const abort=new AbortController();read.current=abort;setLoading(true);setError(null);
    try{
      const value=await api.request<WorkflowListing>(ORDER_ROOT,{q:filter.q,state:filter.state,limit:30,
        cursor:list.nextCursor,expectedSnapshotRevision:list.snapshotRevision,
        ...(filter.mine&&detail?.actorId?{handlerId:detail.actorId}:{})},abort.signal);
      if(!abort.signal.aborted)setList({...value,items:[...list.items,...value.items]});
    }catch(value){if(!abort.signal.aborted)setError(value);}
    finally{if(!abort.signal.aborted)setLoading(false);}
  }

  async function moreAnalyses(){
    if(readingAnalyses||analysisNext===null)return;
    const abort=new AbortController();analysisRead.current=abort;setReadingAnalyses(true);
    try{
      const value=await api.request<{items:AnalysisCandidate[];nextCursor:number|null}>(ORDER_ROOT+'/analyses',
        {orderId:selected,...analysisFilter,cursor:analysisNext},abort.signal);
      if(!abort.signal.aborted){setAnalyses(rows=>[...rows,...value.items]);setAnalysisNext(value.nextCursor);}
    }catch(value){if(!abort.signal.aborted)setAnalysisError(value);}
    finally{if(!abort.signal.aborted)setReadingAnalyses(false);}
  }

  async function send(task?:Mutation){
    if(busy||readOnly)return false;
    if(task&&!pending.current)pending.current=task;
    const request=pending.current;if(!request)return false;
    setBusy(true);setError(null);
    const abort=new AbortController();operation.current=abort;
    try{
      const value=await api.request(request.path,request.body,abort.signal);
      if(!alive.current||abort.signal.aborted)return false;
      pending.current=null;setUnknown(false);request.success(value);setReload(n=>n+1);
      return true;
    }catch(value){
      if(alive.current&&!cancelled(value)){
        const uncertain=!(value instanceof ApiError)||value.status>=500||value.status===0;
        setUnknown(uncertain);if(!uncertain)pending.current=null;setError(value);
      }
      return false;
    }finally{if(alive.current)setBusy(false);}
  }
  const run=(path:string,body:object,success:(value:any)=>void=()=>setDialog(null))=>send({
    path:ORDER_ROOT+path,body:{...body,requestId:crypto.randomUUID()},success,
  });
  function update(action:string,fields:object={},success?:Mutation['success']){
    if(!detail)return Promise.resolve(false);
    return run('/workflow',{orderId:detail.orderId,expectedOrderRevision:detail.orderRevision,action,...fields},value=>{
      if(selectedRef.current===detail.orderId)setDetail({...detail,...value});
      setDialog(null);success?.(value);
    });
  }
  function startNew(alarm?:OrderAlarm) {
    setFromAlarm(alarm||null);setTitle(alarm?.title||'');setIssue('');
    setFaultCode(alarm?.faultCode||'');setFaultSystem('');setEquipment('');setSimulated(!!alarm);
    setError(null);setDialog('new');
  }
  function open(name:Dialog) {
    setError(null);setReason('');setDialog(name);
    if(name==='complete')setCompletionRecord('');
    if(name==='assign'&&detail){
      setMembers([{userId:detail.actorId,name:t('我自己','Myself')}]);setHandler(detail.actorId);
      const abort=new AbortController();
      void api.request<{items:Member[]}>(ORDER_ROOT+'/members',{},abort.signal).then(value=>{
        if(alive.current)setMembers([{userId:detail.actorId,name:t('我自己','Myself')},
          ...value.items.filter(row=>row.userId!==detail.actorId)]);
      }).catch(value=>{if(alive.current)setError(value);});
    }
  }
  function prepareCopy(item:AnalysisCandidate|null) {
    setChoice(item);setTitle((item?item.title+' · '+t('本次处理','This order'):detail?.title||'').slice(0,120));open('copy');
  }
  function submitRecord(){
    if(!recordText.trim())return;
    const fields={text:recordText.trim(),...(occurredAt?{occurredAt:new Date(occurredAt).toISOString()}:{}),
      ...(correcting?{recordId:correcting.recordId}:{})};
    void update(correcting?'correct_record':'record',fields,()=>{setRecordText('');setOccurredAt('');setCorrecting(null);});
  }
  async function readHistory(record:TreatmentRecord){
    if(!detail)return;
    const id=detail.orderId;
    try{
      const result=await api.request<{items:TreatmentRecord[]}>(ORDER_ROOT+'/record-history',{orderId:id,recordId:record.recordId});
      if(alive.current&&selectedRef.current===id)setRecordHistory(result.items);
    }catch(value){if(alive.current&&selectedRef.current===id)setError(value);}
  }
  const errorView=(error||unknown)?<div className="wov-error" role="alert">
    {unknown?t('提交结果待确认。','Save result is unknown.'):orderFailure(error,en)}
    {unknown?<Btn disabled={busy} onClick={()=>void send()}>{t('检查结果','Check result')}</Btn>:
      <Btn disabled={busy} onClick={()=>{setError(null);setReload(n=>n+1);}}>{t('重新读取','Reload')}</Btn>}
  </div>:null;
  const adopted=workflow?.adoptedAnalysis;
  const candidateAdopted=adopted&&analyses.find(item=>item.analysisSessionId===adopted.analysisSessionId&&item.analysisRevision===adopted.analysisRevision);
  const disabled=busy||unknown;
  const blockSelection=disabled||dirty;
  const dialogTitle:Record<Dialog,string>={new:t('新建工单','New work order'),assign:t('分派处理人','Assign handler'),
    complete:t('完成处理','Complete order'),archive:t('归档工单','Archive order'),reopen:t('重新处理','Reopen order'),
    void:t('作废并归档','Void and archive'),copy:choice?t('基于此分析修改','Copy analysis for editing'):t('新建分析','New analysis'),
    adopt:t('采纳分析','Adopt analysis'),remove:t('移出附件','Remove attachment'),clear:t('取消采纳','Clear adoption')};

  return <div className="wov-workspace">
    <aside className="wov-sidebar"><div className="wov-line"><strong>{t('项目工单','Project work orders')}</strong>
      {canCreate&&<Btn primary disabled={disabled} onClick={()=>startNew()}><Plus size={15}/>{t('新建工单','New order')}</Btn>}</div>
      {canCreate&&initialAlarm&&<Btn disabled={disabled} onClick={()=>startNew(initialAlarm)}>{t('从报警发起工单','Create order from alarm')}</Btn>}
      <form className="wov-search" onSubmit={event=>{event.preventDefault();setFilter(value=>({...value,q:query.trim()}));}}>
        <input aria-label={t('搜索工单','Search work orders')} value={query} placeholder={t('编号、标题或故障码','Number, title or fault code')}
          maxLength={200} onChange={event=>setQuery(event.target.value)}/>
        <Btn type="submit" disabled={loading||disabled} aria-label={t('搜索','Search')}><Search size={15}/></Btn>
      </form>
      <div className="wov-line"><select aria-label={t('工单状态','Order state')} value={filter.state} onChange={event=>setFilter(value=>({...value,state:event.target.value}))}>
        <option value="">{t('全部状态','All states')}</option>
        {workflowStates.map(value=><option key={value} value={value}>{workflowLabel(value,en)}</option>)}
      </select><label className="wov-inline"><input type="checkbox" checked={filter.mine} disabled={!detail}
        onChange={event=>setFilter(value=>({...value,mine:event.target.checked}))}/>{t('我处理的','Assigned to me')}</label></div>
      <div className="wov-order-list" aria-label={t('工单列表','Order list')}>
        {list?.items.map(item=><button type="button" key={item.orderId} aria-current={item.orderId===selected?'true':undefined}
          disabled={blockSelection&&item.orderId!==selected} onClick={()=>select(item.orderId)}>
          <span className="wov-line"><small>{item.orderId}</small><small>{workflowLabel(item.state,en)}</small></span>
          <strong>{item.title}</strong><small>{[item.faultCode,item.handler?.name,orderRecordTime(item.updatedAt,en)].filter(Boolean).join(' · ')}</small>
        </button>)}
      </div>
      {loading&&<small role="status">{t('正在读取工单','Loading orders')}</small>}
      {!loading&&list?.total===0&&<small>{t('暂无匹配工单','No matching orders')}</small>}
      {list?.nextCursor!=null&&<Btn disabled={loading||disabled} onClick={()=>void moreOrders()}>{t('更多工单','More orders')}</Btn>}
    </aside>
    <main className="wov-detail">
      {!dialog&&attachmentForm===null&&errorView}
      {detail&&state?<><header className="wov-header"><div><small>{detail.orderId} · r{detail.orderRevision}
        {detail.sourceKind==='simulated'?' · '+t('模拟','Simulation'):''}</small><h2>{detail.title}</h2>
        <div className="wov-actions"><span className="wov-tag">{workflowLabel(state,en)}</span>
          {detail.faultCode&&<span>{t('故障码','Fault code')} {detail.faultCode}</span>}
          {workflow?.equipment&&<span>{workflow.equipment}</span>}
          <span>{t('处理人','Handler')} {detail.handler?.name||'—'}</span></div>
      </div><div className="wov-actions end">
        {manage&&(state==='pending'||state==='processing'&&!detail.handler)&&<Btn primary disabled={disabled}
          onClick={()=>void update('accept')}>{state==='pending'?t('受理','Accept'):t('接手处理','Take over')}</Btn>}
        {process&&<Btn primary disabled={disabled||!!recordText.trim()} onClick={()=>open('complete')}>{t('完成处理','Complete')}</Btn>}
        {manage&&state==='completed'&&<Btn primary disabled={disabled} onClick={()=>open('archive')}>{t('归档','Archive')}</Btn>}
        {manage&&(state==='completed'||state==='archived')&&<Btn disabled={disabled} onClick={()=>open('reopen')}>{t('重新处理','Reopen')}</Btn>}
        {manage&&(state==='pending'||state==='processing')&&<details className="wov-more"><summary>{t('更多操作','More actions')}</summary>
          <div><Btn disabled={disabled} onClick={()=>open('assign')}>{state==='pending'?t('分派','Assign'):t('转交','Transfer')}</Btn>
            <Btn disabled={disabled} onClick={()=>open('void')}>{t('作废并归档','Void and archive')}</Btn></div></details>}
        <Btn disabled={disabled} aria-label={t('重新读取工单','Reload order')} onClick={()=>setReload(n=>n+1)}><RefreshCw size={15}/></Btn>
      </div></header>
      {workflow?.issue&&<p className="wov-issue">{workflow.issue}</p>}
      <nav className="wov-tabs" aria-label={t('工单详情','Order details')}>
        {([['record',t('处理记录','Records')],['analysis',t('相关分析','Related analyses')],['attachments',t('附件','Attachments')]] as const)
          .map(([key,label])=><button type="button" key={key} aria-current={tab===key?'page':undefined} onClick={()=>setTab(key)}>{label}</button>)}
      </nav>
      <div className="wov-content">
        {tab==='record'&&<>
          {(adopted||analyses.length>0)&&<button className="wov-related" type="button" onClick={()=>setTab('analysis')}>
            <FileText size={18}/><span><strong>{candidateAdopted?.title|| (adopted?t('本单采用的分析','Adopted analysis'):t('相关分析可参考','Related analyses available'))}</strong>
            <small>{adopted?'r'+adopted.analysisRevision:t('按故障码检索','Matched by fault code')}</small></span><ArrowRight size={16}/>
          </button>}
          {workflow?<WorkOrderRecords key={detail.orderId} orderId={detail.orderId} revision={detail.orderRevision}
            state={detail.state} simulated={detail.sourceKind==='simulated'} workflow={workflow} en={en}
            onOpenAttachment={setAttachment} onHistory={record=>void readHistory(record)}
            onAttach={attach?record=>setAttachmentForm(record.recordId):undefined}
            onCorrect={process?record=>{setCorrecting(record);setRecordText(record.text);setOccurredAt('');}:undefined}/>:
            <p className="wov-muted">{detail.state==='closed'?(detail.note||detail.investigation.conclusion||t('旧版未登记处理结果','Legacy order has no recorded result')):
              t('暂无新版处置记录','No treatment records in the new workflow')}</p>}
          {process&&<form className="wov-panel wov-form" onSubmit={event=>{event.preventDefault();submitRecord();}}>
            <label>{correcting?t('更正处置记录','Correct treatment record'):t('新增处置记录','Add treatment record')}
              <textarea value={recordText} maxLength={4000} rows={3} disabled={disabled}
                placeholder={t('记录检查、观察和处置结果','Record the checks, observations and results')}
                onChange={event=>setRecordText(event.target.value)}/></label>
            <details><summary>{t('发生时间（选填）','Time of treatment (optional)')}</summary>
              {correcting?.occurredAt&&<small>{t('留空沿用原记录时间。','Leave blank to keep the recorded time.')}</small>}
              <input aria-label={t('发生时间','Time of treatment')} type="datetime-local" value={occurredAt}
                disabled={disabled} onChange={event=>setOccurredAt(event.target.value)}/></details>
            <div className="wov-line">
              <Btn disabled={disabled} onClick={()=>setAttachmentForm('')}><Paperclip size={15}/>{t('添加附件','Add attachment')}</Btn>
              <div className="wov-actions end">
                {correcting&&<Btn disabled={disabled} onClick={()=>{setCorrecting(null);setRecordText('');setOccurredAt('');}}>{t('取消更正','Cancel correction')}</Btn>}
                <Btn primary type="submit" disabled={disabled||!recordText.trim()}>{t('保存记录','Save record')}</Btn>
              </div>
            </div>
          </form>}
          {!!detail.events.length&&<details className="wov-panel"><summary>{t('流转记录','Workflow history')}</summary>
            <ol className="wov-events">{detail.events.slice().reverse().map(event=><li key={event.revision}>
              <strong>{orderActionLabel(event.action,en)}</strong> <small>{event.actor} · {orderRecordTime(event.recordedAt,en)} · r{event.revision}</small>
              {event.note&&<p>{event.note}</p>}</li>)}</ol></details>}
          {detail.batchId!=='work-order-workflow-v1'&&<details className="wov-panel" onToggle={event=>setLegacy(event.currentTarget.open)}>
            <summary>{t('旧版诊断与资料','Legacy diagnosis and evidence')}</summary>
            {legacy&&<Suspense fallback={<p role="status">{t('正在读取','Loading')}</p>}>
              <LegacyRecords api={api} locale={locale} initialQuery={detail.orderId} onlyRecord={detail.orderId}
                onOpenAnalysis={onOpenAnalysis} onOpenReference={onOpenReference}/>
            </Suspense>}
          </details>}
        </>}
        {tab==='analysis'&&<>
          <div className="wov-line"><h3>{t('相关分析','Related analyses')}</h3>
            {process&&<Btn primary disabled={disabled} onClick={()=>prepareCopy(null)}><Plus size={15}/>{t('新建分析','New analysis')}</Btn>}
            {!detail.workflow&&!readOnly&&onAnalyze&&<Btn onClick={()=>onAnalyze(detail.orderId)}>{t('进入原分析','Open original analysis')}</Btn>}
          </div>
          {adopted&&<section className="wov-panel"><small>{t('本单采用','Adopted for this order')} · r{adopted.analysisRevision} · {adopted.actor}</small>
            <h3>{candidateAdopted?.title||t('已采纳分析','Adopted analysis')}</h3>
            <div className="wov-actions"><Btn onClick={()=>setAnalysis(adopted)}>{t('查看分析','View analysis')}</Btn>
              {process&&<Btn disabled={disabled} onClick={()=>open('clear')}>{t('取消采纳','Clear adoption')}</Btn>}</div>
          </section>}
          <form className="wov-search" onSubmit={event=>{event.preventDefault();setAnalysisFilter({q:analysisQuery.trim(),all:true});}}>
            <input aria-label={t('搜索分析','Search analyses')} placeholder={t('搜索可用分析名称','Search available analyses')} maxLength={120}
              value={analysisQuery} onChange={event=>setAnalysisQuery(event.target.value)}/>
            <Btn type="submit"><Search size={15}/>{t('搜索','Search')}</Btn>
            {analysisFilter.all&&<Btn onClick={()=>{setAnalysisQuery('');setAnalysisFilter({q:'',all:false});}}>{t('查看推荐','Recommendations')}</Btn>}
          </form>
          {readingAnalyses&&<p role="status">{t('正在读取相关分析','Loading analyses')}</p>}
          {!!analysisError&&<p role="alert">{orderFailure(analysisError,en)} <Btn onClick={()=>setReload(n=>n+1)}>{t('重试','Retry')}</Btn></p>}
          {!readingAnalyses&&!analysisError&&!analyses.length&&<small>{t('暂无匹配分析','No matching analyses')}</small>}
          {analyses.map(item=><article key={item.analysisSessionId} className="wov-panel">
            <small>{['r'+item.analysisRevision,item.sameCode?t('同故障码','Same fault code'):'',
              item.sameSystem?t('同代码体系','Same code system'):'',
              item.sameEquipment?t('同设备标记','Same equipment label'):'',
              item.equipmentMismatch?t('设备标记不同','Different equipment labels'):'',
              item.simulationMismatch?t('模拟与本单来源不同','Simulation differs from this order'):'',
              item.sameCode?t('适用性待核','Verify applicability'):''].filter(Boolean).join(' · ')}</small>
            <h3>{item.title}</h3>
            {item.applicability.summary&&<p>{item.applicability.summary}</p>}
            <div className="wov-actions">
              <Btn onClick={()=>setAnalysis(item)}>{t('查看','View')}</Btn>
              {process&&<><Btn disabled={disabled} onClick={()=>prepareCopy(item)}>{t('基于此分析修改','Make a copy')}</Btn>
                {(adopted?.analysisSessionId!==item.analysisSessionId||adopted.analysisRevision!==item.analysisRevision)&&
                  <Btn primary disabled={disabled} onClick={()=>{setChoice(item);open('adopt');}}>{t('采纳此分析','Adopt analysis')}</Btn>}
                <Btn disabled={disabled} onClick={()=>void update('link_analysis',fixedAnalysis(item))}>{t('关联参考','Link reference')}</Btn></>}
            </div>
          </article>)}
          {analysisNext!==null&&<Btn disabled={readingAnalyses} onClick={()=>void moreAnalyses()}>{t('更多分析','More analyses')}</Btn>}
          {!!detail.analysisLinks?.length&&<details className="wov-panel"><summary>{t('关联与采纳历史','Linked revisions')}</summary>
            <div className="wov-actions">{detail.analysisLinks.slice().reverse().map(item=><Btn key={item.orderRevision}
              onClick={()=>setAnalysis(item)}>{t('工单','Order')} r{item.orderRevision} · {t('分析','Analysis')} r{item.analysisRevision}</Btn>)}</div></details>}
        </>}
        {tab==='attachments'&&<>
          <div className="wov-line"><h3>{t('工单附件','Attachments')}</h3>
            {attach&&<Btn primary disabled={disabled} onClick={()=>setAttachmentForm('')}><Plus size={15}/>{t('添加附件','Add attachment')}</Btn>}</div>
          {!workflow?.attachments.length&&<small>{t('暂无附件','No attachments yet')}</small>}
          {workflow?.attachments.map(item=><div className="wov-file" key={item.attachmentId}>
            <FileText size={18}/><div><strong>{item.title}</strong>
              <small>v{item.versionNumber} · {item.actor} · {orderRecordTime(item.recordedAt,en)}</small></div>
            <Btn onClick={()=>setAttachment(item)}>{t('查看','View')}</Btn>
            {attach&&<Btn disabled={disabled} onClick={()=>{setAttachment(item);open('remove');}}>{t('移出','Remove')}</Btn>}
          </div>)}
        </>}
      </div></>:<p className="wov-content wov-muted">{t('选择工单查看处理记录','Select an order to view treatment records')}</p>}
    </main>
    {attachmentForm!==null&&detail&&<WorkOrderAttachmentForm api={api} order={detail} en={en} records={records} recordId={attachmentForm}
      locked={disabled} notice={errorView} onAttach={(item:DocumentVersion,recordId)=>update('attach',
        {documentId:item.documentId,contentVersionId:item.contentVersionId,...(recordId?{recordId}:{})},()=>setAttachmentForm(null))}
      onClose={()=>setAttachmentForm(null)}/>}
    {attachment&&detail&&dialog!=='remove'&&<WorkOrderAttachmentView api={api} order={detail} item={attachment} en={en} onClose={()=>setAttachment(null)}/>}
    {analysis&&<WorkOrderAnalysisView api={api} fixed={analysis} en={en} canShare={!readOnly&&(process||manage)}
      canEdit={!readOnly&&(process||manage)} onClose={()=>setAnalysis(null)}
      onEdit={item=>onOpenEditor?.(item.analysisSessionId,item.headRevision)}
      onShare={(item,share)=>run('/analysis-share',{...fixedAnalysis(item),share},()=>{})}/>}
    {recordHistory&&<Modal title={t('记录更正历史','Record corrections')} description={detail?.orderId||''} onClose={()=>setRecordHistory(null)}>
      <div className="wov-form">{recordHistory.map(row=><article className="wov-record" key={row.recordRevision}>
        <small>r{row.recordRevision} · {row.editedBy||row.actor} · {orderRecordTime(row.editedAt||row.recordedAt,en)}</small><p>{row.text}</p>
      </article>)}</div></Modal>}
    {dialog&&<Modal title={dialogTitle[dialog]} description={dialog==='new'?t('发起项目工单','Create project work order'):detail?.orderId||''} onClose={()=>!disabled&&setDialog(null)}>
      <div className="wov-form">
        {errorView}
        {dialog==='new'&&<>
          <label>{t('标题','Title')}<input value={title} maxLength={120} disabled={disabled} onChange={event=>setTitle(event.target.value)}/></label>
          <label>{t('问题说明','Issue')}<textarea value={issue} maxLength={4000} rows={3} disabled={disabled} onChange={event=>setIssue(event.target.value)}/></label>
          <label>{t('设备说明（选填）','Equipment (optional)')}<input value={equipment} maxLength={200} disabled={disabled} onChange={event=>setEquipment(event.target.value)}/></label>
          <div className="wov-form-row"><label>{t('故障码（选填）','Fault code (optional)')}
            <input value={faultCode} maxLength={100} disabled={disabled||!!fromAlarm} onChange={event=>setFaultCode(event.target.value)}/></label>
            {faultCode&&!fromAlarm&&<label>{t('代码体系（选填）','Code system (optional)')}
              <input value={faultSystem} maxLength={120} disabled={disabled} onChange={event=>setFaultSystem(event.target.value)}/></label>}</div>
          <label className="wov-inline"><input type="checkbox" checked={simulated} disabled={disabled||!!fromAlarm}
            onChange={event=>setSimulated(event.target.checked)}/>{t('模拟工单','Simulated order')}</label>
          <Btn primary disabled={disabled||!title.trim()||!issue.trim()} onClick={()=>void run('/create',
            {title:title.trim(),issue:issue.trim(),faultCode:faultCode.trim(),faultSystem:faultCode?faultSystem.trim():'',
              equipment:equipment.trim(),simulated,...(fromAlarm?{alarm:{datasetId:fromAlarm.datasetId,datasetRevision:fromAlarm.datasetRevision}}:{})},
            value=>{setFilter({q:'',state:'',mine:false});setQuery('');select(value.orderId);setDialog(null);})}>{t('提交工单','Submit order')}</Btn>
        </>}
        {dialog==='assign'&&<>
          <label>{t('处理人','Handler')}<select value={handler} disabled={disabled} onChange={event=>setHandler(event.target.value)}>
            {members.map(item=><option key={item.userId} value={item.userId}>{item.name}</option>)}</select></label>
          <label>{t('转交说明（选填）','Transfer note (optional)')}<textarea value={reason} maxLength={1000} onChange={event=>setReason(event.target.value)}/></label>
          <Btn primary disabled={disabled||!handler} onClick={()=>void update('assign',{handlerId:handler,reason:reason.trim()})}>{t('确认分派','Assign handler')}</Btn>
        </>}
        {dialog==='complete'&&<>
          {!!records.filter(item=>item.cycle===workflow?.cycle).length&&<label>{t('使用已保存记录','Use a saved record')}
            <select value={completionRecord} disabled={disabled} onChange={event=>setCompletionRecord(event.target.value)}>
              <option value="">{t('填写处理结果','Enter result')}</option>
              {records.filter(item=>item.cycle===workflow?.cycle).map(row=><option key={row.recordId} value={row.recordId}>{row.text.slice(0,80)}</option>)}
            </select></label>}
          {!completionRecord&&<label>{t('处理结果','Treatment result')}<textarea value={reason} maxLength={4000} disabled={disabled} onChange={event=>setReason(event.target.value)}/></label>}
          <Btn primary disabled={disabled||!completionRecord&&!reason.trim()} onClick={()=>void update('complete',
            completionRecord?{recordId:completionRecord}:{result:reason.trim()})}>{t('确认完成','Complete order')}</Btn>
        </>}
        {(dialog==='reopen'||dialog==='void')&&<>
          <label>{t('原因','Reason')}<textarea value={reason} maxLength={1000} disabled={disabled} onChange={event=>setReason(event.target.value)}/></label>
          <Btn primary disabled={disabled||!reason.trim()} onClick={()=>void update(dialog,{reason:reason.trim()})}>{dialogTitle[dialog]}</Btn>
        </>}
        {dialog==='archive'&&<><p>{workflow?.result?.text||t('归档保留现有处理记录。','Archiving keeps the saved treatment record.')}</p>
          <Btn primary disabled={disabled} onClick={()=>void update('archive')}>{t('确认归档','Archive order')}</Btn></>}
        {dialog==='copy'&&detail&&<>
          {choice&&<small>{choice.title} · r{choice.analysisRevision}</small>}
          <label>{t('分析名称','Analysis name')}<input value={title} maxLength={120} disabled={disabled} onChange={event=>setTitle(event.target.value)}/></label>
          <Btn primary disabled={disabled||!title.trim()} onClick={()=>void run('/analysis-draft',{orderId:detail.orderId,
            expectedOrderRevision:detail.orderRevision,title:title.trim(),...(choice?{base:fixedAnalysis(choice)}:{})},
            value=>{setDialog(null);onOpenEditor?.(value.analysisSessionId,value.analysisRevision,!recordText.trim());})}>
            {choice?t('另存并编辑','Save copy and edit'):t('创建并编辑','Create and edit')}</Btn>
        </>}
        {dialog==='adopt'&&choice&&<><p>{choice.title} · r{choice.analysisRevision}</p>
          <label>{t('采纳说明（选填）','Adoption note (optional)')}<textarea value={reason} maxLength={1000} disabled={disabled}
            onChange={event=>setReason(event.target.value)}/></label>
          <Btn primary disabled={disabled} onClick={()=>void update('adopt_analysis',{...fixedAnalysis(choice),reason:reason.trim()})}>
            {t('确认采纳此版本','Adopt this revision')}</Btn></>}
        {dialog==='remove'&&attachment&&<><p>{attachment.title} · v{attachment.versionNumber}</p>
          <Btn primary disabled={disabled} onClick={()=>void update('detach',{attachmentId:attachment.attachmentId},()=>setAttachment(null))}>{t('移出本单','Remove from this order')}</Btn></>}
        {dialog==='clear'&&<Btn primary disabled={disabled} onClick={()=>void update('clear_analysis')}>{t('确认取消采纳','Clear adoption')}</Btn>}
      </div>
    </Modal>}
  </div>;
}
