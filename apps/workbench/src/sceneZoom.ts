import type {SceneView,Vector3} from './sceneTypes';

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
