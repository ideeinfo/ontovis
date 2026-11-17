import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {rippleNormals,waterMaterial} from '../src/sceneWater.ts';

test('wave normal data stays normalized, seamless in filtering and uses mipmaps instead of distant high-frequency aliases',()=>{
  const texture=rippleNormals(771),{data,width,height}=texture.image;
  assert.equal(texture.wrapS,THREE.RepeatWrapping);assert.equal(texture.wrapT,THREE.RepeatWrapping);
  assert.equal(texture.minFilter,THREE.LinearMipmapLinearFilter);assert.equal(texture.generateMipmaps,true);
  assert.equal(texture.colorSpace,THREE.NoColorSpace);
  let largestSeam=0,largestStep=0;
  for(let y=0;y<height;y++)for(let x=0;x<width;x++){
    const index=(y*width+x)*4,n=[0,1,2].map(i=>data[index+i]/255*2-1);
    assert.ok(Math.abs(Math.hypot(...n)-1)<.013);assert.equal(data[index+3],255);assert.ok(n[2]>0);
    for(let c=0;c<2;c++){
      const difference=Math.abs(data[index+c]-data[(y*width+(x+1)%width)*4+c]);
      if(x===width-1)largestSeam=Math.max(largestSeam,difference);else largestStep=Math.max(largestStep,difference);
    }
  }
  assert.ok(largestSeam<=largestStep,'The repeating edge must not introduce a sharper crease than the interior');texture.dispose();
});

test('wave field is not another two global sine directions and retains changing local wave orientation',()=>{
  const texture=rippleNormals(771),{data,width,height}=texture.image;
  // A two-plane-wave normal has only a few Fourier modes before normalization.
  // Distinct local patch direction distributions reject the former stripe field.
  const directions=new Set();
  for(let by=0;by<4;by++)for(let bx=0;bx<4;bx++){
    let xx=0,xy=0,yy=0;
    for(let y=by*height/4;y<(by+1)*height/4;y++)for(let x=bx*width/4;x<(bx+1)*width/4;x++){
      const i=(y*width+x)*4,nx=(data[i]-127.5)/(data[i+2]-127.5),ny=(data[i+1]-127.5)/(data[i+2]-127.5);
      xx+=nx*nx;xy+=nx*ny;yy+=ny*ny;
    }
    directions.add(Math.round(Math.atan2(2*xy,xx-yy)*4));
  }
  assert.ok(directions.size>=5,'Curved packets must vary direction across the surface');texture.dispose();
});

test('water shader replaces the active tangent-space normal path, preserves PBR and reuses uniforms across frames',()=>{
  const texture=rippleNormals(771),pattern=waterMaterial(texture),{material}=pattern;
  const shader={uniforms:{},fragmentShader:THREE.ShaderLib.standard.fragmentShader};
  material.onBeforeCompile(shader,{});
  assert.ok(shader.fragmentShader.includes('vec3 mapN = ontoVisWaterNormal(vNormalMapUv)'));
  assert.ok(shader.fragmentShader.includes('#include <lights_physical_fragment>'));
  assert.ok(shader.fragmentShader.includes('#include <fog_fragment>'));
  assert.equal(material.normalMap,texture);assert.equal(material.normalMapType,THREE.TangentSpaceNormalMap);
  const uniform=shader.uniforms.ontoVisWater,value=uniform.value,version=material.version,key=material.customProgramCacheKey();
  pattern.update(4,20,.6,Math.PI/2);assert.equal(uniform.value,value);
  assert.deepEqual(value.toArray().map(v=>+v.toFixed(8)),[1/120,.02,1,0].map(v=>+v.toFixed(8)));
  pattern.update(4,20,.6,Math.PI/2);assert.equal(material.version,version);assert.equal(material.customProgramCacheKey(),key);
  const frozen=value.toArray();pattern.update(4,20,.6,Math.PI/2);assert.deepEqual(value.toArray(),frozen);
  pattern.update(1000,2,20,0);assert.ok(value.toArray().every(Number.isFinite));
  let textures=0;texture.addEventListener('dispose',()=>textures++);material.dispose();assert.equal(textures,0,'The runtime, not the material helper, owns the texture');texture.dispose();assert.equal(textures,1);
});
