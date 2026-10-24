import type {ProjectModelVersion} from './resourceTypes';
import type {Bounds3,Vector3} from './sceneTypes';

export type PreviewDisplay='context'|'isolate';
export interface PreviewMaterial {name:string;type:string;color:string|null;opacity:number;textured:boolean}
export interface PreviewNode {
  id:string;parentId:string|null;children:string[];name:string;nodeIndex:number|null;
  kind:'source'|'proxy'|'metadata';componentKeys:string[];path:string[];bounds:Bounds3|null;
  meshes:number;vertices:number;triangles:number;materials:PreviewMaterial[];
  translation:Vector3|null;rotation:Vector3|null;scale:Vector3|null;attributes:Record<string,unknown>;
}
export interface PreviewStructure {identity:string;roots:string[];nodes:PreviewNode[]}
export interface PreviewSelection {identity:string;nodeId:string|null;display:PreviewDisplay;focusToken:number}
export const previewIdentity=(version:ProjectModelVersion|null|undefined)=>version?
  JSON.stringify([version.modelAssetId,version.modelVersionId,version.contentRevision,version.sha256]):'';
