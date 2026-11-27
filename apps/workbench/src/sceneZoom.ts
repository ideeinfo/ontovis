import type {SceneView,Vector3} from './sceneTypes';
import type {Intersection,Mesh,Object3D} from 'three';

export function visibleZoomHit<T extends Pick<Intersection,'object'|'face'>>(hits:readonly T[]):T|undefined {
  return hits.find(hit=>{
    let node:Object3D|null=hit.object;
    while(node){if(!node.visible)return false;node=node.parent;}
    const material=(hit.object as Mesh).material;
    return (Array.isArray(material)?material[hit.face?.materialIndex??0]:material)?.visible!==false;
  });
}

/** Rebase the orbit distance on the visible surface, preserving view direction. */
export function cursorZoomView(view:SceneView,ray:Vector3,factor:number,hitDistance?:number):SceneView {
  const forward=view.target.map((v,i)=>v-view.eye[i]) as Vector3;
  const radius=Math.hypot(...forward),rayLength=Math.hypot(...ray);
  if(!Number.isFinite(factor)||factor<=0||!radius||!rayLength)return view;
  const distance=Math.max(.1,Math.min(300_000,hitDistance??radius));
  const next=Math.max(.1,Math.min(300_000,distance*factor));
  const eye=view.eye.map((v,i)=>v+ray[i]/rayLength*(distance-next)) as Vector3;
  return {eye,target:eye.map((v,i)=>v+forward[i]/radius*next) as Vector3};
}
