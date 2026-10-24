import {useEffect,useRef,useState} from 'react';
import {Box} from 'lucide-react';
import type {SceneApi} from './sceneApi';
import type {ModelThumbnailInfo,ProjectModelVersionSummary} from './resourceTypes';
import {cancelled} from './api';
import {usePreferences} from './Preferences';

export function ModelThumbnail({api,version,name,onStatus}:{api:SceneApi;version:ProjectModelVersionSummary|null;
  name:string;onStatus:(sha256:string,value:ModelThumbnailInfo)=>void}) {
  const {locale}=usePreferences(),element=useRef<HTMLSpanElement>(null),callback=useRef(onStatus);callback.current=onStatus;
  const [visible,setVisible]=useState(false),[loaded,setLoaded]=useState<{key:string;url:string}|null>(null),[failed,setFailed]=useState(false);
  const info=version?.thumbnail;
  const key=JSON.stringify([version?.modelVersionId,version?.contentRevision,version?.sha256,info?.thumbnailRevision]);
  const url=loaded?.key===key?loaded.url:null;
  useEffect(()=>{
    if(!element.current)return;
    if(typeof IntersectionObserver==='undefined'){setVisible(true);return;}
    const observer=new IntersectionObserver(entries=>{if(entries.some(entry=>entry.isIntersecting)){setVisible(true);observer.disconnect();}},{rootMargin:'100px'});
    observer.observe(element.current);return()=>observer.disconnect();
  },[]);
  useEffect(()=>{
    setLoaded(null);setFailed(false);
    if(!visible||!version)return;
    const controller=new AbortController();let owned:string|null=null,timer:ReturnType<typeof setTimeout>|undefined;
    if(info?.state==='ready')void api.modelThumbnailContent(version,info,controller.signal).then(blob=>{
      if(controller.signal.aborted)return;owned=URL.createObjectURL(blob);setLoaded({key,url:owned});
    }).catch(error=>{if(!controller.signal.aborted&&!cancelled(error))setFailed(true);});
    else if(info?.state==='queued'||info?.state==='processing'){
      const poll=()=>void api.modelThumbnail(version,controller.signal).then(value=>{
        if(controller.signal.aborted)return;callback.current(version.sha256,value.thumbnail);
        if(value.thumbnail.state==='queued'||value.thumbnail.state==='processing')timer=setTimeout(poll,2000);
      }).catch(error=>{if(!controller.signal.aborted&&!cancelled(error))setFailed(true);});
      timer=setTimeout(poll,2000);
    }
    return()=>{controller.abort();if(timer)clearTimeout(timer);if(owned)URL.revokeObjectURL(owned);};
  },[api,visible,key,info?.state]);
  const pending=info?.state==='queued'||info?.state==='processing';
  const label=failed||info?.state==='failed'?(locale==='zh'?'缩略图未就绪':'Thumbnail unavailable'):
    pending?(locale==='zh'?'生成中':'Generating'):(locale==='zh'?'模型':'Model');
  return <span ref={element} className={`ov-resource-card-icon ov-model-thumbnail ${url?'ready':''}`} title={url?name:label}>
    {url?<img src={url} alt={`${name} ${locale==='zh'?'缩略图':'thumbnail'}`} width={56} height={62} decoding="async" draggable={false}
      onError={()=>{if(url)URL.revokeObjectURL(url);setFailed(true);setLoaded(null);}}/>:<><Box size={30} aria-hidden="true"/><span>{label}</span></>}
  </span>;
}
