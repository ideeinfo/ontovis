import {useEffect,useRef,useState} from 'react';
import {Focus,Maximize,ZoomIn,ZoomOut} from 'lucide-react';
import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {ApiError,cancelled,failureMessage,type WorkbenchApi} from './api';
import {usePreferences} from './Preferences';
import {IconBtn} from './Primitives';
import {SceneResourceCache,cloneModel} from './sceneResourceCache';
import {sceneModelHit,type SceneComponentPick} from './sceneComponentPick';
import {toDisplay,trueHeadingToThreeYaw} from './sceneTransforms';
import {sceneViewportMessage} from './sceneViewportMessages';
import {componentFocusCurrent,componentFocusKey,componentFocusView,prepareComponentFocus,type ComponentFocusRequest,type ComponentFocusTarget} from './sceneComponentFocus';
import type {ProjectModelVersion,TerrainVersion} from './resourceTypes';
import type {EditableSceneSnapshot,ModelResourceRef,SceneModelInstance,SceneView,Vector3} from './sceneTypes';
import './sceneViewport.css';

export interface SceneViewportProps {
  api:WorkbenchApi;snapshot:EditableSceneSnapshot;modelRefs:ModelResourceRef[];terrainVersion:TerrainVersion|null;
  selectedId:string|null;editing:boolean;disabled?:boolean;personalVisibility:Record<string,boolean>;
  terrainVisible:boolean;pendingPlacement:boolean;previewModel?:ProjectModelVersion|null;
  viewCommand?:{token:number;view:SceneView};focusRequest?:{token:number;instanceId:string|null};
  componentFocus?:ComponentFocusRequest;
  componentPickingInstanceId?:string|null;onComponentPick?:(pick:SceneComponentPick)=>void;
  onSelect:(id:string|null)=>void;onPoint:(point:Vector3)=>void;
  onMove:(id:string,point:Vector3)=>Promise<boolean>;onViewChange:(view:SceneView)=>void;
  onResourceDrop?:(ref:{modelAssetId:string;modelVersionId:string},point:Vector3)=>void;
  onError?:(error:unknown)=>void;
}
type Runtime={sync:()=>void;appearance:()=>void;fit:()=>void;focus:(id:string|null)=>void;
  componentFocus:()=>void;setView:(view:SceneView)=>void;zoom:(factor:number)=>void};
type Entry={root:THREE.Group;key:string};
class ViewportInteractionError extends Error {
  readonly messageKey:'moveFailed'|'dropInvalid';
  constructor(key:'moveFailed'|'dropInvalid'){super(key);this.messageKey=key;}
}
const DROP_MIME='application/x-ontovis-model-version';
const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
function view(camera:THREE.Camera,orbit:OrbitControls):SceneView {
  return {eye:camera.position.toArray() as Vector3,target:orbit.target.toArray() as Vector3};
}
function disposeMaterial(material:THREE.Material|THREE.Material[]) {
  for(const item of Array.isArray(material)?material:[material])item.dispose();
}

