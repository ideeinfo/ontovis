import assert from 'node:assert/strict';
import test from 'node:test';
import {sceneAlarmInstances,alarmLabel} from '../src/sceneAlarm.ts';
const ref={ontobaseConnectionId:'source',projectCode:'P',entityUid:'device-7'};
const instance=(id,objectRef=ref)=>({sceneModelInstanceId:id,rootBinding:objectRef?{objectRef}:null,modelVersionId:'same-version'});
test('only unique physical device bindings participate; shared model versions never identify a device',()=>{
 const one=instance('one'),two=instance('two',{...ref,entityUid:'device-4'}),unbound=instance('none',null);
 assert.deepEqual(sceneAlarmInstances({instances:[one,two,unbound]}),[one,two]);
});
test('duplicate representations and reordered reference properties cannot assign an alarm twice',()=>{
 const a=instance('one'),b=instance('duplicate',{entityUid:ref.entityUid,projectCode:'P',ontobaseConnectionId:'source'}),c=instance('other',{...ref,entityUid:'device-4'});
 assert.deepEqual(sceneAlarmInstances({instances:[a,b,c]}),[c]);
});
test('same UID text in another project remains a different reference',()=>{
 const a=instance('one'),b=instance('two',{...ref,projectCode:'Other'});
 assert.equal(sceneAlarmInstances({instances:[a,b]}).length,2);
});
test('stale, restored and pending states remain distinct in both languages',()=>{
 assert.equal(alarmLabel('stale'),'数据过期');assert.equal(alarmLabel('cleared',true),'Cleared');assert.notEqual(alarmLabel('pending'),alarmLabel('active'));
});
