import {ApiError, failureMessage, type WorkbenchApi} from './api';
import type {CanvasSnapshot} from './analysisCanvas';
import type {OrderListing, WorkOrderDetail} from './workOrderTypes';

export const ORDER_ROOT = '/api/workbench/work-orders';
export type OrderApi = Pick<WorkbenchApi, 'request'|'content'|'uploadWorkOrderPart'|'revision'|'epoch'>;

export function cockpitOrderApi(api:OrderApi):OrderApi {
  const scoped=(path:string,body?:object)=>path===ORDER_ROOT||path.startsWith(`${ORDER_ROOT}/`)
    ?{...body,workOrderView:'cockpit'}:body;
  return {
    get revision(){return api.revision;},
    get epoch(){return api.epoch;},
    request:(path,body,signal,image,upload)=>api.request(path,scoped(path,body),signal,image,upload),
    content:(path,body,descriptor,signal)=>api.content(path,scoped(path,body)!,descriptor,signal),
    uploadWorkOrderPart:(file,metadata,signal)=>api.uploadWorkOrderPart(file,{...metadata,workOrderView:'cockpit'},signal),
  };
}
export type WorkflowState = 'pending'|'processing'|'completed'|'archived';
export type Member = {userId:string; name:string; role?:string};
export type FixedAnalysis = {analysisSessionId:string; analysisRevision:number; analysisSha256:string};
export type AnalysisReuse = {
  faultCode?:string; faultSystem?:string; equipment?:string; simulated?:boolean; summary?:string; advice?:string;
};
export type AnalysisCandidate = FixedAnalysis & {
  title:string; updatedAt:string; headRevision:number; owned:boolean; shared:boolean;
  applicability:AnalysisReuse; sameCode:boolean; sameSystem:boolean; sameEquipment:boolean;
  equipmentMismatch:boolean; simulationMismatch:boolean;
};
export type AnalysisReference = FixedAnalysis & {snapshot:CanvasSnapshot; owned:boolean; shared:boolean; headRevision:number};
export type TreatmentRecord = {
  recordId:string; recordRevision:number; text:string; actor:string; recordedAt:string;
  occurredAt:string|null; editedBy?:string; editedAt?:string; cycle:number; basis:FixedAnalysis|null;
};
export type DocumentVersion = {documentId:string; contentVersionId:string; title:string; kind:string};
export type FixedAttachment = DocumentVersion & {
  attachmentId:string; filename:string; sourceSha256:string; byteSize:number; versionNumber:number;
  previewKind:string; previewAvailable:boolean; pageCount:number|null;
  recordId:string|null; actor:string; recordedAt:string;
};
export type OrderAlarm = {datasetId:string; datasetRevision:string; faultCode:string; title:string};
export type Workflow = {
  issue:string; handler:Member|null; sourceKind:'manual'|'simulated'; source?:{title:string; eventAt:string}|null;
  faultSystem:string; equipment:string; legacyState?:string; cycle:number;
  records:TreatmentRecord[]; attachments:FixedAttachment[];
  adoptedAnalysis:(FixedAnalysis & {actor:string; recordedAt:string; orderRevision:number})|null;
  result:{text:string; recordId:string|null; cycle:number; voided?:boolean}|null;
  completedAt:string|null; archivedAt:string|null;
};
export type WorkflowDetail = Omit<WorkOrderDetail,'state'|'sourceKind'> & {
  state:WorkflowState|WorkOrderDetail['state']; sourceKind:'manual'|'simulated';
  workflow?:Workflow; handler?:Member|null; workflowVersion?:1;
  snapshotSha256:string; canManage:boolean; canProcess:boolean; canAttach:boolean; actorId:string;
};
export type WorkflowListing = Omit<OrderListing,'items'> & {items:WorkflowDetail[]};
export type AttachmentOrder = Pick<WorkflowDetail,'orderId'|'orderRevision'|'snapshotSha256'>;
export const workflowStates:WorkflowState[] = ['pending','processing','completed','archived'];

export function workflowState(state:string):WorkflowState {
  if (state === 'open') return 'pending';
  if (state === 'closed') return 'completed';
  if (state === 'archived' || state === 'completed' || state === 'pending') return state;
  return 'processing';
}

export function workflowLabel(state:string, en:boolean) {
  return {pending:['待处理','Pending'], processing:['处理中','In progress'],
    completed:['已完成','Completed'], archived:['已归档','Archived']}[workflowState(state)][en?1:0];
}

export function fixedAnalysis(row:FixedAnalysis):FixedAnalysis {
  return {analysisSessionId:row.analysisSessionId,analysisRevision:row.analysisRevision,analysisSha256:row.analysisSha256};
}

export function orderFailure(error:unknown, en:boolean) {
  const messages:Record<string,[string,string]> = {
    WORK_ORDER_CHANGED:['工单已更新。重新读取后可继续保存当前输入。','The order changed. Reload it and keep your draft.'],
    WORK_ORDER_STATE_CONFLICT:['工单状态已变化，请重新读取。','The order status changed. Reload it.'],
    WORK_ORDER_HANDLER_REQUIRED:['此操作需要由本单当前处理人完成。','This action requires the current handler.'],
    WORK_ORDER_QUERY_ONLY:['请前往后台处理工单。','Open the workbench to update work orders.'],
    WORK_ORDER_HANDLER_UNAVAILABLE:['所选人员已不可分派，请刷新成员列表。','The selected member is no longer available.'],
    WORK_ORDER_EVENT_LIMIT:['工单记录已达保存上限。','This order has reached the record limit.'],
    WORK_ORDER_SNAPSHOT_LIMIT:['工单内容过长，无法保存当前修改。','The order is too large to save this change.'],
    WORK_ORDER_RECORD_FIXED:['历史处理周期的记录已固定。','The record belongs to a fixed treatment cycle.'],
    WORK_ORDER_COPY_CARD_LIMIT:['原分析资料卡过多，无法同时保留本单资料。可新建分析，再加入所需资料。','The source has too many cards to include this order. Create an analysis and add the materials you need.'],
    document_format_unsupported:['当前文件格式不支持上传。','This file type cannot be uploaded.'],
    document_preview_unavailable:['该版本支持下载原件。','The original file is available to download.'],
    project_documents_readonly:['当前账号可引用已有资料。上传需要源端资料写入权限。','You can link existing files. Uploading requires source document write access.'],
    CONTENT_SIZE_LIMIT:['文件大小超出可上传范围。','The file exceeds the upload limit.'],
    ANALYSIS_NOT_ENABLED:['当前项目尚未启用分析存储。','Analysis storage is unavailable.'],
  };
  return error instanceof ApiError && messages[error.code] ? messages[error.code][en?1:0] : failureMessage(error,en?'en':'zh');
}
