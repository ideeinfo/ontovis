import assert from 'node:assert/strict';
import {test} from 'node:test';
import {ApiError} from '../src/api.ts';
import {canEditAssistantScene,openAssistantScene,verifyAssistantScene} from '../src/assistantScene.ts';

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
 assert.deepEqual(await openAssistantScene(client,project,target,signal),{scene:old,instance:null,terrain:null,imagery:null});
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
