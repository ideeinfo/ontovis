import {ApiError, failureMessage} from './api.ts';
import {resourceText, type ResourceMessageKey} from './resourceMessages.ts';
import type {Locale} from './messages';
import type {ModelCalibrationInput, ModelPurpose, ProjectModelAsset, ProjectModelVersion, UploadModelMetadata, UploadTerrainMetadata} from './resourceTypes';
import type {VerticalDatum, Vector3} from './sceneTypes';

export class ResourceFormError extends Error {
  key: ResourceMessageKey;
  values: Record<string,string|number>;
  constructor(key: ResourceMessageKey, values: Record<string,string|number> = {}) {super(key); this.key = key; this.values = values;}
}
export function resourceCalibrationKey(state:ProjectModelVersion['calibrationState']) {
  return state==='legacy_display'?'legacyDisplay':state==='verified'?'calibrated':'unverified';
}
export function modelPlacementIssue(model:Pick<ProjectModelVersion,'calibrationState'|'calibration'|'canPlace'|'canPlaceGeographic'>,geographic:boolean) {
  if(!model.canPlace||model.calibration.state!==model.calibrationState||!['verified','legacy_display'].includes(model.calibrationState))return 'MODEL_CALIBRATION_REQUIRED';
  return geographic&&model.canPlaceGeographic!==true?'MODEL_GEOGRAPHIC_CALIBRATION_REQUIRED':null;
}
export function resourceFailure(error: unknown, locale: Locale) {
  if (error instanceof ResourceFormError) return resourceText(locale, error.key, error.values);
  if (error instanceof ApiError && error.status === 413 && error.code === 'INVALID_REQUEST') return resourceText(locale, 'metadataLimit');
  if (error instanceof ApiError && ['INVALID_CALIBRATION','UNSUPPORTED_CALIBRATION'].includes(error.code)) return resourceText(locale, 'invalidForward');
  if (error instanceof ApiError && error.code === 'MODEL_SOURCE_RIGHTS_REQUIRED') return resourceText(locale, 'sourcePending');
  if (error instanceof ApiError && error.code === 'MODEL_ALREADY_IMPORTED') return resourceText(locale, 'alreadyAvailable');
  return failureMessage(error, locale);
}
export function writeDenial(error: unknown) {
  return error instanceof ApiError && error.status === 403 && ['MODEL_WRITE_FORBIDDEN','SCENE_WRITE_FORBIDDEN'].includes(error.code);
}
export function privateDenial(error: unknown) {
  return error instanceof ApiError && (error.status === 401 || error.status === 403 && !writeDenial(error));
}
export function validateResourceFile(file: Pick<File,'name'|'size'>, kind: 'model'|'terrain', maximum?: number) {
  const terrain = kind === 'terrain', cap = Math.min(maximum ?? Infinity, (terrain ? 256 : 20) * 1024 * 1024);
  if (!(terrain ? /\.tiff?$/i : /\.glb$/i).test(file.name) || !Number.isSafeInteger(file.size)
      || file.size < (terrain ? 8 : 24)) throw new ResourceFormError(terrain ? 'terrainFileInvalid' : 'modelFileInvalid');
  if (file.size > cap) throw new ResourceFormError(terrain ? 'terrainFileTooLarge' : 'modelFileInvalid', {maximum:resourceUploadBytes(cap)});
}
function vector(values: readonly string[]): Vector3 {
  const numbers = values.map(value => value.trim() ? Number(value) : NaN);
  if (numbers.length !== 3 || numbers.some(value => !Number.isFinite(value) || Math.abs(value) > 1_000_000)) throw new ResourceFormError('finiteCoordinates');
  return numbers as Vector3;
}
export function calibrationInput(base: readonly string[], forward: readonly string[]): ModelCalibrationInput {
  const basePoint = vector(base), direction = vector(forward);
  if (direction[1] !== 0 || direction[0] === 0 && direction[2] === 0) throw new ResourceFormError('invalidForward');
  return {unit:'m', axes:'Y_UP_RIGHT_HANDED', basePoint, forward:direction};
}
export function modelMetadata(fields: {name:string;purpose:ModelPurpose;source:string;rights:boolean}, revision:string,
    requestId:string, asset?:ProjectModelAsset): UploadModelMetadata {
  if (!fields.name.trim() || !fields.source.trim() || !fields.rights) throw new ResourceFormError('sourceRequired');
  return {expectedLibraryRevision:revision,clientRequestId:requestId,
    displayName:asset?.displayName ?? fields.name.trim(),purpose:asset?.purpose ?? fields.purpose,
    sourceNote:fields.source.trim(),rightsDeclared:true,...(asset?{modelAssetId:asset.modelAssetId}:{})};
}
export interface TerrainFields {
  name:string;source:string;license:string;rights:boolean;datum:VerticalDatum|'';relativeReference:string;
  crop:boolean;bounds:readonly string[];
}
export function terrainMetadata(fields:TerrainFields,requestId:string):UploadTerrainMetadata {
  if (!fields.name.trim() || !fields.source.trim() || !fields.license.trim() || !fields.rights || !fields.datum) throw new ResourceFormError('terrainRequired');
  const common = {clientRequestId:requestId,displayName:fields.name.trim(),sourceNote:fields.source.trim(),
    licenseNote:fields.license.trim(),rightsDeclared:true as const,heightUnit:'m' as const};
  let aoi: [number,number,number,number]|undefined;
  if (fields.crop) {
    const values = fields.bounds.map(value => value.trim() ? Number(value) : NaN);
    if (values.length !== 4 || values.some(value => !Number.isFinite(value))
        || !(-180<=values[0] && values[0]<values[2] && values[2]<=180)
        || !(-80<=values[1] && values[1]<values[3] && values[3]<=84)) throw new ResourceFormError('invalidAoi');
    aoi = values as [number,number,number,number];
  }
  if (fields.datum === 'UNKNOWN_RELATIVE') {
    if (!fields.relativeReference.trim()) throw new ResourceFormError('relativeRequired');
    return {...common,verticalDatum:fields.datum,relativeReferenceId:fields.relativeReference.trim(),...(aoi?{aoi}:{})};
  }
  return {...common,verticalDatum:fields.datum,...(aoi?{aoi}:{})};
}
/** A changed business form receives a new ID; an unchanged retry reuses its ID. */
export class ResourceRequestId {
  private signature = '';
  private id = '';
  forPayload(payload: object, fileIdentity = '') {
    const signature = JSON.stringify([payload,fileIdentity]);
    if (signature !== this.signature) {this.signature = signature;this.id = crypto.randomUUID();}
    return this.id;
  }
  reset() {this.signature = '';this.id = '';}
}
/** Component-owned requests release old selections even if transport ignores abort. */
export class ResourceRequestGate {
  private current:AbortController|null = null;
  start() {
    this.cancel();const controller = new AbortController();this.current = controller;
    return {signal:controller.signal,isCurrent:()=>this.current === controller && !controller.signal.aborted};
  }
  cancel() {this.current?.abort();this.current = null;}
}
export const TERRAIN_POLL_MS = 2000;
export function terrainPending(state:string|undefined) {return state === 'queued' || state === 'processing';}
export function resourceBytes(bytes:number) {return `${(bytes/1024/1024).toFixed(2)} MiB`;}
export function resourceUploadBytes(bytes:number) {return `${bytes.toLocaleString('en-US')} B (${resourceBytes(bytes)})`;}
