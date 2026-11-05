import test from 'node:test';
import assert from 'node:assert/strict';
import {cockpitQuickFocus} from '../src/cockpitQuickFocus.ts';
const ref={entityUid:'unit',projectCode:'p',ontobaseConnectionId:'c'};
const instance={sceneModelInstanceId:'placed',modelVersionId:'model',visible:true,rootBinding:{objectRef:ref},componentBindings:[{objectRef:{...ref,entityUid:'cabinet'},componentKeys:['CN1']}],placement:{position:{mode:'local',xM:10,zM:20},height:{mode:'local_relative',relativeHeightM:3},headingDeg:90}};
const model={modelVersionId:'model',sha256:'fixed',contentRevision:'fixed-r1',state:'ready',canPlace:true,calibrationState:'verified',calibration:{state:'verified',unit:'m',axes:'Y_UP_RIGHT_HANDED',basePoint:[1,0,0],forward:[0,0,-1],modelToCalibrated:[1,0,0,0,0,1,0,0,0,0,1,0,-1,0,0,1]},components:[{componentKey:'CN1',bounds:[[1,2,3],[2,4,5]]}]};
const opened={sceneRevision:'r1',headRevision:'r1',resourceRefs:[{modelVersionId:'model',sha256:'fixed',contentRevision:'fixed-r1'}],snapshot:{coordinateFrame:{mode:'local_plane',frameRevision:'frame-r1',unit:'m',axes:'X_EAST_Y_UP_Z_SOUTH',origin:[0,0,0]}}};
const record={item:{entityUid:'unit'},context:{rootEntityUid:'unit',projectCode:'p'},children:[{entityUid:'cabinet',entityRevision:'cabinet-r1'}]};
const read=(o=opened,i=instance,m=model,r=record,expected)=>cockpitQuickFocus(o,i,m,r,'cabinet',1,true,expected);
test('immediate focus uses fixed component bounds with calibration, true heading and placement once',()=>{
 const focus=read();assert.equal(focus.instanceId,'placed');assert.equal(focus.isolate,true);assert.deepEqual(focus.componentKeys,['CN1']);
 for(const [point,expected] of focus.bounds.map((p,i)=>[p,i?[7,7,21]:[5,5,20]]))point.forEach((n,j)=>assert.ok(Math.abs(n-expected[j])<1e-9));
});
test('quick focus refuses stale resources, historical scenes, unknown geometry and changed alarm identities',()=>{
 for(const m of [{...model,sha256:'changed'},{...model,contentRevision:'changed'},{...model,canPlace:false},{...model,components:[]},{...model,components:[...model.components,...model.components]},{...model,calibration:{state:'unverified'}}])assert.equal(read(opened,instance,m),undefined);
 assert.equal(read({...opened,headRevision:'new'}),undefined);
 assert.equal(read(opened,{...instance,componentBindings:[]}),undefined);
 assert.equal(read(opened,{...instance,componentBindings:[...instance.componentBindings,...instance.componentBindings]}),undefined);
 assert.equal(read(opened,instance,model,record,'old'),undefined);
 assert.equal(read(opened,instance,model,{...record,context:{...record.context,rootEntityUid:'other'}}),undefined);
});
test('quick focus never treats a same-name cabinet in another project as the current binding',()=>{
 assert.equal(read(opened,{...instance,componentBindings:[{objectRef:{...ref,entityUid:'cabinet',projectCode:'elsewhere'},componentKeys:['CN1']}]}),undefined);
 assert.equal(read(opened,instance,model,{...record,children:[record.children[0],record.children[0]]}),undefined);
 assert.equal(read(opened,instance,model,record,'cabinet-r1').token,1);
});
