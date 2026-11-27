import * as THREE from 'three';

const TAU=Math.PI*2;
function lattice(x:number,y:number,period:number,seed:number){
  let value=Math.imul((x%period+period)%period,374761393)^Math.imul((y%period+period)%period,668265263)^Math.imul(seed,1442695041);
  value=Math.imul(value^(value>>>13),1274126177);return ((value^(value>>>16))>>>0)/4294967295;
}
function noise(x:number,y:number,period:number,seed:number){
  const ix=Math.floor(x),iy=Math.floor(y),dx=x-ix,dy=y-iy;
  const u=dx*dx*dx*(dx*(dx*6-15)+10),v=dy*dy*dy*(dy*(dy*6-15)+10);
  const a=lattice(ix,iy,period,seed),b=lattice(ix+1,iy,period,seed),c=lattice(ix,iy+1,period,seed),d=lattice(ix+1,iy+1,period,seed);
  return a+(b-a)*u+(c-a)*v+(a-b-c+d)*u*v;
}

/** Seamless, seeded, curved wave packets rather than two infinite straight crests. */
export function rippleNormals(seed:number,size=256):THREE.DataTexture {
  const heights=new Float32Array(size*size),data=new Uint8Array(size*size*4);
  for(let y=0;y<size;y++)for(let x=0;x<size;x++){
    const u=x/size,v=y/size,a=noise(u*3,v*3,3,seed),b=noise(u*4,v*4,4,seed+13);
    const envelope=noise(u*5,v*5,5,seed+29);
    const broad=noise((u+a*.19)*5,(v+b*.19)*5,5,seed+31);
    const middle=noise((u-b*.08)*11,(v+a*.08)*11,11,seed+43);
    const fine=noise(u*19,v*19,19,seed+47);
    heights[y*size+x]=1.2*(broad*.5+middle*.3+fine*.2-.5)
      +.1*envelope*Math.sin(TAU*(u*5+v*2)+a*8+b*6);
  }
  const slope=size/(TAU*8),normal=new THREE.Vector3();
  for(let y=0;y<size;y++)for(let x=0;x<size;x++){
    const nx=(heights[y*size+(x+size-1)%size]-heights[y*size+(x+1)%size])*slope;
    const ny=(heights[((y+size-1)%size)*size+x]-heights[((y+1)%size)*size+x])*slope;
    normal.set(nx,ny,1).normalize();data.set([Math.round((normal.x*.5+.5)*255),Math.round((normal.y*.5+.5)*255),Math.round((normal.z*.5+.5)*255),255],(y*size+x)*4);
  }
  const texture=new THREE.DataTexture(data,size,size);texture.wrapS=texture.wrapT=THREE.RepeatWrapping;
  texture.generateMipmaps=true;texture.minFilter=THREE.LinearMipmapLinearFilter;texture.magFilter=THREE.LinearFilter;
  texture.colorSpace=THREE.NoColorSpace;texture.needsUpdate=true;return texture;
}

const waterNormalShader=/* glsl */`
uniform vec4 ontoVisWater;
vec2 ontoVisSlope(vec2 p) {
  vec3 n=texture2D(normalMap,p).xyz*2.0-1.0;
  return n.xy/max(n.z,0.35);
}
vec3 ontoVisWaterNormal(vec2 uv) {
  vec2 direction=ontoVisWater.zw;
  mat2 heading=mat2(direction.x,-direction.y,direction.y,direction.x);
  mat2 inverseHeading=mat2(direction.x,direction.y,-direction.y,direction.x);
  mat2 crossing=mat2(0.7648,-0.6442,0.6442,0.7648);
  mat2 inverseCrossing=mat2(0.7648,0.6442,-0.6442,0.7648);
  vec2 p=heading*(uv*ontoVisWater.x)-vec2(ontoVisWater.y,0.0);
  vec2 broadA=ontoVisSlope(p*0.13+vec2(1.7,4.3));
  vec2 broadB=inverseCrossing*ontoVisSlope(crossing*(p*0.097)+vec2(5.1,2.9));
  float evolution=0.5+0.5*sin(ontoVisWater.y*56.5487);
  vec2 swell=mix(broadA,broadB,evolution);
  vec2 warp=broadA*0.075+broadB*0.045;
  vec2 fineA=ontoVisSlope(p+warp);
  vec2 fineB=inverseCrossing*ontoVisSlope(crossing*(p*0.67)-warp+vec2(3.8,7.1)+vec2(ontoVisWater.y*0.19,ontoVisWater.y*0.11));
  // Fade unresolved ripples before they become long-distance moire stripes.
  float footprint=max(length(dFdx(p)),length(dFdy(p)));
  float distant=smoothstep(0.025,0.12,footprint);
  vec2 slope=inverseHeading*((fineA*0.65+fineB*0.35)*(1.0-distant)+swell*(0.6+distant*3.0));
  return normalize(vec3(slope,1.0));
}
`;

/** One texture/four filtered reads. The standard PBR, sun, fog and shadow path stays intact. */
export function waterMaterial(normals:THREE.DataTexture){
  const state={value:new THREE.Vector4(1/120,0,0,1)};
  const material=new THREE.MeshStandardMaterial({color:0x507d91,roughness:.3,metalness:.05,normalMap:normals,side:THREE.FrontSide});
  material.customProgramCacheKey=()=> 'ontovis-water-normal-v2';
  material.onBeforeCompile=shader=>{
    shader.uniforms.ontoVisWater=state;
    shader.fragmentShader=shader.fragmentShader.replace('#include <normalmap_pars_fragment>',`#include <normalmap_pars_fragment>\n${waterNormalShader}`)
      .replace('#include <normal_fragment_maps>',THREE.ShaderChunk.normal_fragment_maps.replaceAll('texture2D( normalMap, vNormalMapUv ).xyz * 2.0 - 1.0','ontoVisWaterNormal(vNormalMapUv)'));
  };
  return {material,update(phase:number,wavelength:number,speed:number,heading:number){
    state.value.set(1/(wavelength*6),phase*speed/(wavelength*6),Math.sin(heading),Math.cos(heading));
  }};
}
