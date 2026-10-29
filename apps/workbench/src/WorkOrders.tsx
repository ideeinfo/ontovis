import {useEffect,useRef,useState} from 'react';
import {AlertTriangle,ArrowRight,CheckCircle2,ClipboardList,Focus,GitBranch,Image,RefreshCw,Search} from 'lucide-react';
import {ApiError,cancelled,failureMessage,type WorkbenchApi} from './api';
import type {DiagnosticNode,Investigation,ObjectPhoto,OrderListing,OrderLocation,OrderState,WorkOrderDetail} from './workOrderTypes';
import {WorkOrderPhotoViewport} from './WorkOrderPhotoViewport';
import {InvestigationPanel} from './InvestigationPanel';
import {WorkOrderAssistantTransfers} from './WorkOrderAssistantTransfers';
import {photoCitation} from './workOrderInvestigation';
import {RowContext} from './ListMenus';
import {Btn} from './Primitives';
import './workOrders.css';

const ROOT='/api/workbench/work-orders';
const states:OrderState[]=['open','diagnosing','investigating','review','closed'];
const labels:Record<OrderState,[string,string]>={open:['待受理','Open'],diagnosing:['诊断中','Diagnosing'],investigating:['排查中','Investigating'],review:['待复核','In review'],closed:['已关闭','Closed']};
const nextAction:Record<OrderState,[string,string,string]>={open:['accept','受理并诊断','Accept & diagnose'],diagnosing:['investigate','开始排查','Start investigation'],investigating:['submit','提交复核','Submit for review'],review:['close','复核并关闭演练','Review & close exercise'],closed:['reopen','重新排查','Reopen']};
type OrderApi=Pick<WorkbenchApi,'request'|'content'|'revision'|'epoch'>;
const cabinetCode=(value:string)=>value==='CN'?'CN2':value;
const positions:Record<string,[number,number]>={alarm:[12,82],hypothesis:[205,82],'part-0':[400,10],'part-1':[400,108],'part-2':[400,206],CN1:[625,52],CN2:[625,172],gap:[205,280]};

function DiagnosticGraph({detail,en,selected,onLocate,busy}:{detail:WorkOrderDetail;en:boolean;selected:string;onLocate:(key:string)=>void;busy:boolean}){
  const graph=detail.diagnosis;
  return <section className="wo-card"><header><GitBranch size={16}/><h3>{en?'Source diagnostic reference':'来源诊断参照'}</h3><span className="wo-tag">{en?'Demo rules':'演示诊断规则'}</span></header>
    <div className="wo-graph-scroll"><div className="wo-graph" role="group" aria-label={en?'Reference diagnostic graph':'参照诊断图谱'}>
      <svg viewBox="0 0 820 370" aria-hidden="true"><defs><marker id="wo-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8" fill="none" stroke="currentColor"/></marker></defs>{graph.edges.map(edge=>{
        const from=positions[edge.source],to=positions[edge.target];if(!from||!to)return null;
        const [x,y]=from,[tx,ty]=to;
        return <path key={edge.source+edge.target} d={`M${x+170},${y+37} C${x+190},${y+37} ${tx-20},${ty+37} ${tx},${ty+37}`} markerEnd="url(#wo-arrow)"/>;
      })}</svg>
      {graph.nodes.map((node:DiagnosticNode)=>{const position=positions[node.id];if(!position)return null;
        const content=<><small>{node.kind==='alarm'?(en?'Simulated alarm':'模拟报警'):node.kind==='cabinet'?(en?'Demo cabinet':'演示柜体'):node.kind==='gap'?(en?'Evidence gap':'证据缺口'):node.kind==='hypothesis'?(en?'Hypothesis':'候选原因'):(en?'Reference object':'参照对象')}</small><strong>{node.label}</strong>{node.rds&&<span className="wo-mono">{node.rds}</span>}{node.locateKey&&<span className="wo-node-action"><Focus size={11}/>{en?'Object & photo':'对象与照片'}</span>}</>;
        return node.locateKey?<button type="button" key={node.id} style={{left:position[0],top:position[1]}} className={`wo-node ${node.kind} ${selected===node.locateKey?'selected':''}`} aria-pressed={selected===node.locateKey} disabled={busy} onClick={()=>onLocate(node.locateKey!)}>{content}</button>:<div key={node.id} style={{left:position[0],top:position[1]}} className={`wo-node ${node.kind}`}>{content}</div>;
      })}
    </div></div>
    <details className="wo-source"><summary>{en?'Rule source & applicability':'规则来源与适用性'}</summary><p>{graph.source.catalogue} · {graph.source.projectCode} · {en?'manual page':'手册页'} {graph.source.manualPages.join('、')} · {graph.revision}</p><p>{en?'Reference relationships from the source catalogue are used for this exercise. Demo-PDS applicability and root cause remain unconfirmed.':'来源目录的关系用于本次演练参照；Demo-PDS的工程适用性和根因仍待核实。'}</p><p>{graph.gap}</p></details>
  </section>;
}

