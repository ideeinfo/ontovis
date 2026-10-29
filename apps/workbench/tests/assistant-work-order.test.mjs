import assert from 'node:assert/strict';
import test from 'node:test';
import {canTransfer,transferBody,transferEdits,transferMessage,transferProblems} from '../src/assistantWorkOrder.ts';
import {ApiError} from '../src/api.ts';
const preview={proposal:{runId:'saved-run',proposalSha256:'fixed',items:[
 {id:'hypotheses-0',kind:'hypothesis',text:'待验证测量链',refs:['E3']},
 {id:'nextSteps-0',kind:'step',text:'比较独立参照',refs:['E4']},
 {id:'gaps-0',kind:'gap',text:'缺少规程',refs:[]}]},
 order:{orderId:'one',orderRevision:3,state:'diagnosing',investigation:{hypotheses:[{id:'old'}],steps:[{id:'old-step'}]}},adoptedItemIds:[]};
test('default suggestions distinguish hypotheses and checks from optional evidence gaps',()=>{
 const edits=transferEdits(preview);assert.deepEqual(edits.map(row=>row.selected),[true,true,false]);
 assert.ok(edits.every(row=>row.targetKey===''));assert.deepEqual(transferProblems(preview,edits),[]);
 assert.equal(canTransfer({state:'complete',result:{}}),true);assert.equal(canTransfer({state:'changed',result:{}}),false);
 assert.equal(canTransfer({state:'complete',result:null}),false);
});
test('reload keeps human edits but removes newly adopted suggestions from the selection',()=>{
 const old=transferEdits(preview);old[0].text='人工调整';old[1].targetKey='known-target';
 const result=transferEdits({...preview,adoptedItemIds:['hypotheses-0']},old);
 assert.equal(result[0].text,'人工调整');assert.equal(result[0].selected,false);assert.equal(result[1].targetKey,'known-target');
});
test('submitted items retain original row identities without verified states or conclusions',()=>{
 const edits=transferEdits(preview);edits[0].text=' 人工调整 ';
 const body=transferBody(preview,edits);assert.equal(body.expectedOrderRevision,3);assert.equal(body.expectedProposalSha256,'fixed');
 assert.deepEqual(body.items,[{id:'hypotheses-0',text:'人工调整',targetKey:''},{id:'nextSteps-0',text:'比较独立参照',targetKey:''}]);
 for(const key of ['conclusion','status','outcome','basis','checks','state','sources'])assert.equal(Object.hasOwn(body,key),false);
});
test('read-only states, limits, empty text and unchecked selections block save',()=>{
 const edits=transferEdits(preview);
 for(const state of ['open','review','closed'])assert.ok(transferProblems({...preview,order:{...preview.order,state}},edits).includes('state'));
 assert.ok(transferProblems({...preview,order:{...preview.order,investigation:{hypotheses:Array(6),steps:[]}}},edits).includes('limit'));
 edits[0].text=' ';assert.ok(transferProblems(preview,edits).includes('text'));
 assert.ok(transferProblems(preview,edits.map(row=>({...row,selected:false}))).includes('empty'));
 edits[2].selected=true;edits[2].text='字'.repeat(496);assert.ok(transferProblems(preview,edits).includes('text'));
});
test('save conflicts explain retained edits and do not frame suggestions as confirmations',()=>{
 assert.match(transferMessage(new ApiError(409,'WORK_ORDER_CHANGED'),false),/编辑保留/);
 assert.match(transferMessage(new ApiError(409,'ASSISTANT_TRANSFER_UNAVAILABLE'),true),/cannot be used/);
 assert.equal(transferMessage(new ApiError(500,'OTHER'),false),undefined);
});
