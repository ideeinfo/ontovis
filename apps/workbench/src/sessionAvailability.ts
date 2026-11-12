import {ApiError} from './api.ts';
import type {SessionView} from './types.ts';

export function keepWorkspaceOnSessionFailure(error:unknown,session:SessionView|null,signingOut:boolean){
  return !signingOut&&session?.state==='active'&&
    (error instanceof TypeError||error instanceof ApiError&&error.status>=500&&error.status<=599);
}