function PhotoPanel({en,location,photos,chosen,image,reading,error,onOpen,onImageError}:{en:boolean;location:OrderLocation|null;photos:ObjectPhoto[]|null;chosen:ObjectPhoto|null;image:string;reading:boolean;error:string;onOpen:(photo:ObjectPhoto)=>void;onImageError:()=>void}){
  return <section className="wo-card"><header><Image size={16}/><h3>{en?'Object & photo location':'工程对象与照片定位'}</h3>{location&&<span className="wo-tag">{location.item.objectScope==='installation'?(en?'Demo installation':'演示安装对象'):location.item.objectScope==='definition'?(en?'Definition reference':'定义对象参照'):(en?'Project object reference':'项目对象参照')}</span>}</header>
    {!location?<p className="wo-empty">{en?'Select a graph object or cabinet to inspect its identity and photos.':'点击图谱中的对象或柜体，查看身份与照片位置。'}</p>:<>
      <div className="wo-object"><strong>{location.item.displayName}</strong><span className="wo-mono">{location.item.entityUid}</span><small>{location.context?.displayName||(en?'No installation assignment':'未分配安装范围')}{location.context&&' · '+(en?'Assumed hierarchy':'假定物理关系')}</small></div>
      {location.cabinetReference&&<p className="wo-caption">{en?'Project cabinet definition. Select a recorded member below to open its original photo annotation.':'项目柜级定义；从下方已登记的柜内对象中选择，打开原有照片标注。'}</p>}
      {location.definitionParent&&<p className="wo-caption">{en?'Recorded cabinet':'已登记所属柜体'}：{location.definitionParent.displayName} · {en?'User-provided project definition':'用户提供的项目定义归属'}</p>}
      {location.referenceMatch?.status==='needs_review'&&<p className="wo-caption">{en?'Recorded full primary tag · identifier review pending.':'完整主位号已记录，标识审核尚待完成。'}</p>}
      {photos?.length===0&&<p className="wo-empty">{en?'No stored photo association for this object. No region has been invented.':'该对象暂无已存照片关联，尚不能在照片中定位。'}</p>}
      {!!photos?.length&&<div className="wo-photo-list">{photos.map(photo=><button type="button" key={photo.evidenceRef} className="wo-photo-choice" aria-pressed={chosen?.evidenceRef===photo.evidenceRef} disabled={reading||!photo.selector||!!photo.unavailableReason} onClick={()=>onOpen(photo)}><Image size={14}/><span>{photo.title}<small>v{photo.versionNumber??'—'} · {photo.sourceRelation==='template_definition'?(en?'Fixed template reference':'固定型号来源'):(en?'Object association':'对象自身关联')}{photo.newerVersionAvailable?' · '+(en?'New version available':'有新版本'):''}{photo.anchorUnavailableReason?' · '+photo.anchorUnavailableReason:''}</small></span><ArrowRight size={13}/></button>)}</div>}
      {chosen&&image&&<><WorkOrderPhotoViewport key={chosen.evidenceRef+image} image={image} selector={chosen.selector} label={`${location.item.displayName} · ${chosen.title}`} en={en} onError={onImageError}/>
        <p className="wo-caption">{en?'Source annotation; applicability unverified. It does not confirm this installation or the root cause.':'区域来自已有标注，适用性待核实；不据此确认独立安装对象的现场一致性或故障根因。'}</p>
        <details className="wo-source"><summary>{en?'Fixed photo reference':'固定照片依据'}</summary><p>{chosen.contentVersionId}</p><p>{chosen.sourceRevision}</p><p>{chosen.selector?.displayRevision}</p></details></>}
    </>}
    {reading&&<p className="wo-empty" role="status">{en?'Checking identity and fixed photo bytes…':'正在核对对象身份与固定照片内容…'}</p>}{error&&<p className="wo-error" role="alert">{error}</p>}
  </section>;
}

