import {useState} from 'react';
import {Box,Layers,Network} from 'lucide-react';
import type {ModelViewRequest,ModelViewStatus} from './sceneModelView';
export function CockpitModelView({instanceId,modelVersionId,contentRevision,sha256,en,mode:controlledMode,onChange,onModeSelect,status,canInspect,pending=false}:{
 instanceId:string;modelVersionId:string;contentRevision:string;sha256:string;en:boolean;
 mode?:'solid'|'xray'|'exploded';onChange:(value:ModelViewRequest|null)=>void;onModeSelect?:(mode:'solid'|'xray'|'exploded')=>void;
 status:ModelViewStatus;canInspect:boolean;pending?:boolean;
}){
 const [localMode,setLocalMode]=useState<'solid'|'xray'|'exploded'>('solid'),t=(zh:string,eng:string)=>en?eng:zh;
 const activeMode=controlledMode??localMode;
 const supported=canInspect;
 function choose(next:typeof activeMode){
  if(pending)return;
  setLocalMode(next);
  onModeSelect?.(next);
  onChange(next==='solid'?null:{instanceId,modelVersionId,contentRevision,sha256,mode:next});
 }
 return <section className="pc-model-view" aria-label={t('模型查看','Model inspection')}><div role="group" aria-label={t('模型查看模式','Model view mode')}>{([
  ['solid',Box,t('实体','Solid')],['xray',Layers,t('透视','X-ray')],['exploded',Network,t('爆炸示意','Exploded')],
 ] as const).map(([value,Icon,label])=><button key={value} aria-pressed={activeMode===value} disabled={pending||value!=='solid'&&!supported} onClick={()=>choose(value)}><Icon size={15}/>{label}</button>)}</div>
  {!supported&&!pending?<small>{t('当前模型仅支持实体','Solid view only for this model')}</small>:activeMode!=='solid'?<p role="status">{status==='unavailable'?t('模型内容或节点不匹配，已阻止变形。','Content or nodes do not match. Deformation blocked.'):t(activeMode==='xray'?'外壳半透明 · 显示源模型内部':'分组位移示意 · 非拆解步骤或测量依据',activeMode==='xray'?'Transparent shell · source model internals':'Illustrative group offsets · not disassembly or measurement guidance')}</p>:null}
 </section>;
}
