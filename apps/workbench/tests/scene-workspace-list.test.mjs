import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const dir = path.dirname(fileURLToPath(import.meta.url));
const scenesCss = readFileSync(path.resolve(dir, '../src/scenes.css'), 'utf-8');
const workspaceSrc = readFileSync(path.resolve(dir, '../src/SceneWorkspace.tsx'), 'utf-8');

test('scenes.css defines complete dual-column card, thumbnail hub and centered layout styles', () => {
  const requiredSelectors = [
    '.sw-hub-header',
    '.sw-hub-header-inner',
    '.sw-hub-grid',
    '.sw-hub-list-panel',
    '.sw-view-switch',
    '.sw-facility-card',
    '.sw-facility-card.is-selected',
    '.sw-facility-card-thumb',
    '.sw-facility-card-metrics',
    '.sw-table-thumb',
    '.sw-hub-detail-panel',
    '.sw-hub-stat-grid',
    '.sw-hub-preview-card'
  ];
  for (const selector of requiredSelectors) {
    assert.ok(scenesCss.includes(selector), `Missing CSS selector: ${selector}`);
  }
  // Centering styles
  assert.ok(scenesCss.includes('.sw-hub-header-inner{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;max-width:1440px;margin:0 auto;width:100%}'), 'Expected centered header-inner container');
  assert.ok(scenesCss.includes('.sw-hub-grid{display:grid;grid-template-columns:minmax(0,1.62fr) minmax(320px,0.92fr);gap:18px;align-items:start;max-width:1440px;margin:0 auto}'), 'Expected centered hub-grid');
  // Two-column metrics
  assert.ok(scenesCss.includes('.sw-facility-card-metrics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))'), 'Expected 2-column card metrics grid');
  assert.ok(scenesCss.includes('.sw-hub-stat-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))'), 'Expected 2-column detail stat grid');
  // 16:9 thumbnail ratio and responsive grid
  assert.ok(scenesCss.includes('216px') && scenesCss.includes('122px'), 'Expected 16:9 approximate thumbnail dimensions (216x122)');
  assert.ok(scenesCss.includes('max-width:1050px') || scenesCss.includes('max-width: 1050px'), 'Expected responsive breakpoint for tablets');
});

test('SceneWorkspace integrates cards and list mode toggling without verbose codes', () => {
  assert.ok(workspaceSrc.includes('listMode'), 'Expected listMode state variable');
  assert.ok(workspaceSrc.includes('selectedSceneId'), 'Expected selectedSceneId state variable');
  assert.ok(workspaceSrc.includes('SceneThumbnail'), 'Expected SceneThumbnail component usage');
  assert.ok(workspaceSrc.includes('ScenePlaceholderThumb'), 'Expected ScenePlaceholderThumb fallback');
  assert.ok(workspaceSrc.includes('sw-facility-card'), 'Expected sw-facility-card markup');
  assert.ok(workspaceSrc.includes('sw-hub-header-inner'), 'Expected sw-hub-header-inner markup');
  assert.ok(workspaceSrc.includes('sw-hub-detail-panel'), 'Expected sw-hub-detail-panel markup');
  assert.ok(workspaceSrc.includes('sw-view-switch'), 'Expected sw-view-switch toggle buttons');
  // Confirm verbose codes and badges are removed from template
  assert.ok(!workspaceSrc.includes('sceneShortCode'), 'Should not contain sceneShortCode helper');
  assert.ok(!workspaceSrc.includes('sw-facility-thumb-badge'), 'Should not contain thumb badge overlay');
  assert.ok(!workspaceSrc.includes('SCN-'), 'Should not contain hardcoded SCN prefix');
});
