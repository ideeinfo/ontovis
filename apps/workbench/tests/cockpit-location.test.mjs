import assert from 'node:assert/strict';
import test from 'node:test';
import {cockpitLocationCurrent,cockpitPickedObject,cockpitParentPath} from '../src/cockpitLocation.ts';
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
