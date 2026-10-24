import type {EngineeringExpectation, EngineeringRef, SceneObjectSelection} from './sceneEngineeringTypes';
import type {EditableSceneSnapshot, GeometryValidation, RootBindingChange, SceneModelInstance} from './sceneTypes';

export type EngineeringReviews = ReadonlyMap<string, EngineeringExpectation>;
type StateErrorCode = 'INVALID_REQUEST' | 'ENGINEERING_CHANGED' | 'COMPONENT_ALREADY_BOUND' | 'SCENE_LIMIT_EXCEEDED';
export class SceneEngineeringStateError extends Error {
  code:StateErrorCode;
  constructor(code:StateErrorCode) {super(code);this.code=code;}
}
const MAX_BINDINGS=1000;
function require(condition:unknown,code:StateErrorCode='INVALID_REQUEST'):asserts condition {
  if(!condition)throw new SceneEngineeringStateError(code);
}
const fields=(value:unknown,keys:readonly string[])=>typeof value==='object'&&value!==null&&!Array.isArray(value)&&
  Object.keys(value).length===keys.length&&keys.every(key=>Object.hasOwn(value,key));
const text=(value:unknown,max=512)=>typeof value==='string'&&value.length>0&&value.length<=max&&
  value===value.trim()&&!/[\u0000-\u001f]/u.test(value);

/** A tuple avoids collisions between equal UIDs from different projects or connections. */
export function refKey(ref:EngineeringRef):string {
  require(fields(ref,['ontobaseConnectionId','projectCode','entityUid'])&&text(ref.ontobaseConnectionId,200)&&
    text(ref.projectCode,200)&&text(ref.entityUid));
  return JSON.stringify([ref.ontobaseConnectionId,ref.projectCode,ref.entityUid]);
}
function expectation(value:EngineeringExpectation):EngineeringExpectation {
  require(fields(value,['ref','expectedEntityRevision','installationContextId','expectedHierarchyRevision']));
  refKey(value.ref);
  require(text(value.expectedEntityRevision)&&text(value.installationContextId)&&text(value.expectedHierarchyRevision));
  return structuredClone(value);
}
const sameExpectation=(a:EngineeringExpectation,b:EngineeringExpectation)=>refKey(a.ref)===refKey(b.ref)&&
  a.expectedEntityRevision===b.expectedEntityRevision&&a.installationContextId===b.installationContextId&&
  a.expectedHierarchyRevision===b.expectedHierarchyRevision;

export function engineeringReviews(validation:Pick<GeometryValidation,'engineeringExpectations'|'bindingIssues'>):Map<string,EngineeringExpectation> {
  const result=new Map<string,EngineeringExpectation>();
  for(const value of validation.engineeringExpectations||[]) {
    const item=expectation(value),key=refKey(item.ref);
    require(!result.has(key),'ENGINEERING_CHANGED');result.set(key,item);
  }
  const issueBasis=new Map<string,EngineeringExpectation>();
  for(const issue of validation.bindingIssues) {
    if(issue.kind!=='engineering_changed')continue;
    const item=expectation({ref:issue.objectRef,expectedEntityRevision:issue.expectedEntityRevision,
      installationContextId:issue.installationContextId,expectedHierarchyRevision:issue.expectedHierarchyRevision}),key=refKey(item.ref);
    const prior=issueBasis.get(key);
    require(!prior||sameExpectation(prior,item),'ENGINEERING_CHANGED');issueBasis.set(key,item);
  }
  // An open response may contain fresh reads alongside an old unresolved issue.
  // Keep the issue's reviewed basis until the user explicitly selects that object.
  for(const [key,item] of issueBasis)result.set(key,item);
  return result;
}

export function reviewSelectedObject(reviews:EngineeringReviews,
  selection:Pick<SceneObjectSelection,'objectRef'|'bindingEligible'|'expectation'>):Map<string,EngineeringExpectation> {
  require(selection.bindingEligible===true&&selection.expectation!==null,'ENGINEERING_CHANGED');
  const item=expectation(selection.expectation);
  require(refKey(selection.objectRef)===refKey(item.ref),'ENGINEERING_CHANGED');
  const result=new Map<string,EngineeringExpectation>();
  for(const [key,value] of reviews) {
    require(key===refKey(value.ref));result.set(key,expectation(value));
  }
  result.set(refKey(item.ref),item);return result;
}

