"""SQLite spatial-save boundaries; callbacks are explicit synthetic geometry.

Projection and fixed terrain arithmetic are exercised separately by the actual
GIS suites. These tests verify receipts, lock boundaries and atomic references.
"""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.model_library import ModelLibrary
from apps.api.model_validation import validate
from apps.api.scene_library import SceneLibrary, _digest, _receipt_snapshot_digest
from apps.api.terrain_library import TerrainLibrary
from tests.test_model_upload import glb


class SceneSpatialTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.models = ModelLibrary(self.root/'models', 'fixture-project', str(uuid4()))
        source = glb(self.root/'fixture.glb')
        metadata = {'expectedSessionRevision': 'session:1', 'expectedLibraryRevision': self.models.listing()['libraryRevision'],
                    'clientRequestId': str(uuid4()), 'displayName': 'Synthetic model',
                    'sourceNote': 'Synthetic fixture', 'rightsDeclared': True}
        self.model = self.models.save_upload(source, metadata, 'admin', validate(source), lambda: None)
        self.asset_id = str(uuid4())
        self.content_revision = 'model-content:'+'c'*64
        self.scenes = SceneLibrary(self.models, model_identity=self.identity)
        self.terrains = TerrainLibrary(self.models, python_executable=sys.executable, start_worker=False)
        self.addCleanup(self.terrains.close)
        self.terrain = {'terrainVersionId': str(uuid4()), 'contentRevision': 'terrain-content:fixture-1',
                        'sha256': 'a'*64, 'reportSha256': 'b'*64}
        with self.models.connect() as db:
            db.execute('insert into terrain_versions values (?,?,?,?,?,?,?,?,?,?)',
                       (self.terrain['terrainVersionId'], self.terrain['sha256'], self.terrain['contentRevision'],
                        'Synthetic terrain', '{}', '{}', self.terrain['reportSha256'], '[]', 0, '2026-10-22T00:00:00Z'))
        self.grant, self.allowed = 'grant:1', True
        self.on_geometry = None
        self.geometry_calls = 0

    def identity(self, version_id, *, db=None):
        self.assertIsNotNone(db)
        row = db.execute('select sha256 from versions where id=?', (version_id,)).fetchone()
        if row is None:
            raise PreviewError(404, 'NOT_FOUND_OR_FORBIDDEN')
        return {'modelVersionId': version_id, 'modelAssetId': self.asset_id, 'sha256': row['sha256'],
                'contentRevision': self.content_revision, 'calibrationState': 'verified', 'canPlace': True}

    def authorize(self):
        if not self.allowed:
            raise PreviewError(403, 'SCENE_WRITE_FORBIDDEN')

    def resources(self, snapshot):
        for item in snapshot['instances']:
            self.models.version(item['modelVersionId'])
        if snapshot['coordinateFrame']['mode'] == 'projected_site':
            if snapshot['terrain']['terrainVersionId'] != self.terrain['terrainVersionId']:
                raise PreviewError(409, 'RESOURCE_CHANGED')
            return {'terrains': [copy.deepcopy(self.terrain)]}
        return {'terrains': []}

    def engineering(self, snapshot, reviewed, changes):
        self.assertEqual(reviewed, []); self.assertEqual(changes, [])
        self.assertTrue(all(item['rootBinding'] is None and item['componentBindings'] == [] for item in snapshot['instances']))

    def create(self):
        return self.scenes.create({'displayName': '合成设备区', 'clientRequestId': str(uuid4())},
                                 'admin', self.authorize, self.resources, self.engineering)

    def item(self, *, locked=False):
        return {'sceneModelInstanceId': str(uuid4()), 'displayName': '设备A', 'modelVersionId': self.model['versionId'],
                'placement': {'position': {'mode': 'local', 'xM': 10, 'zM': -20},
                              'height': {'mode': 'local_relative', 'relativeHeightM': 2}, 'headingDeg': 30},
                'visible': True, 'positionLocked': locked, 'rootBinding': None, 'componentBindings': []}

    def body(self, scene, snapshot=None):
        return {'sceneId': scene['sceneId'], 'expectedSceneRevision': scene['sceneRevision'],
                'clientRequestId': str(uuid4()), 'snapshot': copy.deepcopy(snapshot or scene['snapshot']),
                'reviewedEngineering': [], 'rootBindingChanges': []}

    def save(self, body, *, actor='admin', authorize=None, resources=None, geometry=None, access_revision=None):
        return self.scenes.save(body, actor, authorize or self.authorize, resources or self.resources,
                                self.engineering, validate_geometry=geometry or self.geometry,
                                access_revision=access_revision or self.grant)

    def opened(self, scene, revision=None):
        return self.scenes.open(scene['sceneId'], 'admin', self.authorize, revision)

    def local_scene(self, *, locked=False):
        scene = self.create()
        snapshot = copy.deepcopy(scene['snapshot']); snapshot['instances'] = [self.item(locked=locked)]
        self.save(self.body(scene, snapshot))
        return self.opened(scene)

    def anchor(self):
        return {'localAnchor': [0, 0], 'geographicAnchor': [111, 33], 'trueNorthHeadingDeg': 20,
                'anchorHeight': {'mode': 'terrain_ground', 'terrainVersionId': self.terrain['terrainVersionId'], 'offsetM': 0},
                'heightStrategy': 'resample_each_ground'}

    def geometry(self, snapshot, *, expected_frame=None):
        self.geometry_calls += 1
        if self.on_geometry is not None:
            self.on_geometry()
        if expected_frame is not None and snapshot['coordinateFrame'] != expected_frame:
            raise PreviewError(409, 'FRAME_CHANGED')
        provenance = [{'sceneModelInstanceId': item['sceneModelInstanceId'], 'kind': 'terrain_estimate',
                       'terrainVersionId': self.terrain['terrainVersionId'], 'reportSha256': self.terrain['reportSha256'],
                       'sampledHeightM': item['placement']['height']['sampledHeightM']}
                      for item in snapshot['instances']]
        return {'snapshot': copy.deepcopy(snapshot), 'heightProvenance': provenance,
                'displayPlacements': [{'sceneModelInstanceId': item['sceneModelInstanceId'], 'position': [0, 2, 0]}
                                      for item in snapshot['instances']],
                'geometrySummary': {'mode': 'projected_site', 'fieldAccuracyVerified': False},
                'resourceRefs': {'models': sorted({item['modelVersionId'] for item in snapshot['instances']}),
                                 'terrains': [copy.deepcopy(self.terrain)]}}

    def preview(self, local, candidate, anchor):
        self.assertEqual(candidate, self.terrain['terrainVersionId'])
        result = copy.deepcopy(local)
        result['terrain'] = {'terrainVersionId': candidate, 'expectedContentRevision': self.terrain['contentRevision']}
        frame = {'mode': 'projected_site', 'frameRevision': 'fixture-frame-geographic', 'horizontalCrs': 'EPSG:32649',
                 'verticalDatum': 'EGM2008', 'transformId': 'fixture-fixed-transform', 'originEasting': 500000,
                 'originNorthing': 3700000, 'originHeight': 200, 'convergenceRuleId': 'fixture-north-rule',
                 'anchor': copy.deepcopy(anchor)}
        result['coordinateFrame'] = frame
        for item in result['instances']:
            old = item['placement']
            longitude, latitude = 111+old['position']['xM']/100000, 33-old['position']['zM']/100000
            item['placement'] = {'position': {'mode': 'geographic', 'longitude': longitude, 'latitude': latitude,
                                             'transformId': frame['transformId'], 'frameRevision': frame['frameRevision']},
                                 'height': {'mode': 'terrain_ground', 'terrainVersionId': candidate, 'terrainSha256': self.terrain['sha256'],
                                            'sampleLongitude': longitude, 'sampleLatitude': latitude, 'sampledHeightM': 200,
                                            'offsetM': old['height']['relativeHeightM'], 'verticalDatum': 'EGM2008', 'samplingRule': 'synthetic-only'},
                                 'headingDeg': old['headingDeg']}
        result['initialView']['eye'][0] += 10
        return self.geometry(result)

    def check_body(self, scene, snapshot=None, *, kind='anchor'):
        result = {'kind': kind, 'sceneId': scene['sceneId'], 'expectedSceneRevision': scene['sceneRevision'],
                  'snapshot': copy.deepcopy(snapshot or scene['snapshot'])}
        if kind == 'anchor':
            result.update(candidateTerrainVersionId=self.terrain['terrainVersionId'], anchor=self.anchor())
        return result

    def check(self, body, *, actor='admin', resources=None, preview=None, geometry=None, grant=None):
        return self.scenes.check(body, actor, self.authorize, resources or self.resources, self.engineering,
                                 geometry or self.geometry, preview or self.preview, access_revision=grant or self.grant)

    def anchored_request(self, scene):
        checked = self.check(self.check_body(scene))
        request = self.body(scene, checked['proposedSnapshot'])
        request['spatialChange'] = checked['spatialChange']
        return request

    def counts(self):
        with self.models.connect() as db:
            return {name: db.execute('select count(*) from '+name).fetchone()[0]
                    for name in ('scene_revisions', 'scene_requests', 'scene_audit', 'scene_spatial_validations',
                                 'scene_resource_uses', 'scene_terrain_uses')}

    def expect(self, code, action):
        with self.assertRaises(PreviewError) as caught:
            action()
        self.assertEqual(caught.exception.code, code)

    def test_anchor_check_is_read_only_and_save_retains_fixed_spatial_evidence(self):
        scene = self.local_scene()
        before = self.counts()
        checked = self.check(self.check_body(scene))
        self.assertEqual(self.counts(), before)
        self.assertLessEqual(len(checked['spatialChange']['receipt']), 8192)
        request = self.body(scene, checked['proposedSnapshot']); request['spatialChange'] = checked['spatialChange']
        saved = self.save(request)
        opened = self.opened(scene)
        self.assertEqual(opened['sceneRevision'], saved['sceneRevision'])
        self.assertEqual(opened['snapshot'], checked['proposedSnapshot'])
        self.assertEqual(opened['terrainRefs'], [self.terrain])
        self.assertEqual(opened['validation']['scope'], 'projected_site_unbound')
        self.assertEqual(len(opened['heightProvenance']), 1)
        self.assertEqual(opened['resourceRefs'][0]['modelAssetId'], self.asset_id)
        self.assertEqual(opened['resourceRefs'][0]['contentRevision'], self.content_revision)
        self.assertEqual(self.opened(scene, scene['sceneRevision'])['snapshot']['coordinateFrame']['mode'], 'local_plane')

    def test_anchor_receipt_allows_unsaved_local_edits_without_storing_the_draft(self):
        scene = self.local_scene()
        draft = copy.deepcopy(scene['snapshot'])
        draft['instances'][0]['placement']['position']['xM'] += 40
        draft['instances'].append(self.item())
        checked = self.check(self.check_body(scene, draft))
        self.assertEqual(len(self.opened(scene)['snapshot']['instances']), 1)
        request = self.body(scene, checked['proposedSnapshot']); request['spatialChange'] = checked['spatialChange']
        self.save(request)
        self.assertEqual(len(self.opened(scene)['snapshot']['instances']), 2)

    def test_anchor_receipt_accepts_browser_equal_integer_and_negative_zero_numbers(self):
        scene = self.local_scene()

        def preview(local, candidate, anchor):
            result = self.preview(local, candidate, anchor)
            snapshot = result['snapshot']
            snapshot['coordinateFrame']['originHeight'] = 200.0
            snapshot['coordinateFrame']['anchor']['localAnchor'] = [-0.0, 0.0]
            snapshot['instances'][0]['placement']['headingDeg'] = 30.0
            snapshot['initialView']['eye'][1] = 90.0
            return result

        checked = self.check(self.check_body(scene), preview=preview)
        request = self.body(scene, checked['proposedSnapshot'])
        request['spatialChange'] = checked['spatialChange']
        # These are the number tokens emitted by JSON.stringify(JSON.parse(...)).
        browser = copy.deepcopy(request)
        browser['snapshot']['coordinateFrame']['originHeight'] = 200
        browser['snapshot']['coordinateFrame']['anchor']['localAnchor'] = [0, 0]
        browser['snapshot']['instances'][0]['placement']['headingDeg'] = 30
        browser['snapshot']['initialView']['eye'][1] = 90
        self.assertEqual(request, browser)
        self.assertNotEqual(_digest(request['snapshot']), _digest(browser['snapshot']))
        saved = self.save(browser)
        self.assertEqual(self.opened(scene)['sceneRevision'], saved['sceneRevision'])
        self.assertEqual(self.opened(scene)['snapshot'], checked['proposedSnapshot'])
        self.assertEqual(self.save(browser), saved)

    def test_anchor_receipt_preserves_decimal_edits_and_number_types(self):
        scene = self.local_scene(); request = self.anchored_request(scene)
        before = self.counts()
        changed = copy.deepcopy(request)
        changed['snapshot']['instances'][0]['placement']['headingDeg'] += 1e-12
        self.expect('SPATIAL_PRECHECK_INVALID', lambda: self.save(changed))
        changed = copy.deepcopy(request)
        changed['snapshot']['coordinateFrame']['originHeight'] += 1e-12
        self.expect('SPATIAL_PRECHECK_INVALID', lambda: self.save(changed))
        changed = copy.deepcopy(request)
        changed['snapshot']['instances'][0]['placement']['headingDeg'] = True
        self.expect('INVALID_REQUEST', lambda: self.save(changed))
        self.assertEqual(self.counts(), before)
        self.assertNotEqual(_receipt_snapshot_digest({'number': True}), _receipt_snapshot_digest({'number': 1}))
        self.assertNotEqual(_receipt_snapshot_digest({'number': 2**53}), _receipt_snapshot_digest({'number': 2**53+1}))
        self.assertNotEqual(_receipt_snapshot_digest({'number': 2**53+1}), _receipt_snapshot_digest({'number': float(2**53+1)}))

    def test_no_receipt_cannot_change_frame_or_adopt_terrain(self):
        scene = self.local_scene(); request = self.anchored_request(scene)
        request.pop('spatialChange')
        self.expect('SCENE_SCOPE_UNSUPPORTED', lambda: self.save(request))
        self.assertEqual(self.opened(scene)['sceneRevision'], scene['sceneRevision'])

    def test_receipt_is_bound_to_actor_grant_scene_and_proposed_snapshot(self):
        scene = self.local_scene(); request = self.anchored_request(scene)
        before = self.counts()
        self.expect('SPATIAL_PRECHECK_INVALID', lambda: self.save(request, actor='another-admin'))
        self.expect('SPATIAL_PRECHECK_INVALID', lambda: self.save(request, access_revision='grant:2'))
        changed = copy.deepcopy(request); changed['snapshot']['instances'][0]['displayName'] = 'Changed after preview'
        self.expect('SPATIAL_PRECHECK_INVALID', lambda: self.save(changed))
        changed = copy.deepcopy(request); changed['spatialChange']['receipt'] = 'forged-token'
        self.expect('SPATIAL_PRECHECK_INVALID', lambda: self.save(changed))
        another = self.local_scene(); changed = copy.deepcopy(request)
        changed['sceneId'] = another['sceneId']; changed['expectedSceneRevision'] = another['sceneRevision']
        self.expect('SPATIAL_PRECHECK_INVALID', lambda: self.save(changed))
        self.assertEqual(self.counts()['scene_terrain_uses'], before['scene_terrain_uses'])

    def test_stale_head_precedes_receipt_verification(self):
        scene = self.local_scene(); request = self.anchored_request(scene)
        self.save(self.body(scene))
        request['spatialChange']['receipt'] = 'not-a-valid-receipt'
        self.expect('SCENE_CHANGED', lambda: self.save(request))

    def test_anchor_receipts_do_not_accept_the_scene_pagination_signing_namespace(self):
        scene = self.local_scene(); request = self.anchored_request(scene)
        with self.models.connect() as db:
            raw = self.scenes._uncursor(request['spatialChange']['receipt'], self.scenes._receipt_key(db))
            _, cursor_key = self.scenes._catalog(db)
            request['spatialChange']['receipt'] = self.scenes._cursor(raw, cursor_key)
        self.expect('SPATIAL_PRECHECK_INVALID', lambda: self.save(request))

    def test_replay_does_not_rerun_geometry_and_still_checks_current_permission(self):
        scene = self.local_scene(); request = self.anchored_request(scene)
        first = self.save(request); calls = self.geometry_calls; counts = self.counts()
        self.assertEqual(self.save(request), first)
        self.assertEqual(self.geometry_calls, calls); self.assertEqual(self.counts(), counts)
        self.allowed = False
        self.expect('SCENE_WRITE_FORBIDDEN', lambda: self.save(request))

    def test_geometry_runs_without_a_sqlite_write_lock_and_final_cas_rejects_race(self):
        scene = self.local_scene(); request = self.anchored_request(scene)
        actions = []
        def concurrent_local_save():
            self.on_geometry = None
            self.save(self.body(scene))
            actions.append('committed outside geometry lock')
        self.on_geometry = concurrent_local_save
        self.expect('SCENE_CHANGED', lambda: self.save(request))
        self.assertEqual(actions, ['committed outside geometry lock'])
        self.assertEqual(self.opened(scene)['snapshot']['coordinateFrame']['mode'], 'local_plane')

    def test_geometry_resource_changes_roll_back_all_spatial_tables(self):
        scene = self.local_scene(); request = self.anchored_request(scene); before = self.counts()
        self.on_geometry = lambda: setattr(self, 'content_revision', 'model-content:'+'d'*64)
        self.expect('RESOURCE_CHANGED', lambda: self.save(request))
        self.assertEqual(self.counts(), before)

    def test_terrain_manifest_change_after_geometry_rolls_back(self):
        scene = self.local_scene(); request = self.anchored_request(scene); before = self.counts()
        def change_then_result(snapshot, *, expected_frame=None):
            result = self.geometry(snapshot, expected_frame=expected_frame)
            self.terrain['reportSha256'] = 'e'*64
            return result
        self.expect('RESOURCE_CHANGED', lambda: self.save(request, geometry=change_then_result))
        self.assertEqual(self.counts(), before)

    def test_permission_loss_at_final_commit_rolls_back_spatial_evidence(self):
        scene = self.local_scene(); request = self.anchored_request(scene); before = self.counts()
        calls = []
        def revoke_final():
            calls.append(True)
            if len(calls) == 2:
                raise PreviewError(403, 'SCENE_WRITE_FORBIDDEN')
        self.expect('SCENE_WRITE_FORBIDDEN', lambda: self.save(request, authorize=revoke_final))
        self.assertEqual(self.counts(), before)

    def test_locked_local_draft_cannot_hide_move_delete_or_replacement_in_anchor(self):
        scene = self.local_scene(locked=True)
        for change in ('move', 'delete', 'model'):
            snapshot = copy.deepcopy(scene['snapshot'])
            if change == 'move': snapshot['instances'][0]['placement']['position']['xM'] += 1
            elif change == 'delete': snapshot['instances'] = []
            else: snapshot['instances'][0]['modelVersionId'] = str(uuid4())
            self.expect('INSTANCE_POSITION_LOCKED', lambda: self.check(self.check_body(scene, snapshot)))
        self.save(self.anchored_request(scene))
        self.assertTrue(self.opened(scene)['snapshot']['instances'][0]['positionLocked'])

    def test_locked_local_model_change_requires_explicit_unlock(self):
        scene = self.local_scene(locked=True)
        request = self.body(scene)
        request['snapshot']['instances'][0]['modelVersionId'] = str(uuid4())
        self.expect('INSTANCE_POSITION_LOCKED', lambda: self.save(request))

    def test_anchor_preview_cannot_change_ids_locks_names_or_resource(self):
        scene = self.local_scene()
        def broken_preview(snapshot, candidate, anchor):
            result = self.preview(snapshot, candidate, anchor)
            result['snapshot']['instances'][0]['positionLocked'] = True
            return result
        self.expect('INVALID_GEOMETRY_RESULT', lambda: self.check(self.check_body(scene), preview=broken_preview))

    def test_geo_same_frame_save_and_read_only_validate_keep_fixed_revision(self):
        scene = self.local_scene(); self.save(self.anchored_request(scene)); current = self.opened(scene)
        request = self.body(current)
        request['snapshot']['instances'][0]['placement']['position']['longitude'] += .0001
        request['snapshot']['instances'][0]['placement']['height']['sampleLongitude'] += .0001
        checked = self.check(self.check_body(current, request['snapshot'], kind='validate'))
        self.assertIsNone(checked['spatialChange'])
        self.assertEqual(self.opened(current)['sceneRevision'], current['sceneRevision'])
        saved = self.save(request)
        self.assertEqual(self.opened(scene)['sceneRevision'], saved['sceneRevision'])
        old = self.opened(scene, current['sceneRevision'])
        self.assertEqual(old['snapshot'], current['snapshot'])
        self.assertEqual(old['terrainRefs'], current['terrainRefs'])

    def test_read_only_check_can_canonicalize_ground_samples_before_strict_save(self):
        scene = self.local_scene(); self.save(self.anchored_request(scene)); current = self.opened(scene)
        draft = copy.deepcopy(current['snapshot'])
        draft['instances'][0]['placement']['position']['longitude'] += .0001
        def resample(snapshot, *, expected_frame=None):
            result = self.geometry(snapshot, expected_frame=expected_frame)
            for item, note in zip(result['snapshot']['instances'], result['heightProvenance']):
                position, height = item['placement']['position'], item['placement']['height']
                height['sampleLongitude'] = position['longitude']; height['sampleLatitude'] = position['latitude']
                height['sampledHeightM'] = 333; note['sampledHeightM'] = 333
            return result
        checked = self.check(self.check_body(current, draft, kind='validate'), geometry=resample)
        self.assertEqual(self.opened(scene)['sceneRevision'], current['sceneRevision'])
        def strict(snapshot, *, expected_frame=None):
            for item in snapshot['instances']:
                position, height = item['placement']['position'], item['placement']['height']
                if height['sampleLongitude'] != position['longitude'] or height['sampledHeightM'] != 333:
                    raise PreviewError(422, 'TERRAIN_SAMPLE_CHANGED')
            return self.geometry(snapshot, expected_frame=expected_frame)
        self.expect('TERRAIN_SAMPLE_CHANGED', lambda: self.save(self.body(current, draft), geometry=strict))
        self.save(self.body(current, checked['proposedSnapshot']), geometry=strict)
        self.assertEqual(self.opened(scene)['snapshot']['instances'][0]['placement']['height']['sampledHeightM'], 333)

    def test_geographic_frame_terrain_and_model_replacement_remain_explicitly_closed(self):
        scene = self.local_scene(); self.save(self.anchored_request(scene)); current = self.opened(scene)
        for kind in ('frame', 'terrain', 'model'):
            request = self.body(current)
            if kind == 'frame': request['snapshot']['coordinateFrame']['originHeight'] += 1
            elif kind == 'terrain': request['snapshot']['terrain']['terrainVersionId'] = str(uuid4())
            else: request['snapshot']['instances'][0]['modelVersionId'] = str(uuid4())
            self.expect('SCENE_SCOPE_UNSUPPORTED', lambda: self.save(request))

    def test_geographic_writes_require_callbacks_and_a_fixed_resource_manifest(self):
        scene = self.local_scene(); request = self.anchored_request(scene)
        self.expect('SCENE_SCOPE_UNSUPPORTED', lambda: self.scenes.save(request, 'admin', self.authorize,
                    self.resources, self.engineering, access_revision=self.grant))
        self.expect('RESOURCE_VALIDATION_REQUIRED', lambda: self.save(request, resources=lambda _: None))
        self.assertFalse(self.scenes.capabilities()['supportsGeographic'])
        self.assertTrue(self.scenes.capabilities(geographic=True)['supportsGeographic'])

    def test_spatial_validation_and_terrain_reference_rows_are_immutable(self):
        scene = self.local_scene(); self.save(self.anchored_request(scene))
        for statement in ("update scene_spatial_validations set height_provenance='[]'", 'delete from scene_spatial_validations',
                          "update scene_terrain_uses set report_sha256='changed'", 'delete from scene_terrain_uses'):
            with self.assertRaises(sqlite3.IntegrityError):
                with self.models.connect() as db: db.execute(statement)
        self.expect('RESOURCE_IN_USE', lambda: self.scenes.assert_terrain_unused(self.terrain['terrainVersionId'], self.authorize))

    def test_retained_terrain_use_cannot_be_removed_by_emptying_current_instances(self):
        scene = self.local_scene(); self.save(self.anchored_request(scene)); geographic = self.opened(scene)
        snapshot = copy.deepcopy(geographic['snapshot']); snapshot['instances'] = []
        self.save(self.body(geographic, snapshot))
        self.expect('RESOURCE_IN_USE', lambda: self.scenes.assert_terrain_unused(self.terrain['terrainVersionId'], self.authorize))
        old = self.opened(scene, geographic['sceneRevision'])
        self.assertEqual(len(old['heightProvenance']), 1)
        self.assertEqual(len(self.opened(scene)['heightProvenance']), 0)

    def test_retained_scene_reference_prevents_deleting_the_terrain_version(self):
        scene = self.local_scene(); self.save(self.anchored_request(scene))
        with self.assertRaises(sqlite3.IntegrityError):
            with self.models.connect() as db:
                db.execute('delete from terrain_versions where id=?', (self.terrain['terrainVersionId'],))
        with self.models.connect() as db:
            self.assertIsNotNone(db.execute('select id from terrain_versions where id=?',
                                           (self.terrain['terrainVersionId'],)).fetchone())
        self.assertEqual(self.opened(scene)['terrainRefs'], [self.terrain])

    def test_calibration_identity_change_is_not_silently_adopted_by_later_save(self):
        scene = self.local_scene()
        self.content_revision = 'model-content:'+'f'*64
        self.expect('RESOURCE_CHANGED', lambda: self.save(self.body(scene)))

    def test_server_geometry_cannot_silently_change_non_sample_fields(self):
        scene = self.local_scene(); request = self.anchored_request(scene)
        def changed_result(snapshot, *, expected_frame=None):
            result = self.geometry(snapshot, expected_frame=expected_frame)
            result['snapshot']['instances'][0]['placement']['position']['longitude'] += .1
            return result
        self.expect('INVALID_GEOMETRY_RESULT', lambda: self.save(request, geometry=changed_result))


if __name__ == '__main__':
    unittest.main()
