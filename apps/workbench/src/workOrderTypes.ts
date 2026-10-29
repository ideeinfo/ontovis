import type {SceneObjectContext} from './sceneEngineeringTypes';
import type {EngineeringObject} from './types';

export type OrderState = 'open'|'diagnosing'|'investigating'|'review'|'closed';
export interface WorkOrder {
  orderId:string;batchId:string;number:number;faultCode:string;title:string;cabinet:'CN'|'CN1'|'CN2';
  state:OrderState;orderRevision:number;alarmAt:string;updatedAt:string;checks:string[];note:string;
  sourceKind:'simulated';engineeringConfirmation:false;
}
export interface DiagnosticNode {id:string;kind:string;label:string;state:string;rds?:string;locateKey?:string}
export interface Investigation {
  hypotheses:{id:string;description:string;status:'candidate'|'supported'|'rejected';basis:string}[];
  steps:{id:string;title:string;targetKey:string;outcome:'pending'|'observed'|'gap'|'not_applicable';result:string}[];
  conclusion:string;reviewBasis:string;
}
export interface InvestigationHistory {orderRevision:number;actor:string;recordedAt:string}
export interface AssistantTransfer {
  orderRevision:number;runId:string;conversationId:string|null;conversationVersion:number;analysisSessionId:string;
  analysisRevision:number;analysisSha256:string;actor:string;recordedAt:string;engineeringConfirmation:false;
  items:{sourceItemId:string;kind:'hypothesis'|'step'|'gap';originalText:string;text:string;targetKey:string;refs:string[];planItemId:string}[];
  sources:{key:string;kind:string;evidenceRefId:string;sourceRevision?:string;summaryHash?:string;retrievalRevision?:string}[];
}
export interface WorkOrderDetail extends WorkOrder {
  assistantTransfers?:AssistantTransfer[];
  analysisLinks?:{orderRevision:number;analysisSessionId:string;analysisRevision:number;analysisSha256:string}[];
  investigation:Investigation;investigationRevision:number|null;investigationComplete:boolean;
  investigationHistory:InvestigationHistory[];
  createdRuleRevision:string;
  diagnosis:{revision:string;mode:'demonstration_rules';engineeringConfirmation:false;
    source:{projectCode:string;catalogue:string;manualPages:number[];applicability:string};gap:string;
    nodes:DiagnosticNode[];edges:{source:string;target:string;label:string}[];checks:{id:string;label:string}[]};
  targets:Record<'CN'|'CN1',{entityUid:string;entityRevision:string;installationContextId:string;hierarchyRevision:string}>;
  events:{revision:number;action:string;actor:string;recordedAt:string;from:OrderState|null;to:OrderState;note:string}[];
}
export interface OrderListing {items:WorkOrder[];total:number;nextCursor:number|null;snapshotRevision:string;
  capabilities:{canWrite:boolean;canSeedDemo:boolean};sourceKind:'simulated'}
export interface PhotoBox {x:number;y:number;width:number;height:number}
export interface SphericalRegion {yaw_start_deg:number;yaw_span_deg:number;pitch_min_deg:number;pitch_max_deg:number;
  view:{yaw_deg:number;pitch_deg:number;hfov_deg:number}}
export interface PhotoSelector {kind:'image_bbox'|'spherical_region';renditionId:string;displayRevision:string;
  regionKind:'label_region'|'device_region';coordinateSpace:string;bbox?:PhotoBox;sphericalRegion?:SphericalRegion}
export interface ObjectPhoto {evidenceRef:string;sourceRevision:string;sourceRelation:'direct'|'template_definition';
  sourceEntityUid:string;sourceEntityRevision:string;documentId:string;contentVersionId:string;title:string;
  sourceSha256:string|null;versionNumber:number|null;newerVersionAvailable:boolean;documentStatus:string;
  unavailableReason:string|null;anchorUnavailableReason:string|null;selector:PhotoSelector|null;
  engineeringConfirmation:false;versionMode:'fixed_content_version'}
export interface OrderLocation extends SceneObjectContext {locateKey:string;engineeringConfirmation:false;
  referenceMatch?:{scheme:'RDS'|'electrical_tag';status:'accepted'|'needs_review';value:string;scopeType:string;scopeKey:string};
  cabinetReference?:{code:'CN2'|'CN1';purpose:'project_definition'};
  definitionParent?:EngineeringObject;
  cabinetMembers?:{items:EngineeringObject[];total:number;nextCursor:string|null;snapshotRevision:string;basisKind:'user_declared'}}
