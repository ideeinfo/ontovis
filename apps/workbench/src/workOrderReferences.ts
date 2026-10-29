import {ApiError} from './api.ts';
import type {CanvasCard,CanvasSnapshot,ProjectScope} from './analysisCanvas';
import type {DraftReceipt} from './analysisDraftState';
import type {AssistantTransfer} from './workOrderTypes';
import type {EvidenceDetail,EvidenceSource} from './analysisSources';

export const referenceNames:Record<string,[string,string]>={object:['工程对象','Object'],drawing:['图纸','Drawing'],document:['文档','Document'],photo:['照片','Photo'],model:['三维模型','3D model'],trend:['趋势','Trend'],alarm:['故障报警','Alarm'],work_order:['工单','Work order']};
export type WorkOrderReferenceEntry={analysisSessionId:string;analysisRevision:number;assistantRunId?:never;workOrderReference:{orderId:string;orderRevision:number;analysisSha256:string;key:string;kind:string;evidenceRefId:string;sourceRevision:string}};
const hash=(value:unknown):value is string=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);

export function workOrderReferenceEntry(orderId:string,transfer:AssistantTransfer,item:AssistantTransfer['items'][number],key:string):WorkOrderReferenceEntry|null{
 const refs=transfer.sources.filter(source=>source.key===key),ref=refs[0];
 if(!item.refs.includes(key)||!/^E[1-8]$/.test(key)||refs.length!==1||!referenceNames[ref.kind]||!ref.evidenceRefId||!hash(ref.sourceRevision)||!hash(transfer.analysisSha256))return null;
 return {analysisSessionId:transfer.analysisSessionId,analysisRevision:transfer.analysisRevision,workOrderReference:{orderId,orderRevision:transfer.orderRevision,analysisSha256:transfer.analysisSha256,key,kind:ref.kind,evidenceRefId:ref.evidenceRefId,sourceRevision:ref.sourceRevision}};
}

export function workOrderReferenceCard(entry:WorkOrderReferenceEntry,detail:DraftReceipt&{snapshot:CanvasSnapshot},scope:ProjectScope|null):CanvasCard{
 const ref=entry.workOrderReference,snapshot=detail.snapshot;
 if(!scope||detail.analysisSessionId!==entry.analysisSessionId||detail.analysisRevision!==entry.analysisRevision||detail.contentSha256!==ref.analysisSha256||snapshot.projectCode!==scope.projectCode||snapshot.ontobaseConnectionId!==scope.ontobaseConnectionId)throw new ApiError(409,'WORK_ORDER_REFERENCE_CHANGED');
 const kind=ref.kind==='model'?'model3d':ref.kind;
 const cards=snapshot.cards.filter(card=>card.kind===kind&&card.source?.id===ref.evidenceRefId&&card.source.revision===ref.sourceRevision&&card.source.projectCode===scope.projectCode&&card.source.ontobaseConnectionId===scope.ontobaseConnectionId);
 const card=cards.find(card=>!card.historical)??cards[0];
 if(!card)throw new ApiError(409,'WORK_ORDER_REFERENCE_CHANGED');
 return card;
}

export function workOrderReferenceMaterial(entry:WorkOrderReferenceEntry,detail:EvidenceDetail):EvidenceSource{
 const ref=entry.workOrderReference;
 if(detail.evidenceRefId!==ref.evidenceRefId||detail.sourceKind!==ref.kind||detail.sourceRevision!==ref.sourceRevision)throw new ApiError(409,'WORK_ORDER_REFERENCE_CHANGED');
 if(detail.availability!=='available'||!detail.source)throw new ApiError(409,'WORK_ORDER_REFERENCE_UNAVAILABLE');
 return detail.source;
}
