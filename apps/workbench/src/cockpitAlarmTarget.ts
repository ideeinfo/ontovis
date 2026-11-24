import type {CockpitCatalog} from './cockpitState';
import type {ProjectRef} from './projectTypes';
import type {SceneOpen} from './sceneTypes';
import type {SimulationTarget} from './simulatedAlarms';

export type CockpitAlarmTarget={sceneId:string;sceneRevision:string;instanceId:string;modelVersionId:string;rootUid:string;rootName:string;entityUid:string;entityRevision:string;displayName:string};

export function cockpitAlarmTarget(catalog:CockpitCatalog|null,project:ProjectRef,registration:SimulationTarget|undefined):CockpitAlarmTarget|null{
 if(!registration)return null;
 const entry=catalog?.scenes.find(row=>row.summary.sceneId===registration.sceneId),scene=entry?.opened;
 if(!scene||entry.error||scene.sceneId!==registration.sceneId)return null;
 const instance=scene.snapshot.instances.find(row=>row.sceneModelInstanceId===registration.instanceId);
 const ref=instance?.rootBinding?.objectRef;
 if(!instance?.visible||ref?.entityUid!==registration.rootUid||ref.projectCode!==project.projectCode||ref.ontobaseConnectionId!==project.ontobaseConnectionId)return null;
 const {sceneId,instanceId,rootUid,rootName,entityUid,entityRevision,displayName}=registration;
 return {sceneId,instanceId,rootUid,rootName,entityUid,entityRevision,displayName,
  sceneRevision:scene.sceneRevision,modelVersionId:instance.modelVersionId};
}

export function cockpitAlarmInstance(target:CockpitAlarmTarget,scene:SceneOpen|null|undefined){
 if(scene?.sceneId!==target.sceneId||scene.sceneRevision!==target.sceneRevision)return;
 const instance=scene.snapshot.instances.find(row=>row.sceneModelInstanceId===target.instanceId);
 if(instance?.visible&&instance.modelVersionId===target.modelVersionId&&instance.rootBinding?.objectRef.entityUid===target.rootUid)return instance;
}

export function cockpitAlarmTargetCurrent(target:CockpitAlarmTarget,catalog:CockpitCatalog|null){
 const scene=catalog?.scenes.find(row=>row.summary.sceneId===target.sceneId)?.opened;
 return !!cockpitAlarmInstance(target,scene);
}
