import assert from 'node:assert/strict';
import test from 'node:test';
import {ApiError} from '../src/api.ts';
import {interfaceScale,sceneIdentity,catalogIdentity,readCockpitCatalog} from '../src/cockpitState.ts';
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
 const api=fake();let calls=0;api.request=async()=>({items:[],snapshotRevision:'s'+(++calls),nextCursor:calls===1?'next':null});
 await assert.rejects(readCockpitCatalog(api,new AbortController().signal),{code:'SCENE_CHANGED'});
});

test('automatic density tolerates subpixel observer rounding without crossing a whole-pixel boundary',()=>{
 assert.equal(interfaceScale('auto',3840.104,2159.896),2);assert.equal(interfaceScale('auto',2879.9,1619.9),1.5);
 assert.equal(interfaceScale('auto',3839,2160),1.5);assert.equal(interfaceScale('auto',2880,1619),1);
});
