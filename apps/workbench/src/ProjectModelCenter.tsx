import {lazy, Suspense, useState} from 'react';
import {Box, Layers} from 'lucide-react';
import type {WorkbenchApi} from './api';
import {failureMessage} from './api';
import {Btn} from './Primitives';
import {usePreferences} from './Preferences';
import {ResourcePanel} from './ResourcePanel';
import {ModelComponentTree,ModelComponentProperties,ModelPreviewTools,useModelPreview} from './ModelPreviewInspector';
import type {ProjectModelVersion} from './resourceTypes';
import type {LocalSceneSnapshot,ModelResourceRef} from './sceneTypes';
import './projectModelCenter.css';

const SceneViewport=lazy(()=>import('./SceneViewport').then(module=>({default:module.SceneViewport})));
const previewScene:LocalSceneSnapshot={displayName:'',coordinateFrame:{mode:'local_plane',frameRevision:'resource-preview',
  origin:[0,0,0],unit:'m',axes:'X_EAST_Y_UP_Z_SOUTH'},terrain:null,instances:[],
  initialView:{eye:[300,200,300],target:[0,60,0]},defaults:{background:'plain',lighting:'neutral',terrainMaterial:'solid'}};
const ignore=()=>{};
const emptyRefs:ModelResourceRef[]=[],emptyVisibility:Record<string,boolean>={};

export function ProjectModelCenter({api,onOpenScene}:{api:WorkbenchApi;onOpenScene:(sceneId?:string)=>void}) {
  const {locale}=usePreferences(),text=(zh:string,en:string)=>locale==='zh'?zh:en;
  const [preview,setPreview]=useState<ProjectModelVersion|null>(null),[error,setError]=useState<unknown>(null);
  const inspection=useModelPreview(preview);
  const [detailsTarget,setDetailsTarget]=useState<HTMLDivElement|null>(null);
  function show(value:ProjectModelVersion|null){setPreview(value);setError(null);}
  return <section className="pm-center" aria-label={text('项目模型资源','Project model resources')}>
    <header className="pm-heading"><div><strong>{text('项目模型资源','Project model resources')}</strong>
      <p>{text('与场景共用资源库。一个固定模型版本可放置多个独立实例。','Shared with Scenes. One fixed model version can be placed as many independent instances.')}</p></div>
      <Btn onClick={()=>onOpenScene()}><Layers size={15}/>{text('进入场景布置','Open scene placement')}</Btn></header>
    <div className="pm-grid"><div className="pm-catalog mp-catalog" hidden={!!preview}><ResourcePanel api={api} modelsOnly detailsTarget={detailsTarget} canPlace={false} canAcquire={false}
      onPlace={ignore} onPreview={show} onTerrainReady={ignore} onOpenScene={onOpenScene}/></div>
      {preview&&<div className="pm-tree"><ModelComponentTree version={preview} inspection={inspection} onClose={()=>show(null)}/></div>}
      <div className="pm-preview">{preview?<><header><strong>{preview.displayName}</strong><Btn onClick={()=>show(null)}>{text('关闭预览','Close preview')}</Btn></header>
        <ModelPreviewTools inspection={inspection}/>
        <div className="pm-canvas"><Suspense fallback={<p role="status">{text('正在读取模型…','Loading model…')}</p>}>
          <SceneViewport key={preview.modelVersionId} api={api} snapshot={previewScene} modelRefs={emptyRefs} terrainVersion={null}
            selectedId={null} editing={false} personalVisibility={emptyVisibility} terrainVisible={false} pendingPlacement={false}
            previewModel={preview} previewSelection={inspection.selection} onPreviewStructure={inspection.ready} onPreviewPick={inspection.pick}
            onSelect={ignore} onPoint={ignore} onMove={async()=>false} onViewChange={ignore} onError={setError}/>
        </Suspense></div>{!!error&&<p role="alert">{failureMessage(error,locale)}</p>}
        <p className="pm-note">{text('资源预览；现场设备身份、安装位置和工程精度需另行核实。','Resource preview; installed identity, placement and engineering accuracy require separate verification.')}</p>
      </>:<div className="pm-empty"><Box size={32}/><strong>{text('点击模型资源直接预览','Select a model resource to preview')}</strong>
        <p>{text('模型资源保存可复用的几何与来源；实例保存本次安装的位置、名称和设备关联。','Resources hold reusable geometry and provenance. Instances hold placement, name and equipment links.')}</p>
        <p>{text('固定版本只在上传或校准时增加。场景保存和型号属性分别记录修订。','Fixed versions increase only on upload or calibration. Scene saves and model metadata have separate revisions.')}</p></div>}</div>
      <aside className="pm-inspector" aria-label={text(inspection.node?'构件属性':'模型属性',inspection.node?'Component properties':'Model properties')}>
        {preview&&inspection.node&&<ModelComponentProperties version={preview} inspection={inspection}/>}
        <div className="mp-resource-details" hidden={!!inspection.node}><header><strong>{text('模型属性','Model properties')}</strong></header>
        {preview&&<p className="mp-caption">{text('选择构件查看其属性。','Select a component to inspect its properties.')}</p>}
        <div className="pm-resource-details" ref={setDetailsTarget}/><p className="pm-properties-empty">{text('选择模型资源查看属性','Select a model resource to view its properties')}</p></div>
      </aside>
    </div>
  </section>;
}
