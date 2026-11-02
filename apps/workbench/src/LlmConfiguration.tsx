import {useEffect,useMemo,useRef,useState} from 'react';
import {Bot,Check,ChevronRight,KeyRound,RefreshCw,Workflow} from 'lucide-react';
import {Btn,Modal} from './Primitives';
import {assistantMessage} from './assistantApi';
import {cancelled} from './api';
import type {DraftApi} from './AnalysisWorkspace';
import {llmProviderNames,llmTaskNames,modelTaskState,modelChoices,modelConfigurationApi,providerChange,type LlmConfiguration as Config,type LlmProviderConfig,type LlmTaskConfig,type LlmProvider} from './llmSettings';
import './llmConfiguration.css';

export function LlmConfiguration({api,en,onDirtyChange,onSaved}:{api:DraftApi;en:boolean;onDirtyChange?:(dirty:boolean)=>void;onSaved:()=>void}){
 const service=useMemo(()=>modelConfigurationApi(api),[api]),t=(zh:string,eng:string)=>en?eng:zh;
 const [view,setView]=useState<Config|null>(null),[error,setError]=useState<unknown>(null),[notice,setNotice]=useState(''),[reload,setReload]=useState(0),[loading,setLoading]=useState(false);
 const [provider,setProvider]=useState<LlmProviderConfig|null>(null),[task,setTask]=useState<LlmTaskConfig|null>(null);
 const alive=useRef(true),generation=useRef(0);
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;generation.current++;};},[]);
 useEffect(()=>{onDirtyChange?.(!!provider||!!task);return()=>onDirtyChange?.(false);},[!!provider,!!task,onDirtyChange]);
 useEffect(()=>{const abort=new AbortController();setLoading(true);setError(null);setView(null);setProvider(null);setTask(null);setNotice('');generation.current++;
  void service.read(abort.signal).then(v=>{if(!abort.signal.aborted)setView(v);}).catch(e=>{if(!abort.signal.aborted&&!cancelled(e))setError(e);}).finally(()=>{if(!abort.signal.aborted)setLoading(false);});return()=>abort.abort();
 },[service,api.epoch,api.revision,reload]);
 async function saved(){const current=++generation.current;const v=await service.read();if(!alive.current||current!==generation.current)return;setView(v);setProvider(null);setTask(null);setNotice(t('配置已保存，后续新任务使用此配置。','Saved. New runs use these settings.'));onSaved();}
 return <div className="llm-page">
  <header className="llm-heading"><div><h3>{t('模型来源','Model providers')}</h3><p>{t('以下配置只用于 ONTOVis 自有模型；OntoBase 服务使用其生效配置。','These settings apply to ONTOVis models. OntoBase services use their own active configuration.')}</p></div><Btn disabled={loading||!!provider||!!task} onClick={()=>setReload(n=>n+1)}><RefreshCw size={14}/>{t('刷新','Refresh')}</Btn></header>
  {!!error&&<p role="alert">{assistantMessage(error,en)}</p>}{notice&&<p role="status" className="llm-notice"><Check size={14}/>{notice}</p>}{loading&&<p role="status">{t('正在读取模型配置…','Loading model settings…')}</p>}
  {view&&<><div className="llm-provider-grid">{view.providers.map(p=><article className="llm-provider" key={p.id}><div className="llm-provider-name"><span className="llm-provider-icon"><Bot size={20}/></span><h4>{p.name}</h4></div><span className="llm-state" data-ready={p.keyConfigured}>{p.keyConfigured?t('密钥已配置','Key configured'):t('尚未配置','Not configured')}</span><p>{new URL(p.baseUrl).hostname}</p><Btn disabled={!view.canManage} onClick={()=>{setNotice('');setProvider(p);}}><KeyRound size={14}/>{t('配置 ','Configure ')}{p.name}<ChevronRight size={14}/></Btn></article>)}</div>
   <section className="llm-task-section"><header className="llm-heading"><div><h3><Workflow size={17}/>{t('按任务分配模型','Models by task')}</h3><p>{t('由 OntoBase 服务处理时，无需在此配置模型。','Tasks handled by OntoBase need no model settings here.')}</p></div><small>r{view.revision}</small></header>
    <div className="llm-task-list">{view.tasks.map(row=>{const effective=view.services[row.id],state=modelTaskState(row,effective);return <article key={row.id}><div><h4>{llmTaskNames[row.id][en?1:0]}</h4><p>{({analysis:t('分析报警、趋势与资料依据','Review alarms, trends and evidence'),query:t('查询所选资料，大屏助手默认使用','Query selected materials; default for the cockpit'),work_order:t('整理供人工复核的检查与处置建议','Prepare checks and suggestions for human review')})[row.id]}</p></div><div className="llm-task-model"><strong>{row.execution==='ontobase'?'OntoBase':llmProviderNames[row.provider]}</strong><span>{row.execution==='ontobase'?t('模型由源端管理','Model managed by OntoBase'):row.modelId||t('待选择模型','Select a model')}</span></div><span className="llm-state" data-ready={state==='ready'} title={state==='unavailable'?assistantMessage(effective?.reason||'ASSISTANT_SERVICE_UNAVAILABLE',en):undefined}>{({off:t('已关闭','Off'),ready:t('已配置','Configured'),unavailable:t('服务暂不可用','Service unavailable'),missing:t('待配置','Needs setup')})[state]}</span><Btn disabled={!view.canManage} onClick={()=>{setNotice('');setTask(row);}}>{t('设置','Set up')}<ChevronRight size={14}/></Btn></article>;})}</div>
    <details className="llm-explain"><summary>{t('配置与运行范围','Configuration and run scope')}</summary><p>{t('配置只适用于当前项目。读取模型目录不会生成内容；目录列出的型号仍需支持文本对话。密钥不会在回读或历史记录中显示。模型配置变更会停止当前运行，原回答回执保留；下一次任务使用新配置。','Settings apply only to this project. Reading a model catalogue generates no content; the chosen model must support text chat. Keys are never returned or shown in history. Changes stop active runs; saved receipts remain, and new runs use the new settings.')}</p></details>
   </section></>}
  {view&&provider&&<ProviderEditor key={provider.id} provider={provider} view={view} service={service} en={en} onClose={()=>setProvider(null)} onSaved={saved}/>}
  {view&&task&&<TaskEditor key={task.id} task={task} view={view} service={service} en={en} onClose={()=>setTask(null)} onSaved={saved}/>}
 </div>;
}
type EditorProps={view:Config;service:ReturnType<typeof modelConfigurationApi>;en:boolean;onClose:()=>void;onSaved:()=>Promise<void>};
function ProviderEditor({provider,view,service,en,onClose,onSaved}:EditorProps&{provider:LlmProviderConfig}){
 const t=(zh:string,eng:string)=>en?eng:zh;
 const [url,setUrl]=useState(provider.baseUrl),[secret,setSecret]=useState(''),[clear,setClear]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState<unknown>(null),[models,setModels]=useState<string[]|null>(null);
 const alive=useRef(true),controller=useRef<AbortController|null>(null);useEffect(()=>{alive.current=true;return()=>{alive.current=false;controller.current?.abort();};},[]);
 async function run(save:boolean){setBusy(true);setError(null);try{if(save){await service.save(view,providerChange(provider,url,'managed',secret,clear));setSecret('');await onSaved();}
  else{const abort=new AbortController();controller.current=abort;const value=await service.catalogue(view,provider.id,url,secret||null,abort.signal);if(alive.current&&!abort.signal.aborted)setModels(value.items);}}
  catch(e){if(alive.current&&!cancelled(e))setError(e);}finally{if(alive.current)setBusy(false);}}
 const changedAddress=url.trim().replace(/\/$/,'')!==provider.baseUrl;
 return <Modal className="llm-modal" title={t('配置 ','Configure ')+provider.name} description={t('当前项目的 ONTOVis 自有模型密钥','Credentials for ONTOVis models in this project')} onClose={()=>!busy&&onClose()}>
  <label className="llm-field">API Key<span className="llm-field-state">{provider.keyConfigured&&!clear&&!changedAddress?t('已保存 · 留空保持','Saved · leave blank to keep'):t('尚未填写','Enter a key')}</span><input aria-label={provider.name+' API Key'} type="password" autoComplete="new-password" spellCheck={false} value={secret} maxLength={8192} disabled={busy||clear} placeholder={provider.keyConfigured&&!changedAddress?t('输入新密钥以替换','Enter a new key to replace'):t('粘贴此来源的 API Key','Paste this provider’s API key')} onChange={e=>{setSecret(e.target.value);setModels(null);}}/></label>
  <p className="llm-caption">{t('用于 ONTOVis 自有模型；不替换或复制 OntoBase 的密钥。','Used only by ONTOVis models; it does not replace or copy OntoBase credentials.')}</p>
  <details className="llm-endpoint"><summary>{t('API 地址','API endpoint')}</summary><label className="llm-field">Base URL<input aria-label="Base URL" value={url} maxLength={300} disabled={busy} onChange={e=>{setUrl(e.target.value);setSecret('');setModels(null);}}/></label><p>{t('仅接受所选来源的官方 HTTPS 地址；更换地址需重新填写密钥。','Only official HTTPS endpoints for this provider are accepted. Enter a matching key after changing the address.')}</p></details>
  {provider.keyConfigured&&<label className="llm-clear"><input type="checkbox" checked={clear} disabled={busy} onChange={e=>{setClear(e.target.checked);setSecret('');setModels(null);}}/>{t('清除此项目保存的密钥','Clear this project’s saved key')}</label>}
  <Btn disabled={busy||clear||!secret&&(!provider.keyConfigured||changedAddress)} onClick={()=>void run(false)}><RefreshCw size={14}/>{t('读取模型目录','Read model catalogue')}</Btn>
  {models&&<div className="llm-catalogue" role="status"><strong>{t('已读取 ','Read ')+models.length+t(' 个模型',' models')}</strong><p>{models.slice(0,8).join(' · ')||t('可手工输入模型标识','Enter a model ID manually')}</p><small>{t('仅验证目录访问，未发起内容生成。','Catalogue access only; no content generation requested.')}</small></div>}
  {!!error&&<p role="alert">{assistantMessage(error,en)}</p>}<footer className="llm-editor-actions"><Btn disabled={busy} onClick={onClose}>{t('取消','Cancel')}</Btn><Btn primary disabled={busy||changedAddress&&!secret&&!clear} onClick={()=>void run(true)}>{busy?t('处理中…','Working…'):t('保存配置','Save settings')}</Btn></footer>
 </Modal>;
}
function TaskEditor({task,view,service,en,onClose,onSaved}:EditorProps&{task:LlmTaskConfig}){
 const t=(zh:string,eng:string)=>en?eng:zh;
 const [execution,setExecution]=useState(task.execution),[provider,setProvider]=useState<LlmProvider>(task.execution==='ontovis'?task.provider:view.providers.find(p=>p.keyConfigured)?.id||'openai'),[model,setModel]=useState(task.execution==='ontovis'?task.modelId:''),[enabled,setEnabled]=useState(task.enabled),[items,setItems]=useState<string[]>([]),[query,setQuery]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState<unknown>(null);
 const selected=view.providers.find(p=>p.id===provider)!,base=execution==='ontobase';
 const controller=useRef<AbortController|null>(null),alive=useRef(true);useEffect(()=>{alive.current=true;return()=>{alive.current=false;controller.current?.abort();};},[]);
 async function catalogue(){controller.current?.abort();const abort=new AbortController();controller.current=abort;setBusy(true);setError(null);try{const value=await service.catalogue(view,provider,selected.baseUrl,null,abort.signal);if(!abort.signal.aborted)setItems(value.items);}catch(e){if(!abort.signal.aborted)setError(e);}finally{if(!abort.signal.aborted)setBusy(false);}}
 async function save(){setBusy(true);setError(null);try{await service.save(view,base?{kind:'task',taskId:task.id,execution:'ontobase',enabled}:{kind:'task',taskId:task.id,execution:'ontovis',provider,modelId:model.trim(),enabled});await onSaved();}catch(e){if(alive.current)setError(e);}finally{if(alive.current)setBusy(false);}}
 return <Modal className="llm-modal" title={llmTaskNames[task.id][en?1:0]} description={t('选择任务处理方式','Choose how this task is handled')} onClose={()=>!busy&&onClose()}>
  <label className="llm-clear"><input type="checkbox" checked={enabled} disabled={busy} onChange={e=>setEnabled(e.target.checked)}/>{t('启用此任务','Enable this task')}</label>
  <div className="llm-mode"><button type="button" disabled={busy} aria-pressed={base} onClick={()=>{setExecution('ontobase');setError(null);}}>{t('由 OntoBase 服务处理','Use OntoBase service')}</button><button type="button" disabled={busy} aria-pressed={!base} onClick={()=>{setExecution('ontovis');setError(null);}}>{t('使用 ONTOVis 自有模型','Use ONTOVis model')}</button></div>
  {base?<div className="llm-inherited"><Bot size={24}/><h4>{t('跟随 OntoBase 生效配置','Follow OntoBase’s active configuration')}</h4><p>{t('基础服务内部的来源、模型和密钥均由 OntoBase 管理；此处无需配置，也不会传入覆盖参数。','OntoBase manages its service’s provider, model and credentials. No model settings or overrides are supplied here.')}</p></div>:<>
   <label className="llm-field">{t('模型来源','Provider')}<select aria-label={t('模型来源','Provider')} value={provider} disabled={busy} onChange={e=>{setProvider(e.target.value as LlmProvider);setModel('');setItems([]);setQuery('');setError(null);}}>{view.providers.map(p=><option key={p.id} value={p.id}>{p.name}{!p.keyConfigured?t(' · 未配置密钥',' · no key'):''}</option>)}</select></label>
   <label className="llm-field">{t('模型标识','Model ID')}<input aria-label={t('模型标识','Model ID')} maxLength={160} value={model} disabled={busy} placeholder={t('从目录选择，或输入准确的模型标识','Choose from the catalogue or enter an exact model ID')} onChange={e=>setModel(e.target.value)}/></label>
   <div className="llm-model-tools"><input aria-label={t('筛选模型目录','Filter model catalogue')} placeholder={t('筛选已读取的模型','Filter loaded models')} value={query} disabled={busy} onChange={e=>setQuery(e.target.value)}/><Btn disabled={busy||!selected.keyConfigured} onClick={()=>void catalogue()}><RefreshCw size={14}/>{t('读取目录','Read catalogue')}</Btn></div>
   {!selected.keyConfigured&&<p role="status" className="llm-caption">{t('请先在来源卡中配置此项目的 API Key。','Configure this project’s API key in the provider card first.')}</p>}
   {items.length>0&&<div className="llm-model-list" role="listbox" aria-label={t('可选模型','Available models')}>{modelChoices(items,query).map(id=><button type="button" role="option" aria-selected={model===id} key={id} onClick={()=>setModel(id)}>{id}{model===id&&<Check size={14}/>}</button>)}</div>}
   <p className="llm-caption">{t('目录来自当前账号；请选择支持文本对话的模型。','The catalogue comes from this account. Choose a text-chat model.')}</p>
  </>}
  {!!error&&<p role="alert">{assistantMessage(error,en)}</p>}<footer className="llm-editor-actions"><Btn disabled={busy} onClick={onClose}>{t('取消','Cancel')}</Btn><Btn primary disabled={busy||enabled&&!base&&(!selected.keyConfigured||!model.trim())} onClick={()=>void save()}>{busy?t('保存中…','Saving…'):t('保存任务配置','Save task settings')}</Btn></footer>
 </Modal>;
}
