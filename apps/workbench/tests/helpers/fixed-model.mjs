import {createHash} from 'node:crypto';
import * as THREE from 'three';
import {MOTION_MODEL_SHA,MOTION_MERGED_SHA,MOTION_SOURCE,motionProfile} from '../../src/simulatedMotion.ts';
import {WorkbenchApi} from '../../src/api.ts';
import {SceneResourceCache,cloneModel,modelSourceNode} from '../../src/sceneResourceCache.ts';
const sample=(overrides={})=>({sourceId:MOTION_SOURCE,epoch:'demo',seq:1,issuedAt:0,validUntil:2500,rpm:10,yawDeg:90,rpmUnit:'rpm',yawUnit:'deg',quality:'good',...overrides});
export async function fixture(merged=false,sha=merged?MOTION_MERGED_SHA:MOTION_MODEL_SHA){
 const profile=motionProfile(sha);
 const positions=new Float32Array([0,0,0,1,0,0,0,1,0]),nodes=Array.from({length:profile.nodes},(_,i)=>({name:'untrusted-name-'+i}));
 nodes[0].children=[1,2];nodes[1].children=Array.from({length:12},(_,i)=>i+3);nodes[2].children=[15,16,17,18,19];nodes[2].translation=[0,90,6.67];
 if(merged){nodes[1].children=[...Array.from({length:140},(_,i)=>i+3),...Array.from({length:8},(_,i)=>i+176)];nodes[2].children=Array.from({length:33},(_,i)=>i+143);}
 if(profile.layout==='baked'){nodes[1].children=Array.from({length:profile.nodes-3},(_,i)=>i+3);nodes[2].children=[];nodes[2].translation=[0,0,0];}
 for(let i=3;i<nodes.length;i++)nodes[i].mesh=0;
 const doc={asset:{version:'2.0'},scene:0,scenes:[{nodes:[0]}],nodes,meshes:[{primitives:[{attributes:{POSITION:0}}]}],
  buffers:[{byteLength:positions.byteLength}],bufferViews:[{buffer:0,byteLength:positions.byteLength}],accessors:[{bufferView:0,componentType:5126,type:'VEC3',count:3,min:[0,0,0],max:[1,1,0]}]};
 const raw=new TextEncoder().encode(JSON.stringify(doc)),json=new Uint8Array(Math.ceil(raw.length/4)*4);json.fill(32);json.set(raw);
 const bytes=new ArrayBuffer(28+json.length+positions.byteLength),v=new DataView(bytes);
 [0x46546c67,2,bytes.byteLength,json.length,0x4e4f534a].forEach((x,i)=>v.setUint32(i*4,x,true));new Uint8Array(bytes,20,json.length).set(json);
 v.setUint32(20+json.length,positions.byteLength,true);v.setUint32(24+json.length,0x004e4942,true);new Uint8Array(bytes,28+json.length).set(new Uint8Array(positions.buffer));
 const version={state:'ready',canPlace:true,calibrationState:'verified',modelVersionId:'v1',modelAssetId:'a1',contentRevision:'content:1',sha256:createHash('sha256').update(new Uint8Array(bytes)).digest('hex'),bytes:bytes.byteLength,
  calibration:{state:'verified',unit:'m',axes:'Y_UP_RIGHT_HANDED',basePoint:[0,0,0],forward:[0,0,-1],modelToCalibrated:new THREE.Matrix4().toArray()},components:[],report:{animations:0,externalResourcesFetched:0}};
 const api=new WorkbenchApi();api.session('fixture');const cache=new SceneResourceCache(api,{source:{model:async()=>version,modelContent:async()=>new Blob([bytes])}});
 const resource=await cache.model(version),a=cloneModel(resource,'a'),b=cloneModel(resource,'b');
 // Synthetic geometry exercises the reviewed profile without distributing third-party model bytes.
 const adapted={...version,sha256:sha};const now=performance.now();
 const request={instanceId:'a',modelVersionId:'v1',contentRevision:'content:1',sha256:sha,epoch:'demo',playing:true,axes:true,sample:sample({issuedAt:now,validUntil:now+2500,yawDeg:90,rpm:10})};
 return {cache,resource,a,b,adapted,request,now};
}
export const node=(root,i)=>{let match;root.traverse(n=>{if(modelSourceNode(n)?.index===i)match=n;});return match;};
export const snapshot=root=>{root.updateWorldMatrix(true,true);const rows=[];root.traverse(n=>rows.push({uuid:n.uuid,parent:n.parent?.uuid,position:n.position.toArray(),rotation:n.quaternion.toArray(),scale:n.scale.toArray(),world:n.matrixWorld.toArray()}));return rows;};
