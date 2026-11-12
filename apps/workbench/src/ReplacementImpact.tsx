import {usePreferences} from './Preferences';
import {sceneText, type SceneMessageKey} from './sceneMessages';
import {sceneEngineeringText} from './sceneEngineeringMessages';
import type {EditableSceneSnapshot, SceneCheck} from './sceneTypes';
import './replacementImpact.css';

export interface Props {result:SceneCheck;snapshot:EditableSceneSnapshot}
type Fields=Record<string,unknown>;
const fields=(value:unknown):Fields|null=>value!==null&&typeof value==='object'&&!Array.isArray(value)?value as Fields:null;
const text=(value:unknown):string|null=>typeof value==='string'&&value.trim().length>0&&value.length<=512?value:null;
const finite=(value:unknown):value is number=>typeof value==='number'&&Number.isFinite(value);
const vector=(value:unknown):number[]|null=>Array.isArray(value)&&value.length===3&&value.every(finite)?value:null;
const count=(value:unknown):number|null=>typeof value==='number'&&Number.isSafeInteger(value)&&value>=0?value:null;
const records=(value:unknown):Fields[]|null=>Array.isArray(value)&&value.length<=100&&value.every(item=>fields(item)!==null)?value:null;
function identifiers(value:unknown):string[]|null {
  if(!Array.isArray(value)||value.length>100||!value.every(item=>text(item)!==null)||new Set(value).size!==value.length)return null;
  return value;
}

