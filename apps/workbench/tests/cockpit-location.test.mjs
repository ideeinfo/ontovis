import assert from 'node:assert/strict';
import test from 'node:test';
import {cockpitInspectionScene,cockpitLocationCurrent,cockpitPickedObject,cockpitParentPath,readCockpitLocation,retryCockpitRead} from '../src/cockpitLocation.ts';
import {ApiError} from '../src/api.ts';
import {sceneLoadingPlan,sceneLoadingIdentity,scenePreparationStatus,modelLoadingKey,SceneLoadingTracker} from '../src/sceneLoading.ts';
const ref={entityUid:'part',projectCode:'project',ontobaseConnectionId:'source'};
const request={sceneId:'scene',sceneRevision:'r1',contextEpoch:'epoch',selectedObjectRef:ref,representationChoice:{sceneModelInstanceId:'instance',modelVersionId:'model'}};
const context={item:{entityUid:'part',entityRevision:'part-r1'},ancestors:{path:[{object:{entityUid:'parent'}},{object:{entityUid:'root'}},{object:{entityUid:'outside'}}]}};
const located=()=>({sceneId:'scene',sceneRevision:'r1',contextEpoch:'epoch',selectedObject:{objectRef:ref,entityRevision:'part-r1'},status:'located',mode:'direct',sceneModelInstanceId:'instance',modelVersionId:'model',componentKeys:['ct'],worldBounds:[[0,0,0],[2,3,4]]});
test('location requires the same scene, request, engineering revision and fixed representation',()=>{
 assert.equal(cockpitLocationCurrent(located(),request,context),true);
 for(const [field,value] of [['sceneId','other'],['sceneRevision','r2'],['contextEpoch','old'],['sceneModelInstanceId','other'],['modelVersionId','replacement'],['worldBounds',null],['worldBounds',[[0,0,0],[NaN,2,3]]],['componentKeys',['ct','ct']]])assert.equal(cockpitLocationCurrent({...located(),[field]:value},request,context),false);
 for(const field of ['entityUid','projectCode','ontobaseConnectionId'])assert.equal(cockpitLocationCurrent({...located(),selectedObject:{...located().selectedObject,objectRef:{...ref,[field]:'other'}}},request,context),false);
 assert.equal(cockpitLocationCurrent({...located(),selectedObject:{...located().selectedObject,entityRevision:'part-r2'}},request,context),false);
});
test('ancestor geometry retains its status and unavailable geometry does not invent bounds',()=>{
 assert.equal(cockpitLocationCurrent({...located(),mode:'ancestor'},request,context),true);
 const value={...located(),status:'unavailable',mode:null,sceneModelInstanceId:null,modelVersionId:null,worldBounds:null,componentKeys:[]};
 assert.equal(cockpitLocationCurrent(value,request,context),true);assert.equal(value.worldBounds,null);
});
test('reverse model selection uses unique project-scoped snapshot bindings only',()=>{
 const instance={...request.representationChoice,rootBinding:{objectRef:{...ref,entityUid:'root'}},componentBindings:[{objectRef:ref,componentKeys:['ct']}]},pick={...request.representationChoice,componentKey:'ct'};
 assert.equal(cockpitPickedObject(instance,pick),'part');
 for(const changed of [{...pick,modelVersionId:'old'},{...pick,sceneModelInstanceId:'other'},{...pick,componentKey:'unbound'}])assert.equal(cockpitPickedObject(instance,changed),null);
 assert.equal(cockpitPickedObject({...instance,componentBindings:[...instance.componentBindings,...instance.componentBindings]},pick),null);
 assert.equal(cockpitPickedObject({...instance,componentBindings:[{objectRef:{...ref,projectCode:'other'},componentKeys:['ct']}]},pick),null);
});
test('model-picked descendants open their actual parent path without escaping the selected equipment',()=>{
 assert.deepEqual(cockpitParentPath(context,'root'),['root','parent']);
 assert.deepEqual(cockpitParentPath(context,'missing'),[]);
 assert.deepEqual(cockpitParentPath({...context,item:{entityUid:'root'}},'root'),['root']);
});

