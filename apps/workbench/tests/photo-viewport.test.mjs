import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import ts from 'typescript';
import * as geometry from '../src/workOrderPhoto.ts';

// Exercise the production component's buttons, wheel listener and resize effects.
// The viewport supplies browser geometry; React hooks run until updates settle.
function mount({embedded=false,initialView,natural=[1962,4096],selector=null}={}){
  const states=[],refs=[],layouts=[],effects=[],reports=[];
  let si,ri,li,ei,dirty,tree,observer;
  const viewport={clientWidth:1066,clientHeight:432,scrollLeft:0,scrollTop:0,listeners:new Map(),
    scrollTo(value){this.scrollLeft=Math.max(0,value.left);this.scrollTop=Math.max(0,value.top);},
    addEventListener(name,fn){this.listeners.set(name,fn);},removeEventListener(name){this.listeners.delete(name);},
    hasPointerCapture(){return false;},setPointerCapture(){},releasePointerCapture(){},focus(){},scrollIntoView(){},
    getBoundingClientRect(){return {left:0,top:0,width:this.clientWidth,height:this.clientHeight};}};
  const effect=(slots,index)=> (fn,deps)=>{
    const i=index(),previous=slots[i];
    if(!previous||deps.some((value,j)=>!Object.is(value,previous.deps[j])))slots[i]={fn,deps,pending:true,cleanup:previous?.cleanup};
  };
  const hooks={useState(initial){const i=si++;if(!(i in states))states[i]=initial;return [states[i],value=>{
    const next=typeof value==='function'?value(states[i]):value;
    if(!Object.is(next,states[i])){states[i]=next;dirty=true;}
  }];},useRef(initial){return refs[ri++]||=( {current:initial});},
  useLayoutEffect:effect(layouts,()=>li++),useEffect:effect(effects,()=>ei++)};
  const require=createRequire(import.meta.url),dependencies={react:hooks,'./workOrderPhoto':geometry,'./workOrders.css':{},'lucide-react':{Focus:()=>null,ZoomIn:()=>null,ZoomOut:()=>null}};
  const source=readFileSync(new URL('../src/WorkOrderPhotoViewport.tsx',import.meta.url),'utf8');
  const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  const exports={};new Function('require','exports',compiled)(name=>dependencies[name]??require(name),exports);
  const savedObserver=globalThis.ResizeObserver;
  globalThis.ResizeObserver=class{constructor(callback){observer=callback;}observe(){observer();}disconnect(){}};
  const props={embedded,initialView,selector,image:'blob:synthetic-photo',label:'synthetic photo',en:false,onError:()=>assert.fail('unexpected image error'),onViewChange:value=>reports.push(value)};
  const nodes=()=>{const result=[];function walk(node){if(!node||typeof node!=='object')return;
    if(Array.isArray(node)){node.forEach(walk);return;}result.push(node);walk(node.props?.children);
  }walk(tree);return result;};
  function render(){let turns=0;do{assert.ok(turns++<30,'component must settle');dirty=false;si=ri=li=ei=0;
    tree=exports.WorkOrderPhotoViewport(props);
    for(const node of nodes())if(node.props?.ref)node.props.ref.current=viewport;
    for(const slot of [...layouts,...effects])if(slot.pending){slot.pending=false;slot.cleanup?.();slot.cleanup=slot.fn();}
  }while(dirty);}
  render();nodes().find(node=>node.type==='img').props.onLoad({currentTarget:{naturalWidth:natural[0],naturalHeight:natural[1]}});render();
  const find=(tag,predicate=()=>true)=>nodes().find(node=>node.type===tag&&predicate(node.props));
  return {reports,viewport,
    frame:()=>find('div',p=>p.className==='wo-photo-frame').props.style,
    output:()=>find('output').props.children,
    click(label){const text=value=>Array.isArray(value)?value.map(text).join(''):typeof value==='string'?value:'';
      const button=find('button',p=>p['aria-label']===label||text(p.children)===label);assert.ok(button,label);assert.equal(button.props.disabled,false);button.props.onClick();render();},
    resize(width,height){viewport.clientWidth=width;viewport.clientHeight=height;observer();render();},
    wheel(deltaY,deltaMode=0){let prevented=false,stopped=false;viewport.listeners.get('wheel')({deltaY,deltaMode,clientX:533,clientY:216,preventDefault(){prevented=true;},stopPropagation(){stopped=true;}});render();assert.ok(prevented&&stopped);},
    pan(dx,dy){const region=find('div',p=>p.role==='region').props;region.onPointerDown({button:0,pointerId:1,clientX:533,clientY:216,currentTarget:viewport,preventDefault(){}});render();
      const current=find('div',p=>p.role==='region').props;current.onPointerMove({pointerId:1,clientX:533+dx,clientY:216+dy,currentTarget:viewport});current.onPointerUp();render();},
    destroy(){for(const slot of [...layouts,...effects])slot.cleanup?.();globalThis.ResizeObserver=savedObserver;}
  };
}

