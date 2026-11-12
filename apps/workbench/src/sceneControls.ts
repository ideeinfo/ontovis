import type {Camera} from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';

export function createSceneControls(camera:Camera,canvas:HTMLElement) {
  const root=canvas.getRootNode(),orbit=new OrbitControls(camera,canvas);
  // three r184 removes keydown from the current root and omits its pending
  // Control keyup listener. React may already have detached the canvas here.
  const down:unknown=Reflect.get(orbit,'_interceptControlDown'),up:unknown=Reflect.get(orbit,'_interceptControlUp');
  if(typeof down!=='function'||typeof up!=='function'){
    orbit.dispose();throw new Error('Unsupported OrbitControls keyboard lifecycle');
  }
  let disposed=false;
  return {orbit,dispose:()=>{
    if(disposed)return;disposed=true;
    root.removeEventListener('keydown',down as EventListener,{capture:true});
    root.removeEventListener('keyup',up as EventListener,{capture:true});
    orbit.dispose();
  }};
}
