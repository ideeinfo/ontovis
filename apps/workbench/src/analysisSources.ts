import type {DraftApi} from './AnalysisWorkspace';
import type {CanvasCard,SourceRef} from './analysisCanvas';
import type {ProjectModelVersion} from './resourceTypes';
import type {PhotoSelector} from './workOrderTypes';
import type {Investigation,DiagnosticNode} from './workOrderTypes';
import type {ObjectClassification} from './types';
import type {SimulatedTrend,SimulatedDataset,SimulatedAlarm} from './simulatedAlarms';
import type {WorkOrderReferenceEntry} from './workOrderReferences';
import type {Workflow} from './workOrderWorkflow';
import type {FixedDocument} from './equipmentApi';

export const ANALYSIS_ROOT='/api/workbench/analysis-sessions';
export type AnalysisEntry={projectOnly:true}|{entityUid:string;expectedEntityRevision:string;timeTo:string}|{datasetId:string;datasetRevision:string}|{orderId:string}|{analysisSessionId:string;analysisRevision:number;assistantRunId?:string;assistantQuestion?:string;openLatest?:true}|{newDraft:true}|WorkOrderReferenceEntry;
export function assistantEntrySeed(entry:AnalysisEntry|null|undefined,receipt:{analysisSessionId:string;analysisRevision:number}|null,questionUsed=false){
 if(!entry||!('analysisSessionId'in entry)||!receipt||entry.analysisSessionId!==receipt.analysisSessionId)return {};
 return {initialQuestion:questionUsed||!('assistantQuestion'in entry)?undefined:entry.assistantQuestion,
  initialRunId:entry.analysisRevision===receipt.analysisRevision?entry.assistantRunId:undefined};
}
export function analysisEntryRequest(entry:AnalysisEntry,requestId:string){
 if('newDraft'in entry)return null;
 if('analysisSessionId'in entry){const fixed=!('openLatest'in entry&&entry.openLatest);
  return {path:ANALYSIS_ROOT+'/detail',body:{analysisSessionId:entry.analysisSessionId,...(fixed?{analysisRevision:entry.analysisRevision}:{})},fixed};
 }
 return {path:ANALYSIS_ROOT+'/start',body:{entry,requestId},fixed:false};
}
export type SourceKind='object'|'drawing'|'document'|'photo'|'model'|'trend'|'alarm'|'work_order';
export type RecommendationMatch='binding'|'historical_binding'|'name_candidate'|'catalogue_search'|'simulation_mapping'|'simulation_rule';
export type RecommendationRelevance='field_record'|'same_event'|'selected_object'|'object_association'|'shared_definition'|'binding'|'fault_evidence'|'simulation_mapping'|'same_object_fault'|'descendant'|'shared_photos'|'model_applicable'|'same_fault'|'historical_binding'|'simulation_rule'|'name_candidate'|'catalogue_search';
export type Recommendation={key:string;kind:SourceKind;title:string;reason:string;reasonEn?:string;identifier?:string;selector:Record<string,string|number>;preview?:EvidenceSource;matchType?:RecommendationMatch;relevance?:RecommendationRelevance;relevancePriority?:number;assetKey?:string;availability?:'available'|'unavailable'|'field_record'};
export type Recommendations={items:Recommendation[];nextOffset:number|null;nextCursor?:string|null;gaps:string[];dataset:SimulatedDataset|null;order?:'relevance'|'source'};
export type EvidenceSource=Partial<Omit<ProjectModelVersion,'state'> & SimulatedTrend>&{
  title?:string;pageNumber?:number;pageCount?:number;versionNumber?:number;newerVersionAvailable?:boolean;
  documentId?:string;contentVersionId?:string;currentContentVersionId?:string;sourceSha256?:string;selector?:PhotoSelector|null;
  photoPurpose?:'object_location'|'field_record';sourceType?:'project_document';equipmentEntityUid?:string|null;
  outline?:{title:string;page:number}[];
  knowledgeReleaseId?:string;knowledgeNodeId?:string;
  item?:{entityUid:string;entityRevision:string;displayName?:string;objectKind?:string;objectScope?:string;classification?:ObjectClassification|null;identifiers?:{value:string;role:string}[];definitionParentEntityUid?:string};
  dataset?:SimulatedDataset;items?:SimulatedAlarm[];mappingKind?:string;
  orderId?:string;orderRevision?:number;faultCode?:string;state?:string;investigation?:Investigation;
  workflow?:Workflow;snapshotSha256?:string;sourceKind?:'simulated'|'manual';
  checks?:string[];note?:string;
  diagnosis?:{gap?:string;nodes?:DiagnosticNode[]};events?:{recordedAt:string;action:string;note:string}[];
};
export type EvidenceDetail={evidenceRefId:string;sourceKind:SourceKind;sourceRevision:string;availability:'available'|'restricted'|'unavailable'|'changed';reason?:string;source?:EvidenceSource;photoTicket?:string};
export type SourceAnchor={entityUid?:string;selector?:PhotoSelector|null;componentKeys?:string[];nodeId?:string;pageNumber?:number;drawingUid?:string;referenceKind?:'name_candidate'|'historical_binding'};
export type SourceRelationshipGap={evidenceRefId:string;reason:string};
export type SourceRelationship={id:string;fromRef:string;toRef:string;kind:string;label:string;reason:string;origin:'source'|'candidate';anchor:SourceAnchor|null};
export type DrawingClassification={code:string;revisionId?:string;tableRevision?:string;nameZh?:string;nameEn?:string;reviewState?:string};
export type PreviewRow={id:string;title:string;identifier?:string;owner?:string;ownerId?:string|null;objectType?:string|null;classification?:DrawingClassification|null;bbox?:{x:number;y:number;width:number;height:number}|null;pathPoints?:Array<{x:number;y:number}>|null;state?:string;properties?:Record<string,unknown>;sourceInstanceId?:string;selector?:Record<string,string>;targetTitle?:string;targetDrawingUid?:string;targetRevision?:string;reason?:string;semantics?:string;entityUid?:string};
export type KnowledgeNode={id:string;kind:string;title:string;statement:string;faultCode?:string;properties:Record<string,string>};
export type SourcePreview={kind:string;title?:string;drawingUid?:string;drawingNumber?:string;pageNumber?:number;sourceRevision?:string;focusId?:string;selector?:PhotoSelector|null;gaps:string[];nextCursor:number|null;total?:number;objects?:PreviewRow[];ports?:PreviewRow[];connections?:PreviewRow[];references?:PreviewRow[];nodes?:KnowledgeNode[];relations?:{id:string;from:string;to:string;label:string}[];evidence?:{id:string;text:string;page:number;bbox:PreviewRow['bbox'];renditionId?:string}[];scope?:Record<string,unknown>;limitations?:Record<string,unknown>;releaseId?:string};

