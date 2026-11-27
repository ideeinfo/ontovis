import type {ModelResourceRef, SceneModelInstance} from './sceneTypes';

export interface SceneResourceGroup {
  key:string;modelAssetId:string|null;instanceCount:number;
  versions:{modelVersionId:string;instances:SceneModelInstance[]}[];
}

/** Derived display groups never change the instance identities or fixed model references. */
export function sceneResourceGroups(instances:SceneModelInstance[],refs:ModelResourceRef[]):SceneResourceGroup[] {
  const assets=new Map(refs.map(ref=>[ref.modelVersionId,ref.modelAssetId]));
  const groups=new Map<string,SceneResourceGroup>();
  for(const instance of instances){
    const modelAssetId=assets.get(instance.modelVersionId)||null,key=modelAssetId||`version:${instance.modelVersionId}`;
    let group=groups.get(key);
    if(!group){group={key,modelAssetId,instanceCount:0,versions:[]};groups.set(key,group);}
    let version=group.versions.find(item=>item.modelVersionId===instance.modelVersionId);
    if(!version){version={modelVersionId:instance.modelVersionId,instances:[]};group.versions.push(version);}
    version.instances.push(instance);group.instanceCount++;
  }
  return [...groups.values()];
}
