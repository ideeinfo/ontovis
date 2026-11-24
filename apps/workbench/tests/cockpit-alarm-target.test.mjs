import test from 'node:test';
import assert from 'node:assert/strict';
import {cockpitAlarmInstance,cockpitAlarmTarget,cockpitAlarmTargetCurrent} from '../src/cockpitAlarmTarget.ts';
import {registeredSimulationTarget} from '../src/simulatedAlarms.ts';

const project={projectCode:'project',ontobaseConnectionId:'connection'};
const root={entityUid:'unit-1',...project};
const instance={sceneModelInstanceId:'placed-1',modelVersionId:'model-fixed',displayName:'同名设备',visible:true,
 rootBinding:{objectRef:root},componentBindings:[]};
const second={...instance,sceneModelInstanceId:'placed-2',rootBinding:{objectRef:{...root,entityUid:'unit-2'}}};
const scene={summary:{sceneId:'scene-1'},opened:{sceneId:'scene-1',sceneRevision:'s-r1',snapshot:{instances:[second,instance]}}};
const catalog={scenes:[scene],equipment:[]};
const registration={datasetRevision:'fixed:1',sceneId:'scene-1',instanceId:'placed-1',rootUid:'unit-1',rootName:'Unit 1',
 entityUid:'cn1-unit-1',entityRevision:'cabinet-r1',displayName:'Unit 1 CN1'};

test('a registered simulated alarm resolves the exact saved instance and installed cabinet',()=>{
 const target=cockpitAlarmTarget(catalog,project,registration);
 assert.deepEqual(target,{sceneId:'scene-1',sceneRevision:'s-r1',instanceId:'placed-1',modelVersionId:'model-fixed',
   rootUid:'unit-1',rootName:'Unit 1',entityUid:'cn1-unit-1',entityRevision:'cabinet-r1',displayName:'Unit 1 CN1'});
 assert.equal(cockpitAlarmTargetCurrent(target,catalog),true);
 assert.equal(cockpitAlarmInstance(target,scene.opened),instance);
 for(const change of [{sceneRevision:'changed'},{instanceId:'other'},{modelVersionId:'other'},{rootUid:'other'}]){
  assert.equal(cockpitAlarmTargetCurrent({...target,...change},catalog),false);
 }
});

test('alarm location refuses an unregistered, hidden or reassigned instance',()=>{
 assert.equal(cockpitAlarmTarget(catalog,project,undefined),null);
 assert.equal(cockpitAlarmTarget(catalog,project,{...registration,instanceId:'placed-2'}),null);
 assert.equal(cockpitAlarmTarget(catalog,{...project,projectCode:'other'},registration),null);
 const hidden={...instance,visible:false};
 const modified={scenes:[{...scene,opened:{...scene.opened,snapshot:{instances:[second,hidden]}}}]};
 assert.equal(cockpitAlarmTarget(modified,project,registration),null);
});

test('separate alarm registrations do not follow the selected or same-name turbine',()=>{
 const other={...registration,instanceId:'placed-2',rootUid:'unit-2',entityUid:'cn2-unit-2'};
 const dataset={datasetId:'sim:1',datasetRevision:'fixed:1'};
 const catalogue={targets:{'sim:1':registration,'sim:2':other}};
 assert.equal(cockpitAlarmTarget(catalog,project,registeredSimulationTarget(catalogue,dataset)).instanceId,'placed-1');
 assert.equal(cockpitAlarmTarget(catalog,project,registeredSimulationTarget(catalogue,{...dataset,datasetId:'sim:2'})).instanceId,'placed-2');
 assert.equal(registeredSimulationTarget(catalogue,{...dataset,datasetRevision:'new'}),undefined);
});
