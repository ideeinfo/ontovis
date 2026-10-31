import {ApiError} from './api.ts';
import type {ModelThumbnailReference,ProjectModelReport} from './resourceTypes';

export const identityStates=['missing','incomplete','invalid','unverified_claim','collision'] as const;
export type SourceIdentityState=typeof identityStates[number];
export interface ModelSourceNode {
  componentKey:string;nodeIndex:number;keyStability:'version_local';name:string|null;
  sourceExtrasPresent:boolean;sourceExtras:unknown;activeScene:boolean;
  sourceIdentityClaim:Record<string,string>|null;sourceIdentityState:SourceIdentityState;
  sourceIdentityMissingFields:string[];sourceIdentityInvalidFields:string[];sourceIdentityVerified:false;
}
export interface ModelInspectionReport {
  schemaVersion:1;profileVersion:'source-nodes-v1';scope:'fixed_glb_source_local_only';
  modelVersionId:string;contentRevision:string;sha256:string;processorSha256:string;catalogSha256:string;
  sourceNodes:ModelSourceNode[];sourceIdentityStates:Partial<Record<SourceIdentityState,number>>;
  sourceValidation:ProjectModelReport;sourceIdentityVerified:false;geometryCorrespondenceVerified:false;
  bindingMigrationApproved:false;releaseReadiness:{eligible:false;G2Passed:false};
}
const record=(value:unknown):value is Record<string,unknown>=>typeof value==='object'&&value!==null&&!Array.isArray(value);
const digest=(value:unknown)=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
const strings=(value:unknown)=>Array.isArray(value)&&value.every(item=>typeof item==='string');

export function checkedModelInspection(value:unknown,version:ModelThumbnailReference):ModelInspectionReport {
  if(!record(value))throw new ApiError(502,'MODEL_INSPECTION_UNAVAILABLE');
  if(value.modelVersionId!==version.modelVersionId||value.contentRevision!==version.contentRevision||value.sha256!==version.sha256)
    throw new ApiError(409,'RESOURCE_CHANGED');
  const nodes=value.sourceNodes,validation=value.sourceValidation,readiness=value.releaseReadiness;
  if(value.schemaVersion!==1||value.profileVersion!=='source-nodes-v1'||value.scope!=='fixed_glb_source_local_only'
      ||!digest(value.processorSha256)||!digest(value.catalogSha256)||value.sourceIdentityVerified!==false
      ||value.geometryCorrespondenceVerified!==false||value.bindingMigrationApproved!==false
      ||!record(readiness)||readiness.eligible!==false||readiness.G2Passed!==false
      ||!record(validation)||validation.coordinateVerification!=='unverified'||validation.sourceIdentityVerified!==false
      ||!Array.isArray(nodes)||nodes.length<1||nodes.length>2000||validation.nodes!==nodes.length
      ||!record(value.sourceIdentityStates))throw new ApiError(502,'MODEL_INSPECTION_UNAVAILABLE');
  const counts:Partial<Record<SourceIdentityState,number>>={};
  for(const [index,node] of nodes.entries()){
    if(!record(node)||node.nodeIndex!==index||node.componentKey!==`${version.sha256}:node:${index}`
        ||node.keyStability!=='version_local'||node.sourceIdentityVerified!==false
        ||!(node.name===null||typeof node.name==='string')||typeof node.activeScene!=='boolean'
        ||typeof node.sourceExtrasPresent!=='boolean'||!Object.hasOwn(node,'sourceExtras')
        ||!identityStates.includes(node.sourceIdentityState as SourceIdentityState)
        ||!strings(node.sourceIdentityMissingFields)||!strings(node.sourceIdentityInvalidFields)
        ||!(node.sourceIdentityClaim===null||record(node.sourceIdentityClaim)&&Object.values(node.sourceIdentityClaim).every(item=>typeof item==='string')))
      throw new ApiError(502,'MODEL_INSPECTION_UNAVAILABLE');
    const state=node.sourceIdentityState as SourceIdentityState;counts[state]=(counts[state]??0)+1;
  }
  const states=value.sourceIdentityStates;
  if(Object.keys(states).some(state=>!identityStates.includes(state as SourceIdentityState))
      ||identityStates.some(state=>states[state]!==undefined?states[state]!==counts[state]:!!counts[state]))
    throw new ApiError(502,'MODEL_INSPECTION_UNAVAILABLE');
  return value as unknown as ModelInspectionReport;
}

export function sourceIdentityLabel(state:SourceIdentityState,locale:string){
  const labels:Record<SourceIdentityState,[string,string]>={missing:['无身份声明','No identity claim'],incomplete:['声明不完整','Incomplete claim'],
    invalid:['声明格式错误','Invalid claim'],unverified_claim:['声明完整 · 未核实','Complete claim · Unverified'],collision:['声明重复','Duplicate claim']};
  return labels[state][locale==='zh'?0:1];
}
export function filterSourceNodes(nodes:ModelSourceNode[],query:string,state:SourceIdentityState|'',scope:'all'|'active'|'inactive'){
  const search=query.trim().toLocaleLowerCase();
  return nodes.filter(node=>(!state||node.sourceIdentityState===state)&&(scope==='all'||node.activeScene===(scope==='active'))
    &&`${node.nodeIndex} ${node.name??''} ${JSON.stringify(node.sourceIdentityClaim)}`.toLocaleLowerCase().includes(search));
}
