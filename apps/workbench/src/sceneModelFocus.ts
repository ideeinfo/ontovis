import {Box3,Box3Helper,MathUtils,Raycaster,Vector3,type Object3D,type PerspectiveCamera} from 'three';
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

/** Only the original terrain constrains an inspection camera; visual horizon extensions do not. */
export function terrainSafeView(view:SceneView,terrain:Object3D|null):SceneView {
  if(!terrain?.visible)return view;
  terrain.updateWorldMatrix(true,false);
  const eye=new Vector3(...view.eye),target=new Vector3(...view.target),box=new Box3().setFromObject(terrain);
  if(box.isEmpty())return view;
  const clearance=Math.max(2,eye.distanceTo(target)*.015),ray=new Raycaster();
  ray.set(new Vector3(eye.x,Math.max(box.max.y,eye.y)+clearance,eye.z),new Vector3(0,-1,0));
  const ground=ray.intersectObject(terrain,false)[0];
  if(ground)eye.y=Math.max(eye.y,ground.point.y+clearance);
  const step=Math.max(clearance,Math.hypot(eye.x-target.x,eye.z-target.z)*.2);
  for(let i=0;i<8;i++){
    const direction=target.clone().sub(eye),distance=direction.length();
    ray.set(eye,direction.normalize());ray.near=0;ray.far=Math.max(0,distance-.5);
    if(!ray.intersectObject(terrain,false).length)break;
    eye.y+=step;
  }
  return {eye:eye.toArray() as SceneVector3,target:[...view.target]};
}

/** Arrival shows a central group at equipment scale; fit-all remains an explicit overview action. */
export function arrivalModelView(camera:PerspectiveCamera,entries:ReadonlyMap<string,{root:Object3D}>,ids:string[],direction:Vector3):SceneView|null {
  const models=[...new Set(ids)].flatMap(id=>{const bounds=selectedModelBounds(entries,[id]);return bounds.isEmpty()?[]:[{id,bounds,center:bounds.getCenter(new Vector3())}];});
  if(!models.length)return null;
  const median=(axis:'x'|'z')=>models.map(item=>item.center[axis]).sort((a,b)=>a-b)[Math.floor(models.length/2)];
  const center=new Vector3(median('x'),0,median('z'));
  const anchor=[...models].sort((a,b)=>Math.hypot(a.center.x-center.x,a.center.z-center.z)-Math.hypot(b.center.x-center.x,b.center.z-center.z))[0].center;
  const nearest=models.sort((a,b)=>a.center.distanceToSquared(anchor)-b.center.distanceToSquared(anchor)).slice(0,3);
  const box=new Box3();for(const item of nearest)box.union(item.bounds);
  const axis=direction.clone();if(Math.hypot(axis.x,axis.z)<1e-6)axis.set(.9,0,1.2);axis.y=Math.hypot(axis.x,axis.z)*.35;
  return selectedModelView(camera,box,axis);
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
