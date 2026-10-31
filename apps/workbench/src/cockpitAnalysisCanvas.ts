import type {CanvasCard,Viewport} from './analysisCanvas';

export type CockpitCardPosition={x:number;y:number};
export type CockpitCardPositions=Record<string,CockpitCardPosition>;
export type CockpitCanvasSize={width:number;height:number};
export const COCKPIT_CANVAS_MIN_ZOOM=.1,COCKPIT_CANVAS_MAX_ZOOM=2;
const finite=(...values:number[])=>values.every(Number.isFinite);

/** One complete display projection; source views and saved coordinates remain untouched. */
export function cockpitAnalysisLayout(cards:CanvasCard[],positions:CockpitCardPositions={}){
 const center=cards.find(card=>card.kind==='alarm'&&!card.historical)||cards.find(card=>card.kind==='alarm')||cards[0];
 const priority=['drawing','model3d','document','photo','trend','object','analysis','work_order','alarm'];
 const ranked=cards.filter(card=>card.id!==center?.id).map((card,index)=>({card,index})).sort((a,b)=>priority.indexOf(a.card.kind)-priority.indexOf(b.card.kind)||a.index-b.index).map(item=>item.card);
 const kinds=new Set<string>(),first:CanvasCard[]=[],rest:CanvasCard[]=[];
 for(const card of ranked){if(kinds.has(card.kind))rest.push(card);else{first.push(card);kinds.add(card.kind);}}
 let columns=cards.length<=3?Math.max(1,cards.length):Math.min(9,Math.ceil(Math.sqrt(cards.length*1.25)));
 if(cards.length>3&&columns%2===0)columns++;
 const rows=Math.max(1,Math.ceil(cards.length/columns)),centerSlot=Math.floor(rows/2)*columns+Math.floor(columns/2);
 const size={width:columns*432-112+64,height:rows*344-80+64};
 const placed:CanvasCard[]=[];let slot=0;
 for(const card of [...first,...rest]){
  if(slot===centerSlot)slot++;
  const value={...card,x:32+(slot%columns)*432,y:32+Math.floor(slot/columns)*344,width:320,height:264};slot++;
  placed.push({...value,...cockpitCardPosition(value,positions[card.id]??value,size)});
 }
 if(center)placed.push({...center,x:32+(centerSlot%columns)*432,y:32+Math.floor(centerSlot/columns)*344,width:320,height:264});
 return {...size,cards:placed,center,total:cards.length};
}
export function cockpitCardPosition(card:Pick<CanvasCard,'x'|'y'|'width'|'height'>,position:CockpitCardPosition,size:CockpitCanvasSize):CockpitCardPosition{
 return {x:Math.max(0,Math.min(size.width-card.width,Number.isFinite(position.x)?position.x:card.x)),y:Math.max(0,Math.min(size.height-card.height,Number.isFinite(position.y)?position.y:card.y))};
}
/** The world rectangle includes canvas zoom, interface density and browser scaling once. */
export function cockpitCardMove(card:Pick<CanvasCard,'x'|'y'|'width'|'height'>,delta:CockpitCardPosition,rendered:CockpitCanvasSize,size:CockpitCanvasSize):CockpitCardPosition{
 if(!finite(delta.x,delta.y,rendered.width,rendered.height)||rendered.width<=0||rendered.height<=0)return cockpitCardPosition(card,card,size);
 return cockpitCardPosition(card,{x:card.x+delta.x*size.width/rendered.width,y:card.y+delta.y*size.height/rendered.height},size);
}
export function cockpitCanvasFit(cards:CanvasCard[],size:CockpitCanvasSize):Viewport{
 if(!cards.length||!finite(size.width,size.height)||size.width<=0||size.height<=0)return {x:24,y:24,zoom:1};
 const left=Math.min(...cards.map(card=>card.x)),top=Math.min(...cards.map(card=>card.y)),right=Math.max(...cards.map(card=>card.x+card.width)),bottom=Math.max(...cards.map(card=>card.y+card.height));
 const zoom=Math.max(COCKPIT_CANVAS_MIN_ZOOM,Math.min(1,(size.width-48)/Math.max(1,right-left),(size.height-48)/Math.max(1,bottom-top)));
 return {x:size.width/2-(left+right)*zoom/2,y:size.height/2-(top+bottom)*zoom/2,zoom};
}
export function cockpitCanvasZoom(view:Viewport,nextZoom:number,point:CockpitCardPosition):Viewport{
 if(!finite(nextZoom,point.x,point.y,view.zoom)||view.zoom<=0)return view;
 const zoom=Math.max(COCKPIT_CANVAS_MIN_ZOOM,Math.min(COCKPIT_CANVAS_MAX_ZOOM,nextZoom));
 return {x:point.x-(point.x-view.x)*zoom/view.zoom,y:point.y-(point.y-view.y)*zoom/view.zoom,zoom};
}
export function cockpitCanvasPan(view:Viewport,delta:CockpitCardPosition):Viewport{
 if(!finite(delta.x,delta.y))return view;
 return {...view,x:Math.max(-50000,Math.min(50000,view.x+delta.x)),y:Math.max(-50000,Math.min(50000,view.y+delta.y))};
}
export function cockpitCanvasFocus(view:Viewport,card:CanvasCard,size:CockpitCanvasSize):Viewport{
 if(!finite(size.width,size.height)||size.width<=0||size.height<=0)return view;
 const fit=Math.min(1,(size.width-48)/card.width,(size.height-48)/card.height),zoom=Math.max(COCKPIT_CANVAS_MIN_ZOOM,Math.min(fit,Math.max(view.zoom,.85)));
 return {x:size.width/2-(card.x+card.width/2)*zoom,y:size.height/2-(card.y+card.height/2)*zoom,zoom};
}
export function cockpitCanvasWheel(insideMedia:boolean,modified:boolean,hand:boolean){return !insideMedia||modified||hand;}
