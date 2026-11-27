import assert from 'node:assert/strict';
import test from 'node:test';
import {cockpitAddress,cockpitViewKey,readCockpitAddress} from '../src/cockpitAddress.ts';

const projectRef={ontobaseConnectionId:'ontobase-primary',projectCode:'试点 A/2'};
const sceneId='00000000-0000-0000-0000-000000000001';
const sceneRevision='scene:00000000-0000-0000-0000-000000000002';
const instanceId='00000000-0000-0000-0000-000000000003';

test('assets, scene and equipment locations keep exact identities and exclude private session state',()=>{
 for(const entry of [null,{sceneId,sceneRevision,instanceId:null},{sceneId,sceneRevision,instanceId}]){
  const hash=cockpitAddress(projectRef,entry&&{...entry,camera:{eye:[1,2,3],target:[0,0,0]}});
  assert.deepEqual(readCockpitAddress(hash),{projectRef,entry});
  assert.doesNotMatch(hash,/camera|session|token/);
 }
});

test('malformed, ambiguous and partially pinned links cannot select a scene',()=>{
 const assets=cockpitAddress(projectRef,null);
 assert.equal(readCockpitAddress('#project'),undefined);
 for(const hash of ['#cockpit',assets+'&project=another',assets+'&session=private',assets+'&scene='+sceneId,
  assets+'&instance='+instanceId,assets+'&scene='+sceneId+'&revision=latest',
  assets+'&scene='+sceneId+'&revision='+sceneRevision+'&instance=',assets.replace('project=','project=%0A')]){
  assert.equal(readCockpitAddress(hash),null,hash);
 }
});

test('camera bookmarks are separate across saved revisions and equipment',()=>{
 const key=sceneId+':'+sceneRevision;
 assert.equal(cockpitViewKey(key,null),key);
 assert.notEqual(cockpitViewKey(key,instanceId),cockpitViewKey(key,null));
 assert.notEqual(cockpitViewKey(key,instanceId),cockpitViewKey(sceneId+':scene:'+sceneId,instanceId));
});
