import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {SceneModelView} from '../src/sceneModelView.ts';

function createSyntheticTurbineModel() {
  const root = new THREE.Group();
  root.name = 'instance:test-turbine-1';
  root.userData.sceneModelInstanceId = 'test-turbine-1';

  // Tower (height 0 ~ 80)
  const towerGeo = new THREE.CylinderGeometry(2, 3, 80, 8);
  const towerMat = new THREE.MeshBasicMaterial({color: 0xcccccc});
  const towerMesh = new THREE.Mesh(towerGeo, towerMat);
  towerMesh.name = 'Tower_Section';
  towerMesh.position.set(0, 40, 0);
  root.add(towerMesh);

  // Nacelle Shell (height 80 ~ 86, x: -3~3, z: -5~5)
  const shellGeo = new THREE.BoxGeometry(6, 6, 12);
  const shellMat = new THREE.MeshBasicMaterial({color: 0xffffff});
  const shellMesh = new THREE.Mesh(shellGeo, shellMat);
  shellMesh.name = 'Nacelle_Cover_Shell';
  shellMesh.position.set(0, 83, 0);
  root.add(shellMesh);

  // Rotor & Blades (hub at z: 6, y: 83)
  const rotorGeo = new THREE.SphereGeometry(2, 8, 8);
  const rotorMat = new THREE.MeshBasicMaterial({color: 0x999999});
  const rotorMesh = new THREE.Mesh(rotorGeo, rotorMat);
  rotorMesh.name = 'Rotor_Hub_Blade';
  rotorMesh.position.set(0, 83, 6);
  root.add(rotorMesh);

  // Internal 1: Generator
  const genGeo = new THREE.CylinderGeometry(1.5, 1.5, 3, 8);
  const genMat = new THREE.MeshBasicMaterial({color: 0x336699});
  const genMesh = new THREE.Mesh(genGeo, genMat);
  genMesh.name = 'Internal_Generator';
  genMesh.position.set(-1, 83, -2);
  root.add(genMesh);

  // Internal 2: Gearbox
  const gearGeo = new THREE.BoxGeometry(2, 2, 2.5);
  const gearMat = new THREE.MeshBasicMaterial({color: 0x996633});
  const gearMesh = new THREE.Mesh(gearGeo, gearMat);
  gearMesh.name = 'Internal_Gearbox';
  gearMesh.position.set(1, 83, 2);
  root.add(gearMesh);

  root.updateMatrixWorld(true);

  const version = {
    modelVersionId: 'detailed-v1',
    contentRevision: 'rev-det-1',
    sha256: 'sha-synthetic-detailed-model',
    calibration: {state: 'verified'}
  };

  return {root, version, towerMesh, shellMesh, rotorMesh, genMesh, gearMesh};
}

test('Generic Bounding-Box Heuristic dispersion correctly lifts shell, pushes rotor, disperses internals, and locks tower', () => {
  const {root, version, towerMesh, shellMesh, rotorMesh, genMesh, gearMesh} = createSyntheticTurbineModel();

  const initialTowerPos = towerMesh.position.clone();
  const initialShellPos = shellMesh.position.clone();
  const initialRotorPos = rotorMesh.position.clone();
  const initialGenPos = genMesh.position.clone();
  const initialGearPos = gearMesh.position.clone();

  const request = {
    instanceId: 'test-turbine-1',
    modelVersionId: 'detailed-v1',
    contentRevision: 'rev-det-1',
    sha256: 'sha-synthetic-detailed-model',
    mode: 'exploded'
  };

  const view = SceneModelView.create(root, version, request);
  assert.ok(view, 'SceneModelView should be successfully created for detailed model with internals');

  // 1. Tower must remain strictly fixed
  assert.deepEqual(towerMesh.position.toArray(), initialTowerPos.toArray(), 'Tower must not move during explosion');

  // 2. Shell must be lifted upwards (+Y)
  assert.ok(shellMesh.position.y > initialShellPos.y + 5, 'Shell should lift upward');

  // 3. Rotor must be pushed forward (+Z)
  assert.ok(rotorMesh.position.z > initialRotorPos.z + 5, 'Rotor should push forward along Z');

  // 4. Internals must disperse radially away from nacelle center
  assert.notDeepEqual(genMesh.position.toArray(), initialGenPos.toArray(), 'Generator must move');
  assert.notDeepEqual(gearMesh.position.toArray(), initialGearPos.toArray(), 'Gearbox must move');

  // 5. Test clean disposal and complete restoration of initial state
  view.dispose();
  assert.deepEqual(towerMesh.position.toArray(), initialTowerPos.toArray());
  assert.deepEqual(shellMesh.position.toArray(), initialShellPos.toArray());
  assert.deepEqual(rotorMesh.position.toArray(), initialRotorPos.toArray());
  assert.deepEqual(genMesh.position.toArray(), initialGenPos.toArray());
  assert.deepEqual(gearMesh.position.toArray(), initialGearPos.toArray());
});

test('Generic X-Ray mode turns shell transparent without altering internal components', () => {
  const {root, version, shellMesh, genMesh} = createSyntheticTurbineModel();
  const origShellMat = shellMesh.material;
  const origGenMat = genMesh.material;

  const request = {
    instanceId: 'test-turbine-1',
    modelVersionId: 'detailed-v1',
    contentRevision: 'rev-det-1',
    sha256: 'sha-synthetic-detailed-model',
    mode: 'xray'
  };

  const view = SceneModelView.create(root, version, request);
  assert.ok(view);

  assert.notEqual(shellMesh.material, origShellMat);
  assert.equal(shellMesh.material.transparent, true);
  assert.equal(shellMesh.material.opacity, 0.14);
  assert.equal(genMesh.material, origGenMat);

  view.dispose();
  assert.equal(shellMesh.material, origShellMat);
});

test('Appearance-only models without internal components reject explosion and xray', () => {
  const root = new THREE.Group();
  root.name = 'instance:test-exterior-1';
  root.userData.sceneModelInstanceId = 'test-exterior-1';

  const tower = new THREE.Mesh(new THREE.CylinderGeometry(2, 3, 80, 8), new THREE.MeshBasicMaterial());
  tower.name = 'tower';
  root.add(tower);

  const shell = new THREE.Mesh(new THREE.BoxGeometry(6, 6, 12), new THREE.MeshBasicMaterial());
  shell.name = 'nacelle_shell';
  root.add(shell);

  root.updateMatrixWorld(true);

  const version = {
    modelVersionId: 'appearance-v1',
    contentRevision: 'rev-app-1',
    sha256: 'sha-synthetic-appearance-model',
    calibration: {state: 'verified'}
  };

  const req = {
    instanceId: 'test-exterior-1',
    modelVersionId: 'appearance-v1',
    contentRevision: 'rev-app-1',
    sha256: 'sha-synthetic-appearance-model',
    mode: 'exploded'
  };

  assert.equal(SceneModelView.create(root, version, req), null, 'Exterior-only model without internals must return null');
});