test('context validation and spatial lookup start together; location still waits for both revisions',async()=>{
 let contextDone,locationDone;const calls=[];
 const client={objectContext:(uid,expected,signal)=>{calls.push(['context',uid,signal]);return new Promise(resolve=>contextDone=resolve);},locate:(value,signal)=>{calls.push(['locate',value,signal]);return new Promise(resolve=>locationDone=resolve);}};
 const signal=new AbortController().signal,pending=readCockpitLocation(client,request,signal);
 assert.equal(calls.length,2);assert.equal(calls[0][1],'part');assert.equal(calls[1][1],request);assert.ok(calls.every(call=>call[2]===signal));
 contextDone({...context,objectRef:ref});locationDone(located());assert.deepEqual(await pending,located());
});
test('parallel focus rejects changed engineering revisions and aborted late replies',async()=>{
 const client={objectContext:async()=>({...context,objectRef:ref}),locate:async()=>({...located(),selectedObject:{...located().selectedObject,entityRevision:'new'}})};
 await assert.rejects(readCockpitLocation(client,request,new AbortController().signal),{code:'ENGINEERING_CHANGED'});
 const abort=new AbortController();abort.abort();
 await assert.rejects(readCockpitLocation({...client,locate:async()=>located()},request,abort.signal),{name:'AbortError'});
});

test('alarm focus revalidates the cabinet revision shown on its card',async()=>{
 const client={objectContext:async()=>({...context,objectRef:ref}),locate:async()=>located()};
 await assert.rejects(readCockpitLocation(client,request,new AbortController().signal,'old'),{code:'ENGINEERING_CHANGED'});
 assert.equal((await readCockpitLocation(client,request,new AbortController().signal,'part-r1')).status,'located');
});

const modelRef={modelAssetId:'compressor-asset',modelVersionId:'detail',contentRevision:'detail:1',sha256:'b'.repeat(64)};
const appearanceRef={...modelRef,modelVersionId:'model',contentRevision:'outside:1',sha256:'a'.repeat(64)};
const instance={sceneModelInstanceId:'instance',modelVersionId:'model',visible:true,placement:{position:{xM:12,zM:34},headingDeg:71},rootBinding:{objectRef:{...ref,entityUid:'root'}},componentBindings:[{objectRef:{...ref,entityUid:'shell'},componentKeys:['outer-key']}]};
const detail=()=>({sourceModelVersionId:'model',instance:{...structuredClone(instance),modelVersionId:'detail',componentBindings:[{objectRef:ref,componentKeys:['inner-key']}]},modelRef,
 model:{...modelRef,state:'ready',canPlace:true,calibrationState:'verified',representationType:'detailed',components:[{componentKey:'inner-key'}]}});
const switched=()=>({...located(),modelVersionId:'detail',componentKeys:['inner-key'],representation:detail()});
const opened=()=>({sceneId:'scene',sceneRevision:'r1',headRevision:'r1',resourceRefs:[appearanceRef],snapshot:{instances:[structuredClone(instance),{...structuredClone(instance),sceneModelInstanceId:'second'}]}});

test('generic server representation is accepted only for an inspection request with matching fixed identities',()=>{
 const inspection={...request,preferDetailed:true};
 assert.equal(cockpitLocationCurrent(switched(),inspection,context),true);
 assert.equal(cockpitLocationCurrent(switched(),request,context),false);
 for(const patch of [{sourceModelVersionId:'old'},{instance:{...detail().instance,sceneModelInstanceId:'other'}},{modelRef:{...modelRef,sha256:'stale'}},{model:{...detail().model,representationType:'appearance'}},{model:{...detail().model,calibrationState:'unverified'}}]){
  assert.equal(cockpitLocationCurrent({...switched(),representation:{...detail(),...patch}},inspection,context),false);
 }
 assert.equal(cockpitLocationCurrent({...switched(),contextEpoch:'old'},inspection,context),false);
});

