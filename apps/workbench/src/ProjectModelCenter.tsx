import {lazy, Suspense, useMemo, useRef, useState} from 'react';
import {ArrowLeft, Layers} from 'lucide-react';
import type {WorkbenchApi} from './api';
import {failureMessage} from './api';
import {Btn} from './Primitives';
import {usePreferences} from './Preferences';
import {ResourcePanel} from './ResourcePanel';
import {ModelComponentTree,ModelComponentProperties,ModelPreviewTools,useModelPreview} from './ModelPreviewInspector';
import type {ProjectModelVersion} from './resourceTypes';
import type {LocalSceneSnapshot,ModelResourceRef,SceneView} from './sceneTypes';
import type {ProjectRef} from './projectTypes';
import './projectModelCenter.css';

const SceneViewport=lazy(()=>import('./SceneViewport').then(module=>({default:module.SceneViewport})));
const previewScene:LocalSceneSnapshot={displayName:'',coordinateFrame:{mode:'local_plane',frameRevision:'resource-preview',
  origin:[0,0,0],unit:'m',axes:'X_EAST_Y_UP_Z_SOUTH'},terrain:null,instances:[],
  initialView:{eye:[300,200,300],target:[0,60,0]},defaults:{background:'plain',lighting:'neutral',terrainMaterial:'solid'}};
const ignore=()=>{};
const emptyRefs:ModelResourceRef[]=[],emptyVisibility:Record<string,boolean>={};

export function ProjectModelCenter({api,onOpenScene,onConfigure,suspended=false}:{api:WorkbenchApi;onOpenScene:(sceneId?:string,projectRef?:ProjectRef)=>void;onConfigure?:()=>void;suspended?:boolean}) {
  const {locale}=usePreferences(),text=(zh:string,en:string)=>locale==='zh'?zh:en;
  const [preview,setPreview]=useState<ProjectModelVersion|null>(null),[error,setError]=useState<unknown>(null);
  const lastView=useRef<SceneView|null>(null);
  const restoredView=useMemo(()=>lastView.current,[preview?.modelVersionId,api.epoch,api.revision]);
  const snapshot=useMemo(()=>({...previewScene,initialView:restoredView||previewScene.initialView}),[restoredView]);
  const inspection=useModelPreview(preview);
  const [detailsTarget,setDetailsTarget]=useState<HTMLDivElement|null>(null);
  function show(value:ProjectModelVersion|null){if(value?.modelVersionId!==preview?.modelVersionId)lastView.current=null;setPreview(value);setError(null);}
  return <section className={`pm-center${preview?' pm-previewing':''}`} aria-label={text('共享模型资源','Shared model resources')}>
    <header className="pm-heading"><div className="pm-heading-title">{preview&&<Btn onClick={()=>show(null)}><ArrowLeft size={15}/>{text('返回模型中心','Back to model center')}</Btn>}<div><strong>{preview?.displayName||text('共享模型资源','Shared model resources')}</strong>
      <p>{text('模型可供多个项目使用；同一固定版本在各场景中放置为独立实例。','Models are shared across projects. Place independent instances of the same fixed version in each scene.')}</p></div>
      </div>
      <Btn onClick={()=>onOpenScene()}><Layers size={15}/>{text('进入场景布置','Open scene placement')}</Btn></header>
    <div className="pm-catalog pm-library" hidden={!!preview}><ResourcePanel api={api} modelsOnly detailsTarget={detailsTarget} canPlace={false} canAcquire={false}
      onPlace={ignore} onPreview={show} onTerrainReady={ignore} onOpenScene={onOpenScene}/></div>
    {preview&&<div className="pm-grid"><div className="pm-tree"><ModelComponentTree version={preview} inspection={inspection} onClose={()=>show(null)}/></div>
      <div className="pm-preview">
        <ModelPreviewTools inspection={inspection}/>{onConfigure&&<Btn onClick={onConfigure}>{text('在设备层级配置','Configure in equipment hierarchy')}</Btn>}
        <div className="pm-canvas"><Suspense fallback={<p role="status">{text('正在读取模型…','Loading model…')}</p>}>
          <SceneViewport key={preview.modelVersionId} api={api} active={!suspended} snapshot={snapshot} modelRefs={emptyRefs} terrainVersion={null}
            selectedId={null} editing={false} personalVisibility={emptyVisibility} terrainVisible={false} pendingPlacement={false}
            previewModel={preview} initialPreviewView={restoredView} previewSelection={inspection.selection} onPreviewStructure={inspection.ready} onPreviewPick={inspection.pick}
            onSelect={ignore} onPoint={ignore} onMove={async()=>false} onViewChange={value=>{lastView.current=value;}} onError={setError}/>
        </Suspense></div>{!!error&&<p role="alert">{failureMessage(error,locale)}</p>}
        <p className="pm-note">{text('资源预览；现场设备身份、安装位置和工程精度需另行核实。','Resource preview; installed identity, placement and engineering accuracy require separate verification.')}</p>
      </div>
      <aside className="pm-inspector" aria-label={text(inspection.node?'构件属性':'模型属性',inspection.node?'Component properties':'Model properties')}>
        {preview&&inspection.node&&<ModelComponentProperties version={preview} inspection={inspection}/>}
        <div className="mp-resource-details" hidden={!!inspection.node}><header><strong>{text('模型属性','Model properties')}</strong></header>
        {preview&&<p className="mp-caption">{text('选择构件查看其属性。','Select a component to inspect its properties.')}</p>}
        <div className="pm-resource-details" ref={setDetailsTarget}/><p className="pm-properties-empty">{text('选择模型资源查看属性','Select a model resource to view its properties')}</p></div>
      </aside>
    </div>}
  </section>;
}