/** One persistent canvas; snapshot and selection updates never recreate its camera or GLB cache. */
export function SceneViewport(props:SceneViewportProps) {
  const {locale,resolved}=usePreferences();
  const current=useRef({...props,locale,resolved});current.current={...props,locale,resolved};
  const mount=useRef<HTMLDivElement>(null),runtime=useRef<Runtime|null>(null);
  const [reading,setReading]=useState(false),[error,setError]=useState<unknown>(null),[moving,setMoving]=useState(false);
  const [attempt,setAttempt]=useState(0),[rendererAttempt,setRendererAttempt]=useState(0);
  const webglFailure=useRef(false);
  const message=(key:Parameters<typeof sceneViewportMessage>[1])=>sceneViewportMessage(locale,key);
  const errorMessage=webglFailure.current?message('unavailable'):error instanceof ViewportInteractionError?message(error.messageKey):
    error instanceof ApiError&&error.code==='MODEL_REFERENCE_REQUIRED'?message('modelReferenceRequired'):
    error instanceof ApiError&&['INVALID_CALIBRATION','UNSUPPORTED_CALIBRATION'].includes(error.code)?message('invalidCalibration'):failureMessage(error,locale);

  useEffect(()=>{
    const element=mount.current;if(!element)return;
    const api=props.api,epoch=api.epoch,revision=api.revision;
    let disposed=false,renderer:THREE.WebGLRenderer;
    try {renderer=new THREE.WebGLRenderer({antialias:true,powerPreference:'high-performance'});webglFailure.current=false;}
    catch(value){webglFailure.current=true;setError(value);props.onError?.(value);return;}
    const cache=new SceneResourceCache(api),scene=new THREE.Scene();
    const camera=new THREE.PerspectiveCamera(42,1,.05,2_000_000);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,1.5));renderer.outputColorSpace=THREE.SRGBColorSpace;
    renderer.domElement.setAttribute('role','img');renderer.domElement.tabIndex=0;
    element.append(renderer.domElement);
    const orbit=new OrbitControls(camera,renderer.domElement);orbit.enableDamping=false;orbit.maxDistance=300_000;
    const models=new THREE.Group();scene.add(models);
    const light=new THREE.HemisphereLight(0xf1f5ec,0x58694d,2.2);scene.add(light);
    const sun=new THREE.DirectionalLight(0xffe4bd,2.5);sun.position.set(-100,140,80);scene.add(sun);
    const grid=new THREE.GridHelper(2000,40,0x718174,0xa5b29f);grid.position.y=-.02;scene.add(grid);
    const selectedBox=new THREE.Box3Helper(new THREE.Box3(),0x007e6d);selectedBox.visible=false;scene.add(selectedBox);
    const componentBox=new THREE.Box3Helper(new THREE.Box3(),0x007e6d);componentBox.visible=false;scene.add(componentBox);
    (componentBox.material as THREE.LineBasicMaterial).depthTest=false;
    (componentBox.material as THREE.LineBasicMaterial).depthWrite=false;componentBox.renderOrder=1;
    const terrainMaterial=new THREE.MeshStandardMaterial({color:0x859b6c,roughness:1,side:THREE.FrontSide});
    const pixels=new Uint8Array(64*64*4);
    for(let index=0;index<64*64;index++){
      const n=((index*1664525+1013904223)>>>16)%29;
      pixels.set([105+n,126+n,75+n,255],index*4);
    }
    const grass=new THREE.DataTexture(pixels,64,64);grass.wrapS=grass.wrapT=THREE.RepeatWrapping;
    grass.colorSpace=THREE.SRGBColorSpace;grass.needsUpdate=true;
    const entries=new Map<string,Entry>();
    let terrain:THREE.Mesh<THREE.BufferGeometry,THREE.MeshStandardMaterial>|null=null,terrainKey='';
    let preview:THREE.Group|null=null,previewKey='',restoreView:SceneView|null=null;
    let generation=0,frame=0,hiddenAt:number|null=null,loadingAbort:AbortController|null=null;
    let focusPending:string|null|undefined;
    let tween:{start:number;from:SceneView;to:SceneView}|null=null;
    let componentTween=false,lastComponentRequest:string|null=null;
    let componentTarget:ComponentFocusTarget|null=null,componentPending:ComponentFocusTarget|null=null,componentFocused:ComponentFocusTarget|null=null;
    let pointer:{x:number;y:number;id:number}|null=null;
    let drag:{id:string;root:THREE.Group;original:THREE.Vector3;offset:THREE.Vector3;pointerId:number}|null=null;
    let movePending=false;
    let resourcesLoading=false,lastFrameRevision=current.current.snapshot.coordinateFrame.frameRevision;
    const stale=()=>disposed||api.epoch!==epoch||api.revision!==revision;
    const report=(value:unknown)=>{if(!stale()&&!cancelled(value)){setError(value);current.current.onError?.(value);}};
    const emit=()=>{if(!stale())current.current.onViewChange(view(camera,orbit));};
    const request=()=>{if(!disposed&&!document.hidden&&!frame)frame=requestAnimationFrame(render);};
    const render=()=>{
      frame=0;if(disposed)return;
      if(stale()){renderer.clear();return;}
      if(tween){
        const progress=Math.min(1,(performance.now()-tween.start)/900),ease=progress*progress*(3-2*progress);
        camera.position.lerpVectors(new THREE.Vector3(...tween.from.eye),new THREE.Vector3(...tween.to.eye),ease);
        orbit.target.lerpVectors(new THREE.Vector3(...tween.from.target),new THREE.Vector3(...tween.to.target),ease);orbit.update();
        if(progress>=1){tween=null;componentTween=false;emit();}
      }
      renderer.render(scene,camera);if(tween)request();
    };
    const moveView=(target:SceneView,animated=true,component=false)=>{
      componentTween=component;
      if(animated&&!matchMedia('(prefers-reduced-motion: reduce)').matches)tween={start:performance.now(),from:view(camera,orbit),to:structuredClone(target)};
      else {tween=null;componentTween=false;camera.position.fromArray(target.eye);orbit.target.fromArray(target.target);orbit.update();emit();}
      request();
    };
    const focusContext=()=>({snapshot:current.current.snapshot,selectedId:current.current.selectedId,
      modelRefs:current.current.modelRefs,personalVisibility:current.current.personalVisibility,previewActive:!!current.current.previewModel});
    const clearComponentFocus=()=>{
      if(componentTween)tween=null;componentTween=false;
      componentTarget=null;componentPending=null;componentFocused=null;componentBox.visible=false;
    };
    const componentHighlight=()=>{
      const state=current.current,key=componentFocusKey(state.componentFocus);
      if(key!==lastComponentRequest){
        clearComponentFocus();lastComponentRequest=key;
        componentTarget=prepareComponentFocus(state.componentFocus,focusContext());componentPending=componentTarget;
        if(componentTarget)focusPending=undefined;
      }
      if(componentTarget&&!componentFocusCurrent(componentTarget,state.componentFocus,focusContext()))clearComponentFocus();
      const entry=componentTarget?entries.get(componentTarget.instanceId):undefined;
      if(componentPending&&!resourcesLoading&&entry?.key===componentPending.modelKey&&entry.root.visible&&!preview){
        const destination=componentFocusView(componentPending.bounds,view(camera,orbit),camera.fov,camera.aspect);
        if(destination){componentFocused=componentPending;moveView(destination,true,true);}
        componentPending=null;
      }
      componentBox.visible=!!componentFocused&&!!entry&&entry.key===componentFocused.modelKey&&entry.root.visible&&!preview;
      if(componentFocused&&componentBox.visible){
        componentBox.box.min.fromArray(componentFocused.bounds[0]);componentBox.box.max.fromArray(componentFocused.bounds[1]);
        componentBox.updateMatrixWorld(true);
      }
      return componentTarget!==null;
    };
    const bounds=(id?:string|null)=>{
      if(preview)return new THREE.Box3().setFromObject(preview);
      if(id&&entries.has(id))return new THREE.Box3().setFromObject(entries.get(id)!.root);
      const box=new THREE.Box3();
      for(const item of entries.values())if(item.root.visible)box.union(new THREE.Box3().setFromObject(item.root));
      if(terrain&&terrain.visible)box.union(new THREE.Box3().setFromObject(terrain));
      return box.isEmpty()?new THREE.Box3(new THREE.Vector3(-30,0,-30),new THREE.Vector3(30,40,30)):box;
    };
    const fit=(id?:string|null)=>{
      const box=bounds(id);if(box.isEmpty())return;
      const center=box.getCenter(new THREE.Vector3()),size=box.getSize(new THREE.Vector3());
      const distance=Math.max(3,size.length()/(2*Math.tan(THREE.MathUtils.degToRad(camera.fov/2)))*1.15);
      const direction=camera.position.clone().sub(orbit.target);if(direction.lengthSq()<1e-12)direction.set(.9,.55,1.2);
      moveView({eye:center.clone().add(direction.normalize().multiplyScalar(distance)).toArray() as Vector3,
        target:center.toArray() as Vector3});
    };
    const highlight=()=>{
      const entry=current.current.selectedId?entries.get(current.current.selectedId):null;
      const componentActive=componentHighlight();
      selectedBox.visible=!componentActive&&!!entry&&entry.root.visible&&!preview;
      if(entry&&selectedBox.visible){entry.root.updateMatrixWorld(true);selectedBox.box.setFromObject(entry.root);selectedBox.updateMatrixWorld(true);}
      request();
    };
    const appearance=()=>{
      const state=current.current;
      if(drag&&(!state.editing||state.disabled||state.previewModel||state.pendingPlacement))cancelDrag();
      for(const item of state.snapshot.instances){const entry=entries.get(item.sceneModelInstanceId);if(entry)entry.root.visible=(state.personalVisibility[item.sceneModelInstanceId]??item.visible)&&!preview;}
      grid.visible=state.snapshot.coordinateFrame.mode==='local_plane'&&!preview;
      if(terrain)terrain.visible=state.terrainVisible&&!preview;
      const color=getComputedStyle(document.documentElement).getPropertyValue('--primary').trim()||'#007e6d';
      const material=selectedBox.material as THREE.LineBasicMaterial;material.color.set(color);
      (componentBox.material as THREE.LineBasicMaterial).color.set(color);
      renderer.domElement.setAttribute('aria-label',sceneViewportMessage(state.locale,'view'));
      const dusk=state.snapshot.defaults.lighting==='dusk';
      sun.color.set(dusk?0xffca93:0xfff4df);sun.intensity=dusk?1.8:2.5;
      sun.position.set(dusk?-180:-100,dusk?65:140,80);light.intensity=dusk?1.7:2.2;
      scene.background=new THREE.Color(state.snapshot.defaults.background==='sky'?(dusk?0xcdd4c6:0xb8d1da):0xd8e0d4);
      terrainMaterial.map=state.snapshot.defaults.terrainMaterial==='grass'?grass:null;terrainMaterial.needsUpdate=true;
      orbit.enabled=!state.disabled&&!drag;highlight();
    };
    const transform=(item:SceneModelInstance,root:THREE.Group)=>{
      root.position.fromArray(toDisplay(current.current.snapshot.coordinateFrame,item.placement.position,item.placement.height));
      const geographic=item.placement.position.mode==='geographic'?item.placement.position:null;
      root.rotation.y=trueHeadingToThreeYaw(current.current.snapshot.coordinateFrame,item.placement.headingDeg,
        geographic?.longitude,geographic?.latitude);root.updateMatrixWorld(true);
    };
    const cancelDrag=()=>{
      if(drag){
        if(renderer.domElement.hasPointerCapture(drag.pointerId))renderer.domElement.releasePointerCapture(drag.pointerId);
        drag.root.position.copy(drag.original);drag=null;orbit.enabled=!current.current.disabled;highlight();
      }
      pointer=null;
    };
    const sync=async()=>{
      const ticket=++generation;loadingAbort?.abort();loadingAbort=new AbortController();const signal=loadingAbort.signal;
      const state=current.current;cancelDrag();resourcesLoading=true;setReading(true);setError(null);
      highlight();
      if(state.snapshot.coordinateFrame.frameRevision!==lastFrameRevision){
        lastFrameRevision=state.snapshot.coordinateFrame.frameRevision;
        if(restoreView)restoreView=structuredClone(state.snapshot.initialView);else moveView(state.snapshot.initialView);
      }
      const wanted=new Set(state.snapshot.instances.map(item=>item.sceneModelInstanceId));
      for(const [id,entry] of entries)if(!wanted.has(id)){models.remove(entry.root);entries.delete(id);}
      const tasks=state.snapshot.instances.map(async item=>{
        const ref=state.modelRefs.find(value=>value.modelVersionId===item.modelVersionId);
        if(!ref){
          const prior=entries.get(item.sceneModelInstanceId);if(prior){models.remove(prior.root);entries.delete(item.sceneModelInstanceId);}
          throw new ApiError(409,'RESOURCE_CHANGED');
        }
        const key=JSON.stringify([ref.modelVersionId,ref.contentRevision,ref.sha256]);
        let entry=entries.get(item.sceneModelInstanceId);
        if(entry?.key!==key){
          if(entry){models.remove(entry.root);entries.delete(item.sceneModelInstanceId);}
          const resource=await cache.model(ref,signal);if(stale()||ticket!==generation)return;
          entry={root:cloneModel(resource,item.sceneModelInstanceId),key};entries.set(item.sceneModelInstanceId,entry);models.add(entry.root);
        }
        try {transform(item,entry.root);}
        catch(value){models.remove(entry.root);entries.delete(item.sceneModelInstanceId);throw value;}
      });
      tasks.push((async()=>{
        const version=state.terrainVersion,reference=state.snapshot.terrain;
        const clearTerrain=()=>{if(terrain){scene.remove(terrain);terrain=null;}terrainKey='';};
        if(!reference){clearTerrain();return;}
        if(!version){clearTerrain();throw new ApiError(503,'PROCESSING_UNAVAILABLE');}
        if(state.snapshot.coordinateFrame.mode!=='projected_site'||reference.terrainVersionId!==version.terrainVersionId
          ||reference.expectedContentRevision!==version.contentRevision){clearTerrain();throw new ApiError(409,'RESOURCE_CHANGED');}
        const key=JSON.stringify([version.terrainVersionId,version.contentRevision,version.expectedReportSha256]);
        const frameData=state.snapshot.coordinateFrame,resource=version.report.mesh.frame;
        if(resource.horizontalCrs!==frameData.horizontalCrs||resource.transformId!==frameData.transformId
          ||resource.verticalDatum!==frameData.verticalDatum||resource.convergenceRuleId!==frameData.convergenceRuleId
          ||frameData.verticalDatum==='UNKNOWN_RELATIVE'&&version.report.source.relativeReferenceId!==frameData.relativeReferenceId)
          {clearTerrain();throw new ApiError(409,'RESOURCE_CHANGED');}
        if(key!==terrainKey){
          if(terrain){scene.remove(terrain);terrain=null;}terrainKey='';
          const geometry=await cache.terrain(version,signal);if(stale()||ticket!==generation)return;
          if(!geometry.getAttribute('uv')){
            const positions=geometry.getAttribute('position'),uv=new Float32Array(positions.count*2);
            for(let index=0;index<positions.count;index++){uv[index*2]=positions.getX(index)/30;uv[index*2+1]=positions.getZ(index)/30;}
            geometry.setAttribute('uv',new THREE.BufferAttribute(uv,2));
          }
          terrain=new THREE.Mesh(geometry,terrainMaterial);scene.add(terrain);terrainKey=key;
        }
        terrain?.position.set(resource.originEasting-frameData.originEasting,resource.originHeight-frameData.originHeight,
          frameData.originNorthing-resource.originNorthing);terrain?.updateMatrixWorld(true);
      })());
      tasks.push((async()=>{
        const version=state.previewModel;
        if(!version){
          if(preview){scene.remove(preview);preview=null;}
          previewKey='';if(restoreView)moveView(restoreView);restoreView=null;
          appearance();
          return;
        }
        const key=JSON.stringify([version.modelVersionId,version.contentRevision,version.sha256]);
        if(key===previewKey)return;
        if(!restoreView)restoreView=view(camera,orbit);
        if(preview){scene.remove(preview);preview=null;}previewKey='';
        const resource=await cache.model(version,signal);if(stale()||ticket!==generation)return;
        preview=cloneModel(resource,'resource-preview',{calibrated:false});scene.add(preview);previewKey=key;appearance();fit();
      })());
      const results=await Promise.allSettled(tasks);if(stale()||ticket!==generation)return;
      const failed=results.find(value=>value.status==='rejected');if(failed?.status==='rejected')report(failed.reason);
      resourcesLoading=false;setReading(false);appearance();
      if(focusPending!==undefined){const id=focusPending;focusPending=undefined;fit(id);}
    };
    const ray=new THREE.Raycaster(),plane=new THREE.Plane(new THREE.Vector3(0,1,0),0);
    const prepareRay=(x:number,y:number)=>{
      const rect=renderer.domElement.getBoundingClientRect();
      ray.setFromCamera(new THREE.Vector2((x-rect.left)/Math.max(1,rect.width)*2-1,-(y-rect.top)/Math.max(1,rect.height)*2+1),camera);
    };
    const groundPoint=(x:number,y:number)=>{
      prepareRay(x,y);
      if(current.current.snapshot.coordinateFrame.mode==='projected_site'){
        if(!terrain)return null;return ray.intersectObject(terrain,false)[0]?.point.clone()||null;
      }
      return ray.ray.intersectPlane(plane,new THREE.Vector3());
    };
    const hitModel=(x:number,y:number)=>{
      prepareRay(x,y);
      const active=current.current.componentPickingInstanceId;
      const target=active?entries.get(active)?.root:models;if(!target)return null;
      for(const hit of ray.intersectObject(target,true)){
        const result=sceneModelHit(hit.object,models);if(result)return result;
      }
      return null;
    };
    const hitId=(x:number,y:number)=>hitModel(x,y)?.sceneModelInstanceId??null;
    const down=(event:PointerEvent)=>{
      if(event.button!==0)return;tween=null;componentTween=false;componentPending=null;
      pointer={x:event.clientX,y:event.clientY,id:event.pointerId};
      const state=current.current;if(state.disabled||state.previewModel||!state.editing||state.pendingPlacement||movePending||state.componentPickingInstanceId)return;
      const id=hitId(event.clientX,event.clientY),item=state.snapshot.instances.find(value=>value.sceneModelInstanceId===id);
      const entry=id?entries.get(id):null,point=groundPoint(event.clientX,event.clientY);
      if(!id||!item||!entry||item.positionLocked||!point)return;
      tween=null;current.current.onSelect(id);drag={id,root:entry.root,original:entry.root.position.clone(),
        offset:entry.root.position.clone().sub(point),pointerId:event.pointerId};
      orbit.enabled=false;renderer.domElement.setPointerCapture(event.pointerId);
    };
    const motion=(event:PointerEvent)=>{
      if(!drag||event.pointerId!==drag.pointerId)return;
      const point=groundPoint(event.clientX,event.clientY);if(!point)return;
      drag.root.position.set(point.x+drag.offset.x,drag.original.y,point.z+drag.offset.z);drag.root.updateMatrixWorld(true);highlight();
    };
    const up=(event:PointerEvent)=>{
      const clicked=pointer&&pointer.id===event.pointerId&&Math.hypot(pointer.x-event.clientX,pointer.y-event.clientY)<=4;
      pointer=null;
      if(drag&&drag.pointerId===event.pointerId){
        const movement=drag;drag=null;orbit.enabled=!current.current.disabled;
        if(renderer.domElement.hasPointerCapture(event.pointerId))renderer.domElement.releasePointerCapture(event.pointerId);
        const releasePoint=groundPoint(event.clientX,event.clientY);
        if(!releasePoint){movement.root.position.copy(movement.original);report(new ApiError(422,'NO_DATA'));highlight();return;}
        movement.root.position.set(releasePoint.x+movement.offset.x,movement.original.y,releasePoint.z+movement.offset.z);
        movement.root.updateMatrixWorld(true);
        if(movement.root.position.distanceTo(movement.original)<1e-6){highlight();return;}
        movePending=true;setMoving(true);const destination=movement.root.position.toArray() as Vector3;
        const ticket=generation;
        void Promise.resolve().then(()=>current.current.onMove(movement.id,destination)).then(accepted=>{
          if(!accepted&&!stale()&&ticket===generation&&entries.get(movement.id)?.root===movement.root){movement.root.position.copy(movement.original);report(new ViewportInteractionError('moveFailed'));}
        }).catch(value=>{if(!stale()&&ticket===generation&&entries.get(movement.id)?.root===movement.root)movement.root.position.copy(movement.original);report(value);})
          .finally(()=>{movePending=false;if(!stale()){setMoving(false);highlight();}});
        return;
      }
      const state=current.current;if(!clicked||state.disabled||state.previewModel)return;
      if(state.componentPickingInstanceId){
        const hit=hitModel(event.clientX,event.clientY);
        if(hit?.sceneModelInstanceId===state.componentPickingInstanceId&&hit.component)state.onComponentPick?.(hit.component);
        return;
      }
      if(state.editing&&state.pendingPlacement){const point=groundPoint(event.clientX,event.clientY);if(point)state.onPoint(point.toArray() as Vector3);}
      else state.onSelect(hitId(event.clientX,event.clientY));
    };
    const escape=(event:KeyboardEvent)=>{if(event.key==='Escape'&&drag){event.preventDefault();cancelDrag();}};
    const drop=(event:DragEvent)=>{
      const state=current.current;if(!state.editing||state.disabled||state.previewModel||!state.onResourceDrop)return;
      const raw=event.dataTransfer?.getData(DROP_MIME);if(!raw)return;event.preventDefault();
      try {
        if(raw.length>512)throw new Error('invalid');const value:unknown=JSON.parse(raw);
        if(!value||typeof value!=='object'||Object.keys(value).sort().join(',')!=='modelAssetId,modelVersionId')throw new Error('invalid');
        const reference=value as {modelAssetId:string;modelVersionId:string};
        if(!uuid.test(reference.modelAssetId)||!uuid.test(reference.modelVersionId))throw new Error('invalid');
        const point=groundPoint(event.clientX,event.clientY);if(point)state.onResourceDrop(reference,point.toArray() as Vector3);
      } catch {report(new ViewportInteractionError('dropInvalid'));}
    };
    const dragover=(event:DragEvent)=>{const state=current.current;if(state.editing&&!state.disabled&&!state.previewModel&&state.onResourceDrop
      &&event.dataTransfer?.types.includes(DROP_MIME)){event.preventDefault();event.dataTransfer.dropEffect='copy';}};
    const visible=()=>{
      if(document.hidden){hiddenAt=performance.now();cancelAnimationFrame(frame);frame=0;}
      else {if(tween&&hiddenAt!==null)tween.start+=performance.now()-hiddenAt;hiddenAt=null;request();}
    };
    const resize=new ResizeObserver(()=>{const rect=element.getBoundingClientRect();camera.aspect=Math.max(1,rect.width)/Math.max(1,rect.height);
      camera.updateProjectionMatrix();renderer.setSize(Math.max(1,rect.width),Math.max(1,rect.height));request();});resize.observe(element);
    const orbitStart=()=>{tween=null;componentTween=false;componentPending=null;};orbit.addEventListener('change',request);orbit.addEventListener('start',orbitStart);orbit.addEventListener('end',emit);
    const canvas=renderer.domElement;
    canvas.addEventListener('pointerdown',down,true);canvas.addEventListener('pointermove',motion);canvas.addEventListener('pointerup',up);
    canvas.addEventListener('pointercancel',cancelDrag);canvas.addEventListener('keydown',escape);canvas.addEventListener('drop',drop);canvas.addEventListener('dragover',dragover);
    document.addEventListener('visibilitychange',visible);
    runtime.current={sync:()=>void sync(),appearance,componentFocus:highlight,
      fit:()=>{clearComponentFocus();if(resourcesLoading)focusPending=null;else fit();highlight();},
      focus:id=>{clearComponentFocus();if(resourcesLoading||id&&!entries.has(id))focusPending=id;else fit(id);highlight();},
      setView:target=>{if(restoreView)restoreView=structuredClone(target);else moveView(target);},
      zoom:factor=>{tween=null;componentTween=false;componentPending=null;camera.position.sub(orbit.target).multiplyScalar(factor).add(orbit.target);request();emit();}};
    moveView(current.current.snapshot.initialView,false);void sync();
    return ()=>{
      disposed=true;++generation;loadingAbort?.abort();cancelAnimationFrame(frame);resize.disconnect();document.removeEventListener('visibilitychange',visible);
      canvas.removeEventListener('pointerdown',down,true);canvas.removeEventListener('pointermove',motion);canvas.removeEventListener('pointerup',up);
      canvas.removeEventListener('pointercancel',cancelDrag);canvas.removeEventListener('keydown',escape);canvas.removeEventListener('drop',drop);canvas.removeEventListener('dragover',dragover);
      orbit.dispose();cache.dispose();selectedBox.geometry.dispose();disposeMaterial(selectedBox.material);
      componentBox.geometry.dispose();disposeMaterial(componentBox.material);
      grid.geometry.dispose();disposeMaterial(grid.material);terrainMaterial.dispose();grass.dispose();scene.clear();
      renderer.dispose();renderer.forceContextLoss();canvas.remove();runtime.current=null;
    };
  },[props.api,props.api.epoch,props.api.revision,rendererAttempt]);
  useEffect(()=>{runtime.current?.sync();},[props.snapshot,props.modelRefs,props.terrainVersion,props.previewModel,attempt]);
  useEffect(()=>{runtime.current?.appearance();},[props.selectedId,props.personalVisibility,props.terrainVisible,props.disabled,props.editing,props.pendingPlacement,locale,resolved]);
  useEffect(()=>{if(props.viewCommand)runtime.current?.setView(props.viewCommand.view);},[props.viewCommand?.token]);
  useEffect(()=>{if(props.focusRequest)runtime.current?.focus(props.focusRequest.instanceId);},[props.focusRequest?.token]);
  useEffect(()=>{runtime.current?.componentFocus();},[props.componentFocus,props.snapshot,props.modelRefs,props.selectedId,props.personalVisibility,props.previewModel]);
  return <section className="ov-scene-viewport" aria-label={message('view')}>
    <div className="ov-scene-viewport-stage"><div ref={mount} className="ov-scene-viewport-canvas"/>
      {(reading||!!error) && <div className="ov-scene-viewport-state" role={error?'alert':'status'}>{error?errorMessage:message('loading')}
        {error?<button className="ov-btn" onClick={()=>webglFailure.current?setRendererAttempt(value=>value+1):setAttempt(value=>value+1)}>{message('retry')}</button>:null}</div>}
      <div className="ov-scene-viewport-tools"><IconBtn label={message('zoomIn')} onClick={()=>runtime.current?.zoom(.8)}><ZoomIn size={16}/></IconBtn>
        <IconBtn label={message('zoomOut')} onClick={()=>runtime.current?.zoom(1.25)}><ZoomOut size={16}/></IconBtn>
        <IconBtn label={message('fit')} onClick={()=>runtime.current?.fit()}><Maximize size={16}/></IconBtn>
        <IconBtn label={message('focus')} disabled={!props.selectedId||!!props.previewModel} onClick={()=>runtime.current?.focus(props.selectedId)}><Focus size={16}/></IconBtn></div>
    </div><footer className="ov-scene-viewport-foot"><span>{props.previewModel?`${message('preview')} · ${props.previewModel.displayName}`:
      moving?message('moving'):props.editing?props.pendingPlacement?message('place'):message('drag'):message('browse')}</span>
      {props.previewModel?.calibration.state==='unverified'?<span>{message('unverified')}</span>:null}</footer>
  </section>;
}
