import {displayText} from './displayText';
import {useEffect,useId,useRef,useState} from 'react';
import {ApiError} from './api';
import {Btn} from './Primitives';
import type {TaskCandidate} from './assistantTasks';
import type {AssistantSceneTarget} from './assistantScene';

type Filter={query:string;sceneName:string};
type SceneTarget={configurationId:string;modelVersionId:string;cursor:string|null};
export type ModelUsageQuery=Filter&{page:number;expectedSnapshotRevision:string|null;sceneTarget?:SceneTarget};
type ModelUsageRow=Required<Pick<TaskCandidate,'title'|'scenes'>>&{
 configurationId:string;configuration:string;version:string;totalScenes:number;nextSceneCursor:string|null;
};
export type ModelUsagePage={items:ModelUsageRow[];page:number;pageSize:number;total:number;snapshotRevision:string};
type PageLoader=(query:ModelUsageQuery,signal:AbortSignal)=>Promise<ModelUsagePage>;
type ViewScene=(target:AssistantSceneTarget,trigger?:HTMLButtonElement)=>void;
type ModelScenePage={row:ModelUsageRow;history:(string|null)[]};

export function AssistantModelSceneList({scenes,modelVersionId,en,locked,onViewScene}:{
 scenes:TaskCandidate['scenes'];modelVersionId?:string;en:boolean;locked:boolean;onViewScene?:ViewScene;
}){
 const t=(zh:string,english:string)=>en?english:zh;
 if(!scenes?.length)return null;
 return <ul className="as-model-uses">{scenes.map((scene,index)=>{
  const revision=scene.sceneRevision,short=revision?.replace(/^scene:/,'').slice(0,8);
  const target=modelVersionId&&scene.sceneId&&revision?{sceneId:scene.sceneId,sceneRevision:revision,
   title:scene.title,modelVersionId}:null;
  return <li key={scene.sceneId??index}><span><strong>{displayText(scene.title)}</strong>
   <small title={revision??undefined}>{short&&t('保存版','Saved revision')+' '+short+' · '}{scene.instanceCount} {t('个实例','instances')}</small></span>
   {target&&onViewScene&&<Btn aria-haspopup="dialog" aria-label={displayText(t('查看场景','View scene')+' '+scene.title+' '+short)}
    disabled={locked} onClick={event=>onViewScene(target,event.currentTarget)}>{t('查看场景','View scene')}</Btn>}
  </li>;
 })}</ul>;
}

const EMPTY_FILTER={query:'',sceneName:''};

