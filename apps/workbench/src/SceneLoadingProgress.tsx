import type {SceneLoadingState} from './sceneLoading';
import './sceneLoading.css';

export function SceneLoadingProgress({locale,state,phase='scene'}:{locale:string;state?:SceneLoadingState;phase?:'scene'|'list'|'viewer'}){
  const english=locale==='en';
  const label=state?(state.stage==='display'?(english?'Generating the view':'正在生成画面'):(english?'Preparing scene resources':'正在准备场景资源')):
    phase==='list'?(english?'Reading scene list':'正在读取场景列表'):phase==='viewer'?(english?'Preparing the viewer':'正在准备视图'):(english?'Reading scene configuration':'正在读取场景配置');
  return <div className="sw-loading" role="status" aria-live="polite"><strong>{label}</strong>
    <progress aria-label={english?'Scene preparation progress':'场景准备进度'} max={state?.total??1} value={state?.completed}/>
    <small>{state?`${state.completed}/${state.total} · ${Math.floor(state.completed/state.total*100)}% · ${english?'preparation steps':'准备步骤'}`:
      (english?'Waiting for the server; the resource total is not known yet.':'正在等待响应，资源总数尚未确定。')}</small>
  </div>;
}
