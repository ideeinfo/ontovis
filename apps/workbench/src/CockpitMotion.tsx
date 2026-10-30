import {useEffect,useRef,useState} from 'react';
import {Pause,Play,RotateCcw,Rotate3D} from 'lucide-react';
import {Btn} from './Primitives';
import {motionProfile,MOTION_SOURCE,type MotionQuality,type MotionRequest,type MotionStatus} from './simulatedMotion';
import './cockpitMotion.css';

export function CockpitMotion({instanceId,modelVersionId,contentRevision,sha256,name,en,onChange,status}:{
 instanceId:string;modelVersionId:string;contentRevision:string;sha256:string;name:string;en:boolean;
 onChange:(value:MotionRequest|null)=>void;status:MotionStatus;
}){
 const t=(zh:string,eng:string)=>en?eng:zh;
 const [epoch,setEpoch]=useState(''),[playing,setPlaying]=useState(false),[rpm,setRpm]=useState(8),[yaw,setYaw]=useState(0),[axes,setAxes]=useState(true),[quality,setQuality]=useState<MotionQuality>('good');
 const sequence=useRef(0),supported=!!motionProfile(sha256);
 const reset=()=>{setEpoch('');setPlaying(false);setQuality('good');onChange(null);};
 useEffect(()=>{if(!epoch)return;const emit=()=>{const now=performance.now();onChange({instanceId,modelVersionId,contentRevision,sha256,epoch,playing,axes,
  sample:{sourceId:MOTION_SOURCE,epoch,seq:++sequence.current,issuedAt:quality==='stale'?now-3000:now,validUntil:quality==='stale'?now-500:now+2500,rpm,yawDeg:yaw,rpmUnit:'rpm',yawUnit:'deg',quality}});};
  emit();const timer=window.setInterval(emit,1000);return()=>window.clearInterval(timer);
 },[instanceId,modelVersionId,contentRevision,sha256,epoch,playing,axes,quality,rpm,yaw,onChange]);
 useEffect(()=>{const visibility=()=>{if(document.hidden)reset();};document.addEventListener('visibilitychange',visibility);
  return()=>{document.removeEventListener('visibilitychange',visibility);onChange(null);};
 },[onChange]);
 const qualityLabel={good:t('有效模拟','Valid simulation'),bad:t('质量异常 · 冻结','Bad quality · frozen'),stale:t('数据过期 · 冻结','Expired · frozen'),offline:t('连接中断 · 冻结','Disconnected · frozen')}[quality];
 return <section className="pc-motion" aria-label={t('模拟运行','Simulated operation')}>
  <header><Rotate3D size={17}/><h3>{t('模拟运行','Simulated operation')}</h3><strong>{t('模拟','SIMULATED')}</strong></header>
  <p className="pc-motion-target">{t('作用模型','Target model')}：{name}</p>
  <small>{t('本机演示源 · 非设备实测，与天气独立','Local demonstration · not measured telemetry; independent of weather')}</small>
  {!supported?<p role="status">{t('该固定模型暂无动作适配，保持静态。','Motion is unavailable for this fixed model.')}</p>:<>
   <div className="pc-motion-values"><label>{t('模拟转速','Simulated speed')}<select aria-label={t('模拟转速','Simulated speed')} value={rpm} onChange={e=>setRpm(Number(e.target.value))}>{[0,4,8,12,20].map(v=><option key={v} value={v}>{v} rpm</option>)}</select></label>
    <label>{t('偏航偏移','Yaw offset')}<select aria-label={t('偏航偏移','Yaw offset')} value={yaw} onChange={e=>setYaw(Number(e.target.value))}>{[0,1,90,180,270,359].map(v=><option key={v} value={v}>{v}°</option>)}</select></label></div>
   <div className="pc-motion-actions"><Btn onClick={()=>{if(!epoch)setEpoch(crypto.randomUUID());setPlaying(v=>!v);}} disabled={status==='unavailable'}>{playing?<Pause size={14}/>:<Play size={14}/ >}{playing?t('暂停','Pause'):epoch?t('继续演示','Resume demo'):t('开始模拟','Start simulation')}</Btn><Btn onClick={reset} disabled={!epoch}><RotateCcw size={14}/>{t('复位','Reset')}</Btn></div>
   <p role="status">{status==='unavailable'?t('节点或校准不匹配，已阻止动作。','Node or calibration mismatch. Motion blocked.'):epoch?`${playing?qualityLabel:t('已暂停 · 姿态冻结','Paused · pose frozen')} · ${status==='ready'?t('几何适配已核验','Geometry verified'):t('模型加载中','Loading model')}`:t('尚未开始 · 原始姿态','Not started · original pose')}</p>
   <details><summary>{t('轴向核验与异常演练','Axis checks and failure simulation')}</summary>
    <label><input type="checkbox" checked={axes} onChange={e=>setAxes(e.target.checked)}/>{t('显示运动轴线','Show motion axes')}</label>
    <p><span className="pc-motion-y">●</span> {t('青色 +Y：偏航轴，正偏移顺时针','Cyan +Y: yaw axis; positive offset clockwise')}<br/><span className="pc-motion-z">●</span> {t('金色 +Z：叶轮轴，正转遵循右手方向','Gold +Z: rotor axis; positive right-hand rotation')}</p>
    <label>{t('模拟数据质量','Simulated data quality')}<select aria-label={t('模拟数据质量','Simulated data quality')} value={quality} onChange={e=>setQuality(e.target.value as MotionQuality)}><option value="good">{t('正常','Good')}</option><option value="bad">{t('质量异常','Bad quality')}</option><option value="stale">{t('过期','Expired')}</option><option value="offline">{t('断连','Disconnected')}</option></select></label>
    <p>{t('核验：0 rpm 停转；90° 偏航只转机舱与叶轮；359°→1° 最短路径；异常冻结；复位还原。偏航为模型零位偏移，不是真北航向。','Check: 0 rpm stops; 90° yaw rotates nacelle and rotor only; 359°→1° takes the short path; invalid data freezes; reset restores. Yaw is relative to model zero, not true north.')}</p>
    <small>{t('TU-3000 教学模型 · 当前固定内容适配；不构成工程轴向确认。切换设备、页面或隐藏后结束演示。','TU-3000 teaching model · fixed-content mapping, not engineering axis approval. Switching equipment, pages or hiding ends the demo.')}</small>
   </details>
  </>}
 </section>;
}
