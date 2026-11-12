import assert from 'node:assert/strict';
import test from 'node:test';
import {canContinueEquipmentConfiguration,cockpitBoundInstance,equipmentConfigurationNeedsCopy} from '../src/equipmentConfigurationState.ts';
const ref={ontobaseConnectionId:'source',projectCode:'project',entityUid:'root-template'},adoption={applicationId:'app',applicationRevisionId:'app-r2',specificationRevisionId:'spec-r2'};
const snapshot={objectKind:'equipment',projectApplicationRef:{...adoption,applicationRevisionId:'app-r1'},rootDefinition:{objectRef:ref,expectedEntityRevision:'root-r1'},models:[{modelVersionId:'model',mappings:[{objectRef:{...ref,entityUid:'part-template'},expectedEntityRevision:'part-r1',componentKeys:['mesh']}]}]};
const app={applicationId:'app',specification:{objectKind:'equipment'},snapshot:{rootDefinition:{entityUid:'root-template',expectedEntityRevision:'root-r1'},mappings:[{entityUid:'part-template',expectedEntityRevision:'part-r1'}]}};
test('adoption continuation preserves exact mapped identities and revisions across an application revision',()=>{
 assert.equal(canContinueEquipmentConfiguration(snapshot,app),true);
 assert.equal(canContinueEquipmentConfiguration(snapshot,{...app,applicationId:'different'}),false);
 assert.equal(canContinueEquipmentConfiguration(snapshot,{...app,snapshot:{...app.snapshot,mappings:[{entityUid:'part-template',expectedEntityRevision:'part-r2'}]}}),false);
 assert.equal(canContinueEquipmentConfiguration(snapshot,{...app,snapshot:{...app.snapshot,rootDefinition:{entityUid:'new-root',expectedEntityRevision:'root-r1'}}}),false);
});
test('reverse binding projection requires the current adopted revision and unique installed template identity',()=>{
 const instance={sceneModelInstanceId:'instance',modelVersionId:'model',rootBinding:{objectRef:{...ref,entityUid:'installed-root'}},componentBindings:[]};
 const record={item:{entityUid:'installed-root'},adoption,children:[{entityUid:'installed-part',sourceTemplateEntityUid:'part-template'}]};
 const catalog={items:[{snapshot:{...snapshot,projectApplicationRef:adoption}}]};
 const bound=cockpitBoundInstance(instance,record,catalog);
 assert.equal(bound.componentBindings[0].objectRef.entityUid,'installed-part');assert.deepEqual(bound.componentBindings[0].componentKeys,['mesh']);assert.deepEqual(instance.componentBindings,[]);
 assert.equal(cockpitBoundInstance(instance,record,{items:[{snapshot}]}),instance);
 assert.equal(cockpitBoundInstance(instance,record,{items:[...catalog.items,...catalog.items]}),instance);
 assert.deepEqual(cockpitBoundInstance(instance,{...record,children:[...record.children,...record.children]},catalog).componentBindings,[]);
 const occupied={...instance,componentBindings:[{objectRef:{...ref,entityUid:'explicit-part'},componentKeys:['mesh']}]};
 assert.deepEqual(cockpitBoundInstance(occupied,record,catalog).componentBindings,occupied.componentBindings);
});
test('new adoption revisions copy bindings while legacy attachment and the same fixed adoption keep their identity',()=>{
 const current={...app,revisionId:adoption.applicationRevisionId,snapshot:{...app.snapshot,specificationRevisionId:adoption.specificationRevisionId}};
 assert.equal(equipmentConfigurationNeedsCopy(snapshot,current),true);
 assert.equal(equipmentConfigurationNeedsCopy({...snapshot,projectApplicationRef:null},current),false);
 assert.equal(equipmentConfigurationNeedsCopy({...snapshot,projectApplicationRef:adoption},current),false);
 assert.equal(equipmentConfigurationNeedsCopy({...snapshot,projectApplicationRef:adoption},{...current,snapshot:{...current.snapshot,specificationRevisionId:'changed'}}),true);
});
