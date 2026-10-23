import proj4 from 'proj4';
import * as THREE from 'three';
import {ApiError} from './api.ts';
import type {SceneApi} from './sceneApi';
import type {ImageryRecord,ImageryReport,TerrainFrame,TerrainVersion} from './resourceTypes';
import type {SceneImageryRef} from './sceneTypes';

function projection(crs:string){
  if(crs==='EPSG:4326')return '+proj=longlat +datum=WGS84 +no_defs';
  const match=/^EPSG:(326|327)(\d{2})$/.exec(crs);
  if(!match||Number(match[2])<1||Number(match[2])>60)throw new ApiError(422,'UNSUPPORTED_CRS');
  return `+proj=utm +zone=${Number(match[2])}${match[1]==='327'?' +south':''} +datum=WGS84 +units=m +no_defs`;
}

/** Raster pixel corners and the terrain's own fixed grid, never an AOI-box stretch. */
export function imageryUvs(positions:THREE.BufferAttribute|THREE.InterleavedBufferAttribute,frame:Pick<TerrainFrame,'horizontalCrs'|'originEasting'|'originNorthing'>,report:ImageryReport){
  if(!Number.isSafeInteger(report.width)||!Number.isSafeInteger(report.height)||report.width<1||report.height<1||report.width>4096||report.height>4096)throw new ApiError(422,'UNSUPPORTED_IMAGERY');
  const [a,b,c,d,e,f]=report.pixelCornerAffine,det=a*e-b*d;
  if(![a,b,c,d,e,f,frame.originEasting,frame.originNorthing].every(Number.isFinite)||Math.abs(det)<1e-20)throw new ApiError(422,'UNSUPPORTED_IMAGERY');
  const transform=proj4(projection(frame.horizontalCrs),projection(report.horizontalCrs)),uv=new Float32Array(positions.count*2);
  for(let i=0;i<positions.count;i++){
    const [east,north]=transform.forward([frame.originEasting+positions.getX(i),frame.originNorthing-positions.getZ(i)]),x=east-c,y=north-f;
    const u=(e*x-b*y)/det/report.width,v=1-(-d*x+a*y)/det/report.height;
    if(!Number.isFinite(u)||!Number.isFinite(v)||Math.max(Math.abs(u),Math.abs(v))>1e8)throw new ApiError(422,'INVALID_COORDINATE');
    uv[i*2]=u;uv[i*2+1]=v;
  }
  return uv;
}

type Layer={key:string;mesh:THREE.Mesh<THREE.BufferGeometry,THREE.MeshBasicMaterial>;texture:THREE.Texture;bitmap:ImageBitmap;partial:boolean};
export class SceneImageryLayer {
  private layer:Layer|null=null;
  private sequence=0;
  private disposed=false;
  private api:SceneApi;
  constructor(api:SceneApi){this.api=api;}
  private release(){const value=this.layer;this.layer=null;if(value){value.mesh.removeFromParent();value.mesh.geometry.dispose();value.mesh.material.dispose();value.texture.dispose();value.bitmap.close();}}
  visible(value:boolean){if(this.layer)this.layer.mesh.visible=value;}
  partial(){return this.layer?.partial??false;}
  async sync(terrain:THREE.Mesh|null,terrainVersion:TerrainVersion|null,imagery:ImageryRecord|null,reference:SceneImageryRef|null|undefined,signal:AbortSignal){
    const ticket=++this.sequence;
    if(!terrain||!terrainVersion||!imagery||!reference){this.release();return;}
    if(imagery.imageryVersionId!==reference.imageryVersionId||imagery.contentRevision!==reference.expectedContentRevision||imagery.expectedReportSha256!==reference.expectedReportSha256){this.release();throw new ApiError(409,'RESOURCE_CHANGED');}
    const key=JSON.stringify([imagery.imageryVersionId,imagery.contentRevision,imagery.texture.sha256,terrainVersion.terrainVersionId,terrainVersion.expectedReportSha256]);
    if(this.layer?.key===key){if(this.layer.mesh.parent!==terrain)terrain.add(this.layer.mesh);return;}
    this.release();
    const blob=await this.api.imageryContent(imagery,signal);
    const bitmap=await createImageBitmap(blob,{imageOrientation:'flipY',premultiplyAlpha:'none',colorSpaceConversion:'none'});
    if(this.disposed||ticket!==this.sequence||signal.aborted){bitmap.close();throw new DOMException('Imagery changed','AbortError');}
    let geometry:THREE.BufferGeometry|undefined,texture:THREE.Texture|undefined,material:THREE.MeshBasicMaterial|undefined;
    try{
      if(bitmap.width!==imagery.report.width||bitmap.height!==imagery.report.height)throw new ApiError(409,'RESOURCE_CHANGED');
      geometry=terrain.geometry.clone();const uv=imageryUvs(geometry.getAttribute('position'),terrainVersion.report.mesh.frame,imagery.report);geometry.setAttribute('uv',new THREE.BufferAttribute(uv,2));
      const outside=(i:number)=>uv[i*2]<-1e-5||uv[i*2]>1+1e-5||uv[i*2+1]<-1e-5||uv[i*2+1]>1+1e-5;
      const partial=geometry.index?Array.from(geometry.index.array).some(outside):Array.from({length:geometry.getAttribute('position').count},(_,i)=>i).some(outside);
      texture=new THREE.Texture(bitmap);texture.flipY=false;texture.colorSpace=THREE.SRGBColorSpace;
      texture.minFilter=texture.magFilter=THREE.LinearFilter;texture.generateMipmaps=false;texture.needsUpdate=true;
      material=new THREE.MeshBasicMaterial({map:texture,transparent:true,depthWrite:false,polygonOffset:true,polygonOffsetFactor:-1,polygonOffsetUnits:-1});
      material.onBeforeCompile=shader=>{shader.fragmentShader=shader.fragmentShader.replace('#include <map_fragment>','if (vMapUv.x < 0.0 || vMapUv.x > 1.0 || vMapUv.y < 0.0 || vMapUv.y > 1.0) discard;\n#include <map_fragment>');};
      material.customProgramCacheKey=()=> 'ontovis-imagery-clip-v1';
      const mesh=new THREE.Mesh(geometry,material);mesh.name='overview-imagery';mesh.renderOrder=1;terrain.add(mesh);
      this.layer={key,mesh,texture,bitmap,partial};
    }catch(error){geometry?.dispose();material?.dispose();texture?.dispose();bitmap.close();throw error;}
  }
  dispose(){this.disposed=true;++this.sequence;this.release();}
}
