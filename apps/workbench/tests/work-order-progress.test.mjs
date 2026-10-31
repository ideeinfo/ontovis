import assert from 'node:assert/strict';
import test from 'node:test';
import {adoptionProgress,progressRecommendation,progressRows,progressTargetLabel} from '../src/workOrderProgress.ts';
const plan={hypotheses:[{id:'h1',description:'测量链待核',status:'candidate',basis:''}],steps:[{id:'s1',title:'核对温度',targetKey:'part-0',outcome:'pending',result:''}],conclusion:'',reviewBasis:''};
const fixed={orderId:'one',orderRevision:3,state:'diagnosing',investigation:plan};
const item={sourceItemId:'nextSteps-0',kind:'step',text:'核对温度',targetKey:'part-0',planItemId:'s1',refs:[]};
test('each revision resolves its own object label without exposing internal navigation keys',()=>{
 const old={diagnosis:{nodes:[{locateKey:'part-0',label:'温度传感器'}]}};
 const now={diagnosis:{nodes:[{locateKey:'part-0',label:'独立测温元件'}]}};
 assert.equal(progressTargetLabel('part-0',old),'温度传感器');assert.equal(progressTargetLabel('part-0',now),'独立测温元件');
 assert.equal(progressTargetLabel('missing',old),undefined);assert.equal(progressTargetLabel('part-0',{}),undefined);
});
test('comparison uses stable identities; a same-name replacement is a removal and addition',()=>{
 const now=structuredClone(fixed);now.investigation.steps[0].id='another';
 assert.deepEqual(progressRows(fixed,now).map(r=>[r.id,r.change]),[['h1','unchanged'],['s1','removed'],['another','added']]);
 assert.equal(adoptionProgress(item,now.investigation).retained,false);
});
test('recorded results and changed navigation targets are distinct from adopted text',()=>{
 const now=structuredClone(plan);now.steps[0].result='仅软件演练，保留缺口';now.steps[0].outcome='gap';
 let result=adoptionProgress(item,now);assert.equal(result.state,'gap');assert.equal(result.edited,false);assert.match(result.record,/保留缺口/);
 now.steps[0].targetKey='part-1';result=adoptionProgress(item,now);assert.equal(result.edited,true);
 assert.equal(progressRows(fixed,{...fixed,investigation:now})[1].change,'changed');
 assert.equal(plan.steps[0].outcome,'pending');
});
test('hypothesis basis and status are human records; changed field ordering is not a difference',()=>{
 const current={steps:plan.steps,hypotheses:[{basis:'独立参照尚待现场核查',status:'supported',description:'测量链待核',id:'h1'}],conclusion:'',reviewBasis:''};
 const h={...item,kind:'hypothesis',planItemId:'h1',text:'测量链待核',targetKey:''};
 assert.equal(adoptionProgress(h,current).state,'supported');assert.equal(adoptionProgress(h,current).edited,false);
 assert.equal(progressRows(fixed,{...fixed,investigation:current})[0].change,'changed');
 current.hypotheses[0].basis='';current.hypotheses[0].status='candidate';assert.ok(progressRows(fixed,{...fixed,investigation:current}).every(r=>r.change==='unchanged'));
});
test('gap prefix is presentation; adoption detects later edits without rewriting its receipt',()=>{
 const gap={...item,kind:'gap',text:'缺少现场依据'};
 const current=structuredClone(plan);current.steps[0].title='补充证据：缺少现场依据';
 assert.equal(adoptionProgress(gap,current).edited,false);current.steps[0].title='人工调整的核验范围';assert.equal(adoptionProgress(gap,current).edited,true);assert.equal(gap.text,'缺少现场依据');
});
test('only an explicitly newer revision of the same order can replace the fixed source',()=>{
 for(const after of [{...fixed,orderRevision:2},{...fixed,orderRevision:3},{...fixed,orderId:'other',orderRevision:4},{...fixed,orderRevision:4.5}])assert.equal(progressRecommendation(fixed,after),null);
 const result=progressRecommendation(fixed,{...fixed,title:'本单温度核对',orderRevision:4});
 assert.equal(result.kind,'work_order');assert.deepEqual(result.selector,{orderId:'one',expectedOrderRevision:4});
 assert.equal(Object.hasOwn(result.selector,'conclusion'),false);
});
