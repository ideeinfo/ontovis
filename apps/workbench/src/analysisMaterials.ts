import type {CanvasSnapshot,Viewport} from './analysisCanvas';
import type {Recommendation,RecommendationRelevance} from './analysisSources';

export const MATERIAL_CATEGORIES=[
  {id:'materials',kind:'document',zh:'相关资料',en:'Related materials',hint:'按关联依据排列图纸、照片和文档',hintEn:'Drawings, photos and documents ordered by recorded relevance'},
  {id:'objects',kind:'object',zh:'工程对象',en:'Engineering objects',hint:'报警对象及相关设备',hintEn:'Alarm objects and related equipment'},
  {id:'device_materials',kind:'document',zh:'当前设备适用资料',en:'Applicable equipment materials',hint:'服务器按已选安装设备解析型号与角色',hintEn:'Resolved by the source for the selected installed device'},
  {id:'project_documents',kind:'document',zh:'本项目文档库',en:'Project document library',hint:'本项目有权读取的PDF与照片',hintEn:'Authorized project PDFs and photos'},
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
export function relatedMaterialSection(_objectScope:string|undefined){
  return 'materials';
}
const relevanceLabels:Record<RecommendationRelevance,[string,string]>={field_record:['本设备现场','This equipment'],same_event:['本次事件','Current event'],selected_object:['当前对象','Selected object'],object_association:['本对象关联','Object link'],shared_definition:['共享定义','Shared definition'],binding:['模型绑定','Recorded binding'],fault_evidence:['故障码证据','Fault-code evidence'],simulation_mapping:['模拟映射','Simulation mapping'],same_object_fault:['同对象同故障','Same object and fault'],descendant:['下级对象','Registered descendants'],shared_photos:['共享照片','Shared photos'],model_applicable:['型号适用','Applicable model'],same_fault:['同故障码','Same fault code'],historical_binding:['历史绑定','Historical binding'],simulation_rule:['演练参照','Rehearsal reference'],name_candidate:['名称候选','Name candidate'],catalogue_search:['目录检索','Catalogue search']};
export function recommendationRelevanceLabel(item:Recommendation,en:boolean){
  const basis=item.relevance||item.matchType;
  return basis&&relevanceLabels[basis]?.[en?1:0]||'';
}
export function mergeRecommendations(previous:Recommendation[],incoming:Recommendation[]){
  const result:Recommendation[]=[],positions=new Map<string,number>();
  for(const item of [...previous,...incoming]){
    const identity=item.assetKey||item.key,index=positions.get(identity);
    if(index===undefined){positions.set(identity,result.length);result.push(item);continue;}
    const old=result[index],usable=!item.availability||item.availability==='available',oldUsable=!old.availability||old.availability==='available';
    if(usable&&!oldUsable||usable===oldUsable&&(item.relevancePriority??90)<(old.relevancePriority??90))result[index]=item;
  }
  return result.sort((a,b)=>(a.relevancePriority??90)-(b.relevancePriority??90));
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
