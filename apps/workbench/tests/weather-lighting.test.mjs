import test from 'node:test';
import assert from 'node:assert/strict';
import {weatherEnvironment} from '../src/weatherEnvironment.ts';
import {presentationEnvironment} from '../src/cockpitDisplayState.ts';

test('weatherEnvironment provides soft fill lighting and enhanced hemisphere diffuse in overcast/rainy conditions',()=>{
  const rainForecast = {
    contact: 'ops@example.com',
    sceneId: 'test-scene',
    retrievedAt: '2026-11-01T07:00:00Z',
    forecast: {
      updatedAt: '2026-11-01T07:00:00Z',
      temperatureC: 12,
      windSpeedMps: 7,
      windDirectionDeg: 180,
      condition: 'rain',
      symbol: 'rain',
      cloudPercent: 95
    }
  };

  const env = weatherEnvironment(null, rainForecast);
  assert.equal(env.lighting.sun.enabled, true, 'Sun directional light should remain enabled as soft diffuse sky light');
  assert.equal(env.lighting.sun.intensity, 1.15, 'Sun intensity should be soft diffuse 1.15');
  assert.equal(env.lighting.sun.color, '#dce6f2', 'Sun color should be diffuse cool white');
  assert.equal(env.lighting.hemisphereIntensity, 1.65, 'Hemisphere light should be enhanced to 1.65 for ambient diffuse');
  assert.equal(env.lighting.environment.intensity, 1.0, 'Environment map intensity should be boosted to 1.0');
});

test('presentationEnvironment preserves bright turbine visibility when user selects rain/snow/fog demo weather',()=>{
  const rainDemo = presentationEnvironment(null, null, 'scene', 'rain');
  assert.ok(rainDemo);
  assert.equal(rainDemo.value.lighting.sun.enabled, true, 'Sun light should remain enabled in demo rain');
  assert.equal(rainDemo.value.lighting.sun.intensity, 1.15);
  assert.equal(rainDemo.value.lighting.hemisphereIntensity, 1.65);
  assert.equal(rainDemo.value.lighting.environment.intensity, 1.0);

  const fogDemo = presentationEnvironment(null, null, 'scene', 'fog');
  assert.ok(fogDemo);
  assert.equal(fogDemo.value.lighting.sun.enabled, false, 'Sun light disabled in dense fog per contrast spec');
  assert.equal(fogDemo.value.lighting.hemisphereIntensity, 1.65, 'Hemisphere light boosted in fog for fill illumination');
  assert.equal(fogDemo.value.lighting.environment.intensity, 1.0);

  const clearDemo = presentationEnvironment(null, null, 'scene', 'clear');
  assert.ok(clearDemo);
  assert.equal(clearDemo.value.lighting.sun.enabled, true);
  assert.equal(clearDemo.value.lighting.hemisphereIntensity, 1);
});
