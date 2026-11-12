import {useEffect,useMemo,useState} from 'react';
import type {DraftApi} from './AnalysisWorkspace';
import {AnalysisEvidenceViewer} from './AnalysisEvidenceViewer';
import {AnalysisSources,type EvidenceSource} from './analysisSources';
import type {CanvasCard} from './analysisCanvas';
import {ASSISTANT_ROOT,assistantMessage,assistantSourceAnchor,type AssistantSource} from './assistantApi';
import {Btn,Modal} from './Primitives';
import './analysisMaterials.css';

// The existing evidence viewer and its bounded byte cache are shared with Canvas.
// The adapter only accepts stored run citations; it never registers a source.
export function AssistantSourceViewer({api,runId,reference,en,onClose}:{api:DraftApi;runId:string;reference:AssistantSource;en:boolean;onClose:()=>void}){
 const [value,setValue]=useState<{kind:'document'|'drawing';source:EvidenceSource;revision:string}|null>(null);
 const [error,setError]=useState<unknown>(null),[reload,setReload]=useState(0);
 const sources=useMemo(()=>new AnalysisSources({...api,request<T>(path:string,body?:object,signal?:AbortSignal,image?:boolean|'model'|'source'){
  const action=path.endsWith('/evidence/preview')?'task-source-preview':path.endsWith('/evidence/content')||path.endsWith('/evidence/preview-content')?'task-source-content':null;
  if(!action)return Promise.reject(new Error('Unsupported citation operation'));
  const options=(body as {options?:object}|undefined)?.options;
  return api.request<T>(ASSISTANT_ROOT+'/'+action,{runId,sourceKey:reference.key,...(options?{options}:{})},signal,image);
 }},runId),[api,runId,reference.key]);
 useEffect(()=>()=>sources.dispose(),[sources]);
 useEffect(()=>{const abort=new AbortController();setValue(null);setError(null);
  void api.request<{kind:'document'|'drawing';source:EvidenceSource;revision:string}>(ASSISTANT_ROOT+'/task-source',{runId,sourceKey:reference.key},abort.signal)
   .then(result=>{if(!abort.signal.aborted)setValue(result);}).catch(reason=>{if(!abort.signal.aborted)setError(reason);});
  return()=>abort.abort();
 },[api,runId,reference.key,reload]);
 const card:CanvasCard|null=value&&api.project?{id:reference.key,kind:value.kind,title:value.source.title||reference.title||reference.key,
  x:0,y:0,width:400,height:300,pinned:false,source:{system:'ontobase',ontobaseConnectionId:api.project.ontobaseConnectionId,projectCode:api.project.projectCode,id:runId,revision:value.revision}}:null;
 return <Modal className="ac-source-modal" title={value?.source.title||reference.title||(en?'Cited source':'引用原文')} description={en?'Read the fixed source without changing the canvas':'查看固定版本原文，不改变画布'} onClose={onClose}>
  <div className="ac-expanded">{value&&card?<AnalysisEvidenceViewer card={card} source={value.source} sources={sources} en={en} anchor={assistantSourceAnchor(reference)}/>:<div className="ac-source-state" role="status">{error?assistantMessage(error,en):en?'Loading source…':'正在读取固定来源…'}{!!error&&<Btn onClick={()=>setReload(n=>n+1)}>{en?'Retry':'重试'}</Btn>}</div>}</div>
 </Modal>;
}
