import {useEffect,useMemo,useRef,useState} from 'react';
import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {ArrowRight,Focus,Globe2,Pause,Play,X} from 'lucide-react';
import earthMap from '../../../assets/maps/bluemarble-2048.png';
import {clusterGlobePoints,globeClusterDegrees,globeClusterFocusDistance,globeDriftRadians,globeVector,globeFlightProgress,resumedGlobeFlightStart,globeFramePlan,type GlobePoint} from './cockpitSpace';
import './cockpitSpace.css';

export function WindTurbineIcon({size=16,className=''}:{size?:number;className?:string}){
 return <svg viewBox="0 0 24 24" width={size} height={size} fill="currentColor" className={className} aria-hidden="true">
  <path d="M11.3 11.5L10.5 21.5H13.5L12.7 11.5Z" opacity="0.85"/>
  <circle cx="12" cy="11" r="1.6"/>
  <path d="M12 11C12.6 7.5 13.6 3.8 12 1.5C10.8 3.8 11.4 7.5 12 11Z"/>
  <path d="M12 11C14.8 12.8 18.5 15.2 20.2 13.8C18.2 11.8 14.6 11.5 12 11Z"/>
  <path d="M12 11C9.5 13 5.8 15.2 4.8 13C7 11.5 9.4 11.5 12 11Z"/>
 </svg>;
}

