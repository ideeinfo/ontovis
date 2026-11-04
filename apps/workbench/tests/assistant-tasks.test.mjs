import test from 'node:test';
import assert from 'node:assert/strict';
import {checkedTaskSnapshot,snapshotDigest} from '../src/assistantTasks.ts';
import {assistantSendBlocker} from '../src/assistantApi.ts';
import {blankAnalysisDraft} from '../src/analysisDraftState.ts';
const scope={ontobaseConnectionId:'source',projectCode:'Demo-PDS'};
test('project querying accepts an unsaved empty canvas but retains permission and uncertainty guards',()=>{
 const state={projectTools:true,busy:false,active:false,pending:false,loadingHistory:false,focusedEarlier:false,taskMismatch:false,hasReceipt:false,
  view:{policy:{enabled:true,reads:8}},policyError:null,service:{enabled:true,canRun:true},selectedCount:0,question:'Find orders'};
 assert.equal(assistantSendBlocker(state),null);assert.equal(assistantSendBlocker({...state,pending:true}),'ASSISTANT_START_UNCERTAIN');
 assert.equal(assistantSendBlocker({...state,service:{enabled:true,canRun:false}}),'ASSISTANT_RUN_FORBIDDEN');
});
test('draft changes, cross-project patches and repeated application cannot overwrite the live canvas',async()=>{
 const original={...blankAnalysisDraft(scope),schemaVersion:2},raw=JSON.stringify(original),prepared={snapshot:{...original,title:'Candidate'},baseDigest:await snapshotDigest(raw)};
 assert.equal(checkedTaskSnapshot(original,prepared,scope,raw).title,'Candidate');
 assert.equal(original.title,'新建分析');assert.equal(prepared.baseDigest.length,64);
 assert.throws(()=>checkedTaskSnapshot({...original,title:'User edit'},prepared,scope,raw),/画布已变化/);
 assert.throws(()=>checkedTaskSnapshot(original,{...prepared,snapshot:{...prepared.snapshot,projectCode:'other'}},scope,raw));
 assert.throws(()=>checkedTaskSnapshot(original,{...prepared,alreadyApplied:true},scope,raw),/未重复/);
});
