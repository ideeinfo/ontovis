import type {CanvasCard,CanvasSnapshot,Viewport} from './analysisCanvas';

export type CockpitCardPosition={x:number;y:number};
export type CockpitCardPositions=Record<string,CockpitCardPosition>;
export type CockpitCanvasSize={width:number;height:number};
export type CockpitCanvasBounds=CockpitCanvasSize&CockpitCardPosition;
export const COCKPIT_CANVAS_MIN_ZOOM=.1,COCKPIT_CANVAS_MAX_ZOOM=2;
const finite=(...values:number[])=>values.every(Number.isFinite);

export function cockpitAnalysisLayout(snapshot?:Pick<CanvasSnapshot,'cards'|'frames'>,positions:CockpitCardPositions={}){
 const frames=snapshot?.frames??[];
 const cards=(snapshot?.cards??[]).map(card=>{
  const position=positions[card.id];
  return position&&finite(position.x,position.y)?{...card,x:position.x,y:position.y}:card;
 });
 const items=[...frames,...cards];
 if(!items.length)return {frames,cards,bounds:null};
 const x=Math.min(...items.map(item=>item.x)),y=Math.min(...items.map(item=>item.y));
 const width=Math.max(...items.map(item=>item.x+item.width))-x;
 const height=Math.max(...items.map(item=>item.y+item.height))-y;
 return {frames,cards,bounds:{x,y,width,height}};
}
export function cockpitCardOutsideFrame(card:CockpitCanvasBounds,frame:CockpitCanvasBounds){
 return card.x<frame.x||card.y<frame.y||card.x+card.width>frame.x+frame.width||card.y+card.height>frame.y+frame.height;
}
/** The rendered card rectangle includes canvas zoom and interface scaling. */
export function cockpitCardMove(card:CockpitCanvasBounds,delta:CockpitCardPosition,rendered:CockpitCanvasSize):CockpitCardPosition{
 if(!finite(delta.x,delta.y,rendered.width,rendered.height)||rendered.width<=0||rendered.height<=0)return {x:card.x,y:card.y};
 return {x:card.x+delta.x*card.width/rendered.width,y:card.y+delta.y*card.height/rendered.height};
}
export function cockpitCanvasFit(bounds:CockpitCanvasBounds|null,size:CockpitCanvasSize):Viewport{
 if(!bounds||!finite(size.width,size.height)||size.width<=0||size.height<=0)return {x:24,y:24,zoom:1};
 const zoom=Math.min(1,Math.max(1,size.width-48)/bounds.width,Math.max(1,size.height-48)/bounds.height);
 return {x:size.width/2-(bounds.x+bounds.width/2)*zoom,y:size.height/2-(bounds.y+bounds.height/2)*zoom,zoom};
}
export function cockpitCanvasZoom(view:Viewport,nextZoom:number,point:CockpitCardPosition,minZoom=COCKPIT_CANVAS_MIN_ZOOM):Viewport{
 if(!finite(nextZoom,point.x,point.y,view.zoom)||view.zoom<=0)return view;
 const zoom=Math.max(minZoom,Math.min(COCKPIT_CANVAS_MAX_ZOOM,nextZoom));
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
export function cockpitCanvasReveal(view:Viewport,card:CanvasCard,size:CockpitCanvasSize):Viewport{
 const left=view.x+card.x*view.zoom,top=view.y+card.y*view.zoom;
 return left>=4&&top>=4&&left+card.width*view.zoom<=size.width-4&&top+card.height*view.zoom<=size.height-4?view:cockpitCanvasFocus(view,card,size);
}
export function cockpitCanvasWheel(insideMedia:boolean,modified:boolean,hand:boolean){return !insideMedia||modified||hand;}
