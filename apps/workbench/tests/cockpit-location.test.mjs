import assert from 'node:assert/strict';
import test from 'node:test';
import {cockpitInspectionScene,cockpitLocationCurrent,cockpitPickedObject,cockpitParentPath,readCockpitLocation} from '../src/cockpitLocation.ts';
import {sceneLoadingPlan,modelLoadingKey,SceneLoadingTracker} from '../src/sceneLoading.ts';
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
