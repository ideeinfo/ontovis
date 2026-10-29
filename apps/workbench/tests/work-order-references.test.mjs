import assert from 'node:assert/strict';
import test from 'node:test';
import {workOrderReferenceEntry,workOrderReferenceCard} from '../src/workOrderReferences.ts';
const scope={ontobaseConnectionId:'source-one',projectCode:'P'};
const transfer={analysisSessionId:'analysis-one',analysisRevision:3,analysisSha256:'a'.repeat(64),orderRevision:7,sources:[{key:'E5',kind:'document',evidenceRefId:'manual-ref',sourceRevision:'b'.repeat(64)}]};
const item={refs:['E5']};
const card={id:'manual-card',kind:'document',title:'手册',source:{...scope,id:'manual-ref',revision:'b'.repeat(64)}};
const detail={analysisSessionId:'analysis-one',analysisRevision:3,contentSha256:'a'.repeat(64),snapshot:{...scope,cards:[card]}};
const entry=()=>workOrderReferenceEntry('order-one',transfer,item,'E5');
test('navigation keeps the adopted fixed analysis and original reference identity',()=>{
 const value=entry();assert.equal(value.analysisRevision,3);assert.equal(value.workOrderReference.orderRevision,7);
 assert.equal(value.workOrderReference.evidenceRefId,'manual-ref');assert.equal(value.workOrderReference.key,'E5');
 assert.equal(Object.hasOwn(value,'assistantRunId'),false);assert.equal(Object.hasOwn(value,'snapshot'),false);
 assert.equal(workOrderReferenceCard(value,detail,scope),card);
});
test('legacy, missing and ambiguous references never infer from a key or name',()=>{
 for(const sources of [[],[transfer.sources[0],transfer.sources[0]],[{...transfer.sources[0],sourceRevision:undefined}],[{...transfer.sources[0],kind:'script'}]])assert.equal(workOrderReferenceEntry('order-one',{...transfer,sources},item,'E5'),null);
 assert.equal(workOrderReferenceEntry('order-one',transfer,{refs:['E1']},'E5'),null);
 assert.equal(workOrderReferenceEntry('order-one',{...transfer,analysisSha256:''},item,'E5'),null);
});
test('another analysis, revision or content hash cannot replace the original analysis',()=>{
 for(const patch of [{analysisSessionId:'other'},{analysisRevision:4},{contentSha256:'c'.repeat(64)}])assert.throws(()=>workOrderReferenceCard(entry(),{...detail,...patch},scope),/WORK_ORDER_REFERENCE_CHANGED/);
});
test('project and connection scope must match both the snapshot and source',()=>{
 for(const target of [null,{...scope,projectCode:'Q'},{...scope,ontobaseConnectionId:'another'}])assert.throws(()=>workOrderReferenceCard(entry(),detail,target),/WORK_ORDER_REFERENCE_CHANGED/);
 for(const target of [{projectCode:'Q'},{ontobaseConnectionId:'another'}])assert.throws(()=>workOrderReferenceCard(entry(),{...detail,snapshot:{...detail.snapshot,cards:[{...card,source:{...card.source,...target}}]}},scope),/WORK_ORDER_REFERENCE_CHANGED/);
});
test('same title, wrong kind or wrong source revision cannot resolve a citation',()=>{
 for(const patch of [{kind:'photo'},{source:{...card.source,id:'another'}},{source:{...card.source,revision:'c'.repeat(64)}}])assert.throws(()=>workOrderReferenceCard(entry(),{...detail,snapshot:{...detail.snapshot,cards:[{...card,...patch}]}},scope),/WORK_ORDER_REFERENCE_CHANGED/);
});
test('multiple representations of the identical fixed reference prefer a current card without modifying it',()=>{
 const old={...card,id:'old-card',historical:true};assert.equal(workOrderReferenceCard(entry(),{...detail,snapshot:{...detail.snapshot,cards:[old,card]}},scope),card);
 assert.equal(workOrderReferenceCard(entry(),{...detail,snapshot:{...detail.snapshot,cards:[old]}},scope),old);
 assert.equal(Object.hasOwn(card,'historical'),false);
});
test('model source references resolve model cards using the same fixed identities',()=>{
 const value=workOrderReferenceEntry('order-one',{...transfer,sources:[{...transfer.sources[0],kind:'model'}]},item,'E5');
 const model={...card,kind:'model3d'};assert.equal(workOrderReferenceCard(value,{...detail,snapshot:{...detail.snapshot,cards:[model]}},scope),model);
});
