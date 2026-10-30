import {validateSnapshot,type CanvasCard,type CanvasSnapshot,type ProjectScope} from './analysisCanvas.ts';
import type {AnalysisEntry} from './analysisSources';
import type {DraftApi} from './AnalysisWorkspace';
import type {DraftReceipt} from './analysisDraftState';
import {AssistantApi,type AssistantRun} from './assistantApi.ts';
import {noteSections,readNote} from './analysisNotes.ts';

const ROOT='/api/workbench/analysis-sessions';
export type CockpitAnalysisDetail=DraftReceipt&{snapshot:CanvasSnapshot};
export type CockpitAnalysisCandidate={analysisSessionId:string;analysisRevision:number;title:string;reason:string;eventId?:string};
export type CockpitFault={datasetId:string;datasetRevision:string;faultCode:string;title:string};
type FaultEntry={datasetId:string;datasetRevision:string}|{orderId:string};

export function cockpitFaultEntry(entry:AnalysisEntry|null):FaultEntry|null{
 return entry&&'datasetId'in entry?{datasetId:entry.datasetId,datasetRevision:entry.datasetRevision}:entry&&'orderId'in entry?{orderId:entry.orderId}:null;
}
function checkedDetail(value:CockpitAnalysisDetail,scope:ProjectScope|null,id:string,revision:number){
 if(!scope||value.analysisSessionId!==id||value.analysisRevision!==revision||validateSnapshot(value.snapshot,scope).length)throw new Error('ANALYSIS_CHANGED');
 return value;
}
export async function cockpitAnalysisDetail(api:DraftApi,item:CockpitAnalysisCandidate,signal:AbortSignal,faultCode?:string){
 const value=checkedDetail(await api.request<CockpitAnalysisDetail>(ROOT+'/detail',{analysisSessionId:item.analysisSessionId,analysisRevision:item.analysisRevision},signal),api.project,item.analysisSessionId,item.analysisRevision);
 if(!value.snapshot.context.faultCode||faultCode&&value.snapshot.context.faultCode!==faultCode)throw new Error('ANALYSIS_CONTEXT_MISMATCH');
 return value;
}
export async function cockpitAnalysisIndex(api:DraftApi,entry:AnalysisEntry|null,signal:AbortSignal){
 let fault=cockpitFaultEntry(entry),initial:CockpitAnalysisDetail|null=null;
 if(entry&&'analysisSessionId'in entry){
  initial=await cockpitAnalysisDetail(api,{...entry,title:'',reason:''},signal);
  const context=initial.snapshot.context;
  fault=context.datasetId&&context.datasetRevision?{datasetId:context.datasetId,datasetRevision:context.datasetRevision}:null;
 }
 if(!fault)return {entry:null,items:[] as CockpitAnalysisCandidate[],initial:null};
 const value=await api.request<{items:CockpitAnalysisCandidate[]}>(ROOT+'/history-candidates',{entry:fault},signal);
 const items=value.items.filter((item,index,all)=>all.findIndex(other=>other.analysisSessionId===item.analysisSessionId)===index);
 if(initial){
  const chosen=items.find(item=>item.analysisSessionId===initial!.analysisSessionId&&item.analysisRevision===initial!.analysisRevision);
  // An explicit fixed revision stays fixed even when its current head has advanced.
  const pinned=chosen||{analysisSessionId:initial.analysisSessionId,analysisRevision:initial.analysisRevision,title:initial.snapshot.title,reason:'固定分析修订',eventId:initial.snapshot.context.eventId};
  return {entry:fault,items:[pinned,...items.filter(item=>item.analysisSessionId!==pinned.analysisSessionId)],initial};
 }
 return {entry:fault,items,initial};
}

/** Display positions never replace the saved canvas, including its internal media views. */
export function cockpitAnalysisPage(cards:CanvasCard[],requestedPage=0,capacity:3|5=5){
 const center=cards.find(card=>card.kind==='alarm'&&!card.historical)||cards.find(card=>card.kind==='alarm')||cards[0];
 const priority=['drawing','model3d','document','photo','trend','object','analysis','work_order','alarm'];
 const ranked=cards.filter(card=>card.id!==center?.id).map((card,index)=>({card,index})).sort((a,b)=>priority.indexOf(a.card.kind)-priority.indexOf(b.card.kind)||a.index-b.index).map(item=>item.card);
 const kinds=new Set<string>(),first:CanvasCard[]=[],rest:CanvasCard[]=[];
 for(const card of ranked){if(kinds.has(card.kind))rest.push(card);else{first.push(card);kinds.add(card.kind);}}
 const others=[...first,...rest];
 const count=Math.max(1,Math.ceil(others.length/capacity)),page=Math.max(0,Math.min(count-1,requestedPage));
 const slots=capacity===3?[[18,28,304,286],[678,28,304,286],[678,382,304,286]]:[[18,18,292,274],[354,18,292,274],[690,18,292,274],[18,402,292,280],[690,402,292,280]];
 const visible=others.slice(page*capacity,(page+1)*capacity).map((card,i)=>({...card,x:slots[i][0],y:slots[i][1],width:slots[i][2],height:slots[i][3]}));
 if(center)visible.push({...center,x:354,y:capacity===3?382:356,width:292,height:capacity===3?286:250});
 return {cards:visible,page,count,total:cards.length,others,center};
}
export function cockpitAnalysisPageFor(cards:CanvasCard[],id:string,capacity:3|5=5){
 const layout=cockpitAnalysisPage(cards,0,capacity);if(layout.center?.id===id)return 0;
 const index=layout.others.findIndex(card=>card.id===id);return index<0?0:Math.floor(index/capacity);
}
export function cockpitNoteRecords(cards:CanvasCard[],en=false){
 const sections={观察:'observations',原因假设:'hypotheses',检查步骤:'checks',检查结果:'results',反证与缺口:'gaps',下一步:'nextSteps'};
 return cards.filter(card=>card.kind==='analysis'&&card.note?.trim()).flatMap(card=>{
  if(!noteSections.some(([name])=>card.note!.split('\n').some(line=>line.startsWith(name+'：'))))return [{id:card.id,title:card.title,rows:[{text:card.note!,refs:[] as string[]}]}];
  const fields=readNote(card.note!);
  return noteSections.flatMap(([name,english])=>fields[name]?[{id:sections[name],title:en?english:name,rows:[{text:fields[name],refs:[] as string[]}]}]:[]);
 });
}
export function cockpitAnalysisHistorical(detail:CockpitAnalysisDetail,entry:FaultEntry|null){
 return !!entry&&'datasetId'in entry&&(detail.snapshot.context.datasetId!==entry.datasetId||detail.snapshot.context.datasetRevision!==entry.datasetRevision);
}
export function cockpitSavedTurns(runs:AssistantRun[],receipt:DraftReceipt){
 return runs.filter(run=>run.analysisSessionId===receipt.analysisSessionId&&run.analysisRevision===receipt.analysisRevision);
}
export async function cockpitAnalysisTurns(api:DraftApi,receipt:DraftReceipt,signal:AbortSignal){
 const service=new AssistantApi(api),list=await service.conversations(receipt.analysisSessionId,receipt.analysisRevision,signal);
 if(!list.items.length)return [];
 const value=await service.conversation(list.items[0].conversationId,undefined,signal);
 return cockpitSavedTurns(value.items,receipt);
}
