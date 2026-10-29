import assert from 'node:assert/strict';
import test from 'node:test';
import {equipmentSimulationTarget} from '../src/equipmentSimulationTarget.ts';

const definition={entityUid:'definition-cn1',entityRevision:'d1',objectKind:'cabinet',objectScope:'definition',identifiers:[{role:'primary',value:'=WEC+CN1'}]};
const root={entityUid:'device-7',entityRevision:'r1',displayName:'Device 7',objectScope:'installation',installationContextId:'installation-7'};
const cabinet={entityUid:'device-7-cn1',entityRevision:'c1',displayName:'Cabinet 7',objectKind:'cabinet',objectScope:'installation',installationContextId:'installation-7',sourceTemplateEntityUid:definition.entityUid};
const context={item:root,root,objectRef:{entityUid:root.entityUid,projectCode:'project-a'},context:{installationContextId:'installation-7',hierarchyRevision:'h1',projectCode:'project-a'}};
const record={item:root,context:{installationContextId:'installation-7',hierarchyRevision:'h1',rootEntityUid:root.entityUid,projectCode:'project-a'},children:[cabinet],adoption:{applicationRevisionId:'app-r1'}};
const bundle={application:{revisionId:'app-r1',projectCode:'project-a',snapshot:{mappings:[{roleKey:'source-role',entityUid:definition.entityUid,expectedEntityRevision:'d1'}]}},objects:[definition]};
const dataset={primaryRds:'=WEC+CN1-1B4',cabinet:'CN1'};
test('a root device resolves only its recorded child through the adopted shared definition',()=>{
  const target=equipmentSimulationTarget(record,context,bundle,dataset);
  assert.equal(target.item.entityUid,cabinet.entityUid);assert.equal(target.definition.entityUid,definition.entityUid);
  assert.equal(target.rootUid,root.entityUid);assert.equal(target.engineeringRds,dataset.primaryRds);assert.equal(target.roleKey,'source-role');
});
test('the cabinet itself can be selected without inventing an installed sensor identity',()=>{
  const target=equipmentSimulationTarget({...record,item:cabinet,children:[]},{...context,item:cabinet,objectRef:{...context.objectRef,entityUid:cabinet.entityUid}},bundle,dataset);
  assert.equal(target.item.entityUid,cabinet.entityUid);assert.equal(target.rootUid,root.entityUid);
  assert.equal(Object.hasOwn(target,'sensorUid'),false);
});
test('another device shares only the definition and never receives the other installation UID',()=>{
  const otherRoot={...root,entityUid:'device-4',installationContextId:'installation-4'};
  const otherCabinet={...cabinet,entityUid:'device-4-cn1',installationContextId:'installation-4'};
  const otherRecord={...record,item:otherRoot,context:{...record.context,installationContextId:'installation-4',rootEntityUid:otherRoot.entityUid},children:[otherCabinet]};
  const target=equipmentSimulationTarget(otherRecord,{item:otherRoot,root:otherRoot,context:otherRecord.context,objectRef:{...context.objectRef,entityUid:otherRoot.entityUid}},bundle,dataset);
  assert.equal(target.item.entityUid,'device-4-cn1');assert.notEqual(target.item.entityUid,cabinet.entityUid);
});
test('display names cannot create a target and another cabinet cannot borrow CN1 state',()=>{
  const cn2={...cabinet,entityUid:'cn2',sourceTemplateEntityUid:'definition-cn2',displayName:'CN1'};
  assert.equal(equipmentSimulationTarget({...record,item:cn2,children:[]},{...context,item:cn2},bundle,dataset),null);
  assert.equal(equipmentSimulationTarget(record,context,{...bundle,objects:[{...definition,identifiers:[],displayName:'CN1'}]},dataset),null);
});
test('missing or changed adoption and layer revisions refuse the simulated target',()=>{
  for(const [r,c,b] of [[{...record,adoption:null},context,bundle],[record,context,null],
    [record,context,{...bundle,application:{...bundle.application,revisionId:'new'}}],
    [record,{...context,item:{...root,entityRevision:'changed'}},bundle],
    [record,{...context,context:{...context.context,hierarchyRevision:'h2'}},bundle]]){
    assert.equal(equipmentSimulationTarget(r,c,b,dataset),null);
  }
});
test('ambiguous definitions, duplicate children and cross-installation children do not guess a match',()=>{
  assert.equal(equipmentSimulationTarget(record,context,{...bundle,objects:[definition,definition]},dataset),null);
  assert.equal(equipmentSimulationTarget({...record,children:[cabinet,cabinet]},context,bundle,dataset),null);
  assert.equal(equipmentSimulationTarget({...record,children:[{...cabinet,installationContextId:'installation-4'}]},context,bundle,dataset),null);
});
test('source cabinet identity and fixed mapping revisions are required',()=>{
  assert.equal(equipmentSimulationTarget(record,context,bundle,{...dataset,cabinet:'CN2'}),null);
  assert.equal(equipmentSimulationTarget(record,context,bundle,{...dataset,primaryRds:'unstructured-name'}),null);
  assert.equal(equipmentSimulationTarget(record,context,{...bundle,application:{...bundle.application,snapshot:{mappings:[{entityUid:definition.entityUid,expectedEntityRevision:'old'}]}}},dataset),null);
});
test('root and project scope must agree across the selected device, context and adopted application',()=>{
  for(const [r,c,b] of [
    [{...record,context:{...record.context,rootEntityUid:'another-root'}},context,bundle],
    [record,{...context,objectRef:{...context.objectRef,entityUid:'another-device'}},bundle],
    [record,{...context,objectRef:{...context.objectRef,projectCode:'project-b'}},bundle],
    [record,{...context,context:{...context.context,projectCode:'project-b'}},bundle],
    [record,context,{...bundle,application:{...bundle.application,projectCode:'project-b'}}],
  ])assert.equal(equipmentSimulationTarget(r,c,b,dataset),null);
});
