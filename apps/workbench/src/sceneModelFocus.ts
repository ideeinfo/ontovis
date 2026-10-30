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
export function terrainSafeView(view:SceneView,terrain:Object3D|null,checkSightline=true):SceneView {
  if(!terrain?.visible)return view;
  terrain.updateWorldMatrix(true,false);
  const eye=new Vector3(...view.eye),target=new Vector3(...view.target),box=new Box3().setFromObject(terrain);
  if(box.isEmpty())return view;
  const clearance=Math.max(2,eye.distanceTo(target)*.015),ray=new Raycaster();
  ray.set(new Vector3(eye.x,Math.max(box.max.y,eye.y)+clearance,eye.z),new Vector3(0,-1,0));
  const ground=ray.intersectObject(terrain,false)[0];
  if(ground)eye.y=Math.max(eye.y,ground.point.y+clearance);
  if(!checkSightline)return {eye:eye.toArray() as SceneVector3,target:[...view.target]};
  const step=Math.max(clearance,Math.hypot(eye.x-target.x,eye.z-target.z)*.2);
  for(let i=0;i<8;i++){
    const direction=target.clone().sub(eye),distance=direction.length();
    ray.set(eye,direction.normalize());ray.near=0;ray.far=Math.max(0,distance-.5);
    if(!ray.intersectObject(terrain,false).length)break;
    eye.y+=step;
  }
  return {eye:eye.toArray() as SceneVector3,target:[...view.target]};
}

export interface OverviewFrame {left:number;right:number;top:number;bottom:number}
const emptyFrame:OverviewFrame={left:0,right:0,top:0,bottom:0};

/** Fit the complete asset bounds inside the unobstructed screen area, rather than the terrain. */
function framedModelView(camera:PerspectiveCamera,boxes:Box3[],direction:Vector3,frame:OverviewFrame,minimum=3):SceneView|null {
  if(!boxes.length)return null;
  const inset=(value:number)=>Number.isFinite(value)?Math.max(0,Math.min(.44,value)):0;
  const left=inset(frame.left),rightInset=inset(frame.right),top=inset(frame.top),bottom=inset(frame.bottom);
  const halfX=1-left-rightInset,halfY=1-top-bottom,cx=left-rightInset,cy=bottom-top;
  const tanY=Math.tan(MathUtils.degToRad(camera.fov/2)),tanX=tanY*camera.aspect;
  const axis=direction.clone().normalize(),right=new Vector3(0,1,0).cross(axis).normalize(),up=axis.clone().cross(right).normalize();
  const union=new Box3();for(const box of boxes)union.union(box);
  const center=union.getCenter(new Vector3()),corners:{x:number;y:number;z:number}[]=[];
  let distance=minimum;
  for(const box of boxes)for(const x of [box.min.x,box.max.x])for(const y of [box.min.y,box.max.y])for(const z of [box.min.z,box.max.z]){
    const delta=new Vector3(x,y,z).sub(center);
    const point={x:delta.dot(right)/tanX,y:delta.dot(up)/tanY,z:delta.dot(axis)};
    corners.push(point);distance=Math.max(distance,point.z+camera.near*2);
  }
  const minX=cx-halfX,maxX=cx+halfX,minY=cy-halfY,maxY=cy+halfY;
  distance=Math.max(distance,
    (Math.max(...corners.map(p=>maxX*p.z+p.x))-Math.min(...corners.map(p=>minX*p.z+p.x)))/(2*halfX),
    (Math.max(...corners.map(p=>maxY*p.z+p.y))-Math.min(...corners.map(p=>minY*p.z+p.y)))/(2*halfY));
  distance*=1.06;
  const shiftX=(Math.max(...corners.map(p=>minX*(distance-p.z)-p.x))+Math.min(...corners.map(p=>maxX*(distance-p.z)-p.x)))/2;
  const shiftY=(Math.max(...corners.map(p=>minY*(distance-p.z)-p.y))+Math.min(...corners.map(p=>maxY*(distance-p.z)-p.y)))/2;
  const target=center.clone().addScaledVector(right,-shiftX*tanX).addScaledVector(up,-shiftY*tanY);
  return {eye:target.clone().addScaledVector(axis,distance).toArray() as SceneVector3,target:target.toArray() as SceneVector3};
}

export function arrivalModelView(camera:PerspectiveCamera,entries:ReadonlyMap<string,{root:Object3D}>,ids:string[],direction:Vector3,frame:OverviewFrame=emptyFrame,terrain:Object3D|null=null):SceneView|null {
  const boxes=[...new Set(ids)].map(id=>selectedModelBounds(entries,[id])).filter(box=>!box.isEmpty());if(!boxes.length)return null;
  const axis=direction.clone();if(Math.hypot(axis.x,axis.z)<1e-6)axis.set(.9,0,1.2);
  axis.y=Math.hypot(axis.x,axis.z)*.55;
  let destination=framedModelView(camera,boxes,axis,frame);
  for(let i=0;destination&&i<4;i++){
    // A farm's framing target can lie inside a ridge between units. Keep the eye clear without chasing that underground sightline.
    const safe=terrainSafeView(destination,terrain,false);
    if(safe.eye.every((value,index)=>Math.abs(value-destination!.eye[index])<1e-6))return destination;
    const delta=new Vector3(...safe.eye).sub(new Vector3(...safe.target));
    destination=framedModelView(camera,boxes,delta,frame,delta.length());
  }
  return destination;
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
