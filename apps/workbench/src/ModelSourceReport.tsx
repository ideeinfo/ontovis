import {useEffect,useMemo,useState} from 'react';
import {ApiError,cancelled} from './api';
import {Btn,Modal} from './Primitives';
import {usePreferences} from './Preferences';
import {privateDenial,resourceFailure,ResourceRequestGate,resourceCalibrationKey} from './resourceForms';
import {resourceText} from './resourceMessages';
import {filterSourceNodes,identityStates,sourceIdentityLabel,type ModelInspectionReport,type SourceIdentityState} from './modelInspection';
import type {SceneApi} from './sceneApi';
import type {ProjectModelVersion} from './resourceTypes';
import './modelSourceReport.css';

export function ModelSourceReport({api,version,onClose,onPrivateDenied}:{api:SceneApi;version:ProjectModelVersion;onClose:()=>void;onPrivateDenied:()=>void}){
  const {locale}=usePreferences(),text=(zh:string,en:string)=>locale==='zh'?zh:en;
  const [report,setReport]=useState<ModelInspectionReport|null>(null),[error,setError]=useState<unknown>(null),[busy,setBusy]=useState(true),[reload,setReload]=useState(0);
  const [query,setQuery]=useState(''),[state,setState]=useState<SourceIdentityState|''>(''),[scope,setScope]=useState<'all'|'active'|'inactive'>('all');
  const [selected,setSelected]=useState<number|null>(null),[limit,setLimit]=useState(50);
  const gate=useMemo(()=>new ResourceRequestGate(),[]);
  useEffect(()=>{
    const request=gate.start();setReport(null);setError(null);setBusy(true);setSelected(null);
    api.modelInspection(version,request.signal).then(value=>{if(request.isCurrent())setReport(value);}).catch(value=>{
      if(!request.isCurrent()||cancelled(value))return;
      setError(value);if(privateDenial(value))onPrivateDenied();
    }).finally(()=>{if(request.isCurrent())setBusy(false);});
    return ()=>gate.cancel();
  },[api,version.modelVersionId,version.contentRevision,version.sha256,reload,gate]);
  const current=report?.modelVersionId===version.modelVersionId&&report.contentRevision===version.contentRevision&&report.sha256===version.sha256?report:null;
  const matches=useMemo(()=>filterSourceNodes(current?.sourceNodes??[],query,state,scope),[current,query,state,scope]);
  const visible=matches.slice(0,limit),node=visible.find(row=>row.nodeIndex===selected)??visible[0];
  function filter(action:()=>void){action();setLimit(50);setSelected(null);}
  const failure=error instanceof ApiError&&error.code==='RESOURCE_CHANGED'?text('固定版本已变化，请关闭报告后重新选择模型版本。','The fixed version changed. Close this report and select the model version again.'):
    error instanceof ApiError&&error.code==='MODEL_INSPECTION_UNAVAILABLE'?text('无法读取完整源属性报告，请稍后重试。','The complete source report is unavailable. Try again later.'):resourceFailure(error,locale);
  return <Modal title={text('源属性报告','Source property report')} description={text('固定模型源节点及未经核实的原始属性','Fixed model source nodes and unverified original properties')}
    className="ms-report-dialog" onClose={()=>{gate.cancel();onClose();}}><section className="ms-report">
    <div className="ms-heading"><strong>{version.displayName}</strong><span>{resourceText(locale,resourceCalibrationKey(version.calibrationState))}</span></div>
    <p className="ms-caption">{text('源文件声明未经工程核实；原模型校准保持。','Source claims are not engineering verification. Existing calibration is retained.')}</p>
    {busy&&<p role="status">{text('正在读取固定版本…','Reading fixed version…')}</p>}
    {!!error&&<div className="ms-failure"><p role="alert">{failure}</p>{!privateDenial(error)&&!(error instanceof ApiError&&error.code==='RESOURCE_CHANGED')&&<Btn onClick={()=>setReload(value=>value+1)}>{text('重试','Retry')}</Btn>}</div>}
    {current&&<>
      <div className="ms-counts">{identityStates.map(value=><span key={value}>{sourceIdentityLabel(value,locale)} <b>{current.sourceIdentityStates[value]??0}</b></span>)}</div>
      <div className="ms-filters"><label>{text('搜索节点','Search nodes')}<input value={query} placeholder={text('名称、编号或身份声明','Name, index or identity claim')} onChange={e=>filter(()=>setQuery(e.target.value))}/></label>
        <label>{text('声明状态','Claim state')}<select value={state} onChange={e=>filter(()=>setState(e.target.value as SourceIdentityState|''))}><option value="">{text('全部','All')}</option>{identityStates.map(value=><option key={value} value={value}>{sourceIdentityLabel(value,locale)}</option>)}</select></label>
        <label>{text('场景范围','Scene scope')}<select value={scope} onChange={e=>filter(()=>setScope(e.target.value as typeof scope))}><option value="all">{text('全部源节点','All source nodes')}</option><option value="active">{text('默认场景内','In default scene')}</option><option value="inactive">{text('默认场景外','Outside default scene')}</option></select></label>
      </div>
      <p className="ms-caption" role="status">{text(`匹配 ${matches.length} / ${current.sourceNodes.length} 个节点，已显示 ${visible.length} 个`,`Matching ${matches.length} / ${current.sourceNodes.length} nodes; showing ${visible.length}`)}</p>
      <div className="ms-grid"><div className="ms-list" aria-label={text('源节点列表','Source node list')}>
        {visible.map(row=><button type="button" key={row.componentKey} aria-pressed={node?.nodeIndex===row.nodeIndex} onClick={()=>setSelected(row.nodeIndex)}>
          <strong>#{row.nodeIndex} {row.name||text('未命名节点','Unnamed node')}</strong><small>{sourceIdentityLabel(row.sourceIdentityState,locale)} · {text(row.activeScene?'默认场景内':'默认场景外',row.activeScene?'In default scene':'Outside default scene')}</small>
        </button>)}
        {!matches.length&&<div><p>{text('没有匹配节点','No matching nodes')}</p><Btn onClick={()=>filter(()=>{setQuery('');setState('');setScope('all');})}>{text('清除筛选','Clear filters')}</Btn></div>}
        {limit<matches.length&&<Btn onClick={()=>setLimit(value=>value+50)}>{text('再显示50项','Show 50 more')}</Btn>}
      </div><article className="ms-node" aria-label={text('节点原始属性','Original node properties')}>
        {node&&<><h3>#{node.nodeIndex} {node.name||text('未命名节点','Unnamed node')}</h3><p>{sourceIdentityLabel(node.sourceIdentityState,locale)}</p>
          <p className="ms-caption">{text('节点编号及构件键仅对本固定版本有效。','Node indices and component keys apply only to this fixed version.')}</p>
          {!!node.sourceIdentityMissingFields.length&&<p>{text('缺少字段：','Missing fields: ')}{node.sourceIdentityMissingFields.join(', ')}</p>}
          {!!node.sourceIdentityInvalidFields.length&&<p>{text('格式错误：','Invalid fields: ')}{node.sourceIdentityInvalidFields.join(', ')}</p>}
          {node.sourceIdentityState==='collision'&&<p>{text('同文件存在重复声明，默认场景外节点也纳入检查。','This file has duplicate claims, including nodes outside the default scene.')}</p>}
          <h4>{text('原始属性（extras）','Original properties (extras)')}</h4>
          {node.sourceExtrasPresent?<pre tabIndex={0}>{JSON.stringify(node.sourceExtras,null,2)}</pre>:<p>{text('源节点未提供 extras 字段。','The source node has no extras field.')}</p>}
          <details><summary>{text('版本内构件键','Version-local component key')}</summary><code>{node.componentKey}</code></details>
        </>}
      </article></div>
      <details className="ms-provenance"><summary>{text('报告来源与范围','Report identity and scope')}</summary><dl>
        <dt>{text('固定版本','Fixed version')}</dt><dd>{current.modelVersionId}</dd><dt>{text('内容修订','Content revision')}</dt><dd>{current.contentRevision}</dd>
        <dt>{text('文件摘要','File digest')}</dt><dd>{current.sha256}</dd><dt>{text('节点目录摘要','Node catalog digest')}</dt><dd>{current.catalogSha256}</dd>
        <dt>{text('处理器摘要','Processor digest')}</dt><dd>{current.processorSha256}</dd></dl>
        <p>{text('GLB局部坐标未核实。源身份、几何对应、绑定迁移及工程发布资格均未确认；模型层级不代表现场物理层级。','GLB local coordinates are unverified. Source identity, geometry correspondence, binding migration and engineering release readiness remain unconfirmed. Model hierarchy does not establish installed hierarchy.')}</p>
      </details>
    </>}
  </section></Modal>;
}
