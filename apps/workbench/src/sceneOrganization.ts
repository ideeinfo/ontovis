import {cloneSnapshot, moveInstance, SceneEditError} from './sceneState.ts';
import {toDisplay} from './sceneTransforms.ts';
import type {EditableSceneSnapshot, SceneOrganization, SceneRoute, SceneViewpoint, Vector3} from './sceneTypes';

export const organizationLimits={groups:16,viewpoints:32,routes:8,steps:32,name:80} as const;
export const sceneOrganization=(snapshot:EditableSceneSnapshot):SceneOrganization=>snapshot.organization??{groups:[],viewpoints:[],routes:[]};
export class SceneBatchError extends SceneEditError {
  readonly instanceIds:string[];
  constructor(code:string,instanceIds:string[]=[]){super(code);this.instanceIds=[...instanceIds];}
}
const ensure=(value:unknown,code='INVALID_SCENE_ORGANIZATION'):void=>{if(!value)throw new SceneBatchError(code);};
const name=(value:string)=>{const result=value.trim();ensure(result.length>0&&result.length<=organizationLimits.name&&!/[\x00-\x1f]/.test(value));return result;};
const finite=(value:number,limit=1_000_000)=>{ensure(Number.isFinite(value)&&Math.abs(value)<=limit,'INVALID_COORDINATE');return value;};
const normalizeHeading=(value:number)=>((finite(value)%360)+360)%360;

export function snapNumber(value:number,step:number):number {
  finite(value);ensure(Number.isFinite(step)&&step>=0&&step<=1_000_000,'INVALID_COORDINATE');
  return finite(step?Math.round(value/step)*step:value);
}
export function snapPoint(point:Vector3,step:number):Vector3 {return [snapNumber(point[0],step),finite(point[1],100_000),snapNumber(point[2],step)];}

