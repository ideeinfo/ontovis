import type {PhotoBox,PhotoSelector} from './workOrderTypes';

export const MAX_PHOTO_ZOOM=16;

export function photoFocusZoom(box:PhotoBox|undefined, viewportWidth:number, viewportHeight:number, imageWidth:number, imageHeight:number):number {
  if(!box||![viewportWidth,viewportHeight,imageWidth,imageHeight].every(v=>Number.isFinite(v)&&v>0))return 1;
  const baseHeight=viewportWidth*imageHeight/imageWidth;
  const zoom=Math.min(.72/box.width,viewportHeight*.6/(box.height*baseHeight));
  return Math.max(1,Math.min(MAX_PHOTO_ZOOM,zoom,48000/Math.max(viewportWidth,baseHeight)));
}

export function photoFocusScroll(box:PhotoBox|undefined,width:number,height:number,viewportWidth:number,viewportHeight:number){
  if(!box)return {left:0,top:0};
  return {left:Math.max(0,Math.min(width-viewportWidth,(box.x+box.width/2)*width-viewportWidth/2)),
    top:Math.max(0,Math.min(height-viewportHeight,(box.y+box.height/2)*height-viewportHeight/2))};
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
