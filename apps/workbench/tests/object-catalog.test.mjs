import assert from 'node:assert/strict';
import test from 'node:test';
import {categoryLabel,objectCategory,recordedObjectPath} from '../src/objectCatalog.ts';
const object=(uid,name,context='unit')=>({entityUid:uid,displayName:name,installationContextId:context,objectKind:'unknown'});
test('standard classification uses source code and the selected language without a second type line',()=>{
 const classification={code:'A1',nameZh:'控制接口',nameEn:'Control interface',reviewState:'unreviewed'};
 const item={...object('definition','控制定义',null),classification};
 assert.equal(objectCategory(item,'zh'),'A1 · 控制接口');assert.equal(objectCategory(item,'en'),'A1 · Control interface');
 assert.equal(item.objectKind,'unknown');assert.equal(item.classification.reviewState,'unreviewed');
 assert.equal(categoryLabel({...classification,nameEn:null,objectKind:'unknown'},'en'),'A1 · 控制接口');
});
test('unclassified objects and recorded equipment kinds have distinct translated categories',()=>{
 assert.equal(objectCategory(object('a','甲'),'zh'),'未分类');
 assert.equal(objectCategory({...object('b','乙'),objectKind:'cabinet'},'zh'),'柜体');
 assert.equal(objectCategory({...object('b','乙'),objectKind:'cabinet'},'en'),'Cabinet');
});
test('shared equipment kinds have readable labels while source standard categories keep priority',()=>{
 const rows=[['blade_assembly','叶片组','Blade assembly'],['rotor','叶轮 / 转子','Rotor assembly'],['yaw_mechanism','偏航机构','Yaw mechanism'],
  ['transformer','变压器','Transformer'],['generator','发电机','Generator'],['gearbox','齿轮箱','Gearbox'],['main_shaft','主轴','Main shaft'],['hub','轮毂','Hub'],['tower','塔筒','Tower'],['nacelle','机舱','Nacelle']];
 for(const [objectKind,zh,en] of rows){
  const item={...object('fixture','设备'),objectKind};
  assert.equal(objectCategory(item,'zh'),zh);assert.equal(objectCategory(item,'en'),en);
  assert.equal(objectCategory({...item,classification:{code:'A',nameZh:'来源分类'}},'zh'),'A · 来源分类');
 }
});
test('a standard category remains visible when generic kind and definition/installation scope are unclassified',()=>{
 const item={...object('sensor','+CN1-1B4',null),objectScope:'unclassified',classification:{code:'BTA',nameZh:'温度变送器',nameEn:'Temperature transmitter',reviewState:'unreviewed'}};
 const before=structuredClone(item);
 assert.equal(objectCategory(item,'zh'),'BTA · 温度变送器');assert.equal(objectCategory(item,'en'),'BTA · Temperature transmitter');
 assert.equal(objectCategory({objectKind:item.objectKind,classification:{...item.classification,nameEn:null}},'en'),'BTA · 温度变送器');
 assert.deepEqual(item,before);assert.equal(item.objectScope,'unclassified');assert.equal(item.classification.reviewState,'unreviewed');
});
test('the object path shows recorded parents from root to selection without mutating the nearest-first response',()=>{
 const root=object('root','机组'),cabinet=object('CN','信号柜'),child=object('child','控制接口');
 const detail={item:child,ancestors:{completeness:'complete',path:[{object:cabinet},{object:root}]}};
 assert.deepEqual(recordedObjectPath(detail).map(row=>row.entityUid),['root','CN','child']);
 assert.deepEqual(detail.ancestors.path.map(row=>row.object.entityUid),['CN','root']);
 assert.deepEqual(recordedObjectPath({...detail,item:{...child,installationContextId:null}}),[]);
 assert.deepEqual(recordedObjectPath({...detail,ancestors:{completeness:'incomplete',path:[{object:cabinet}]}}).map(row=>row.entityUid),['CN','child']);
});
