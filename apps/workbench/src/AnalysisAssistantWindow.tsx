import {useLayoutEffect,useRef,useState,type KeyboardEvent,type PointerEvent,type ReactNode} from 'react';
import {GripHorizontal,MoveDiagonal,MoveDiagonal2,X} from 'lucide-react';
import {IconBtn} from './Primitives';
import {displayText} from './displayText';

type Size={width:number;height:number};
type Box=Size&{x:number;y:number};
type Handle='move'|'left'|'right';
const WINDOW_POSITION='ontovis.workbench.analysis_assistant_window';
const arrows:Record<string,[number,number]>={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]};
const clamp=(value:number,low:number,high:number)=>Math.min(Math.max(value,low),high);
function fit(box:Box,area:Box):Box{
 const width=clamp(box.width,Math.min(300,area.width),area.width);
 const height=clamp(box.height,Math.min(340,area.height),area.height);
 return {width,height,x:clamp(box.x,area.x,area.x+area.width-width),y:clamp(box.y,area.y,area.y+area.height-height)};
}
function savedWindow():Box|null{
 try{
  const saved=JSON.parse(localStorage.getItem(WINDOW_POSITION)??'null');
  if(saved&&[saved.x,saved.y,saved.width,saved.height].every(Number.isFinite)&&saved.width>0&&saved.height>0){
   return {x:saved.x,y:saved.y,width:saved.width,height:saved.height};
  }
 }catch{}
 return null;
}
function rememberWindow(box:Box|null){
 if(box)try{localStorage.setItem(WINDOW_POSITION,JSON.stringify(box));}catch{}
}

export function AnalysisAssistantWindow({title,en,onClose,children}:{title:string;en:boolean;onClose:()=>void;children:ReactNode}){
 const [box,setBox]=useState<Box|null>(null);
 const windowRef=useRef<HTMLElement>(null),area=useRef<Box>({x:0,y:0,width:0,height:0});
 const preferred=useRef<Box|null>(null);
 const drag=useRef<{pointer:number;handle:Handle;x:number;y:number;box:Box}|null>(null);
 const t=(zh:string,english:string)=>en?english:zh;
 useLayoutEffect(()=>{
  const initialArea=windowRef.current?.parentElement?.getBoundingClientRect();
  const viewport=window.visualViewport;
  preferred.current=savedWindow();
  const update=()=>{
   const width=viewport?.width??document.documentElement.clientWidth;
   const height=viewport?.height??document.documentElement.clientHeight;
   if(!width||!height)return;
   const bounds={x:viewport?.offsetLeft??0,y:viewport?.offsetTop??0,width,height};
   area.current=bounds;
   setBox(fit(preferred.current??{
    x:(initialArea?.right||bounds.x+width)-444,y:(initialArea?.top??bounds.y)+12,
    width:432,height:Math.min((initialArea?.height||height)-68,640),
   },bounds));
  };
  update();
  window.addEventListener('resize',update);
  viewport?.addEventListener('resize',update);
  viewport?.addEventListener('scroll',update);
  return()=>{
   if(drag.current)rememberWindow(preferred.current);
   window.removeEventListener('resize',update);
   viewport?.removeEventListener('resize',update);
   viewport?.removeEventListener('scroll',update);
  };
 },[]);
 function place(next:Box){preferred.current=next;setBox(next);}
 function adjust(initial:Box,handle:Handle,dx:number,dy:number){
  const bounds=area.current;
  const start=fit(initial,bounds);
  if(handle==='move'){place(fit({...start,x:start.x+dx,y:start.y+dy},bounds));return;}
  const right=start.x+start.width;
  const maxWidth=handle==='left'?right-bounds.x:bounds.x+bounds.width-start.x;
  const width=clamp(start.width+(handle==='left'?-dx:dx),Math.min(300,maxWidth),maxWidth);
  const maxHeight=bounds.y+bounds.height-start.y;
  const height=clamp(start.height+dy,Math.min(340,maxHeight),maxHeight);
  place({...start,width,height,x:handle==='left'?right-width:start.x});
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
  if(drag.current?.pointer===event.pointerId){drag.current=null;rememberWindow(preferred.current);}
 }
 function keyboard(event:KeyboardEvent<HTMLButtonElement>,handle:Handle){
  const direction=arrows[event.key];
  if(!box||!direction)return;
  event.preventDefault();
  const step=event.shiftKey?40:12;
  adjust(box,handle,direction[0]*step,direction[1]*step);
  rememberWindow(preferred.current);
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
