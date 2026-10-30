import type {Bounds3, EditableSceneSnapshot, ModelResourceRef, SceneView, Vector3} from './sceneTypes';

export interface ComponentFocusRequest {token:number;instanceId:string;bounds:Bounds3;componentKeys?:string[];isolate?:boolean}
export interface ComponentFocusContext {
  snapshot:EditableSceneSnapshot;selectedId:string|null;modelRefs:readonly ModelResourceRef[];
  personalVisibility:Readonly<Record<string,boolean>>;previewActive:boolean;
}
export interface ComponentFocusTarget extends ComponentFocusRequest {requestKey:string;sourceKey:string;modelKey:string}
const vector=(value:unknown):value is Vector3=>Array.isArray(value)&&value.length===3&&
  value.every(number=>typeof number==='number'&&Number.isFinite(number));
function validBounds(value:unknown):value is Bounds3 {
  return Array.isArray(value)&&value.length===2&&vector(value[0])&&vector(value[1])&&
    value[0].every((number,index)=>number<=value[1][index])&&
    Number.isFinite(Math.hypot(...value[0].map((number,index)=>value[1][index]-number)))&&
    Math.hypot(...value[0].map((number,index)=>value[1][index]-number))>0;
}
export function componentFocusKey(request:ComponentFocusRequest|undefined):string|null {
  return request&&Number.isSafeInteger(request.token)&&request.token>=0&&typeof request.instanceId==='string'&&
    request.instanceId.length>0&&validBounds(request.bounds)&&(request.componentKeys===undefined||Array.isArray(request.componentKeys)&&
      request.componentKeys.every(key=>typeof key==='string'&&key.length>0&&key.length<=512)&&
      new Set(request.componentKeys).size===request.componentKeys.length)&&(request.isolate===undefined||typeof request.isolate==='boolean')?JSON.stringify([request.token,request.instanceId,request.bounds,request.componentKeys??[],request.isolate??false]):null;
}
/** Capture the exact fixed resource and placement before awaiting its shared GLB. */
export function prepareComponentFocus(request:ComponentFocusRequest|undefined,context:ComponentFocusContext):ComponentFocusTarget|null {
  const requestKey=componentFocusKey(request);
  if(!request||requestKey===null||context.previewActive||context.selectedId!==request.instanceId)return null;
  const instances=context.snapshot.instances.filter(item=>item.sceneModelInstanceId===request.instanceId);
  if(instances.length!==1)return null;
  const item=instances[0],refs=context.modelRefs.filter(ref=>ref.modelVersionId===item.modelVersionId);
  if(!(context.personalVisibility[item.sceneModelInstanceId]??item.visible)||refs.length!==1)return null;
  const ref=refs[0],modelKey=JSON.stringify([ref.modelVersionId,ref.contentRevision,ref.sha256]);
  return {...structuredClone(request),requestKey,modelKey,
    sourceKey:JSON.stringify([context.snapshot.coordinateFrame,item.modelVersionId,item.placement,ref.modelAssetId??null,modelKey])};
}
export function componentFocusCurrent(target:ComponentFocusTarget,request:ComponentFocusRequest|undefined,context:ComponentFocusContext):boolean {
  const current=prepareComponentFocus(request,context);
  return current!==null&&current.requestKey===target.requestKey&&current.sourceKey===target.sourceKey;
}

export function sameComponentFocusView(a:ComponentFocusTarget|null,b:ComponentFocusTarget|null){
 return !!a&&!!b&&a.sourceKey===b.sourceKey&&a.token===b.token&&a.instanceId===b.instanceId
  &&JSON.stringify(a.componentKeys??[])===JSON.stringify(b.componentKeys??[])
  &&a.bounds.every((point,i)=>point.every((value,j)=>Math.abs(value-b.bounds[i][j])<1e-6));
}

/** Fit the verified world bounds directly from the current eye/target direction. */
export function componentFocusView(bounds:Bounds3,current:SceneView,fovDeg:number,aspect:number,showContext=false):SceneView|null {
  if(!validBounds(bounds)||!vector(current.eye)||!vector(current.target)||!Number.isFinite(fovDeg)||
    fovDeg<=0||fovDeg>=179||!Number.isFinite(aspect)||aspect<=0)return null;
  const target=bounds[0].map((number,index)=>number+(bounds[1][index]-number)/2) as Vector3;
  const radius=Math.hypot(...bounds[0].map((number,index)=>bounds[1][index]-number))/2;
  const halfVertical=fovDeg*Math.PI/360,halfHorizontal=Math.atan(Math.tan(halfVertical)*aspect);
  const distance=Math.max(showContext?6:3,radius/Math.sin(Math.min(halfVertical,halfHorizontal))*(showContext?1.7:1.15));
  let direction=current.eye.map((number,index)=>number-current.target[index]);
  let length=Math.hypot(...direction);
  if(!Number.isFinite(length))return null;
  if(length<1e-6){direction=[.9,.55,1.2];length=Math.hypot(...direction);}
  if(showContext){
    if(Math.hypot(direction[0],direction[2])<1e-6)direction=[.9,direction[1],1.2];
    const horizontal=Math.hypot(direction[0],direction[2]);
    direction[1]=horizontal*Math.max(.3,Math.min(.7,direction[1]/horizontal));length=Math.hypot(...direction);
  }
  const eye=target.map((number,index)=>number+direction[index]/length*distance) as Vector3;
  return vector(eye)&&vector(target)&&Math.hypot(...eye.map((number,index)=>number-target[index]))>1e-12?{eye,target}:null;
}
