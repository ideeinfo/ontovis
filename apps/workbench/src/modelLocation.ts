import type { ModelView, ObjectView } from './types';

export function bindingNeedsReview(detail:ObjectView|null, model:ModelView|null) {
  if(!detail || !model)return false;
  const objects=[detail.item,...detail.ancestors.path.map(row=>row.object)];
  return objects.some(item=>model.bindingWarnings?.some(row=>row.entityUid===item.entityUid)
    || model.bindings.some(row=>row.entityUid===item.entityUid && (row.entityRevision!==item.entityRevision || item.lifecycle!=='active')));
}

export function modelLocation(detail: ObjectView | null, model: ModelView | null) {
  if (!detail || !model || !detail.item.installationContextId || detail.item.lifecycle !== 'active') return null;
  if(model.bindingWarnings?.some(row=>row.entityUid===detail.item.entityUid))return null;
  const direct = model.bindings.find(row => row.entityUid === detail.item.entityUid && row.entityRevision === detail.item.entityRevision);
  if (direct) return {binding:direct, mode:'direct' as const};
  if(model.bindingWarnings?.some(row=>row.entityUid===detail.item.entityUid)
      || model.bindings.some(row=>row.entityUid===detail.item.entityUid))return null;
  // OntoBase supplies nearest parent first. An incomplete chain cannot prove a host.
  if (detail.ancestors.completeness !== 'complete') return null;
  for (const ancestor of detail.ancestors.path) {
    if(ancestor.object.lifecycle!=='active' || model.bindingWarnings?.some(row=>row.entityUid===ancestor.object.entityUid))return null;
    const binding = model.bindings.find(row => row.entityUid === ancestor.object.entityUid);
    if (binding) return binding.entityRevision===ancestor.object.entityRevision ? {binding, mode:'ancestor' as const} : null;
  }
  return null;
}
