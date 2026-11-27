export type AssistantWindowBox={x:number;y:number;width:number;height:number};
export type AssistantWindowHandle='move'|'left'|'right';

const minWidth=300,minHeight=340;
const clamp=(value:number,low:number,high:number)=>Math.min(Math.max(value,low),high);
const arrows:Partial<Record<string,[number,number]>>={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]};

export function assistantWindowViewport(margin=0):AssistantWindowBox{
 const viewport=window.visualViewport;
 return {
  x:(viewport?.offsetLeft??0)+margin,y:(viewport?.offsetTop??0)+margin,
  width:Math.max(0,(viewport?.width??document.documentElement.clientWidth)-2*margin),
  height:Math.max(0,(viewport?.height??document.documentElement.clientHeight)-2*margin),
 };
}

export function fitAssistantWindow(box:AssistantWindowBox,area:AssistantWindowBox):AssistantWindowBox{
 const width=clamp(box.width,Math.min(minWidth,area.width),area.width);
 const height=clamp(box.height,Math.min(minHeight,area.height),area.height);
 return {width,height,x:clamp(box.x,area.x,area.x+area.width-width),y:clamp(box.y,area.y,area.y+area.height-height)};
}

export function adjustAssistantWindow(box:AssistantWindowBox,area:AssistantWindowBox,handle:AssistantWindowHandle,dx:number,dy:number):AssistantWindowBox{
 const origin=fitAssistantWindow(box,area);
 if(handle==='move')return fitAssistantWindow({...origin,x:origin.x+dx,y:origin.y+dy},area);
 const right=origin.x+origin.width;
 const maxWidth=handle==='left'?right-area.x:area.x+area.width-origin.x;
 const width=clamp(origin.width+(handle==='left'?-dx:dx),Math.min(minWidth,maxWidth),maxWidth);
 const maxHeight=area.y+area.height-origin.y;
 const height=clamp(origin.height+dy,Math.min(minHeight,maxHeight),maxHeight);
 return {...origin,width,height,x:handle==='left'?right-width:origin.x};
}

export function assistantWindowKeyDelta(key:string,shiftKey:boolean):[number,number]|undefined{
 const direction=Object.hasOwn(arrows,key)?arrows[key]:undefined;
 if(!direction)return;
 const step=shiftKey?40:12;
 return [direction[0]*step,direction[1]*step];
}
