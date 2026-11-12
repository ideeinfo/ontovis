import test from 'node:test';
import assert from 'node:assert/strict';
import {environmentPreset} from '../src/sceneEnvironment.ts';
import {validEnvironmentFog,sceneWithEnvironment,environmentPlaybackReset} from '../src/sceneEnvironmentEditing.ts';
import {sceneHistory,commitScene,undoScene,redoScene,hasSceneChanges} from '../src/sceneState.ts';
const snapshot=()=>({displayName:'Scene',coordinateFrame:{mode:'local_plane'},terrain:null,instances:[],initialView:{eye:[80,60,90],target:[0,15,0]},defaults:{background:'sky',lighting:'dusk',terrainMaterial:'solid'}});
test('environment changes immediately enter the saveable draft and support undo and redo',()=>{
 const source=snapshot(),environment=environmentPreset('dusk-v1');
 let history=commitScene(sceneHistory(source),sceneWithEnvironment(source,environment));
 assert.equal(hasSceneChanges(source,history.present),true);assert.equal(history.present.environment.presetId,'dusk-v1');
 assert.deepEqual(history.present.initialView,source.initialView);assert.deepEqual(history.present.instances,source.instances);
 environment.color.exposure=2.4;assert.notEqual(history.present.environment.color.exposure,2.4);
 history=undoScene(history);assert.deepEqual(history.present,source);assert.equal(hasSceneChanges(source,history.present),false);
 history=redoScene(history);assert.equal(history.present.environment.presetId,'dusk-v1');
 const restored=sceneWithEnvironment(history.present,null);assert.equal(restored.environment,null);assert.deepEqual(restored.initialView,source.initialView);
});
test('invalid fog ranges cannot enter the rendered scene draft or a save',()=>{
 const value=environmentPreset('land-day-v1');value.atmosphere.fog.nearM=value.atmosphere.fog.farM;
 assert.equal(validEnvironmentFog(value),false);assert.throws(()=>sceneWithEnvironment(snapshot(),value));
 value.atmosphere.fog.farM++;assert.equal(validEnvironmentFog(value),true);assert.equal(validEnvironmentFog(null),true);
});
test('explicit default playback edits reset only their own personal pause, unrelated changes preserve it',()=>{
 const source=environmentPreset('land-day-v1'),next=structuredClone(source);next.presetId='custom-v1';next.color.exposure=1.4;
 assert.deepEqual(environmentPlaybackReset(source,next),{water:false,clouds:false});
 next.animation.defaultPlayback=source.animation.defaultPlayback==='playing'?'paused':'playing';
 assert.deepEqual(environmentPlaybackReset(source,next),{water:true,clouds:false});
 next.atmosphere.clouds.defaultPlayback=source.atmosphere.clouds.defaultPlayback==='playing'?'paused':'playing';
 assert.deepEqual(environmentPlaybackReset(source,next),{water:true,clouds:true});
 assert.deepEqual(environmentPlaybackReset(source,environmentPreset('dusk-v1')),{water:true,clouds:true});
});
