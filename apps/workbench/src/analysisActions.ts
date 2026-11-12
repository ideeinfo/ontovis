import {addManualRelation,arrangeCards,resizeCard,validateSnapshot,type CanvasRelation,type CanvasSnapshot,type ProjectScope,type ResizeHandle} from './analysisCanvas.ts';

// The UI and later conversation client use these same bounded local operations.
// Saving and source registration stay explicit server requests, never effects of Q&A.
export type CanvasAction=
 | {kind:'append-note';cardId:string;text:string}
 | {kind:'add-relation';relation:CanvasRelation}
 | {kind:'arrange'}
 | {kind:'resize-card';cardId:string;handle:ResizeHandle;dx:number;dy:number;lockRatio:boolean}
 | {kind:'set-window';from:string;to:string};
export type ActionContext=ProjectScope&{analysisSessionId:string;analysisRevision:number;selectedCardIds:string[];eventId?:string;workOrderId?:string};
export type CanvasIntent=
 | {kind:'query-history';faultCode:string;sourceConnectionId:string}
 | {kind:'import-history';analysisSessionId:string;analysisRevision:number}
 | {kind:'add-source';recommendationKey:string}
 | {kind:'focus-card';cardId:string}
 | {kind:'compare-trends';cardIds:string[]}
 | {kind:'save-and-link';orderId:string};
export function applyCanvasAction(snapshot:CanvasSnapshot,action:CanvasAction,context:ProjectScope):CanvasSnapshot{
  if(snapshot.projectCode!==context.projectCode||snapshot.ontobaseConnectionId!==context.ontobaseConnectionId)throw new Error('分析范围已变化');
  let next=snapshot;
  if(action.kind==='append-note'){
    const card=snapshot.cards.find(c=>c.id===action.cardId);
    if(!card||card.kind!=='analysis'||card.historical)throw new Error('请选择本次分析记录');
    next={...snapshot,cards:snapshot.cards.map(c=>c===card?{...c,note:(c.note||'')+action.text}:c)};
  }else if(action.kind==='add-relation')next=addManualRelation(snapshot,action.relation);
  else if(action.kind==='arrange')next=arrangeCards(snapshot);
  else if(action.kind==='resize-card')next=resizeCard(snapshot,action.cardId,action.handle,action.dx,action.dy,action.lockRatio);
  else if(action.kind==='set-window')next={...snapshot,context:{...snapshot.context,timeFrom:action.from,timeTo:action.to}};
  else throw new Error('不支持的画布操作');
  const errors=validateSnapshot(next,context);if(errors.length)throw new Error(errors[0]);return next;
}
export function conversationContext(snapshot:CanvasSnapshot,sessionId:string,revision:number,selectedCardIds:string[]){
  return {ontobaseConnectionId:snapshot.ontobaseConnectionId,projectCode:snapshot.projectCode,analysisSessionId:sessionId,
    analysisRevision:revision,eventId:snapshot.context.eventId,workOrderId:snapshot.context.workOrderId,
    timeFrom:snapshot.context.timeFrom,timeTo:snapshot.context.timeTo,timezone:snapshot.context.timezone,
    selectedCardIds:selectedCardIds.filter(id=>snapshot.cards.some(card=>card.id===id)),
    sources:snapshot.cards.filter(card=>card.source).map(card=>({cardId:card.id,kind:card.kind,source:card.source,historical:!!card.historical}))};
}
