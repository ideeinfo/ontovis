import {useEffect,useRef,useState} from 'react';
import {CloudSun,RefreshCw} from 'lucide-react';
import {cancelled,type WorkbenchApi} from './api';
import {Btn} from './Primitives';
import {WeatherCard} from './WeatherCard';
import {WEATHER_ROOT,weatherMessage,weatherProblems,type WeatherConfig,type WeatherConfigView,type WeatherView} from './weather';
import './weather.css';
export function WeatherSettings({api,en=false,active=true,onDirtyChange}:{api:WorkbenchApi;en?:boolean;active?:boolean;onDirtyChange:(v:boolean)=>void}){
 const t=(zh:string,eng:string)=>en?eng:zh;
 const [view,setView]=useState<WeatherConfigView|null>(null),[draft,setDraft]=useState<WeatherConfig|null>(null),[preview,setPreview]=useState<WeatherView|null>(null);
 const [error,setError]=useState<unknown>(null),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false),[reload,setReload]=useState(0);
 const abort=useRef<AbortController|null>(null),intent=useRef(0),request=useRef<{fingerprint:string;id:string}|null>(null);
 const dirty=!!view&&!!draft&&JSON.stringify(view.config)!==JSON.stringify(draft),valid=!!draft&&!weatherProblems(draft).length;
 useEffect(()=>{onDirtyChange(dirty);},[dirty,onDirtyChange]);useEffect(()=>()=>onDirtyChange(false),[onDirtyChange]);
 useEffect(()=>{if(!active)return;const controller=new AbortController();abort.current?.abort();abort.current=controller;const serial=++intent.current;setBusy(true);setError(null);setPreview(null);
  void api.request<WeatherConfigView>(WEATHER_ROOT+'config',{},controller.signal).then(value=>{if(!controller.signal.aborted&&serial===intent.current){setView(value);setDraft(structuredClone(value.config));}}).catch(e=>{if(!controller.signal.aborted&&!cancelled(e))setError(e);}).finally(()=>{if(!controller.signal.aborted&&serial===intent.current)setBusy(false);});
  return()=>{controller.abort();++intent.current;};
 },[api,api.epoch,api.revision,active,reload]);
 useEffect(()=>()=>abort.current?.abort(),[]);
 function change(value:WeatherConfig){setDraft(value);setPreview(null);setNotice('');setError(null);}
 async function action(kind:'save'|'test'){
  if(!draft||!view||!valid||busy)return;const controller=new AbortController();abort.current?.abort();abort.current=controller;const serial=++intent.current;setBusy(true);setError(null);setNotice('');
  const fingerprint=JSON.stringify([view.revision,draft]);if(request.current?.fingerprint!==fingerprint)request.current={fingerprint,id:crypto.randomUUID()};
  try{if(kind==='test'){
   const result=await api.request<WeatherView>(WEATHER_ROOT+'test',{config:draft,expectedAccessRevision:view.accessRevision},controller.signal);
   if(!controller.signal.aborted&&serial===intent.current){setPreview(result);setNotice(t('查询完成，未修改已保存配置。','Query completed; saved settings are unchanged.'));}
  }else{
   const result=await api.request<WeatherConfigView>(WEATHER_ROOT+'save',{config:draft,expectedRevision:view.revision,expectedAccessRevision:view.accessRevision,requestId:request.current.id},controller.signal);
   if(!controller.signal.aborted&&serial===intent.current){setView(result);setDraft(structuredClone(result.config));setPreview(null);setNotice(t('配置已保存','Settings saved')+' · r'+result.revision);}
  }}catch(e){if(!controller.signal.aborted&&!cancelled(e))setError(e);}finally{if(!controller.signal.aborted&&serial===intent.current)setBusy(false);}
 }
 return <section className="wx-settings" aria-label={t('天气接口','Weather API')}><header><div><h2><CloudSun size={18}/>{t('天气接口','Weather API')}</h2><p>{t('配置项目天气接口，自动使用场景地理锚点提供有来源的预报。','Configure project weather API to provide sourced forecasts from scene geographic anchors.')}</p></div><Btn disabled={busy||dirty} onClick={()=>setReload(v=>v+1)}><RefreshCw size={14}/>{t('重新读取','Reload')}</Btn></header>
  {!!error&&<p role="alert">{weatherMessage(error,en)}</p>}{notice&&<p role="status">{notice}</p>}{busy&&!view&&<p role="status">{t('正在读取配置…','Loading settings…')}</p>}
  {view&&draft&&<div className="wx-settings-grid"><main><fieldset disabled={busy||!view.canManage}><legend>{t('接口配置','API settings')}</legend><label className="wx-toggle"><input type="checkbox" checked={draft.enabled} onChange={e=>change({...draft,enabled:e.target.checked})}/>{t('启用本项目天气','Enable project weather')}</label><div className="wx-fields"><label>{t('数据来源','Provider')}<input readOnly value="MET Norway · Locationforecast 2.0"/></label><label>{t('最小更新间隔','Minimum update interval')}<select value={draft.refreshMinutes} onChange={e=>change({...draft,refreshMinutes:Number(e.target.value) as WeatherConfig['refreshMinutes']})}>{[180,360,720].map(v=><option key={v} value={v}>{v/60} {t('小时','hours')}</option>)}</select></label><label className="wx-wide">API {t('地址','endpoint')}<input readOnly value={view.endpoint}/></label><label className="wx-wide">{t('联系链接或业务邮箱','Contact link or business email')}<input value={draft.contact} maxLength={200} onChange={e=>change({...draft,contact:e.target.value})}/><small>{t('应能联系到技术维护人员；无需 API Key。','Must reach technical maintainers; no API key needed.')}</small></label></div></fieldset>
   <p className="wx-caption">{t('已定位场景自动使用自身地理锚点查询天气（截断至四位小数），只向天气来源发送坐标和联系标识。','Geolocated scenes automatically query weather using their own geographic anchor (truncated to four decimals); only coordinates and contact identification are sent.')}</p>
   {view.legacySceneIds!==undefined&&<p className="wx-caption">{t('旧配置仍仅对原有场景生效。点击“启用项目范围并保存”后，才会使用本项目全部已定位场景的坐标查询。','Legacy settings retain their original scene scope. Save project scope explicitly to query all geolocated scenes in this project.')}</p>}
   {!valid&&<p role="status">{t('请填写有效的联系链接（https://）或业务邮箱。','Enter a valid HTTPS contact link or business email.')}</p>}
   <div className="wx-actions"><Btn disabled={busy||!view.canManage||!valid} onClick={()=>void action('test')}>{t('测试查询','Test query')}</Btn><Btn primary disabled={busy||!view.canManage||!valid||(!dirty&&view.legacySceneIds===undefined)} onClick={()=>void action('save')}>{view.legacySceneIds!==undefined?t('启用项目范围并保存','Save project scope'):t('保存配置','Save settings')}</Btn><Btn disabled={busy||!dirty} onClick={()=>change(structuredClone(view.config))}>{t('放弃修改','Discard changes')}</Btn><span>r{view.revision}{dirty?' · '+t('有未保存修改','Unsaved changes'):''}</span></div>{!view.canManage&&<p>{t('当前账号只读；保存与测试查询需要项目管理员。','Read only; saving and test queries require a project administrator.')}</p>}
  </main><aside><h3>{t('草稿查询预览','Draft query preview')}</h3>{preview?<WeatherCard value={preview} en={en}/>:<p>{t('点击“测试查询”验证当前接口配置。测试不会保存或启用项目配置。','Click "Test query" to verify API settings. Testing does not save or enable settings.')}</p>}<p className="wx-caption">{t('全球模式预报不能代替现场观测或设备遥测。风速为地面以上 10 m，不用于推算风机转速、偏航或变桨。','Global model forecasts do not replace site observations or equipment telemetry. The 10 m wind cannot determine rotor speed, yaw or pitch.')}</p></aside></div>}
 </section>;
}
