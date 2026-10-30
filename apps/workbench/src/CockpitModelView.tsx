import {useEffect,useState} from 'react';
import {Box,Layers,Network} from 'lucide-react';
import {MOTION_MERGED_SHA} from './simulatedMotion';
import type {ModelViewRequest,ModelViewStatus} from './sceneModelView';
export function CockpitModelView({instanceId,modelVersionId,contentRevision,sha256,en,onChange,status}:{
 instanceId:string;modelVersionId:string;contentRevision:string;sha256:string;en:boolean;
 onChange:(value:ModelViewRequest|null)=>void;status:ModelViewStatus;
}){
 const [mode,setMode]=useState<'solid'|'xray'|'exploded'>('solid'),t=(zh:string,eng:string)=>en?eng:zh;
 useEffect(()=>()=>onChange(null),[onChange]);
 const supported=sha256===MOTION_MERGED_SHA;
 function choose(next:typeof mode){setMode(next);onChange(next==='solid'?null:{instanceId,modelVersionId,contentRevision,sha256,mode:next});}
 return <section className="pc-model-view" aria-label={t('模型查看','Model inspection')}><div role="group" aria-label={t('模型查看模式','Model view mode')}>{([
  ['solid',Box,t('实体','Solid')],['xray',Layers,t('透视','X-ray')],['exploded',Network,t('爆炸示意','Exploded')],
 ] as const).map(([value,Icon,label])=><button key={value} aria-pressed={mode===value} disabled={value!=='solid'&&!supported} onClick={()=>choose(value)}><Icon size={15}/>{label}</button>)}</div>
  {!supported?<small>{t('当前固定模型未适配内部查看。','Internal inspection unavailable for this fixed model.')}</small>:mode!=='solid'?<p role="status">{status==='unavailable'?t('模型内容或节点不匹配，已阻止变形。','Content or nodes do not match. Deformation blocked.'):t(mode==='xray'?'外壳半透明 · 显示源模型内部':'分组位移示意 · 非拆解步骤或测量依据',mode==='xray'?'Transparent shell · source model internals':'Illustrative group offsets · not disassembly or measurement guidance')}{' '}{t('模拟运行已结束。选择“实体”复位。','Simulation ended. Choose Solid to restore.')}</p>:null}
 </section>;
}