export function documentVersionChoice(source:EvidenceSource,version:FixedDocument,page:number):Recommendation|null {
  if(!source.newerVersionAvailable||!source.contentVersionId||version.kind!=='pdf'||version.documentId!==source.documentId
    ||version.contentVersionId!==source.currentContentVersionId||version.contentVersionId===source.contentVersionId
    ||!Number.isInteger(page)||!Number.isInteger(version.pageCount)||page<1||page>Math.min(version.pageCount,10000)
    ||!/^[a-f0-9]{64}$/.test(version.sourceSha256))return null;
  return {key:version.contentVersionId,kind:'document',title:version.title,reason:'',selector:{documentId:version.documentId,
    contentVersionId:version.contentVersionId,sourceSha256:version.sourceSha256,pageNumber:page}};
}

export function keepFixedDocumentCard(card:CanvasCard,source:EvidenceSource):boolean {
  return !!(card.historical||source.knowledgeReleaseId||source.knowledgeNodeId);
}

export function setCardPreviewOpen(current:ReadonlySet<string>,id:string,open:boolean):ReadonlySet<string>{
  if(current.has(id)===open)return current;
  const next=new Set(current);if(open)next.add(id);else next.delete(id);return next;
}


// One workspace owns this short-lived cache. Metadata is authorized on every
// mount/open; only fixed bytes are reused after that read. Nothing is persisted.

type FileTransfer={abort:AbortController;foreground:boolean};

