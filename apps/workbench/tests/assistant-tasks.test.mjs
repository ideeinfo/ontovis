import test from 'node:test';
import assert from 'node:assert/strict';
import {adoptedModelTarget,equipmentConfigurationTarget,checkedTaskSnapshot,snapshotDigest,canApplyFreshTask} from '../src/assistantTasks.ts';
import {assistantSendBlocker} from '../src/assistantApi.ts';
import {blankAnalysisDraft} from '../src/analysisDraftState.ts';
import {assistantEntrySeed} from '../src/analysisSources.ts';
const scope={ontobaseConnectionId:'source',projectCode:'Demo-PDS'};
test('the adopted model viewer uses the fixed pair returned by the catalogue',()=>{
 const row={key:'R1',title:'配置模型',identifier:'asset-9',version:'fixed-version-2',kind:'adopted_model',simulated:false,reason:''};
 assert.deepEqual(adoptedModelTarget(row),{modelAssetId:'asset-9',modelVersionId:'fixed-version-2',title:'配置模型'});
 for(const invalid of [{kind:'scene'},{kind:'model'},{version:2},{identifier:''},{version:''}]){
  assert.equal(adoptedModelTarget({...row,...invalid}),null);
 }
});
test('same-name devices open the exact fixed configuration and adoption identity',()=>{
 const row={kind:'equipment_configuration',title:'Identical name',identifier:'device-a',version:'device-a:3',configurationId:'config',configurationRevision:'config:5'};
 assert.deepEqual(equipmentConfigurationTarget(row),{configurationId:'config',configurationRevision:'config:5',device:{entityUid:'device-a',entityRevision:'device-a:3'}});
 const duplicate={...row,identifier:'device-b',version:'device-b:7'};
 assert.equal(equipmentConfigurationTarget(duplicate).device.entityUid,'device-b');
 for(const incomplete of [{configurationId:null},{configurationRevision:null},{version:7},{kind:'scene'}]){
  assert.equal(equipmentConfigurationTarget({...row,...incomplete}),null);
 }
 assert.deepEqual(equipmentConfigurationTarget({...row,kind:'adopted_model'}),{configurationId:'config',configurationRevision:'config:5'});
});
test('a cockpit handoff stays on its target canvas and does not replay after consumption',()=>{
 const entry={analysisSessionId:'target',analysisRevision:8,assistantQuestion:'Add the matching order',openLatest:true};
 assert.deepEqual(assistantEntrySeed(entry,null),{});
 assert.deepEqual(assistantEntrySeed(entry,{analysisSessionId:'other',analysisRevision:8}),{});
 assert.equal(assistantEntrySeed(entry,{analysisSessionId:'target',analysisRevision:9}).initialQuestion,entry.assistantQuestion);
 for(const revision of [8,9])assert.equal(assistantEntrySeed(entry,{analysisSessionId:'target',analysisRevision:revision},true).initialQuestion,undefined);
 const record={...entry,assistantQuestion:undefined,assistantRunId:'saved-turn'};
 assert.equal(assistantEntrySeed(record,{analysisSessionId:'target',analysisRevision:8}).initialRunId,'saved-turn');
 assert.equal(assistantEntrySeed(record,{analysisSessionId:'target',analysisRevision:9}).initialRunId,undefined);
 assert.deepEqual(assistantEntrySeed({newDraft:true},{analysisSessionId:'target',analysisRevision:8}),{});
});
test('project querying accepts an unsaved empty canvas but retains permission and uncertainty guards',()=>{
 const state={projectTools:true,busy:false,active:false,pending:false,loadingHistory:false,focusedEarlier:false,taskMismatch:false,hasReceipt:false,
  view:{policy:{enabled:true}},policyError:null,service:{enabled:true,canRun:true},selectedCount:0,question:'Find orders'};
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
test('only a newly requested unambiguous draft edit applies directly; history, queries and wider saves wait',()=>{
 const task={mode:'workbench',plan:{intent:'edit',actions:[{kind:'add_results',targets:['ORDER-A']}]},receipts:[],trace:[]};
 assert.equal(canApplyFreshTask(task,true,true),true);
 assert.equal(canApplyFreshTask(task,false,false),false);
 assert.equal(canApplyFreshTask({...task,mode:'cockpit_query'},true,false),false);
 assert.equal(canApplyFreshTask({...task,plan:{intent:'query',actions:[]}},true,false),false);
 assert.equal(canApplyFreshTask({...task,receipts:[{operationId:'already-applied'}]},true,false),false);
 const saving={...task,plan:{intent:'edit',actions:[{kind:'save',targets:[]}]}};
 assert.equal(canApplyFreshTask(saving,true,true),false);assert.equal(canApplyFreshTask(saving,true,false),true);
 assert.equal(canApplyFreshTask({...task,plan:{intent:'edit',actions:[{kind:'add_results',targets:[]}]},trace:[{nextCursor:6}]},true,false),false);
 assert.equal(canApplyFreshTask({...task,plan:{intent:'edit',actions:[{kind:'add_results',targets:[]}]}},true,false),false);
 for(const kind of ['replace_source','restore_revision'])assert.equal(canApplyFreshTask({...task,plan:{intent:'edit',actions:[{kind,targets:['C1']}]}},true,false),false);
});
