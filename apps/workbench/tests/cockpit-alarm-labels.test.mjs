import test from 'node:test';
import assert from 'node:assert/strict';
import {cockpitAlarmLabels} from '../src/cockpitAlarmLabels.ts';
import {layoutAlarmLabels} from '../src/sceneAlarm.ts';
const start='2026-10-25T00:00:00Z';
const row=(id='alarm',instanceId='wind-1',entityUid='cabinet',severity='warning')=>({dataset:{datasetId:id,datasetRevision:'fixed:1',timeFrom:start,faultCode:'13001',title:'柜温高报警'},detail:{alarms:[{updatedAt:'2026-10-25T00:00:30Z',state:'active',severity}]},target:{sceneId:'scene',instanceId,entityUid,rootName:'风机名称',displayName:'柜体名称'}});
const mapped=target=>target.entityUid==='cabinet'?['cabinet-mesh']:null;
test('overview labels group by placed turbine and keep separate recurrences in the event count',()=>{
 const a=row(),recurrence=row('recurrence'),sameName=row('other','wind-2');
 const labels=cockpitAlarmLabels([a,a,recurrence,sameName],'scene',null,false,undefined,()=>{throw new Error('Overview must use asset labels');});
 assert.equal(labels.length,2);assert.equal(labels[0].label,'风机名称');assert.equal(labels[0].detail,'2条报警');
 assert.equal(labels[1].detail,'1条报警');assert.notEqual(labels[0].id,labels[1].id);
});
test('a device label keeps the selected fixed event without also counting it at asset level',()=>{
 const a=row(),critical=row('critical','wind-1','cabinet','critical'),different=row('different','wind-2');
 const labels=cockpitAlarmLabels([a,critical,different],'scene','wind-1',false,a.dataset,mapped),component=labels.find(x=>x.level==='component');
 assert.equal(labels.length,1);assert.equal(component.label,'柜体名称');assert.equal(component.detail,'13001 · 柜温高报警');
 assert.equal(component.target.entityUid,'cabinet');assert.equal(component.selection.datasetId,'alarm');assert.equal(component.severity,'warning');
 assert.deepEqual(component.componentKeys,['cabinet-mesh']);
});
test('five mapped alarms yield one cabinet callout rather than duplicate five-alarm layers',()=>{
 const alarms=Array.from({length:5},(_,i)=>row('event-'+i));let resolved=0;
 const labels=cockpitAlarmLabels(alarms,'scene','wind-1',false,undefined,target=>{resolved++;return mapped(target);});
 assert.equal(labels.length,1);assert.equal(labels[0].level,'component');assert.equal(labels[0].detail,'5条报警');
 assert.equal(resolved,1,'Mapping is resolved once per component group, not once per alarm');
});
test('missing component geometry falls back to one asset callout with every event retained',()=>{
 const alarms=[row('a'),row('b')];
 for(const resolve of [undefined,()=>null,()=>[]]){
  const labels=cockpitAlarmLabels(alarms,'scene','wind-1',false,undefined,resolve);
  assert.equal(labels.length,1);assert.equal(labels[0].level,'asset');assert.equal(labels[0].detail,'2条报警');assert.equal(labels[0].componentKeys,undefined);
 }
});
test('partly mapped targets keep only the unmapped events in the asset fallback count',()=>{
 const alarms=[row('a'),row('b','wind-1','cabinet','critical'),row('unmapped','wind-1','unmapped')];
 const labels=cockpitAlarmLabels(alarms,'scene','wind-1',false,undefined,mapped);
 assert.equal(labels.length,2);
 const asset=labels.find(x=>x.level==='asset'),component=labels.find(x=>x.level==='component');
 assert.equal(asset.detail,'1条报警');assert.equal(asset.selection.datasetId,'unmapped');
 assert.equal(component.detail,'2条报警');assert.equal(component.selection.datasetId,'b');assert.equal(component.severity,'critical');
});
test('separate mapped cabinets keep separate identities instead of merging their matching names',()=>{
 const labels=cockpitAlarmLabels([row('a'),row('b','wind-1','other-cabinet')],'scene','wind-1',false,undefined,target=>[target.entityUid+'-mesh']);
 assert.equal(labels.length,2);assert.ok(labels.every(label=>label.level==='component'));assert.notEqual(labels[0].id,labels[1].id);
});
test('repeated fixed events count once while independent recurrences still count separately',()=>{
 const a=row('a'),recurrence=row('recurrence');
 const labels=cockpitAlarmLabels([a,a,recurrence],'scene','wind-1',false,undefined,mapped);
 assert.equal(labels.length,1);assert.equal(labels[0].detail,'2条报警');
});
test('model availability changes replace the fallback label without changing the event identity',()=>{
 const alarms=[row('a')];let ready=false;
 const resolve=()=>ready?['cabinet-mesh']:undefined;
 const fallback=cockpitAlarmLabels(alarms,'scene','wind-1',false,undefined,resolve);
 ready=true;const detailed=cockpitAlarmLabels(alarms,'scene','wind-1',false,undefined,resolve);
 ready=false;const restored=cockpitAlarmLabels(alarms,'scene','wind-1',false,undefined,resolve);
 assert.deepEqual([fallback,detailed,restored].map(labels=>labels.map(label=>label.level)),[['asset'],['component'],['asset']]);
 assert.deepEqual(fallback[0].selection,detailed[0].selection);assert.deepEqual(restored[0].selection,detailed[0].selection);
});
test('absent, cleared, wrong scene and unbound targets do not receive active labels',()=>{
 const a=row(),cleared=row('cleared');cleared.detail.alarms[0].state='cleared';
 assert.deepEqual(cockpitAlarmLabels([{...a,target:null},{...a,detail:null},cleared],'scene',null),[]);
 assert.deepEqual(cockpitAlarmLabels([a],'other',null),[]);
 assert.equal(cockpitAlarmLabels([a],'scene',null,true)[0].detail,'1 alarm');
 assert.equal(cockpitAlarmLabels([a,row('recurrence')],'scene','wind-1',true,undefined,mapped)[0].detail,'2 alarms');
});
test('nearby labels keep separate readable rectangles and stay within the viewport',()=>{
 const items=[{id:'asset',x:400,y:300,width:180,height:50},{id:'component',x:410,y:308,width:190,height:60},{id:'edge',x:2,y:12,width:130,height:44}];
 const placed=layoutAlarmLabels(items,900,600);assert.equal(placed.length,3);
 for(const rect of placed){assert.ok(rect.left>=10&&rect.top>=10);assert.ok(rect.left+rect.width<=890&&rect.top+rect.height<=590);}
 const [a,b]=placed;assert.ok(a.top+a.height<=b.top||b.top+b.height<=a.top);
});
test('callouts stay clear of both side panels while their leader can point to an edge asset',()=>{
 const placed=layoutAlarmLabels([{id:'edge',x:285,y:200,width:200,height:48}],1280,720,{left:.24,right:.22});
 assert.ok(placed[0].left>=1280*.24+10);assert.ok(placed[0].left+200<=1280*.78-10);
});
