import assert from 'node:assert/strict';
import test from 'node:test';
import {ApiError,failureMessage,WorkbenchApi} from '../src/api.ts';
import {SceneApi} from '../src/sceneApi.ts';
import {LegacySceneEntryReader,legacyEntryInstance} from '../src/legacySceneEntry.ts';

const json=value=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json'}});
const deferred=()=>{let resolve;const promise=new Promise(done=>{resolve=done;});return {promise,resolve};};
const target=(id='A')=>({sceneId:`scene-${id}`,sceneRevision:`current-${id}`,registeredSceneRevision:`registered-${id}`,sceneModelInstanceId:`instance-${id}`});
const registered=(id='A')=>({sessionRevision:'session:1',migrated:true,legacyReadOnly:true,available:true,entry:target(id),reason:null});
const notRegistered=()=>({sessionRevision:'session:1',migrated:false,legacyReadOnly:false,available:false,entry:null,reason:'NOT_REGISTERED'});

test('default and old upload entries use only the protected POST path and preserve their explicit source',async()=>{
  const calls=[],transport=new WorkbenchApi(async(path,options)=>{calls.push({path,options});return json(registered());});
  transport.session('session:1');const reader=new LegacySceneEntryReader(new SceneApi(transport));
  assert.deepEqual(await reader.read(null),target());assert.deepEqual(await reader.read('exact-old-version'),target());
  assert.deepEqual(calls.map(({path,options})=>({path,method:options.method,body:JSON.parse(options.body)})),[
    {path:'/api/workbench/scenes/legacy-migration/entry',method:'POST',body:{expectedSessionRevision:'session:1'}},
    {path:'/api/workbench/scenes/legacy-migration/entry',method:'POST',body:{sourceKind:'uploaded_version',sourceKey:'exact-old-version',expectedSessionRevision:'session:1'}},
  ]);
  assert.ok(calls.every(({options})=>options.signal instanceof AbortSignal));
});

test('only an explicitly unregistered writable legacy source permits the old route',async()=>{
  let value=notRegistered();const reader=new LegacySceneEntryReader({legacyEntry:async()=>value});
  assert.equal(await reader.read(null),null);
  for(const change of [{legacyReadOnly:true},{migrated:true},{reason:'TARGET_INSTANCE_MISSING'},
    {reason:null},{available:true},{entry:target()}]) {
    value={...notRegistered(),...change};
    await assert.rejects(reader.read(null),error=>error instanceof ApiError&&error.code==='LEGACY_SCENE_ENTRY_UNAVAILABLE');
  }
});

test('an active missing target or failed entry read never produces an old route or asks for a scene list',async()=>{
  const calls=[];let reply=json({...registered(),available:false,entry:null,reason:'TARGET_INSTANCE_MISSING'});
  const transport=new WorkbenchApi(async(path)=>{calls.push(path);return reply;});transport.session('session:1');
  const reader=new LegacySceneEntryReader(new SceneApi(transport));
  await assert.rejects(reader.read('old-version'),error=>error.code==='LEGACY_SCENE_ENTRY_UNAVAILABLE');
  reply=new Response('{"code":"SOURCE_UNAVAILABLE"}',{status:502});
  await assert.rejects(reader.read(null),error=>error.code==='SOURCE_UNAVAILABLE');
  assert.deepEqual(calls,Array(2).fill('/api/workbench/scenes/legacy-migration/entry'));
});

test('A then B preview cancels A and rejects its late response even when transport ignores cancellation',async()=>{
  const waiting=[deferred(),deferred()],calls=[],opened=[];
  const reader=new LegacySceneEntryReader({legacyEntry:(body,signal)=>{calls.push({body,signal});return waiting[calls.length-1].promise;}});
  const a=reader.read('old-A').then(value=>opened.push(value));
  const rejected=assert.rejects(a,error=>error.name==='AbortError');
  const b=reader.read('old-B').then(value=>opened.push(value));
  assert.equal(calls[0].signal.aborted,true);assert.equal(calls[1].signal.aborted,false);
  waiting[1].resolve(registered('B'));await b;waiting[0].resolve(registered('A'));await rejected;
  assert.deepEqual(opened,[target('B')]);
});

test('leaving or clearing the view cancels a pending lookup without opening its late scene',async()=>{
  const waiting=deferred();let signal;
  const reader=new LegacySceneEntryReader({legacyEntry:(_body,value)=>{signal=value;return waiting.promise;}});
  const pending=reader.read(null);reader.cancel();assert.equal(signal.aborted,true);
  waiting.resolve(registered());await assert.rejects(pending,error=>error.name==='AbortError');
});

test('session invalidation prevents an entry response from reopening an earlier user scene',async()=>{
  const waiting=deferred(),transport=new WorkbenchApi(async()=>waiting.promise);transport.session('session:1');
  const reader=new LegacySceneEntryReader(new SceneApi(transport)),pending=reader.read(null);transport.invalidate();
  waiting.resolve(json(registered()));await assert.rejects(pending,error=>error.name==='AbortError');
});

test('opening a registered entry pins its current scene revision and selects the exact instance beyond the first row',async()=>{
  const calls=[],entry=target(),opened={sceneId:entry.sceneId,sceneRevision:entry.sceneRevision,headRevision:'newer-head',
    snapshot:{instances:[{sceneModelInstanceId:'unrelated-first',modelVersionId:'newer-model'},
      {sceneModelInstanceId:entry.sceneModelInstanceId,modelVersionId:'old-source-fixed-version'}]},sessionRevision:'session:1'};
  const transport=new WorkbenchApi(async(path,options)=>{calls.push({path,body:JSON.parse(options.body)});return json(opened);});
  transport.session('session:1');const api=new SceneApi(transport),value=await api.open(entry.sceneId,entry.sceneRevision);
  assert.equal(legacyEntryInstance(value,entry),'instance-A');
  assert.deepEqual(calls,[{path:'/api/workbench/scenes/open',body:{sceneId:'scene-A',sceneRevision:'current-A',expectedSessionRevision:'session:1'}}]);
  assert.notEqual(entry.sceneRevision,entry.registeredSceneRevision);assert.equal(value.headRevision,'newer-head');
});

test('changed scene identity, unexpected revision and absent or repeated target instances fail without selecting another',()=>{
  const entry=target(),value={sceneId:entry.sceneId,sceneRevision:entry.sceneRevision,snapshot:{instances:[{sceneModelInstanceId:entry.sceneModelInstanceId}]}};
  for(const changed of [{...value,sceneId:'other-scene'},{...value,sceneRevision:'other-head'},
    {...value,snapshot:{instances:[{sceneModelInstanceId:'other-instance'}]}},
    {...value,snapshot:{instances:[...value.snapshot.instances,...value.snapshot.instances]}}])
    assert.throws(()=>legacyEntryInstance(changed,entry),error=>error.code==='LEGACY_SCENE_ENTRY_UNAVAILABLE');
});

test('unavailable entry messages offer a concise reread in both languages',()=>{
  const error=new ApiError(409,'LEGACY_SCENE_ENTRY_UNAVAILABLE');
  assert.match(failureMessage(error,'zh'),/场景暂不可用.*重新读取/);assert.match(failureMessage(error,'en'),/scene.*unavailable.*Reload/);
});
