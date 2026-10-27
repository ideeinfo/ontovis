import type {CanvasSnapshot,Viewport} from './analysisCanvas';
import type {Recommendation} from './analysisSources';

export const MATERIAL_CATEGORIES=[
  {id:'objects',kind:'object',zh:'工程对象',en:'Engineering objects',hint:'报警对象及相关设备',hintEn:'Alarm objects and related equipment'},
  {id:'drawings',kind:'drawing',zh:'图纸',en:'Drawings',hint:'所选对象的关联图纸',hintEn:'Drawings linked to the selected object'},
  {id:'documents',kind:'document',zh:'文档',en:'Documents',hint:'故障代码手册及知识证据',hintEn:'Fault manuals and knowledge evidence'},
  {id:'photos',kind:'photo',zh:'照片',en:'Photos',hint:'对象照片与区域定位',hintEn:'Object photos and located regions'},
  {id:'models',kind:'model3d',zh:'三维模型',en:'3D models',hint:'模型构件与空间参照',hintEn:'Model components and spatial references'},
  {id:'trends',kind:'trend',zh:'趋势',en:'Trends',hint:'当前报警的信号与时间窗',hintEn:'Signals and time window of the current alarm'},
  {id:'alarms',kind:'alarm',zh:'故障报警',en:'Fault alarms',hint:'本项目的报警事件',hintEn:'Alarm events in this project'},
  {id:'orders',kind:'work_order',zh:'历史工单',en:'Work orders',hint:'同故障码的处理记录',hintEn:'Work orders with the same fault code'},
  {id:'analysis',kind:'analysis',zh:'分析笔记',en:'Analysis note',hint:'观察、假设与排查记录',hintEn:'Observations, hypotheses and checks'},
] as const;
export function materialCategories(query:string){
  const needle=query.trim().toLocaleLowerCase();
  return MATERIAL_CATEGORIES.filter(row=>[row.zh,row.en,row.hint,row.hintEn].join(' ').toLocaleLowerCase().includes(needle));
}
export function materialPosition(view:Viewport,point:{x:number;y:number}){
  return {x:Math.max(-20000,Math.min(20000,Math.round((point.x-view.x)/view.zoom))),
    y:Math.max(-20000,Math.min(20000,Math.round((point.y-view.y)/view.zoom)))};
}
export function withPrimaryAlarm(snapshot:CanvasSnapshot,item:Recommendation):CanvasSnapshot{
  const dataset=item.preview?.dataset,eventId=item.selector.eventId;
  if(item.kind!=='alarm'||snapshot.context.datasetId||snapshot.context.eventId||!dataset?.branch||typeof eventId!=='string')return snapshot;
  return {...snapshot,context:{...snapshot.context,eventId,faultCode:dataset.faultCode,sourceConnectionId:dataset.sourceConnectionId,
    branch:dataset.branch,datasetId:dataset.datasetId,datasetRevision:dataset.datasetRevision,timeFrom:dataset.timeFrom,timeTo:dataset.timeTo}};
}
