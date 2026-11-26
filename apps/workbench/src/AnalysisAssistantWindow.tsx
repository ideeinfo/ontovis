import {useLayoutEffect,useRef,useState,type KeyboardEvent,type PointerEvent,type ReactNode} from 'react';
import {GripHorizontal,MoveDiagonal,MoveDiagonal2,X} from 'lucide-react';
import {IconBtn} from './Primitives';
import {displayText} from './displayText';

type Size={width:number;height:number};
type Box=Size&{x:number;y:number};
type Handle='move'|'left'|'right';
const arrows:Record<string,[number,number]>={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]};
const clamp=(value:number,low:number,high:number)=>Math.min(Math.max(value,low),high);
function fit(box:Box,area:Size):Box{
 const width=clamp(box.width,Math.min(300,area.width),area.width);
 const height=clamp(box.height,Math.min(340,area.height),area.height);
 return {width,height,x:clamp(box.x,0,area.width-width),y:clamp(box.y,0,area.height-height)};
}

export function AnalysisAssistantWindow({title,en,onClose,children}:{title:string;en:boolean;onClose:()=>void;children:ReactNode}){
 const [box,setBox]=useState<Box|null>(null);
 const windowRef=useRef<HTMLElement>(null),area=useRef<Size>({width:0,height:0});
 const drag=useRef<{pointer:number;handle:Handle;x:number;y:number;box:Box}|null>(null);
 const t=(zh:string,english:string)=>en?english:zh;
 useLayoutEffect(()=>{
  const parent=windowRef.current?.parentElement;
  if(!parent)return;
  const update=()=>{
   const width=parent.clientWidth,height=parent.clientHeight;
   if(!width||!height)return;
   area.current={width,height};
   setBox(previous=>fit(previous??{x:width-444,y:12,width:432,height:Math.min(height-68,640)},area.current));
  };
  update();
  const observer=new ResizeObserver(update);
  observer.observe(parent);
  return()=>observer.disconnect();
 },[]);
 function adjust(start:Box,handle:Handle,dx:number,dy:number){
  const bounds=area.current;
  if(handle==='move'){setBox(fit({...start,x:start.x+dx,y:start.y+dy},bounds));return;}
  const right=start.x+start.width;
  const maxWidth=handle==='left'?right:bounds.width-start.x;
  const width=clamp(start.width+(handle==='left'?-dx:dx),Math.min(300,maxWidth),maxWidth);
  const maxHeight=bounds.height-start.y;
  const height=clamp(start.height+dy,Math.min(340,maxHeight),maxHeight);
  setBox({...start,width,height,x:handle==='left'?right-width:start.x});
 }
 function begin(event:PointerEvent<HTMLButtonElement>,handle:Handle){
  if(!box||event.button!==0||drag.current)return;
  event.preventDefault();
  event.currentTarget.setPointerCapture(event.pointerId);
  drag.current={pointer:event.pointerId,handle,x:event.clientX,y:event.clientY,box};
 }
 function move(event:PointerEvent<HTMLButtonElement>){
  const value=drag.current;
  if(value?.pointer===event.pointerId)adjust(value.box,value.handle,event.clientX-value.x,event.clientY-value.y);
 }
 function end(event:PointerEvent<HTMLButtonElement>){
  if(drag.current?.pointer===event.pointerId)drag.current=null;
 }
 function keyboard(event:KeyboardEvent<HTMLButtonElement>,handle:Handle){
  const direction=arrows[event.key];
  if(!box||!direction)return;
  event.preventDefault();
  const step=event.shiftKey?40:12;
  adjust(box,handle,direction[0]*step,direction[1]*step);
 }
 function grip(handle:Handle,label:string){
  return {type:'button' as const,'aria-label':label,title:label,onPointerDown:(event:PointerEvent<HTMLButtonElement>)=>begin(event,handle),
   onPointerMove:move,onLostPointerCapture:end,onPointerCancel:end,onPointerUp:end,
   onKeyDown:(event:KeyboardEvent<HTMLButtonElement>)=>keyboard(event,handle)};
 }
 const label=t('分析助手','Analysis assistant');
 return <aside ref={windowRef} className="ad-inspector ad-assistant ad-assistant-window" aria-label={label}
  style={box?{left:box.x,top:box.y,width:box.width,height:box.height}:{visibility:'hidden'}}>
  <header><button className="as-window-grip" {...grip('move',t('移动助手窗口','Move assistant window'))}>
   <GripHorizontal size={16}/><strong>{label}</strong><span title={title}>{displayText(title)}</span>
  </button><IconBtn label={t('关闭助手','Close assistant')} onClick={onClose}><X size={16}/></IconBtn></header>
  {children}
  <button className="as-window-resize as-window-resize-left" {...grip('left',t('向左缩放助手窗口','Resize assistant from the left'))}><MoveDiagonal size={13}/></button>
  <button className="as-window-resize as-window-resize-right" {...grip('right',t('向右缩放助手窗口','Resize assistant from the right'))}><MoveDiagonal2 size={13}/></button>
 </aside>;
}
