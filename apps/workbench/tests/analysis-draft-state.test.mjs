import assert from 'node:assert/strict';
import test from 'node:test';
import {blankAnalysisDraft,draftChanged,draftProblems,pendingDraft,pendingLifecycle} from '../src/analysisDraftState.ts';
const scope={ontobaseConnectionId:'synthetic',projectCode:'A'};
test('new draft has explicit time scope and inherits no source or work order',()=>{
 const value=blankAnalysisDraft(scope,new Date('2026-10-26T12:00:00Z'));
 assert.deepEqual(value.context,{objectIds:[],timeFrom:'2026-10-25T12:00:00.000Z',timeTo:'2026-10-26T12:00:00.000Z',timezone:'Asia/Shanghai'});
 assert.deepEqual(draftProblems(value,scope),[]);
});
test('draft-only policy refuses source cards and conclusion states',()=>{
 for(const state of ['concluded','archived']){const value=blankAnalysisDraft(scope);value.status=state;assert.ok(draftProblems(value,scope).length);}
 const value=blankAnalysisDraft(scope);value.context.objectIds=['claimed-source'];assert.ok(draftProblems(value,scope).length);
});
test('pending save freezes body so editing cannot change an uncertain request',()=>{
 const value=blankAnalysisDraft(scope),receipt={analysisSessionId:'synthetic-id',analysisRevision:2,headRevision:3,contentSha256:'fixture'};
 const pending=pendingDraft(value,receipt,'request-1');value.title='changed';
 assert.equal(pending.body.snapshot.title,'新建分析');assert.equal(pending.body.expectedAnalysisRevision,3);
 assert.equal(pending.body.requestId,'request-1');assert.equal(pending.path,'/api/workbench/analysis-sessions/save');
});
test('restore references a fixed revision while copy creates a separate draft',()=>{
 const value=blankAnalysisDraft(scope),receipt={analysisSessionId:'synthetic-id',analysisRevision:4,contentSha256:'fixture'};
 const restore=pendingDraft(value,receipt,'r',1);
 assert.deepEqual(restore.body,{requestId:'r',analysisSessionId:'synthetic-id',expectedAnalysisRevision:4,restoreRevision:1});
 assert.equal(pendingDraft(value,null,'copy').path,'/api/workbench/analysis-sessions/create');
 assert.throws(()=>pendingDraft(value,null,'bad',1));
});

test('read-only camera movement is not an unsaved edit but local notes remain dirty',()=>{
 const value=blankAnalysisDraft(scope),saved=JSON.stringify(value);value.viewport.x+=10;
 assert.equal(draftChanged(value,saved,false),false);assert.equal(draftChanged(value,saved),true);
 value.title='local edit';assert.equal(draftChanged(value,saved,false),true);
});

test('recycle-bin requests pin both versions and keep content revision restore separate',()=>{
 const item={analysisSessionId:'fixture-id',analysisRevision:5,lifecycleRevision:2,title:'Local canvas',status:'analyzing',updatedAt:'fixture'};
 const pending=pendingLifecycle(item,'trash','request-fixed');item.analysisRevision=6;item.lifecycleRevision=3;
 assert.deepEqual(pending,{path:'/api/workbench/analysis-sessions/trash',body:{analysisSessionId:'fixture-id',expectedAnalysisRevision:5,expectedLifecycleRevision:2,requestId:'request-fixed'}});
 assert.equal(pendingLifecycle(item,'untrash','restore-id').path,'/api/workbench/analysis-sessions/untrash');
 assert.equal(pendingLifecycle({...item,lifecycleRevision:undefined},'trash','first').body.expectedLifecycleRevision,0);
});
