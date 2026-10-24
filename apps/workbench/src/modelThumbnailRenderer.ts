import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {prepareSceneRenderer} from './sceneRenderer';

/** A fixed resource view, independent of scene placement or installed identity. */
export async function renderModelThumbnail(bytes:ArrayBuffer) {
  const manager=new THREE.LoadingManager();let textureFailed=false;
  manager.setURLModifier(url=>{if(!url.startsWith('blob:'))throw new Error('THUMBNAIL_EXTERNAL_RESOURCE');return url;});
  manager.onError=()=>{textureFailed=true;};
  const model=(await new GLTFLoader(manager).parseAsync(bytes,'')).scene;
  let renderer:THREE.WebGLRenderer|null=null;
  try {
    if(textureFailed)throw new Error('THUMBNAIL_TEXTURE_FAILED');
    model.updateMatrixWorld(true);
    const box=new THREE.Box3().setFromObject(model),center=box.getCenter(new THREE.Vector3());
    const radius=box.getSize(new THREE.Vector3()).length()/2;
    if(box.isEmpty()||!Number.isFinite(radius)||radius<=0)throw new Error('THUMBNAIL_EMPTY_MODEL');
    const camera=new THREE.OrthographicCamera(-1,1,1,-1,.01,Math.max(10,radius*10));
    camera.position.copy(center).add(new THREE.Vector3(1,.45,1.5).normalize().multiplyScalar(radius*3+1));
    camera.lookAt(center);camera.updateMatrixWorld(true);
    let horizontal=0,vertical=0;
    for(const x of [box.min.x,box.max.x])for(const y of [box.min.y,box.max.y])for(const z of [box.min.z,box.max.z]) {
      const point=new THREE.Vector3(x,y,z).applyMatrix4(camera.matrixWorldInverse);
      horizontal=Math.max(horizontal,Math.abs(point.x));vertical=Math.max(vertical,Math.abs(point.y));
    }
    const extent=Math.max(horizontal,vertical)*1.12;
    camera.left=camera.bottom=-extent;camera.right=camera.top=extent;camera.updateProjectionMatrix();
    const scene=new THREE.Scene();scene.add(model,new THREE.HemisphereLight(0xffffff,0x718275,3));
    const sun=new THREE.DirectionalLight(0xffffff,2.5);
    sun.position.copy(center).add(new THREE.Vector3(2,3,4).multiplyScalar(radius));scene.add(sun);
    renderer=prepareSceneRenderer(new THREE.WebGLRenderer({alpha:true,antialias:true,preserveDrawingBuffer:true}));
    renderer.setPixelRatio(1);renderer.setSize(256,256);renderer.setClearColor(0x000000,0);
    renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;
    renderer.render(scene,camera);
    const gl=renderer.getContext(),pixels=new Uint8Array(256*256*4);
    gl.readPixels(0,0,256,256,gl.RGBA,gl.UNSIGNED_BYTE,pixels);
    let coveredPixels=0;for(let index=3;index<pixels.length;index+=4)if(pixels[index]>0)coveredPixels++;
    if(coveredPixels<16||gl.getError()!==gl.NO_ERROR)throw new Error('THUMBNAIL_EMPTY_RENDER');
    return {png:renderer.domElement.toDataURL('image/png').split(',')[1],coveredPixels,width:256,height:256};
  } finally {
    const released=new Set<object>();
    model.traverse(node=>{
      if(!(node instanceof THREE.Mesh||node instanceof THREE.Line||node instanceof THREE.Points))return;
      if(!released.has(node.geometry)){released.add(node.geometry);node.geometry.dispose();}
      for(const material of Array.isArray(node.material)?node.material:[node.material]) {
        if(released.has(material))continue;released.add(material);
        for(const value of Object.values(material))if(value instanceof THREE.Texture&&!released.has(value)) {
          released.add(value);const image=value.image as {close?:()=>void}|null;
          if(image&&typeof image.close==='function'&&!released.has(image)){released.add(image);image.close();}
          value.dispose();
        }
        material.dispose();
      }
    });
    renderer?.dispose();renderer?.forceContextLoss();
  }
}

Object.assign(window,{ontoVisThumbnail:async()=>{
  const response=await fetch(new URL('model.glb',location.href));
  if(!response.ok)throw new Error('THUMBNAIL_SOURCE_UNAVAILABLE');
  return renderModelThumbnail(await response.arrayBuffer());
}});
