import type {CockpitCatalog} from './cockpitState';
import type {ProjectRef} from './projectTypes';
import type {SceneOpen} from './sceneTypes';
import {motionProfile} from './motionProfiles.ts';
import {sameProject} from './cockpitState.ts';

/** Fixed-content profiles identify complete turbine models, without guessing from names. */
export function cockpitTurbineIds(scene:SceneOpen){
 const models=new Set(scene.resourceRefs.filter(ref=>motionProfile(ref.sha256)).map(ref=>ref.modelVersionId));
 return scene.snapshot.instances.filter(item=>models.has(item.modelVersionId)).map(item=>item.sceneModelInstanceId);
}
export function cockpitOverviewIds(scene:SceneOpen){
 const turbines=cockpitTurbineIds(scene);
 return turbines.length?turbines:scene.snapshot.instances.map(item=>item.sceneModelInstanceId);
}
export function cockpitFleet(catalog:CockpitCatalog,project:ProjectRef){
 const installed=new Set(catalog.equipment.filter(row=>row.objectScope==='installation').map(row=>row.entityUid));
 const units=new Set<string>(),unbound=new Set<string>();let complete=!catalog.loading&&catalog.equipmentReady!==false;
 for(const row of catalog.scenes){
  if(!row.opened){complete=false;continue;}
  const ids=new Set(cockpitTurbineIds(row.opened));
  for(const item of row.opened.snapshot.instances){
   if(!ids.has(item.sceneModelInstanceId))continue;
   const ref=item.rootBinding?.objectRef;
   if(ref&&sameProject(ref,project)&&installed.has(ref.entityUid))units.add('installed:'+ref.entityUid);
   else {const key=JSON.stringify([row.opened.sceneId,item.sceneModelInstanceId]);units.add(key);unbound.add(key);}
  }
 }
 return {turbines:units.size,unboundTurbines:unbound.size,complete};
}
