import {ApiError,cancelled} from './api.ts';
import type {SceneApi} from './sceneApi';
import type {UploadImageryMetadata} from './resourceTypes';

export interface PendingImageryUpload {
  file:Blob;
  metadata:UploadImageryMetadata;
  expectedSourceSha256:string;
}

export async function prepareImageryUpload(file:Blob,metadata:UploadImageryMetadata,signal?:AbortSignal):Promise<PendingImageryUpload> {
  signal?.throwIfAborted();
  const bytes=await file.arrayBuffer();
  signal?.throwIfAborted();
  const digest=await crypto.subtle.digest('SHA-256',bytes);
  signal?.throwIfAborted();
  return {file,metadata:Object.freeze({...metadata}),
    expectedSourceSha256:[...new Uint8Array(digest)].map(value=>value.toString(16).padStart(2,'0')).join('')};
}

export function uncertainImageryUpload(error:unknown) {
  return !cancelled(error)&&(!(error instanceof ApiError)||error.status>=500||error.status===429);
}

export async function checkImageryUpload(api:Pick<SceneApi,'imageryUploadResult'>,attempt:PendingImageryUpload,signal?:AbortSignal) {
  const result=await api.imageryUploadResult(attempt.metadata,attempt.expectedSourceSha256,signal);
  if(result.state==='unknown')throw new ApiError(503,'IMAGERY_UPLOAD_UNCONFIRMED');
  if(result.state!=='completed'||result.sha256!==attempt.expectedSourceSha256
    ||result.metadata.clientRequestId!==attempt.metadata.clientRequestId)throw new ApiError(409,'RESOURCE_CHANGED');
  return result;
}
