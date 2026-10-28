import assert from 'node:assert/strict';
import test from 'node:test';
import {ApiError,WorkbenchApi} from '../src/api.ts';
import {keepWorkspaceOnSessionFailure} from '../src/sessionAvailability.ts';

const active={state:'active',sessionRevision:'session:1'};
test('an interrupted background inspection preserves an active workspace without granting a new session',async()=>{
  for(const error of [new TypeError('Failed to fetch'),new ApiError(502,'SOURCE_UNAVAILABLE'),new ApiError(503,'SOURCE_UNAVAILABLE')]){
    const api=new WorkbenchApi(async()=>{throw error;});api.session(active.sessionRevision);
    const failure=await api.request('/api/session').catch(value=>value);
    assert.equal(keepWorkspaceOnSessionFailure(failure,active,false),true);
    for(const state of ['signedOut','expired','denied','unavailable'])assert.equal(keepWorkspaceOnSessionFailure(failure,{...active,state},false),false);
    assert.equal(keepWorkspaceOnSessionFailure(failure,null,false),false);
    assert.equal(keepWorkspaceOnSessionFailure(failure,active,true),false);
  }
});
test('authorization failures still invalidate access and cannot preserve the workspace',async()=>{
  for(const status of [401,403]){
    let denial;
    const api=new WorkbenchApi(async()=>new Response(JSON.stringify({error:'FORBIDDEN'}),{status}));
    api.session(active.sessionRevision);api.onDenied=value=>{denial=value;};
    const failure=await api.request('/api/session').catch(value=>value);
    assert.equal(denial,status);
    assert.equal(keepWorkspaceOnSessionFailure(failure,active,false),false);
  }
  assert.equal(keepWorkspaceOnSessionFailure(new ApiError(409,'SESSION_CHANGED'),active,false),false);
});
