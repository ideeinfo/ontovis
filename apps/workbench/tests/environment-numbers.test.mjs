import test from 'node:test';import assert from 'node:assert/strict';
import {environmentNumbers,environmentNumberValid,environmentNumberRange} from '../src/environmentNumbers.ts';
import {environmentPreset} from '../src/sceneEnvironment.ts';
test('environment controls accept all saved preset values with the existing service ranges',()=>{
 for(const id of ['land-day-v1','offshore-overview-v1','dusk-v1']){
  const e=environmentPreset(id),values={exposure:e.color.exposure,azimuth:e.lighting.sun.azimuthDeg,elevation:e.lighting.sun.elevationDeg,intensity:e.lighting.sun.intensity,ambient:e.lighting.hemisphereIntensity,environment:e.lighting.environment.intensity,near:e.atmosphere.fog.nearM,far:e.atmosphere.fog.farM,radius:e.shadows.radiusM,rough:e.surface.terrainRoughness,repeat:e.surface.textureRepeatM,direction:e.water.travelHeadingDeg,strength:e.water.rippleStrength,length:e.water.wavelengthM,speed:e.water.travelSpeedMps,waterRough:e.water.roughness};
  for(const [key,value] of Object.entries(values))assert.ok(environmentNumberValid(key,value),`${id}:${key}`);
 }
});
test('angles exclude 360 and all controls reject missing/nonfinite/outside values without coercing them',()=>{
 for(const [key,rule] of Object.entries(environmentNumbers)){
  assert.ok(environmentNumberValid(key,rule.min));assert.ok(environmentNumberValid(key,(rule.min+rule.max)/2));
  for(const n of [NaN,Infinity,-Infinity,rule.min-.001,rule.max+.001])assert.equal(environmentNumberValid(key,n),false,`${key}:${n}`);
  assert.equal(environmentNumberValid(key,rule.max),!rule.exclusive);
 }
 assert.equal(environmentNumberRange('azimuth'),'0–<360');assert.equal(environmentNumberRange('speed'),'0–5');
 assert.ok(environmentNumberValid('exposure',1.135));assert.ok(environmentNumberValid('near',0));assert.ok(environmentNumberValid('far',100000));
});