export class AnalysisSources{
  private pending=new Map<string,{resolve:(value:EvidenceDetail)=>void;reject:(error:unknown)=>void}[]>();
  private scheduled=false;private disposed=false;private controllers=new Set<AbortController>();
  private files=new Map<string,{url:string;bytes:number}>();
  private inflight=new Map<string,{promise:Promise<string>;transfer:FileTransfer;users:number}>();
  private decoded=new Map<string,HTMLImageElement>();
  private light=0;private lightQueue:(()=>void)[]=[];
  private fileCount=0;
  private fileQueue:{transfer:FileTransfer;start:()=>void}[]=[];
  readonly api:DraftApi;readonly sessionId:string;
  constructor(api:DraftApi,sessionId:string){this.api=api;this.sessionId=sessionId;}
  decodedImage(url:string){for(const [key,file] of this.files)if(file.url===url){const image=this.decoded.get(key);if(image){this.decoded.delete(key);this.decoded.set(key,image);}return image;}return undefined;}
  private async detailSlot(){
    if(this.disposed)throw new DOMException('Closed','AbortError');
    if(this.light>=4){await new Promise<void>(resolve=>this.lightQueue.push(resolve));
      if(this.disposed)throw new DOMException('Closed','AbortError');return;}
    this.light++;
  }
  private releaseDetailSlot(){
    const next=this.lightQueue.shift();
    if(next)next();else this.light--;
  }
  private async fileSlot(transfer:FileTransfer){
    const signal=transfer.abort.signal;
    if(this.disposed||signal.aborted)throw new DOMException('Closed','AbortError');
    if(this.fileCount<2){this.fileCount++;return;}
    await new Promise<void>((resolve,reject)=>{
      const queued={transfer,start:()=>{
        signal.removeEventListener('abort',cancel);
        resolve();
      }};
      const cancel=()=>{
        this.fileQueue=this.fileQueue.filter(item=>item!==queued);
        reject(new DOMException('Closed','AbortError'));
      };
      this.fileQueue.push(queued);
      signal.addEventListener('abort',cancel,{once:true});
    });
  }
  private releaseFileSlot(){
    const next=this.fileQueue.findIndex(item=>item.transfer.foreground);
    const [queued]=this.fileQueue.splice(Math.max(0,next),1);
    if(queued)queued.start();else this.fileCount--;
  }
  detail(ref:SourceRef):Promise<EvidenceDetail>{
    return new Promise((resolve,reject)=>{
      if(this.disposed){reject(new DOMException('Closed','AbortError'));return;}
      const group=this.pending.get(ref.id)||[];group.push({resolve,reject});this.pending.set(ref.id,group);
      if(!this.scheduled){this.scheduled=true;queueMicrotask(()=>void this.flush());}
    });
  }
  private async flush(){
    this.scheduled=false;const entries=[...this.pending];this.pending.clear();
    for(let start=0;start<entries.length;start+=12){const batch=entries.slice(start,start+12);
      void (async()=>{let acquired=false;const abort=new AbortController();this.controllers.add(abort);
        try{await this.detailSlot();acquired=true;const result=await this.api.request<{items:EvidenceDetail[]}>(ANALYSIS_ROOT+'/evidence/batch',
          {analysisSessionId:this.sessionId,evidenceRefIds:batch.map(([id])=>id)},abort.signal);
          for(const [id,listeners] of batch){const item=result.items.find(row=>row.evidenceRefId===id);if(!item)throw new Error('资料读取结果不完整');listeners.forEach(listener=>listener.resolve(item));}
        }catch(error){batch.forEach(([,listeners])=>listeners.forEach(listener=>listener.reject(error)));}
        finally{this.controllers.delete(abort);if(acquired)this.releaseDetailSlot();}
      })();
    }
  }
  async preview(ref:SourceRef,options:Record<string,string|number>={},signal?:AbortSignal):Promise<SourcePreview>{
    await this.detailSlot();
    try{return await this.api.request(ANALYSIS_ROOT+'/evidence/preview',{analysisSessionId:this.sessionId,evidenceRefId:ref.id,options},signal);}
    finally{this.releaseDetailSlot();}
  }
  relationships(refs:SourceRef[],signal?:AbortSignal){
    return this.api.request<{items:SourceRelationship[];gaps:{evidenceRefId:string;reason:string}[]}>(ANALYSIS_ROOT+'/evidence/relationships',
      {analysisSessionId:this.sessionId,evidenceRefIds:[...new Set(refs.map(ref=>ref.id))]},signal);
  }
  file(ref:SourceRef,source?:EvidenceSource,signal?:AbortSignal,representation:'original'|'preview'='original',pageNumber?:number,
    priority:'foreground'|'background'='background',photo?:{ticket?:string}):Promise<string>{
    if(signal?.aborted||this.disposed)return Promise.reject(new DOMException('Closed','AbortError'));
    const key=representation+':'+(source?.contentVersionId&&source?.selector?`${source.contentVersionId}:${source.selector.displayRevision}`:ref.id+':'+ref.revision)+':'+(pageNumber||'');
    const cached=this.files.get(key);if(cached){this.files.delete(key);this.files.set(key,cached);return Promise.resolve(cached.url);}
    let entry=this.inflight.get(key);
    if(!entry||entry.transfer.abort.signal.aborted){
      const abort=new AbortController(),transfer={abort,foreground:priority==='foreground'};
      const promise=(async()=>{
        await this.fileSlot(transfer);
        try{
          if(this.disposed||abort.signal.aborted)throw new DOMException('Closed','AbortError');
          const route=ANALYSIS_ROOT+(representation==='preview'||pageNumber?'/evidence/preview-content':'/evidence/content');
          const fixedPhoto=photo&&representation==='original'&&!pageNumber;
          const request={
            analysisSessionId:this.sessionId,evidenceRefId:ref.id,...(pageNumber?{options:{pageNumber}}:
              fixedPhoto?{representation:'full_resolution'}:{})
          };
          const blob=fixedPhoto&&this.api.analysisPhoto?await this.api.analysisPhoto(route,request,abort.signal,photo.ticket):
            await this.api.request<Blob>(route,request,abort.signal,'source');
          if(this.disposed||abort.signal.aborted)throw new DOMException('Closed','AbortError');
          const url=URL.createObjectURL(blob);
          if(blob.type.startsWith('image/')&&typeof Image!=='undefined'){
            const image=new Image();image.src=url;
            try{await image.decode();if(this.disposed||abort.signal.aborted)throw new DOMException('Closed','AbortError');}
            catch(error){image.src='';URL.revokeObjectURL(url);throw error;}
            this.decoded.set(key,image);
            // Keep at most two decoded sources, independently of the byte cache.
            while(this.decoded.size>2){const first=this.decoded.keys().next().value!;this.decoded.get(first)!.src='';this.decoded.delete(first);}
          }
          this.files.set(key,{url,bytes:blob.size});
          while(this.files.size>20||[...this.files.values()].reduce((sum,row)=>sum+row.bytes,0)>96*1024*1024){const first=this.files.keys().next().value!;
            URL.revokeObjectURL(this.files.get(first)!.url);this.files.delete(first);const image=this.decoded.get(first);if(image)image.src='';this.decoded.delete(first);}
          return url;
        }finally{
          this.releaseFileSlot();
        }
      })().finally(()=>{
        if(this.inflight.get(key)?.transfer===transfer)this.inflight.delete(key);
      });
      entry={promise,transfer,users:0};
      this.inflight.set(key,entry);
    }
    // A user opening a viewer can promote a file already queued by its card.
    if(priority==='foreground')entry.transfer.foreground=true;
    const active=entry;active.users++;
    return new Promise((resolve,reject)=>{let done=false;const finish=()=>{if(done)return false;done=true;signal?.removeEventListener('abort',cancel);active.users--;return true;};
      const cancel=()=>{if(finish()){if(active.users===0)active.transfer.abort.abort();reject(new DOMException('Closed','AbortError'));}};
      signal?.addEventListener('abort',cancel,{once:true});active.promise.then(value=>{if(finish())resolve(value);},error=>{if(finish())reject(error);});
    });
  }
  dispose(){this.disposed=true;this.controllers.forEach(abort=>abort.abort());this.controllers.clear();
    this.inflight.forEach(entry=>entry.transfer.abort.abort());this.inflight.clear();
    this.decoded.forEach(image=>{image.src='';});this.decoded.clear();
    this.files.forEach(row=>URL.revokeObjectURL(row.url));this.files.clear();
    const error=new DOMException('Closed','AbortError');this.pending.forEach(rows=>rows.forEach(row=>row.reject(error)));this.pending.clear();
    this.lightQueue.splice(0).forEach(done=>done());}
}
