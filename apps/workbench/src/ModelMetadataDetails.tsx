import {useEffect,useRef,useState} from 'react';
import {cancelled} from './api';
import type {SceneApi} from './sceneApi';
import type {ProjectModelVersion} from './resourceTypes';
import {privateDenial,resourceFailure} from './resourceForms';
import {usePreferences} from './Preferences';
import {modelPropertyLabel,metadataSourceUrl,type ModelResourceMetadata as Metadata} from './modelResourceMetadata';

export function ModelResourceMetadata({api,version,onPrivateDenied}:{api:SceneApi;version:ProjectModelVersion;onPrivateDenied:()=>void}) {
  const {locale}=usePreferences(),text=(zh:string,en:string)=>locale==='zh'?zh:en;
  const [open,setOpen]=useState(false),[item,setItem]=useState<Metadata|null>(null),[read,setRead]=useState(false),[error,setError]=useState<unknown>(null);
  const request=useRef<AbortController|null>(null);
  useEffect(()=>()=>request.current?.abort(),[api,version.modelVersionId]);
  async function load(){
    request.current?.abort();const controller=new AbortController();request.current=controller;setRead(false);setError(null);
    try{const value=await api.modelMetadata(version.modelAssetId,version.modelVersionId,controller.signal);
      if(!controller.signal.aborted){setItem(value.item);setRead(true);}}
    catch(value){if(!controller.signal.aborted&&!cancelled(value)){setItem(null);setError(value);setRead(true);if(privateDenial(value))onPrivateDenied();}}
  }
  const scopes:Record<string,string>={type:text('型号','Type'),site_configuration:text('场站配置','Site configuration'),program_default:text('程序默认','Program default'),teaching_reference:text('教学参考','Teaching reference'),teaching_variant:text('教学变体','Teaching variant'),platform_reference:text('平台参考','Platform reference')};
  const kinds={page_declared:text('来源声明','Source declaration'),program_geometry_parameter:text('几何程序参数','Geometry parameter'),
    simulation_operating_parameter:text('教学模拟参数','Simulation parameter'),derived_calculation:text('推导值','Derived value')};
  return <details className="ov-resource-disclosure" open={open} onToggle={event=>{const value=event.currentTarget.open;setOpen(value);if(value&&!read&&!request.current)void load();}}>
    <summary>{text('型号属性与证据','Model properties and evidence')}</summary>
    {!read&&<p className="ov-resource-caption" role="status">{text('正在读取…','Loading…')}</p>}
    {!!error&&<><p role="alert" className="ov-resource-error">{resourceFailure(error,locale)}</p><button type="button" className="sw-text-button" onClick={()=>void load()}>{text('重试','Retry')}</button></>}
    {read&&!error&&!item&&<p className="ov-resource-caption">{text('尚未录入型号属性；几何报告和来源说明仍可查看。','No model properties recorded. Geometry reports and source notes remain available.')}</p>}
    {item&&<><p className="ov-resource-caption">{text('型号资源属性，未经制造商或现场核实；不代表已安装设备属性。','Model resource properties, not verified against the manufacturer or site; they do not confirm installed equipment.')}</p>
      <dl className="ov-resource-facts pm-metadata">{Object.entries(item.metadata.fields).map(([key,evidence])=><div key={key}>
        <dt>{modelPropertyLabel(key,locale)}</dt><dd>{evidence?.length?evidence.map((entry,index)=>{const url=metadataSourceUrl(entry.source.url);return <div key={index}>
          <strong>{entry.value===null?'—':String(entry.value)}{entry.unit?` ${entry.unit}`:''}</strong><span className="ov-resource-caption"> · {kinds[entry.kind]||entry.kind} · {scopes[entry.scope]||entry.scope}</span>
          <details><summary>{text('来源与依据','Source and basis')}</summary><p className="ov-resource-caption">{entry.note||entry.source.locator}</p>{url&&<a href={url} target="_blank" rel="noreferrer">{text('来源页面','Source page')}</a>}
            <p className="ov-resource-caption">{text('原文位置','Source lines')} {entry.source.lineStart}–{entry.source.lineEnd} · SHA256 {entry.source.pageSha256}</p></details>
        </div>;}):<span className="ov-resource-caption">{text('资料未给出','Not supplied')}</span>}</dd></div>)}</dl>
      {item.metadata.cautions.length>0&&<details><summary>{text('适用范围与差异','Scope and differences')}</summary>{item.metadata.cautions.map((note,index)=><p className="ov-resource-caption" key={index}>{note}</p>)}</details>}
      <p className="ov-resource-caption">{text('属性修订','Metadata revision')} {item.metadataRevision} · {new Date(item.createdAt).toLocaleString(locale)}</p>
    </>}
  </details>;
}
