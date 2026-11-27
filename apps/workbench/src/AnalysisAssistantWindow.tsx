import {useLayoutEffect,useRef,useState,type KeyboardEvent,type PointerEvent,type ReactNode} from 'react';
import {GripHorizontal,MoveDiagonal,MoveDiagonal2,X} from 'lucide-react';
import {IconBtn} from './Primitives';
import {displayText} from './displayText';
import {adjustAssistantWindow,assistantWindowKeyDelta,assistantWindowViewport,fitAssistantWindow,type AssistantWindowBox,type AssistantWindowHandle} from './assistantWindowGeometry';

const WINDOW_POSITION='ontovis.workbench.analysis_assistant_window';
function savedWindow():AssistantWindowBox|null{
 try{
  const saved=JSON.parse(localStorage.getItem(WINDOW_POSITION)??'null');
  if(saved&&[saved.x,saved.y,saved.width,saved.height].every(Number.isFinite)&&saved.width>0&&saved.height>0){
   return {x:saved.x,y:saved.y,width:saved.width,height:saved.height};
  }
 }catch{}
 return null;
}
function rememberWindow(box:AssistantWindowBox|null){
 if(box)try{localStorage.setItem(WINDOW_POSITION,JSON.stringify(box));}catch{}
}

export function AnalysisAssistantWindow({title,en,onClose,children}:{title:string;en:boolean;onClose:()=>void;children:ReactNode}){
 const [box,setBox]=useState<AssistantWindowBox|null>(null);
 const windowRef=useRef<HTMLElement>(null),area=useRef<AssistantWindowBox>({x:0,y:0,width:0,height:0});
 const preferred=useRef<AssistantWindowBox|null>(null);
 const drag=useRef<{pointer:number;handle:AssistantWindowHandle;x:number;y:number;box:AssistantWindowBox}|null>(null);
 const t=(zh:string,english:string)=>en?english:zh;
 useLayoutEffect(()=>{
  const initialArea=windowRef.current?.parentElement?.getBoundingClientRect();
  const viewport=window.visualViewport;
  preferred.current=savedWindow();
  const update=()=>{
   const bounds=assistantWindowViewport(),{width,height}=bounds;
   if(!width||!height)return;
   area.current=bounds;
   setBox(fitAssistantWindow(preferred.current??{
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
 function adjust(initial:AssistantWindowBox,handle:AssistantWindowHandle,dx:number,dy:number){
  const next=adjustAssistantWindow(initial,area.current,handle,dx,dy);
  preferred.current=next;
  setBox(next);
 }
 function begin(event:PointerEvent<HTMLElement>,handle:AssistantWindowHandle){
  if(!box||event.button!==0||!event.isPrimary||drag.current)return;
  event.preventDefault();
  event.currentTarget.setPointerCapture(event.pointerId);
  drag.current={pointer:event.pointerId,handle,x:event.clientX,y:event.clientY,box};
 }
 function move(event:PointerEvent<HTMLElement>){
  const value=drag.current;
  if(value?.pointer===event.pointerId)adjust(value.box,value.handle,event.clientX-value.x,event.clientY-value.y);
 }
 function end(event:PointerEvent<HTMLElement>){
  if(drag.current?.pointer===event.pointerId){drag.current=null;rememberWindow(preferred.current);}
 }
 function keyboard(event:KeyboardEvent<HTMLElement>,handle:AssistantWindowHandle){
  const delta=assistantWindowKeyDelta(event.key,event.shiftKey);
  if(!box||!delta)return;
  event.preventDefault();
  adjust(box,handle,...delta);
  rememberWindow(preferred.current);
 }
 const dragEvents={onPointerMove:move,onLostPointerCapture:end,onPointerCancel:end,onPointerUp:end};
 function grip(handle:'left'|'right',label:string){
  return {type:'button' as const,'aria-label':label,title:label,...dragEvents,onPointerDown:(event:PointerEvent<HTMLButtonElement>)=>begin(event,handle),
   onKeyDown:(event:KeyboardEvent<HTMLButtonElement>)=>keyboard(event,handle)};
 }
 const label=t('分析助手','Analysis assistant');
 return <aside ref={windowRef} className="ad-inspector ad-assistant ad-assistant-window" aria-label={label}
  style={box?{left:box.x,top:box.y,width:box.width,height:box.height}:{visibility:'hidden'}}>
  <header {...dragEvents} role="group" aria-label={t('移动助手窗口','Move assistant window')} tabIndex={0}
   onPointerDown={event=>{if(!(event.target as Element).closest('button'))begin(event,'move');}}
   onKeyDown={event=>{if(event.target===event.currentTarget)keyboard(event,'move');}}>
   <div className="as-window-title"><GripHorizontal size={16} aria-hidden="true"/><strong>{label}</strong><span title={title}>{displayText(title)}</span></div>
   <IconBtn label={t('关闭助手','Close assistant')} onClick={onClose}><X size={16}/></IconBtn>
  </header>
  {children}
  <button className="as-window-resize as-window-resize-left" {...grip('left',t('向左缩放助手窗口','Resize assistant from the left'))}><MoveDiagonal size={13}/></button>
  <button className="as-window-resize as-window-resize-right" {...grip('right',t('向右缩放助手窗口','Resize assistant from the right'))}><MoveDiagonal2 size={13}/></button>
 </aside>;
}
