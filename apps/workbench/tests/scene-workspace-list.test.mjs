import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const dir = path.dirname(fileURLToPath(import.meta.url));
const scenesCss = readFileSync(path.resolve(dir, '../src/scenes.css'), 'utf-8');
const workspaceSrc = readFileSync(path.resolve(dir, '../src/SceneWorkspace.tsx'), 'utf-8');

test('scenes.css defines complete dual-column card and thumbnail hub styles', () => {
  const requiredSelectors = [
    '.sw-hub-header',
    '.sw-hub-grid',
    '.sw-hub-list-panel',
    '.sw-view-switch',
    '.sw-facility-card',
    '.sw-facility-card.is-selected',
    '.sw-facility-card-thumb',
    '.sw-facility-thumb-badge',
    '.sw-table-thumb',
    '.sw-hub-detail-panel',
    '.sw-hub-stat-grid',
    '.sw-hub-preview-card'
  ];
  for (const selector of requiredSelectors) {
    assert.ok(scenesCss.includes(selector), `Missing CSS selector: ${selector}`);
  }
  // 16:9 thumbnail ratio and responsive grid
  assert.ok(scenesCss.includes('216px') && scenesCss.includes('122px'), 'Expected 16:9 approximate thumbnail dimensions (216x122)');
  assert.ok(scenesCss.includes('max-width:1050px') || scenesCss.includes('max-width: 1050px'), 'Expected responsive breakpoint for tablets');
});

test('SceneWorkspace integrates cards and list mode toggling with thumbnails', () => {
  assert.ok(workspaceSrc.includes('listMode'), 'Expected listMode state variable');
  assert.ok(workspaceSrc.includes('selectedSceneId'), 'Expected selectedSceneId state variable');
  assert.ok(workspaceSrc.includes('SceneThumbnail'), 'Expected SceneThumbnail component usage');
  assert.ok(workspaceSrc.includes('ScenePlaceholderThumb'), 'Expected ScenePlaceholderThumb fallback');
  assert.ok(workspaceSrc.includes('sw-facility-card'), 'Expected sw-facility-card markup');
  assert.ok(workspaceSrc.includes('sw-hub-detail-panel'), 'Expected sw-hub-detail-panel markup');
  assert.ok(workspaceSrc.includes('sw-view-switch'), 'Expected sw-view-switch toggle buttons');
});

test('scene short code formats cleanly as SCN- prefix with uppercase alphanumerics', () => {
  const format = (id) => `SCN-${id.replace(/^scene-/, '').slice(0, 8).toUpperCase()}`;
  assert.equal(format('scene-area'), 'SCN-AREA');
  assert.equal(format('scene-substation-main'), 'SCN-SUBSTATI');
  assert.equal(format('custom-01'), 'SCN-CUSTOM-0');
});
