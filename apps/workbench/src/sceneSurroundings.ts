import * as THREE from 'three';
import type {SceneEnvironmentV1} from './sceneEnvironment';
import {waterMaterial} from './sceneWater.ts';

type Point={x:number;y:number;z:number};
const SEGMENTS=128,RINGS=9;
const cross=(a:Point,b:Point,c:Point)=>(b.x-a.x)*(c.z-a.z)-(b.z-a.z)*(c.x-a.x);

/** A small display outline from referenced vertices; masked zero placeholders never enter it. */
function outline(geometry:THREE.BufferGeometry){
  const positions=geometry.getAttribute('position'),index=geometry.index;if(!positions)return [];
  const used=new Uint8Array(positions.count);
  if(index)for(let i=0;i<index.count;i++)used[index.getX(i)]=1;else used.fill(1);
  const box=new THREE.Box3(),point=new THREE.Vector3();
  for(let i=0;i<used.length;i++)if(used[i])box.expandByPoint(point.fromBufferAttribute(positions,i));
  if(box.isEmpty())return [];
  const center=box.getCenter(point),candidates=new Map<number,{point:Point;distance:number}>();
  for(let i=0;i<used.length;i++)if(used[i]){
    const x=positions.getX(i),y=positions.getY(i),z=positions.getZ(i),dx=x-center.x,dz=z-center.z;
    const bucket=Math.floor((Math.atan2(dz,dx)+Math.PI)/(2*Math.PI)*SEGMENTS)%SEGMENTS,distance=dx*dx+dz*dz;
    if(!candidates.has(bucket)||candidates.get(bucket)!.distance<distance)candidates.set(bucket,{point:{x,y,z},distance});
  }
  const points=[...candidates.values()].map(v=>v.point).sort((a,b)=>a.x-b.x||a.z-b.z);
  const lower:Point[]=[],upper:Point[]=[];
  for(const p of points){while(lower.length>1&&cross(lower.at(-2)!,lower.at(-1)!,p)<=0)lower.pop();lower.push(p);}
  for(const p of points.reverse()){while(upper.length>1&&cross(upper.at(-2)!,upper.at(-1)!,p)<=0)upper.pop();upper.push(p);}
  return [...lower.slice(0,-1),...upper.slice(0,-1)];
}

/** Separate coarse geometry. The small inward overlap is drawn underneath the original surface. */
export function surroundingGeometry(source:THREE.BufferGeometry,offshore:boolean):THREE.BufferGeometry|null {
  const hull=outline(source);if(hull.length<3)return null;
  const center=hull.reduce<THREE.Vector3>((a,p)=>a.add(new THREE.Vector3(p.x,p.y,p.z)),new THREE.Vector3()).multiplyScalar(1/hull.length);
  const maxRadius=Math.max(...hull.map(p=>Math.hypot(p.x-center.x,p.z-center.z))),outer=Math.max(750000,maxRadius*40);
  if(!Number.isFinite(outer)||maxRadius<=0)return null;
  const positions:number[]=[],uv:number[]=[],colors:number[]=[],fade:number[]=[],indices:number[]=[];
  for(let ring=0;ring<RINGS;ring++)for(let i=0;i<=SEGMENTS;i++){
    const angle=i/SEGMENTS*Math.PI*2,dx=Math.sin(angle),dz=-Math.cos(angle);let distance=Infinity,height=center.y;
    for(let j=0;j<hull.length;j++){
      const a=hull[j],b=hull[(j+1)%hull.length],ex=b.x-a.x,ez=b.z-a.z,den=dx*ez-dz*ex;
      if(Math.abs(den)<1e-12)continue;
      const ax=a.x-center.x,az=a.z-center.z,t=(ax*ez-az*ex)/den,u=(ax*dz-az*dx)/den;
      if(t>=0&&u>=-1e-8&&u<=1+1e-8&&t<distance){distance=t;height=a.y+(b.y-a.y)*u;}
    }
    if(!Number.isFinite(distance))return null;
    const radii=[distance*.97,distance,distance+maxRadius*.15,distance+maxRadius*.5,distance+maxRadius*2,distance+maxRadius*8,outer*.25,outer*.6,outer];
    const r=radii[ring],x=center.x+dx*r,z=center.z+dz*r;
    const blend=Math.min(1,Math.max(0,(r-distance)/Math.max(1,maxRadius*3)));
    const rolling=Math.sin(angle*3+.7)*Math.cos(angle*5-.9)*Math.min(350,maxRadius*.08);
    const y=offshore?center.y:height*(1-blend)+(center.y+rolling*Math.min(1,ring/3))*blend;
    positions.push(x,y,z);uv.push(x,-z);
    const tint=offshore?1:.88+.08*Math.sin(angle*7+ring*.8);colors.push(tint,tint,tint);
    fade.push(ring<6?0:ring===6?.2:ring===7?.8:1);
    if(ring<RINGS-1&&i<SEGMENTS){const a=ring*(SEGMENTS+1)+i,b=a+1,c=a+SEGMENTS+1,d=c+1;indices.push(a,b,c,b,d,c);}
  }
  const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));
  geometry.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2));geometry.setAttribute('color',new THREE.Float32BufferAttribute(colors,3));
  geometry.setAttribute('surroundingFade',new THREE.Float32BufferAttribute(fade,1));geometry.setIndex(indices);geometry.computeVertexNormals();return geometry;
}

