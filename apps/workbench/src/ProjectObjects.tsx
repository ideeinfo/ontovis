import {useEffect,useState} from 'react';
import {SceneObjectsPanel} from './SceneObjectsPanel';
import {SceneApi} from './sceneApi';
import {cancelled,failureMessage,type WorkbenchApi} from './api';
import type {SceneObjectContext} from './sceneEngineeringTypes';
import {usePreferences} from './Preferences';
import {SourceEvidence} from './SourceEvidence';

export function ProjectObjects({api}:{api:WorkbenchApi}){
  const {locale}=usePreferences(),en=locale==='en';
  const [uid,setUid]=useState(''),[detail,setDetail]=useState<SceneObjectContext|null>(null),[error,setError]=useState<unknown>(null);
  useEffect(()=>{
    const abort=new AbortController();setDetail(null);setError(null);
    if(uid)void new SceneApi(api).objectContext(uid,undefined,abort.signal).then(value=>{if(!abort.signal.aborted)setDetail(value);})
      .catch(error=>{if(!abort.signal.aborted&&!cancelled(error))setError(error);});
    return()=>abort.abort();
  },[api,uid]);
  return <div className="pv-object-browser"><SceneObjectsPanel api={api} root={detail} selectedUid={uid} ancestorUids={detail?.ancestors.path.map(row=>row.object.entityUid)||[]} onSelect={setUid}/>
    <section className="cw-panel"><header><strong>{detail?.item.displayName||(en?'Project objects':'项目对象')}</strong></header><div className="cw-page-body">{error?<p role="alert">{failureMessage(error,locale)}</p>:detail?<><p>{[...detail.ancestors.path].reverse().map(row=>row.object.displayName).concat(detail.item.displayName).join(' › ')}</p><dl className="cw-kv"><dt>{en?'Object identity':'对象身份'}</dt><dd className="ov-mono">{detail.item.entityUid}</dd><dt>{en?'Project':'所属项目'}</dt><dd>{detail.objectRef.projectCode}</dd><dt>{en?'Installation':'安装范围'}</dt><dd>{detail.context?.displayName||'—'}</dd></dl><SourceEvidence api={api} object={detail.item} context={detail.context} host="—" endpointPrefix="/api/workbench/objects/evidence"/></>:<p>{en?'Select an object to view its physical path and documents.':'选择项目对象，查看其物理路径和自身资料。'}</p>}</div></section></div>;
}
