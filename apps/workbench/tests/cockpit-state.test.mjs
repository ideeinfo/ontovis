import assert from 'node:assert/strict';
import test from 'node:test';
import {ApiError} from '../src/api.ts';
import {CockpitCatalogCache,interfaceScale,sceneIdentity,catalogIdentity,readCockpitCatalog} from '../src/cockpitState.ts';
const project={ontobaseConnectionId:'source',projectCode:'P'};
const equipment=[{entityUid:'u1',objectScope:'installation'},{entityUid:'u2',objectScope:'installation'},{entityUid:'definition',objectScope:'definition'}];
const scene=(ids)=>({snapshot:{instances:ids.map((uid,i)=>({sceneModelInstanceId:String(i),rootBinding:uid?{objectRef:{...project,entityUid:uid}}:null}))}});
test('interface scale uses available CSS space; 4K with OS 200% is not doubled',()=>{
 assert.equal(interfaceScale('auto',3840,2160),2);assert.equal(interfaceScale('auto',1920,1080),1);
 assert.equal(interfaceScale('auto',2880,1620),1.5);assert.equal(interfaceScale('auto',3840,1200),1);
 assert.equal(interfaceScale('2',406,800),2);assert.equal(interfaceScale('invalid',1920,1080),1);
});
test('counts distinct installed identities across overlapping scenes, not names/models',()=>{
 const a=scene(['u1','u1','u2',null,'definition']),b=scene(['u1']);
 assert.deepEqual(sceneIdentity(a,equipment,project),{uids:['u1','u2'],unresolved:2,representations:5});
 assert.deepEqual(catalogIdentity({scenes:[{opened:a},{opened:b}],equipment},project),{devices:2,unresolved:2,representations:6,complete:true});
});
test('cross-project bindings and missing scene snapshots never claim complete counts',()=>{
 const a=scene(['u1']);a.snapshot.instances[0].rootBinding.objectRef.projectCode='OTHER';
 assert.equal(sceneIdentity(a,equipment,project).unresolved,1);
 assert.equal(catalogIdentity({scenes:[{opened:a},{opened:null}],equipment},project).complete,false);
});
function fake(){return {project,epoch:1,revision:'s1',async request(path,body){
 if(path.endsWith('/scenes'))return {items:[{sceneId:'a',headRevision:'r1'}],snapshotRevision:'list1',nextCursor:null};
 if(path.endsWith('/equipment'))return {items:equipment,nextCursor:null,snapshotRevision:'eq1'};
 if(path.endsWith('/scenes/open'))return {...scene(['u1']),sceneId:'a',projectCode:'P',sceneRevision:'r1'};
 throw Error(path);
}};}
test('catalog follows authorized existing reads and exact scene revisions',async()=>{
 const api=fake(),value=await readCockpitCatalog(api,new AbortController().signal);
 assert.equal(value.scenes[0].opened.sceneRevision,'r1');assert.equal(value.equipment.length,3);
});
test('late read after a project switch is discarded',async()=>{
 const api=fake(),request=api.request;api.request=async(...args)=>{const result=await request(...args);api.epoch++;return result;};
 await assert.rejects(readCockpitCatalog(api,new AbortController().signal),{name:'AbortError'});
});
test('missing scene and revision mismatch remain visible gaps rather than empty assets',async()=>{
 const api=fake(),request=api.request;api.request=async(path,body)=>path.endsWith('/scenes/open')?{...scene(['u1']),sceneId:'a',projectCode:'P',sceneRevision:'r2'}:request(path,body);
 const value=await readCockpitCatalog(api,new AbortController().signal);assert.equal(value.scenes[0].opened,null);assert.equal(value.scenes[0].error.code,'SCENE_CHANGED');
});
test('catalog pagination changes and repeated cursors fail without stale mixed totals',async()=>{
 const api=fake();api.request=async()=>({items:[],snapshotRevision:'s',nextCursor:'repeat'});
 await assert.rejects(readCockpitCatalog(api,new AbortController().signal),{code:'COCKPIT_CATALOG_LIMIT'});
});

test('project revocation rejects the entire catalog instead of returning partial identities',async()=>{
 const api=fake(),request=api.request;api.request=async(path,body)=>{if(path.endsWith('/scenes/open'))throw new ApiError(403,'FORBIDDEN');return request(path,body);};
 await assert.rejects(readCockpitCatalog(api,new AbortController().signal),{status:403});
});
test('scene catalog revision cannot change between pages',async()=>{
 const api=fake(),request=api.request;let calls=0;api.request=async(path,body)=>path.endsWith('/scenes')?({items:[],snapshotRevision:'s'+(++calls),nextCursor:calls===1?'next':null}):request(path,body);
 await assert.rejects(readCockpitCatalog(api,new AbortController().signal),{code:'SCENE_CHANGED'});
});

test('automatic density tolerates subpixel observer rounding without crossing a whole-pixel boundary',()=>{
 assert.equal(interfaceScale('auto',3840.104,2159.896),2);assert.equal(interfaceScale('auto',2879.9,1619.9),1.5);
 assert.equal(interfaceScale('auto',3839,2160),1.5);assert.equal(interfaceScale('auto',2880,1619),1);
});

