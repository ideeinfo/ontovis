import { useEffect, useState } from 'react';
import { ApiError, cancelled, failureMessage, type WorkbenchApi } from './api';
import { Badge, Btn } from './Primitives';
import { usePreferences } from './Preferences';
import type { EngineeringObject, Installation, ModelView } from './types';

export function BindingEditor({api,model,object,context,onReload}:{api:WorkbenchApi;model:ModelView|null;object:EngineeringObject;context:Installation;onReload:()=>void}) {
  const {t,locale}=usePreferences();
  const [component,setComponent]=useState(''),[busy,setBusy]=useState(false),[saved,setSaved]=useState(false),[error,setError]=useState<unknown>(null);
  useEffect(()=>{if(model)setComponent(model.bindings.find(row=>row.entityUid===object.entityUid)?.componentKey || '');},[model,object.entityUid]);
  async function save() {
    if(!model?.modelVersionId || !component)return;
    setBusy(true);setError(null);setSaved(false);
    try {
      await api.request('/api/workbench/models/binding',{modelVersionId:model.modelVersionId,componentKey:component,entityUid:object.entityUid,expectedEntityRevision:object.entityRevision,expectedHierarchyRevision:context.hierarchyRevision,expectedModelRevision:model.modelRevision,clientRequestId:crypto.randomUUID()});
      setSaved(true);onReload();
    }catch(value){if(!cancelled(value)){setError(value);if(value instanceof ApiError && value.code==='MODEL_WRITE_FORBIDDEN')onReload();}}finally{setBusy(false);}
  }
  return <details className="cw-details cw-binding-editor"><summary>{t('demoBinding')}</summary>{model?.bindingWarnings?.some(row=>row.entityUid===object.entityUid) && <Badge tone="amber">{t('bindingChanged')}</Badge>}<label>{t('chooseComponent')}<select aria-label={t('chooseComponent')} value={component} disabled={busy || !model?.canEditBindings} onChange={event=>{setComponent(event.target.value);setSaved(false);}}><option value="">—</option>{model?.components?.map(row=><option key={row.componentKey} value={row.componentKey}>{row.displayName}{row.geometryQuality==='proxy_schematic'?` · ${t('proxy')}`:''}</option>)}</select></label><Btn primary disabled={busy || !component || !model?.canEditBindings} title={model?.canEditBindings?t('saveDemoBinding'):t('adminRequired')} onClick={()=>void save()}>{t(busy?'savingBinding':'saveDemoBinding')}</Btn>{error ? <p role="alert">{failureMessage(error,locale)}</p> : saved && model ? <p role="status">{t('bindingSaved')}</p> : null}</details>;
}
