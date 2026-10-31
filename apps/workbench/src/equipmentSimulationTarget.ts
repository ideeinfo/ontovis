import type {EquipmentRecord,ApplicationBundle} from './equipmentApi';
import type {SceneObjectContext} from './sceneEngineeringTypes';
import type {SimulatedDataset} from './simulatedAlarms';

/** Resolve the declared demo cabinet identity through the adopted definition,
 * then the recorded installation. Display names never participate in the join. */
export function equipmentSimulationTarget(record:EquipmentRecord,context:SceneObjectContext,bundle:ApplicationBundle|null,dataset:SimulatedDataset){
  if(!bundle||!record.adoption||record.adoption.applicationRevisionId!==bundle.application.revisionId
      ||context.item.entityUid!==record.item.entityUid||context.item.entityRevision!==record.item.entityRevision
      ||context.context?.installationContextId!==record.context.installationContextId
      ||context.context.hierarchyRevision!==record.context.hierarchyRevision
      ||!record.context.rootEntityUid||(context.root?.entityUid??context.item.entityUid)!==record.context.rootEntityUid
      ||context.objectRef.entityUid!==record.item.entityUid
      ||context.objectRef.projectCode!==record.context.projectCode
      ||context.context.projectCode!==record.context.projectCode
      ||bundle.application.projectCode!==record.context.projectCode)return null;
  const boundary=dataset.primaryRds.indexOf('-'),cabinetRds=boundary>0?dataset.primaryRds.slice(0,boundary):'';
  if(!cabinetRds||!dataset.cabinet||!cabinetRds.endsWith('+'+dataset.cabinet))return null;
  const definitions=bundle.objects.filter(item=>item.objectKind==='cabinet'&&item.objectScope==='definition'
    &&item.identifiers?.some(id=>id.role==='primary'&&id.value===cabinetRds)
    &&bundle.application.snapshot.mappings.some(map=>map.entityUid===item.entityUid&&map.expectedEntityRevision===item.entityRevision));
  if(definitions.length!==1)return null;
  const definition=definitions[0];
  const candidates=[record.item,...record.children].filter(item=>item.objectScope==='installation'
    &&item.objectKind==='cabinet'&&item.installationContextId===record.context.installationContextId
    &&item.sourceTemplateEntityUid===definition.entityUid);
  if(candidates.length!==1)return null;
  const item=candidates[0];
  return {item,definition,rootUid:record.context.rootEntityUid,
    rootName:context.root?.displayName||record.item.displayName,roleKey:bundle.application.snapshot.mappings.find(map=>map.entityUid===definition.entityUid)!.roleKey,
    engineeringRds:dataset.primaryRds,cabinetRds};
}
