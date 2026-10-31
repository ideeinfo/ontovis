import * as THREE from 'three';
import type {SceneEnvironmentV1} from './sceneEnvironment';

function hash(x:number,y:number,period:number,seed:number){
  let n=Math.imul((x%period+period)%period,374761393)^Math.imul((y%period+period)%period,668265263)^Math.imul(seed,1442695041);
  n=Math.imul(n^(n>>>13),1274126177);return ((n^(n>>>16))>>>0)/4294967295;
}
function noise(x:number,y:number,period:number,seed:number){
  const a=Math.floor(x),b=Math.floor(y),u=x-a,v=y-b,tx=u*u*(3-2*u),ty=v*v*(3-2*v);
  return THREE.MathUtils.lerp(THREE.MathUtils.lerp(hash(a,b,period,seed),hash(a+1,b,period,seed),tx),
    THREE.MathUtils.lerp(hash(a,b+1,period,seed),hash(a+1,b+1,period,seed),tx),ty);
}
/** Seeded, seamless multi-scale noise. Generated once, never on each animation frame. */
export function cloudNoise(seed:number){
  const size=256,data=new Uint8Array(size*size*4);
  for(let y=0;y<size;y++)for(let x=0;x<size;x++){
    for(let channel=0;channel<3;channel++){
      let value=0,weight=0;
      for(let octave=0;octave<4;octave++){
        const frequency=4*2**(octave+channel),amplitude=.5**octave;
        value+=noise(x/size*frequency,y/size*frequency,frequency,seed+channel*71+octave*179)*amplitude;weight+=amplitude;
      }
      data[(y*size+x)*4+channel]=Math.round(value/weight*255);
    }
    data[(y*size+x)*4+3]=255;
  }
  const texture=new THREE.DataTexture(data,size,size);texture.wrapS=texture.wrapT=THREE.RepeatWrapping;
  texture.magFilter=THREE.LinearFilter;texture.minFilter=THREE.LinearMipmapLinearFilter;texture.generateMipmaps=true;texture.needsUpdate=true;return texture;
}

const vertexShader=/* glsl */`
varying vec3 cloudRay;
void main(){
  cloudRay=position;
  // Camera rotation only: a sky layer has no world bounds or physical location.
  vec4 point=projectionMatrix*mat4(mat3(viewMatrix))*vec4(position,1.0);
  gl_Position=point.xyww;
}`;
const fragmentShader=/* glsl */`
uniform sampler2D cloudNoise;
uniform vec4 cloudShape;
uniform vec2 cloudTravel;
uniform vec2 cloudCamera;
uniform vec2 cloudSun;
uniform vec3 cloudLight;
uniform vec3 cloudShade;
varying vec3 cloudRay;
float field(vec2 p){
  vec2 warp=texture2D(cloudNoise,p*0.37+vec2(0.17,0.53)).gb-0.5;
  return texture2D(cloudNoise,p+warp*0.65).r*0.72
    +texture2D(cloudNoise,p*2.03+warp*0.21+vec2(0.63,0.21)).g*0.20
    +texture2D(cloudNoise,p*4.11-warp*0.13).b*0.08;
}
void main(){
  vec3 ray=normalize(cloudRay);
  if(ray.y<=0.015||cloudShape.x<=0.0||cloudShape.y<=0.0)discard;
  // A visual projection above the viewer, not a georeferenced weather observation.
  vec2 p=(ray.xz/max(ray.y,0.025)*1600.0+cloudCamera)*cloudShape.z-cloudTravel;
  float value=field(p),threshold=mix(0.73,0.27,cloudShape.x);
  float filterWidth=max(fwidth(value)*1.5,0.035);
  float body=smoothstep(threshold-filterWidth,threshold+0.13,value);
  float alpha=(1.0-exp(-body*cloudShape.y*3.0))*smoothstep(0.015,0.13,ray.y);
  float lightSample=field(p+cloudSun*0.035);
  float edge=clamp((value-lightSample)*5.0+0.68-body*0.28,0.0,1.0);
  vec3 color=mix(cloudShade,cloudLight,edge);
  gl_FragColor=vec4(color,alpha);
  #include <colorspace_fragment>
}`;

/** One bounded sky draw, one shared noise texture; never part of scene picking/placement. */
export class SceneClouds {
  private scene:THREE.Scene;private mesh:THREE.Mesh<THREE.SphereGeometry,THREE.ShaderMaterial>|null=null;
  private texture:THREE.DataTexture|null=null;private seed:number|null=null;
  private uniforms={cloudNoise:{value:null as THREE.Texture|null},cloudShape:{value:new THREE.Vector4()},
    cloudTravel:{value:new THREE.Vector2()},cloudCamera:{value:new THREE.Vector2()},cloudSun:{value:new THREE.Vector2()},
    cloudLight:{value:new THREE.Color()},cloudShade:{value:new THREE.Color()}};
  private scale=1;private speed=0;private heading=0;
  constructor(scene:THREE.Scene){this.scene=scene;}
  configure(environment:SceneEnvironmentV1|null,heading:number,sunHeading=0,night=false){
    const value=environment?.atmosphere.clouds;
    if(!value?.enabled){this.dispose();return;}
    if(!this.mesh){
      const geometry=new THREE.SphereGeometry(1,24,12),material=new THREE.ShaderMaterial({uniforms:this.uniforms,vertexShader,fragmentShader,
        side:THREE.BackSide,transparent:true,depthWrite:false,depthTest:true,toneMapped:false});
      this.mesh=new THREE.Mesh(geometry,material);this.mesh.name='visual-clouds-not-placement';this.mesh.renderOrder=-2000;
      this.mesh.frustumCulled=false;this.mesh.raycast=()=>{};this.mesh.userData={visualOnly:true,excludeFromBounds:true};
      const eye=new THREE.Vector3();this.mesh.onBeforeRender=(_renderer,_scene,camera)=>{camera.getWorldPosition(eye);this.uniforms.cloudCamera.value.set(eye.x,eye.z);};
      this.scene.add(this.mesh);
    }
    if(this.seed!==value.seed){const next=cloudNoise(value.seed);this.texture?.dispose();this.texture=next;this.seed=value.seed;this.uniforms.cloudNoise.value=next;}
    this.scale=.22/value.scaleM;this.speed=value.speedMps;this.heading=heading;
    this.uniforms.cloudShape.value.set(value.coverage,value.density,this.scale,0);
    const sun=environment!.lighting.sun;this.uniforms.cloudSun.value.set(Math.sin(sunHeading),-Math.cos(sunHeading));
    this.uniforms.cloudLight.value.set(night?'#7184a2':'#fffdf7').lerp(new THREE.Color(sun.color),sun.enabled ? .3 : 0);
    this.uniforms.cloudShade.value.set(environment!.atmosphere.horizonColor).multiplyScalar(.72);
  }
  update(phase:number){this.uniforms.cloudTravel.value.set(Math.sin(this.heading),-Math.cos(this.heading)).multiplyScalar(phase*this.speed*this.scale);}
  active(){return !!this.mesh;}
  dispose(){this.mesh?.removeFromParent();this.mesh?.geometry.dispose();this.mesh?.material.dispose();this.texture?.dispose();this.mesh=null;this.texture=null;this.seed=null;this.uniforms.cloudNoise.value=null;}
}
