import * as THREE from 'three';

type DisposeListener=(event:THREE.Event<'dispose',THREE.Texture>)=>void;
let registeringRenderer:symbol|null=null;

/** Three r184 keeps its shared DFG_LUT alive after renderer.dispose(). */
export function prepareSceneRenderer(renderer:THREE.WebGLRenderer):THREE.WebGLRenderer {
  const owner=Symbol(),owned=new Map<THREE.Texture,Set<DisposeListener>>();
  const render=renderer.render.bind(renderer),dispose=renderer.dispose.bind(renderer);
  let disposed=false;
  renderer.render=(scene,camera)=>{
    if(disposed)return;
    const add=THREE.Texture.prototype.addEventListener,previous=registeringRenderer;
    registeringRenderer=owner;
    // Registrations are synchronous. Restore the prototype even if rendering fails,
    // and attribute nested renders only to their own renderer.
    THREE.Texture.prototype.addEventListener=function(type,listener){
      Reflect.apply(add,this,[type,listener]);
      if(registeringRenderer===owner&&type==='dispose'&&this instanceof THREE.DataTexture
        &&this.name==='DFG_LUT'&&this.format===THREE.RGFormat&&this.type===THREE.HalfFloatType
        &&this.image.width===16&&this.image.height===16){
        let callbacks=owned.get(this);if(!callbacks){callbacks=new Set();owned.set(this,callbacks);}
        callbacks.add(listener as DisposeListener);
      }
    };
    try {render(scene,camera);}
    finally {THREE.Texture.prototype.addEventListener=add;registeringRenderer=previous;}
  };
  renderer.dispose=()=>{
    if(disposed)return;disposed=true;
    try {
      for(const [texture,callbacks] of owned)for(const callback of callbacks){
        // Invoke only this renderer's texture deallocator, before properties.dispose().
        // A global texture.dispose() would also evict other live viewports' allocations.
        try {callback.call(texture,{type:'dispose',target:texture});}
        finally {texture.removeEventListener('dispose',callback);}
      }
    } finally {owned.clear();dispose();}
  };
  return renderer;
}