export function WorkOrders({api,locale='zh',initialQuery='',onDirtyChange,onAnalyze,onOpenAnalysis}:{api:OrderApi;locale?:string;initialQuery?:string;onDirtyChange?:(dirty:boolean)=>void;onAnalyze?:(orderId:string)=>void;onOpenAnalysis?:(id:string,revision:number,runId?:string)=>void}){
  const en=locale==='en';
  const [list,setList]=useState<OrderListing|null>(null),[detail,setDetail]=useState<WorkOrderDetail|null>(null);
  const [selected,setSelected]=useState(''),[query,setQuery]=useState(initialQuery),[filter,setFilter]=useState({q:initialQuery,state:''});
  const [refresh,setRefresh]=useState(0),[error,setError]=useState<unknown>(null),[busy,setBusy]=useState(false),[loading,setLoading]=useState(false);
  const [note,setNote]=useState(''),[checks,setChecks]=useState<string[]>([]);
  const [plan,setPlan]=useState<Investigation|null>(null),[history,setHistory]=useState<{orderRevision:number;investigation:Investigation}|null>(null);
  const dirty=!!detail&&!!plan&&JSON.stringify(plan)!==JSON.stringify(detail.investigation);
  useEffect(()=>{onDirtyChange?.(dirty);return()=>onDirtyChange?.(false);},[dirty,onDirtyChange]);
  useEffect(()=>{const handler=(event:BeforeUnloadEvent)=>{if(dirty){event.preventDefault();event.returnValue='';}};window.addEventListener('beforeunload',handler);return()=>window.removeEventListener('beforeunload',handler);},[dirty]);
  const [location,setLocation]=useState<OrderLocation|null>(null),[photos,setPhotos]=useState<ObjectPhoto[]|null>(null);
  const [chosen,setChosen]=useState<ObjectPhoto|null>(null),[image,setImage]=useState(''),[photoError,setPhotoError]=useState<unknown>(null),[reading,setReading]=useState(false),[locateKey,setLocateKey]=useState('');
  const [cabinet,setCabinet]=useState(''),[referenceRds,setReferenceRds]=useState('');
  const [members,setMembers]=useState<OrderLocation['cabinetMembers']>();
  const alive=useRef(true),selectedRef=useRef(selected);selectedRef.current=selected;
  const picture=useRef(''),photoAbort=useRef<AbortController|null>(null),actionAbort=useRef<AbortController|null>(null);
  const pending=useRef<{fingerprint:string;body:object}|null>(null);
  function clearPhoto(){photoAbort.current?.abort();photoAbort.current=null;if(picture.current)URL.revokeObjectURL(picture.current);picture.current='';setImage('');setChosen(null);setPhotoError(null);setReading(false);}
  function useDetail(value:WorkOrderDetail){setDetail(value);setPlan(structuredClone(value.investigation));setChecks(value.checks);setNote(value.note);}
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;photoAbort.current?.abort();actionAbort.current?.abort();if(picture.current)URL.revokeObjectURL(picture.current);};},[]);
  useEffect(()=>{
    const abort=new AbortController();setLoading(true);setError(null);
    void api.request<OrderListing>(ROOT,{...filter,limit:50},abort.signal).then(value=>{if(!abort.signal.aborted){setList(value);if(!selectedRef.current&&value.items[0])setSelected(value.items[0].orderId);}})
      .catch(value=>{if(!abort.signal.aborted&&!cancelled(value)){setList(null);setError(value);}}).finally(()=>{if(!abort.signal.aborted)setLoading(false);});
    return()=>abort.abort();
  },[api,api.revision,api.epoch,filter,refresh]);
  useEffect(()=>{
    const abort=new AbortController();setDetail(null);setPlan(null);setHistory(null);setLocation(null);setPhotos(null);setLocateKey('');setCabinet('');setReferenceRds('');setMembers(undefined);clearPhoto();setError(null);pending.current=null;
    if(selected)void api.request<WorkOrderDetail>(ROOT+'/detail',{orderId:selected},abort.signal).then(value=>{if(!abort.signal.aborted)useDetail(value);})
      .catch(value=>{if(!abort.signal.aborted&&!cancelled(value))setError(value);});
    return()=>abort.abort();
  },[api,api.revision,api.epoch,selected,refresh]);
  async function seed(){
    if(busy||!list)return;setBusy(true);setError(null);const abort=new AbortController();actionAbort.current=abort;
    const fingerprint='seed:'+list.snapshotRevision;
    if(pending.current?.fingerprint!==fingerprint)pending.current={fingerprint,body:{requestId:crypto.randomUUID(),expectedSnapshotRevision:list.snapshotRevision}};
    try{await api.request(ROOT+'/seed-demo',pending.current.body,abort.signal);if(alive.current){pending.current=null;setRefresh(v=>v+1);}}
    catch(value){if(alive.current&&!cancelled(value))setError(value);}finally{if(alive.current)setBusy(false);}
  }
  async function action(name:string){
    if(busy||!detail||dirty&&name!=='save_diagnosis')return;setBusy(true);setError(null);const abort=new AbortController();actionAbort.current=abort;
    const content={orderId:detail.orderId,expectedOrderRevision:detail.orderRevision,action:name,checks,note,...(name==='save_diagnosis'?{investigation:plan}:{})};
    const fingerprint=JSON.stringify(content);
    if(pending.current?.fingerprint!==fingerprint)pending.current={fingerprint,body:{...content,requestId:crypto.randomUUID()}};
    try{const value=await api.request<WorkOrderDetail>(ROOT+'/action',pending.current.body,abort.signal);if(alive.current&&selectedRef.current===content.orderId){pending.current=null;useDetail(value);setList(previous=>previous?{...previous,items:previous.items.map(item=>item.orderId===value.orderId?value:item)}:previous);}}
    catch(value){if(alive.current&&!cancelled(value))setError(value);}finally{if(alive.current)setBusy(false);}
  }
  async function locate(key:string,referenceRds?:string,memberCursor?:string){
    if(!detail)return;
    if(!referenceRds&&!memberCursor){setMembers(undefined);setCabinet(['CN2','CN1'].includes(key)?key:'');setReferenceRds(['CN2','CN1'].includes(key)?'=WEC+'+key+'-':'');}
    clearPhoto();setLocation(null);setPhotos(null);setLocateKey(key);setReading(true);
    const abort=new AbortController();photoAbort.current=abort;
    try{
      const value=await api.request<OrderLocation>(ROOT+'/locate',{orderId:detail.orderId,locateKey:key,...(referenceRds?{referenceRds}:{}),...(memberCursor?{memberCursor}:{})},abort.signal);
      if(abort.signal.aborted)return;setLocation(value);if(value.cabinetMembers)setMembers(value.cabinetMembers);
      const body={entityUid:value.item.entityUid,expectedEntityRevision:value.item.entityRevision,installationContextId:value.item.installationContextId,
        expectedHierarchyRevision:value.context?.hierarchyRevision??null};
      const result=await api.request<{items:ObjectPhoto[]}>('/api/workbench/objects/photos/resolve',body,abort.signal);
      if(!abort.signal.aborted)setPhotos(result.items);
    }catch(value){if(!abort.signal.aborted&&!cancelled(value))setPhotoError(value);}finally{if(!abort.signal.aborted)setReading(false);}
  }
  async function openPhoto(photo:ObjectPhoto){
    if(!location||!photo.selector||!photo.sourceSha256)return;clearPhoto();setChosen(photo);setReading(true);
    const abort=new AbortController();photoAbort.current=abort;
    try{
      const blob=await api.content('/api/workbench/objects/photos/content',{entityUid:location.item.entityUid,expectedEntityRevision:location.item.entityRevision,
        installationContextId:location.item.installationContextId,expectedHierarchyRevision:location.context?.hierarchyRevision??null,
        evidenceRef:photo.evidenceRef,expectedSourceRevision:photo.sourceRevision,expectedContentVersionId:photo.contentVersionId,
        expectedSourceSha256:photo.sourceSha256,expectedDisplayRevision:photo.selector.displayRevision},
        {mime:['image/png','image/jpeg','image/webp'],maxBytes:20*1024*1024,sha256:photo.selector.displayRevision},abort.signal);
      if(!abort.signal.aborted){picture.current=URL.createObjectURL(blob);setImage(picture.current);}
    }catch(value){if(!abort.signal.aborted&&!cancelled(value))setPhotoError(value);}finally{if(!abort.signal.aborted)setReading(false);}
  }
  async function readHistory(orderRevision:number){
    if(!detail)return;const identifier=detail.orderId;setError(null);
    try{const value=await api.request<{orderRevision:number;investigation:Investigation}>(ROOT+'/diagnosis-history',{orderId:identifier,orderRevision});if(alive.current&&selectedRef.current===identifier)setHistory(value);}
    catch(value){if(alive.current&&selectedRef.current===identifier){setHistory(null);setError(value);}}
  }
  const canWrite=!!list?.capabilities.canWrite;
  const main=detail?nextAction[detail.state]:null;
  const requiresNote=detail&&['investigating','review','closed'].includes(detail.state);
  const incomplete=detail&&['investigating','review'].includes(detail.state)&&(checks.length!==detail.diagnosis.checks.length||!detail.investigationComplete);
  return <div className="wo-workspace">
    <aside className="wo-list"><div className="wo-list-head"><ClipboardList size={17}/><strong>{en?'Project work orders':'项目工单'}</strong><span className="wo-count">{list?.total??'—'}</span><button type="button" aria-label={en?'Reload work orders':'重新读取工单'} disabled={loading||busy||dirty} onClick={()=>setRefresh(v=>v+1)}><RefreshCw size={14}/></button></div>
      <form className="wo-search" onSubmit={event=>{event.preventDefault();setFilter(value=>({...value,q:query}));}}><Search size={14}/><input aria-label={en?'Search work orders':'搜索工单'} placeholder={en?'Code or title':'故障码或工单主题'} maxLength={200} value={query} onChange={event=>setQuery(event.target.value)}/><button type="submit">{en?'Search':'搜索'}</button></form>
      <label className="wo-filter">{en?'Status':'状态'}<select value={filter.state} onChange={event=>setFilter(value=>({...value,state:event.target.value}))}><option value="">{en?'All':'全部'}</option>{states.map(state=><option value={state} key={state}>{labels[state][en?1:0]}</option>)}</select></label>
      {loading&&<p className="wo-empty" role="status">{en?'Loading…':'正在读取…'}</p>}
      {!loading&&list?.total===0&&<div className="wo-empty"><p>{en?'No work orders in this project':'当前项目暂无工单'}</p>{list.capabilities.canSeedDemo&&<button type="button" className="wo-button primary" disabled={busy} onClick={()=>void seed()}>{en?'Create 20 demo orders':'生成20条演示工单'}</button>}</div>}
      <ul className="wo-order-list ov-list" aria-label={en?'Project work orders':'项目工单'}>{list?.items.map(item=><RowContext key={item.orderId} name={item.title} disabled={busy||dirty} actions={[{id:'open',label:en?'Open work order':'打开工单',icon:<ClipboardList/>,disabled:busy||dirty,onSelect:()=>setSelected(item.orderId)}]}><li className={`ov-list-item${selected===item.orderId?' selected':''}`}><button type="button" className="wo-order ov-list-main" aria-pressed={selected===item.orderId} disabled={busy||dirty} onClick={()=>setSelected(item.orderId)}><span className="wo-order-top"><span className="wo-mono">{item.faultCode}</span><span className={`wo-status ${item.state}`}>{labels[item.state][en?1:0]}</span></span><span className="ov-list-copy"><strong>{item.title}</strong><small>{String(item.number).padStart(3,'0')} · {cabinetCode(item.cabinet)} · {new Date(item.alarmAt).toLocaleString(en?'en-GB':'zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})}</small></span></button></li></RowContext>)}</ul>
    </aside>
    <div className="wo-main">{!!error&&<div className="wo-error" role="alert">{failureMessage(error,locale)} <button type="button" disabled={dirty||busy} onClick={()=>setRefresh(v=>v+1)}>{en?'Reload':'重新读取'}</button></div>}
      {!detail?<div className="wo-empty wo-welcome"><ClipboardList size={30}/><h2>{en?'Alarm to object evidence':'从报警走到对象证据'}</h2><p>{en?'Select an order to diagnose, investigate, locate photos and review.':'选择工单，沿诊断图谱排查、核对照片位置并完成复核。'}</p></div>:<>
        <header className="wo-detail-head"><div><span className="wo-tag">{en?'Simulated alarm · demo work order':'模拟报警 · 演示工单'}</span><h2>{detail.title}</h2><small className="wo-mono">{detail.orderId} · r{detail.orderRevision}</small></div>{onAnalyze&&['13001','13002','13003','13004'].includes(detail.faultCode)&&<Btn onClick={()=>onAnalyze(detail.orderId)}>{en?'Analyze in canvas':'进入分析画布'}</Btn>}<span className={`wo-status ${detail.state}`}>{labels[detail.state][en?1:0]}</span></header>
        {!!detail.analysisLinks?.length&&<section className="wo-panel"><header><strong>{en?'Linked analyses':'关联分析'}</strong></header><div className="wo-step-actions">{detail.analysisLinks.slice().reverse().map(link=><Btn key={link.orderRevision} onClick={()=>onOpenAnalysis?.(link.analysisSessionId,link.analysisRevision)}>{en?'Open linked analysis':'打开关联分析'} · r{link.analysisRevision}<small> · {en?'Work order':'工单'} r{link.orderRevision}</small></Btn>)}</div></section>}
        <ol className="wo-progress" aria-label={en?'Work order lifecycle':'工单流程'}>{states.map((state,index)=><li key={state} aria-current={detail.state===state?'step':undefined} className={states.indexOf(detail.state)>=index?'done':''}><span>{states.indexOf(detail.state)>index?<CheckCircle2 size={14}/>:index+1}</span>{labels[state][en?1:0]}</li>)}</ol>
        <section className="wo-alarm"><AlertTriangle size={19}/><div><strong>{en?'Alarm':'故障报警'} {detail.faultCode}</strong><span>{new Date(detail.alarmAt).toLocaleString(en?'en-GB':'zh-CN')} · {en?'Demo unit 07':'7号演示机组'} · {cabinetCode(detail.cabinet)}</span></div><span className="wo-tag">{en?'Simulated · no live source':'模拟数据 · 未接真实源'}</span></section>
        {plan&&<InvestigationPanel detail={detail} plan={plan} en={en} canWrite={canWrite} busy={busy} dirty={dirty} onChange={setPlan} onSave={()=>void action('save_diagnosis')} onDiscard={()=>setPlan(structuredClone(detail.investigation))} onLocate={key=>void locate(key)} citation={chosen&&location&&image?photoCitation(chosen,location):''}/>}
        <WorkOrderAssistantTransfers detail={detail} en={en} onOpenAnalysis={onOpenAnalysis} onFocusItem={!busy&&!dirty?id=>{const element=document.getElementById('wo-plan-'+id);element?.scrollIntoView({block:'center',behavior:'smooth'});element?.focus({preventScroll:true});}:undefined}/>
        <details className="wo-reference"><summary>{en?'Source graph & cabinet navigation (read only)':'来源参照图与柜体导航（只读）'}</summary><DiagnosticGraph detail={detail} en={en} selected={locateKey} onLocate={key=>void locate(key)} busy={reading}/></details>
        {cabinet&&<section className="wo-card"><header><Search size={16}/><h3>{cabinet} · {en?'Cabinet objects':'柜内对象'}</h3>{members&&<span className="wo-tag">{members.total} {en?'recorded':'已登记'}</span>}</header>
          <form className="wo-search" onSubmit={event=>{event.preventDefault();void locate(cabinet,referenceRds.trim());}}><input aria-label={en?'Full cabinet object tag':'柜内对象完整位号'} maxLength={200} value={referenceRds} onChange={event=>setReferenceRds(event.target.value)}/><button type="submit" disabled={reading||!referenceRds.trim().startsWith('=WEC+'+cabinet+'-')||referenceRds.trim().length<('=WEC+'+cabinet+'-').length+1}>{en?'Read object':'查阅对象'}</button></form>
          {members&&<><div className="wo-members">{members.items.map(item=>{const tag=item.identifiers?.find(identity=>identity.role==='primary'&&identity.value.startsWith('=WEC+'+cabinet+'-'))?.value;return <button type="button" className="wo-photo-choice" key={item.entityUid} disabled={reading||!tag} onClick={()=>{setReferenceRds(tag!);void locate(cabinet,tag);}}><span>{item.displayName}<small className="wo-mono">{tag}</small></span><ArrowRight size={13}/></button>;})}</div><div className="wo-actions"><button type="button" className="wo-button" disabled={reading} onClick={()=>void locate(cabinet)}>{en?'First page':'首屏'}</button>{members.nextCursor&&<button type="button" className="wo-button" disabled={reading} onClick={()=>void locate(cabinet,undefined,members.nextCursor!)}>{en?'Next page':'下一页'}</button>}</div></>}
          <p className="wo-caption">{en?'Cabinet membership is recorded from the user-provided project definition. Field installation and photo applicability remain separate.':'柜内归属按用户提供的项目定义登记；现场安装与照片适用性另行核实。'}</p></section>}
        <PhotoPanel en={en} location={location} photos={photos} chosen={chosen} image={image} reading={reading} error={photoError?failureMessage(photoError,locale):''} onOpen={photo=>void openPhoto(photo)} onImageError={()=>{if(picture.current)URL.revokeObjectURL(picture.current);picture.current='';setImage('');setPhotoError(new ApiError(502,'IMAGE_INVALID'));}}/>
        <section className="wo-card"><header><CheckCircle2 size={16}/><h3>{en?'Investigation & review':'排查与复核'}</h3>{!canWrite&&<span className="wo-tag">{en?'Read only':'只读'}</span>}</header><div className="wo-checks">{detail.diagnosis.checks.map(check=><label key={check.id}><input type="checkbox" checked={checks.includes(check.id)} disabled={!canWrite||busy||detail.state==='open'||detail.state==='closed'} onChange={event=>setChecks(value=>event.target.checked?[...value,check.id]:value.filter(key=>key!==check.id))}/><span>{check.label}</span></label>)}</div>
          <label className="wo-note">{en?'Exercise findings / review note':'演示处理记录 / 复核说明'}<textarea value={note} maxLength={2000} rows={3} disabled={!canWrite||busy} placeholder={en?'Record the exercise result and remaining evidence gaps.':'记录本次演练的处理、核对结果与仍需补充的依据。'} onChange={event=>setNote(event.target.value)}/></label>
          <div className="wo-actions">{canWrite&&main&&<button type="button" className="wo-button primary" disabled={busy||dirty||!!requiresNote&&!note.trim()||!!incomplete} onClick={()=>void action(main[0])}>{busy?(en?'Saving…':'正在保存…'):main[en?2:1]}<ArrowRight size={14}/></button>}{canWrite&&['diagnosing','investigating','review'].includes(detail.state)&&<button type="button" className="wo-button" disabled={busy||dirty} onClick={()=>void action('save')}>{en?'Save findings':'保存排查记录'}</button>}{canWrite&&detail.state==='review'&&<button type="button" className="wo-button" disabled={busy||!note.trim()} onClick={()=>void action('return')}>{en?'Return for investigation':'退回排查'}</button>}{incomplete&&<small>{en?'Save step results, conclusion and review basis, and complete all checks.':'保存逐项结果、结论与复核依据，并完成全部检查后可提交或关闭。'}</small>}</div>
        </section>
        {!!detail.investigationHistory?.length&&<details className="wo-card wo-history"><summary>{en?'Investigation revisions':'诊断修订历史'} <span>{detail.investigationHistory.length}</span></summary><div className="wo-plan-history">{detail.investigationHistory.map(row=><button type="button" className="wo-button" key={row.orderRevision} onClick={()=>void readHistory(row.orderRevision)}>r{row.orderRevision} · {row.actor} · {new Date(row.recordedAt).toLocaleString(en?'en-GB':'zh-CN')}</button>)}</div>{history&&<div className="wo-history-snapshot"><strong>{en?'Read-only snapshot':'只读快照'} r{history.orderRevision}</strong>{history.investigation.hypotheses.map(row=><p key={row.id}>{row.description} · {en?row.status:{candidate:'待核候选',supported:'记录支持',rejected:'记录排除'}[row.status]}<br/>{row.basis}</p>)}{history.investigation.steps.map((row,index)=><p key={row.id}>{index+1}. {row.title} · {en?row.outcome:{pending:'待排查',observed:'已记录观察',gap:'资料缺口',not_applicable:'不适用'}[row.outcome]}<br/>{row.result}</p>)}<p>{history.investigation.conclusion}</p><p>{history.investigation.reviewBasis}</p></div>}</details>}
        <details className="wo-card wo-history"><summary>{en?'Workflow history':'流转记录'} <span>{detail.events.length}</span></summary><ol>{detail.events.map(event=><li key={event.revision}><strong>{labels[event.to][en?1:0]}</strong><span>{event.actor} · {new Date(event.recordedAt).toLocaleString(en?'en-GB':'zh-CN')}</span><p>{event.note}</p></li>)}</ol></details>
      </>}
    </div>
  </div>;
}