export class SceneSurroundings {
  private scene:THREE.Scene;private mesh:THREE.Mesh<THREE.BufferGeometry,THREE.MeshBasicMaterial|THREE.MeshStandardMaterial>|null=null;
  private key='';private profile:'land'|'offshore'|null=null;private pattern:ReturnType<typeof waterMaterial>|null=null;
  private horizon={value:new THREE.Color()};
  constructor(scene:THREE.Scene){this.scene=scene;}
  configure(value:SceneEnvironmentV1|null,terrain:THREE.Mesh|null,normals:THREE.DataTexture|null,visible:boolean){
    if(!value||value.surroundings?.mode!=='auto'||!terrain||!visible){this.dispose();return;}
    const profile=value.surroundings.profile,water=profile==='offshore'&&!!normals,key=JSON.stringify([terrain.uuid,terrain.geometry.uuid,profile,water?normals!.uuid:null]);
    if(key!==this.key){
      this.dispose();const geometry=surroundingGeometry(terrain.geometry,profile==='offshore');if(!geometry)return;
      this.pattern=water?waterMaterial(normals!):null;
      const material=this.pattern?.material??new THREE.MeshBasicMaterial({vertexColors:true,toneMapped:false,fog:false});
      material.depthWrite=false;material.depthTest=false;material.fog=false;
      const compile=material.onBeforeCompile.bind(material);
      material.onBeforeCompile=(shader,renderer)=>{
        compile(shader,renderer);shader.uniforms.ontoVisSurroundingHorizon=this.horizon;
        shader.vertexShader=shader.vertexShader.replace('#include <common>','#include <common>\nattribute float surroundingFade; varying float vSurroundingFade;')
          .replace('#include <begin_vertex>','#include <begin_vertex>\nvSurroundingFade=surroundingFade;');
        shader.fragmentShader=shader.fragmentShader.replace('#include <common>','#include <common>\nuniform vec3 ontoVisSurroundingHorizon; varying float vSurroundingFade;')
          .replace('#include <opaque_fragment>','outgoingLight=mix(outgoingLight,ontoVisSurroundingHorizon,vSurroundingFade);\n#include <opaque_fragment>');
      };
      material.customProgramCacheKey=()=>water?'ontovis-surrounding-water-v1':'ontovis-surrounding-land-v1';
      this.mesh=new THREE.Mesh(geometry,material);this.mesh.name='visual-surroundings-not-placement';this.mesh.renderOrder=-1000;
      this.mesh.matrixAutoUpdate=false;this.mesh.raycast=()=>{};this.mesh.userData={visualOnly:true,excludeFromBounds:true};
      this.scene.add(this.mesh);this.key=key;this.profile=profile;
    }
    this.mesh!.matrix.copy(terrain.matrixWorld);this.horizon.value.set(value.atmosphere.horizonColor);
    this.mesh!.material.color.set(profile==='offshore'?value.water.color:'#98a58b');
    if(this.pattern){const material=this.pattern.material;material.roughness=value.water.roughness;material.normalScale.setScalar(value.water.rippleStrength);}
  }
  update(phase:number,value:SceneEnvironmentV1,heading:number){this.pattern?.update(phase,value.water.wavelengthM,value.water.travelSpeedMps,heading);}
  status(){return this.profile;}
  dispose(){this.mesh?.removeFromParent();this.mesh?.geometry.dispose();this.mesh?.material.dispose();this.mesh=null;this.pattern=null;this.profile=null;this.key='';}
}
