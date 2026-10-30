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
export type CockpitCatalog={scenes:CockpitScene[];equipment:EquipmentCatalogItem[]};
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
  const uids=new Set<string>();let unresolved=0,representations=0,complete=true;
  for(const row of catalog.scenes){
    if(!row.opened){complete=false;continue;}
    const value=sceneIdentity(row.opened,catalog.equipment,project);
    value.uids.forEach(uid=>uids.add(uid));unresolved+=value.unresolved;representations+=value.representations;
  }
  return {devices:uids.size,unresolved,representations,complete};
}

/** Read existing authorized catalogs; never infer a device identity from its model/name. */
export async function readCockpitCatalog(api:WorkbenchApi,signal:AbortSignal):Promise<CockpitCatalog>{
  const client=new SceneApi(api),equipmentApi=new EquipmentApi(api);
  const project=api.project,epoch=api.epoch,revision=api.revision;
  const guard=()=>{if(signal.aborted||api.epoch!==epoch||api.revision!==revision||!project||!api.project||!sameProject(project,api.project))throw new DOMException('Closed','AbortError');};
  const summaries:SceneSummary[]=[],equipment:EquipmentCatalogItem[]=[];
  let cursor:string|null=null,sceneRevision='',equipmentRevision='';
  const sceneCursors=new Set<string>(),equipmentCursors=new Set<string>();
  do {
    guard();const value=await client.list({limit:50,cursor},signal);guard();
    if(sceneRevision&&sceneRevision!==value.snapshotRevision)throw new ApiError(409,'SCENE_CHANGED');
    sceneRevision=value.snapshotRevision;summaries.push(...value.items);cursor=value.nextCursor;
    if(cursor&&(sceneCursors.has(cursor)||summaries.length>=1000))throw new ApiError(422,'COCKPIT_CATALOG_LIMIT');
    if(cursor)sceneCursors.add(cursor);
  }while(cursor);
  do {
    guard();const value=await equipmentApi.catalogue('',cursor,signal);guard();
    if(equipmentRevision&&equipmentRevision!==value.snapshotRevision)throw new ApiError(409,'ENGINEERING_CHANGED');
    equipmentRevision=value.snapshotRevision;equipment.push(...value.items);cursor=value.nextCursor;
    if(cursor&&(equipmentCursors.has(cursor)||equipment.length>=10000))throw new ApiError(422,'COCKPIT_CATALOG_LIMIT');
    if(cursor)equipmentCursors.add(cursor);
  }while(cursor);
  const scenes:CockpitScene[]=summaries.map(summary=>({summary,opened:null,error:null}));let index=0;
  await Promise.all(Array.from({length:Math.min(3,scenes.length)},async()=>{
    while(index<scenes.length){
      const row=scenes[index++];guard();
      try {const opened=await client.open(row.summary.sceneId,row.summary.headRevision,signal);guard();
        if(opened.sceneId!==row.summary.sceneId||opened.sceneRevision!==row.summary.headRevision||opened.projectCode!==project!.projectCode)throw new ApiError(409,'SCENE_CHANGED');
        row.opened=opened;
      }catch(error){guard();if(error instanceof ApiError&&[401,403].includes(error.status))throw error;row.error=error;}
    }
  }));
  guard();return {scenes,equipment};
}
