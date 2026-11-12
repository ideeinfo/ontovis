import test from 'node:test';
import assert from 'node:assert/strict';
import {cockpitAlarmPlacements,cockpitAlarmTarget,cockpitAlarmTargetCurrent} from '../src/cockpitAlarmTarget.ts';
const ref={entityUid:'unit-1',projectCode:'project',ontobaseConnectionId:'connection'};
const root={entityUid:'unit-1',entityRevision:'unit-r1',objectScope:'installation',displayName:'Unit 1',installationContextId:'installed-1'};
const cabinet={entityUid:'cn1-unit-1',entityRevision:'cabinet-r1',displayName:'Unit 1 CN1',objectScope:'installation',objectKind:'cabinet',installationContextId:'installed-1',sourceTemplateEntityUid:'cn1-definition'};
const instance={sceneModelInstanceId:'placed-1',modelVersionId:'model-fixed',displayName:'Unit 1',visible:true,rootBinding:{objectRef:ref},componentBindings:[]};
const scene={summary:{sceneId:'scene-1',displayName:'Scene 1'},opened:{sceneId:'scene-1',sceneRevision:'s-r1',snapshot:{coordinateFrame:{mode:'projected_site'},instances:[instance]}}};
const catalog={scenes:[scene],equipment:[root]},placement=cockpitAlarmPlacements(catalog,ref)[0];
const installation={rootEntityUid:'unit-1',projectCode:'project',installationContextId:'installed-1',hierarchyRevision:'h1'};
const record={item:root,context:installation,children:[cabinet],adoption:{applicationRevisionId:'application-fixed'}};
const context={item:root,root,context:installation,objectRef:ref};
const bundle={application:{revisionId:'application-fixed',projectCode:'project',snapshot:{mappings:[{entityUid:'cn1-definition',expectedEntityRevision:'definition-r1',roleKey:'cabinet-role'}]}},objects:[{entityUid:'cn1-definition',entityRevision:'definition-r1',objectKind:'cabinet',objectScope:'definition',identifiers:[{role:'primary',value:'=WEC+CN1'}]}]};
const dataset={sourceKind:'simulated',cabinet:'CN1',primaryRds:'=WEC+CN1-1B4'};
test('alarm exercise placements require visible, unique installed units in the authorized project',()=>{
 assert.equal(placement.instance,instance);
 for(const changed of [{visible:false},{rootBinding:null},{rootBinding:{objectRef:{...ref,projectCode:'elsewhere'}}}])assert.equal(cockpitAlarmPlacements({...catalog,scenes:[{...scene,opened:{...scene.opened,snapshot:{...scene.opened.snapshot,instances:[{...instance,...changed}]}}}]},ref).length,0);
 assert.equal(cockpitAlarmPlacements({...catalog,equipment:[]},ref).length,0);
 assert.equal(cockpitAlarmPlacements({...catalog,scenes:[{...scene,opened:{...scene.opened,snapshot:{...scene.opened.snapshot,instances:[instance,{...instance,sceneModelInstanceId:'duplicate'}]}}}]},ref).length,0);
});
test('a simulated alarm resolves to the installed cabinet, keeping its scene, model and engineering revision',()=>{
 const target=cockpitAlarmTarget(placement,record,context,bundle,dataset);
 assert.deepEqual(target,{sceneId:'scene-1',sceneRevision:'s-r1',instanceId:'placed-1',modelVersionId:'model-fixed',rootUid:'unit-1',rootName:'Unit 1',entityUid:'cn1-unit-1',entityRevision:'cabinet-r1',displayName:'Unit 1 CN1'});
 assert.equal(cockpitAlarmTargetCurrent(target,catalog),true);
 for(const change of [{sceneRevision:'changed'},{instanceId:'other'},{modelVersionId:'other'},{rootUid:'other'}])assert.equal(cockpitAlarmTargetCurrent({...target,...change},catalog),false);
});
test('names and shared model identity cannot move an alarm to another installation or source',()=>{
 assert.equal(cockpitAlarmTarget(placement,record,{...context,objectRef:{...ref,ontobaseConnectionId:'other'}},bundle,dataset),null);
 assert.equal(cockpitAlarmTarget(placement,{...record,children:[{...cabinet,installationContextId:'installed-2',displayName:'Unit 1 CN1'}]},context,bundle,dataset),null);
 assert.equal(cockpitAlarmTarget(placement,{...record,children:[cabinet,cabinet]},context,bundle,dataset),null);
 assert.equal(cockpitAlarmTarget(placement,record,context,bundle,{...dataset,sourceKind:'live'}),null);
 assert.equal(cockpitAlarmTarget(placement,record,context,bundle,{...dataset,cabinet:'CT'}),null);
});
