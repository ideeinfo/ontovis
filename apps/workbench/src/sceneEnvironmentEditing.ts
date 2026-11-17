import type {SceneEnvironmentV1} from './sceneEnvironment';
import type {EditableSceneSnapshot} from './sceneTypes';

export function validEnvironmentFog(value:SceneEnvironmentV1|null|undefined):boolean {
  return !value||value.atmosphere.fog.farM>value.atmosphere.fog.nearM;
}
export function sceneWithEnvironment(snapshot:EditableSceneSnapshot,value:SceneEnvironmentV1|null):EditableSceneSnapshot {
  if(!validEnvironmentFog(value))throw new Error('INVALID_ENVIRONMENT');
  return {...snapshot,environment:structuredClone(value)};
}
export function environmentPlaybackReset(previous:SceneEnvironmentV1|null|undefined,next:SceneEnvironmentV1|null|undefined) {
  const preset=previous?.presetId!==next?.presetId&&next?.presetId!=='custom-v1';
  return {water:preset||previous?.animation.defaultPlayback!==next?.animation.defaultPlayback,
    clouds:preset||previous?.atmosphere.clouds?.defaultPlayback!==next?.atmosphere.clouds?.defaultPlayback};
}
