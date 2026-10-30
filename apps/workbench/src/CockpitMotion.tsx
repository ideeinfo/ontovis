import {Pause,Play,RotateCcw,Rotate3D,SlidersHorizontal,Check} from 'lucide-react';
import {Btn} from './Primitives';
import {modelSimulation,type SimulationPreset} from './cockpitSimulation';
import type {useCockpitSimulation} from './useCockpitSimulation';
import {motionProfile,type MotionStatus} from './simulatedMotion';
import type {SceneOpen,SceneModelInstance,ModelResourceRef} from './sceneTypes';
import './cockpitMotion.css';

export function CockpitMotion({simulation,opened,selected,selectedRef,status,en,paused,inspecting,sceneCount}:{
 simulation:ReturnType<typeof useCockpitSimulation>;opened:SceneOpen|null;selected?:SceneModelInstance;selectedRef?:ModelResourceRef|null;
 status:Record<string,MotionStatus>;en:boolean;paused:boolean;inspecting:boolean;sceneCount:number;
}){
 const t=(zh:string,eng:string)=>en?eng:zh;
 const models=opened?.snapshot.instances??[],refs=new Map(opened?.resourceRefs.map(r=>[r.modelVersionId,r.sha256]));
 const dynamic=models.filter(m=>!!motionProfile(refs.get(m.modelVersionId)??'')).length;
 const running=simulation.running&&!paused&&!simulation.reduced,ready=Object.values(status).filter(s=>s==='ready').length,failed=Object.values(status).filter(s=>s==='unavailable').length;
 const preset=selected&&selectedRef?modelSimulation(selected.sceneModelInstanceId,selectedRef.sha256,simulation.preset):null;
 const custom=selected?simulation.overrides[selected.sceneModelInstanceId]:null;
 const rpm=custom?.rpm??preset?.rpm??0,yaw=custom?.yaw??preset?.yaw??0,axes=custom?.axes??false;
 const change=(value:Parameters<typeof simulation.setModel>[2])=>{if(selected&&selectedRef)simulation.setModel(selected.sceneModelInstanceId,selectedRef.sha256,value);};
 const presets:[SimulationPreset,string,string][]=[['balanced',t('均衡运行','Balanced'),t('按型号分配转速','Model-specific speeds')],['slow',t('低速展示','Slow'),t('便于观察叶轮','Gentle rotor movement')],['stopped',t('停机展示','Stationary'),t('保持设备姿态','Stationary equipment')]];
 return <section className="pc-motion" aria-label={t('全场模拟运行','Scene simulation')}>
  <div className="pc-motion-hero"><div className={'pc-motion-illustration '+(running&&simulation.preset!=='stopped'?'running':'')} aria-hidden="true">
   <svg viewBox="0 0 100 100"><path className="tower" d="M47 48L44 92H56L53 48"/><g className="rotor"><path d="M50 48L47 8Q45 3 50 3L54 41Z"/><path d="M50 48L84 67Q89 69 87 73L54 53Z"/><path d="M50 48L20 70Q15 74 13 70L44 47Z"/><circle cx="50" cy="48" r="4"/></g></svg>
  </div><div><span className="pc-motion-eyebrow">{t('所有场景 · 自动预设','ALL SCENES · AUTO PRESETS')}</span><h3>{t('全场模拟运行','Scene simulation')}</h3><p><i className={running?'running':''}/>{simulation.reduced?t('系统减少动态','Reduced motion'):paused?t('可视化已暂停','Visuals paused'):!simulation.running?t('已暂停','Paused'):simulation.preset==='stopped'?t('停机预设','Stationary preset'):t('加载即运行','Runs on load')}<strong>{t('模拟','SIM')}</strong></p></div></div>
  <div className="pc-motion-stats"><div><b>{sceneCount}</b><span>{t('场景自动应用','Scenes covered')}</span></div><div><b>{opened?dynamic:'—'}</b><span>{t('本场运动预设','Motion presets here')}</span></div><div><b>{opened?models.length-dynamic:'—'}</b><span>{t('本场静态预设','Static presets here')}</span></div></div>
  <div className="pc-motion-presets" role="group" aria-label={t('运行预设','Operation presets')}>{presets.map(([id,label,hint])=><button key={id} aria-pressed={simulation.preset===id} onClick={()=>simulation.choosePreset(id)}><span>{label}{simulation.preset===id&&<Check size={14}/>}</span><small>{hint}</small></button>)}</div>
  <div className="pc-motion-actions"><Btn onClick={()=>simulation.setRunning(!simulation.running)} disabled={paused}>{simulation.running?<Pause size={15}/>:<Play size={15}/ >}{simulation.running?t('暂停全场','Pause all'):t('继续运行','Resume all')}</Btn><Btn onClick={simulation.reset}><RotateCcw size={15}/>{t('恢复预设','Restore presets')}</Btn></div>
  {selected&&selectedRef&&preset?.dynamic&&<details className="pc-motion-tuning"><summary><SlidersHorizontal size={15}/>{t('选中模型微调','Fine-tune selected model')}<span>{selected.displayName}</span></summary>
   <div className="pc-motion-values"><label>{t('转速','Speed')}<b>{rpm} rpm</b><input aria-label={t('模拟转速','Simulated speed')} type="range" min="0" max="20" step=".5" value={rpm} onChange={e=>change({rpm:Number(e.target.value)})}/></label>
    <label>{t('偏航偏移','Yaw offset')}<b>{yaw}°</b><input aria-label={t('模拟偏航','Simulated yaw')} type="range" min="0" max="359" value={yaw} onChange={e=>change({yaw:Number(e.target.value)})}/></label></div>
   <label className="pc-motion-axis"><input type="checkbox" checked={axes} onChange={e=>change({axes:e.target.checked})}/>{t('显示运动轴线','Show motion axes')}</label>
   {inspecting&&<small>{t('构件检查使用静态姿态；返回整机后自动继续。','Inspection uses the static pose; return to the whole model to resume.')}</small>}
  </details>}
  <footer><Rotate3D size={14}/><span>{t('模拟数据 · 与天气及现场遥测独立','Simulated data · independent of weather and telemetry')}</span>{!!failed&&<span role="status">{failed} {t('个模型未通过动作校验','models failed motion validation')}</span>}{opened&&dynamic>0&&ready===0&&!inspecting&&!failed&&<span role="status">{t('等待模型加载','Waiting for models')}</span>}</footer>
 </section>;
}
