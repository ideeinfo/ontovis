import {ApiError} from './api.ts';
import type {SceneApi} from './sceneApi.ts';
import type {LegacySceneEntry,LegacySceneEntryTarget,SceneOpen} from './sceneTypes.ts';

function target(value:LegacySceneEntry):LegacySceneEntryTarget|null {
  if(value.available&&value.migrated&&value.entry&&
    [value.entry.sceneId,value.entry.sceneRevision,value.entry.registeredSceneRevision,value.entry.sceneModelInstanceId]
      .every(item=>typeof item==='string'&&item.length>0))return {...value.entry};
  if(value.available===false&&value.migrated===false&&value.legacyReadOnly===false&&value.entry===null&&value.reason==='NOT_REGISTERED')return null;
  throw new ApiError(409,'LEGACY_SCENE_ENTRY_UNAVAILABLE');
}

/** A later legacy preview or navigation invalidates the entire earlier lookup. */
export class LegacySceneEntryReader {
  private pending:AbortController|null=null;
  private readonly client:Pick<SceneApi,'legacyEntry'>;
  constructor(client:Pick<SceneApi,'legacyEntry'>){this.client=client;}
  cancel(){this.pending?.abort();this.pending=null;}
  async read(modelVersionId:string|null):Promise<LegacySceneEntryTarget|null> {
    this.cancel();const abort=new AbortController();this.pending=abort;
    try{
      const value=await this.client.legacyEntry(modelVersionId===null?{}:
        {sourceKind:'uploaded_version',sourceKey:modelVersionId},abort.signal);
      if(abort.signal.aborted||this.pending!==abort)throw new DOMException('Legacy entry changed','AbortError');
      return target(value);
    }finally{if(this.pending===abort)this.pending=null;}
  }
}

export function legacyEntryInstance(value:SceneOpen,entry:LegacySceneEntryTarget):string {
  if(value.sceneId!==entry.sceneId||value.sceneRevision!==entry.sceneRevision||
    value.snapshot.instances.filter(item=>item.sceneModelInstanceId===entry.sceneModelInstanceId).length!==1)
    throw new ApiError(409,'LEGACY_SCENE_ENTRY_UNAVAILABLE');
  return entry.sceneModelInstanceId;
}
