import {lazy,Suspense,useEffect,useRef,useState} from 'react';
import {ModelPreviewTools,useModelPreview} from './ModelPreviewInspector';
import type {ProjectModelVersion} from './resourceTypes';
import type {LocalSceneSnapshot,ModelResourceRef} from './sceneTypes';
import type {WorkbenchApi} from './api';
import type {ModelView} from './analysisCanvas';
import type {SceneCameraControl} from './SceneViewport';
const SceneViewport=lazy(()=>import('./SceneViewport').then(module=>({default:module.SceneViewport})));
const scene:LocalSceneSnapshot={displayName:'',coordinateFrame:{mode:'local_plane',frameRevision:'analysis-preview',origin:[0,0,0],unit:'m',axes:'X_EAST_Y_UP_Z_SOUTH'},terrain:null,instances:[],initialView:{eye:[300,200,300],target:[0,60,0]},defaults:{background:'plain',lighting:'neutral',terrainMaterial:'solid'}};
const refs:ModelResourceRef[]=[],visibility:Record<string,boolean>={},ignore=()=>{},noMove=async()=>false;
export function AnalysisModelCard({api,version,en,initialView,onView}:{api:WorkbenchApi;version:ProjectModelVersion;en:boolean;initialView?:ModelView;onView?:(value:ModelView)=>void}){
  const inspection=useModelPreview(version),[error,setError]=useState<unknown>(null);
  const camera=useRef<SceneCameraControl|null>(null),initial=useRef(initialView),interacted=useRef(false),timer=useRef<ReturnType<typeof setTimeout>|undefined>(undefined),lastView=useRef<ModelView|null>(null);
  const change=useRef(onView),selected=useRef(inspection.selection.nodeId);change.current=onView;selected.current=inspection.selection.nodeId;
  function flushView(){clearTimeout(timer.current);const value=lastView.current;lastView.current=null;if(value)change.current?.(value);}
  useEffect(()=>()=>flushView(),[]);
  useEffect(()=>{if(!inspection.structure||!initial.current)return;const view=initial.current;initial.current=undefined;
    if(view.componentId)inspection.choose(view.componentId);
    const id=requestAnimationFrame(()=>camera.current?.setView({eye:view.eye,target:view.target}));return()=>cancelAnimationFrame(id);
  },[inspection.structure]);
  function saveView(view:ModelView){if(!interacted.current)return;clearTimeout(timer.current);lastView.current={...view,...(selected.current?{componentId:selected.current}:{})};timer.current=setTimeout(flushView,200);}
  return <div className="ac-model" data-canvas-inner>
    <select aria-label={en?'Model component':'模型构件'} value={inspection.selection.nodeId||''} onChange={event=>{interacted.current=true;inspection.choose(event.target.value||null);}}>
      <option value="">{en?'Whole model':'全部模型'}</option>{inspection.structure?.nodes.map(node=><option key={node.id} value={node.id}>{node.name}{node.kind==='proxy'?' · 示意':''}</option>)}
    </select><ModelPreviewTools inspection={inspection}/>
    <div className="ac-model-view"><Suspense fallback={<p role="status">{en?'Loading model…':'正在加载模型…'}</p>}>
      <SceneViewport api={api} snapshot={scene} modelRefs={refs} terrainVersion={null} selectedId={null} editing={false} personalVisibility={visibility}
        terrainVisible={false} pendingPlacement={false} previewModel={version} previewSelection={inspection.selection}
        cameraControl={camera} onCameraInteraction={()=>{interacted.current=true;}}
        onPreviewStructure={inspection.ready} onPreviewPick={(identity,id)=>{interacted.current=true;inspection.pick(identity,id);}} onSelect={ignore} onPoint={ignore} onMove={noMove} onViewChange={saveView} onError={setError}/>
    </Suspense></div>{!!error&&<p role="alert">{en?'Model unavailable. Retry opening this card.':'模型暂时不可用，请重新打开。'}</p>}
    <small>{en?'Source geometry / schematic proxies retain their original precision.':'源几何及示意代理保持原精度，不代表现场确认。'}</small>
  </div>;
}
