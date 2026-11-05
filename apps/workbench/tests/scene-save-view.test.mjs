import assert from 'node:assert/strict';
import test from 'node:test';
import {sceneSnapshotWithView,sceneViewChanged} from '../src/sceneSaveView.ts';
const snapshot=()=>({displayName:'场景',coordinateFrame:{mode:'local_plane',frameRevision:'frame1',origin:[0,0,0],unit:'m',axes:'X_EAST_Y_UP_Z_SOUTH'},terrain:null,instances:[],initialView:{eye:[80,60,90],target:[0,15,0]},defaults:{background:'sky',lighting:'dusk',terrainMaterial:'solid'}});
test('a view-only save captures orbit, pan and distance while preserving all scene content',()=>{
 const before=snapshot(),view={eye:[100,88,-60],target:[20,18,30]},saved=sceneSnapshotWithView(before,view);
 assert.equal(sceneViewChanged(before.initialView,view),true);assert.deepEqual(saved.initialView,view);
 assert.deepEqual({...saved,initialView:before.initialView},before);assert.deepEqual(before.initialView,snapshot().initialView);
 assert.equal(sceneViewChanged(saved.initialView,view),false);
});
test('validation and uncertain-write replay keep the click-time camera even after later movement',async()=>{
 const draft=snapshot(),view={eye:[100,80,90],target:[0,30,0]},captured=sceneSnapshotWithView(draft,view);
 const request={clientRequestId:'one-write',snapshot:captured},first=JSON.stringify(request);
 await Promise.resolve();view.eye[0]=999;view.target[1]=99;draft.displayName='later edit';
 assert.equal(JSON.stringify(request),first);assert.equal(request.snapshot.initialView.eye[0],100);
 assert.notEqual(JSON.stringify(sceneSnapshotWithView(draft,view)),JSON.stringify(request.snapshot));
});
test('round-off does not create a camera-only dirty state, while a material camera move does',()=>{
 const source=snapshot().initialView;
 assert.equal(sceneViewChanged(source,null),false);
 assert.equal(sceneViewChanged(source,{...source,eye:[80+1e-8,60,90]}),false);
 assert.equal(sceneViewChanged(source,{...source,target:[0,15,.001]}),true);
});
test('invalid or coincident views cannot replace a valid saved default',()=>{
 const source=snapshot();
 for(const view of [{eye:[NaN,0,0],target:[0,0,0]},{eye:[0,0,0],target:[0,0,0]},{eye:[1,2],target:[0,0,0]},{eye:[1,2,3],target:[0,Infinity,0]}]){
  assert.throws(()=>sceneSnapshotWithView(source,view),e=>e.code==='INVALID_COORDINATE');assert.equal(sceneViewChanged(source.initialView,view),false);
 }
 assert.deepEqual(sceneSnapshotWithView(source,null),source);
});
