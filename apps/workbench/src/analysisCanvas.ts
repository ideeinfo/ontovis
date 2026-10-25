// Q-20 page-contract logic. Used by the MagicPath prototype; not a live session API.
export const CARD_KINDS = ['object','drawing','document','photo','model3d','trend','alarm','work_order','analysis'] as const;
export type CardKind = typeof CARD_KINDS[number];
export type Availability = 'ready'|'restricted'|'missing'|'unavailable'|'unconnected'|'stale';
export type RelationKind = 'engineering'|'reference'|'hypothesis'|'supports'|'contradicts';
export type SessionStatus = 'analyzing'|'awaiting_field_check'|'awaiting_expert_review'|'concluded'|'archived';
export type ProjectScope = {ontobaseConnectionId:string;projectCode:string};
export type SourceRef = ProjectScope & {system:'ontobase'|'ontovis';id:string;revision:string;locator?:string};
export type CanvasCard = {id:string;kind:CardKind;title:string;x:number;y:number;width:number;height:number;pinned:boolean;source?:SourceRef;note?:string};
export type CanvasRelation = {id:string;from:string;to:string;kind:RelationKind;origin:'source'|'manual';reason:string};
export type Viewport = {x:number;y:number;zoom:number};
export type AnalysisContext = {objectIds:string[];eventId?:string;workOrderId?:string;timeFrom:string;timeTo:string;timezone:'Asia/Shanghai'|'UTC'};
export type CanvasSnapshot = ProjectScope & {schemaVersion:1;title:string;status:SessionStatus;context:AnalysisContext;cards:CanvasCard[];relations:CanvasRelation[];viewport:Viewport};
export const MIN_ZOOM=.25;
export const MAX_ZOOM=1.5;
const finite=(v:unknown,min:number,max:number):v is number=>typeof v==='number'&&Number.isFinite(v)&&v>=min&&v<=max;
const bounded=(v:unknown,max:number):v is string=>typeof v==='string'&&v.trim().length>0&&v.length<=max;
const record=(v:unknown):v is Record<string,unknown>=>v!==null&&typeof v==='object'&&!Array.isArray(v);
const only=(v:Record<string,unknown>,keys:string[])=>Object.keys(v).every(k=>keys.includes(k));
const utcTime=(v:unknown):v is string=>typeof v==='string'&&/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{3})?Z$/.test(v)&&Number.isFinite(Date.parse(v))&&new Date(v).toISOString().replace('.000Z','Z')===v.replace('.000Z','Z');
export function validateSnapshot(value:unknown,scope:ProjectScope):string[]{
  const errors:string[]=[];
  if(!record(value))return ['画布数据无效'];
  if(!only(value,['schemaVersion','ontobaseConnectionId','projectCode','title','status','context','cards','relations','viewport']))errors.push('画布包含未支持字段');
  if(value.schemaVersion!==1||value.projectCode!==scope.projectCode||value.ontobaseConnectionId!==scope.ontobaseConnectionId||!bounded(scope.projectCode,120)||!bounded(scope.ontobaseConnectionId,120))errors.push('画布版本或项目不匹配');
  if(!bounded(value.title,120))errors.push('会话名称需为 1–120 字');
  if(!['analyzing','awaiting_field_check','awaiting_expert_review','concluded','archived'].includes(String(value.status)))errors.push('会话状态无效');
  const context=value.context;
  if(!record(context)||!only(context,['objectIds','eventId','workOrderId','timeFrom','timeTo','timezone'])||!Array.isArray(context.objectIds)||context.objectIds.length>20||context.objectIds.some(id=>!bounded(id,200))||new Set(context.objectIds).size!==context.objectIds.length||(context.eventId!==undefined&&!bounded(context.eventId,200))||(context.workOrderId!==undefined&&!bounded(context.workOrderId,200))||!['Asia/Shanghai','UTC'].includes(String(context.timezone)))errors.push('分析上下文无效');
  if(!record(context)||!utcTime(context.timeFrom)||!utcTime(context.timeTo)||Date.parse(context.timeFrom)>=Date.parse(context.timeTo))errors.push('分析时间范围无效');
  if(!record(value.viewport)||!only(value.viewport,['x','y','zoom'])||!finite(value.viewport.x,-50000,50000)||!finite(value.viewport.y,-50000,50000)||!finite(value.viewport.zoom,MIN_ZOOM,MAX_ZOOM))errors.push('视图位置无效');
  if(!Array.isArray(value.cards)||value.cards.length>50)return [...errors,'单个会话最多 50 张卡片'];
  const ids=new Set<string>();
  for(const c of value.cards){
    if(!record(c)){errors.push('卡片数据无效');continue;}
    if(!only(c,['id','kind','title','x','y','width','height','pinned','source','note']))errors.push('卡片不允许保存源内容或扩展字段');
    if(!bounded(c.id,100)||ids.has(c.id))errors.push('卡片标识缺失或重复');else ids.add(c.id);
    if(!CARD_KINDS.includes(c.kind as CardKind)||!bounded(c.title,120))errors.push('卡片类型或名称无效');
    if(!finite(c.x,-20000,20000)||!finite(c.y,-20000,20000)||!finite(c.width,240,720)||!finite(c.height,176,960)||typeof c.pinned!=='boolean')errors.push('卡片布局无效');
    if(c.note!==undefined&&(c.kind!=='analysis'||typeof c.note!=='string'||c.note.length>4000))errors.push('仅分析卡片可保存不超过 4000 字的人工笔记');
    if(c.kind==='analysis'){if(c.source!==undefined)errors.push('人工分析不能冒充来源事实');}
    else{
      const s=c.source;
      if(!record(s)||!only(s,['system','ontobaseConnectionId','projectCode','id','revision','locator'])||!['ontobase','ontovis'].includes(String(s.system))||s.projectCode!==scope.projectCode||s.ontobaseConnectionId!==scope.ontobaseConnectionId||!bounded(s.id,200)||!bounded(s.revision,120)||(s.locator!==undefined&&!bounded(s.locator,200)))errors.push('资料引用必须属于本项目并指向明确版本');
    }
  }
  if(!Array.isArray(value.relations)||value.relations.length>100)return [...errors,'单个会话最多 100 条关系'];
  const links=new Set<string>();
  const pairs=new Set<string>();
  for(const r of value.relations){
    if(!record(r)){errors.push('关系数据无效');continue;}
    if(!only(r,['id','from','to','kind','origin','reason'])||!bounded(r.id,100)||links.has(String(r.id)))errors.push('关系标识无效');else links.add(String(r.id));
    if(!ids.has(String(r.from))||!ids.has(String(r.to))||r.from===r.to)errors.push('关系端点无效');
    if(!['engineering','reference','hypothesis','supports','contradicts'].includes(String(r.kind))||!['source','manual'].includes(String(r.origin)))errors.push('关系类型无效');
    if(r.kind==='engineering'&&r.origin!=='source')errors.push('人工关系不能写入工程事实');
    if(typeof r.reason!=='string'||r.reason.length>1000||(r.origin==='manual'&&!r.reason.trim()))errors.push('人工关系需要不超过 1000 字的依据');
    const pair=JSON.stringify([r.from,r.to,r.kind]);
    if(pairs.has(pair))errors.push('关系重复');else pairs.add(pair);
  }
  return [...new Set(errors)];
}
export function moveCard(snapshot:CanvasSnapshot,id:string,x:number,y:number):CanvasSnapshot{
  if(!finite(x,-20000,20000)||!finite(y,-20000,20000))return snapshot;
  const card=snapshot.cards.find(c=>c.id===id);
  if(!card||card.pinned||(card.x===x&&card.y===y))return snapshot;
  return {...snapshot,cards:snapshot.cards.map(c=>c.id===id?{...c,x,y}:c)};
}
export function removeCard(snapshot:CanvasSnapshot,id:string):CanvasSnapshot{
  return {...snapshot,cards:snapshot.cards.filter(c=>c.id!==id),relations:snapshot.relations.filter(r=>r.from!==id&&r.to!==id)};
}
export function addManualRelation(snapshot:CanvasSnapshot,relation:CanvasRelation):CanvasSnapshot{
  if(relation.origin!=='manual'||relation.kind==='engineering')throw new Error('人工编辑不能创建工程事实');
  const next={...snapshot,relations:[...snapshot.relations,relation]};
  const errors=validateSnapshot(next,snapshot);
  if(errors.length)throw new Error(errors[0]);
  return next;
}
const overlap=(a:CanvasCard,b:CanvasCard)=>a.x<b.x+b.width+24&&a.x+a.width+24>b.x&&a.y<b.y+b.height+24&&a.y+a.height+24>b.y;
export function arrangeCards(snapshot:CanvasSnapshot):CanvasSnapshot{
  const placed=snapshot.cards.filter(c=>c.pinned);
  const moved=new Map<string,CanvasCard>();
  const stepX=Math.max(300,...snapshot.cards.map(c=>c.width))+40;
  const stepY=Math.max(200,...snapshot.cards.map(c=>c.height))+40;
  for(const card of snapshot.cards.filter(c=>!c.pinned)){
    let found:CanvasCard|undefined;
    for(let row=0;row<120&&!found;row++)for(let column=0;column<3;column++){
      const candidate={...card,x:32+column*stepX,y:40+row*stepY};
      if(!placed.some(c=>overlap(candidate,c))){found=candidate;break;}
    }
    // Dense pinned layouts keep the original position rather than exceeding bounds.
    if(found&&found.y<=20000){placed.push(found);moved.set(card.id,found);}
  }
  return {...snapshot,cards:snapshot.cards.map(c=>moved.get(c.id)??c)};
}
export function fitViewport(cards:CanvasCard[],width:number,height:number):Viewport{
  if(!cards.length||!finite(width,1,100000)||!finite(height,1,100000))return {x:24,y:24,zoom:1};
  const left=Math.min(...cards.map(c=>c.x)),top=Math.min(...cards.map(c=>c.y));
  const right=Math.max(...cards.map(c=>c.x+c.width)),bottom=Math.max(...cards.map(c=>c.y+c.height));
  const zoom=Math.max(MIN_ZOOM,Math.min(1,(width-64)/(right-left),(height-64)/(bottom-top)));
  return {x:width/2-(left+right)*zoom/2,y:height/2-(top+bottom)*zoom/2,zoom};
}
export function zoomAt(view:Viewport,nextZoom:number,screenX:number,screenY:number):Viewport{
  if(!Number.isFinite(nextZoom)||!Number.isFinite(screenX)||!Number.isFinite(screenY))return view;
  const zoom=Math.max(MIN_ZOOM,Math.min(MAX_ZOOM,nextZoom));
  return {x:Math.max(-50000,Math.min(50000,screenX-(screenX-view.x)*zoom/view.zoom)),y:Math.max(-50000,Math.min(50000,screenY-(screenY-view.y)*zoom/view.zoom)),zoom};
}
export function visibleSource(card:CanvasCard,availability:Availability):{title:string;source?:SourceRef}{
  return availability==='restricted'?{title:'资料访问已撤销'}:{title:card.title,source:card.source};
}
