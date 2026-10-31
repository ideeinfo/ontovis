import type {CockpitCatalog,CockpitScene} from './cockpitState';
import type {ProjectRef} from './projectTypes';
import type {SceneModelInstance} from './sceneTypes';
import type {EquipmentRecord,ApplicationBundle} from './equipmentApi';
import type {SceneObjectContext} from './sceneEngineeringTypes';
import type {SimulatedDataset} from './simulatedAlarms';
import {sceneAlarmInstances} from './sceneAlarm.ts';
import {equipmentSimulationTarget} from './equipmentSimulationTarget.ts';

export type CockpitAlarmPlacement={key:string;scene:CockpitScene;instance:SceneModelInstance};
export type CockpitAlarmTarget={sceneId:string;sceneRevision:string;instanceId:string;modelVersionId:string;rootUid:string;rootName:string;entityUid:string;entityRevision:string;displayName:string};

/** The operator selects an installed unit for the exercise, never a shared model definition. */
export function cockpitAlarmPlacements(catalog:CockpitCatalog|null,project:ProjectRef):CockpitAlarmPlacement[]{
 if(!catalog)return [];
 const known=new Set(catalog.equipment.filter(item=>item.objectScope==='installation').map(item=>item.entityUid));
 return catalog.scenes.filter(scene=>scene.opened&&!scene.error).flatMap(scene=>sceneAlarmInstances(scene.opened!.snapshot)
  .filter(instance=>instance.visible&&known.has(instance.rootBinding!.objectRef.entityUid)&&instance.rootBinding!.objectRef.projectCode===project.projectCode&&instance.rootBinding!.objectRef.ontobaseConnectionId===project.ontobaseConnectionId)
  .map(instance=>({key:JSON.stringify([scene.summary.sceneId,instance.sceneModelInstanceId]),scene,instance})))
  .sort((a,b)=>Number(b.scene.opened!.snapshot.coordinateFrame.mode==='projected_site')-Number(a.scene.opened!.snapshot.coordinateFrame.mode==='projected_site')||a.scene.summary.displayName.localeCompare(b.scene.summary.displayName,'zh')||a.instance.displayName.localeCompare(b.instance.displayName,'zh',{numeric:true})||a.key.localeCompare(b.key));
}

export function cockpitAlarmTarget(placement:CockpitAlarmPlacement,record:EquipmentRecord,context:SceneObjectContext,bundle:ApplicationBundle,dataset:SimulatedDataset):CockpitAlarmTarget|null{
 const ref=placement.instance.rootBinding?.objectRef,scene=placement.scene.opened;
 if(!scene||!ref||dataset.sourceKind!=='simulated'||record.item.entityUid!==ref.entityUid||context.objectRef.ontobaseConnectionId!==ref.ontobaseConnectionId||context.objectRef.projectCode!==ref.projectCode||record.context.rootEntityUid!==ref.entityUid)return null;
 const target=equipmentSimulationTarget(record,context,bundle,dataset);
 return target?{sceneId:scene.sceneId,sceneRevision:scene.sceneRevision,instanceId:placement.instance.sceneModelInstanceId,modelVersionId:placement.instance.modelVersionId,rootUid:target.rootUid,rootName:target.rootName,entityUid:target.item.entityUid,entityRevision:target.item.entityRevision,displayName:target.item.displayName}:null;
}

export function cockpitAlarmTargetCurrent(target:CockpitAlarmTarget,catalog:CockpitCatalog|null){
 const scene=catalog?.scenes.find(row=>row.summary.sceneId===target.sceneId)?.opened;
 const instance=scene?.snapshot.instances.find(row=>row.sceneModelInstanceId===target.instanceId);
 return !!scene&&scene.sceneRevision===target.sceneRevision&&instance?.modelVersionId===target.modelVersionId&&instance.rootBinding?.objectRef.entityUid===target.rootUid&&instance.visible;
}
