import test from 'node:test';
import assert from 'node:assert/strict';
import {adoptedModelTarget,equipmentConfigurationTarget,checkedTaskSnapshot,snapshotDigest,canApplyFreshTask,assistantEditReview,isTaskAddition,taskMaterialName,taskResultReceipt} from '../src/assistantTasks.ts';
import {assistantSendBlocker} from '../src/assistantApi.ts';
import {blankAnalysisDraft} from '../src/analysisDraftState.ts';
import {assistantEntrySeed} from '../src/analysisSources.ts';
const scope={ontobaseConnectionId:'source',projectCode:'Demo-PDS'};
test('source operations display engineering names and track completion for the selected result',()=>{
 assert.equal(taskMaterialName('Demo-PDS:OBJ:00e3efa4c0e8',false),'名称未登记');
 assert.equal(taskMaterialName('r8b13aea4-1ef5-4cf3-9aff-0d6fd03c2952:1',true),'Name not recorded');
 assert.equal(taskMaterialName('+CN1-1U2',false),'+CN1-1U2');
 assert.equal(taskMaterialName('机舱动力柜供电',false),'机舱动力柜供电');
 const receipt={kind:'add_results',resultKey:'R1',label:'工程对象 A'};
 assert.equal(taskResultReceipt([{items:[receipt]}],{key:'R1'}),receipt);
 assert.equal(taskResultReceipt([{items:[receipt]}],{key:'R2'}),undefined);
 const apply=[{kind:'add_results'}];
 assert.equal(isTaskAddition({plan:{actions:apply}},[]),true);
 assert.equal(isTaskAddition({plan:{actions:[...apply,{kind:'arrange'}]}},[]),false);
 assert.equal(isTaskAddition({plan:{actions:[]}},['R1']),true);
});
test('target prompts remain operable in old turns while actual evidence needs remain in the answer',()=>{
 const task={plan:{intent:'edit',actions:[]},receipts:[]};
 const legacyText='请选中目标卡片，或补充卡片、分组或连线的准确名称。';
 const missingMaterials={text:'需要故障发生时段的趋势。',refs:['E1']};
 assert.deepEqual(assistantEditReview(task,[missingMaterials,{text:legacyText,refs:[]}]),
  {target:'card',message:'',legacyGap:legacyText});
 assert.equal(assistantEditReview(task,[missingMaterials]),undefined);
 assert.equal(assistantEditReview(task,[{text:legacyText,refs:['E1']}]),undefined);
 assert.equal(assistantEditReview({...task,plan:{intent:'query',actions:[]}},[{text:legacyText,refs:[]}]),undefined);
 const editReview={target:'group',message:'请在指令中写明要修改的分组名称。'};
 assert.deepEqual(assistantEditReview({...task,editReview}),editReview);
});
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
