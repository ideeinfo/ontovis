import {useEffect,useLayoutEffect,useRef,useState,type PointerEvent} from 'react';
import {Focus,ZoomIn,ZoomOut} from 'lucide-react';
import type {PhotoSelector} from './workOrderTypes';
import type {ImageView} from './analysisCanvas';
import {clampPhotoZoom,MAX_PHOTO_ZOOM,MIN_PHOTO_ZOOM,photoBaseSize,photoBoxes,photoFocusScroll,photoFocusZoom,photoWheelZoom,photoZoomScroll} from './workOrderPhoto';
import './workOrders.css';

export function WorkOrderPhotoViewport({image,selector,label,en,onError,embedded=false,initialView,onViewChange,decodedImage,regions=[],onRegion,focusFraction=.09}:{image:string;selector:PhotoSelector|null;label:string;en:boolean;onError:()=>void;embedded?:boolean;initialView?:ImageView;onViewChange?:(value:ImageView)=>void;decodedImage?:HTMLImageElement;regions?:{id:string;title:string;bbox:{x:number;y:number;width:number;height:number}}[];onRegion?:(id:string)=>void;focusFraction?:number}){
  const viewer=useRef<HTMLDivElement>(null);
  const [size,setSize]=useState({width:600,height:500}),[natural,setNatural]=useState({width:0,height:0});
  const [zoom,setZoom]=useState(1),[panning,setPanning]=useState(false);
  const zoomRef=useRef(1),pending=useRef<{left:number;top:number}|null>(null);
  const initial=useRef(initialView),restoring=useRef<ImageView|null>(null),changed=useRef(false),settle=useRef<ReturnType<typeof setTimeout>|undefined>(undefined),lastView=useRef<ImageView|null>(null);
  const onChange=useRef(onViewChange);onChange.current=onViewChange;
  function flushView(){clearTimeout(settle.current);const value=lastView.current;lastView.current=null;if(value)onChange.current?.(value);}
  function report(){if(!changed.current)return;clearTimeout(settle.current);
    const view=viewer.current;if(!view||!natural.width)return;
    lastView.current={zoom:zoomRef.current,centerX:Math.max(0,Math.min(1,(view.scrollLeft+view.clientWidth/2)/Math.max(view.clientWidth,base.width*zoomRef.current))),centerY:Math.max(0,Math.min(1,(view.scrollTop+view.clientHeight/2)/Math.max(view.clientHeight,base.height*zoomRef.current)))};
    settle.current=setTimeout(flushView,180);
  }
  useLayoutEffect(()=>()=>flushView(),[]);
  useLayoutEffect(()=>{
    const view=viewer.current;if(!decodedImage?.naturalWidth||!view)return;
    // Every viewer owns its image element; the decoded cache only supplies size.
    // Moving a shared image into a second card would empty the first card.
    setSize({width:view.clientWidth,height:view.clientHeight});setNatural({width:decodedImage.naturalWidth,height:decodedImage.naturalHeight});
  },[decodedImage,image]);
  const pan=useRef<{id:number;x:number;y:number;left:number;top:number}|null>(null);
  const boxes=photoBoxes(selector),box=boxes.reduce<(typeof boxes)[number]|undefined>((best,value)=>!best||value.width*value.height>best.width*best.height?value:best,undefined);
  const base=photoBaseSize(size.width,size.height,natural.width,natural.height);
  function cancelPan(){
    const view=viewer.current,start=pan.current;pan.current=null;
    if(start&&view?.hasPointerCapture(start.id))view.releasePointerCapture(start.id);
    setPanning(false);
  }
  function applyZoom(next:number,x?:number,y?:number){
    const view=viewer.current;if(!view||!natural.width)return;
    cancelPan();changed.current=true;restoring.current=null;
    pending.current=photoZoomScroll(zoomRef.current,next,base.width,base.height,view.clientWidth,view.clientHeight,view.scrollLeft,view.scrollTop,x??view.clientWidth/2,y??view.clientHeight/2);
    zoomRef.current=next;setZoom(next);
    if(next===zoom){view.scrollTo(pending.current);pending.current=null;}report();
  }
  function focusPhoto(){
    const view=viewer.current;if(!view||!natural.width)return;
    cancelPan();restoring.current=null;const next=photoFocusZoom(box,size.width,size.height,natural.width,natural.height,focusFraction);
    pending.current=photoFocusScroll(box,base.width*next,base.height*next,view.clientWidth,view.clientHeight);
    zoomRef.current=next;setZoom(next);
    if(next===zoom){view.scrollTo(pending.current);pending.current=null;}
  }
  useLayoutEffect(()=>{
    const view=viewer.current;if(!view)return;
    const observer=new ResizeObserver(()=>{
      const width=view.clientWidth,height=view.clientHeight;
      setSize(current=>current.width===width&&current.height===height?current:{width,height});
    });
    observer.observe(view);return()=>observer.disconnect();
  },[]);
  useLayoutEffect(()=>{if(initial.current&&natural.width){const value=initial.current;initial.current=undefined;
    zoomRef.current=value.zoom;setZoom(value.zoom);restoring.current=value;
  // The loading placeholder and scrollbars change the usable viewport after
  // decoding. Finish automatic centering before preserving the user's view.
  }else if(!embedded||!changed.current&&!restoring.current)focusPhoto();},[natural.width,natural.height,size.width,size.height]);
  useLayoutEffect(()=>{const view=viewer.current,value=restoring.current;if(!view||zoomRef.current!==zoom)return;
    // Image dimensions settle after the viewer opens; restore against the final
    // frame rather than the temporary pre-scrollbar viewport.
    if(value)view.scrollTo({left:Math.max(view.clientWidth,base.width*zoom)*value.centerX-view.clientWidth/2,top:Math.max(view.clientHeight,base.height*zoom)*value.centerY-view.clientHeight/2});
    else if(pending.current){view.scrollTo(pending.current);pending.current=null;}
  },[zoom,base.width,base.height]);
  useLayoutEffect(()=>{if(natural.width&&!embedded)viewer.current?.scrollIntoView({block:'center',inline:'nearest'});},[natural.width,natural.height,embedded]);
  useEffect(()=>{
    const view=viewer.current;if(!view)return;
    const wheel=(event:WheelEvent)=>{
      if(!natural.width)return;event.preventDefault();event.stopPropagation();
      const rect=view.getBoundingClientRect();
      applyZoom(photoWheelZoom(zoomRef.current,event.deltaY,event.deltaMode,view.clientHeight),(event.clientX-rect.left)*view.clientWidth/rect.width,(event.clientY-rect.top)*view.clientHeight/rect.height);
    };
    view.addEventListener('wheel',wheel,{passive:false});return()=>view.removeEventListener('wheel',wheel);
  },[natural.width,base.width,base.height,zoom]);
  function start(event:PointerEvent<HTMLDivElement>){
    if(event.button!==0||!natural.width)return;
    event.preventDefault();changed.current=true;restoring.current=null;event.currentTarget.focus({preventScroll:true});event.currentTarget.setPointerCapture(event.pointerId);
    pan.current={id:event.pointerId,x:event.clientX,y:event.clientY,left:event.currentTarget.scrollLeft,top:event.currentTarget.scrollTop};setPanning(true);
  }
  return <>
    <div className="wo-photo-tools"><span>{selector?.kind==='spherical_region'?(en?'Panorama · unfolded region':'球面全景 · 展开图区域'):(en?'Fixed display region':'固定显示资源区域')}</span>
      <button type="button" aria-label={en?'Zoom out':'照片缩小'} disabled={!natural.width||zoom<=MIN_PHOTO_ZOOM} onClick={()=>applyZoom(clampPhotoZoom(zoom/1.3))}><ZoomOut size={15}/></button>
      <button type="button" aria-label={en?'Zoom in':'照片放大'} disabled={!natural.width||zoom>=MAX_PHOTO_ZOOM} onClick={()=>applyZoom(clampPhotoZoom(zoom*1.3))}><ZoomIn size={15}/></button>
      <output aria-label={en?'Photo zoom':'照片缩放比例'}>{Math.round(zoom*100)}%</output>
      <button type="button" disabled={!natural.width} onClick={()=>{changed.current=true;focusPhoto();report();}}><Focus size={14}/>{en?'Focus annotation':'定位标注'}</button>
      <button type="button" disabled={!natural.width} onClick={()=>applyZoom(1)}>{en?'Fit photo':'适应窗口'}</button>
    </div>
    <p className="wo-photo-hint">{en?'Scroll to zoom · drag with the left mouse button to pan':'滚轮缩放 · 按住鼠标左键平移'}</p>
    {!natural.width&&<p className="wo-empty" role="status">{en?'Preparing photo display…':'正在解码照片…'}</p>}
    <div className={`wo-photo-scroll${panning?' panning':''}`} ref={viewer} role="region" aria-label={en?'Photo viewer':'照片查看器'} tabIndex={0}
      onScroll={report} onPointerDown={start} onPointerMove={event=>{const value=pan.current;if(value?.id===event.pointerId){const view=event.currentTarget,rect=view.getBoundingClientRect();view.scrollLeft=value.left-(event.clientX-value.x)*view.clientWidth/rect.width;view.scrollTop=value.top-(event.clientY-value.y)*view.clientHeight/rect.height;}}}
      onPointerUp={()=>{report();flushView();cancelPan();}} onPointerCancel={cancelPan} onLostPointerCapture={cancelPan}
      onKeyDown={event=>{if(['+','=','-'].includes(event.key)){event.preventDefault();applyZoom(clampPhotoZoom(zoom+(event.key==='-'?-.1:.1)));}else if(event.key==='Escape')cancelPan();}}>
      <div className="wo-photo-stage"><div className="wo-photo-frame" style={{width:base.width*zoom,height:base.height*zoom,visibility:natural.width?'visible':'hidden'}}>
        <img src={image} alt={label} draggable={false} onLoad={event=>setNatural({width:event.currentTarget.naturalWidth,height:event.currentTarget.naturalHeight})} onError={onError}/>
        {regions.map(region=><button key={region.id} type="button" className="ac-drawing-hotspot" aria-label={region.title} title={region.title}
          onPointerDown={event=>event.stopPropagation()} onClick={()=>onRegion?.(region.id)} style={{left:`${region.bbox.x*100}%`,top:`${region.bbox.y*100}%`,width:`${region.bbox.width*100}%`,height:`${region.bbox.height*100}%`}}/>)}
        {boxes.map((region,index)=><span key={index} className="wo-photo-region" style={{left:`${region.x*100}%`,top:`${region.y*100}%`,width:`${region.width*100}%`,height:`${region.height*100}%`}}><span>{selector?.regionKind==='label_region'?(en?'Label region':'来源标签区域'):(en?'Object region':'来源对象区域')}</span></span>)}
      </div></div>
    </div>
  </>;
}
