import {lazy,Suspense,useEffect,useMemo,useRef,useState,type CSSProperties} from 'react';
import {ArrowLeft,ArrowRight,Box,Cloud,Globe2,Layers,LayoutDashboard,Maximize2,Moon,Search,Settings2,Sun,TriangleAlert,X} from 'lucide-react';
import logo from '../../../assets/brand/ONTOVis.png';
import {ApiError,cancelled,failureMessage,type WorkbenchApi} from './api';
import {usePreferences} from './Preferences';
import {Btn,IconBtn,Modal} from './Primitives';
import type {ProjectSummary} from './projectTypes';
import type {SceneView,SceneOpen} from './sceneTypes';
import type {TerrainVersion,ImageryVersion} from './resourceTypes';
import type {SceneCameraControl} from './SceneViewport';
import type {AnalysisEntry} from './analysisSources';
import {SceneApi} from './sceneApi';
import {catalogIdentity,interfaceScale,readCockpitCatalog,sceneIdentity,type CockpitCatalog,type InterfaceScale} from './cockpitState';
import {CockpitDevice} from './CockpitDevice';
import './projectCockpit.css';
import './weather.css';
import {useCockpitWeather,WeatherEffects} from './CockpitWeather';
import {WeatherCard} from './WeatherCard';

const SceneViewport=lazy(()=>import('./SceneViewport').then(m=>({default:m.SceneViewport})));
const AnalysisWorkspace=lazy(()=>import('./AnalysisWorkspace').then(m=>({default:m.AnalysisWorkspace})));
const DataAlarms=lazy(()=>import('./DataAlarms').then(m=>({default:m.DataAlarms})));
const WorkOrders=lazy(()=>import('./WorkOrders').then(m=>({default:m.WorkOrders})));
type View='assets'|'scene'|'device'|'analysis'|'orders';
export type CockpitEntry={sceneId:string;sceneRevision:string;instanceId:string|null;camera?:SceneView};
export function ProjectCockpit({api,project,active,onExit,onWorkspace,initialEntry}:{api:WorkbenchApi;project:ProjectSummary;active:boolean;onExit:()=>void;onWorkspace:(sceneId?:string)=>void;initialEntry?:CockpitEntry|null}){
 const {locale,resolved,setTheme}=usePreferences(),en=locale==='en',t=(zh:string,eng:string)=>en?eng:zh;
 const root=useRef<HTMLDivElement>(null),camera=useRef<SceneCameraControl|null>(null);
 const [size,setSize]=useState({width:1920,height:1080}),[scale,setScale]=useState<InterfaceScale>('auto');
 const [catalog,setCatalog]=useState<CockpitCatalog|null>(null),[error,setError]=useState<unknown>(null),[attempt,setAttempt]=useState(0);
 const [view,setView]=useState<View>(initialEntry?'scene':'assets'),[sceneId,setSceneId]=useState(initialEntry?.sceneId||''),[instanceId,setInstanceId]=useState<string|null>(initialEntry?.instanceId||null),[uid,setUid]=useState(''),[query,setQuery]=useState('');
 const [pinnedEntry,setPinnedEntry]=useState(initialEntry),[pinnedScene,setPinnedScene]=useState<SceneOpen|null>(null),[pinnedError,setPinnedError]=useState<unknown>(null);
 const [terrain,setTerrain]=useState<TerrainVersion|null>(null),[imagery,setImagery]=useState<ImageryVersion|null>(null),[resourceError,setResourceError]=useState<unknown>(null),[resourceAttempt,setResourceAttempt]=useState(0);
 const [terrainVisible,setTerrainVisible]=useState(true),[imageryVisible,setImageryVisible]=useState(true),[personal,setPersonal]=useState<Record<string,boolean>>({}),[focus,setFocus]=useState<{token:number;instanceId:string|null}>();
 const [settings,setSettings]=useState(false),[alarms,setAlarms]=useState(false),[notice,setNotice]=useState('');
 const [analysisMounted,setAnalysisMounted]=useState(false),[analysisEntry,setAnalysisEntry]=useState<AnalysisEntry|null>(null),[analysisGeneration,setAnalysisGeneration]=useState(0),[analysisDirty,setAnalysisDirty]=useState(false),[orderDirty,setOrderDirty]=useState(false),[leave,setLeave]=useState<(()=>void)|null>(null);
 const [orderQuery,setOrderQuery]=useState(''),[orderMounted,setOrderMounted]=useState(false);
 const bookmarks=useRef(new Map<string,SceneView>(initialEntry?.camera?[[initialEntry.sceneId+':'+initialEntry.sceneRevision,initialEntry.camera]]:[])),returnView=useRef<View>('assets');
 const previousEntry=useRef<CockpitEntry|null|undefined>(initialEntry),entryPending=useRef(!!initialEntry);
 const client=useMemo(()=>new SceneApi(api),[api]);
 const row=catalog?.scenes.find(x=>x.summary.sceneId===sceneId);
 const historical=!!pinnedEntry&&pinnedEntry.sceneId===sceneId&&!!row&&pinnedEntry.sceneRevision!==row.summary.headRevision;
 const opened=historical?(pinnedScene?.sceneId===sceneId&&pinnedScene.sceneRevision===pinnedEntry?.sceneRevision?pinnedScene:null):row?.opened||null;
 const viewportSnapshot=useMemo(()=>opened?{...opened.snapshot,initialView:bookmarks.current.get(opened.sceneId+':'+opened.sceneRevision)||opened.snapshot.initialView}:null,[opened]);
 const selected=opened?.snapshot.instances.find(x=>x.sceneModelInstanceId===instanceId);
 const total=catalog?catalogIdentity(catalog,project.projectRef):null;
 const counts=opened&&catalog?sceneIdentity(opened,catalog.equipment,project.projectRef):null;
 const effectiveScale=interfaceScale(scale,size.width,size.height),automaticScale=interfaceScale('auto',size.width,size.height);
 const spatialKey=opened?opened.sceneId+':'+opened.sceneRevision:'';
 const weather=useCockpitWeather(api,opened?.sceneId||'',active&&(view==='scene'||view==='device'));
 const [weatherEffects,setWeatherEffects]=useState(true);
 useEffect(()=>{const element=root.current;if(!active||!element)return;const observer=new ResizeObserver(([entry])=>setSize({width:entry.contentRect.width,height:entry.contentRect.height}));observer.observe(element);return()=>observer.disconnect();},[active]);
 useEffect(()=>{if(!active)return;const abort=new AbortController();setCatalog(null);setError(null);
  void readCockpitCatalog(api,abort.signal).then(value=>{if(!abort.signal.aborted)setCatalog(value);}).catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setError(e);});return()=>abort.abort();
 },[api,api.epoch,api.revision,active,attempt]);
 useEffect(()=>{setPinnedScene(null);setPinnedError(null);if(!active||!historical||!pinnedEntry)return;const abort=new AbortController();
  void client.open(pinnedEntry.sceneId,pinnedEntry.sceneRevision,abort.signal).then(value=>{if(value.sceneId!==pinnedEntry.sceneId||value.sceneRevision!==pinnedEntry.sceneRevision||value.projectCode!==project.projectRef.projectCode)throw new ApiError(409,'SCENE_CHANGED');if(!abort.signal.aborted)setPinnedScene(value);}).catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setPinnedError(e);});return()=>abort.abort();
 },[active,client,historical,pinnedEntry,attempt]);
 useEffect(()=>{setTerrain(null);setImagery(null);setResourceError(null);if(!active||!opened)return;const abort=new AbortController();
  const scene=opened;
  void Promise.all([scene.snapshot.terrain?client.version(scene.snapshot.terrain.terrainVersionId,abort.signal).then(value=>{
   if(value.contentRevision!==scene.snapshot.terrain!.expectedContentRevision)throw new ApiError(409,'RESOURCE_CHANGED');return value;
  }):null,scene.snapshot.imagery?client.imageryVersion(scene.snapshot.imagery.imageryVersionId,abort.signal).then(value=>{
   if(value.contentRevision!==scene.snapshot.imagery!.expectedContentRevision||value.expectedReportSha256!==scene.snapshot.imagery!.expectedReportSha256)throw new ApiError(409,'RESOURCE_CHANGED');return value;
  }):null]).then(([ground,image])=>{if(!abort.signal.aborted){setTerrain(ground);setImagery(image);}}).catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setResourceError(e);});return()=>abort.abort();
 },[active,client,spatialKey,resourceAttempt]);
 useEffect(()=>{setPersonal({});setTerrainVisible(true);setImageryVisible(opened?.snapshot.imagery?.visible??true);},[spatialKey]);
 useEffect(()=>{if(!active){setAlarms(false);setSettings(false);setAnalysisMounted(false);setOrderMounted(false);setAnalysisDirty(false);setOrderDirty(false);setView(value=>value==='analysis'||value==='orders'?returnView.current:value);}},[active]);
 useEffect(()=>{if(active&&initialEntry&&previousEntry.current!==initialEntry){previousEntry.current=initialEntry;entryPending.current=true;setPinnedEntry(initialEntry);if(initialEntry.camera)saveView(initialEntry.sceneId+':'+initialEntry.sceneRevision,initialEntry.camera);setSceneId(initialEntry.sceneId);setInstanceId(initialEntry.instanceId);setUid('');setView(initialEntry.instanceId?'device':'scene');}},[active,initialEntry]);
 useEffect(()=>{if(!entryPending.current||!opened||!catalog)return;entryPending.current=false;const candidate=selected?.rootBinding?.objectRef.entityUid||'';setUid(counts?.uids.includes(candidate)?candidate:'');if(instanceId)setView('device');},[opened,catalog,instanceId]);
 useEffect(()=>{const handler=(event:KeyboardEvent)=>{if(event.key==='Escape'){setSettings(false);setAlarms(false);}};if(active)window.addEventListener('keydown',handler);return()=>window.removeEventListener('keydown',handler);},[active]);
 function guarded(action:()=>void,blocked=analysisDirty||orderDirty){if(blocked)setLeave(()=>action);else action();}
 function saveView(key:string,value:SceneView){bookmarks.current.delete(key);bookmarks.current.set(key,value);while(bookmarks.current.size>24)bookmarks.current.delete(bookmarks.current.keys().next().value!);}
 function remember(){const value=camera.current?.getView();if(value&&spatialKey)saveView(spatialKey,value);}
 function exit(){remember();guarded(onExit);}
 function navigate(next:View){remember();if(next==='analysis')setAnalysisMounted(true);setView(next);}
 function openScene(id:string){remember();setPinnedEntry(null);entryPending.current=false;setSceneId(id);setInstanceId(null);setUid('');setView('scene');}
 function selectInstance(id:string|null){setInstanceId(id);const candidate=id?opened?.snapshot.instances.find(x=>x.sceneModelInstanceId===id)?.rootBinding?.objectRef.entityUid||'':'';setUid(counts?.uids.includes(candidate)?candidate:'');if(id){setFocus({token:Date.now(),instanceId:id});setView('device');}}
 function analyze(entry:AnalysisEntry){remember();guarded(()=>{if(view!=='analysis'&&view!=='orders')returnView.current=view;setAnalysisEntry(entry);setAnalysisGeneration(v=>v+1);setAnalysisMounted(true);setView('analysis');setAlarms(false);setAnalysisDirty(false);},analysisDirty);}
 function orders(code:string){guarded(()=>{if(view!=='analysis'&&view!=='orders')returnView.current=view;setOrderQuery(code);setOrderMounted(true);setView('orders');setAlarms(false);setOrderDirty(false);},orderDirty);}
 const pending=t('正在读取…','Loading…'),unconnected=t('尚未接入','Not connected');
 if(!active)return null;
 return <div className="pc-root" ref={root} data-theme={resolved} role="region" aria-label={t('项目驾驶舱','Project cockpit')}>
  <div className="pc-frame" style={{zoom:effectiveScale,width:size.width/effectiveScale,height:size.height/effectiveScale,'--pc-scale':effectiveScale} as CSSProperties}>
   <div className="pc-app">
    <header className="pc-header"><button className="pc-brand" onClick={exit} aria-label={t('返回工作台','Return to workbench')}><img src={logo} alt="ONTOVis 本源数智"/></button><div className="pc-project"><small>{t('项目','Project')}</small><strong>{project.displayName}</strong></div>
     <nav aria-label={t('驾驶舱页面','Cockpit pages')}>{([['assets',Globe2,t('项目资产','Project assets')],['scene',Layers,t('场景总览','Scene overview')],['device',Box,t('设备','Equipment')],['analysis',LayoutDashboard,t('分析工作台','Analysis')]] as const).map(([id,Icon,label])=><button key={id} aria-current={view===id?'page':undefined} onClick={()=>navigate(id)}><Icon size={18}/><span>{label}</span></button>)}</nav>
     <div className="pc-header-actions"><IconBtn label={t('返回工作台','Return to workbench')} onClick={exit}><ArrowLeft size={18}/></IconBtn><IconBtn label={t('切换主题','Switch theme')} onClick={()=>setTheme(resolved==='dark'?'light':'dark')}>{resolved==='dark'?<Sun size={18}/>:<Moon size={18}/>}</IconBtn><IconBtn label={t('显示设置','Display settings')} onClick={()=>setSettings(true)}><Settings2 size={18}/></IconBtn></div>
    </header>
    <div className="pc-breadcrumb"><button onClick={()=>navigate('assets')}>{project.displayName}</button>{row&&<><span>/</span><button onClick={()=>navigate('scene')}>{row.summary.displayName}</button></>}{selected&&<><span>/</span><span>{selected.displayName}</span></>}{(view==='analysis'||view==='orders')&&<button className="pc-back" onClick={()=>navigate(returnView.current)}><ArrowLeft size={14}/>{t('返回空间','Return to space')}</button>}</div>
    {!!error&&<div className="pc-error" role="alert">{failureMessage(error,locale)} <Btn onClick={()=>setAttempt(v=>v+1)}>{t('重试','Retry')}</Btn></div>}
    {view==='assets'&&<main className="pc-assets"><div className="pc-globe" aria-hidden="true"><div/><Globe2/></div><section className="pc-panel pc-portfolios"><header><Layers/><h1>{t('资产组合','Asset portfolios')}</h1></header>
     <div className="pc-totals"><span><b>{catalog?.scenes.length??'—'}</b>{t('场景','Scenes')}</span><span><b>{total?.complete?total.devices:'—'}</b>{t('去重设备','Distinct devices')}</span><span><b>—</b>{t('当前告警','Current alarms')}</span></div>
     <label className="pc-search"><Search size={17}/><input aria-label={t('搜索场景','Search scenes')} value={query} onChange={e=>setQuery(e.target.value)} placeholder={t('搜索当前项目场景','Search project scenes')}/></label>
     {!catalog&&!error&&<p role="status">{pending}</p>}{catalog?.scenes.length===0&&<div className="pc-empty"><p>{t('项目尚无场景。','This project has no scenes.')}</p><Btn onClick={()=>guarded(()=>onWorkspace())}>{t('打开场景工作台','Open scene workbench')}</Btn></div>}
     <div className="pc-scene-list">{catalog?.scenes.filter(item=>item.summary.displayName.toLocaleLowerCase().includes(query.toLocaleLowerCase())).map(item=>{
      const count=item.opened?sceneIdentity(item.opened,catalog.equipment,project.projectRef):null;
      return <button key={item.summary.sceneId} className="pc-scene-card" onClick={()=>openScene(item.summary.sceneId)}><span className="pc-card-visual">{item.opened?.snapshot.coordinateFrame.mode==='projected_site'?<Globe2/>:<Box/>}</span><span><strong>{item.summary.displayName}</strong><small>{item.opened?(item.opened.snapshot.coordinateFrame.mode==='projected_site'?t('地理场景 · 精度未核实','Geographic · accuracy unverified'):t('局部模型','Local models')):t('场景读取待重试','Scene read requires retry')}</small><small>{count?`${count.uids.length} ${t('台设备','devices')} · ${count.representations} ${t('个模型表示','representations')}`:'—'}</small>{!!count?.unresolved&&<small>{count.unresolved} {t('个表示身份待解析','unresolved representations')}</small>}</span><ArrowRight size={16}/></button>;
     })}</div>{catalog&&query&&!catalog.scenes.some(item=>item.summary.displayName.toLocaleLowerCase().includes(query.toLocaleLowerCase()))&&<p>{t('无匹配场景。','No matching scenes.')} <button onClick={()=>setQuery('')}>{t('清空搜索','Clear search')}</button></p>}
     <small>{t('场景为资产组合，设备按安装身份去重。','Scenes form portfolios; equipment is counted by installed identity.')}{total&&!total.complete?' '+t('部分场景未读取，汇总暂不可用。','Some scenes could not be read; totals unavailable.'):''}</small>
    </section><aside className="pc-panel pc-source"><h3>{t('数据状态','Data status')}</h3><p><TriangleAlert size={16}/>{t('真实报警','Live alarms')}：{unconnected}</p><p><Cloud size={16}/>{t('天气预报','Weather forecast')}：{t('按场景查看','Available by scene')}</p><button onClick={()=>setAlarms(true)}>{t('查看明确模拟的报警回放','Open simulated alarm replay')}<ArrowRight size={15}/></button><small>{t('背景为中性空间示意，不表示实时天气或已核验资产位置。','Neutral spatial background; not live weather or verified asset positions.')}</small></aside></main>}
    <div className="pc-spatial" hidden={view!=='scene'&&view!=='device'}>
     {opened?<><div className="pc-viewport pc-native"><Suspense fallback={<p role="status">{pending}</p>}><SceneViewport key={spatialKey} api={api} active={active&&(view==='scene'||view==='device')} snapshot={viewportSnapshot!} modelRefs={opened.resourceRefs} terrainVersion={terrain} imageryVersion={imagery} imageryVisible={imageryVisible} terrainVisible={terrainVisible} personalVisibility={personal} editing={false} pendingPlacement={false} selectedId={instanceId} cameraControl={camera} focusRequest={focus} preparationKey={spatialKey+':'+resourceAttempt} preparationError={resourceError} onRetryPreparation={()=>setResourceAttempt(v=>v+1)} onSelect={selectInstance} onPoint={()=>{}} onMove={async()=>false} onViewChange={value=>saveView(spatialKey,value)}/></Suspense><WeatherEffects value={weather.value} enabled={weatherEffects&&weather.usable}/></div>
      <section className="pc-panel pc-scene-info"><h2>{opened.snapshot.displayName}</h2>{historical&&<small>{t('从工作台继承的固定历史版本','Fixed historical version from the workbench')}</small>}<p>{opened.snapshot.description}</p><div className="pc-totals"><span><b>{counts?.uids.length}</b>{t('去重设备','Distinct devices')}</span><span><b>{counts?.representations}</b>{t('模型表示','Representations')}</span></div><small>{opened.snapshot.coordinateFrame.mode==='projected_site'?t('地理参考 · 工程精度未核实','Geographic reference · engineering accuracy unverified'):t('局部坐标 · 无地理范围','Local coordinates · no geographic bounds')}</small>
       <div className="pc-layer-controls"><label><input type="checkbox" checked={terrainVisible} onChange={e=>setTerrainVisible(e.target.checked)}/>{t('地形','Terrain')}</label>{imagery&&<label><input type="checkbox" checked={imageryVisible} onChange={e=>setImageryVisible(e.target.checked)}/>{t('影像','Imagery')}</label>}</div>
       <ul className="pc-tree">{opened.snapshot.instances.map(item=><li key={item.sceneModelInstanceId}><button aria-pressed={instanceId===item.sceneModelInstanceId} onClick={()=>selectInstance(item.sceneModelInstanceId)}><Box size={14}/>{item.displayName}</button><input type="checkbox" aria-label={`${t('显示','Show')} ${item.displayName}`} checked={personal[item.sceneModelInstanceId]??item.visible} onChange={e=>setPersonal(value=>({...value,[item.sceneModelInstanceId]:e.target.checked}))}/></li>)}</ul>
       <Btn onClick={()=>guarded(()=>onWorkspace(sceneId))}>{t('在工作台管理场景','Manage scene in workbench')}</Btn>
      </section><aside className="pc-panel pc-device-panel">{view==='device'&&uid?<CockpitDevice key={uid} api={api} uid={uid} en={en} representationUid={selected?.rootBinding?.objectRef.entityUid} onSelect={setUid} onAnalyze={analyze}/>:<><h2>{view==='device'?t('选择设备','Choose equipment'):t('场景状态','Scene status')}</h2><p>{view==='device'?t('从模型列表选择一台设备。无绑定表示不会自动认定设备身份。','Choose an instance. Unbound representations do not imply equipment identity.'):t('真实运行姿态和报警尚未接入。','Live operating pose and alarms are not connected.')}</p><button onClick={()=>setAlarms(true)}>{t('查看模拟报警回放','View simulated alarm replay')}</button><p className="pc-muted">{t('透视/爆炸与运行旋转等待固定模型能力及轴向核验。','X-ray, exploded views and runtime rotation await fixed-model capability and axis verification.')}</p></>}<WeatherCard value={weather.value} loading={weather.loading} error={weather.error} now={weather.now} en={en}/><label className="wx-toggle"><input type="checkbox" checked={weatherEffects} onChange={e=>setWeatherEffects(e.target.checked)}/>{t('按预报显示特效','Show forecast effects')}</label></aside>
     </>:<section className="pc-panel pc-selection"><h2>{t('选择场景','Choose a scene')}</h2>{!!(pinnedError||row?.error)&&<p role="alert">{failureMessage(pinnedError||row?.error,locale)} <Btn onClick={()=>setAttempt(v=>v+1)}>{t('重新读取','Reload')}</Btn></p>}{!catalog&&!error?<p role="status">{pending}</p>:catalog?.scenes.map(item=><button key={item.summary.sceneId} onClick={()=>openScene(item.summary.sceneId)}>{item.summary.displayName}<ArrowRight size={15}/></button>)}{catalog?.scenes.length===0&&<p>{t('项目尚无场景。','This project has no scenes.')}</p>}</section>}
    </div>
    {analysisMounted&&<div className="pc-workspace pc-native" hidden={view!=='analysis'}><Suspense fallback={<p role="status">{pending}</p>}><AnalysisWorkspace key={analysisGeneration} api={api} locale={locale} initialEntry={analysisEntry} onDirtyChange={setAnalysisDirty} onOpenWorkOrder={orders}/></Suspense></div>}
    {orderMounted&&<div className="pc-workspace pc-native" hidden={view!=='orders'}><Suspense fallback={<p role="status">{pending}</p>}><WorkOrders key={orderQuery} api={api} locale={locale} initialQuery={orderQuery} onDirtyChange={setOrderDirty} onAnalyze={orderId=>analyze({orderId})} onOpenReference={analyze} onOpenAnalysis={(analysisSessionId,analysisRevision,assistantRunId)=>analyze({analysisSessionId,analysisRevision,...(assistantRunId?{assistantRunId}:{})})}/></Suspense></div>}
    {notice&&<p role="status" className="pc-notice">{notice}<button onClick={()=>setNotice('')}><X size={14}/></button></p>}
   </div>
  </div>
  {settings&&<Modal title={t('显示设置','Display settings')} description={t('调整当前会话显示偏好。','Adjust display preferences for this session.')} onClose={()=>setSettings(false)}><div className="pc-settings"><label>{t('界面缩放','Interface scale')}<select aria-label={t('界面缩放','Interface scale')} value={scale} onChange={e=>setScale(e.target.value as InterfaceScale)}><option value="auto">{t('自动','Automatic')}（{automaticScale*100}%）</option><option value="1">100%</option><option value="1.5">150%</option><option value="2">200%</option></select></label><p>{t('调整驾驶舱导航和信息面板尺寸。三维视角、分析工作区倍率及照片原像素比例独立保持。','Scale cockpit navigation and information panels. The 3D view, analysis workspace zoom and original photo pixels remain independent.')}</p><Btn onClick={()=>setScale('auto')}>{t('恢复自动缩放','Reset to automatic')}</Btn><Btn onClick={()=>{if(document.fullscreenElement)void document.exitFullscreen();else void document.documentElement.requestFullscreen().catch(()=>setNotice(t('当前浏览器无法进入全屏。','Fullscreen is unavailable in this browser.')));}}><Maximize2 size={16}/>{t('全屏显示','Fullscreen')}</Btn></div></Modal>}
  {alarms&&<Modal className="pc-alarm-dialog" title={t('模拟报警回放','Simulated alarm replay')} description={t('使用独立的固定模拟来源，不自动关联当前所选设备；不代表项目现场报警。','Independent fixed simulation, not automatically linked to the selected equipment; not live project alarms.')} onClose={()=>setAlarms(false)}><Suspense fallback={<p role="status">{pending}</p>}><p className="pc-dialog-note">{t('独立模拟演练，不自动关联当前所选设备。','Independent simulation; not automatically linked to the selected equipment.')}</p><DataAlarms api={api} locale={locale} onAnalyze={analyze} onOpenWorkOrders={orders}/></Suspense></Modal>}
  {leave&&<Modal title={t('修改尚未保存','Unsaved changes')} description={t('离开前处理未保存修改。','Resolve unsaved changes before leaving.')} onClose={()=>setLeave(null)}><p>{t('继续离开将放弃当前未保存的修改。','Leaving discards the current unsaved edits.')}</p><Btn onClick={()=>setLeave(null)}>{t('继续编辑','Keep editing')}</Btn><Btn onClick={()=>{const change=leave;setLeave(null);change();}}>{t('放弃修改并离开','Discard and leave')}</Btn></Modal>}
 </div>;
}
