import * as THREE from 'three';
import type {SceneOpen,SceneModelInstance,Bounds3} from './sceneTypes';
import type {ProjectModelVersion} from './resourceTypes';
import type {EquipmentRecord} from './equipmentApi';
import {calibrationMatrix} from './sceneResourceCache.ts';
import {toDisplay,trueHeadingToThreeYaw} from './sceneTransforms.ts';
import {componentFocusKey,type ComponentFocusRequest} from './sceneComponentFocus.ts';

/** A visual preview from the already-read fixed mapping. Server authority is checked in parallel. */
export function cockpitQuickFocus(opened:SceneOpen|null,instance:SceneModelInstance|undefined,model:ProjectModelVersion|null,record:EquipmentRecord|undefined,uid:string,token:number,isolate:boolean,expectedRevision?:string):ComponentFocusRequest|undefined{
 if(!opened||opened.sceneRevision!==opened.headRevision||!instance?.rootBinding||!model||!record||model.state!=='ready'||!model.canPlace)return;
 const root=instance.rootBinding.objectRef,refs=opened.resourceRefs.filter(ref=>ref.modelVersionId===instance.modelVersionId);
 if(opened.snapshot.coordinateFrame.mode==='projected_site'&&!model.canPlaceGeographic)return;
 const children=record.children.filter(item=>item.entityUid===uid);
 if(root.entityUid!==record.item.entityUid||root.entityUid!==record.context.rootEntityUid||root.projectCode!==record.context.projectCode||children.length!==1||expectedRevision&&children[0].entityRevision!==expectedRevision)return;
 if(refs.length!==1||model.modelVersionId!==refs[0].modelVersionId||model.sha256!==refs[0].sha256||model.contentRevision!==refs[0].contentRevision)return;
 const bindings=instance.componentBindings.filter(binding=>binding.objectRef.entityUid===uid&&binding.objectRef.projectCode===root.projectCode&&binding.objectRef.ontobaseConnectionId===root.ontobaseConnectionId);
 if(bindings.length!==1||!bindings[0].componentKeys.length)return;
 const keys=bindings[0].componentKeys;
 if(keys.some(key=>instance.componentBindings.filter(binding=>binding.componentKeys.includes(key)).length!==1))return;
 try{
  const frame=opened.snapshot.coordinateFrame,placement=instance.placement,geo=placement.position.mode==='geographic'?placement.position:null;
  const transform=new THREE.Matrix4().makeRotationY(trueHeadingToThreeYaw(frame,placement.headingDeg,geo?.longitude,geo?.latitude));
  transform.setPosition(new THREE.Vector3(...toDisplay(frame,placement.position,placement.height)));transform.multiply(calibrationMatrix(model));
  const world=new THREE.Box3();
  for(const key of keys){const parts=model.components.filter(part=>part.componentKey===key);if(parts.length!==1)return;
   const box=parts[0].bounds;if(!componentFocusKey({token,instanceId:instance.sceneModelInstanceId,bounds:box}))return;
   world.union(new THREE.Box3(new THREE.Vector3(...box[0]),new THREE.Vector3(...box[1])).applyMatrix4(transform));
  }
  const result={token,instanceId:instance.sceneModelInstanceId,componentKeys:[...keys],bounds:[world.min.toArray(),world.max.toArray()] as Bounds3,isolate};
  return componentFocusKey(result)?result:undefined;
 }catch{return;}
}
