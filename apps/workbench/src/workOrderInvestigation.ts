import type {Investigation,ObjectPhoto,OrderLocation} from './workOrderTypes';

export function investigationComplete(plan:Investigation):boolean {
  return !!(plan.conclusion.trim()&&plan.reviewBasis.trim()&&plan.steps.length&&plan.hypotheses.length
    &&plan.steps.every(step=>step.outcome!=='pending'&&step.result.trim())
    &&plan.hypotheses.every(item=>item.status==='candidate'||item.basis.trim()));
}

export function photoCitation(photo:ObjectPhoto,location:OrderLocation):string {
  return `${location.item.displayName} · ${location.item.entityUid}\n${photo.title} · v${photo.versionNumber??'—'}\n${photo.evidenceRef}\n${photo.contentVersionId}\n${photo.selector?.displayRevision??''}`;
}