export function reviewedForSave(required:readonly EngineeringExpectation[],reviews:EngineeringReviews):EngineeringExpectation[] {
  const seen=new Set<string>();
  return required.map(value=>{
    const current=expectation(value),key=refKey(current.ref),reviewed=reviews.get(key);
    require(!seen.has(key),'ENGINEERING_CHANGED');seen.add(key);
    require(reviewed!==undefined&&sameExpectation(expectation(reviewed),current),'ENGINEERING_CHANGED');
    return structuredClone(reviewed);
  });
}

function rootChange(value:RootBindingChange):RootBindingChange {
  require(fields(value,['sceneModelInstanceId','from','to','clearOldComponentBindings','reviewedRemovedBindingsDigest'])&&
    text(value.sceneModelInstanceId,200)&&value.clearOldComponentBindings===true&&
    /^[0-9a-f]{64}$/u.test(value.reviewedRemovedBindingsDigest));
  if(value.from!==null)refKey(value.from);
  if(value.to!==null)refKey(value.to);
  return structuredClone(value);
}
const nullableKey=(ref:EngineeringRef|null)=>ref===null?null:refKey(ref);
const sameRootChange=(a:RootBindingChange,b:RootBindingChange)=>a.sceneModelInstanceId===b.sceneModelInstanceId&&
  nullableKey(a.from)===nullableKey(b.from)&&nullableKey(a.to)===nullableKey(b.to)&&
  a.clearOldComponentBindings===b.clearOldComponentBindings&&a.reviewedRemovedBindingsDigest===b.reviewedRemovedBindingsDigest;

export function rootChangesForSave(required:readonly RootBindingChange[],approved:readonly RootBindingChange[]):RootBindingChange[] {
  const approvals=new Map<string,RootBindingChange>();
  for(const value of approved) {
    const item=rootChange(value);
    require(!approvals.has(item.sceneModelInstanceId),'ENGINEERING_CHANGED');approvals.set(item.sceneModelInstanceId,item);
  }
  const seen=new Set<string>();
  const result=required.map(value=>{
    const item=rootChange(value),approval=approvals.get(item.sceneModelInstanceId);
    require(!seen.has(item.sceneModelInstanceId)&&approval!==undefined&&sameRootChange(item,approval),'ENGINEERING_CHANGED');
    seen.add(item.sceneModelInstanceId);return structuredClone(approval);
  });
  require(approvals.size===seen.size,'ENGINEERING_CHANGED');return result;
}

function instance(snapshot:EditableSceneSnapshot,id:string):SceneModelInstance {
  const items=snapshot.instances.filter(item=>item.sceneModelInstanceId===id);
  require(items.length===1);return items[0];
}
export function changeRootBinding(snapshot:EditableSceneSnapshot,id:string,ref:EngineeringRef|null):EditableSceneSnapshot {
  if(ref!==null)refKey(ref);
  const next=structuredClone(snapshot),item=instance(next,id);
  if(nullableKey(item.rootBinding?.objectRef||null)!==nullableKey(ref))item.componentBindings=[];
  item.rootBinding=ref===null?null:{objectRef:structuredClone(ref)};return next;
}

export function bindComponentKeys(snapshot:EditableSceneSnapshot,id:string,ref:EngineeringRef,keys:readonly string[]):EditableSceneSnapshot {
  const key=refKey(ref);require(Array.isArray(keys)&&keys.every(value=>text(value))&&new Set(keys).size===keys.length);
  require(keys.length<=MAX_BINDINGS,'SCENE_LIMIT_EXCEEDED');
  const next=structuredClone(snapshot),item=instance(next,id);
  if(keys.length) {
    require(item.rootBinding!==null,'ENGINEERING_CHANGED');
    require(item.rootBinding.objectRef.ontobaseConnectionId===ref.ontobaseConnectionId&&
      item.rootBinding.objectRef.projectCode===ref.projectCode,'ENGINEERING_CHANGED');
  }
  const objects=new Set<string>();
  for(const binding of item.componentBindings) {
    const other=refKey(binding.objectRef);require(!objects.has(other));objects.add(other);
    require(other===key||!binding.componentKeys.some(value=>keys.includes(value)),'COMPONENT_ALREADY_BOUND');
  }
  const row={objectRef:structuredClone(ref),componentKeys:[...keys].sort()},index=item.componentBindings.findIndex(value=>refKey(value.objectRef)===key);
  if(index>=0) {
    if(keys.length)item.componentBindings[index]=row;else item.componentBindings.splice(index,1);
  } else if(keys.length)item.componentBindings.push(row);
  const bindings=next.instances.flatMap(value=>value.componentBindings);
  require(bindings.length<=MAX_BINDINGS&&bindings.reduce((total,value)=>total+value.componentKeys.length,0)<=MAX_BINDINGS,'SCENE_LIMIT_EXCEEDED');
  return next;
}