export function AssistantModelUsage({loadPage,en,locked,onViewScene}:{
 loadPage:PageLoader;en:boolean;locked:boolean;onViewScene?:ViewScene;
}){
 const t=(zh:string,english:string)=>en?english:zh;
 const [open,setOpen]=useState(false),[fields,setFields]=useState<Filter>(EMPTY_FILTER);
 const [filter,setFilter]=useState<Filter>(EMPTY_FILTER),[page,setPage]=useState<ModelUsagePage|null>(null);
 const [scenes,setScenes]=useState<Record<string,ModelScenePage>>({});
 const [busy,setBusy]=useState(false),[error,setError]=useState<unknown>(null);
 const request=useRef<AbortController|null>(null),contentId=useId();
 useEffect(()=>()=>request.current?.abort(),[]);

 async function load(criteria:ModelUsageQuery,detail?:{key:string;history:(string|null)[]}){
  if(request.current)return;
  const controller=new AbortController();
  request.current=controller;
  setBusy(true);setError(null);
  try{
   const next=await loadPage(criteria,controller.signal);
   if(controller.signal.aborted)return;
   if(detail){
    if(next.items.length!==1)throw new Error('Invalid scene page');
    const row=next.items[0];
    setScenes(previous=>({...previous,[detail.key]:{row,history:detail.history}}));
   }else{
    setPage(next);setScenes({});
    setFilter({query:criteria.query,sceneName:criteria.sceneName});
   }
  }catch(reason){
   if(!controller.signal.aborted){setPage(null);setScenes({});setError(reason);}
  }finally{
   request.current=null;
   if(!controller.signal.aborted)setBusy(false);
  }
 }
 function search(){
  void load({query:fields.query.trim(),sceneName:fields.sceneName.trim(),page:1,expectedSnapshotRevision:null});
 }
 function showPage(number:number){
  if(page)void load({...filter,page:number,expectedSnapshotRevision:page.snapshotRevision});
 }
 function showScenes(row:ModelUsageRow,key:string,history:(string|null)[]){
  if(page)void load({...filter,page:page.page,expectedSnapshotRevision:page.snapshotRevision,
   sceneTarget:{configurationId:row.configurationId,modelVersionId:row.version,cursor:history.at(-1)??null}},{key,history});
 }
 const disabled=locked||busy;
 const expired=error instanceof ApiError&&error.status===409;
 const denied=error instanceof ApiError&&[401,403,404].includes(error.status);
 return <section className="as-usage-browser">
  <Btn aria-expanded={open} aria-controls={contentId} disabled={locked} onClick={()=>{
   setOpen(!open);
   if(!open&&!page&&!error&&!busy)search();
  }}>{t('完整使用清单','Full usage list')}</Btn>
  {open&&<div id={contentId} aria-busy={busy}>
   <form className="as-usage-filters" onSubmit={event=>{event.preventDefault();search();}}>
    <label>{t('配置或型号','Configuration or model')}<input maxLength={200} disabled={disabled} value={fields.query}
     onChange={event=>setFields({...fields,query:event.currentTarget.value})}/></label>
    <label>{t('场景名称','Scene name')}<input maxLength={200} disabled={disabled} value={fields.sceneName}
     onChange={event=>setFields({...fields,sceneName:event.currentTarget.value})}/></label>
    <Btn type="submit" disabled={disabled}>{t('筛选','Filter')}</Btn>
   </form>
   {busy&&<small role="status">{t('正在读取使用清单…','Loading usage…')}</small>}
   {!!error&&<div className="as-usage-error" role="alert">
    <span>{expired?t('使用清单已变化。','The usage list has changed.'):denied?
     t('当前无法查看此使用清单。','This usage list is unavailable.'):t('读取使用清单失败。','Could not load the usage list.')}</span>
    <Btn disabled={disabled} onClick={search}>{t('从第一页重新读取','Reload from first page')}</Btn>
   </div>}
   {page&&<>
    <small role={busy?undefined:'status'}>{page.total} {t('条模型','model entries')} · {t('第 '+page.page+' 页','Page '+page.page)}</small>
    {!page.items.length&&<p>{t('没有匹配的模型或场景。','No matching models or scenes.')}</p>}
    {page.items.map(initial=>{
     const key=initial.configurationId+':'+initial.version;
     const {row,history}=scenes[key]??{row:initial,history:[null]};
     return <article className="as-usage-card" key={key}>
      <strong>{displayText(row.title)}</strong><small title={row.version}>{row.configuration} · {row.version.slice(0,8)} · {row.totalScenes} {t('个场景','scenes')}</small>
      <AssistantModelSceneList scenes={row.scenes} modelVersionId={row.version} en={en} locked={disabled} onViewScene={onViewScene}/>
      {(history.length>1||row.nextSceneCursor)&&<div className="as-usage-pager" role="group" aria-label={t('场景翻页','Scene pages')}>
       <Btn disabled={disabled||history.length===1} onClick={()=>showScenes(row,key,history.slice(0,-1))}>{t('上一页场景','Previous scenes')}</Btn>
       <Btn disabled={disabled||!row.nextSceneCursor} onClick={()=>showScenes(row,key,[...history,row.nextSceneCursor])}>{t('下一页场景','More scenes')}</Btn>
      </div>}
     </article>;
    })}
    {(page.total>page.pageSize||page.page>1)&&<div className="as-usage-pager" role="group" aria-label={t('模型翻页','Model pages')}>
     <Btn disabled={disabled||page.page===1} onClick={()=>showPage(page.page-1)}>{t('上一页模型','Previous models')}</Btn>
     <Btn disabled={disabled||page.page*page.pageSize>=page.total} onClick={()=>showPage(page.page+1)}>{t('下一页模型','More models')}</Btn>
    </div>}
   </>}
  </div>}
 </section>;
}