export type GlobeFlight={token:number;longitude:number;latitude:number;direction:'in'|'out'};
export function CockpitGlobe({points,active,en,light,flight,focusTarget,onSelectScene,paused,onTogglePause,onOpen}:{points:GlobePoint[];active:boolean;en:boolean;light:boolean;flight:GlobeFlight|null;focusTarget?:{sceneId:string;token:number}|null;onSelectScene?:(sceneId:string)=>void;paused:boolean;onTogglePause:()=>void;onOpen:(id:string)=>void}){
 const mount=useRef<HTMLDivElement>(null),pins=useRef(new Map<string,HTMLButtonElement>());
 const [fallback,setFallback]=useState(false),[selected,setSelected]=useState(''),[clusterDegrees,setClusterDegrees]=useState(()=>globeClusterDegrees(3.65,900));
 const groups=useMemo(()=>clusterGlobePoints(points,clusterDegrees),[points,clusterDegrees]),selectedGroup=groups.find(g=>g.id===selected);
 const latest=useRef({groups,active,light,flight,paused,inspecting:!!selectedGroup});latest.current={groups,active,light,flight,paused,inspecting:!!selectedGroup};
 const runtime=useRef<{refresh:()=>void;focus:(longitude:number,latitude:number,distance?:number)=>void;home:()=>void;distance:()=>number;height:()=>number}|null>(null);
 const lastFocusToken=useRef<number>(-1);
 useEffect(()=>{
  if(!focusTarget||focusTarget.token===lastFocusToken.current)return;
  lastFocusToken.current=focusTarget.token;
  const targetGroup=groups.find(g=>g.points.some(p=>p.sceneId===focusTarget.sceneId));
  if(targetGroup){
   setSelected(targetGroup.id);
   const currentDistance=runtime.current?.distance()??3.65,height=runtime.current?.height()??900;
   const targetDistance=globeClusterFocusDistance(targetGroup,height);
   runtime.current?.focus(targetGroup.longitude,targetGroup.latitude,Math.min(currentDistance,targetDistance));
  }else setSelected('');
 },[focusTarget,groups]);
 useEffect(()=>{
  if(!mount.current)return;const element=mount.current;let renderer:THREE.WebGLRenderer;
  try{renderer=new THREE.WebGLRenderer({antialias:true,alpha:true,powerPreference:'low-power'});}catch{setFallback(true);return;}
  let disposed=false,failed=false,frame=0,lastFlight=-1,lastDraw=0,resumeAt=performance.now(),interacting=false,drifting=false,texture:THREE.Texture|null=null;
  const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(34,1,.01,100);
  const overview=new THREE.Vector3(...globeVector(108,28)).multiplyScalar(3.65);camera.position.copy(overview);
  let lastDegrees=globeClusterDegrees(camera.position.length(),Math.max(240,element.clientHeight||900));
  setClusterDegrees(lastDegrees);
  const syncDegrees=()=>{
   const next=globeClusterDegrees(camera.position.length(),Math.max(240,element.clientHeight||900));
   if(next!==lastDegrees){lastDegrees=next;setClusterDegrees(next);}
  };
  renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.setClearAlpha(0);renderer.outputColorSpace=THREE.SRGBColorSpace;
  renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.1;element.append(renderer.domElement);
  const controls=new OrbitControls(camera,renderer.domElement);controls.enablePan=false;controls.enableDamping=false;controls.minDistance=1.12;controls.maxDistance=5.8;controls.rotateSpeed=.5;controls.zoomSpeed=.55;
  const geometry=new THREE.SphereGeometry(1,80,48),material=new THREE.MeshPhongMaterial({color:0xb6cecb,shininess:7,specular:0x173346});
  const earth=new THREE.Mesh(geometry,material);scene.add(earth);
  const ambient=new THREE.AmbientLight(0xcadbe0,1.35),sun=new THREE.DirectionalLight(0xfff4d7,2.3);sun.position.fromArray(globeVector(85,30)).multiplyScalar(5);scene.add(ambient,sun);
  const glowMaterial=new THREE.ShaderMaterial({transparent:true,depthWrite:false,side:THREE.BackSide,blending:THREE.AdditiveBlending,
   uniforms:{tint:{value:new THREE.Color(0x518d9a)}},vertexShader:'varying vec3 n; varying vec3 v; void main(){vec4 p=modelViewMatrix*vec4(position,1.); n=normalize(normalMatrix*normal);v=normalize(-p.xyz);gl_Position=projectionMatrix*p;}',
   fragmentShader:'varying vec3 n;varying vec3 v;uniform vec3 tint;void main(){float a=pow(1.-abs(dot(normalize(n),normalize(v))),3.);gl_FragColor=vec4(tint,a*.65);}'});
  const glow=new THREE.Mesh(geometry,glowMaterial);glow.scale.setScalar(1.035);scene.add(glow);
  const cloudMaterial=new THREE.ShaderMaterial({transparent:true,depthWrite:false,uniforms:{opacity:{value:.18}},
   vertexShader:'varying vec3 p;void main(){p=position;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}',
   fragmentShader:'varying vec3 p;uniform float opacity;float h(vec3 q){return fract(sin(dot(q,vec3(127.1,311.7,74.7)))*43758.5453);}float n(vec3 q){vec3 i=floor(q),f=fract(q);f=f*f*(3.-2.*f);return mix(mix(mix(h(i),h(i+vec3(1,0,0)),f.x),mix(h(i+vec3(0,1,0)),h(i+vec3(1,1,0)),f.x),f.y),mix(mix(h(i+vec3(0,0,1)),h(i+vec3(1,0,1)),f.x),mix(h(i+vec3(0,1,1)),h(i+vec3(1,1,1)),f.x),f.y),f.z);}void main(){float c=n(p*14.)*.6+n(p*39.)*.3+n(p*91.)*.1;float a=smoothstep(.49,.72,c)*opacity;gl_FragColor=vec4(.87,.94,.94,a);}'});
  const clouds=new THREE.Mesh(geometry,cloudMaterial);clouds.scale.setScalar(1.008);scene.add(clouds);
  let tween:{start:number;from:THREE.Vector3;to:THREE.Vector3}|null=null,hiddenAt:number|null=null;
  const media=matchMedia('(prefers-reduced-motion: reduce)');
  const schedule=()=>{if(!disposed&&!failed&&!document.hidden&&latest.current.active&&!frame)frame=requestAnimationFrame(draw);};
  const focus=(longitude:number,latitude:number,distance=2.35)=>{
   resumeAt=performance.now()+4500;
   const to=new THREE.Vector3(...globeVector(longitude,latitude)).multiplyScalar(distance);
   if(media.matches){camera.position.copy(to);controls.update();tween=null;}else tween={start:performance.now(),from:camera.position.clone(),to};schedule();
  };
  const refresh=()=>{
   const state=latest.current;controls.enabled=state.active&&state.flight?.direction!=='in';
   material.color.set(state.light?0xe2e8d8:0xb6cecb);glowMaterial.uniforms.tint.value.set(state.light?0x799a8d:0x518d9a);cloudMaterial.uniforms.opacity.value=state.light ? .12 : .2;
   const newFlight=!!state.flight&&state.flight.token!==lastFlight;
   if(state.flight&&newFlight){lastFlight=state.flight.token;focus(state.flight.longitude,state.flight.latitude,state.flight.direction==='in'?1.14:3.65);}
   if(!state.active||document.hidden){cancelAnimationFrame(frame);frame=0;lastDraw=0;drifting=false;if(hiddenAt===null)hiddenAt=performance.now();if(!state.active)tween=null;}else{if(hiddenAt!==null){if(tween)tween.start=resumedGlobeFlightStart(tween.start,hiddenAt,performance.now(),newFlight);resumeAt=performance.now();lastDraw=0;}hiddenAt=null;schedule();}
  };
  function draw(){
   frame=0;if(disposed||failed||document.hidden||!latest.current.active)return;
   const now=performance.now(),state=latest.current,plan=globeFramePlan(!!tween,!state.paused&&!state.inspecting&&!interacting&&!media.matches&&state.flight?.direction!=='in'),canDrift=plan.drift;
   if(canDrift&&!drifting)resumeAt=Math.max(resumeAt,now);
   const angle=globeDriftRadians(lastDraw?now-lastDraw:0,now-resumeAt,canDrift);lastDraw=now;drifting=canDrift;
   if(angle){camera.position.applyAxisAngle(new THREE.Vector3(0,1,0),angle);controls.update();}
   if(tween){const progress=globeFlightProgress(tween.start,now),e=progress*progress*(3-2*progress);
    const direction=tween.from.clone().normalize(),rotation=new THREE.Quaternion().setFromUnitVectors(direction,tween.to.clone().normalize());
    direction.applyQuaternion(new THREE.Quaternion().slerp(rotation,e));camera.position.copy(direction.multiplyScalar(THREE.MathUtils.lerp(tween.from.length(),tween.to.length(),e)));controls.update();if(progress===1)tween=null;}
   syncDegrees();
   camera.updateMatrixWorld();const width=element.clientWidth,height=element.clientHeight;
   for(const group of latest.current.groups){const button=pins.current.get(group.id);if(!button)continue;
    const point=new THREE.Vector3(...globeVector(group.longitude,group.latitude)),front=point.dot(camera.position)>1.025;
    point.multiplyScalar(1.016).project(camera);button.style.display=front&&point.z>=-1&&point.z<=1?'':'none';button.style.left=`${element.offsetLeft+(point.x+1)*width/2}px`;button.style.top=`${element.offsetTop+(1-point.y)*height/2}px`;
   }
   try{renderer.render(scene,camera);}catch{failed=true;setFallback(true);return;}if(plan.continue)schedule();
  }
  const resize=new ResizeObserver(()=>{const width=Math.max(1,element.clientWidth),height=Math.max(1,element.clientHeight);renderer.setSize(width,height);camera.aspect=width/height;camera.updateProjectionMatrix();syncDegrees();schedule();});resize.observe(element);
  const change=()=>schedule(),start=()=>{tween=null;interacting=true;drifting=false;},end=()=>{interacting=false;resumeAt=performance.now()+4500;lastDraw=0;schedule();};controls.addEventListener('change',change);controls.addEventListener('start',start);controls.addEventListener('end',end);
  const lost=(event:Event)=>{event.preventDefault();failed=true;setFallback(true);cancelAnimationFrame(frame);frame=0;};renderer.domElement.addEventListener('webglcontextlost',lost);
  document.addEventListener('visibilitychange',refresh);media.addEventListener('change',refresh);
  new THREE.TextureLoader().load(earthMap,value=>{if(disposed){value.dispose();return;}texture=value;value.colorSpace=THREE.SRGBColorSpace;value.anisotropy=Math.min(4,renderer.capabilities.getMaxAnisotropy());material.map=value;material.needsUpdate=true;schedule();},undefined,()=>{if(!disposed){failed=true;cancelAnimationFrame(frame);frame=0;setFallback(true);}});
  runtime.current={refresh,focus,home:()=>focus(108,28,3.65),distance:()=>camera.position.length(),height:()=>Math.max(240,element.clientHeight||900)};refresh();
  return()=>{disposed=true;cancelAnimationFrame(frame);resize.disconnect();document.removeEventListener('visibilitychange',refresh);media.removeEventListener('change',refresh);controls.removeEventListener('change',change);controls.removeEventListener('start',start);controls.removeEventListener('end',end);controls.dispose();geometry.dispose();material.dispose();glowMaterial.dispose();cloudMaterial.dispose();texture?.dispose();renderer.domElement.removeEventListener('webglcontextlost',lost);renderer.dispose();renderer.forceContextLoss();renderer.domElement.remove();runtime.current=null;};
 },[]);
 useEffect(()=>{runtime.current?.refresh();},[active,light,flight,groups,paused,selectedGroup]);
 useEffect(()=>{if(!active){setSelected('');onSelectScene?.('');}},[active]);
 return <section className={`pc-globe-view${fallback?' is-fallback':''}`} aria-label={en?'Project globe':'项目地球'}>
  <div className="pc-globe-render" ref={mount}/>
  {fallback?<div className="pc-globe-fallback"><Globe2/><span>{en?'Globe unavailable; use the scene list.':'地球视图暂不可用，请从场景列表进入。'}</span></div>:groups.map(group=><button className={`pc-globe-pin${selected===group.id?' selected':''}${group.coincident?' coincident':group.points.length>1?' cluster':''}`} key={group.id} ref={element=>{if(element)pins.current.set(group.id,element);else pins.current.delete(group.id);}} aria-label={group.points.length>1?(group.coincident?`${group.points.length} ${en?'co-located scene reference points':'个同位置场景参考点'} · ${group.points.map(p=>p.name).join(' / ')}`:`${group.points.length} ${en?'scene reference points':'个场景参考点'}`):`${group.points[0].name} · ${en?'reference point':'参考点'}`} onClick={()=>{
   const currentDistance=runtime.current?.distance()??3.65,height=runtime.current?.height()??900;
   const targetDistance=globeClusterFocusDistance(group,height),targetDegrees=globeClusterDegrees(targetDistance,height);
   if(group.points.length>1&&!group.coincident&&targetDegrees<clusterDegrees&&currentDistance>targetDistance+.04){setSelected('');onSelectScene?.('');runtime.current?.focus(group.longitude,group.latitude,targetDistance);return;}
   if(group.points.length===1&&selected===group.id){onOpen(group.points[0].sceneId);return;}
   setSelected(group.id);onSelectScene?.(group.points[0]?.sceneId||'');runtime.current?.focus(group.longitude,group.latitude,Math.min(currentDistance,targetDistance));
  }}>
   <span className="pc-globe-pin-icon">
    <i/>
    <WindTurbineIcon size={16}/>
    {group.points.length>1&&<b>{group.points.length}</b>}
   </span>
   {group.points.length===1?<span>{group.points[0].name}</span>:group.coincident?<span>{group.points[0].name} +{group.points.length-1}</span>:null}
  </button>)}
  {selectedGroup&&<aside className="pc-globe-choice" aria-label={en?'Scene reference points':'场景参考点'}>
   <header>
    <div className="pc-globe-choice-head">
     <strong>{en?'Scene reference points':'场景参考点'}</strong>
     <small>{selectedGroup.coincident?(en?'Same reference coordinates · accuracy unverified':'同参考坐标场景 · 位置精度未核实'):(en?'Location accuracy unverified':'位置精度未核实')}</small>
    </div>
    <button className="pc-globe-choice-close" aria-label={en?'Close reference points':'关闭参考点'} onClick={()=>{setSelected('');onSelectScene?.('');}}><X size={15}/></button>
   </header>
   <div className="pc-globe-choice-list">
    {selectedGroup.points.map(point=><button key={point.sceneId} className="pc-globe-choice-item" onClick={()=>onOpen(point.sceneId)} aria-label={`${en?'Enter':'进入场景'} ${point.name}`}>
     <span className="pc-globe-choice-info">
      <WindTurbineIcon size={15}/>
      <span className="pc-globe-choice-name" title={point.name}>{point.name}</span>
     </span>
     <span className="pc-globe-choice-btn">
      <span>{en?'Enter scene':'进入场景'}</span>
      <ArrowRight size={13}/>
     </span>
    </button>)}
   </div>
  </aside>}
  {!fallback&&<button className="pc-globe-pause" aria-label={paused?(en?'Resume globe rotation':'继续地球自转'):(en?'Pause globe rotation':'暂停地球自转')} onClick={onTogglePause}>{paused?<Play size={17}/>:<Pause size={17}/>}</button>}
  <button className="pc-globe-home" aria-label={en?'Reset globe view':'恢复地球视角'} onClick={()=>{setSelected('');onSelectScene?.('');runtime.current?.home();}}><Focus size={17}/></button>
 </section>;
}