for(const embedded of [false,true]){
  test(`${embedded?'embedded':'standalone'} photo keeps button and wheel magnification after scrollbars resize the viewport`,()=>{
    const view=mount({embedded});try{
      const fit=view.frame().height;assert.equal(view.output(),'9.77%');
      view.click('照片放大');const enlarged=view.frame().height;assert.ok(enlarged>fit*1.29);
      view.resize(1051,432);assert.equal(view.frame().height,enlarged,'vertical scrollbar must not refit the image');
      view.wheel(-500);const wheel=view.frame().height;assert.ok(wheel>enlarged*1.6);
      view.resize(1051,417);assert.equal(view.frame().height,wheel,'horizontal scrollbar must not refit the image');
      view.click('100%（1:1）');assert.equal(view.output(),'100%');assert.equal(view.frame().width,1962);assert.equal(view.frame().height,4096);
      view.click('照片放大');assert.equal(view.output(),'130%');assert.equal(view.frame().height,4096*1.3);
      view.resize(500,300);assert.equal(view.output(),'130%');
      view.click('适应窗口');assert.ok(view.frame().width<=468&&view.frame().height<=268.01);
    }finally{view.destroy();}
  });
}
test('the original resource can reach and exceed its native pixel size and left-drag emits a compatible saved view',()=>{
  const view=mount({natural:[5076,10599]});try{
    assert.equal(view.output(),'3.77%');view.click('100%（1:1）');assert.equal(view.frame().height,10599);
    view.wheel(-300);assert.ok(view.frame().height>10599);const before=view.viewport.scrollTop;
    view.pan(-70,-100);assert.equal(view.viewport.scrollTop,before+100);
    const saved=view.reports.at(-1);assert.equal(saved.zoomBasis,'pixels');assert.ok(saved.zoom>1);
    assert.ok(saved.centerX>=0&&saved.centerX<=1&&saved.centerY>=0&&saved.centerY<=1);
  }finally{view.destroy();}
});
test('old fit-relative views restore without rewriting history and new pixel views restore at actual 100%',()=>{
  const old=mount({initialView:{zoom:8,centerX:.5,centerY:.7}});try{
    assert.ok(Math.abs(old.frame().height-3200)<.01);old.resize(1051,417);assert.ok(Math.abs(old.frame().height-3200)<.01);
    assert.equal(old.reports.length,0,'reading a historical view must not write it');
  }finally{old.destroy();}
  const current=mount({initialView:{zoom:1,zoomBasis:'pixels',centerX:.5,centerY:.7}});try{
    assert.equal(current.frame().height,4096);assert.equal(current.output(),'100%');
  }finally{current.destroy();}
});
test('source annotation remains normalized through true pixel zoom and explicit focus',()=>{
  const selector={kind:'image_bbox',coordinateSpace:'oriented_display_normalized',bbox:{x:.4,y:.6,width:.02,height:.03}};
  const view=mount({selector});try{
    const focus=view.frame().height;view.click('100%（1:1）');view.click('照片放大');view.resize(1051,417);
    assert.equal(view.output(),'130%');view.click('定位标注');assert.ok(view.frame().height<4096*1.3&&view.frame().height>0);
    assert.notEqual(view.frame().height,focus,'explicit focus uses the current viewport');
  }finally{view.destroy();}
});
