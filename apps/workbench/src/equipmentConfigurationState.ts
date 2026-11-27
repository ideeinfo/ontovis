import type {ApplicationBundle,EquipmentConfigurationSnapshot,EquipmentConfigurations,EquipmentRecord} from './equipmentApi';
import type {SceneModelInstance} from './sceneTypes';

export function canContinueEquipmentConfiguration(snapshot:EquipmentConfigurationSnapshot,application:ApplicationBundle['application']):boolean {
 const source=application.snapshot,root=snapshot.rootDefinition;
 if(snapshot.projectApplicationRef&&snapshot.projectApplicationRef.applicationId!==application.applicationId)return false;
 if(snapshot.objectKind!==application.specification.objectKind||root?.objectRef.entityUid!==source.rootDefinition?.entityUid||root?.expectedEntityRevision!==source.rootDefinition?.expectedEntityRevision)return false;
 const allowed=new Map([...(source.rootDefinition?[source.rootDefinition]:[]),...source.mappings].map(row=>[row.entityUid,row.expectedEntityRevision]));
 return snapshot.models.every(model=>model.mappings.every(row=>allowed.get(row.objectRef.entityUid)===row.expectedEntityRevision));
}

export function equipmentConfigurationNeedsCopy(snapshot:EquipmentConfigurationSnapshot,application:ApplicationBundle['application']):boolean {
 const ref=snapshot.projectApplicationRef;
 return !!ref&&(ref.applicationId!==application.applicationId||ref.applicationRevisionId!==application.revisionId||ref.specificationRevisionId!==application.snapshot.specificationRevisionId);
}

/** Match current fixed adoption and exact template identities; leave historical scene snapshots untouched. */
export function cockpitBoundInstance(instance:SceneModelInstance,record:EquipmentRecord,catalog:EquipmentConfigurations):SceneModelInstance {
 const root=instance.rootBinding?.objectRef,adoption=record.adoption;
 if(!root||root.entityUid!==record.item.entityUid||!adoption)return instance;
 const configs=catalog.items.filter(item=>{const ref=item.snapshot.projectApplicationRef;return ref?.applicationId===adoption.applicationId&&ref.applicationRevisionId===adoption.applicationRevisionId&&ref.specificationRevisionId===adoption.specificationRevisionId;});
 if(configs.length!==1)return instance;
 const models=configs[0].snapshot.models.filter(model=>model.modelVersionId===instance.modelVersionId);if(models.length!==1)return instance;
 const componentBindings=[...instance.componentBindings],occupied=new Set(componentBindings.flatMap(item=>item.componentKeys));
 for(const mapping of models[0].mappings){
  if(!mapping.componentKeys.length||mapping.objectRef.projectCode!==root.projectCode||mapping.objectRef.ontobaseConnectionId!==root.ontobaseConnectionId)continue;
  const children=record.children.filter(item=>item.sourceTemplateEntityUid===mapping.objectRef.entityUid);
  if(children.length!==1||componentBindings.some(item=>item.objectRef.entityUid===children[0].entityUid)||mapping.componentKeys.some(key=>occupied.has(key)))continue;
  componentBindings.push({objectRef:{...root,entityUid:children[0].entityUid},componentKeys:[...mapping.componentKeys]});for(const key of mapping.componentKeys)occupied.add(key);
 }
 return {...instance,componentBindings};
}
