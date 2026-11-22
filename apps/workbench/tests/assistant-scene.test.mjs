import assert from 'node:assert/strict';
import {test} from 'node:test';
import {ApiError} from '../src/api.ts';
import {assistantInstanceOptions,canEditAssistantScene,openAssistantScene,verifyAssistantScene} from '../src/assistantScene.ts';

const project={projectCode:'P',ontobaseConnectionId:'source'};
const target={sceneId:'s1',sceneRevision:'scene:earlier',title:'Saved scene'};
const old={...target,projectCode:'P',headRevision:'scene:latest',snapshot:{terrain:null}};
const instanceTarget={instanceId:'a',modelVersionId:'model-a',equipmentUid:'device-a'};
const fixedTarget={...target,instance:instanceTarget};
const savedInstance={sceneModelInstanceId:'a',displayName:'Device',modelVersionId:'model-a',visible:false,
 rootBinding:{objectRef:{...project,entityUid:'device-a'}}};

test('assistant preview reads the exact saved revision, including an older saved scene',async()=>{
 const calls=[];
 const client={open:async (...args)=>{calls.push(args);return old;}};
 const signal=new AbortController().signal;
 assert.deepEqual(await openAssistantScene(client,project,target,signal),{scene:old,instance:null,modelInstances:[],terrain:null,imagery:null});
 assert.deepEqual(calls,[[target.sceneId,target.sceneRevision,signal]]);
});

test('assistant preview rejects replacement revisions, another project and changed map resources',async()=>{
 const signal=new AbortController().signal;
 for(const [patch,code] of [[{sceneRevision:'scene:latest'},'SCENE_CHANGED'],[{projectCode:'Other'},'PROJECT_SCOPE_MISMATCH']]){
  await assert.rejects(openAssistantScene({open:async()=>({...old,...patch})},project,target,signal),{code});
 }
 const client={open:async()=>({...old,snapshot:{terrain:null,imagery:{imageryVersionId:'image',expectedContentRevision:'old',expectedReportSha256:'hash'}}}),
  imageryVersion:async()=>({imageryVersionId:'image',contentRevision:'new',expectedReportSha256:'hash'})};
 await assert.rejects(openAssistantScene(client,project,target,signal),{code:'RESOURCE_CHANGED'});
});

test('leaving the assistant preview discards the late result and skips resource reads',async()=>{
 const abort=new AbortController();
 const client={open:async()=>{abort.abort();return {...old,snapshot:{terrain:{terrainVersionId:'id'}}};},
  version:()=>assert.fail('cancelled read requested resources')};
 await assert.rejects(openAssistantScene(client,project,target,abort.signal),{name:'AbortError'});
});

test('configuration preview locates its exact instance even if another has the same name',async()=>{
 const other={...savedInstance,sceneModelInstanceId:'b',visible:true};
 const scene={...old,snapshot:{terrain:null,instances:[other,savedInstance]},resourceRefs:[{modelVersionId:'model-a'}]};
 const signal=new AbortController().signal;
 const client={open:async (id,revision)=>{
  assert.equal(id,fixedTarget.sceneId);
  assert.equal(revision,fixedTarget.sceneRevision);
  return scene;
 }};
 assert.equal((await openAssistantScene(client,project,fixedTarget,signal)).instance,savedInstance);
 assert.equal(savedInstance.visible,false);
});

test('configuration location rejects changed bindings, instances and model references before reading resources',async()=>{
 const signal=new AbortController().signal;
 const changedRef=patch=>({...savedInstance,rootBinding:{objectRef:{...savedInstance.rootBinding.objectRef,...patch}}});
 for(const instances of [[],[savedInstance,savedInstance],[{...savedInstance,modelVersionId:'other-model'}],
  [{...savedInstance,rootBinding:null}],[changedRef({entityUid:'other-device'})],
  [changedRef({projectCode:'Other'})],[changedRef({ontobaseConnectionId:'other-source'})]]){
  const scene={...old,snapshot:{terrain:{terrainVersionId:'t'},instances},resourceRefs:[{modelVersionId:'model-a'}]};
  const client={open:async()=>scene,version:()=>assert.fail('invalid binding requested resources')};
  await assert.rejects(openAssistantScene(client,project,fixedTarget,signal),{status:409,code:'SCENE_INSTANCE_CHANGED'});
 }
 const scene={...old,snapshot:{terrain:{terrainVersionId:'t'},instances:[savedInstance]},resourceRefs:[]};
 const client={open:async()=>scene,version:()=>assert.fail('invalid model requested resources')};
 await assert.rejects(openAssistantScene(client,project,fixedTarget,signal),{status:409,code:'SCENE_INSTANCE_CHANGED'});
});

