import type {PhotoBox,PhotoSelector} from './workOrderTypes';

export const MAX_PHOTO_ZOOM=16;
export const MIN_PHOTO_ZOOM=.5;

export function clampPhotoZoom(value:number,precision=2){
  return Number(Math.max(MIN_PHOTO_ZOOM,Math.min(MAX_PHOTO_ZOOM,Number.isFinite(value)?value:1)).toFixed(precision));
}

export function photoBaseSize(viewportWidth:number,viewportHeight:number,imageWidth:number,imageHeight:number){
  if(![viewportWidth,viewportHeight,imageWidth,imageHeight].every(v=>Number.isFinite(v)&&v>0))return {width:1,height:1};
  const width=Math.max(1,Math.min(viewportWidth-32,(viewportHeight-32)*imageWidth/imageHeight));
  return {width,height:width*imageHeight/imageWidth};
}

export function photoWheelZoom(current:number,deltaY:number,deltaMode:number,viewportHeight:number){
  const pixels=deltaY*(deltaMode===1?16:deltaMode===2?viewportHeight:1);
  return clampPhotoZoom(current*Math.exp(-pixels*.001),4);
}

export function photoZoomScroll(current:number,next:number,baseWidth:number,baseHeight:number,viewportWidth:number,viewportHeight:number,left:number,top:number,x:number,y:number){
  const axis=(base:number,viewport:number,scroll:number,pointer:number)=>Math.max(0,
    (scroll+pointer-Math.max(16,(viewport-base*current)/2))*next/current+Math.max(16,(viewport-base*next)/2)-pointer);
  return {left:axis(baseWidth,viewportWidth,left,x),top:axis(baseHeight,viewportHeight,top,y)};
}

export function photoFocusZoom(box:PhotoBox|undefined, viewportWidth:number, viewportHeight:number, imageWidth:number, imageHeight:number,focusFraction=.09):number {
  if(!box||![viewportWidth,viewportHeight,imageWidth,imageHeight].every(v=>Number.isFinite(v)&&v>0))return 1;
  const base=photoBaseSize(viewportWidth,viewportHeight,imageWidth,imageHeight);
  // Match OntoBase's photo focus: retain context around the source annotation.
  return clampPhotoZoom(Math.min(viewportWidth*focusFraction/(box.width*base.width),viewportHeight*focusFraction/(box.height*base.height)));
}

export function photoFocusScroll(box:PhotoBox|undefined,width:number,height:number,viewportWidth:number,viewportHeight:number){
  if(!box)return {left:0,top:0};
  return {left:Math.max(0,Math.min(width+32-viewportWidth,16+(box.x+box.width/2)*width-viewportWidth/2)),
    top:Math.max(0,Math.min(height+32-viewportHeight,16+(box.y+box.height/2)*height-viewportHeight/2))};
}

export function photoBoxes(selector:PhotoSelector|null):PhotoBox[] {
  if(!selector)return [];
  if(selector.kind==='image_bbox'&&selector.coordinateSpace==='oriented_display_normalized'){
    const b=selector.bbox;
    return b&&[b.x,b.y,b.width,b.height].every(Number.isFinite)&&b.x>=0&&b.y>=0&&b.width>0&&b.height>0&&b.x+b.width<=1+1e-9&&b.y+b.height<=1+1e-9?[b]:[];
  }
  const region=selector.sphericalRegion;
  if(selector.kind!=='spherical_region'||selector.coordinateSpace!=='spherical_degrees'||!region)return [];
  const {yaw_start_deg:start,yaw_span_deg:span,pitch_min_deg:low,pitch_max_deg:high}=region;
  if(![start,span,low,high].every(Number.isFinite)||start< -180||start>=180||span<=0||span>360||low< -90||high>90||low>=high)return [];
  const x=(start+180)/360,width=span/360,y=(90-high)/180,height=(high-low)/180;
  return x+width<=1?[{x,y,width,height}]:[{x,y,width:1-x,height},{x:0,y,width:x+width-1,height}];
}
