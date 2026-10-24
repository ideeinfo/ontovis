import test from 'node:test';import assert from 'node:assert/strict';
import {SceneLoadingTracker,sceneLoadingPlan,modelLoadingKey} from '../src/sceneLoading.ts';
const a={modelVersionId:'a',contentRevision:'a1',sha256:'sha-a'},b={modelVersionId:'b',contentRevision:'b1',sha256:'sha-b'};
const scene={instances:[{modelVersionId:'a'},{modelVersionId:'a'},{modelVersionId:'b'}],terrain:{terrainVersionId:'t',expectedContentRevision:'t1'},imagery:{imageryVersionId:'i',expectedContentRevision:'i1',expectedReportSha256:'ri',visible:true}};
test('loading counts one task per immutable model version, terrain and imagery; repeated instances and shared preview reuse it',()=>{
 const plan=sceneLoadingPlan(scene,[a,b],a);assert.equal(plan.length,4);assert.ok(plan.includes(modelLoadingKey(a)));
 assert.deepEqual(sceneLoadingPlan({...scene,instances:[...scene.instances].reverse()},[b,a],a),plan);
 assert.equal(sceneLoadingPlan(scene,[a,b],{...a,modelVersionId:'c'}).length,5);
});
test('resource revision changes restart the plan, while visibility and placement changes do not',()=>{
 const plan=sceneLoadingPlan(scene,[a,b]);assert.deepEqual(sceneLoadingPlan({...scene,imagery:{...scene.imagery,visible:false},instances:scene.instances.map(v=>({...v,position:[1,2,3]}))},[a,b]),plan);
 assert.notDeepEqual(sceneLoadingPlan({...scene,terrain:{...scene.terrain,expectedContentRevision:'t2'}},[a,b]),plan);
 assert.notDeepEqual(sceneLoadingPlan({...scene,imagery:{...scene.imagery,expectedReportSha256:'ri2'}},[a,b]),plan);
 assert.notDeepEqual(sceneLoadingPlan(scene,[{...a,contentRevision:'a2'},b]),plan);
});
test('out of order completions and duplicate callbacks never inflate progress or finish before the first draw',()=>{
 const changes=[],t=new SceneLoadingTracker(['a','b'],s=>changes.push(s));t.drawn();assert.equal(t.state().completed,0);
 t.done('b');t.done('b');t.done('unknown');assert.deepEqual(t.state(),{completed:1,total:3,stage:'resources'});
 t.done('a');assert.deepEqual(t.state(),{completed:2,total:3,stage:'display'});t.drawn();t.drawn();t.done('a');
 assert.deepEqual(t.state(),{completed:3,total:3,stage:'complete'});assert.equal(changes.length,4);
});
test('late metadata stays pending even after all known models are prepared',()=>{
 const keys=sceneLoadingPlan(scene,[a,b]),t=new SceneLoadingTracker(keys,()=>{});t.done(modelLoadingKey(a));t.done(modelLoadingKey(b));t.drawn();
 assert.equal(t.state().stage,'resources');assert.equal(t.state().completed,2);assert.equal(t.state().total,5);
 for(const key of keys)t.done(key);assert.equal(t.state().stage,'display');t.drawn();assert.equal(t.state().completed,5);
});
test('failure and cancellation reject late completion; a retry owns independent progress',()=>{
 for(const end of ['fail','cancel']){
  const t=new SceneLoadingTracker(['a','b'],()=>{});t.done('a');t[end]();const stopped=t.state();t.done('b');t.drawn();assert.deepEqual(t.state(),stopped);
  const retry=new SceneLoadingTracker(['a','b'],()=>{});assert.equal(retry.state().completed,0);retry.done('a');retry.done('b');retry.drawn();assert.equal(retry.state().stage,'complete');assert.deepEqual(t.state(),stopped);
 }
});
test('an empty scene still waits for a draw; a missing model reference remains a pending task',()=>{
 const t=new SceneLoadingTracker(sceneLoadingPlan({instances:[],terrain:null,imagery:null},[]),()=>{});assert.deepEqual(t.state(),{completed:0,total:1,stage:'display'});t.drawn();assert.equal(t.state().stage,'complete');
 const plan=sceneLoadingPlan({instances:[{modelVersionId:'missing'}]},[]);assert.deepEqual(plan,['missing-model:missing']);
});

test('same resources in a new open or metadata retry own a new completion identity',()=>{
 const keys=sceneLoadingPlan(scene,[a,b]),first=new SceneLoadingTracker(keys,()=>{},'scene:1:open1');for(const key of keys)first.done(key);first.drawn();
 const refresh=new SceneLoadingTracker(keys,()=>{},'scene:1:open2'),retry=new SceneLoadingTracker(keys,()=>{},'scene:1:retry1');
 assert.notEqual(refresh.identity,first.identity);assert.notEqual(retry.identity,refresh.identity);assert.equal(refresh.state().completed,0);assert.equal(first.state().stage,'complete');
});
