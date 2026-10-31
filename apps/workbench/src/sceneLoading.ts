import type {EditableSceneSnapshot,ModelResourceRef} from './sceneTypes';

export type SceneLoadingState={completed:number;total:number;stage:'resources'|'display'|'complete'|'failed'|'cancelled'};
export const sceneLoadingIdentity=(keys:readonly string[],context?:string)=>JSON.stringify([keys,context??null]);
export const modelLoadingKey=(ref:Pick<ModelResourceRef,'modelVersionId'|'contentRevision'|'sha256'>)=>
  `model:${JSON.stringify([ref.modelVersionId,ref.contentRevision,ref.sha256])}`;
export const terrainLoadingKey=(ref:NonNullable<EditableSceneSnapshot['terrain']>)=>`terrain:${JSON.stringify([ref.terrainVersionId,ref.expectedContentRevision])}`;
export const imageryLoadingKey=(ref:NonNullable<EditableSceneSnapshot['imagery']>)=>`imagery:${JSON.stringify([ref.imageryVersionId,ref.expectedContentRevision,ref.expectedReportSha256])}`;
export function sceneLoadingPlan(snapshot:EditableSceneSnapshot,refs:ModelResourceRef[],preview?:Pick<ModelResourceRef,'modelVersionId'|'contentRevision'|'sha256'>|null){
  const keys=new Set(snapshot.instances.map(item=>{
    const ref=refs.find(value=>value.modelVersionId===item.modelVersionId);
    return ref?modelLoadingKey(ref):`missing-model:${item.modelVersionId}`;
  }));
  if(preview)keys.add(modelLoadingKey(preview));
  if(snapshot.terrain)keys.add(terrainLoadingKey(snapshot.terrain));
  if(snapshot.imagery)keys.add(imageryLoadingKey(snapshot.imagery));
  return [...keys].sort();
}

/** Resource preparation steps, followed by an actual draw submission; never a byte/time estimate. */
export class SceneLoadingTracker {
  readonly identity:string;
  private completed=new Set<string>();
  private terminal:SceneLoadingState['stage']|null=null;
  private readonly keys:readonly string[];
  private readonly changed:(state:SceneLoadingState)=>void;
  constructor(keys:readonly string[],changed:(state:SceneLoadingState)=>void,context?:string){
    this.keys=[...new Set(keys)];this.changed=changed;this.identity=sceneLoadingIdentity(this.keys,context);this.emit();
  }
  state():SceneLoadingState {
    return {completed:this.completed.size+(this.terminal==='complete'?1:0),total:this.keys.length+1,
      stage:this.terminal||(this.completed.size===this.keys.length?'display':'resources')};
  }
  done(key:string){
    if(this.terminal||!this.keys.includes(key)||this.completed.has(key))return;
    this.completed.add(key);this.emit();
  }
  drawn(){if(this.state().stage!=='display')return;this.terminal='complete';this.emit();}
  fail(){if(!this.terminal){this.terminal='failed';this.emit();}}
  cancel(){if(!this.terminal){this.terminal='cancelled';this.emit();}}
  private emit(){this.changed(this.state());}
}
