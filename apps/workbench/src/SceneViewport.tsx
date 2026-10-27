import {useEffect,useRef,useState} from 'react';
import {Focus,Maximize,ZoomIn,ZoomOut} from 'lucide-react';
import * as THREE from 'three';
import type {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {ApiError,cancelled,failureMessage,type WorkbenchApi} from './api';
import {usePreferences} from './Preferences';
import {IconBtn} from './Primitives';
import {SceneResourceCache,cloneModel} from './sceneResourceCache';
import {createSceneControls} from './sceneControls';
import {cursorZoomView,visibleZoomHit} from './sceneZoom';
import {prepareSceneRenderer} from './sceneRenderer';
import {selectedModelBounds,selectedModelView} from './sceneModelFocus';
import {SceneCabinetAppearance} from './sceneCabinetAppearance';
import {ModelPreviewInspection} from './modelPreview';
import {previewIdentity,type PreviewSelection,type PreviewStructure} from './modelPreviewTypes';
import {sceneModelRayHit,type SceneComponentPick} from './sceneComponentPick';
import {toDisplay,trueHeadingToThreeYaw} from './sceneTransforms';
import {sceneViewportMessage} from './sceneViewportMessages';
import {componentFocusCurrent,componentFocusKey,componentFocusView,prepareComponentFocus,type ComponentFocusRequest,type ComponentFocusTarget} from './sceneComponentFocus';
import type {ProjectModelVersion,TerrainVersion} from './resourceTypes';
import type {EditableSceneSnapshot,ModelResourceRef,SceneModelInstance,SceneView,Vector3} from './sceneTypes';
import {snapPoint} from './sceneOrganization';
import {SceneApi} from './sceneApi';
import {SceneEnvironmentRuntime} from './sceneEnvironmentRuntime';
import type {SceneEnvironmentV1} from './sceneEnvironment';
import {SceneImageryLayer} from './sceneImagery';
import {imageryFailure,imageryText} from './imageryMessages';
import type {ImageryRecord} from './resourceTypes';
import {SceneLoadingProgress} from './SceneLoadingProgress';
import {SceneLoadingTracker,sceneLoadingPlan,sceneLoadingIdentity,modelLoadingKey,terrainLoadingKey,imageryLoadingKey,type SceneLoadingState} from './sceneLoading';
import './sceneViewport.css';

export interface SceneCameraControl {getView:()=>SceneView;setView:(value:SceneView)=>void;ready:()=>boolean}
export interface SceneViewportProps {
  preparationKey?:string;preparationError?:unknown;onRetryPreparation?:()=>void;
  environmentPreview?:{value:SceneEnvironmentV1|null}|null;
  api:WorkbenchApi;snapshot:EditableSceneSnapshot;modelRefs:ModelResourceRef[];terrainVersion:TerrainVersion|null;
  selectedId:string|null;editing:boolean;disabled?:boolean;personalVisibility:Record<string,boolean>;
  selectedIds?:string[];gridSnap?:number;cameraControl?:{current:SceneCameraControl|null};onCameraInteraction?:()=>void;
  terrainVisible:boolean;pendingPlacement:boolean;placementModel?:ProjectModelVersion|null;previewModel?:ProjectModelVersion|null;
  imageryVersion?:ImageryRecord|null;imageryVisible?:boolean;
  viewCommand?:{token:number;view:SceneView};focusRequest?:{token:number;instanceId:string|null;instanceIds?:string[]};
  componentFocus?:ComponentFocusRequest;
  componentPickingInstanceId?:string|null;onComponentPick?:(pick:SceneComponentPick)=>void;
  previewSelection?:PreviewSelection;onPreviewStructure?:(value:PreviewStructure|null)=>void;
  onPreviewPick?:(identity:string,nodeId:string|null)=>void;
  onSelect:(id:string|null,additive?:boolean)=>void;onPoint:(point:Vector3)=>void;
  onMove:(id:string,point:Vector3)=>Promise<boolean>;onViewChange:(view:SceneView)=>void;
  onResourceDrop?:(ref:{modelAssetId:string;modelVersionId:string},point:Vector3)=>void;
  onError?:(error:unknown)=>void;
}
type Runtime={sync:()=>void;preload:()=>void;appearance:()=>void;fit:()=>void;focus:(id:string|null|string[])=>void;
  componentFocus:()=>void;previewSelection:()=>void;setView:(view:SceneView)=>void;zoom:(factor:number)=>void};
type Entry={root:THREE.Group;key:string;appearance:SceneCabinetAppearance};
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
  const [loadingState,setLoadingState]=useState<SceneLoadingState>();
  const [reading,setReading]=useState(true),[error,setError]=useState<unknown>(null),[moving,setMoving]=useState(false);
  const [waterOverride,setWaterOverride]=useState<boolean|null>(null),[cloudOverride,setCloudOverride]=useState<boolean|null>(null),[reduced,setReduced]=useState(()=>matchMedia('(prefers-reduced-motion: reduce)').matches);
  const [environmentStatus,setEnvironmentStatus]=useState({water:false,clouds:false,surroundings:null as 'land'|'offshore'|null,casters:0,phase:0,cloudPhase:0,fallback:false,textureBudgetBytes:0});
  const motionState=useRef({waterOverride,cloudOverride,reduced});motionState.current={waterOverride,cloudOverride,reduced};
  const previewMotion=useRef<{override:boolean|null;playback?:'playing'|'paused';cloudOverride:boolean|null;cloudPlayback?:'playing'|'paused';cloudReset:boolean;environment:SceneEnvironmentV1|null|undefined;resetPlayback:boolean}|null>(null);
  useEffect(()=>{if(props.environmentPreview){
      const value=props.environmentPreview.value,playback=value?.animation.defaultPlayback,cloudPlayback=value?.atmosphere.clouds?.defaultPlayback;
      if(!previewMotion.current)previewMotion.current={override:waterOverride,playback:props.snapshot.environment?.animation.defaultPlayback,cloudOverride,cloudPlayback:props.snapshot.environment?.atmosphere.clouds?.defaultPlayback,cloudReset:false,environment:props.snapshot.environment,resetPlayback:false};
      // An explicit preset or playback edit previews its default, independently of a prior personal pause.
      if(value?.presetId==='offshore-overview-v1'||playback!==previewMotion.current.playback){setWaterOverride(null);previewMotion.current.resetPlayback=true;}
      if((value&&value.presetId!=='custom-v1')||cloudPlayback!==previewMotion.current.cloudPlayback){setCloudOverride(null);previewMotion.current.cloudReset=true;}
      previewMotion.current.playback=playback;
      previewMotion.current.cloudPlayback=cloudPlayback;
    }else if(previewMotion.current){const previous=previewMotion.current;setWaterOverride(previous.resetPlayback&&props.snapshot.environment!==previous.environment?null:previous.override);setCloudOverride(previous.cloudReset&&props.snapshot.environment!==previous.environment?null:previous.cloudOverride);previewMotion.current=null;}},[props.environmentPreview]);
  useEffect(()=>{const media=matchMedia('(prefers-reduced-motion: reduce)'),change=()=>{setReduced(media.matches);setWaterOverride(null);setCloudOverride(null);};media.addEventListener('change',change);return()=>media.removeEventListener('change',change);},[]);
  const [imageryPartial,setImageryPartial]=useState(false);
  const latestError=useRef(error);latestError.current=error;
  const [attempt,setAttempt]=useState(0),[rendererAttempt,setRendererAttempt]=useState(0);
  const webglFailure=useRef(false);
  const message=(key:Parameters<typeof sceneViewportMessage>[1])=>sceneViewportMessage(locale,key);
  const displayError=props.preparationError||error;
  const errorMessage=webglFailure.current?message('unavailable'):displayError instanceof ViewportInteractionError?message(displayError.messageKey):
    displayError instanceof ApiError&&displayError.code==='MODEL_REFERENCE_REQUIRED'?message('modelReferenceRequired'):
    displayError instanceof ApiError&&['INVALID_CALIBRATION','UNSUPPORTED_CALIBRATION'].includes(displayError.code)?message('invalidCalibration'):failureMessage(displayError,locale);

  useEffect(()=>{
    const element=mount.current;if(!element)return;
    const api=props.api,epoch=api.epoch,revision=api.revision;
    let disposed=false,renderer:THREE.WebGLRenderer;
    try {renderer=prepareSceneRenderer(new THREE.WebGLRenderer({antialias:true,powerPreference:'high-performance'}));webglFailure.current=false;}
    catch(value){webglFailure.current=true;setError(value);props.onError?.(value);return;}
    const cache=new SceneResourceCache(api),scene=new THREE.Scene(),imageryLayer=new SceneImageryLayer(new SceneApi(api));
    const camera=new THREE.PerspectiveCamera(42,1,.05,2_000_000);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,1.5));renderer.outputColorSpace=THREE.SRGBColorSpace;
    renderer.domElement.setAttribute('role','img');renderer.domElement.tabIndex=0;
    element.append(renderer.domElement);
    const sceneControls=createSceneControls(camera,renderer.domElement),orbit=sceneControls.orbit;
    orbit.enableDamping=false;orbit.maxDistance=300_000;
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
    const environment=new SceneEnvironmentRuntime(scene,renderer,sun,light,terrainMaterial,grass);
    const entries=new Map<string,Entry>();
    let terrain:THREE.Mesh<THREE.BufferGeometry,THREE.MeshStandardMaterial>|null=null,terrainKey='';
    let preview:THREE.Group|null=null,previewKey='',restoreView:SceneView|null=null;
    let previewInspection:ModelPreviewInspection|null=null,lastPreviewFocus='';
    let generation=0,frame=0,hiddenAt:number|null=null,loadingAbort:AbortController|null=null;
    let focusPending:string|null|string[]|undefined;
    let tween:{start:number;from:SceneView;to:SceneView}|null=null;
    let componentTween=false,lastComponentRequest:string|null=null;
    let componentTarget:ComponentFocusTarget|null=null,componentPending:ComponentFocusTarget|null=null,componentFocused:ComponentFocusTarget|null=null;
    let pointer:{x:number;y:number;id:number}|null=null;
    let drag:{id:string;root:THREE.Group;original:THREE.Vector3;offset:THREE.Vector3;pointerId:number}|null=null;
    let movePending=false;
    let loading:SceneLoadingTracker|null=null,awaitingDisplay:SceneLoadingTracker|null=null;
    let resourcesLoading=false,lastFrameRevision=current.current.snapshot.coordinateFrame.frameRevision;
    const stale=()=>disposed||api.epoch!==epoch||api.revision!==revision;
    const report=(value:unknown)=>{if(!stale()&&!cancelled(value)){setError(value);current.current.onError?.(value);}};
    const emit=()=>{if(!stale())current.current.onViewChange(view(camera,orbit));};
    let dirtyFrame=true;
    let wheelPending:{x:number;y:number;delta:number}|null=null;
    const schedule=()=>{if(!disposed&&!document.hidden&&!frame)frame=requestAnimationFrame(render);};
    const request=()=>{dirtyFrame=true;schedule();};
    const render=()=>{
      frame=0;if(disposed||document.hidden)return;
      if(stale()){renderer.clear();return;}
      if(wheelPending){const pending=wheelPending;wheelPending=null;
        if(!resourcesLoading&&!current.current.disabled)zoomAt(pending.x,pending.y,Math.pow(.95,pending.delta/100));}
      if(tween){
        const progress=Math.min(1,(performance.now()-tween.start)/900),ease=progress*progress*(3-2*progress);
        camera.position.lerpVectors(new THREE.Vector3(...tween.from.eye),new THREE.Vector3(...tween.to.eye),ease);
        orbit.target.lerpVectors(new THREE.Vector3(...tween.from.target),new THREE.Vector3(...tween.to.target),ease);orbit.update();
        if(progress>=1){tween=null;componentTween=false;emit();}
      }
      const motion=motionState.current,playing=environment.playing(motion.waterOverride,motion.reduced),cloudPlaying=environment.cloudsPlaying(motion.cloudOverride,motion.reduced);
      const wave=environment.beforeRender(performance.now(),orbit.target,playing,cloudPlaying);
      if(dirtyFrame||tween||wave){
        try{renderer.render(scene,camera);dirtyFrame=false;}
        catch(value){loading?.fail();setReading(false);report(value);return;}
        if(awaitingDisplay===loading&&awaitingDisplay){awaitingDisplay.drawn();awaitingDisplay=null;resourcesLoading=false;setReading(false);}
      }
      if(tween||playing||cloudPlaying)schedule();
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
      for(const entry of entries.values())entry.appearance.restore();
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
      const color=getComputedStyle(document.documentElement).getPropertyValue('--primary').trim()||'#007e6d';
      for(const value of entries.values()){
        if(componentFocused&&value===entry&&componentBox.visible)value.appearance.apply(componentFocused.componentKeys??[],color);
        else value.appearance.restore();
      }
      return componentTarget!==null;
    };
    const bounds=(id?:string|null|string[])=>{
      if(Array.isArray(id))return selectedModelBounds(entries,id);
      if(preview)return new THREE.Box3().setFromObject(preview);
      if(id&&entries.has(id))return new THREE.Box3().setFromObject(entries.get(id)!.root);
      const box=new THREE.Box3();
      for(const item of entries.values())if(item.root.visible)box.union(new THREE.Box3().setFromObject(item.root));
      if(terrain&&terrain.visible)box.union(new THREE.Box3().setFromObject(terrain));
      return box.isEmpty()?new THREE.Box3(new THREE.Vector3(-30,0,-30),new THREE.Vector3(30,40,30)):box;
    };
    const fit=(id?:string|null|string[])=>{
      const box=bounds(id);if(box.isEmpty())return;
      if(Array.isArray(id)){const target=selectedModelView(camera,box,camera.position.clone().sub(orbit.target));if(target)moveView(target);return;}
      const center=box.getCenter(new THREE.Vector3()),size=box.getSize(new THREE.Vector3());
      const distance=Math.max(3,size.length()/(2*Math.tan(THREE.MathUtils.degToRad(camera.fov/2)))*1.15);
      const direction=camera.position.clone().sub(orbit.target);if(direction.lengthSq()<1e-12)direction.set(.9,.55,1.2);
      moveView({eye:center.clone().add(direction.normalize().multiplyScalar(distance)).toArray() as Vector3,
        target:center.toArray() as Vector3});
    };
    const previewSelection=()=>{
      if(!preview||!previewInspection||stale())return;
      const state=current.current,identity=previewIdentity(state.previewModel);
      if(identity!==previewInspection.structure.identity)return;
      const selection=state.previewSelection?.identity===identity?state.previewSelection:null;
      const color=getComputedStyle(document.documentElement).getPropertyValue('--primary').trim()||'#007e6d';
      previewInspection.apply(selection,color);
      const node=previewInspection.structure.nodes.find(row=>row.id===selection?.nodeId);
      componentBox.visible=!!node?.bounds;
      if(node?.bounds){componentBox.box.min.fromArray(node.bounds[0]);componentBox.box.max.fromArray(node.bounds[1]);componentBox.updateMatrixWorld(true);}
      const key=JSON.stringify([identity,selection?.focusToken??0]);
      if(lastPreviewFocus!==key){lastPreviewFocus=key;
        if(selection?.focusToken){
          if(node?.bounds){const destination=componentFocusView(node.bounds,view(camera,orbit),camera.fov,camera.aspect);if(destination)moveView(destination);}
          else if(!selection.nodeId)fit();
        }
      }
      request();
    };
    const highlight=()=>{
      const state=current.current,ids=state.selectedIds??(state.selectedId?[state.selectedId]:[]);
      const selectedEntries=ids.flatMap(id=>{const entry=entries.get(id);return entry?.root.visible?[entry]:[];});
      const componentActive=componentHighlight();
      selectedBox.visible=!componentActive&&selectedEntries.length>0&&!preview;
      if(selectedBox.visible){selectedBox.box.makeEmpty();for(const entry of selectedEntries){entry.root.updateMatrixWorld(true);selectedBox.box.union(new THREE.Box3().setFromObject(entry.root));}selectedBox.updateMatrixWorld(true);}
      previewSelection();
      request();
    };
    const appearance=()=>{
      const state=current.current;
      if(drag&&(!state.editing||state.disabled||state.previewModel||state.pendingPlacement))cancelDrag();
      for(const item of state.snapshot.instances){const entry=entries.get(item.sceneModelInstanceId);if(entry)entry.root.visible=(state.personalVisibility[item.sceneModelInstanceId]??item.visible)&&!preview;}
      grid.visible=state.snapshot.coordinateFrame.mode==='local_plane'&&!preview;
      if(terrain)terrain.visible=state.terrainVisible&&!preview;
      imageryLayer.visible(state.terrainVisible&&!!state.imageryVisible&&!preview);
      const color=getComputedStyle(document.documentElement).getPropertyValue('--primary').trim()||'#007e6d';
      const material=selectedBox.material as THREE.LineBasicMaterial;material.color.set(color);
      (componentBox.material as THREE.LineBasicMaterial).color.set(color);
      renderer.domElement.setAttribute('aria-label',sceneViewportMessage(state.locale,'view'));
      const dusk=state.snapshot.defaults.lighting==='dusk';
      sun.color.set(dusk?0xffca93:0xfff4df);sun.intensity=dusk?1.8:2.5;
      sun.position.set(dusk?-180:-100,dusk?65:140,80);light.intensity=dusk?1.7:2.2;
      scene.background=new THREE.Color(state.snapshot.defaults.background==='sky'?(dusk?0xcdd4c6:0xb8d1da):0xd8e0d4);
      const effective=state.previewModel?null:state.environmentPreview?state.environmentPreview.value:state.snapshot.environment??null;
      environment.preview(!!state.environmentPreview);
      const water=environment.configure(effective,state.snapshot.coordinateFrame,terrain,[...entries.values()].map(e=>e.root),state.selectedId?entries.get(state.selectedId)?.root??null:null,state.terrainVisible&&!preview);
      if(terrain)terrain.visible=state.terrainVisible&&!preview&&!water;
      imageryLayer.shading(effective?.surface.imageryShading??'source-color',!!effective);
      imageryLayer.visible(state.terrainVisible&&!!state.imageryVisible&&!preview&&!water);
      const status=environment.status();setEnvironmentStatus(previous=>previous.water===status.water&&previous.clouds===status.clouds&&previous.surroundings===status.surroundings&&previous.casters===status.casters&&previous.fallback===status.fallback?previous:status);
      const groundMap=state.snapshot.defaults.terrainMaterial==='grass'?grass:null;if(terrainMaterial.map!==groundMap){terrainMaterial.map=groundMap;terrainMaterial.needsUpdate=true;}
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
    const preload=()=>{
      const version=current.current.placementModel;if(!version)return;
      void cache.model(version).catch(value=>{
        if(current.current.placementModel?.modelVersionId===version.modelVersionId)report(value);
      });
    };
    const sync=async()=>{
      const ticket=++generation;loadingAbort?.abort();loadingAbort=new AbortController();const signal=loadingAbort.signal;
      const state=current.current;cancelDrag();resourcesLoading=true;setError(null);awaitingDisplay=null;
      const plan=sceneLoadingPlan(state.snapshot,state.modelRefs,state.previewModel);
      if(!loading||loading.identity!==sceneLoadingIdentity(plan,state.preparationKey)||loading.state().stage==='failed'){
        loading?.cancel();loading=new SceneLoadingTracker(plan,value=>{if(!stale())setLoadingState(value);},state.preparationKey);
      }
      const progress=loading,valid=()=>!stale()&&ticket===generation;setReading(progress.state().stage!=='complete');
      highlight();
      const imageryPreparation=imageryLayer.prepare(state.imageryVersion??null,state.snapshot.imagery,signal);
      // Observe immediately: a model may load more slowly than a failed image read.
      void imageryPreparation.catch(()=>undefined);
      if(state.snapshot.coordinateFrame.frameRevision!==lastFrameRevision){
        lastFrameRevision=state.snapshot.coordinateFrame.frameRevision;
        if(restoreView)restoreView=structuredClone(state.snapshot.initialView);else moveView(state.snapshot.initialView);
      }
      const wanted=new Set(state.snapshot.instances.map(item=>item.sceneModelInstanceId));
      for(const [id,entry] of entries)if(!wanted.has(id)){entry.appearance.dispose();models.remove(entry.root);entries.delete(id);}
      const modelTasks=state.snapshot.instances.map(async item=>{
        const ref=state.modelRefs.find(value=>value.modelVersionId===item.modelVersionId);
        if(!ref){
          const prior=entries.get(item.sceneModelInstanceId);if(prior){prior.appearance.dispose();models.remove(prior.root);entries.delete(item.sceneModelInstanceId);}
          throw new ApiError(409,'RESOURCE_CHANGED');
        }
        const key=JSON.stringify([ref.modelVersionId,ref.contentRevision,ref.sha256]);
        let entry=entries.get(item.sceneModelInstanceId);
        if(entry?.key!==key){
          if(entry){entry.appearance.dispose();models.remove(entry.root);entries.delete(item.sceneModelInstanceId);}
          const resource=await cache.model(ref,signal);if(stale()||ticket!==generation)return;
          const root=cloneModel(resource,item.sceneModelInstanceId);
          entry={root,key,appearance:new SceneCabinetAppearance(root,resource.version)};entries.set(item.sceneModelInstanceId,entry);models.add(entry.root);
        }
        try {transform(item,entry.root);}
        catch(value){entry.appearance.dispose();models.remove(entry.root);entries.delete(item.sceneModelInstanceId);throw value;}
      });
      const tasks=[...new Set(state.snapshot.instances.map(item=>item.modelVersionId))].map(async id=>{
        await Promise.all(modelTasks.filter((_,index)=>state.snapshot.instances[index].modelVersionId===id));
        const ref=state.modelRefs.find(value=>value.modelVersionId===id);if(valid()&&ref)progress.done(modelLoadingKey(ref));
      });
      const terrainTask=(async()=>{
        const version=state.terrainVersion,reference=state.snapshot.terrain;
        const clearTerrain=()=>{if(terrain){scene.remove(terrain);terrain=null;}terrainKey='';};
        if(!reference){clearTerrain();return;}
        if(!version){clearTerrain();return;}
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
        if(valid())progress.done(terrainLoadingKey(reference));
      })();
      tasks.push(terrainTask);
      tasks.push((async()=>{
        await Promise.all([terrainTask,imageryPreparation]);if(stale()||ticket!==generation)return;
        await imageryLayer.sync(terrain,state.terrainVersion,state.imageryVersion??null,state.snapshot.imagery,signal);
        if(stale()||ticket!==generation)return;
        setImageryPartial(imageryLayer.partial());appearance();
        if(state.snapshot.imagery&&state.imageryVersion&&(!state.snapshot.terrain||state.terrainVersion))progress.done(imageryLoadingKey(state.snapshot.imagery));
      })());
      tasks.push((async()=>{
        const version=state.previewModel;
        if(!version){
          previewInspection?.dispose();previewInspection=null;lastPreviewFocus='';state.onPreviewStructure?.(null);
          if(preview){scene.remove(preview);preview=null;}
          previewKey='';if(restoreView)moveView(restoreView);restoreView=null;
          appearance();
          return;
        }
        const key=JSON.stringify([version.modelVersionId,version.contentRevision,version.sha256]);
        if(key===previewKey){progress.done(modelLoadingKey(version));return;}
        if(!restoreView)restoreView=view(camera,orbit);
        previewInspection?.dispose();previewInspection=null;lastPreviewFocus='';state.onPreviewStructure?.(null);
        if(preview){scene.remove(preview);preview=null;}previewKey='';
        const resource=await cache.model(version,signal);if(stale()||ticket!==generation)return;
        preview=cloneModel(resource,'resource-preview',{calibrated:false});scene.add(preview);previewKey=key;
        previewInspection=new ModelPreviewInspection(preview,resource.version);
        current.current.onPreviewStructure?.(previewInspection.structure);appearance();fit();progress.done(modelLoadingKey(version));
      })());
      const results=await Promise.allSettled(tasks);if(stale()||ticket!==generation)return;
      const failed=results.find(value=>value.status==='rejected');
      if(failed?.status==='rejected'){progress.fail();setReading(false);report(failed.reason);return;}
      const waitingMetadata=!!state.snapshot.terrain&&!state.terrainVersion||!!state.snapshot.imagery&&!state.imageryVersion;
      resourcesLoading=waitingMetadata||progress.state().stage==='display';
      if(!waitingMetadata&&progress.state().stage==='display')awaitingDisplay=progress;
      appearance();
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
    const zoomAt=(x:number,y:number,factor:number)=>{
      prepareRay(x,y);
      const targets:THREE.Object3D[]=preview?[preview]:[...entries.values()].filter(entry=>entry.root.visible).map(entry=>entry.root);
      if(terrain?.visible&&!preview)targets.push(terrain);
      const hit=visibleZoomHit(ray.intersectObjects(targets,true));
      const target=cursorZoomView(view(camera,orbit),ray.ray.direction.toArray() as Vector3,factor,hit?.distance);
      camera.position.fromArray(target.eye);orbit.target.fromArray(target.target);orbit.update();emit();
    };
    const wheel=(event:WheelEvent)=>{
      if(current.current.disabled||!orbit.enabled||!orbit.enableZoom||resourcesLoading)return;
      event.preventDefault();event.stopImmediatePropagation();
      current.current.onCameraInteraction?.();tween=null;componentTween=false;componentPending=null;
      const delta=-event.deltaY*(event.deltaMode===1?16:event.deltaMode===2?element.clientHeight:1)*(event.ctrlKey?10:1);
      wheelPending={x:event.clientX,y:event.clientY,delta:Math.max(-1200,Math.min(1200,(wheelPending?.delta??0)+delta))};request();
    };
    const hitModel=(x:number,y:number)=>{
      prepareRay(x,y);
      const active=current.current.componentPickingInstanceId;
      const entry=active?entries.get(active):undefined,target=active?entry?.root:models;if(!target)return null;
      return sceneModelRayHit(ray.intersectObject(target,true),models,active&&entry?
        {instanceId:active,isFadedOccluder:(object,index)=>entry.appearance.isFadedOccluder(object,index)}:undefined);
    };
    const hitId=(x:number,y:number)=>hitModel(x,y)?.sceneModelInstanceId??null;
    const down=(event:PointerEvent)=>{
      if(event.button!==0)return;current.current.onCameraInteraction?.();tween=null;componentTween=false;componentPending=null;
      pointer={x:event.clientX,y:event.clientY,id:event.pointerId};
      const state=current.current;if(state.disabled||state.previewModel||!state.editing||state.pendingPlacement||movePending||state.componentPickingInstanceId)return;
      const id=hitId(event.clientX,event.clientY),item=state.snapshot.instances.find(value=>value.sceneModelInstanceId===id);
      const entry=id?entries.get(id):null,point=groundPoint(event.clientX,event.clientY);
      if(!id||!item||!entry||item.positionLocked||!point||event.shiftKey)return;
      if((state.selectedIds?.length??0)>1||state.snapshot.organization?.groups.some(group=>group.instanceIds.includes(id)))return;
      tween=null;current.current.onSelect(id);drag={id,root:entry.root,original:entry.root.position.clone(),
        offset:entry.root.position.clone().sub(point),pointerId:event.pointerId};
      orbit.enabled=false;renderer.domElement.setPointerCapture(event.pointerId);
    };
    const motion=(event:PointerEvent)=>{
      if(!drag||event.pointerId!==drag.pointerId)return;
      const point=groundPoint(event.clientX,event.clientY);if(!point)return;
      drag.root.position.fromArray(snapPoint([point.x+drag.offset.x,drag.original.y,point.z+drag.offset.z],current.current.gridSnap??0));drag.root.updateMatrixWorld(true);highlight();
    };
    const up=(event:PointerEvent)=>{
      const clicked=pointer&&pointer.id===event.pointerId&&Math.hypot(pointer.x-event.clientX,pointer.y-event.clientY)<=4;
      pointer=null;
      if(drag&&drag.pointerId===event.pointerId){
        const movement=drag;drag=null;orbit.enabled=!current.current.disabled;
        if(renderer.domElement.hasPointerCapture(event.pointerId))renderer.domElement.releasePointerCapture(event.pointerId);
        const releasePoint=groundPoint(event.clientX,event.clientY);
        if(!releasePoint){movement.root.position.copy(movement.original);report(new ApiError(422,'NO_DATA'));highlight();return;}
        movement.root.position.fromArray(snapPoint([releasePoint.x+movement.offset.x,movement.original.y,releasePoint.z+movement.offset.z],current.current.gridSnap??0));
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
      const state=current.current;if(!clicked||state.disabled)return;
      if(state.previewModel){if(!preview||!previewInspection||stale())return;prepareRay(event.clientX,event.clientY);
        const identity=previewIdentity(state.previewModel);
        state.onPreviewPick?.(identity,previewInspection.pick(ray.intersectObject(preview,true),identity));return;}
      if(state.componentPickingInstanceId){
        const hit=hitModel(event.clientX,event.clientY);
        if(hit?.sceneModelInstanceId===state.componentPickingInstanceId&&hit.component)state.onComponentPick?.(hit.component);
        return;
      }
      if(state.editing&&state.pendingPlacement){const point=groundPoint(event.clientX,event.clientY);if(point)state.onPoint(point.toArray() as Vector3);else report(new ApiError(422,'OUTSIDE_COVERAGE'));}
      else state.onSelect(hitId(event.clientX,event.clientY),event.shiftKey);
    };
    const escape=(event:KeyboardEvent)=>{if(event.key.startsWith('Arrow'))current.current.onCameraInteraction?.();if(event.key==='Escape'&&drag){event.preventDefault();cancelDrag();}};
    const drop=(event:DragEvent)=>{
      const state=current.current;if(!state.editing||state.disabled||state.previewModel||!state.onResourceDrop)return;
      const raw=event.dataTransfer?.getData(DROP_MIME);if(!raw)return;event.preventDefault();
      try {
        if(raw.length>512)throw new Error('invalid');const value:unknown=JSON.parse(raw);
        if(!value||typeof value!=='object'||Object.keys(value).sort().join(',')!=='modelAssetId,modelVersionId')throw new Error('invalid');
        const reference=value as {modelAssetId:string;modelVersionId:string};
        if(!uuid.test(reference.modelAssetId)||!uuid.test(reference.modelVersionId))throw new Error('invalid');
        const point=groundPoint(event.clientX,event.clientY);if(point)state.onResourceDrop(reference,point.toArray() as Vector3);else report(new ApiError(422,'OUTSIDE_COVERAGE'));
      } catch {report(new ViewportInteractionError('dropInvalid'));}
    };
    const dragover=(event:DragEvent)=>{const state=current.current;if(state.editing&&!state.disabled&&!state.previewModel&&state.onResourceDrop
      &&event.dataTransfer?.types.includes(DROP_MIME)){event.preventDefault();event.dataTransfer.dropEffect='copy';}};
    const visible=()=>{
      if(document.hidden){environment.suspend();hiddenAt=performance.now();cancelAnimationFrame(frame);frame=0;}
      else {if(tween&&hiddenAt!==null)tween.start+=performance.now()-hiddenAt;hiddenAt=null;appearance();request();}
    };
    const resize=new ResizeObserver(()=>{
      // Layout dimensions exclude the enclosing analysis canvas's CSS zoom.
      const width=Math.max(1,element.clientWidth),height=Math.max(1,element.clientHeight);
      camera.aspect=width/height;camera.updateProjectionMatrix();renderer.setSize(width,height);request();});resize.observe(element);
    const orbitStart=()=>{current.current.onCameraInteraction?.();tween=null;componentTween=false;componentPending=null;};orbit.addEventListener('change',request);orbit.addEventListener('start',orbitStart);orbit.addEventListener('end',emit);
    const canvas=renderer.domElement;
    canvas.addEventListener('wheel',wheel,{capture:true,passive:false});
    canvas.addEventListener('pointerdown',down,true);canvas.addEventListener('pointermove',motion);canvas.addEventListener('pointerup',up);
    canvas.addEventListener('pointercancel',cancelDrag);canvas.addEventListener('keydown',escape);canvas.addEventListener('drop',drop);canvas.addEventListener('dragover',dragover);
    document.addEventListener('visibilitychange',visible);
    runtime.current={sync:()=>void sync(),preload,appearance,componentFocus:highlight,previewSelection:highlight,
      fit:()=>{clearComponentFocus();if(previewInspection){previewInspection.restore();current.current.onPreviewPick?.(previewInspection.structure.identity,null);fit();request();return;}
        if(resourcesLoading)focusPending=null;else fit();highlight();},
      focus:id=>{clearComponentFocus();if(previewInspection){previewInspection.restore();current.current.onPreviewPick?.(previewInspection.structure.identity,null);fit();request();return;}
        if(resourcesLoading||(Array.isArray(id)?id.some(member=>!entries.has(member)):id&&!entries.has(id)))focusPending=id;else fit(id);highlight();},
      setView:target=>{if(restoreView)restoreView=structuredClone(target);else moveView(target);},
      zoom:factor=>{tween=null;componentTween=false;componentPending=null;const rect=canvas.getBoundingClientRect();zoomAt(rect.left+rect.width/2,rect.top+rect.height/2,factor);request();}};
    const cameraControl:SceneCameraControl={getView:()=>view(camera,orbit),ready:()=>!disposed&&!stale()&&!resourcesLoading&&!preview&&!latestError.current,
      setView:target=>{if(disposed||stale())return;if(componentTarget||componentFocused)clearComponentFocus();moveView(target,false);}};
    if(current.current.cameraControl)current.current.cameraControl.current=cameraControl;
    moveView(current.current.snapshot.initialView,false);void sync();
    return ()=>{
      if(current.current.cameraControl?.current===cameraControl)current.current.cameraControl.current=null;
      disposed=true;++generation;loading?.cancel();loadingAbort?.abort();cancelAnimationFrame(frame);resize.disconnect();document.removeEventListener('visibilitychange',visible);
      wheelPending=null;canvas.removeEventListener('wheel',wheel,true);
      canvas.removeEventListener('pointerdown',down,true);canvas.removeEventListener('pointermove',motion);canvas.removeEventListener('pointerup',up);
      canvas.removeEventListener('pointercancel',cancelDrag);canvas.removeEventListener('keydown',escape);canvas.removeEventListener('drop',drop);canvas.removeEventListener('dragover',dragover);
      orbit.removeEventListener('change',request);orbit.removeEventListener('start',orbitStart);orbit.removeEventListener('end',emit);
      sceneControls.dispose();environment.dispose();imageryLayer.dispose();previewInspection?.dispose();previewInspection=null;
      current.current.onPreviewStructure?.(null);
      for(const entry of entries.values())entry.appearance.dispose();entries.clear();cache.dispose();selectedBox.geometry.dispose();disposeMaterial(selectedBox.material);
      componentBox.geometry.dispose();disposeMaterial(componentBox.material);
      grid.geometry.dispose();disposeMaterial(grid.material);terrainMaterial.dispose();grass.dispose();scene.clear();
      renderer.dispose();renderer.forceContextLoss();canvas.remove();runtime.current=null;
    };
  },[props.api,props.api.epoch,props.api.revision,rendererAttempt]);
  useEffect(()=>{runtime.current?.preload();},[props.placementModel]);
  useEffect(()=>{runtime.current?.sync();},[props.snapshot,props.modelRefs,props.terrainVersion,props.imageryVersion,props.previewModel,props.preparationKey,attempt]);
  useEffect(()=>{runtime.current?.appearance();},[props.selectedId,props.selectedIds,props.personalVisibility,props.terrainVisible,props.imageryVisible,props.disabled,props.editing,props.pendingPlacement,props.environmentPreview,waterOverride,cloudOverride,reduced,locale,resolved]);
  useEffect(()=>{if(props.viewCommand)runtime.current?.setView(props.viewCommand.view);},[props.viewCommand?.token]);
  useEffect(()=>{if(props.focusRequest)runtime.current?.focus(props.focusRequest.instanceIds??props.focusRequest.instanceId);},[props.focusRequest?.token]);
  useEffect(()=>{runtime.current?.componentFocus();},[props.componentFocus,props.snapshot,props.modelRefs,props.selectedId,props.personalVisibility,props.previewModel]);
  useEffect(()=>{runtime.current?.previewSelection();},[props.previewSelection]);
  return <section className="ov-scene-viewport" aria-label={message('view')}>
    <div className="ov-scene-viewport-stage"><div ref={mount} className="ov-scene-viewport-canvas"/>
      {(reading||!!displayError) && <div className="ov-scene-viewport-state" role={displayError?'alert':undefined}>{displayError?<>{displayError instanceof ApiError&&/IMAGERY/.test(displayError.code)?imageryFailure(displayError,locale):errorMessage}
        <button className="ov-btn" onClick={()=>props.preparationError?props.onRetryPreparation?.():webglFailure.current?setRendererAttempt(value=>value+1):setAttempt(value=>value+1)}>{message('retry')}</button></>:<SceneLoadingProgress locale={locale} state={loadingState}/>}</div>}
      <div className="ov-scene-viewport-tools"><IconBtn label={message('zoomIn')} onClick={()=>{props.onCameraInteraction?.();runtime.current?.zoom(.8);}}><ZoomIn size={16}/></IconBtn>
        <IconBtn label={message('zoomOut')} onClick={()=>{props.onCameraInteraction?.();runtime.current?.zoom(1.25);}}><ZoomOut size={16}/></IconBtn>
        <IconBtn label={message('fit')} onClick={()=>{props.onCameraInteraction?.();runtime.current?.fit();}}><Maximize size={16}/></IconBtn>
        <IconBtn label={message('focus')} disabled={!props.selectedId||!!props.previewModel} onClick={()=>{props.onCameraInteraction?.();runtime.current?.focus((props.selectedIds?.length??0)>1?props.selectedIds!:props.selectedId);}}><Focus size={16}/></IconBtn></div>
      {props.imageryVersion&&props.snapshot.imagery&&props.imageryVisible&&props.terrainVisible&&!props.previewModel&&!environmentStatus.water&&<div className="ov-scene-imagery-attribution">
        <span>{props.imageryVersion.displayName} · {props.imageryVersion.metadata.acquiredAt} · {props.imageryVersion.report.pixelSize.map(v=>Number(v.toPrecision(3))).join(' × ')} {props.imageryVersion.report.horizontalCrs==='EPSG:4326'?'°':'m'} · {imageryText(locale,'precision')}</span>
        <span>{props.imageryVersion.metadata.attribution}</span>{imageryPartial&&<span>{imageryText(locale,'partial')}</span>}
      </div>}
      {(environmentStatus.water||environmentStatus.clouds||environmentStatus.fallback||environmentStatus.surroundings)&&<div className="ev-status">{environmentStatus.surroundings&&<span>{locale==='en'?'Surrounding background is illustrative; placement and measurement use original terrain only':'外围背景为示意；放置、贴地和测量仅使用原地形'}</span>}<span>{environmentStatus.water?(locale==='en'?'Visual water; placement uses the positioning surface':'视觉水面 按原定位基准面放置'):environmentStatus.fallback?(locale==='en'?'Static environment fallback':'静态环境回退'):null}</span>{environmentStatus.water&&!environmentStatus.fallback&&<button className="ov-btn" type="button" onClick={()=>setWaterOverride(previous=>!(previous??(!reduced&&(props.environmentPreview?props.environmentPreview.value:props.snapshot.environment)?.animation.defaultPlayback==='playing')))}>{(waterOverride??(!reduced&&(props.environmentPreview?props.environmentPreview.value:props.snapshot.environment)?.animation.defaultPlayback==='playing'))?(locale==='en'?'Pause ripples':'暂停水纹'):(locale==='en'?'Play ripples':'播放水纹')}</button>}{environmentStatus.clouds&&!environmentStatus.fallback&&<button className="ov-btn" type="button" onClick={()=>setCloudOverride(previous=>!(previous??(!reduced&&(props.environmentPreview?props.environmentPreview.value:props.snapshot.environment)?.atmosphere.clouds?.defaultPlayback==='playing')))}>{(cloudOverride??(!reduced&&(props.environmentPreview?props.environmentPreview.value:props.snapshot.environment)?.atmosphere.clouds?.defaultPlayback==='playing'))?(locale==='en'?'Pause clouds':'暂停流云'):(locale==='en'?'Play clouds':'播放流云')}</button>}{environmentStatus.fallback&&<span>{locale==='en'?'Environment allocation unavailable; shadows and animation are off':'环境资源不可用，已关闭阴影和动画'}</span>}{reduced&&<span>{locale==='en'?'Reduced motion':'减少动画'}</span>}</div>}
    </div><footer className="ov-scene-viewport-foot"><span>{props.previewModel?`${message('preview')} · ${props.previewModel.displayName}`:
      moving?message('moving'):props.editing?props.pendingPlacement?message('place'):message('drag'):message('browse')}</span>
      {props.previewModel?.calibration.state==='unverified'?<span>{message('unverified')}</span>:null}</footer>
  </section>;
}
