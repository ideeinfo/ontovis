import test from 'node:test';
import assert from 'node:assert/strict';
import {cockpitFleet,cockpitTurbineIds,cockpitOverviewIds} from '../src/cockpitFleet.ts';
import {MOTION_MODEL_SHA} from '../src/motionProfiles.ts';
const project={projectCode:'P',ontobaseConnectionId:'C'},equipment=[{entityUid:'unit',objectScope:'installation'},{entityUid:'definition',objectScope:'definition'}];
const unit=(id,uid=null,modelVersionId='wind')=>({sceneModelInstanceId:id,modelVersionId,visible:true,rootBinding:uid?{objectRef:{...project,entityUid:uid}}:null});
const scene=(sceneId,instances)=>({sceneId,resourceRefs:[{modelVersionId:'wind',sha256:MOTION_MODEL_SHA},{modelVersionId:'sample',sha256:'unknown'}],snapshot:{instances}});
const catalog=(...scenes)=>({scenes:scenes.map(opened=>({opened})),equipment});
test('whole turbines count independently of cabinets, model names and synthetic samples',()=>{
 const s=scene('a',[unit('wind1','unit'),unit('static',null,'sample')]);s.snapshot.instances[1].displayName='风机';
 assert.deepEqual(cockpitTurbineIds(s),['wind1']);assert.deepEqual(cockpitFleet(catalog(s),project),{turbines:1,unboundTurbines:0,complete:true});
 assert.deepEqual(cockpitOverviewIds(s),['wind1']);
});
test('same installed turbine counts once across overlapping portfolios, unbound placements remain distinct',()=>{
 const a=scene('a',[unit('1','unit'),unit('2','unit'),unit('source-index-1')]),b=scene('b',[unit('1','unit'),unit('source-index-1')]);
 assert.deepEqual(cockpitFleet(catalog(a,b),project),{turbines:3,unboundTurbines:2,complete:true});
 a.snapshot.instances[2].visible=false;assert.equal(cockpitFleet(catalog(a,b),project).turbines,3);
});
test('cross-project and definition references never turn placements into verified installation identities',()=>{
 const s=scene('a',[unit('1','unit'),unit('2','definition')]);s.snapshot.instances[0].rootBinding.objectRef.projectCode='OTHER';
 assert.deepEqual(cockpitFleet(catalog(s),project),{turbines:2,unboundTurbines:2,complete:true});
});
test('missing scenes leave incomplete totals; other industries can still frame their visible models',()=>{
 const s=scene('a',[unit('cabinet',null,'sample')]),value=catalog(s);value.scenes.push({opened:null});
 assert.deepEqual(cockpitFleet(value,project),{turbines:0,unboundTurbines:0,complete:false});assert.deepEqual(cockpitOverviewIds(s),['cabinet']);
});
