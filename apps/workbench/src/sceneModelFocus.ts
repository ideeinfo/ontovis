import {Box3,Box3Helper,MathUtils,Vector3,type Object3D,type PerspectiveCamera} from 'three';
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

export class SceneModelSelectionBoxes {
  readonly helpers=new Map<string,Box3Helper>();
  private readonly parent:Object3D;
  constructor(parent:Object3D){this.parent=parent;}
  private release(id:string,helper:Box3Helper):void {
    this.parent.remove(helper);helper.geometry.dispose();
    for(const material of Array.isArray(helper.material)?helper.material:[helper.material])material.dispose();
    this.helpers.delete(id);
  }
  update(entries:ReadonlyMap<string,{root:Object3D}>,ids:string[]):void {
    const selected=new Set(ids);if(selected.size<=1)selected.clear();
    for(const [id,helper] of this.helpers)if(!selected.has(id)||!entries.get(id)?.root.visible){
      this.release(id,helper);
    }
    for(const id of selected){
      const root=entries.get(id)?.root;if(!root?.visible)continue;
      let helper=this.helpers.get(id);
      if(!helper){
        helper=new Box3Helper(new Box3(),0x38ad97);helper.renderOrder=1;
        for(const material of Array.isArray(helper.material)?helper.material:[helper.material]){material.depthTest=false;material.depthWrite=false;}
        this.helpers.set(id,helper);this.parent.add(helper);
      }
      root.updateWorldMatrix(true,true);helper.box.setFromObject(root);helper.updateMatrixWorld(true);
    }
  }
  dispose():void {
    for(const [id,helper] of this.helpers)this.release(id,helper);
    this.helpers.clear();
  }
}