test('runtime inspection preserves saved pose and installation identity, uses detail bindings, and replaces only one instance',()=>{
 const source=opened(),before=structuredClone(source),display=cockpitInspectionScene(source,source.snapshot.instances[0],detail());
 assert.deepEqual(source,before);
 assert.deepEqual(display.snapshot.instances[0].placement,instance.placement);
 assert.deepEqual(display.snapshot.instances[0].rootBinding,instance.rootBinding);
 assert.deepEqual(display.snapshot.instances[1],source.snapshot.instances[1]);
 assert.equal(display.snapshot.instances[0].modelVersionId,'detail');
 assert.equal(cockpitPickedObject(display.snapshot.instances[0],{sceneModelInstanceId:'instance',modelVersionId:'detail',componentKey:'inner-key'}),'part');
 assert.equal(cockpitPickedObject(display.snapshot.instances[0],{sceneModelInstanceId:'instance',modelVersionId:'detail',componentKey:'outer-key'}),null);
 assert.equal(cockpitInspectionScene(source,instance,null),source);
 assert.deepEqual(cockpitInspectionScene(source,instance,null).snapshot.instances[0],instance);
});

test('representation payload cannot substitute the root device or overwrite a known fixed resource',()=>{
 assert.throws(()=>cockpitInspectionScene(opened(),instance,{...detail(),instance:{...detail().instance,rootBinding:{objectRef:{...ref,entityUid:'wrong-root'}}}}),{code:'ENGINEERING_CHANGED'});
 const source=opened();source.resourceRefs.push({...modelRef,sha256:'changed'});
 assert.throws(()=>cockpitInspectionScene(source,instance,detail()),{code:'RESOURCE_CHANGED'});
});

test('loading plan accounts for the inspected detail and the other appearances, then completes after drawing',()=>{
 const source=opened(),display=cockpitInspectionScene(source,instance,detail()),plan=sceneLoadingPlan(display.snapshot,display.resourceRefs);
 assert.deepEqual(plan.sort(),[modelLoadingKey(appearanceRef),modelLoadingKey(modelRef)].sort());
 const tracker=new SceneLoadingTracker(plan,()=>{});
 tracker.done(modelLoadingKey(appearanceRef));assert.equal(tracker.state().stage,'resources');
 tracker.done(modelLoadingKey(modelRef));assert.equal(tracker.state().stage,'display');
 tracker.drawn();assert.equal(tracker.state().stage,'complete');
 assert.equal(sceneLoadingPlan(source.snapshot,source.resourceRefs).length,1);
});
test('alarm target changes on the same fixed detailed model retain prepared resource identity',()=>{
 const source=opened(),first=cockpitInspectionScene(source,instance,detail());
 const identity=display=>sceneLoadingIdentity(sceneLoadingPlan(display.snapshot,display.resourceRefs),JSON.stringify([
  'scene:r1',0,'login','project',display.snapshot.instances.map(item=>[item.sceneModelInstanceId,item.modelVersionId])]));
 const prepared={key:identity(first),state:'ready'};
 const next=detail();next.instance.componentBindings.push({objectRef:{...ref,entityUid:'another-part'},componentKeys:['another-key']});
 const refreshed=cockpitInspectionScene(source,instance,next);
 assert.equal(identity(first),identity(refreshed));
 assert.equal(scenePreparationStatus(identity(refreshed),prepared),'ready');
 assert.deepEqual(refreshed.snapshot.instances[0].placement,first.snapshot.instances[0].placement);
 const revised=detail();revised.modelRef={...modelRef,contentRevision:'detail:2',sha256:'c'.repeat(64)};
 revised.model={...revised.model,...revised.modelRef};
 const changed=cockpitInspectionScene(source,instance,revised);
 assert.notEqual(identity(changed),prepared.key);
 assert.equal(scenePreparationStatus(identity(changed),prepared),'loading');
});

