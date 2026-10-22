"""Real GIS -> HTTP -> SQLite scene checks with synthetic project authority.

GeoTIFF processing, projection, fixed-mesh sampling, GLB validation and geometry
checks run in their actual subprocesses. No production service or data is used.
Missing GIS dependencies fail this suite rather than skipping acceptance.
"""
import base64
import copy
from http.server import ThreadingHTTPServer
import json
import math
from pathlib import Path
import sys
import tempfile
from threading import Thread
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

import numpy as np
import rasterio
from rasterio.transform import Affine
from rasterio.warp import transform

from apps.api.session_http import handler_type
from apps.api.workbench_server import WorkbenchSessions
import tests.test_project_model_http as model_http


class SceneSpatialHttpTests(unittest.TestCase):
    # Reuse request helpers without inheriting or importing another TestCase.
    request = model_http.ProjectModelHttpTests.request
    login = model_http.ProjectModelHttpTests.login
    authority = model_http.ProjectModelHttpTests.authority
    listing = model_http.ProjectModelHttpTests.listing
    metadata = model_http.ProjectModelHttpTests.metadata
    upload = model_http.ProjectModelHttpTests.upload
    new_version = model_http.ProjectModelHttpTests.new_version
    calibration = model_http.ProjectModelHttpTests.calibration
    calibrate = model_http.ProjectModelHttpTests.calibrate
    expect = model_http.ProjectModelHttpTests.expect

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sessions = WorkbenchSessions('http://127.0.0.1:1234', 'fixture-project', model_http.CONTEXT,
            library_root=self.root / 'private', terrain_python=Path(sys.executable), factory=model_http.SceneAuthority)
        self.addCleanup(self.sessions.terrains.close)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler_type(self.sessions, model_http.ORIGIN, development=True))
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.thread.join)
        self.addCleanup(self.server.shutdown)
        self.admin = self.login('synthetic-spatial-admin')
        self.data = model_http.glb(self.root / 'synthetic.glb').read_bytes()
        self.raw_model = self.new_version()
        status, self.version, _ = self.calibrate(self.calibration(self.raw_model))
        self.assertEqual(status, 200, self.version)
        self.assertTrue(self.version['canPlace'])
        self.terrain_version = None

    def lonlat(self, east=500080, north=3699920):
        longitude, latitude = transform('EPSG:32649', 'EPSG:4326', [east], [north])
        return [longitude[0], latitude[0]]

    def terrain(self, *, hole=False):
        if self.terrain_version is not None:
            return self.terrain_version
        row, column = np.indices((32, 32))
        values = np.asarray(100 + row * .1 + column * .2, dtype='float32')
        if hole: values[14:18, 14:18] = -9999
        source = self.root / 'synthetic-elevation.tif'
        with rasterio.open(source, 'w', driver='GTiff', width=32, height=32, count=1, dtype='float32',
                crs='EPSG:32649', transform=Affine(10, 0, 500000, 0, -10, 3700000), nodata=-9999) as dataset:
            dataset.write(values, 1)
            dataset.update_tags(VERTICAL_DATUM='EGM2008')
        metadata = {'expectedSessionRevision': self.admin['revision'], 'clientRequestId': str(uuid4()),
            'displayName': 'Synthetic regional elevation', 'sourceNote': '32x32 synthetic EPSG:32649 fixture',
            'licenseNote': 'Synthetic test data', 'rightsDeclared': True, 'verticalDatum': 'EGM2008', 'heightUnit': 'm'}
        header = base64.b64encode(json.dumps(metadata).encode()).decode()
        status, item, _ = self.request('/api/workbench/terrains/upload', raw=source.read_bytes(),
            headers={'Content-Type': 'image/tiff', 'X-Terrain-Metadata': header})
        self.assertEqual(status, 202, item)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            status, current, _ = self.request('/api/workbench/terrains/job', {'jobId': item['jobId']})
            self.assertEqual(status, 200, current)
            if current['state'] in ('ready', 'failed', 'cancelled'):
                break
            time.sleep(.02)
        self.assertEqual(current['state'], 'ready', current)
        status, version, _ = self.request('/api/workbench/terrains/version', {'terrainVersionId': current['terrainVersionId']})
        self.assertEqual(status, 200, version)
        self.assertEqual(version['report']['source']['width'], 32)
        self.assertEqual(version['report']['source']['height'], 32)
        self.assertEqual(version['report']['source']['verticalDatum'], 'EGM2008')
        self.terrain_version = version
        return version

    def item(self, *, locked=False):
        return {'sceneModelInstanceId': str(uuid4()), 'displayName': 'Synthetic equipment',
            'modelVersionId': self.version['modelVersionId'],
            'placement': {'position': {'mode': 'local', 'xM': 0, 'zM': 0},
                'height': {'mode': 'local_relative', 'relativeHeightM': 3}, 'headingDeg': 30},
            'visible': True, 'positionLocked': locked, 'rootBinding': None, 'componentBindings': []}

    def save_body(self, scene, snapshot=None, **extra):
        return {'sceneId': scene['sceneId'], 'expectedSceneRevision': scene['sceneRevision'],
            'clientRequestId': str(uuid4()), 'snapshot': copy.deepcopy(scene['snapshot'] if snapshot is None else snapshot),
            'reviewedEngineering': [], 'rootBindingChanges': [], **extra}

    def save(self, body, **options):
        return self.request('/api/workbench/scenes/save', body, **options)

    def opened(self, scene, revision=None, **options):
        body = {'sceneId': scene['sceneId']}
        if revision is not None: body['sceneRevision'] = revision
        status, value, _ = self.request('/api/workbench/scenes/open', body, **options)
        self.assertEqual(status, 200, value)
        return value

    def local_scene(self, *, locked=False):
        status, scene, _ = self.request('/api/workbench/scenes/create',
            {'displayName': 'Synthetic scene', 'clientRequestId': str(uuid4())})
        self.assertEqual(status, 200, scene)
        snapshot = copy.deepcopy(scene['snapshot'])
        snapshot['instances'] = [self.item(locked=locked)]
        snapshot['initialView'] = {'eye': [80, 60, 90], 'target': [0, 15, 0]}
        status, value, _ = self.save(self.save_body(scene, snapshot))
        self.assertEqual(status, 200, value)
        return self.opened(scene)

    def anchor_body(self, scene, snapshot=None, *, heading=90):
        terrain = self.terrain()
        return {'kind': 'anchor', 'sceneId': scene['sceneId'], 'expectedSceneRevision': scene['sceneRevision'],
            'snapshot': copy.deepcopy(scene['snapshot'] if snapshot is None else snapshot),
            'candidateTerrainVersionId': terrain['terrainVersionId'],
            'anchor': {'localAnchor': [0, 0], 'geographicAnchor': self.lonlat(), 'trueNorthHeadingDeg': heading,
                'anchorHeight': {'mode': 'terrain_ground', 'terrainVersionId': terrain['terrainVersionId'], 'offsetM': 2},
                'heightStrategy': 'resample_each_ground'}}

    def check(self, body, **options):
        return self.request('/api/workbench/scenes/check', body, **options)

    def checked(self, scene):
        status, value, _ = self.check(self.anchor_body(scene))
        self.assertEqual(status, 200, value)
        return value

    def anchored(self):
        scene = self.local_scene()
        checked = self.checked(scene)
        status, value, _ = self.save(self.save_body(scene, checked['proposedSnapshot'], spatialChange=checked['spatialChange']))
        self.assertEqual(status, 200, value)
        return self.opened(scene)

    def counts(self):
        with self.sessions.library.connect() as db:
            return {name: db.execute('select count(*) from ' + name).fetchone()[0] for name in (
                'scene_revisions', 'scene_audit', 'scene_requests', 'scene_resource_uses',
                'scene_spatial_validations', 'scene_terrain_uses')}

    def assert_clean_geometry(self):
        self.assertEqual(list((self.sessions.library.root / 'temporary').glob('scene-geometry-*')), [])
        self.assertTrue(self.sessions.geometry.slots.acquire(blocking=False))
        self.sessions.geometry.slots.release()

    def moved(self, current, east=500120, north=3699920):
        snapshot = copy.deepcopy(current['snapshot'])
        position = snapshot['instances'][0]['placement']['position']
        position['longitude'], position['latitude'] = self.lonlat(east, north)
        return snapshot

    def validate_body(self, scene, snapshot):
        return {'kind': 'validate', 'sceneId': scene['sceneId'],
            'expectedSceneRevision': scene['sceneRevision'], 'snapshot': snapshot}

    def test_real_gis_anchor_receipt_save_and_fixed_old_revisions_retain_private_resource_identities(self):
        scene = self.local_scene()
        before = self.counts()
        checked = self.checked(scene)
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.opened(scene)['snapshot'], scene['snapshot'])
        self.assertGreater(len(checked['spatialChange']['receipt']), 64)
        self.assertLessEqual(len(checked['spatialChange']['receipt']), 8192)
        body = self.save_body(scene, checked['proposedSnapshot'], spatialChange=checked['spatialChange'])
        status, saved, _ = self.save(body)
        self.assertEqual(status, 200, saved)
        self.assertEqual(self.save(body)[1]['sceneRevision'], saved['sceneRevision'])
        current = self.opened(scene)
        self.assertEqual(current['snapshot'], checked['proposedSnapshot'])
        self.assertEqual(current['validation']['scope'], 'projected_site_unbound')
        self.assertFalse(current['validation']['geometrySummary']['fieldAccuracyVerified'])
        self.assertEqual(current['resourceRefs'][0]['modelAssetId'], self.version['modelAssetId'])
        self.assertEqual(current['resourceRefs'][0]['contentRevision'], self.version['contentRevision'])
        status, recalibrated, _ = self.calibrate(self.calibration(self.version))
        self.assertEqual(status, 200, recalibrated)
        self.assertNotEqual(recalibrated['modelVersionId'], self.version['modelVersionId'])
        self.assertEqual(self.opened(scene)['resourceRefs'], current['resourceRefs'])
        terrain = self.terrain_version
        self.assertEqual(current['terrainRefs'], [{'terrainVersionId': terrain['terrainVersionId'],
            'contentRevision': terrain['contentRevision'], 'sha256': terrain['sha256'], 'reportSha256': terrain['expectedReportSha256']}])
        self.assertAlmostEqual(current['snapshot']['coordinateFrame']['originHeight'], 104.25, delta=.02)
        self.assertAlmostEqual(current['snapshot']['instances'][0]['placement']['height']['offsetM'], 5)
        local = self.opened(scene, scene['sceneRevision'])
        self.assertEqual(local['snapshot']['coordinateFrame']['mode'], 'local_plane')
        self.assertEqual(local['terrainRefs'], [])
        self.assertEqual(local['headRevision'], saved['sceneRevision'])
        renamed = copy.deepcopy(current['snapshot']); renamed['displayName'] = 'Later name'
        self.assertEqual(self.save(self.save_body(current, renamed))[0], 200)
        fixed = self.opened(scene, saved['sceneRevision'])
        self.assertEqual(fixed['snapshot']['displayName'], 'Synthetic scene')
        self.assertEqual(fixed['terrainRefs'], current['terrainRefs'])
        self.assertEqual(fixed['resourceRefs'][0]['modelVersionId'], self.version['modelVersionId'])
        self.assertNotIn(str(self.root), json.dumps(fixed))
        self.assertFalse(any('/installations/' in path for _, path in self.authority().calls))
        self.assert_clean_geometry()

    def test_anchor_camera_and_placement_follow_independently_measured_true_north_rotation(self):
        scene = self.local_scene()
        draft = copy.deepcopy(scene['snapshot'])
        draft['instances'][0]['placement']['position']['xM'] = 20
        body = self.anchor_body(scene, draft)
        status, checked, _ = self.check(body)
        self.assertEqual(status, 200, checked)
        longitude, latitude = body['anchor']['geographicAnchor']
        east, north = transform('EPSG:4326', 'EPSG:32649', [longitude, longitude], [latitude, latitude + .0001])
        heading = math.radians(90 + math.degrees(math.atan2(east[1] - east[0], north[1] - north[0])))
        eye = checked['proposedSnapshot']['initialView']['eye']
        self.assertAlmostEqual(eye[0], 80 * math.cos(heading) - 90 * math.sin(heading), places=5)
        self.assertAlmostEqual(eye[2], 80 * math.sin(heading) + 90 * math.cos(heading), places=5)
        self.assertAlmostEqual(eye[1], 60, places=6)
        self.assertNotEqual(eye, scene['snapshot']['initialView']['eye'])
        actual = checked['validation']['displayPlacements'][0]['position']
        self.assertAlmostEqual(actual[0], 20 * math.cos(heading), places=5)
        self.assertAlmostEqual(actual[2], 20 * math.sin(heading), places=5)
        self.assertEqual(self.opened(scene)['snapshot'], scene['snapshot'])

    def test_forged_receipt_or_changed_proposed_snapshot_never_advances_head(self):
        scene = self.local_scene(); checked = self.checked(scene); before = self.counts()
        body = self.save_body(scene, checked['proposedSnapshot'], spatialChange={'kind': 'anchor', 'receipt': 'forged'})
        self.expect(self.save(body), 409, 'SPATIAL_PRECHECK_INVALID')
        body['spatialChange'] = checked['spatialChange']
        body['snapshot']['initialView']['eye'][0] += 1
        self.expect(self.save(body), 409, 'SPATIAL_PRECHECK_INVALID')
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.opened(scene)['sceneRevision'], scene['sceneRevision'])

    def test_receipt_is_bound_to_the_actual_user_and_access_revision(self):
        scene = self.local_scene(); checked = self.checked(scene); before = self.counts()
        body = self.save_body(scene, checked['proposedSnapshot'], spatialChange=checked['spatialChange'])
        other = self.login('another-synthetic-admin')
        self.expect(self.save(body, client=other), 409, 'SPATIAL_PRECHECK_INVALID')
        self.authority().grant = 'grant:later'
        self.expect(self.save(body), 409, 'SPATIAL_PRECHECK_INVALID')
        self.assertEqual(self.counts(), before)

    def test_old_head_after_preflight_cannot_be_overwritten_by_receipt(self):
        scene = self.local_scene(); checked = self.checked(scene)
        draft = copy.deepcopy(scene['snapshot']); draft['displayName'] = 'Concurrent local edit'
        status, newer, _ = self.save(self.save_body(scene, draft))
        self.assertEqual(status, 200, newer)
        before = self.counts()
        body = self.save_body(scene, checked['proposedSnapshot'], spatialChange=checked['spatialChange'])
        self.expect(self.save(body), 409, 'SCENE_CHANGED')
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.opened(scene)['sceneRevision'], newer['sceneRevision'])

    def test_frame_and_terrain_adoption_require_the_explicit_signed_preflight_receipt(self):
        scene = self.local_scene(); checked = self.checked(scene); before = self.counts()
        self.expect(self.save(self.save_body(scene, checked['proposedSnapshot'])), 422, 'SCENE_SCOPE_UNSUPPORTED')
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.opened(scene)['snapshot'], scene['snapshot'])

    def test_geographic_move_with_old_ground_sample_fails_then_checked_resampling_saves(self):
        current = self.anchored(); draft = self.moved(current); before = self.counts()
        old_height = draft['instances'][0]['placement']['height']['sampledHeightM']
        self.expect(self.save(self.save_body(current, draft)), 409, 'TERRAIN_SAMPLE_CHANGED')
        self.assertEqual(self.counts(), before)
        status, checked, _ = self.check(self.validate_body(current, draft))
        self.assertEqual(status, 200, checked)
        self.assertIsNone(checked['spatialChange'])
        height = checked['proposedSnapshot']['instances'][0]['placement']['height']
        self.assertAlmostEqual(height['sampledHeightM'] - old_height, .8, delta=.02)
        self.assertEqual(height['offsetM'], 5)
        self.assertEqual(height['sampleLongitude'], self.lonlat(500120, 3699920)[0])
        self.assertEqual(self.opened(current)['sceneRevision'], current['sceneRevision'])
        status, saved, _ = self.save(self.save_body(current, checked['proposedSnapshot']))
        self.assertEqual(status, 200, saved)
        opened = self.opened(current)
        self.assertEqual(opened['snapshot'], checked['proposedSnapshot'])
        self.assertEqual(opened['snapshot']['coordinateFrame'], current['snapshot']['coordinateFrame'])
        self.assert_clean_geometry()

    def test_locked_geographic_object_cannot_move_or_be_deleted(self):
        current = self.anchored()
        snapshot = copy.deepcopy(current['snapshot']); snapshot['instances'][0]['positionLocked'] = True
        self.assertEqual(self.save(self.save_body(current, snapshot))[0], 200)
        locked = self.opened(current); before = self.counts()
        self.expect(self.save(self.save_body(locked, self.moved(locked))), 409, 'INSTANCE_POSITION_LOCKED')
        removed = copy.deepcopy(locked['snapshot']); removed['instances'] = []
        self.expect(self.save(self.save_body(locked, removed)), 409, 'INSTANCE_POSITION_LOCKED')
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.opened(current)['snapshot'], locked['snapshot'])

    def test_public_resample_switch_and_private_path_injection_are_rejected(self):
        scene = self.local_scene(); before = self.counts()
        for field, value in (('resampleGround', True), ('terrainRoot', '/private/terrain'), ('path', '/etc/passwd'),
                             ('trustedTerrains', []), ('url', 'https://untrusted.invalid/elevation.tif')):
            body = self.anchor_body(scene); body[field] = value
            self.expect(self.check(body), 422, 'INVALID_REQUEST')
        body = self.anchor_body(scene); body['candidateTerrainVersionId'] = '../../source.tif'
        self.expect(self.check(body), 422, 'INVALID_REQUEST')
        body = self.anchor_body(scene); body['snapshot']['resampleGround'] = True
        self.expect(self.check(body), 422, 'INVALID_REQUEST')
        self.assertEqual(self.counts(), before)
        self.assert_clean_geometry()

    def test_nodata_hole_rejects_anchor_and_moved_ground_without_filling_zero(self):
        self.terrain(hole=True)
        scene = self.local_scene(); before = self.counts()
        body = self.anchor_body(scene); body['anchor']['geographicAnchor'] = self.lonlat(500160, 3699840)
        self.expect(self.check(body), 422, 'NO_DATA')
        self.assertEqual(self.counts(), before)
        current = self.anchored(); before = self.counts()
        draft = self.moved(current, 500160, 3699840)
        self.expect(self.check(self.validate_body(current, draft)), 422, 'NO_DATA')
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.opened(current)['snapshot'], current['snapshot'])
        self.assert_clean_geometry()

    def test_membership_revocation_after_actual_geometry_processing_does_not_commit(self):
        scene = self.local_scene(); checked = self.checked(scene); before = self.counts()
        body = self.save_body(scene, checked['proposedSnapshot'], spatialChange=checked['spatialChange'])
        original = self.sessions.geometry.process
        def revoke_after_actual_process(*args):
            value = original(*args)
            self.authority().allowed = False
            return value
        with patch.object(self.sessions.geometry, 'process', side_effect=revoke_after_actual_process):
            self.expect(self.save(body), 403, 'FORBIDDEN')
        self.assertEqual(self.counts(), before)
        self.authority().allowed = True
        self.assertEqual(self.opened(scene)['sceneRevision'], scene['sceneRevision'])
        self.assert_clean_geometry()

    def test_logout_after_actual_geometry_processing_drops_late_result_and_does_not_commit(self):
        scene = self.local_scene(); checked = self.checked(scene); before = self.counts()
        body = self.save_body(scene, checked['proposedSnapshot'], spatialChange=checked['spatialChange'])
        original = self.sessions.geometry.process
        def logout_after_actual_process(*args):
            value = original(*args)
            self.assertEqual(self.request('/api/session/logout')[0], 200)
            return value
        with patch.object(self.sessions.geometry, 'process', side_effect=logout_after_actual_process):
            self.expect(self.save(body), 401, 'SESSION_EXPIRED')
        self.assertEqual(self.counts(), before)
        self.assert_clean_geometry()

    def test_real_child_process_failure_and_busy_limit_release_slot_and_private_temporary_files(self):
        scene = self.local_scene(); body = self.anchor_body(scene); before = self.counts()
        failure = self.root / 'failing-geometry-worker'
        failure.write_text('#!' + sys.executable + '\nimport sys\nsys.exit(3)\n')
        failure.chmod(0o700)
        with patch.object(self.sessions.geometry, 'python', failure):
            self.expect(self.check(body), 422, 'SCENE_LIMIT_EXCEEDED')
        self.assert_clean_geometry()
        self.assertTrue(self.sessions.geometry.slots.acquire(blocking=False))
        try:
            self.expect(self.check(body), 429, 'SCENE_GEOMETRY_BUSY')
        finally:
            self.sessions.geometry.slots.release()
        self.assertEqual(self.check(body)[0], 200)
        self.assertEqual(self.counts(), before)
        self.assert_clean_geometry()

    def test_changed_fixed_terrain_artifact_is_refused_by_real_geometry_child(self):
        scene = self.local_scene(); body = self.anchor_body(scene); before = self.counts()
        artifact = self.sessions.terrains.root / 'versions' / self.terrain_version['terrainVersionId'] / 'derived' / 'positions.f32'
        original = artifact.read_bytes()
        changed = bytearray(original); changed[0] ^= 1; artifact.write_bytes(changed)
        self.expect(self.check(body), 409, 'RESOURCE_CHANGED')
        self.assertEqual(self.counts(), before)
        artifact.write_bytes(original)
        self.assertEqual(self.check(body)[0], 200)
        self.assert_clean_geometry()


if __name__ == '__main__': unittest.main()
