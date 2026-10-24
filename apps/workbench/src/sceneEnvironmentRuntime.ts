import * as THREE from 'three';
import {SceneSurroundings} from './sceneSurroundings.ts';
import {EnvironmentClock,type SceneEnvironmentV1} from './sceneEnvironment.ts';
import {trueHeadingToThreeYaw} from './sceneTransforms.ts';
import type {CoordinateFrame} from './sceneTypes';
import {rippleNormals,waterMaterial} from './sceneWater.ts';
export {rippleNormals} from './sceneWater.ts';
function skyTexture(top:string,horizon:string){
  const width=1024,height=512,data=new Uint8Array(width*height*4),a=new THREE.Color(top),b=new THREE.Color(horizon);
  for(let y=0;y<height;y++){
    const up=Math.cos(Math.PI*(1-y/(height-1))),c=b.clone().lerp(a,Math.max(0,up)**.6).convertLinearToSRGB();
    for(let x=0;x<width;x++)data.set([Math.round(c.r*255),Math.round(c.g*255),Math.round(c.b*255),255],(y*width+x)*4);
  }
  const texture=new THREE.DataTexture(data,width,height);texture.mapping=THREE.EquirectangularReflectionMapping;
  texture.minFilter=texture.magFilter=THREE.LinearFilter;texture.colorSpace=THREE.SRGBColorSpace;texture.needsUpdate=true;return texture;
}
export function shadowCandidates(roots:THREE.Group[],target:THREE.Vector3,radius:number,selected:THREE.Group|null){
  const candidates=roots.filter(r=>r.visible).map(root=>({root,distance:new THREE.Box3().setFromObject(root).getCenter(new THREE.Vector3()).distanceTo(target)}))
    .filter(r=>r.distance<=radius).sort((a,b)=>(a.root===selected?-1:b.root===selected?1:a.distance-b.distance));
  let triangles=0;const accepted:THREE.Group[]=[];
  for(const {root} of candidates){let count=0;root.traverse(o=>{if(o instanceof THREE.Mesh&&o.visible)count+=(o.geometry.index?.count??o.geometry.getAttribute('position')?.count??0)/3*(o instanceof THREE.InstancedMesh?o.count:1);});
    if(accepted.length<8&&count+triangles<=250000){accepted.push(root);triangles+=count;}}
  return {roots:accepted,triangles};
}
/** Every texture/target belongs to this viewport; shared GLB geometry/materials stay untouched. */
export class SceneEnvironmentRuntime {
  private sky:THREE.DataTexture|null=null;private target:THREE.WebGLRenderTarget|null=null;private generator:THREE.PMREMGenerator|null=null;
  private water:THREE.Mesh<THREE.BufferGeometry,THREE.MeshStandardMaterial>|null=null;private normals:THREE.DataTexture|null=null;
  private waterPattern:ReturnType<typeof waterMaterial>|null=null;
  private skyKey='';private terrain:THREE.Mesh|null=null;private waterSeed=-1;private waterFrame='';private clockKey='';
  private config:SceneEnvironmentV1|null=null;private frame:CoordinateFrame|null=null;
  private clock=new EnvironmentClock();private lastWave=-Infinity;private dirtyShadow=true;private shadowAnchor=new THREE.Vector3(Infinity,Infinity,Infinity);
  private ownedShadow=new Map<THREE.Mesh,{cast:boolean;receive:boolean}>();private casterCount=0;
  private sunHeading=0;private waveHeading=0;
  private roots:THREE.Group[]=[];private selected:THREE.Group|null=null;private fallback=false;
  private previewClock:{clock:EnvironmentClock;key:string}|null=null;
  private disposed=false;private surroundings:SceneSurroundings;
  private scene:THREE.Scene;private renderer:THREE.WebGLRenderer;private sun:THREE.DirectionalLight;private hemisphere:THREE.HemisphereLight;
  private ground:THREE.MeshStandardMaterial;private grass:THREE.Texture;
  constructor(scene:THREE.Scene,renderer:THREE.WebGLRenderer,sun:THREE.DirectionalLight,hemisphere:THREE.HemisphereLight,ground:THREE.MeshStandardMaterial,grass:THREE.Texture){
    this.scene=scene;this.renderer=renderer;this.sun=sun;this.hemisphere=hemisphere;this.ground=ground;this.grass=grass;this.surroundings=new SceneSurroundings(scene);scene.add(sun.target);
  }
  private releaseSky(){this.scene.environment=null;this.target?.dispose();this.target=null;this.sky?.dispose();this.sky=null;this.skyKey='';}
  private releaseWater(){this.water?.removeFromParent();this.water?.geometry.dispose();this.water?.material.dispose();this.water=null;this.waterPattern=null;this.normals?.dispose();this.normals=null;this.terrain=null;this.waterSeed=-1;}
  private releaseShadow(){this.sun.castShadow=false;this.renderer.shadowMap.enabled=false;this.sun.shadow.dispose();this.sun.shadow.map=null;this.sun.shadow.mapPass=null;this.casterCount=0;}
  preview(active:boolean){
    if(active&&!this.previewClock){this.previewClock={clock:this.clock,key:this.clockKey};this.clock=new EnvironmentClock(this.clock.value());}
    if(!active&&this.previewClock){this.clock=this.previewClock.clock;this.clockKey=this.previewClock.key;this.clock.suspend();this.previewClock=null;this.lastWave=-Infinity;}
  }
  private casters(target:THREE.Vector3,radius:number){
    const allowed=shadowCandidates(this.roots,target,radius,this.selected),ids=new Set(allowed.roots);this.casterCount=ids.size;
    const live=new Set<THREE.Mesh>();for(const root of this.roots)root.traverse(o=>{if(o instanceof THREE.Mesh)live.add(o);});
    for(const [mesh,p] of this.ownedShadow)if(!live.has(mesh)){mesh.castShadow=p.cast;mesh.receiveShadow=p.receive;this.ownedShadow.delete(mesh);}
    // Distant instances need neither shadow sampling nor another shadow shader variant.
    for(const root of this.roots)root.traverse(o=>{if(o instanceof THREE.Mesh){if(!this.ownedShadow.has(o))this.ownedShadow.set(o,{cast:o.castShadow,receive:o.receiveShadow});o.castShadow=ids.has(root);o.receiveShadow=ids.has(root);}});
  }
  configure(value:SceneEnvironmentV1|null,frame:CoordinateFrame,terrain:THREE.Mesh|null,roots:THREE.Group[],selected:THREE.Group|null,visible:boolean){
    if(this.disposed)return false;this.config=value;this.frame=frame;this.roots=roots;this.selected=selected;this.dirtyShadow=true;
    if(!value){
      this.surroundings.dispose();this.releaseSky();this.releaseWater();this.releaseShadow();this.fallback=false;this.sun.target.position.set(0,0,0);this.scene.fog=null;this.scene.environmentIntensity=1;
      this.renderer.toneMapping=THREE.NoToneMapping;this.renderer.toneMappingExposure=1;this.ground.roughness=1;this.grass.repeat.set(1,1);
      for(const [mesh,prior] of this.ownedShadow){mesh.castShadow=prior.cast;mesh.receiveShadow=prior.receive;}this.ownedShadow.clear();return false;
    }
    const geo=frame.mode==='projected_site'?frame.anchor.geographicAnchor:undefined;
    this.sunHeading=-trueHeadingToThreeYaw(frame,value.lighting.sun.azimuthDeg,geo?.[0],geo?.[1]);this.waveHeading=-trueHeadingToThreeYaw(frame,value.water.travelHeadingDeg,geo?.[0],geo?.[1]);
    this.renderer.toneMapping=value.color.toneMapping==='aces'?THREE.ACESFilmicToneMapping:THREE.NoToneMapping;this.renderer.toneMappingExposure=value.color.exposure;
    this.hemisphere.intensity=value.lighting.hemisphereIntensity;this.sun.color.set(value.lighting.sun.color);this.sun.intensity=value.lighting.sun.enabled?value.lighting.sun.intensity:0;
    this.scene.environmentIntensity=value.lighting.environment.intensity;
    const fog=value.atmosphere.fog;this.scene.fog=fog.mode==='linear'?new THREE.Fog(value.atmosphere.horizonColor,fog.nearM,fog.farM):null;
    // Upload/generate only on a visible render, never while the document is hidden.
    const key=JSON.stringify([value.atmosphere.topColor,value.atmosphere.horizonColor]);
    if(key!==this.skyKey&&!document.hidden){
      this.releaseSky();this.fallback=false;
      try{
        this.sky=skyTexture(value.atmosphere.topColor,value.atmosphere.horizonColor);
        this.generator??=new THREE.PMREMGenerator(this.renderer);this.target=this.generator.fromEquirectangular(this.sky);
      }catch{
        this.releaseSky();this.generator?.dispose();this.generator=null;this.fallback=true;
      }
      this.skyKey=key;
    }
    if(this.sky){this.scene.background=this.sky;this.scene.environment=this.target?.texture??null;}
    else if(this.fallback)this.scene.background=new THREE.Color(value.atmosphere.horizonColor);
    this.ground.roughness=value.surface.terrainRoughness;this.grass.repeat.setScalar(30/value.surface.textureRepeatM);
    const enabled=value.water.enabled&&visible&&!!terrain&&frame.mode==='projected_site'&&frame.verticalDatum==='UNKNOWN_RELATIVE';
    if(!enabled)this.releaseWater();
    else if(terrain!==this.terrain||this.waterSeed!==value.water.seed||this.waterFrame!==frame.frameRevision){
      this.releaseWater();terrain.geometry.computeBoundingBox();const box=terrain.geometry.boundingBox;
      if(box&&box.max.y-box.min.y<=.0001){
        const geometry=terrain.geometry.clone(),positions=geometry.getAttribute('position'),uv=new Float32Array(positions.count*2);
        for(let i=0;i<positions.count;i++){uv[i*2]=positions.getX(i);uv[i*2+1]=-positions.getZ(i);}geometry.setAttribute('uv',new THREE.BufferAttribute(uv,2));
        this.normals=rippleNormals(value.water.seed);this.normals.anisotropy=Math.min(4,this.renderer.capabilities.getMaxAnisotropy());
        this.waterPattern=waterMaterial(this.normals);const material=this.waterPattern.material;
        this.water=new THREE.Mesh(geometry,material);this.water.name='visual-water-not-placement';this.water.receiveShadow=true;
        terrain.updateMatrixWorld(true);this.water.matrixAutoUpdate=false;this.water.matrix.copy(terrain.matrixWorld);this.scene.add(this.water);this.terrain=terrain;this.waterSeed=value.water.seed;this.waterFrame=frame.frameRevision;
      }
    }
    if(this.water){this.water.visible=enabled;this.water.material.color.set(value.water.color);this.water.material.roughness=value.water.roughness;this.water.material.normalScale.setScalar(value.water.rippleStrength);}
    this.surroundings.configure(value,terrain,this.water?this.normals:null,visible);
    const phaseKey=JSON.stringify([value.animation.initialPhase,frame.frameRevision,value.water.seed]);
    if(phaseKey!==this.clockKey){this.clock=new EnvironmentClock(value.animation.initialPhase);this.clockKey=phaseKey;this.lastWave=-Infinity;}
    this.waterPattern?.update(this.clock.value(),value.water.wavelengthM,value.water.travelSpeedMps,this.waveHeading);
    this.surroundings.update(this.clock.value(),value,this.waveHeading);
    const shadows=value.shadows.mode==='sun-local'&&value.lighting.sun.enabled&&!this.fallback;
    if(!shadows)this.releaseShadow();else{
      this.renderer.shadowMap.enabled=true;this.renderer.shadowMap.type=THREE.PCFShadowMap;this.renderer.shadowMap.autoUpdate=false;
      this.sun.castShadow=true;this.sun.shadow.mapSize.set(1024,1024);this.sun.shadow.autoUpdate=false;this.sun.shadow.bias=-.00015;this.sun.shadow.normalBias=.12;
      const target=selected?new THREE.Box3().setFromObject(selected).getCenter(new THREE.Vector3()):this.sun.target.position;
      this.casters(target,value.shadows.radiusM);
      if(terrain)terrain.receiveShadow=true;this.dirtyShadow=true;
    }
    return !!this.water&&enabled;
  }
  playing(override:boolean|null,reduced:boolean){return !this.fallback&&!!this.water&&!!this.config&&this.config.water.travelSpeedMps>0&&this.config.water.rippleStrength>0&&(override??(!reduced&&this.config.animation.defaultPlayback==='playing'));}
  suspend(){this.clock.suspend();this.lastWave=-Infinity;}
  beforeRender(now:number,target:THREE.Vector3,playing:boolean){
    const e=this.config;if(!e||!this.frame)return false;
    // Local shadows follow the current interest point without covering a whole wind farm.
    const radius=e.shadows.radiusM,anchor=this.sun.target.position;
    if(this.dirtyShadow||this.shadowAnchor.distanceTo(target)>radius*.2){
      anchor.copy(target);
      const heading=this.sunHeading,alt=THREE.MathUtils.degToRad(e.lighting.sun.elevationDeg),distance=radius*3;
      this.sun.position.copy(anchor).add(new THREE.Vector3(Math.sin(heading)*Math.cos(alt),Math.sin(alt),-Math.cos(heading)*Math.cos(alt)).multiplyScalar(distance));
      const camera=this.sun.shadow.camera;camera.left=camera.bottom=-radius;camera.right=camera.top=radius;camera.near=.1;camera.far=radius*8;camera.updateProjectionMatrix();
      this.sun.shadow.needsUpdate=true;this.renderer.shadowMap.needsUpdate=true;this.shadowAnchor.copy(target);this.dirtyShadow=false;
      if(this.sun.castShadow)this.casters(target,radius);
    }
    const phase=this.clock.step(now,playing),due=now-this.lastWave>=1000/30;
    if(this.waterPattern&&due){const water=e.water;
      this.waterPattern.update(phase,water.wavelengthM,water.travelSpeedMps,this.waveHeading);this.lastWave=now;this.surroundings.update(phase,e,this.waveHeading);
    }
    return playing&&due;
  }
  status(){return {water:!!this.water,surroundings:this.surroundings.status(),casters:this.casterCount,phase:this.clock.value(),fallback:this.fallback,textureBudgetBytes:2*1024*512*4+6*256*256*8+1024*1024*4+349524};}
  dispose(){if(this.disposed)return;this.disposed=true;this.surroundings.dispose();this.releaseWater();this.releaseSky();this.releaseShadow();this.generator?.dispose();this.generator=null;this.scene.fog=null;
    for(const [mesh,p] of this.ownedShadow){mesh.castShadow=p.cast;mesh.receiveShadow=p.receive;}this.ownedShadow.clear();this.roots=[];this.selected=null;this.previewClock=null;this.sun.target.removeFromParent();}
}