test('configuration location never falls back after a denied or deleted saved scene',async()=>{
 const signal=new AbortController().signal;
 for(const [status,code] of [[403,'PROJECT_FORBIDDEN'],[410,'SCENE_DELETED']]){
  const client={open:async()=>{throw new ApiError(status,code);},version:()=>assert.fail('unavailable scene requested resources')};
  await assert.rejects(openAssistantScene(client,project,fixedTarget,signal),{status,code});
 }
});

test('model use opens the recorded revision and selects all instances of that exact version',async()=>{
 const modelUse={...target,modelVersionId:'model-a'};
 const unbound={...savedInstance,sceneModelInstanceId:'c',rootBinding:null};
 const replacement={...savedInstance,sceneModelInstanceId:'b',modelVersionId:'model-new'};
 const scene={...old,snapshot:{terrain:null,instances:[replacement,unbound,savedInstance]},
  resourceRefs:[{modelVersionId:'model-a'},{modelVersionId:'model-new'}]};
 const client={open:async(id,revision)=>{
  assert.equal(id,target.sceneId);
  assert.equal(revision,target.sceneRevision);
  return scene;
 }};
 const signal=new AbortController().signal;
 assert.deepEqual((await openAssistantScene(client,project,modelUse,signal)).modelInstances,[unbound,savedInstance]);
 assert.equal(canEditAssistantScene({...scene,headRevision:scene.sceneRevision,capabilities:{canWrite:true}},'P',modelUse),false);
 for(const patch of [{resourceRefs:[]},{snapshot:{terrain:{terrainVersionId:'t'},instances:[replacement]}}]){
  await assert.rejects(openAssistantScene({open:async()=>({...scene,...patch}),
   version:()=>assert.fail('invalid use requested map resources')},project,modelUse,signal),{code:'SCENE_INSTANCE_CHANGED'});
 }
 await assert.rejects(openAssistantScene({open:async()=>{throw new ApiError(403,'PROJECT_FORBIDDEN');}},
  project,modelUse,signal),{status:403,code:'PROJECT_FORBIDDEN'});
});

test('the editor opens only the exact writable head in the active project',()=>{
 const current={...old,headRevision:old.sceneRevision,capabilities:{canWrite:true}};
 assert.equal(canEditAssistantScene(current,'P',target),true);
 assert.equal(canEditAssistantScene(current,'P',fixedTarget),false);
 for(const changed of [
  {...current,headRevision:'scene:new-head'},
  {...current,sceneId:'another-scene'},
  {...current,sceneRevision:'scene:new-head',headRevision:'scene:new-head'},
  {...current,projectCode:'Other'},
  {...current,capabilities:{canWrite:false}},
 ])assert.equal(canEditAssistantScene(changed,'P',target),false);
 assert.throws(()=>verifyAssistantScene({...current,sceneId:'another-scene'},'P',target),{code:'SCENE_CHANGED'});
 assert.throws(()=>verifyAssistantScene(current,'Other',target),{code:'PROJECT_SCOPE_MISMATCH'});
});

test('instance search accepts name, position number or saved identity and distinguishes duplicates after filtering',()=>{
 const first={...savedInstance,sceneModelInstanceId:'11111111-first',displayName:'机位组 · A01'};
 const second={...first,sceneModelInstanceId:'22222222-second',visible:false};
 const third={...first,sceneModelInstanceId:'33333333-third',displayName:'机位组 · A02'};
 const instances=[first,second,third];
 assert.equal(assistantInstanceOptions(instances,' 机位 Ａ０１ ').length,2);
 assert.deepEqual(assistantInstanceOptions(instances,'a01 22222222'),[{instance:second,display:'机位组 · A01 · 22222222'}]);
 assert.deepEqual(assistantInstanceOptions(instances,'A03'),[]);
 assert.deepEqual(assistantInstanceOptions(instances).map(option=>option.instance),instances);
 const samePrefix={...first,sceneModelInstanceId:first.sceneModelInstanceId.slice(0,8)+'-another'};
 assert.deepEqual(assistantInstanceOptions([first,samePrefix]).map(option=>option.display),
  [first,samePrefix].map(instance=>instance.displayName+' · '+instance.sceneModelInstanceId));
 assert.equal(second.visible,false);
});
