import type {ProjectRef} from './projectTypes';
import type {SceneView} from './sceneTypes';

export type CockpitEntry = {sceneId:string;sceneRevision:string;instanceId:string|null;camera?:SceneView};
export type CockpitAddress = {projectRef:ProjectRef;entry:CockpitEntry|null};

const prefix='#cockpit?';
const identifier='[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}';
const uuid=new RegExp(`^${identifier}$`);
const revision=new RegExp(`^scene:${identifier}$`);

export function cockpitAddress(project:ProjectRef,entry:CockpitEntry|null):string {
 const params=new URLSearchParams({connection:project.ontobaseConnectionId,project:project.projectCode});
 if(entry){
  params.set('scene',entry.sceneId);params.set('revision',entry.sceneRevision);
  if(entry.instanceId)params.set('instance',entry.instanceId);
 }
 return prefix+params.toString();
}

// Undefined is a workbench location. Null identifies a malformed cockpit link.
export function readCockpitAddress(hash:string):CockpitAddress|null|undefined {
 if(hash!=='#cockpit'&&!hash.startsWith(prefix))return undefined;
 if(hash.length>2400)return null;
 const params=new URLSearchParams(hash.slice(prefix.length));
 const fields=new Set(['connection','project','scene','revision','instance']);
 for(const key of params.keys())if(!fields.delete(key))return null;
 const ontobaseConnectionId=params.get('connection')||'',projectCode=params.get('project')||'';
 if(![ontobaseConnectionId,projectCode].every(value=>value.length>0&&value.length<=200&&value===value.trim()&&!/[\p{Cc}\uFFFD]/u.test(value)))return null;
 const projectRef={ontobaseConnectionId,projectCode};
 const sceneId=params.get('scene'),sceneRevision=params.get('revision'),instanceId=params.get('instance');
 if(sceneId===null&&sceneRevision===null&&instanceId===null)return {projectRef,entry:null};
 if(!sceneId||!uuid.test(sceneId)||!sceneRevision||!revision.test(sceneRevision)||instanceId!==null&&!uuid.test(instanceId))return null;
 return {projectRef,entry:{sceneId,sceneRevision,instanceId}};
}

export function cockpitViewKey(sceneKey:string,instanceId:string|null):string {
 return instanceId?`${sceneKey}:${instanceId}`:sceneKey;
}
