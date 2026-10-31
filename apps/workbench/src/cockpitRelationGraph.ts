import type {CanvasCard,CanvasRelation} from './analysisCanvas.ts';
import type {SourceAnchor,SourceRelationship} from './analysisSources.ts';

type SourceLink=SourceRelationship&{from:CanvasCard;to:CanvasCard};
export type CockpitRelation={id:string;from:CanvasCard;to:CanvasCard;label:string;reason:string;origin:'source'|'candidate'|'manual';anchor:SourceAnchor|null;via:CanvasCard[];steps:SourceLink[]};

/** Only existing readable source paths through off-page objects may be collapsed. */
export function cockpitRelationGraph(cards:CanvasCard[],visible:CanvasCard[],relations:SourceLink[],saved:CanvasRelation[],availability:Record<string,string>,gaps:{evidenceRefId:string;reason:string}[],en=false){
 const informational=new Set(['MODEL_NAME_CANDIDATE_ONLY','MODEL_BOUND_TO_DIFFERENT_OBJECT','MODEL_BINDING_IN_RECYCLE_BIN','MODEL_BINDINGS_TRUNCATED','ALARM_OBJECT_MAPPING_AMBIGUOUS']);
 const blocked=new Set(gaps.filter(gap=>!informational.has(gap.reason)).map(gap=>gap.evidenceRefId)),known=new Set(cards.map(card=>card.id));
 const readable=(card:CanvasCard)=>!card.source||!blocked.has(card.source.id)&&(!availability[card.source.id]||availability[card.source.id]==='available');
 const placed=new Map(visible.filter(card=>readable(card)&&(!card.source||availability[card.source.id]==='available')).map(card=>[card.id,card]));
 const edges=relations.filter(link=>known.has(link.from.id)&&known.has(link.to.id)&&readable(link.from)&&readable(link.to)&&!!link.from.historical===!!link.to.historical);
 const direct:CockpitRelation[]=edges.flatMap(link=>placed.has(link.from.id)&&placed.has(link.to.id)?[{...link,from:placed.get(link.from.id)!,to:placed.get(link.to.id)!,via:[],steps:[link]}]:[]);
 const names={engineering:['工程关系','Engineering relation'],reference:['资料关联','Reference'],hypothesis:['人工假设','Manual hypothesis'],supports:['支持依据','Supporting evidence'],contradicts:['反证','Contradicting evidence']};
 for(const link of saved){const from=placed.get(link.from),to=placed.get(link.to);if(from&&to&&!!from.historical===!!to.historical)direct.push({...link,from,to,label:names[link.kind][en?1:0],anchor:null,via:[],steps:[]});}
 const adjacent=new Map<string,SourceLink[]>();
 for(const link of edges)for(const id of [link.from.id,link.to.id])adjacent.set(id,[...(adjacent.get(id)||[]),link]);
 const center=visible.find(card=>card.kind==='alarm')?.id;
 const starts=[...placed.values()].sort((a,b)=>Number(b.id===center)-Number(a.id===center));
 const candidates:CockpitRelation[]=[],pairs=new Set<string>();
 for(const start of starts){
  const queue=[{node:start,via:[] as CanvasCard[],steps:[] as SourceLink[]}],seen=new Set([start.id]);
  while(queue.length){const current=queue.shift()!;
   for(const edge of adjacent.get(current.node.id)||[]){
    const next=edge.from.id===current.node.id?edge.to:edge.from;if(seen.has(next.id))continue;seen.add(next.id);
    const steps=[...current.steps,edge],target=placed.get(next.id);
    if(target){
     if(!current.via.length)continue;
     const pair=[start.id,target.id].sort().join('\0');if(pairs.has(pair))continue;pairs.add(pair);
     const candidate=steps.some(step=>step.origin==='candidate'),last=steps.at(-1)!;
     candidates.push({id:'path:'+steps.map(step=>step.id).join(':'),from:start,to:target,label:last.label+(en?' · via object':' · 经对象'),reason:steps.map(step=>step.label+'：'+step.reason).join('\n'),origin:candidate?'candidate':'source',anchor:last.to.id===target.id?last.anchor:null,via:current.via,steps});
    }else if(next.kind==='object'&&current.via.length<3)queue.push({node:next,via:[...current.via,next],steps});
   }
  }
 }
 // Retain direct edges; add the fewest indirect paths needed, rather than a clique.
 const parent=new Map<string,string>();
 const root=(id:string):string=>{const next=parent.get(id);return next&&next!==id?root(next):id;};
 const join=(a:string,b:string)=>parent.set(root(a),root(b));
 for(const link of direct)join(link.from.id,link.to.id);
 candidates.sort((a,b)=>Number(a.origin==='candidate')-Number(b.origin==='candidate')||a.steps.length-b.steps.length);
 for(const link of candidates)if(root(link.from.id)!==root(link.to.id)){direct.push(link);join(link.from.id,link.to.id);}
 return direct;
}

