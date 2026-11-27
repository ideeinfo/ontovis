import test from 'node:test';
import assert from 'node:assert/strict';
import {drawingGroups,drawingObjectLocationLabel} from '../src/drawingGroups.ts';

const classified=(id,code='BTA',revisionId='r1')=>({id,title:id,objectType:'unknown',classification:{code,revisionId,nameZh:'温度变送器',nameEn:'Temperature transmitter',reviewState:'unreviewed'}});

test('objects group by pinned standard revision and code without changing their rows',()=>{
 const rows=[classified('B10'),classified('B2'),classified('B1','BTA','r2'),{id:'unknown',title:'Unclassified'}],before=structuredClone(rows);
 const groups=drawingGroups(rows,false,false);
 assert.equal(groups.length,3);assert.deepEqual(groups.find(g=>g.rows.length===2).rows.map(r=>r.id),['B2','B10']);
 assert.equal(groups[0].label,'BTA · 温度变送器');assert.equal(groups.at(-1).label,'未分类');assert.deepEqual(rows,before);
 assert.equal(drawingGroups(rows,false,true)[0].label,'BTA · Temperature transmitter');
});

test('port owners use source identity rather than equal display names',()=>{
 const rows=[{...classified('端口 10'),owner:'Same object',ownerId:'one'},{...classified('端口 2'),owner:'Same object',ownerId:'one'},{...classified('端口 1'),owner:'Same object',ownerId:'two'}];
 const groups=drawingGroups(rows,true,false);assert.equal(groups.length,1);assert.equal(groups[0].owners.length,2);
 assert.deepEqual(groups[0].owners[0].rows.map(r=>r.title),['端口 2','端口 10']);assert.notEqual(groups[0].owners[0].key,groups[0].owners[1].key);
});

test('type and object search retains matching hierarchy and counts',()=>{
 const rows=[{...classified('端口 1'),owner:'CN1-1B4',ownerId:'one'},{...classified('端口 2'),owner:'CN2-2B4',ownerId:'two'}];
 assert.equal(drawingGroups(rows,true,false,'BTA')[0].rows.length,2);
 assert.equal(drawingGroups(rows,true,false,'1B4')[0].owners.length,1);
 assert.equal(drawingGroups(rows,true,false,'温度变送器')[0].rows.length,2);
 assert.equal(drawingGroups(rows,true,false,'missing').length,0);
});

test('unassigned ports and generic type aliases remain represented',()=>{
 const groups=drawingGroups([{id:'a',title:'A',objectType:'signal',ownerId:'one',owner:'Signal A'},{id:'b',title:'B',objectType:'pid_signal',ownerId:'two',owner:'Signal B'},{id:'c',title:'C',objectType:' '}],true,false);
 assert.equal(groups.length,2);assert.equal(groups[0].label,'信号/联锁');assert.equal(groups[0].owners.length,2);
 assert.equal(groups[1].label,'未分类');assert.equal(groups[1].owners[0].label,'未关联对象');
});

test('drawing region labels use the selected object classification and full recorded designation',()=>{
 const row={id:'internal-location',entityUid:'internal-object',title:'not the object code',identifier:' =WEC+CN1-1Q1 ',
  classification:{code:'QAB',nameZh:'断路器',nameEn:'Circuit breaker'},bbox:{x:.3,y:.4,width:.02,height:.05}},before=structuredClone(row);
 assert.equal(drawingObjectLocationLabel(row,false),'断路器-=WEC+CN1-1Q1');
 assert.equal(drawingObjectLocationLabel(row,true),'Circuit breaker-=WEC+CN1-1Q1');
 assert.equal(drawingObjectLocationLabel({...row,identifier:'=WEC+CN1-1B4',classification:classified('other').classification},false),'温度变送器-=WEC+CN1-1B4');
 assert.deepEqual(row,before);
});

test('drawing region labels retain partial source identity without inventing classification or codes',()=>{
 assert.equal(drawingObjectLocationLabel(undefined,false),'');
 assert.equal(drawingObjectLocationLabel({id:'internal',entityUid:'entity:internal',title:'file.pdf',objectType:'unknown'},false),'');
 assert.equal(drawingObjectLocationLabel({id:'one',title:'wrong',identifier:'+Q1',classification:{code:'QAB'}},false),'QAB-+Q1');
 assert.equal(drawingObjectLocationLabel({id:'one',title:'wrong',identifier:'+Q1'},false),'+Q1');
 assert.equal(drawingObjectLocationLabel({...classified('one'),identifier:' '},false),'温度变送器');
 assert.equal(drawingObjectLocationLabel({...classified('one'),classification:{code:'BTA',nameZh:'温度变送器'}},true),'温度变送器');
});

test('drawing region labels reuse readable generic type aliases when no source standard is recorded',()=>{
 const row={id:'source',title:'different name',identifier:'=A+P1',objectType:'pid_pump'};
 assert.equal(drawingObjectLocationLabel(row,false),'泵-=A+P1');
 assert.equal(drawingObjectLocationLabel(row,true),'Pump-=A+P1');
 assert.equal(drawingObjectLocationLabel({...row,objectType:'unclassified'},false),'=A+P1');
});
