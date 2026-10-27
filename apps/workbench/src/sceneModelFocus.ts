import {Box3,MathUtils,Vector3,type Object3D,type PerspectiveCamera} from 'three';
import type {SceneView,Vector3 as SceneVector3} from './sceneTypes';

/** Selected models define their own frame; a regional terrain must not dilute it. */
export function selectedModelBounds(entries:ReadonlyMap<string,{root:Object3D}>,ids:string[]):Box3 {
  const box=new Box3();
  for(const id of new Set(ids)){
    const root=entries.get(id)?.root;
    if(root?.visible){root.updateWorldMatrix(true,true);box.union(new Box3().setFromObject(root));}
  }
  return box;
}
export function selectedModelView(camera:PerspectiveCamera,box:Box3,direction:Vector3):SceneView|null {
  if(box.isEmpty())return null;
  const center=box.getCenter(new Vector3()),radius=box.getSize(new Vector3()).length()/2;
  const halfFov=MathUtils.degToRad(camera.fov/2),horizontal=Math.atan(Math.tan(halfFov)*camera.aspect);
  const distance=Math.max(3,radius/Math.sin(Math.min(halfFov,horizontal))*1.15);
  const axis=direction.clone();if(axis.lengthSq()<1e-12)axis.set(.9,.55,1.2);
  return {eye:center.clone().add(axis.normalize().multiplyScalar(distance)).toArray() as SceneVector3,
    target:center.toArray() as SceneVector3};
}
