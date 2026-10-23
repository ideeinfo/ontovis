import { useEffect, useRef, useState } from 'react';
import { Box, Focus, Maximize, ZoomIn, ZoomOut } from 'lucide-react';
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import type { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { ApiError, cancelled, failureMessage, type WorkbenchApi } from './api';
import { IconBtn } from './Primitives';
import { usePreferences } from './Preferences';
import { bindingNeedsReview, modelLocation, modelNavigation } from './modelLocation';
import { createSceneControls } from './sceneControls';
import type { ModelView, ObjectView } from './types';

type Controls = {fit:() => void; locate:() => void; zoom:(factor:number) => void};
export function ModelViewport({api, active, detail, model, modelVersionId, onModel, onSelect, focusSignal}: {
  api:WorkbenchApi; active:boolean; detail:ObjectView | null; model:ModelView | null;
  onModel:(value:ModelView | null) => void; onSelect:(uid:string) => void;
  focusSignal:number;
  modelVersionId:string|null;
}) {
  const {t, locale, resolved} = usePreferences();
  const mount = useRef<HTMLDivElement>(null);
  const controls = useRef<Controls | null>(null);
  const current = useRef({detail, model, resolved, onSelect}); current.current = {detail, model, resolved, onSelect};
  const update = useRef<() => void>(() => {});
  const [reading, setReading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!active || !mount.current) return;
    const abort = new AbortController(); const element = mount.current;
    const epoch=api.epoch,revision=api.revision;
    let renderer:THREE.WebGLRenderer | null = null, scene:THREE.Scene | null = null;
    let orbit:OrbitControls | null = null, observer:ResizeObserver | null = null, frame = 0;
    let sceneControls:ReturnType<typeof createSceneControls> | null = null;
    let disposed = false;
    const stale=()=>disposed || abort.signal.aborted || api.epoch!==epoch || api.revision!==revision;
    onModel(null); setReading(true); setError(null);
    const disposeObject = (object:THREE.Object3D) => object.traverse(node => {
      if (node instanceof THREE.Mesh || node instanceof THREE.LineSegments) {
        node.geometry.dispose();
        const materials = Array.isArray(node.material) ? node.material : [node.material];
        for (const material of materials) {
          for (const value of Object.values(material)) if (value instanceof THREE.Texture) value.dispose();
          material.dispose();
        }
      }
    });
    async function start() {
      const metadata = await api.request<ModelView>('/api/workbench/model', modelVersionId ? {modelVersionId} : {}, abort.signal);
      const reference = modelVersionId ? {modelVersionId,expectedModelRevision:metadata.modelRevision,expectedViewRevision:metadata.viewRevision} : {};
      const blob = await api.request<Blob>('/api/workbench/model/content', {...reference,expectedModelSha256:metadata.sha256}, abort.signal, 'model');
      const bytes = await blob.arrayBuffer();
      const sha = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))).map(v => v.toString(16).padStart(2,'0')).join('');
      if (stale()) return;
      if (sha !== metadata.sha256) throw new ApiError(409, 'MODEL_CHANGED');
      const gltf = await new GLTFLoader().parseAsync(bytes, '');
      if (stale()) {disposeObject(gltf.scene); return;}
      scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(42, 1, .05, 3000);
      renderer = new THREE.WebGLRenderer({antialias:true, powerPreference:'high-performance'});
      renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      renderer.domElement.setAttribute('aria-label', t('modelView')); renderer.domElement.setAttribute('role','img');
      element.append(renderer.domElement);
      const root = gltf.scene;
      const keys = new Map(metadata.components?.flatMap(row=>row.nodeIndices.map(index=>[index,row.componentKey] as const)) || []);
      root.traverse(node=>{
        let source:THREE.Object3D|null=node;
        while(source) {
          const index=gltf.parser.associations.get(source)?.nodes;
          if(index!==undefined && keys.has(index)){node.userData.ontoVisKey=keys.get(index);break;}
          source=source.parent;
        }
      });
      const materials = new Map<string, THREE.Material>();
      root.traverse(node => {
        if (!(node instanceof THREE.Mesh)) return;
        const copy = (material:THREE.Material) => {
          const key = `${node.userData.ontoVisKey || node.userData.component}:${material.uuid}`;
          if (!materials.has(key)) materials.set(key, material.clone());
          return materials.get(key)!;
        };
        node.material = Array.isArray(node.material) ? node.material.map(copy) : copy(node.material);
      });
      const proxy = new THREE.Group();
      for (const binding of metadata.bindings.filter(row => row.geometryQuality === 'proxy_schematic')) {
        const bounds = new THREE.Box3(new THREE.Vector3(...binding.bounds[0]), new THREE.Vector3(...binding.bounds[1]));
        const size = bounds.getSize(new THREE.Vector3());
        const mesh = new THREE.Mesh(new THREE.BoxGeometry(size.x,size.y,size.z), new THREE.MeshStandardMaterial({color:0x718275,roughness:.75}));
        mesh.position.copy(bounds.getCenter(new THREE.Vector3())); mesh.userData.component = binding.componentKey;mesh.userData.ontoVisKey=binding.componentKey;
        proxy.add(mesh);
      }
      root.add(proxy); scene.add(root);
      const light = new THREE.HemisphereLight(0xffffff, 0x596d61, 2.5); scene.add(light);
      const sun = new THREE.DirectionalLight(0xfff0d8, 3); sun.position.set(40,140,70); scene.add(sun);
      sceneControls = createSceneControls(camera, renderer.domElement); orbit = sceneControls.orbit;
      orbit.enableDamping = false; orbit.maxDistance = 700;
      const whole = new THREE.Box3().setFromObject(root);
      let tween:{start:number; from:THREE.Vector3; to:THREE.Vector3; targetFrom:THREE.Vector3; targetTo:THREE.Vector3} | null = null;
      const render = () => {
        frame = 0; if (disposed || !renderer || !scene || !orbit) return;
        if (tween) {
          const p = Math.min(1, (performance.now() - tween.start) / 900), ease = p*p*(3-2*p);
          camera.position.lerpVectors(tween.from, tween.to, ease); orbit.target.lerpVectors(tween.targetFrom,tween.targetTo,ease); orbit.update();
          if (p >= 1) tween = null;
        }
        renderer.render(scene,camera); if (tween) request();
      };
      const request = () => {if (!frame && !disposed) frame = requestAnimationFrame(render);};
      const fit = (bounds:THREE.Box3, animated = true, direction = new THREE.Vector3(.9,.38,1.5)) => {
        if (!orbit) return;
        const center = bounds.getCenter(new THREE.Vector3()), size = bounds.getSize(new THREE.Vector3());
        const distance = Math.max(size.length() / (2*Math.tan(THREE.MathUtils.degToRad(camera.fov/2))), 3) * 1.25;
        const position = center.clone().add(direction.clone().normalize().multiplyScalar(distance));
        if (animated && !matchMedia('(prefers-reduced-motion: reduce)').matches) tween = {start:performance.now(),from:camera.position.clone(),to:position,targetFrom:orbit.target.clone(),targetTo:center};
        else {tween=null; camera.position.copy(position); orbit.target.copy(center); orbit.update();}
        request();
      };
      const highlight = new THREE.Group(); scene.add(highlight);
      let lastSelection = '';
      update.current = () => {
        if (!scene || !orbit) return;
        const state = current.current, location = modelLocation(state.detail, metadata);
        // Clear stale highlights while loading without sending the camera back to the whole model.
        if (!state.detail && tween) {tween = null; lastSelection = '';}
        const destination = modelNavigation(state.detail, metadata, lastSelection);
        const css = getComputedStyle(document.documentElement);
        scene.background = new THREE.Color(css.getPropertyValue('--sceneBackground').trim());
        disposeObject(highlight); highlight.clear();
        const selectedKey = location?.binding.componentKey;
        root.traverse(node => {
          if (!(node instanceof THREE.Mesh)) return;
          const selected = metadata.components ? node.userData.ontoVisKey===selectedKey && !!selectedKey : node.userData.component === selectedKey || selectedKey === 'CN' && node.userData.component === 'controller';
          const mats = Array.isArray(node.material) ? node.material : [node.material];
          for (const material of mats) {
            if (material instanceof THREE.MeshStandardMaterial) {
              material.emissive.set(selected ? css.getPropertyValue('--primary').trim() : 0x000000);
              material.emissiveIntensity = selected ? .25 : 0;
              // Only enclosing shells fade; internal meshes retain their depth.
              const shell = selectedKey && ['tower','nacelle','rotor_cover'].includes(node.userData.component);
              material.transparent = !!shell; material.opacity = shell ? .2 : 1; material.depthWrite = !shell;
              material.needsUpdate = true;
            }
          }
        });
        if (location) {
          const box = new THREE.Box3(new THREE.Vector3(...location.binding.bounds[0]), new THREE.Vector3(...location.binding.bounds[1]));
          const helper = new THREE.Box3Helper(box, new THREE.Color(css.getPropertyValue('--primary').trim())); highlight.add(helper);
        }
        if (destination) {
          if (destination.bounds) {
            const box = new THREE.Box3(new THREE.Vector3(...destination.bounds[0]), new THREE.Vector3(...destination.bounds[1]));
            fit(box, true, new THREE.Vector3(box.getCenter(new THREE.Vector3()).x<0 ? -1 : 1, .35, -1.5));
          } else fit(whole);
          lastSelection = destination.entityUid;
        }
        request();
      };
      controls.current = {fit:() => fit(whole), locate:() => {const l = modelLocation(current.current.detail,metadata); if (l) fit(new THREE.Box3(new THREE.Vector3(...l.binding.bounds[0]),new THREE.Vector3(...l.binding.bounds[1])), true, new THREE.Vector3(l.binding.bounds[0][0]+l.binding.bounds[1][0]<0 ? -1 : 1,.35,-1.5));},
        zoom:factor => {if (!orbit) return; tween=null; camera.position.sub(orbit.target).multiplyScalar(factor).add(orbit.target); request();}};
      orbit.addEventListener('change', request); orbit.addEventListener('start', () => {tween=null;});
      observer = new ResizeObserver(() => {
        if (!renderer) return; const {width,height} = element.getBoundingClientRect();
        camera.aspect = Math.max(1,width)/Math.max(1,height); camera.updateProjectionMatrix(); renderer.setSize(width,height); request();
      }); observer.observe(element);
      let down:{x:number;y:number} | null = null;
      renderer.domElement.addEventListener('pointerdown', event => {down={x:event.clientX,y:event.clientY};});
      renderer.domElement.addEventListener('pointerup', event => {
        if (!down || Math.hypot(down.x-event.clientX,down.y-event.clientY)>5) return;
        const rect = element.getBoundingClientRect(); const ray = new THREE.Raycaster();
        ray.setFromCamera(new THREE.Vector2((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1),camera);
        const hit = ray.intersectObject(root,true).find(item => item.object instanceof THREE.Mesh && item.object.visible);
        const key = metadata.components ? hit?.object.userData.ontoVisKey : hit?.object.userData.component;
        const binding = metadata.bindings.find(item => item.componentKey === key || !metadata.components && item.componentKey === 'CN' && key === 'controller');
        if (binding) current.current.onSelect(binding.entityUid);
      });
      fit(whole,false); onModel(metadata); update.current(); setReading(false);
    }
    void start().catch(value => {if (!disposed && !cancelled(value)) {setError(value); setReading(false); onModel(null);}});
    return () => {
      disposed=true; abort.abort(); cancelAnimationFrame(frame); observer?.disconnect(); sceneControls?.dispose(); orbit=null;
      if (scene) {disposeObject(scene); scene.clear();}
      if (renderer) {renderer.dispose(); renderer.forceContextLoss(); renderer.domElement.remove();}
      controls.current=null; update.current=() => {};
    };
  }, [active, attempt, modelVersionId]);
  useEffect(() => {update.current(); mount.current?.querySelector('canvas')?.setAttribute('aria-label', t('modelView'));}, [detail, resolved, locale]);
  useEffect(() => {controls.current?.locate();}, [focusSignal]);
  const location = modelLocation(detail, model);
  return <section className="cw-panel cw-scene"><header><Box size={15}/><strong>{t('modelView')}</strong><span className="cw-grow"/><span className="cw-caption">{model ? model.displayName || t('modelName') : ''}</span></header>
    <div className="cw-model-stage"><div className="cw-canvas" ref={mount}/>
      {(!active || reading || !!error) && <div className="cw-model-state" role={error ? 'alert' : 'status'}>{!active ? t('loginPrompt') : reading ? t('loading') : failureMessage(error,locale)}{error ? <button className="ov-btn" onClick={() => setAttempt(v => v+1)}>{t('retry')}</button> : null}</div>}
      {model && <div className="cw-scene-tools"><IconBtn label={t('zoomIn')} onClick={() => controls.current?.zoom(.8)}><ZoomIn size={16}/></IconBtn><IconBtn label={t('zoomOut')} onClick={() => controls.current?.zoom(1.25)}><ZoomOut size={16}/></IconBtn><IconBtn label={t('showAll')} onClick={() => controls.current?.fit()}><Maximize size={16}/></IconBtn><IconBtn label={t('locate')} disabled={!location} onClick={() => controls.current?.locate()}><Focus size={16}/></IconBtn></div>}
    </div><footer className="cw-panel-foot"><span>{detail?.item.displayName || t('select')}</span><span className="cw-grow"/><span>{bindingNeedsReview(detail,model) ? t('bindingChanged') : location ? location.mode === 'ancestor' ? t('ancestor') : location.binding.geometryQuality === 'proxy_schematic' ? t('proxy') : t('candidate') : !!model && detail?.item.entityUid === model.rootEntityUid ? t('modelReady') : t('unlocated')}</span></footer>
  </section>;
}
