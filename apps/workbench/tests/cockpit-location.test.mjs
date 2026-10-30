import assert from 'node:assert/strict';
import test from 'node:test';
import {cockpitLocationCurrent,cockpitPickedObject,cockpitParentPath,readCockpitLocation} from '../src/cockpitLocation.ts';
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
