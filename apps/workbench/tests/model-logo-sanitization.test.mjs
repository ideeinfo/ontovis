import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {sanitizeModelLogos} from '../src/sceneResourceCache.ts';

test('sanitizeModelLogos hides TU-22K TerraUrsa logo node and textures',()=>{
  const root = new THREE.Group();
  
  // TU-22K nacelle logo node (supports both raw Static:nacelle:20 and sanitized Staticnacelle20)
  const tu22kLogo = new THREE.Mesh(
    new THREE.BufferGeometry(),
    new THREE.MeshStandardMaterial({name: 'tu22k-mat'})
  );
  tu22kLogo.name = 'Staticnacelle20';
  tu22kLogo.visible = true;
  root.add(tu22kLogo);

  // Mesh with terraursa texture name
  const dummyTex = new THREE.Texture();
  dummyTex.name = 'terraursa-logo-decal';
  const customMesh = new THREE.Mesh(
    new THREE.BufferGeometry(),
    new THREE.MeshStandardMaterial({map: dummyTex})
  );
  customMesh.name = 'Static:custom:1';
  customMesh.visible = true;
  root.add(customMesh);

  // Other real vendor nodes: Vestas, Siemens, MingYang
  const vestasMesh = new THREE.Mesh(
    new THREE.BufferGeometry(),
    new THREE.MeshStandardMaterial({name: 'vestas-nacelle-mat'})
  );
  vestasMesh.name = 'Static:nacelle:00';
  vestasMesh.visible = true;
  root.add(vestasMesh);

  const mingyangMesh = new THREE.Mesh(
    new THREE.BufferGeometry(),
    new THREE.MeshStandardMaterial({name: 'mingyang-blade-mat'})
  );
  mingyangMesh.name = 'Static:blades:01';
  mingyangMesh.visible = true;
  root.add(mingyangMesh);

  // Execute sanitization
  return sanitizeModelLogos(root).then(()=>{
    // 1. TU-22K logo must be hidden
    assert.equal(tu22kLogo.visible, false, 'TU-22K Static:nacelle:20 must be hidden');
    assert.equal(tu22kLogo.material.visible, false, 'TU-22K material must be hidden');
    assert.equal(tu22kLogo.material.opacity, 0, 'TU-22K opacity must be 0');

    // 2. Custom mesh with terraursa texture must be hidden
    assert.equal(customMesh.visible, false, 'Mesh with terraursa texture must be hidden');
    assert.equal(customMesh.material.visible, false, 'Material with terraursa texture must be hidden');

    // 3. Real brand and vendor meshes must be strictly preserved
    assert.equal(vestasMesh.visible, true, 'Vestas mesh must remain visible');
    assert.equal(vestasMesh.material.visible, true, 'Vestas material must remain visible');
    assert.equal(mingyangMesh.visible, true, 'MingYang mesh must remain visible');
    assert.equal(mingyangMesh.material.visible, true, 'MingYang material must remain visible');
  });
});

test('sanitizeModelLogos safely handles TU-3000 node and leaves non-logo nacelle structures untouched',()=>{
  const root = new THREE.Group();
  
  // Nacelle main shell
  const nacelleShell = new THREE.Mesh(
    new THREE.BufferGeometry(),
    new THREE.MeshStandardMaterial({color: 0xffffff})
  );
  nacelleShell.name = 'Static:nacelle:0';
  nacelleShell.visible = true;
  root.add(nacelleShell);

  // TU-3000 logo decal
  const tu3000Logo = new THREE.Mesh(
    new THREE.BufferGeometry(),
    new THREE.MeshStandardMaterial({name: 'tu3000-decal'})
  );
  tu3000Logo.name = 'Static:nacelle:10';
  tu3000Logo.visible = true;
  root.add(tu3000Logo);

  return sanitizeModelLogos(root).then(()=>{
    // Nacelle main body remains visible
    assert.equal(nacelleShell.visible, true, 'Nacelle shell must remain visible');
    assert.equal(nacelleShell.material.visible, true, 'Nacelle shell material must remain visible');
  });
});
