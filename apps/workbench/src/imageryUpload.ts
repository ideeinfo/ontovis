import {ApiError,cancelled} from './api.ts';
import type {SceneApi} from './sceneApi';
import type {UploadImageryMetadata,ImageryTransferResult,ImageryUploadSession,ImageryUploadResult} from './resourceTypes';

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

function matchingResult(result:ImageryTransferResult|ImageryUploadResult,attempt:PendingImageryUpload) {
  if(result.state==='unknown')throw new ApiError(503,'IMAGERY_UPLOAD_UNCONFIRMED');
  if(!['receiving','completed'].includes(result.state))throw new ApiError(409,'RESOURCE_CHANGED');
  if(result.sha256!==attempt.expectedSourceSha256||!result.metadata
    ||Object.keys(result.metadata).length!==Object.keys(attempt.metadata).length
    ||Object.entries(attempt.metadata).some(([key,value])=>result.metadata[key as keyof UploadImageryMetadata]!==
      (typeof value==='string'?value.trim():value)))throw new ApiError(409,'RESOURCE_CHANGED');
  return result;
}

export async function checkImageryUpload(api:Pick<SceneApi,'imageryUploadResult'>,attempt:PendingImageryUpload,signal?:AbortSignal) {
  const result=matchingResult(await api.imageryUploadResult(attempt.metadata,attempt.expectedSourceSha256,signal),attempt);
  if(result.state!=='completed')throw new ApiError(503,'IMAGERY_UPLOAD_UNCONFIRMED');
  return result;
}

export interface ImageryUploadProgress {receivedBytes:number;bytes:number;phase:'receiving'|'processing';upload:ImageryUploadSession}
type TransferApi=Pick<SceneApi,'imageryUploadStart'|'imageryUploadStatus'|'imageryUploadChunk'|'imageryUploadComplete'>;

export async function sendImageryUpload(api:TransferApi,attempt:PendingImageryUpload,options:{signal?:AbortSignal;progress?:(value:ImageryUploadProgress)=>void}={}) {
  const {signal,progress}=options;
  const inspect=(response:ImageryTransferResult)=>{
    const row=matchingResult(response,attempt);
    if(row.state==='receiving'&&(!row.uploadId||!row.uploadRevision||row.bytes!==attempt.file.size
      ||!Number.isSafeInteger(row.receivedBytes)||row.receivedBytes<0||row.receivedBytes>row.bytes))throw new ApiError(409,'RESOURCE_CHANGED');
    return row;
  };
  signal?.throwIfAborted();
  let row=inspect(await api.imageryUploadStart(attempt.metadata,attempt.expectedSourceSha256,attempt.file.size,signal));
  if(row.state==='completed')return row;
  const chunkBytes=row.limits.maxChunkBytes;
  if(typeof chunkBytes!=='number'||!Number.isSafeInteger(chunkBytes)||chunkBytes<1||chunkBytes>256*1024)throw new ApiError(502,'SOURCE_UNAVAILABLE');
  while(row.state==='receiving'&&row.receivedBytes<row.bytes){
    signal?.throwIfAborted();progress?.({receivedBytes:row.receivedBytes,bytes:row.bytes,phase:'receiving',upload:row});
    const offset=row.receivedBytes,end=Math.min(offset+chunkBytes,row.bytes),uploadId=row.uploadId;
    const part=attempt.file.slice(offset,end),raw=await part.arrayBuffer();signal?.throwIfAborted();
    const digest=await crypto.subtle.digest('SHA-256',raw);signal?.throwIfAborted();
    const expectedChunkSha256=[...new Uint8Array(digest)].map(x=>x.toString(16).padStart(2,'0')).join('');
    try{row=inspect(await api.imageryUploadChunk(part,{uploadId,offset,expectedUploadRevision:row.uploadRevision,expectedChunkSha256},signal));}
    catch(error){
      if(!uncertainImageryUpload(error))throw error;
      row=inspect(await api.imageryUploadStatus(uploadId,signal));
      if(row.state==='receiving'&&row.receivedBytes<end)throw new ApiError(503,'IMAGERY_UPLOAD_UNCONFIRMED');
    }
    signal?.throwIfAborted();
    if(row.state==='receiving'&&(row.uploadId!==uploadId||row.receivedBytes<end))throw new ApiError(409,'RESOURCE_CHANGED');
  }
  if(row.state==='completed')return row;
  progress?.({receivedBytes:row.receivedBytes,bytes:row.bytes,phase:'processing',upload:row});
  const result=inspect(await api.imageryUploadComplete(row.uploadId,row.uploadRevision,signal));
  if(result.state!=='completed')throw new ApiError(503,'IMAGERY_UPLOAD_UNCONFIRMED');
  return result;
}