const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
test('scene cards arrive before slow equipment and snapshots, with honest incomplete totals',async()=>{
 const api=fake(),request=api.request,equipmentGate=deferred(),sceneGate=deferred(),updates=[],started=[];
 api.request=async(path,body)=>{started.push(path);if(path.endsWith('/equipment'))await equipmentGate.promise;if(path.endsWith('/scenes/open'))await sceneGate.promise;return request(path,body);};
 const reading=readCockpitCatalog(api,new AbortController().signal,{changed:value=>updates.push(value)});await tick();
 assert.equal(started.filter(path=>path.endsWith('/equipment')).length,1);assert.equal(updates[0].scenes[0].opened,null);
 assert.equal(updates[0].equipmentReady,false);assert.equal(catalogIdentity(updates[0],project).complete,false);
 sceneGate.resolve();await tick();assert.equal(updates.at(-1).scenes[0].opened.sceneRevision,'r1');
 assert.equal(updates[0].scenes[0].opened,null,'published snapshots cannot be mutated by later reads');
 equipmentGate.resolve();const result=await reading;assert.equal(result.loading,false);assert.equal(catalogIdentity(result,project).complete,true);
});
test('same-session cache shows immediately and revalidates directories without reopening unchanged scenes',async()=>{
 const api=fake(),request=api.request,calls=[];api.request=async(...args)=>{calls.push(args[0]);return request(...args);};
 const cache=new CockpitCatalogCache(api),signal=new AbortController().signal;
 await cache.read(signal,()=>{});calls.length=0;let immediate;
 const reading=cache.read(signal,value=>{immediate??=value;});assert.equal(immediate.scenes[0].opened.sceneRevision,'r1');await reading;
 assert.deepEqual(calls.sort(),['/api/workbench/equipment','/api/workbench/scenes']);
});
test('fresh heads and deletions replace cached snapshots, while failed scene reads retry',async()=>{
 const api=fake(),request=api.request,cache=new CockpitCatalogCache(api),signal=new AbortController().signal;let phase=0,opens=0;
 api.request=async(path,body)=>{
  if(path.endsWith('/scenes')&&phase)return {items:phase===3?[]:[{sceneId:'a',headRevision:'r2'}],snapshotRevision:'l2',nextCursor:null};
  if(path.endsWith('/scenes/open')){opens++;if(phase===1)throw new ApiError(409,'SCENE_CHANGED');if(phase===2)return {...scene(['u1']),sceneId:'a',projectCode:'P',sceneRevision:'r2'};}
  return request(path,body);
 };
 await cache.read(signal,()=>{});phase=1;let result=await cache.read(signal,()=>{});assert.equal(result.scenes[0].opened,null);assert.equal(result.scenes[0].error.code,'SCENE_CHANGED');
 phase=2;result=await cache.read(signal,()=>{});assert.equal(result.scenes[0].opened.sceneRevision,'r2');assert.equal(opens,3);
 phase=3;result=await cache.read(signal,()=>{});assert.equal(result.scenes.length,0);assert.equal(cache.peek().scenes.length,0);
});
test('logout, session revision and project changes make memory inaccessible and reject old cache readers',async()=>{
 for(const change of [api=>api.epoch++,api=>api.revision='s2',api=>api.project={...project,projectCode:'OTHER'}]){
  const api=fake(),cache=new CockpitCatalogCache(api),signal=new AbortController().signal;await cache.read(signal,()=>{});change(api);
  assert.equal(cache.peek(),null);await assert.rejects(cache.read(signal,()=>{}),{name:'AbortError'});
 }
});
test('revocation clears a warm cache even when no scene snapshot needs reopening',async()=>{
 const api=fake(),cache=new CockpitCatalogCache(api),signal=new AbortController().signal;await cache.read(signal,()=>{});
 api.request=async()=>{throw new ApiError(403,'FORBIDDEN');};await assert.rejects(cache.read(signal,()=>{}),{status:403});assert.equal(cache.peek(),null);
});
test('cancelling retains completed memory but late responses cannot publish; selected scenes get the next slot',async()=>{
 const api=fake(),request=api.request,gates=Array.from({length:5},deferred),opened=[],updates=[],abort=new AbortController();let priority='';
 api.request=async(path,body)=>{
  if(path.endsWith('/scenes'))return {items:gates.map((_,index)=>({sceneId:String(index),headRevision:'r1'})),snapshotRevision:'l1',nextCursor:null};
  if(path.endsWith('/scenes/open')){opened.push(body.sceneId);await gates[Number(body.sceneId)].promise;return {...scene(['u1']),sceneId:body.sceneId,projectCode:'P',sceneRevision:'r1'};}
  return request(path,body);
 };
 const reading=readCockpitCatalog(api,abort.signal,{priority:()=>priority,changed:value=>updates.push(value)});await tick();assert.deepEqual(opened,['0','1','2']);
 priority='4';gates[0].resolve();await tick();assert.deepEqual(opened,['0','1','2','4']);
 const count=updates.length;abort.abort();gates.forEach(g=>g.resolve());await assert.rejects(reading,{name:'AbortError'});assert.equal(updates.length,count);
});
