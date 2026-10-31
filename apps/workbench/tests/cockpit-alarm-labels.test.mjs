import test from 'node:test';
import assert from 'node:assert/strict';
import {cockpitAlarmLabels} from '../src/cockpitAlarmLabels.ts';
import {layoutAlarmLabels} from '../src/sceneAlarm.ts';
const start='2026-10-25T00:00:00Z';
const row=(id='alarm',instanceId='wind-1',entityUid='cabinet',severity='warning')=>({dataset:{datasetId:id,datasetRevision:'fixed:1',timeFrom:start,faultCode:'13001',title:'柜温高报警'},detail:{alarms:[{updatedAt:'2026-10-25T00:00:30Z',state:'active',severity}]},target:{sceneId:'scene',instanceId,entityUid,rootName:'风机名称',displayName:'柜体名称'}});
test('overview labels group by placed turbine and keep separate recurrences in the event count',()=>{
 const a=row(),recurrence=row('recurrence'),sameName=row('other','wind-2');
 const labels=cockpitAlarmLabels([a,a,recurrence,sameName],'scene',null);
 assert.equal(labels.length,2);assert.equal(labels[0].label,'风机名称');assert.equal(labels[0].detail,'2条报警');
 assert.equal(labels[1].detail,'1条报警');assert.notEqual(labels[0].id,labels[1].id);
});
test('device labels carry the actual cabinet identity and the selected fixed event, not just a fault code',()=>{
 const a=row(),critical=row('critical','wind-1','cabinet','critical'),different=row('different','wind-2');
 const labels=cockpitAlarmLabels([a,critical,different],'scene','wind-1',false,a.dataset),component=labels.find(x=>x.level==='component');
 assert.equal(labels.length,2);assert.equal(component.label,'柜体名称');assert.equal(component.detail,'13001 · 柜温高报警');
 assert.equal(component.target.entityUid,'cabinet');assert.equal(component.selection.datasetId,'alarm');assert.equal(component.severity,'warning');
 assert.equal(labels.find(x=>x.level==='asset').severity,'critical');
});
test('absent, cleared, wrong scene and unbound targets do not receive active labels',()=>{
 const a=row(),cleared=row('cleared');cleared.detail.alarms[0].state='cleared';
 assert.deepEqual(cockpitAlarmLabels([{...a,target:null},{...a,detail:null},cleared],'scene',null),[]);
 assert.deepEqual(cockpitAlarmLabels([a],'other',null),[]);
 assert.equal(cockpitAlarmLabels([a],'scene',null,true)[0].detail,'1 alarm');
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
