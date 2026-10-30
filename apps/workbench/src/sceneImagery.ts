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
  const source=projection(frame.horizontalCrs),destination=projection(report.horizontalCrs);
  const transform=frame.horizontalCrs===report.horizontalCrs?null:proj4(source,destination),uv=new Float32Array(positions.count*2);
  for(let i=0;i<positions.count;i++){
    const east=frame.originEasting+positions.getX(i),north=frame.originNorthing-positions.getZ(i);
    const point=transform?.forward([east,north]),x=(point?.[0]??east)-c,y=(point?.[1]??north)-f;
    const u=(e*x-b*y)/det/report.width,v=1-(-d*x+a*y)/det/report.height;
    if(!Number.isFinite(u)||!Number.isFinite(v)||Math.max(Math.abs(u),Math.abs(v))>1e8)throw new ApiError(422,'INVALID_COORDINATE');
    uv[i*2]=u;uv[i*2+1]=v;
  }
  return uv;
}

type Layer={key:string;mesh:THREE.Mesh<THREE.BufferGeometry,THREE.MeshBasicMaterial|THREE.MeshStandardMaterial>;source:THREE.MeshBasicMaterial;lit:THREE.MeshStandardMaterial|null;texture:THREE.Texture;partial:boolean};
type PreparedImage={key:string;abort:AbortController;promise:Promise<ImageBitmap>;bitmap:ImageBitmap|null};
export class SceneImageryLayer {
  private layer:Layer|null=null;
  private prepared:PreparedImage|null=null;
  private sequence=0;
  private disposed=false;
  private api:SceneApi;
  constructor(api:SceneApi){this.api=api;}
  private releaseLayer(){const value=this.layer;this.layer=null;if(value){value.mesh.removeFromParent();value.mesh.geometry.dispose();value.source.dispose();value.lit?.dispose();value.texture.dispose();}}
  private release(){this.releaseLayer();const prepared=this.prepared;this.prepared=null;if(prepared){prepared.abort.abort();prepared.bitmap?.close();prepared.bitmap=null;}}
  private cancelled(){return new DOMException('Imagery changed','AbortError');}
  private consume(prepared:PreparedImage,signal?:AbortSignal):Promise<ImageBitmap>{
    if(this.disposed||signal?.aborted)return Promise.reject(this.cancelled());
    return new Promise((resolve,reject)=>{
      const aborted=()=>{signal?.removeEventListener('abort',aborted);reject(this.cancelled());};
      signal?.addEventListener('abort',aborted,{once:true});
      prepared.promise.then(bitmap=>{signal?.removeEventListener('abort',aborted);
        if(this.disposed||prepared!==this.prepared||signal?.aborted)reject(this.cancelled());else resolve(bitmap);
      },error=>{signal?.removeEventListener('abort',aborted);reject(error);});
    });
  }
  visible(value:boolean){if(this.layer)this.layer.mesh.visible=value;}
  shading(mode:'source-color'|'lit',environment=false){
    const layer=this.layer;if(!layer)return;
    if(mode==='lit'&&!layer.lit){
      layer.lit=new THREE.MeshStandardMaterial({map:layer.texture,roughness:1,transparent:true,depthWrite:false,polygonOffset:true,polygonOffsetFactor:-1,polygonOffsetUnits:-1});
      layer.lit.onBeforeCompile=layer.source.onBeforeCompile;layer.lit.customProgramCacheKey=()=> 'ontovis-imagery-lit-clip-v1';
    }
    const toneMapped=!environment;if(layer.source.toneMapped!==toneMapped){layer.source.toneMapped=toneMapped;layer.source.needsUpdate=true;}
    // Source colors bypass lighting and exposure, but still share the scene's distance haze.
    layer.source.fog=true;layer.mesh.material=mode==='lit'?layer.lit!:layer.source;layer.mesh.receiveShadow=mode==='lit';
  }
  partial(){return this.layer?.partial??false;}
  /** Start the fixed private read alongside model/terrain loading; only sync may attach it. */
  prepare(imagery:ImageryRecord|null,reference:SceneImageryRef|null|undefined,signal?:AbortSignal):Promise<ImageBitmap|null>{
    if(this.disposed||signal?.aborted)return Promise.reject(this.cancelled());
    if(!imagery||!reference){this.release();return Promise.resolve(null);}
    if(imagery.imageryVersionId!==reference.imageryVersionId||imagery.contentRevision!==reference.expectedContentRevision||imagery.expectedReportSha256!==reference.expectedReportSha256){this.release();return Promise.reject(new ApiError(409,'RESOURCE_CHANGED'));}
    const key=JSON.stringify([imagery.imageryVersionId,imagery.contentRevision,imagery.expectedReportSha256,imagery.texture.sha256]);
    let prepared=this.prepared;
    if(prepared?.key!==key){
      this.release();
      const abort=new AbortController();
      const promise:Promise<ImageBitmap>=this.api.imageryContent(imagery,abort.signal).then(async blob=>{
        if(this.disposed||pending!==this.prepared||abort.signal.aborted)throw this.cancelled();
        const bitmap=await createImageBitmap(blob,{imageOrientation:'flipY',premultiplyAlpha:'none',colorSpaceConversion:'none'});
        if(this.disposed||pending!==this.prepared||abort.signal.aborted){bitmap.close();throw this.cancelled();}
        if(bitmap.width!==imagery.report.width||bitmap.height!==imagery.report.height){bitmap.close();throw new ApiError(409,'RESOURCE_CHANGED');}
        pending.bitmap=bitmap;return bitmap;
      }).catch(error=>{if(this.prepared===pending){this.prepared=null;this.releaseLayer();}throw error;});
      const pending:PreparedImage={key,abort,promise,bitmap:null};prepared=pending;this.prepared=pending;
    }
    return this.consume(prepared,signal);
  }
  async sync(terrain:THREE.Mesh|null,terrainVersion:TerrainVersion|null,imagery:ImageryRecord|null,reference:SceneImageryRef|null|undefined,signal:AbortSignal){
    const ticket=++this.sequence;
    if(!terrain||!terrainVersion){this.releaseLayer();return;}
    const bitmap=await this.prepare(imagery,reference,signal);
    if(this.disposed||ticket!==this.sequence||signal.aborted)throw this.cancelled();
    if(!bitmap||!imagery||!reference){this.releaseLayer();return;}
    if(bitmap!==this.prepared?.bitmap)throw this.cancelled();
    const key=JSON.stringify([imagery.imageryVersionId,imagery.contentRevision,imagery.texture.sha256,terrainVersion.terrainVersionId,terrainVersion.expectedReportSha256]);
    if(this.layer?.key===key&&this.layer.mesh.geometry.getAttribute('position').count===terrain.geometry.getAttribute('position').count){if(this.layer.mesh.parent!==terrain)terrain.add(this.layer.mesh);return;}
    this.releaseLayer();
    let geometry:THREE.BufferGeometry|undefined,texture:THREE.Texture|undefined,material:THREE.MeshBasicMaterial|undefined;
    try{
      geometry=terrain.geometry.clone();const uv=imageryUvs(geometry.getAttribute('position'),terrainVersion.report.mesh.frame,imagery.report);geometry.setAttribute('uv',new THREE.BufferAttribute(uv,2));
      const outside=(i:number)=>uv[i*2]<-1e-5||uv[i*2]>1+1e-5||uv[i*2+1]<-1e-5||uv[i*2+1]>1+1e-5;
      const count=geometry.index?.count??geometry.getAttribute('position').count;let partial=false;
      for(let i=0;i<count;i++)if(outside(geometry.index?geometry.index.getX(i):i)){partial=true;break;}
      texture=new THREE.Texture(bitmap);texture.flipY=false;texture.colorSpace=THREE.SRGBColorSpace;
      texture.minFilter=texture.magFilter=THREE.LinearFilter;texture.generateMipmaps=false;texture.needsUpdate=true;
      material=new THREE.MeshBasicMaterial({map:texture,transparent:true,depthWrite:false,polygonOffset:true,polygonOffsetFactor:-1,polygonOffsetUnits:-1});
      material.onBeforeCompile=shader=>{shader.fragmentShader=shader.fragmentShader.replace('#include <map_fragment>','if (vMapUv.x < 0.0 || vMapUv.x > 1.0 || vMapUv.y < 0.0 || vMapUv.y > 1.0) discard;\n#include <map_fragment>');};
      material.customProgramCacheKey=()=> 'ontovis-imagery-clip-v1';
      // Draw behind transparent equipment, whose ghost materials intentionally do not write depth.
      const mesh=new THREE.Mesh(geometry,material);mesh.name='overview-imagery';mesh.renderOrder=-10;terrain.add(mesh);
      this.layer={key,mesh,texture,partial,source:material,lit:null};
    }catch(error){geometry?.dispose();material?.dispose();texture?.dispose();throw error;}
  }
  dispose(){this.disposed=true;++this.sequence;this.release();}
}
