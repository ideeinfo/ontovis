/** Explicit local demonstration; these values never represent equipment telemetry. */
export const MOTION_SOURCE='ontovis-local-motion-demo-v1';
export const MOTION_MODEL_SHA='078bbc161a9c9c8cbe0bbc872ca825b6a222d4d4c22f8c16c7889908a97a5806';
export const MOTION_MERGED_SHA='fb7963a94988d67a16c5ef08c024b200881df53d4f4e2e2cde27661861d9d9b1';
export function motionProfile(sha:string){return sha===MOTION_MODEL_SHA?{nodes:20,movingEnd:14,rotorStart:15,rotorEnd:19}:sha===MOTION_MERGED_SHA?{nodes:184,movingEnd:142,rotorStart:143,rotorEnd:175}:null;}
export type MotionQuality='good'|'bad'|'stale'|'offline';
export interface MotionSample {
 sourceId:typeof MOTION_SOURCE;epoch:string;seq:number;issuedAt:number;validUntil:number;
 rpm:number;yawDeg:number;rpmUnit:'rpm';yawUnit:'deg';quality:MotionQuality;
}
export interface MotionRequest {
 instanceId:string;modelVersionId:string;contentRevision:string;sha256:string;epoch:string;
 playing:boolean;axes:boolean;sample:MotionSample;
}
export type MotionStatus='ready'|'unavailable'|'loading';
export function yawDelta(current:number,target:number){return ((target-current+540)%360+360)%360-180;}
export class SimulatedMotionClock {
 private seq=-1;private last:number|null=null;private sample:MotionSample|null=null;
 yaw=0;rotor=0;
 readonly epoch:string;
 constructor(epoch:string){this.epoch=epoch;}
 accept(sample:MotionSample,now:number){
  if(sample.sourceId!==MOTION_SOURCE||sample.epoch!==this.epoch||!Number.isSafeInteger(sample.seq)||sample.seq<=this.seq)return false;
  this.seq=sample.seq;
  const valid=sample.quality==='good'&&sample.rpmUnit==='rpm'&&sample.yawUnit==='deg'
   &&Number.isFinite(sample.rpm)&&sample.rpm>=0&&sample.rpm<=20&&Number.isFinite(sample.yawDeg)&&sample.yawDeg>=0&&sample.yawDeg<360
   &&Number.isFinite(sample.issuedAt)&&sample.issuedAt<=now&&now-sample.issuedAt<=2500
   &&Number.isFinite(sample.validUntil)&&sample.validUntil>now&&sample.validUntil<=sample.issuedAt+2500;
  if(!valid){this.sample=null;this.last=null;return false;}
  // Resuming after a gap starts a fresh integral; never catch up missed rotations.
  if(!this.sample||this.sample.validUntil<=now)this.last=null;
  this.sample=sample;return true;
 }
 suspend(){this.last=null;}
 step(now:number,playing:boolean){
  const sample=this.sample;
  if(!playing||!sample||now>=sample.validUntil){this.last=null;return false;}
  const dt=this.last===null?0:Math.max(0,Math.min(.1,(now-this.last)/1000));this.last=now;
  const delta=yawDelta(this.yaw,sample.yawDeg);
  this.yaw=(this.yaw+Math.sign(delta)*Math.min(Math.abs(delta),30*dt)+360)%360;
  this.rotor=(this.rotor+sample.rpm*Math.PI/30*dt)%(2*Math.PI);
  return sample.rpm>0||Math.abs(yawDelta(this.yaw,sample.yawDeg))>.00001;
 }
}
