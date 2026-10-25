import type {SceneObjectContext} from './sceneEngineeringTypes';

export type OrderState = 'open'|'diagnosing'|'investigating'|'review'|'closed';
export interface WorkOrder {
  orderId:string;batchId:string;number:number;faultCode:string;title:string;cabinet:'CN'|'CN1';
  state:OrderState;orderRevision:number;alarmAt:string;updatedAt:string;checks:string[];note:string;
  sourceKind:'simulated';engineeringConfirmation:false;
}
export interface DiagnosticNode {id:string;kind:string;label:string;state:string;rds?:string;locateKey?:string}
export interface WorkOrderDetail extends WorkOrder {
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
export interface OrderLocation extends SceneObjectContext {locateKey:string;engineeringConfirmation:false}
