import test from 'node:test';
import assert from 'node:assert/strict';
import {sceneInformationSnapshot,prepareSceneInformationSave} from '../src/sceneInformation.ts';
import {ApiError} from '../src/api.ts';

const snapshot=()=>({displayName:'Original',description:'Original description',coordinateFrame:{mode:'local_plane',frameRevision:'frame:1',origin:[0,0,0],unit:'m',axes:'X_EAST_Y_UP_Z_SOUTH'},terrain:null,instances:[],initialView:{eye:[80,60,90],target:[0,15,0]},defaults:{background:'sky',lighting:'dusk',terrainMaterial:'solid'}});
const opened=()=>({sceneId:'scene-id',sceneRevision:'scene:4',headRevision:'scene:4',lifecycleRevision:2,snapshot:snapshot(),capabilities:{canWrite:true},validation:{bindingIssues:[],engineeringExpectations:[]}});
const checked=()=>({capabilities:{canWrite:true},reviewedEngineering:[],rootBindingChanges:[]});
test('list information edits only name and description, preserving the saved camera and complete scene',()=>{
 const source=snapshot(),next=sceneInformationSnapshot(source,{name:'  New name  ',description:'Line 1\nLine 2'});
 assert.equal(next.displayName,'New name');assert.equal(next.description,'Line 1\nLine 2');
 assert.deepEqual({...next,displayName:source.displayName,description:source.description},source);
 next.initialView.eye[0]=999;assert.equal(source.initialView.eye[0],80);
 assert.equal(sceneInformationSnapshot(source,{name:'Name',description:''}).description,'');
 delete source.description;assert.equal(Object.hasOwn(sceneInformationSnapshot(source,{name:'Name',description:''}),'description'),false);
});
test('information validates character limits and control characters before requesting a write',()=>{
 for(const info of [{name:' ',description:''},{name:'x'.repeat(201),description:''},{name:'Name',description:'x'.repeat(2001)},{name:'Bad\nname',description:''},{name:'Name',description:'\t'}])assert.throws(()=>sceneInformationSnapshot(snapshot(),info),e=>e.code==='INVALID_REQUEST');
 assert.equal(Array.from(sceneInformationSnapshot(snapshot(),{name:'风'.repeat(200),description:''}).displayName).length,200);
});
test('direct save keeps scene and lifecycle conditions and an immutable request for retries',async()=>{
 const original=opened(),calls=[],signal=new AbortController().signal,info={name:'Renamed',description:'Note'};
 const body=await prepareSceneInformationSave({check:async(request,actualSignal)=>{calls.push(request);assert.equal(actualSignal,signal);return checked();}},original,info,'fixed-request',signal);
 assert.equal(calls.length,1);assert.equal(calls[0].expectedSceneRevision,'scene:4');
 assert.equal(body.expectedLifecycleRevision,2);assert.equal(body.clientRequestId,'fixed-request');assert.equal(body.snapshot.displayName,'Renamed');
 const first=JSON.stringify(body);original.snapshot.initialView.eye[0]=300;info.name='Later typing';assert.equal(JSON.stringify(body),first);
});
test('read-only, stale revisions, concurrent updates and revoked write access never produce a save request',async()=>{
 const info={name:'Name',description:''};let calls=0;
 for(const original of [{...opened(),capabilities:{canWrite:false}},{...opened(),headRevision:'scene:5'}])await assert.rejects(()=>prepareSceneInformationSave({check:async()=>{calls++;return checked();}},original,info,'req'));
 assert.equal(calls,0);
 await assert.rejects(()=>prepareSceneInformationSave({check:async()=>{throw new ApiError(409,'SCENE_CHANGED');}},opened(),info,'req'),e=>e.code==='SCENE_CHANGED');
 await assert.rejects(()=>prepareSceneInformationSave({check:async()=>({...checked(),capabilities:{canWrite:false}})},opened(),info,'req'),e=>e.code==='SCENE_WRITE_FORBIDDEN');
});
test('direct metadata editing cannot silently approve changed engineering bindings',async()=>{
 const requirement={ref:{ontobaseConnectionId:'source',projectCode:'project',entityUid:'entity'},expectedEntityRevision:'entity:2',installationContextId:'context',expectedHierarchyRevision:'hierarchy:1'};
 await assert.rejects(()=>prepareSceneInformationSave({check:async()=>({...checked(),reviewedEngineering:[requirement]})},opened(),{name:'Name',description:''},'req'),e=>e.code==='ENGINEERING_CHANGED');
});