const settle=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
test('cockpit read recovers transient source failures after bounded waits',async t=>{
 t.mock.timers.enable({apis:['setTimeout','Date']});let calls=0;const api={epoch:1,revision:'r1'};
 const pending=retryCockpitRead(api,async()=>{calls++;if(calls<3)throw new ApiError(calls===1?502:503,'SOURCE_UNAVAILABLE');return 'current';},new AbortController().signal);
 await settle();assert.equal(calls,1);t.mock.timers.tick(999);await settle();assert.equal(calls,1);
 t.mock.timers.tick(1);await settle();assert.equal(calls,2);t.mock.timers.tick(3000);await settle();
 assert.equal(await pending,'current');assert.equal(calls,3);
});
test('persistent cockpit read failure stops after three retries',async t=>{
 t.mock.timers.enable({apis:['setTimeout','Date']});let calls=0;
 const pending=retryCockpitRead({epoch:1,revision:'r1'},async()=>{calls++;throw new ApiError(503,'SOURCE_UNAVAILABLE');},new AbortController().signal);
 const failure=assert.rejects(pending,{status:503,code:'SOURCE_UNAVAILABLE'});
 await settle();for(const delay of [1000,3000,6000]){t.mock.timers.tick(delay);await settle();}
 await failure;t.mock.timers.tick(60000);await settle();assert.equal(calls,4);
});
test('permission, version, invalid payload and non-transient errors never retry',async t=>{
 t.mock.timers.enable({apis:['setTimeout','Date']});
 for(const [status,code] of [[401,'SESSION_EXPIRED'],[403,'FORBIDDEN'],[409,'ENGINEERING_CHANGED'],[422,'INVALID_REQUEST'],[500,'SOURCE_UNAVAILABLE'],[502,'RESOURCE_CHANGED']]){
  let calls=0;const error=new ApiError(status,code);
  await assert.rejects(retryCockpitRead({epoch:1,revision:'r1'},async()=>{calls++;throw error;},new AbortController().signal),e=>e===error);
  t.mock.timers.tick(60000);await settle();assert.equal(calls,1);
 }
});
test('leaving an equipment selection cancels scheduled recovery without another read',async t=>{
 t.mock.timers.enable({apis:['setTimeout','Date']});const abort=new AbortController();let calls=0;
 const pending=retryCockpitRead({epoch:1,revision:'r1'},async()=>{calls++;throw new ApiError(503,'SOURCE_UNAVAILABLE');},abort.signal);
 const failure=assert.rejects(pending,{name:'AbortError'});await settle();abort.abort();await failure;
 t.mock.timers.tick(60000);await settle();assert.equal(calls,1);
});
test('a project or login change cannot dispatch an old scheduled read',async t=>{
 t.mock.timers.enable({apis:['setTimeout','Date']});
 for(const change of [api=>api.epoch++,api=>api.revision='r2']){
  const api={epoch:1,revision:'r1'};let calls=0;
  const pending=retryCockpitRead(api,async()=>{calls++;throw new ApiError(503,'SOURCE_UNAVAILABLE');},new AbortController().signal);
  const failure=assert.rejects(pending,{name:'AbortError'});await settle();change(api);t.mock.timers.tick(1000);await settle();await failure;assert.equal(calls,1);
 }
});
test('a late successful reply cannot cross the current login or project scope',async()=>{
 const api={epoch:1,revision:'r1'};let finish;
 const pending=retryCockpitRead(api,()=>new Promise(resolve=>finish=resolve),new AbortController().signal);
 const failure=assert.rejects(pending,{name:'AbortError'});api.epoch++;finish('old');await failure;
});
test('a slow failed request consumes the recovery window instead of starting more long reads',async t=>{
 t.mock.timers.enable({apis:['setTimeout','Date']});let reject,calls=0;
 const pending=retryCockpitRead({epoch:1,revision:'r1'},()=>{calls++;return new Promise((resolve,fail)=>reject=fail);},new AbortController().signal);
 const failure=assert.rejects(pending,{status:504});t.mock.timers.tick(13000);reject(new ApiError(504,'SOURCE_UNAVAILABLE'));await failure;assert.equal(calls,1);
});