/** Paths use diagram coordinates; labels are positioned in an unscaled HTML layer. */
export function cockpitRelationRoute(from:CanvasCard,to:CanvasCard,position?:{x:number;y:number}){
 const ax=from.x+from.width/2,ay=from.y+from.height/2,bx=to.x+to.width/2,by=to.y+to.height/2;
 const upper=ay<by?from:to,lower=ay<by?to:from,verticalGap=lower.y-upper.y-upper.height;
 if(verticalGap>=12){
  const y1=ay<by?from.y+from.height:from.y,y2=ay<by?to.y:to.y+to.height,lane=position?.y??(y1+y2)/2-4,mid=position?.x??(ax+bx)/2;
  return {d:`M${ax},${y1} C${ax},${lane} ${ax},${lane} ${mid},${lane} S${bx},${lane} ${bx},${y2}`,x:mid,y:lane};
 }
 const left=ax<bx?from:to,right=ax<bx?to:from,gap=right.x-left.x-left.width;
 if(gap<85){
  const lane=position?.y??Math.max(12,Math.min(from.y,to.y)-12),mid=position?.x??(ax+bx)/2;
  return {d:`M${ax},${from.y} C${ax},${lane} ${ax},${lane} ${mid},${lane} S${bx},${lane} ${bx},${to.y}`,x:mid,y:lane};
 }
 const x1=ax<bx?from.x+from.width:from.x,x2=ax<bx?to.x:to.x+to.width,x=position?.x??(x1+x2)/2,y=position?.y??(ay+by)/2;
 return {d:`M${x1},${ay} C${x},${ay} ${x},${y} ${x},${y} S${x},${by} ${x2},${by}`,x,y};
}

/** Place natural-sized labels in free diagram space, including compact layouts. */
export function cockpitRelationLabels(links:{id:string;route:{x:number;y:number}}[],cards:CanvasCard[],sizes:Record<string,{width:number;height:number}>,width:number,height:number){
 if(!width||!height)return {};
 const sx=1000/width,sy=700/height,placed:{x:number;y:number;width:number;height:number}[]=[],result:Record<string,{x:number;y:number}>={};
 const intersects=(a:typeof placed[number],b:typeof placed[number],px:number,py:number)=>a.x<b.x+b.width+px&&a.x+a.width+px>b.x&&a.y<b.y+b.height+py&&a.y+a.height+py>b.y;
 for(const link of links){
  const size=sizes[link.id];if(!size)continue;const w=size.width*sx,h=size.height*sy;
  const xs=[link.route.x,6*sx+w/2,1000-6*sx-w/2,...[...cards,...placed].flatMap(card=>[card.x-w/2-4*sx,card.x+card.width+w/2+4*sx])];
  const ys=[link.route.y,6*sy+h/2,700-6*sy-h/2,...[...cards,...placed].flatMap(card=>[card.y-h/2-4*sy,card.y+card.height+h/2+4*sy])];
  const candidates=xs.flatMap(x=>ys.map(y=>({x,y,distance:((x-link.route.x)/sx)**2+((y-link.route.y)/sy)**2}))).sort((a,b)=>a.distance-b.distance);
  const chosen=candidates.find(point=>{const box={x:point.x-w/2,y:point.y-h/2,width:w,height:h};return box.x>=3*sx&&box.y>=3*sy&&box.x+w<=1000-3*sx&&box.y+h<=700-3*sy&&!cards.some(card=>intersects(box,card,2*sx,2*sy))&&!placed.some(other=>intersects(box,other,4*sx,4*sy));})||link.route;
  result[link.id]={x:chosen.x,y:chosen.y};placed.push({x:chosen.x-w/2,y:chosen.y-h/2,width:w,height:h});
 }
 return result;
}
