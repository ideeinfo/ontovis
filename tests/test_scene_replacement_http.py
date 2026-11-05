"""Real HTTP/GIS replacement previews, saves and permission boundaries.

All identities and terrain are synthetic. Reuse fixture helpers, not inherited
TestCase methods, so original acceptance cases are not counted a second time.
"""
import base64
import copy
import json
import time
from uuid import uuid4
import unittest

import numpy as np
import rasterio
from rasterio.transform import Affine

from tests import test_scene_spatial_http as fixture


class SceneReplacementHttpTests(unittest.TestCase):
    setUp = fixture.SceneSpatialHttpTests.setUp
    request = fixture.SceneSpatialHttpTests.request
    login = fixture.SceneSpatialHttpTests.login
    authority = fixture.SceneSpatialHttpTests.authority
    listing = fixture.SceneSpatialHttpTests.listing
    metadata = fixture.SceneSpatialHttpTests.metadata
    upload = fixture.SceneSpatialHttpTests.upload
    new_version = fixture.SceneSpatialHttpTests.new_version
    calibration = fixture.SceneSpatialHttpTests.calibration
    calibrate = fixture.SceneSpatialHttpTests.calibrate
    expect = fixture.SceneSpatialHttpTests.expect
    lonlat = fixture.SceneSpatialHttpTests.lonlat
    terrain = fixture.SceneSpatialHttpTests.terrain
    item = fixture.SceneSpatialHttpTests.item
    save_body = fixture.SceneSpatialHttpTests.save_body
    save = fixture.SceneSpatialHttpTests.save
    opened = fixture.SceneSpatialHttpTests.opened
    local_scene = fixture.SceneSpatialHttpTests.local_scene
    anchor_body = fixture.SceneSpatialHttpTests.anchor_body
    check = fixture.SceneSpatialHttpTests.check
    checked = fixture.SceneSpatialHttpTests.checked
    anchored = fixture.SceneSpatialHttpTests.anchored
    counts = fixture.SceneSpatialHttpTests.counts
    assert_clean_geometry = fixture.SceneSpatialHttpTests.assert_clean_geometry

    def replacement(self, scene, kind, **extra):
        return {'sceneId': scene['sceneId'], 'expectedSceneRevision': scene['sceneRevision'],
            'snapshot': copy.deepcopy(scene['snapshot']), 'kind': kind, **extra}

    def preflight(self, body, **options):
        return self.request('/api/workbench/scenes/replacement-check', body, **options)

    def other_model(self):
        body = self.calibration(self.version)
        body['calibration']['forward'] = [1, 0, 0]
        status, version, _ = self.calibrate(body)
        self.assertEqual(status, 200, version)
        self.assertNotEqual(version['modelVersionId'], self.version['modelVersionId'])
        return version

    def other_terrain(self, *, delta=5, hole=False, flat=False, datum='EGM2008'):
        row, column = np.indices((32, 32))
        values = np.full((32, 32), 100 + delta, dtype='float32') if flat else np.asarray(100 + row * .1 + column * .2 + delta, dtype='float32')
        if hole:
            values[6:11, 6:11] = -9999
        source = self.root / 'synthetic-replacement.tif'
        with rasterio.open(source, 'w', driver='GTiff', width=32, height=32, count=1,
                dtype='float32', crs='EPSG:32649', transform=Affine(10, 0, 500000, 0, -10, 3700000), nodata=-9999) as dataset:
            dataset.write(values, 1)
        metadata = {'expectedSessionRevision': self.admin['revision'], 'clientRequestId': str(uuid4()),
            'displayName': 'Synthetic replacement elevation', 'sourceNote': 'Synthetic elevation, not a field survey',
            'licenseNote': 'Synthetic test data', 'rightsDeclared': True, 'verticalDatum': datum, 'heightUnit': 'm'}
        if datum == 'UNKNOWN_RELATIVE':
            metadata['relativeReferenceId'] = 'synthetic-common-relative-reference'
        encoded = base64.b64encode(json.dumps(metadata).encode()).decode()
        status, job, _ = self.request('/api/workbench/terrains/upload', raw=source.read_bytes(),
            headers={'Content-Type': 'image/tiff', 'X-Terrain-Metadata': encoded})
        self.assertEqual(status, 202, job)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            status, current, _ = self.request('/api/workbench/terrains/job', {'jobId': job['jobId']})
            self.assertEqual(status, 200, current)
            if current['state'] in ('ready', 'failed', 'cancelled'):
                break
            time.sleep(.02)
        self.assertEqual(current['state'], 'ready', current)
        status, version, _ = self.request('/api/workbench/terrains/version', {'terrainVersionId': current['terrainVersionId']})
        self.assertEqual(status, 200, version)
        return version

    def test_model_preview_has_no_writes_and_save_changes_only_target_with_history(self):
        scene = self.local_scene()
        draft = copy.deepcopy(scene['snapshot'])
        second = copy.deepcopy(draft['instances'][0])
        second['sceneModelInstanceId'] = str(uuid4())
        second['placement']['position']['xM'] = 80
        draft['instances'].append(second)
        status, _, _ = self.save(self.save_body(scene, draft))
        self.assertEqual(status, 200)
        scene = self.opened(scene)
        candidate = self.other_model()
        body = self.replacement(scene, 'model', sceneModelInstanceId=draft['instances'][0]['sceneModelInstanceId'],
            candidateModelVersionId=candidate['modelVersionId'])
        before = self.counts()
        status, checked, _ = self.preflight(body)
        self.assertEqual(status, 200, checked)
        self.assertEqual(self.counts(), before)
        self.assertEqual(checked['validation']['impact']['kind'], 'model_replacement')
        self.assertEqual(checked['proposedSnapshot']['instances'][1], scene['snapshot']['instances'][1])
        save = self.save_body(scene, checked['proposedSnapshot'], spatialChange=checked['spatialChange'])
        status, saved, _ = self.save(save)
        self.assertEqual(status, 200, saved)
        self.assertEqual(self.save(save)[1]['sceneRevision'], saved['sceneRevision'])
        opened = self.opened(scene)
        self.assertEqual(opened['snapshot'], checked['proposedSnapshot'])
        self.assertEqual(self.opened(scene, scene['sceneRevision'])['snapshot'], scene['snapshot'])
        self.assertEqual(opened['snapshot']['instances'][0]['modelVersionId'], candidate['modelVersionId'])
        self.assertEqual(opened['snapshot']['instances'][1]['modelVersionId'], self.version['modelVersionId'])

    def test_model_preflight_is_member_readable_but_save_requires_admin(self):
        scene, candidate = self.local_scene(), self.other_model()
        reader = self.login('synthetic-replacement-reader')
        self.authority(reader).role = 'viewer'
        body = self.replacement(scene, 'model', sceneModelInstanceId=scene['snapshot']['instances'][0]['sceneModelInstanceId'],
            candidateModelVersionId=candidate['modelVersionId'])
        before = self.counts()
        status, checked, _ = self.preflight(body, client=reader)
        self.assertEqual(status, 200, checked)
        self.assertFalse(checked['capabilities']['canWrite'])
        status, value, _ = self.save(self.save_body(scene, checked['proposedSnapshot'], spatialChange=checked['spatialChange']), client=reader)
        self.assertEqual((status, value['code']), (403, 'SCENE_WRITE_FORBIDDEN'))
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.opened(scene, client=reader)['snapshot'], scene['snapshot'])

    def test_dirty_snapshot_unverified_version_and_mutually_exclusive_fields_are_rejected(self):
        scene, candidate = self.local_scene(), self.other_model()
        body = self.replacement(scene, 'model', sceneModelInstanceId=scene['snapshot']['instances'][0]['sceneModelInstanceId'],
            candidateModelVersionId=candidate['modelVersionId'])
        dirty = copy.deepcopy(body)
        dirty['snapshot']['displayName'] += ' unsaved'
        self.expect(self.preflight(dirty), 409, 'SCENE_DRAFT_REQUIRES_SAVE')
        mixed = {**body, 'candidateTerrainVersionId': str(uuid4()), 'strategy': 'keep_height'}
        self.expect(self.preflight(mixed), 422, 'INVALID_REQUEST')
        raw = {**body, 'candidateModelVersionId': self.raw_model['modelVersionId']}
        self.expect(self.preflight(raw), 409, 'MODEL_CALIBRATION_REQUIRED')
        self.assertEqual(self.opened(scene)['snapshot'], scene['snapshot'])

    def test_preflight_route_has_its_own_large_json_boundary(self):
        status, value, _ = self.request('/api/workbench/scenes/replacement-check', raw=b'{}',
            headers={'Content-Type': 'application/json', 'Content-Length': str(1024 * 1024 + 1)})
        self.assertEqual((status, value['code']), (413, 'SCENE_LIMIT_EXCEEDED'))
        status, value, _ = self.request('/api/workbench/scenes/head', raw=b'{}',
            headers={'Content-Type': 'application/json', 'Content-Length': '17000'})
        self.assertEqual((status, value['code']), (413, 'INVALID_REQUEST'))

    def test_real_gis_resample_saves_new_height_and_retains_old_terrain_history(self):
        scene, candidate = self.anchored(), self.other_terrain()
        before = self.counts()
        status, checked, _ = self.preflight(self.replacement(scene, 'terrain',
            candidateTerrainVersionId=candidate['terrainVersionId'], strategy='resample_ground'))
        self.assertEqual(status, 200, checked)
        self.assertEqual(self.counts(), before)
        impact = checked['validation']['impact']
        self.assertAlmostEqual(impact['instances'][0]['heightDeltaM'], 5, delta=.001)
        self.assertEqual(checked['proposedSnapshot']['initialView'], scene['snapshot']['initialView'])
        status, saved, _ = self.save(self.save_body(scene, checked['proposedSnapshot'], spatialChange=checked['spatialChange']))
        self.assertEqual(status, 200, saved)
        opened = self.opened(scene)
        self.assertEqual(opened['snapshot']['terrain']['terrainVersionId'], candidate['terrainVersionId'])
        self.assertEqual(self.opened(scene, scene['sceneRevision'])['terrainRefs'], scene['terrainRefs'])
        self.assertEqual(opened['validation']['impact'], impact)
        self.assert_clean_geometry()

    def test_known_keep_height_accepts_new_nodata_and_preserves_estimate_source(self):
        scene, candidate = self.anchored(), self.other_terrain(hole=True)
        status, checked, _ = self.preflight(self.replacement(scene, 'terrain',
            candidateTerrainVersionId=candidate['terrainVersionId'], strategy='keep_height'))
        self.assertEqual(status, 200, checked)
        height = checked['proposedSnapshot']['instances'][0]['placement']['height']
        self.assertEqual(height['mode'], 'absolute')
        self.assertEqual(checked['validation']['impact']['instances'][0]['newSampledHeightM'], None)
        self.assertTrue(checked['validation']['impact']['sampleIssues'])
        status, saved, _ = self.save(self.save_body(scene, checked['proposedSnapshot'], spatialChange=checked['spatialChange']))
        self.assertEqual(status, 200, saved)
        opened = self.opened(scene)
        self.assertEqual(opened['snapshot']['instances'][0]['placement']['height'], height)
        self.assertTrue(opened['heightProvenance'])
        self.assert_clean_geometry()

    def test_integer_origin_browser_roundtrip_can_reopen_then_make_an_ordinary_save(self):
        self.terrain_version = self.other_terrain(delta=0, flat=True)
        scene, candidate = self.anchored(), self.other_terrain(delta=5, flat=True)
        status, checked, _ = self.preflight(self.replacement(scene, 'terrain',
            candidateTerrainVersionId=candidate['terrainVersionId'], strategy='keep_height'))
        self.assertEqual(status, 200, checked)
        # Match JSON.stringify's integral number representation without making
        # Node an additional dependency of the optional Python/GIS suite.
        def browser_numbers(value):
            if type(value) is float and value.is_integer():
                return int(value)
            if type(value) is dict:
                return {key: browser_numbers(item) for key, item in value.items()}
            if type(value) is list:
                return [browser_numbers(item) for item in value]
            return value
        proposed = browser_numbers(checked['proposedSnapshot'])
        status, saved, _ = self.save(self.save_body(scene, proposed, spatialChange=checked['spatialChange']))
        self.assertEqual(status, 200, saved)
        opened = self.opened(scene)
        draft = browser_numbers(opened['snapshot'])
        draft['instances'][0]['displayName'] += ' after browser reopen'
        status, validation, _ = self.check({'kind': 'validate', 'sceneId': opened['sceneId'],
            'expectedSceneRevision': opened['sceneRevision'], 'snapshot': draft})
        self.assertEqual(status, 200, validation)
        status, saved, _ = self.save(self.save_body(opened, browser_numbers(validation['proposedSnapshot'])))
        self.assertEqual(status, 200, saved)
        final = self.opened(scene)
        self.assertEqual(final['snapshot']['instances'][0]['displayName'], draft['instances'][0]['displayName'])
        self.assertEqual(final['snapshot']['coordinateFrame']['frameRevision'], proposed['coordinateFrame']['frameRevision'])

    def test_unknown_relative_decimal_origin_survives_both_replacement_strategies_and_reopen(self):
        self.terrain_version = self.other_terrain(delta=-100, flat=True, datum='UNKNOWN_RELATIVE')
        candidate = self.other_terrain(delta=0, flat=True, datum='UNKNOWN_RELATIVE')
        for strategy in ('keep_height', 'resample_ground'):
            with self.subTest(strategy=strategy):
                scene = self.local_scene()
                anchor = self.anchor_body(scene)
                anchor['anchor']['anchorHeight']['offsetM'] = .1
                status, checked, _ = self.check(anchor)
                self.assertEqual(status, 200, checked)
                status, saved, _ = self.save(self.save_body(scene, checked['proposedSnapshot'], spatialChange=checked['spatialChange']))
                self.assertEqual(status, 200, saved)
                scene = self.opened(scene)
                self.assertEqual(scene['snapshot']['coordinateFrame']['originHeight'], .1)
                status, checked, _ = self.preflight(self.replacement(scene, 'terrain',
                    candidateTerrainVersionId=candidate['terrainVersionId'], strategy=strategy))
                self.assertEqual(status, 200, checked)
                self.assertEqual(checked['proposedSnapshot']['coordinateFrame']['originHeight'], .1)
                self.assertIn('offsetCompensationM', checked['proposedSnapshot']['coordinateFrame']['anchor']['anchorHeight'])
                status, saved, _ = self.save(self.save_body(scene, checked['proposedSnapshot'], spatialChange=checked['spatialChange']))
                self.assertEqual(status, 200, saved)
                current = self.opened(scene)
                self.assertEqual(current['snapshot']['coordinateFrame']['originHeight'], .1)
                status, validation, _ = self.check({'kind': 'validate', 'sceneId': current['sceneId'],
                    'expectedSceneRevision': current['sceneRevision'], 'snapshot': current['snapshot']})
                self.assertEqual(status, 200, validation)
                self.assertEqual(validation['proposedSnapshot']['coordinateFrame']['originHeight'], .1)
                self.assert_clean_geometry()

    def test_required_ground_nodata_and_locked_height_change_reject_without_scene_writes(self):
        scene = self.anchored()
        candidate = self.other_terrain(hole=True)
        before = self.counts()
        self.expect(self.preflight(self.replacement(scene, 'terrain',
            candidateTerrainVersionId=candidate['terrainVersionId'], strategy='resample_ground')), 422, 'NO_DATA')
        self.assertEqual(self.counts(), before)
        snapshot = copy.deepcopy(scene['snapshot'])
        snapshot['instances'][0]['positionLocked'] = True
        status, _, _ = self.save(self.save_body(scene, snapshot))
        self.assertEqual(status, 200)
        scene = self.opened(scene)
        valid = self.other_terrain(delta=7)
        before = self.counts()
        self.expect(self.preflight(self.replacement(scene, 'terrain',
            candidateTerrainVersionId=valid['terrainVersionId'], strategy='resample_ground')), 409, 'INSTANCE_POSITION_LOCKED')
        self.assertEqual(self.counts(), before)
        self.assert_clean_geometry()


if __name__ == '__main__':
    unittest.main()