export function selectSceneInstances(snapshot:EditableSceneSnapshot,selection:string[],id:string|null,additive=false):string[] {
  if(!id)return additive?[...selection]:[];
  if(!snapshot.instances.some(item=>item.sceneModelInstanceId===id))return [];
  const members=sceneOrganization(snapshot).groups.find(group=>group.instanceIds.includes(id))?.instanceIds??[id];
  if(!additive)return [...members];
  return members.every(member=>selection.includes(member))?selection.filter(member=>!members.includes(member)):[...new Set([...selection,...members])];
}
export function groupSceneInstances(snapshot:EditableSceneSnapshot,ids:string[],displayName:string,groupId:string):EditableSceneSnapshot {
  const data=sceneOrganization(snapshot),members=[...new Set(ids)];
  ensure(members.length>=2&&members.length===ids.length&&members.every(id=>snapshot.instances.some(item=>item.sceneModelInstanceId===id)));
  ensure(!data.groups.some(group=>group.groupId===groupId||group.instanceIds.some(id=>members.includes(id))),'INSTANCE_ALREADY_GROUPED');
  ensure(data.groups.length<organizationLimits.groups,'SCENE_LIMIT_EXCEEDED');
  const next=cloneSnapshot(snapshot);next.organization={...structuredClone(data),groups:[...structuredClone(data.groups),{groupId,displayName:name(displayName),instanceIds:members}]};return next;
}
export function ungroupSceneInstances(snapshot:EditableSceneSnapshot,groupId:string):EditableSceneSnapshot {
  const next=cloneSnapshot(snapshot),data=sceneOrganization(next);next.organization={...data,groups:data.groups.filter(group=>group.groupId!==groupId)};return next;
}
export function pruneSceneGroups(snapshot:EditableSceneSnapshot):EditableSceneSnapshot {
  if(!snapshot.organization)return snapshot;
  const next=cloneSnapshot(snapshot),ids=new Set(next.instances.map(item=>item.sceneModelInstanceId));
  next.organization!.groups=next.organization!.groups.map(group=>({...group,instanceIds:group.instanceIds.filter(id=>ids.has(id))})).filter(group=>group.instanceIds.length>=2);
  return next;
}
export function moveSceneInstances(snapshot:EditableSceneSnapshot,ids:string[],delta:[number,number],headingDelta:number,grid=0,angle=0):EditableSceneSnapshot {
  const members=[...new Set(ids)],items=snapshot.instances.filter(item=>members.includes(item.sceneModelInstanceId));
  ensure(members.length>0&&members.length===ids.length&&items.length===members.length,'INVALID_SELECTION');
  const locked=items.filter(item=>item.positionLocked).map(item=>item.sceneModelInstanceId);
  if(locked.length)throw new SceneBatchError('INSTANCE_POSITION_LOCKED',locked);
  const dx=snapNumber(delta[0],grid),dz=snapNumber(delta[1],grid),heading=snapNumber(headingDelta,angle);
  let next=cloneSnapshot(snapshot);
  for(const item of items){
    try{
      if(dx||dz){const point=toDisplay(snapshot.coordinateFrame,item.placement.position,item.placement.height);
        next=moveInstance(next,item.sceneModelInstanceId,[finite(point[0]+dx),point[1],finite(point[2]+dz)]);}
      next.instances.find(value=>value.sceneModelInstanceId===item.sceneModelInstanceId)!.placement.headingDeg=normalizeHeading(item.placement.headingDeg+heading);
    }catch(error){if(error instanceof Error&&'code'in error)throw new SceneBatchError(String(error.code),[item.sceneModelInstanceId]);throw error;}
  }
  return next;
}
export function viewpointIssue(snapshot:EditableSceneSnapshot,viewpoint:SceneViewpoint):'VIEW_FRAME_CHANGED'|'VIEW_MODEL_CHANGED'|'VIEW_TARGET_MISSING'|null {
  if(viewpoint.frameRevision!==snapshot.coordinateFrame.frameRevision)return 'VIEW_FRAME_CHANGED';
  if(!viewpoint.modelTarget)return null;
  const item=snapshot.instances.find(value=>value.sceneModelInstanceId===viewpoint.modelTarget!.sceneModelInstanceId);
  if(!item)return 'VIEW_TARGET_MISSING';
  return item.modelVersionId===viewpoint.modelTarget.modelVersionId?null:'VIEW_MODEL_CHANGED';
}
export function putSceneViewpoint(snapshot:EditableSceneSnapshot,viewpoint:SceneViewpoint):EditableSceneSnapshot {
  const data=sceneOrganization(snapshot),index=data.viewpoints.findIndex(value=>value.viewpointId===viewpoint.viewpointId);
  ensure(index>=0||data.viewpoints.length<organizationLimits.viewpoints,'SCENE_LIMIT_EXCEEDED');
  ensure(!viewpointIssue(snapshot,viewpoint),'VIEWPOINT_STALE');
  ensure(viewpoint.kind==='overview'||viewpoint.kind==='component'&&viewpoint.modelTarget!==null);
  for(const vector of [viewpoint.view.eye,viewpoint.view.target]){ensure(vector.length===3);vector.forEach(value=>finite(value));}
  ensure(viewpoint.view.eye.reduce((sum,value,i)=>sum+(value-viewpoint.view.target[i])**2,0)>1e-12,'INVALID_COORDINATE');
  const next=cloneSnapshot(snapshot),views=structuredClone(data.viewpoints),value={...structuredClone(viewpoint),displayName:name(viewpoint.displayName)};
  if(index<0)views.push(value);else views[index]=value;
  next.organization={...structuredClone(data),viewpoints:views};return next;
}
export function removeSceneViewpoint(snapshot:EditableSceneSnapshot,id:string):EditableSceneSnapshot {
  const data=sceneOrganization(snapshot);ensure(!data.routes.some(route=>route.steps.some(step=>step.viewpointId===id)),'VIEWPOINT_IN_USE');
  const next=cloneSnapshot(snapshot);next.organization={...structuredClone(data),viewpoints:data.viewpoints.filter(value=>value.viewpointId!==id)};return next;
}
export function putSceneRoute(snapshot:EditableSceneSnapshot,route:SceneRoute):EditableSceneSnapshot {
  const data=sceneOrganization(snapshot),index=data.routes.findIndex(value=>value.routeId===route.routeId);
  ensure(index>=0||data.routes.length<organizationLimits.routes,'SCENE_LIMIT_EXCEEDED');
  ensure(route.steps.length<=organizationLimits.steps,'SCENE_LIMIT_EXCEEDED');
  ensure(new Set(route.steps.map(step=>step.stepId)).size===route.steps.length);
  for(const step of route.steps){ensure(data.viewpoints.some(value=>value.viewpointId===step.viewpointId));
    ensure(Number.isFinite(step.flightSeconds)&&step.flightSeconds>=.2&&step.flightSeconds<=30);
    ensure(Number.isFinite(step.dwellSeconds)&&step.dwellSeconds>=0&&step.dwellSeconds<=300);}
  const next=cloneSnapshot(snapshot),routes=structuredClone(data.routes),value={...structuredClone(route),displayName:name(route.displayName)};
  if(index<0)routes.push(value);else routes[index]=value;
  next.organization={...structuredClone(data),routes};return next;
}
export function removeSceneRoute(snapshot:EditableSceneSnapshot,id:string):EditableSceneSnapshot {
  const next=cloneSnapshot(snapshot),data=sceneOrganization(next);next.organization={...data,routes:data.routes.filter(value=>value.routeId!==id)};return next;
}
