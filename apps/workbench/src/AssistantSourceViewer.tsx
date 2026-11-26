import {displayText} from './displayText';
import {useEffect,useMemo,useState} from 'react';
import type {DraftApi} from './AnalysisWorkspace';
import {AnalysisEvidenceViewer} from './AnalysisEvidenceViewer';
import {AnalysisSourceCard} from './AnalysisSourceCard';
import {AnalysisSources,type EvidenceSource,type SourceAnchor} from './analysisSources';
import type {CanvasCard} from './analysisCanvas';
import {ASSISTANT_ROOT,assistantMessage,assistantSourceAnchor,type AssistantSource} from './assistantApi';
import {taskMaterialName,type TaskCandidate} from './assistantTasks';
import {Btn,Modal} from './Primitives';
import './analysisMaterials.css';

// The existing evidence viewer and its bounded byte cache are shared with Canvas.
export type AssistantPreviewTarget={runId:string}&({reference:AssistantSource;candidate?:never;trigger?:never}|
 {reference?:never;candidate:TaskCandidate;trigger:HTMLButtonElement});
type SourceResponse={kind:'object'|'photo'|'document'|'drawing';source:EvidenceSource;revision:string;anchor?:SourceAnchor};
// Candidate previews and citations share the protected evidence viewer.
export function AssistantSourceViewer({api,runId,reference,candidate,trigger,en,onClose}:AssistantPreviewTarget&{api:DraftApi;en:boolean;onClose:()=>void}){
 const [value,setValue]=useState<SourceResponse|null>(null);
 const [error,setError]=useState<unknown>(null),[reload,setReload]=useState(0);
 const key=candidate?.key??reference!.key,field=candidate?'resultKey':'sourceKey';
 const sources=useMemo(()=>new AnalysisSources({...api,request<T>(path:string,body?:object,signal?:AbortSignal,image?:boolean|'model'|'source'){
  if(path.endsWith('/evidence/batch'))return api.request<SourceResponse>(ASSISTANT_ROOT+'/task-source',{runId,[field]:key},signal)
   .then(result=>({items:[{evidenceRefId:runId,sourceKind:result.kind,sourceRevision:result.revision,
    availability:'available',source:result.source}]} as T));
  const action=path.endsWith('/evidence/preview')?'task-source-preview':path.endsWith('/evidence/content')||path.endsWith('/evidence/preview-content')?'task-source-content':null;
  if(!action)return Promise.reject(new Error('Unsupported source operation'));
  const options=(body as {options?:object}|undefined)?.options;
  return api.request<T>(ASSISTANT_ROOT+'/'+action,{runId,[field]:key,...(options?{options}:{})},signal,image);
 }},runId),[api,runId,field,key]);
 useEffect(()=>()=>sources.dispose(),[sources]);
 useEffect(()=>{const abort=new AbortController();setValue(null);setError(null);
  void api.request<SourceResponse>(ASSISTANT_ROOT+'/task-source',{runId,[field]:key},abort.signal)
   .then(result=>{if(!abort.signal.aborted)setValue(result);}).catch(reason=>{if(!abort.signal.aborted)setError(reason);});
  return()=>abort.abort();
 },[api,runId,field,key,reload]);
 const name=displayText(value?.source.title||reference?.title||(candidate?taskMaterialName(candidate.title,en):(en?'Cited source':'引用原文')));
 const card:CanvasCard|null=value&&api.project?{id:key,kind:value.kind,title:name,
  x:0,y:0,width:400,height:300,pinned:false,source:{system:'ontobase',ontobaseConnectionId:api.project.ontobaseConnectionId,projectCode:api.project.projectCode,id:runId,revision:value.revision}}:null;
 const anchor=reference?assistantSourceAnchor(reference):value?.anchor;
 return <Modal className="ac-source-modal" title={name}
  description={candidate?(en?'Match evidence · ':'匹配依据 · ')+displayText(candidate.reason):(en?'Fixed source':'固定原文')} onClose={onClose}
  onCloseAutoFocus={event=>{if(trigger?.isConnected){event.preventDefault();trigger.focus();}}}>
  <div className="ac-expanded">{value&&card?value.kind==='drawing'||value.kind==='document'
   ?<AnalysisEvidenceViewer card={card} source={value.source} sources={sources} en={en} anchor={anchor}/>
   :<AnalysisSourceCard card={card} sources={sources} en={en} active full viewOnly onOpen={()=>{}} onActivate={()=>{}} onDeactivate={()=>{}}/>
   :<div className="ac-source-state" role="status">{error?assistantMessage(error,en):en?'Loading source…':'正在读取固定来源…'}{!!error&&<Btn onClick={()=>setReload(n=>n+1)}>{en?'Retry':'重试'}</Btn>}</div>}</div>
 </Modal>;
}