/** A read-only rendering of service impact facts; missing fields never imply zero or success. */
export function ReplacementImpact({result,snapshot}:Props) {
  const {locale}=usePreferences(),t=(key:SceneMessageKey)=>sceneText(locale,key),unknown=t('impactUnknown');
  const impact=fields(fields(result.validation)?.impact),kind=impact?.kind;
  const names=new Map(snapshot.instances.map(item=>[item.sceneModelInstanceId,item.displayName]));
  const name=(id:unknown)=>text(id)!==null?names.get(id as string)||t('impactUnknownModel'):t('impactUnknownModel');
  const number=(value:unknown,signed=false)=>{
    if(!finite(value))return unknown;
    const magnitude=Math.abs(value),formatted=value===0?'0':magnitude<1e-6||magnitude>=1e9?value.toExponential(3):
      new Intl.NumberFormat(locale==='zh'?'zh-CN':'en',{maximumFractionDigits:3,useGrouping:false}).format(value);
    return `${signed&&value>0?'+':''}${formatted}`;
  };
  const metres=(value:unknown,signed=false)=>finite(value)?`${number(value,signed)} m`:unknown;
  const tuple=(value:unknown,dimension=false)=>{
    const values=vector(value);
    return values&&(!dimension||values.every(item=>item>=0))?`${values.map(item=>number(item)).join(dimension?' × ':', ')}${dimension?' m':''}`:unknown;
  };
  const sample=(value:unknown)=>value===null?t('impactNoSample'):metres(value);
  const affected=identifiers(impact?.instanceIds);
  const strategy=(value:unknown)=>value==='keep_height'?t('keepHeight'):value==='resample_ground'?t('resampleGround'):unknown;
  const old=fields(impact?.oldModel),next=fields(impact?.newModel);
  const heightRows=records(impact?.instances),sampleIssues=records(impact?.sampleIssues);
  const metricRows:readonly [SceneMessageKey,string,string][]=[
    ['impactDimensions',tuple(old?.dimensionsM,true),tuple(next?.dimensionsM,true)],
    ['impactBasePoint',tuple(old?.basePoint),tuple(next?.basePoint)],
    ['impactComponents',count(old?.componentCount)===null?unknown:number(old?.componentCount),count(next?.componentCount)===null?unknown:number(next?.componentCount)],
  ];
  const sampleReason=(code:unknown)=>code==='NO_DATA'?t('impactNoData'):code==='OUTSIDE_COVERAGE'?t('impactOutsideCoverage'):
    code==='OUTSIDE_PROJECTION_AREA'?t('impactOutsideProjection'):unknown;
  return <section className="ov-replacement-impact" aria-label={t('impactTitle')}>
    {kind==='model_replacement'?<>
      <strong className="ov-replacement-name">{name(impact?.sceneModelInstanceId)}</strong>
      <table className="ov-replacement-comparison ov-list-table"><thead><tr><th scope="col">{t('impactProperty')}</th><th scope="col">{t('impactOld')}</th><th scope="col">{t('impactNew')}</th></tr></thead><tbody>
        {metricRows.map(([label,before,after])=><tr key={label}><th scope="row">{t(label)}</th><td>{before}</td><td>{after}</td></tr>)}
      </tbody></table>
      {result.validation.bindingIssues?.some(issue=>issue.kind==='model_version_changed'&&issue.sceneModelInstanceId===impact?.sceneModelInstanceId)&&<p className="ov-replacement-caption">{sceneEngineeringText(locale,'pendingLinks')} · {result.validation.bindingIssues.filter(issue=>issue.kind==='model_version_changed'&&issue.sceneModelInstanceId===impact?.sceneModelInstanceId).length}</p>}
      <details className="ov-replacement-details"><summary>{t('impactVersions')}</summary><dl className="ov-replacement-facts">
        <dt>{t('impactOldVersion')}</dt><dd className="ov-replacement-identity">{text(old?.modelVersionId)||unknown}</dd>
        <dt>{t('impactNewVersion')}</dt><dd className="ov-replacement-identity">{text(next?.modelVersionId)||unknown}</dd>
        <dt>{t('impactOldForward')}</dt><dd>{tuple(old?.forward)}</dd>
        <dt>{t('impactNewForward')}</dt><dd>{tuple(next?.forward)}</dd>
      </dl></details>
    </>:kind==='terrain_replacement'?<>
      <strong className="ov-replacement-name">{t('impactTerrain')}</strong>
      <dl className="ov-replacement-facts"><dt>{t('terrainStrategy')}</dt><dd>{strategy(impact?.strategy)}</dd><dt>{t('impactCount')}</dt><dd>{affected===null?unknown:number(affected.length)}</dd></dl>
      {heightRows===null?<p className="ov-replacement-caption">{unknown}</p>:<ul className="ov-replacement-instances">{heightRows.map((item,index)=>{
        const sameHeight=finite(item.oldHeightM)&&finite(item.newHeightM)&&item.oldHeightM===item.newHeightM&&item.heightDeltaM===0;
        const absoluteKept=item.oldHeightMode==='absolute'&&item.newHeightMode==='absolute'&&sameHeight;
        const estimateKept=impact?.strategy==='keep_height'&&item.oldHeightMode==='terrain_ground'&&item.newHeightMode==='absolute'&&sameHeight;
        return <li key={index}><strong>{name(item.sceneModelInstanceId)}</strong><div className="ov-replacement-heights">
          <span><small>{t('impactOldHeight')}</small>{metres(item.oldHeightM)}</span><span><small>{t('impactNewHeight')}</small>{metres(item.newHeightM)}</span><span><small>{t('impactHeightDelta')}</small>{metres(item.heightDeltaM,true)}</span>
        </div>{absoluteKept&&<p className="ov-replacement-caption">{t('impactAbsoluteKept')}</p>}{estimateKept&&<p className="ov-replacement-caption">{t('impactEstimateKept')}</p>}</li>;
      })}</ul>}
      <details className="ov-replacement-details"><summary>{t('impactSampling')}</summary>
        {heightRows===null?<p className="ov-replacement-caption">{unknown}</p>:<ul className="ov-replacement-instances">{heightRows.map((item,index)=><li key={index}><strong>{name(item.sceneModelInstanceId)}</strong><dl className="ov-replacement-facts">
          <dt>{t('impactOldSample')}</dt><dd>{sample(item.oldSampledHeightM)}</dd><dt>{t('impactNewSample')}</dt><dd>{sample(item.newSampledHeightM)}</dd><dt>{t('impactSampleDelta')}</dt><dd>{sample(item.sampledHeightDeltaM)}</dd>
        </dl></li>)}</ul>}
        <div className="ov-replacement-gap-title">{t('impactSampleIssues')} · {sampleIssues===null?unknown:number(sampleIssues.length)}</div>
        {sampleIssues&&sampleIssues.length>0&&<ul className="ov-replacement-gaps">{sampleIssues.map((issue,index)=><li key={index}><span>{name(issue.sceneModelInstanceId)}</span><span>{issue.role==='old'?t('impactOldTerrain'):issue.role==='new'?t('impactNewTerrain'):unknown} · {sampleReason(issue.code)}</span></li>)}</ul>}
      </details>
    </>:kind==='first_geographic_anchor'?<>
      <strong className="ov-replacement-name">{t('impactAnchor')}</strong><dl className="ov-replacement-facts"><dt>{t('impactConvertedCount')}</dt><dd>{affected===null?unknown:number(affected.length)}</dd>
        <dt>{t('terrainStrategy')}</dt><dd>{fields(fields(result.validation)?.anchorTransform)?.heightStrategy==='keep_relative_to_anchor'?t('keepRelative'):
          fields(fields(result.validation)?.anchorTransform)?.heightStrategy==='resample_each_ground'?t('resample'):unknown}</dd></dl>
    </>:<p className="ov-replacement-caption">{t('impactTitle')} · {unknown}</p>}
  </section>;
}
