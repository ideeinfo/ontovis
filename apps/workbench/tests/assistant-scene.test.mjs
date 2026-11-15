import assert from 'node:assert/strict';
import {test} from 'node:test';
import {openAssistantScene} from '../src/assistantScene.ts';

const target={sceneId:'s1',sceneRevision:'scene:earlier',title:'Saved scene'};
const old={...target,projectCode:'P',headRevision:'scene:latest',snapshot:{terrain:null}};

test('assistant preview reads the exact saved revision, including an older saved scene',async()=>{
 const calls=[];
 const client={open:async (...args)=>{calls.push(args);return old;}};
 const signal=new AbortController().signal;
 assert.deepEqual(await openAssistantScene(client,'P',target,signal),{scene:old,terrain:null,imagery:null});
 assert.deepEqual(calls,[[target.sceneId,target.sceneRevision,signal]]);
});

test('assistant preview rejects replacement revisions, another project and changed map resources',async()=>{
 const signal=new AbortController().signal;
 for(const [patch,code] of [[{sceneRevision:'scene:latest'},'SCENE_CHANGED'],[{projectCode:'Other'},'PROJECT_SCOPE_MISMATCH']]){
  await assert.rejects(openAssistantScene({open:async()=>({...old,...patch})},'P',target,signal),{code});
 }
 const client={open:async()=>({...old,snapshot:{terrain:null,imagery:{imageryVersionId:'image',expectedContentRevision:'old',expectedReportSha256:'hash'}}}),
  imageryVersion:async()=>({imageryVersionId:'image',contentRevision:'new',expectedReportSha256:'hash'})};
 await assert.rejects(openAssistantScene(client,'P',target,signal),{code:'RESOURCE_CHANGED'});
});

test('leaving the assistant preview discards the late result and skips resource reads',async()=>{
 const abort=new AbortController();
 const client={open:async()=>{abort.abort();return {...old,snapshot:{terrain:{terrainVersionId:'id'}}};},
  version:()=>assert.fail('cancelled read requested resources')};
 await assert.rejects(openAssistantScene(client,'P',target,abort.signal),{name:'AbortError'});
});
