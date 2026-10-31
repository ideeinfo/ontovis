import {ApiError,type WorkbenchApi} from './api.ts';
import {SceneApi} from './sceneApi.ts';
import {EquipmentApi,type EquipmentCatalogItem} from './equipmentApi.ts';
import type {ProjectRef} from './projectTypes';
import type {SceneOpen,SceneSummary} from './sceneTypes';

export type InterfaceScale='auto'|'1'|'1.5'|'2';
export function interfaceScale(value:InterfaceScale,width:number,height:number){
  if(value==='1'||value==='1.5'||value==='2')return Number(value);
  // ResizeObserver may report subpixel rounding at a display-density boundary.
  const w=Math.round(width),h=Math.round(height);
  return w>=3840&&h>=2160?2:w>=2880&&h>=1620?1.5:1;
}
export type CockpitScene={summary:SceneSummary;opened:SceneOpen|null;error:unknown|null};
export type CockpitCatalog={scenes:CockpitScene[];equipment:EquipmentCatalogItem[];loading?:boolean;equipmentReady?:boolean};
export function sameProject(a:ProjectRef,b:ProjectRef){return a.ontobaseConnectionId===b.ontobaseConnectionId&&a.projectCode===b.projectCode;}
export function sceneIdentity(scene:SceneOpen,equipment:EquipmentCatalogItem[],project:ProjectRef){
  const known=new Set(equipment.filter(row=>row.objectScope==='installation').map(row=>row.entityUid));
  const uids=new Set<string>();let unresolved=0;
  for(const instance of scene.snapshot.instances){
    const ref=instance.rootBinding?.objectRef;
    if(ref&&sameProject(ref,project)&&known.has(ref.entityUid))uids.add(ref.entityUid);else unresolved++;
  }
  return {uids:[...uids],unresolved,representations:scene.snapshot.instances.length};
}
export function catalogIdentity(catalog:CockpitCatalog,project:ProjectRef){
  const uids=new Set<string>();let unresolved=0,representations=0,complete=!catalog.loading&&catalog.equipmentReady!==false;
  for(const row of catalog.scenes){
    if(!row.opened){complete=false;continue;}
    const value=sceneIdentity(row.opened,catalog.equipment,project);
    value.uids.forEach(uid=>uids.add(uid));unresolved+=value.unresolved;representations+=value.representations;
  }
  return {devices:uids.size,unresolved,representations,complete};
}

/** Session memory only. A new project/session epoch cannot reuse private scene snapshots. */
export class CockpitCatalogCache {
  private value:CockpitCatalog|null=null;
  private readonly epoch:number;
  private readonly revision:string;
  private readonly project:ProjectRef|null;
  private readonly api:WorkbenchApi;
  priority='';
  constructor(api:WorkbenchApi){this.api=api;this.epoch=api.epoch;this.revision=api.revision;this.project=api.project?{...api.project}:null;}
  peek(){
    if(this.api.epoch!==this.epoch||this.api.revision!==this.revision||!this.project||!this.api.project||!sameProject(this.project,this.api.project))this.value=null;
    return this.value;
  }
  async read(signal:AbortSignal,changed:(value:CockpitCatalog)=>void){
    const cached=this.peek();
    if(this.api.epoch!==this.epoch||this.api.revision!==this.revision||!this.project||!this.api.project||!sameProject(this.project,this.api.project))throw new DOMException('Closed','AbortError');
    if(cached&&!signal.aborted)changed(cached);
    try {
      return await readCockpitCatalog(this.api,signal,{cached,priority:()=>this.priority,changed:value=>{
        if(signal.aborted||this.api.epoch!==this.epoch||this.api.revision!==this.revision)return;
        this.value=value;changed(value);
      }});
    }catch(error){if(!signal.aborted&&!(error instanceof DOMException&&error.name==='AbortError'))this.value=null;this.peek();throw error;}
  }
}

