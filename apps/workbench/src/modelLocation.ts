import type { ModelView, ObjectView } from './types';

export function modelLocation(detail: ObjectView | null, model: ModelView | null) {
  if (!detail || !model || !detail.item.installationContextId || detail.item.lifecycle !== 'active') return null;
  const direct = model.bindings.find(row => row.entityUid === detail.item.entityUid && row.entityRevision === detail.item.entityRevision);
  if (direct) return {binding:direct, mode:'direct' as const};
  // OntoBase supplies nearest parent first. An incomplete chain cannot prove a host.
  if (detail.ancestors.completeness !== 'complete') return null;
  for (const ancestor of detail.ancestors.path) {
    const binding = model.bindings.find(row => row.entityUid === ancestor.object.entityUid && row.entityRevision === ancestor.object.entityRevision);
    if (binding) return {binding, mode:'ancestor' as const};
  }
  return null;
}