/** Publish the list before its details; reuse only snapshots matching a freshly authorized head. */
export async function readCockpitCatalog(api:WorkbenchApi,signal:AbortSignal,options:{cached?:CockpitCatalog|null;changed?:(value:CockpitCatalog)=>void;priority?:()=>string}={}):Promise<CockpitCatalog>{
  const client=new SceneApi(api),equipmentApi=new EquipmentApi(api);
  const project=api.project,epoch=api.epoch,revision=api.revision;
  let closed=false;
  const guard=()=>{if(closed||signal.aborted||api.epoch!==epoch||api.revision!==revision||!project||!api.project||!sameProject(project,api.project))throw new DOMException('Closed','AbortError');};
  const summaries:SceneSummary[]=[],equipment:EquipmentCatalogItem[]=[];
  let scenes:CockpitScene[]=[],equipmentReady=false;
  const publish=(loading=true)=>{guard();const value={scenes:[...scenes],equipment:[...equipment],loading,equipmentReady};options.changed?.(value);return value;};
  const equipmentTask=(async()=>{
    let cursor:string|null=null,equipmentRevision='';const equipmentCursors=new Set<string>();
    do {
      guard();const value=await equipmentApi.catalogue('',cursor,signal);guard();
      if(equipmentRevision&&equipmentRevision!==value.snapshotRevision)throw new ApiError(409,'ENGINEERING_CHANGED');
      equipmentRevision=value.snapshotRevision;equipment.push(...value.items);cursor=value.nextCursor;
      if(cursor&&(equipmentCursors.has(cursor)||equipment.length>=10000))throw new ApiError(422,'COCKPIT_CATALOG_LIMIT');
      if(cursor)equipmentCursors.add(cursor);
    }while(cursor);
    equipmentReady=true;if(scenes.length)publish();
  })();
  // Observe a failed independent read immediately, including when the scene list is slower.
  void equipmentTask.catch(()=>undefined);
  let cursor:string|null=null,sceneRevision='';
  const sceneCursors=new Set<string>();
  try {
  do {
    guard();const value=await client.list({limit:50,cursor},signal);guard();
    if(sceneRevision&&sceneRevision!==value.snapshotRevision)throw new ApiError(409,'SCENE_CHANGED');
    sceneRevision=value.snapshotRevision;summaries.push(...value.items);cursor=value.nextCursor;
    if(cursor&&(sceneCursors.has(cursor)||summaries.length>=1000))throw new ApiError(422,'COCKPIT_CATALOG_LIMIT');
    if(cursor)sceneCursors.add(cursor);
  }while(cursor);
  scenes=summaries.map(summary=>{
    const prior=options.cached?.scenes.find(row=>row.summary.sceneId===summary.sceneId&&row.opened?.sceneRevision===summary.headRevision);
    return {summary,opened:prior?.opened??null,error:null};
  });publish();
  const waiting=scenes.filter(row=>!row.opened);
  const sceneTask=Promise.all(Array.from({length:Math.min(3,scenes.length)},async()=>{
    while(waiting.length){
      const preferred=waiting.findIndex(row=>row.summary.sceneId===options.priority?.());
      const row=waiting.splice(Math.max(0,preferred),1)[0];guard();
      try {const opened=await client.open(row.summary.sceneId,row.summary.headRevision,signal);guard();
        if(opened.sceneId!==row.summary.sceneId||opened.sceneRevision!==row.summary.headRevision||opened.projectCode!==project!.projectCode)throw new ApiError(409,'SCENE_CHANGED');
        scenes=scenes.map(item=>item===row?{...row,opened}:item);
      }catch(error){guard();if(error instanceof ApiError&&[401,403].includes(error.status))throw error;scenes=scenes.map(item=>item===row?{...row,error}:item);}
      publish();
    }
  }));
  await Promise.all([sceneTask,equipmentTask]);return publish(false);
  }finally{closed=true;}
}
