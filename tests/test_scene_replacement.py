"""Replacement receipts and SQLite atomicity with explicitly synthetic GIS callbacks.

The geometry algorithms and HTTP authorization are covered by their real suites;
this fixture never claims a measured terrain or engineering binding.
"""
import copy
import json
import sqlite3
import unittest
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.model_validation import validate
from tests import test_scene_spatial as spatial_fixture
from tests.test_model_upload import glb


class SceneReplacementTests(unittest.TestCase):
    def setUp(self):
        self.f = spatial_fixture.SceneSpatialTests('test_anchor_check_is_read_only_and_save_retains_fixed_spatial_evidence')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        source = glb(self.f.root/'replacement.glb')
        self.candidate = self.f.models.save_upload(source, {
            'expectedSessionRevision': 'session:1', 'expectedLibraryRevision': self.f.models.listing()['libraryRevision'],
            'clientRequestId': str(uuid4()), 'displayName': 'Synthetic replacement',
            'sourceNote': 'Synthetic replacement fixture', 'rightsDeclared': True}, 'admin', validate(source), lambda: None)
        self.terrains = {self.f.terrain['terrainVersionId']: copy.deepcopy(self.f.terrain)}
        self.new_terrain = {'terrainVersionId': str(uuid4()), 'contentRevision': 'terrain-content:fixture-2',
                            'sha256': 'd'*64, 'reportSha256': 'e'*64}
        self.terrains[self.new_terrain['terrainVersionId']] = self.new_terrain
        with self.f.models.connect() as db:
            db.execute('insert into terrain_versions values (?,?,?,?,?,?,?,?,?,?)', (
                self.new_terrain['terrainVersionId'], self.new_terrain['sha256'], self.new_terrain['contentRevision'],
                'Synthetic replacement terrain', '{}', '{}', self.new_terrain['reportSha256'], '[]', 0, '2026-10-22T00:01:00Z'))
        self.can_place = True
        self.details_calls = []
        self.geometry_calls = 0
        self.replacement_calls = 0
        self.on_replacement = None
        self.sample_delta = 25.0

    def resources(self, snapshot):
        for item in snapshot['instances']:
            self.f.models.version(item['modelVersionId'])
        return {'terrains': [copy.deepcopy(self.terrains[snapshot['terrain']['terrainVersionId']])]} if snapshot['terrain'] else {'terrains': []}

    def model_details(self, identifier):
        self.details_calls.append(identifier)
        version = self.f.models.version(identifier)
        return {'modelVersionId': identifier, 'modelAssetId': self.f.asset_id, 'sha256': version['sha256'],
                'contentRevision': self.f.content_revision, 'state': 'ready', 'canPlace': self.can_place,
                'calibrationState': 'verified' if self.can_place else 'unverified',
                'calibration': {'state': 'verified', 'basePoint': [0.0, 0.0, -0.0], 'forward': [0, 0, -1]},
                'report': {'bounds': {'min': [0, 0, 0], 'max': [1, 2, 3]}}, 'components': []}

    def geometry(self, snapshot, *, expected_frame=None):
        self.geometry_calls += 1
        if expected_frame is not None:
            self.assertEqual(snapshot['coordinateFrame'], expected_frame)
        terrain = copy.deepcopy(self.terrains[snapshot['terrain']['terrainVersionId']])
        notes = []
        for item in snapshot['instances']:
            height = item['placement']['height']
            notes.append({'sceneModelInstanceId': item['sceneModelInstanceId'],
                          'kind': 'terrain_estimate' if height['mode'] == 'terrain_ground' else 'declared_absolute',
                          'verticalDatum': height['verticalDatum']})
        return {'snapshot': copy.deepcopy(snapshot), 'heightProvenance': notes,
                'displayPlacements': [{'sceneModelInstanceId': item['sceneModelInstanceId'], 'position': [0, 2.0, 0]}
                                      for item in snapshot['instances']],
                'geometrySummary': {'mode': 'projected_site', 'fieldAccuracyVerified': False},
                'resourceRefs': {'models': sorted({item['modelVersionId'] for item in snapshot['instances']}), 'terrains': [terrain]}}

    def terrain_preview(self, previous, candidate, strategy):
        self.replacement_calls += 1
        if self.on_replacement is not None:
            self.on_replacement()
        proposed = copy.deepcopy(previous)
        old_terrain = copy.deepcopy(self.terrains[previous['terrain']['terrainVersionId']])
        terrain = copy.deepcopy(self.terrains[candidate])
        proposed['terrain'] = {'terrainVersionId': candidate, 'expectedContentRevision': terrain['contentRevision']}
        frame = proposed['coordinateFrame']
        frame['frameRevision'] = 'replaced:'+candidate
        frame['anchor']['anchorHeight'] = {'mode': 'terrain_ground', 'terrainVersionId': candidate, 'offsetM': -25.0}
        impacts = []
        for item in proposed['instances']:
            item['placement']['position']['frameRevision'] = frame['frameRevision']
            height = item['placement']['height']
            if height['mode'] == 'terrain_ground':
                old_h = height['sampledHeightM'] + height['offsetM']
                if strategy == 'resample_ground' or frame['verticalDatum'] == 'UNKNOWN_RELATIVE':
                    height['sampledHeightM'] += self.sample_delta
                    if strategy == 'keep_height': height['offsetM'] = old_h-height['sampledHeightM']
                    height['terrainVersionId'], height['terrainSha256'] = candidate, terrain['sha256']
                else:
                    item['placement']['height'] = {'mode': 'absolute', 'valueM': old_h,
                        'verticalDatum': frame['verticalDatum'], 'sourceNote': 'Estimated from old terrain '+old_terrain['terrainVersionId']}
            impacts.append({'sceneModelInstanceId': item['sceneModelInstanceId']})
        result = self.geometry(proposed)
        result['impact'] = {'kind': 'terrain_replacement', 'strategy': strategy,
            'oldTerrainRef': old_terrain, 'newTerrainRef': terrain, 'instances': impacts, 'explicitConfirmationRequired': True}
        previous_heights = {item['sceneModelInstanceId']: item['placement']['height'] for item in previous['instances']}
        for note in result['heightProvenance']:
            note['previousTerrainRef'] = old_terrain
            note['previousHeight'] = copy.deepcopy(previous_heights[note['sceneModelInstanceId']])
            if strategy == 'keep_height' and previous_heights[note['sceneModelInstanceId']]['mode'] == 'terrain_ground':
                note['kind'] = 'terrain_estimate_preserved_as_absolute'
        return result

    def local(self, *, locked=False):
        return self.f.local_scene(locked=locked)

    def geographic(self, *, locked=False):
        scene = self.local(locked=locked)
        self.f.save(self.f.anchored_request(scene))
        return self.f.opened(scene)

    def check_body(self, scene, kind='model', **extra):
        body = {'kind': kind, 'sceneId': scene['sceneId'], 'expectedSceneRevision': scene['sceneRevision'],
                'snapshot': copy.deepcopy(scene['snapshot'])}
        body.update({'sceneModelInstanceId': scene['snapshot']['instances'][0]['sceneModelInstanceId'],
                     'candidateModelVersionId': self.candidate['versionId']} if kind == 'model' else {
                     'candidateTerrainVersionId': self.new_terrain['terrainVersionId'], 'strategy': 'keep_height'})
        return {**body, **extra}

    def check(self, body, **callbacks):
        return self.f.scenes.replacement_check(body, 'admin', self.f.authorize, self.resources, self.f.engineering,
            callbacks.get('geometry', self.geometry), callbacks.get('terrain', self.terrain_preview),
            callbacks.get('details', self.model_details), access_revision=self.f.grant)

    def request(self, scene, checked):
        return {**self.f.body(scene, checked['proposedSnapshot']), 'spatialChange': checked['spatialChange']}

    def save(self, body, **options):
        return self.f.scenes.save(body, options.get('actor', 'admin'), options.get('authorize', self.f.authorize),
            self.resources, self.f.engineering, validate_geometry=self.geometry,
            access_revision=options.get('grant', self.f.grant), terrain_replacement=options.get('terrain', self.terrain_preview),
            model_details=options.get('details', self.model_details))

    def expect(self, code, action):
        with self.assertRaises(PreviewError) as caught: action()
        self.assertEqual(caught.exception.code, code)

    def test_model_preview_cancel_is_read_only_and_save_retains_old_identity_and_references(self):
        scene = self.local()
        request = self.f.body(scene); request['snapshot']['instances'].append(self.f.item())
        self.f.save(request); scene = self.f.opened(scene)
        before = self.f.counts()
        checked = self.check(self.check_body(scene))
        self.assertEqual(self.f.counts(), before)
        self.assertEqual(self.f.opened(scene)['snapshot'], scene['snapshot'])
        self.assertEqual(checked['validation']['impact']['oldModel']['dimensionsM'], [1, 2, 3])
        self.assertEqual(checked['spatialChange']['kind'], 'model')
        self.assertLessEqual(len(checked['spatialChange']['receipt']), 8192)
        saved = self.save(self.request(scene, checked))
        current = self.f.opened(scene)
        self.assertEqual(current['sceneRevision'], saved['sceneRevision'])
        self.assertEqual(current['snapshot']['instances'][0]['modelVersionId'], self.candidate['versionId'])
        self.assertEqual(current['snapshot']['instances'][1], scene['snapshot']['instances'][1])
        self.assertEqual(self.f.opened(scene, scene['sceneRevision'])['snapshot'], scene['snapshot'])
        with self.f.models.connect() as db:
            self.assertEqual(db.execute('select count(*) from scene_resource_uses where model_version_id=?', (self.candidate['versionId'],)).fetchone()[0], 1)
            self.assertGreater(db.execute('select count(*) from scene_resource_uses where model_version_id=?', (self.f.model['versionId'],)).fetchone()[0], 1)

    def test_model_replacement_of_geographic_instance_keeps_entire_placement_and_camera(self):
        scene = self.geographic()
        checked = self.check(self.check_body(scene))
        self.assertEqual(checked['proposedSnapshot']['coordinateFrame'], scene['snapshot']['coordinateFrame'])
        self.assertEqual(checked['proposedSnapshot']['initialView'], scene['snapshot']['initialView'])
        self.assertEqual(checked['proposedSnapshot']['instances'][0]['placement'], scene['snapshot']['instances'][0]['placement'])
        self.save(self.request(scene, checked))
        self.assertEqual(self.f.opened(scene)['terrainRefs'], scene['terrainRefs'])

    def test_dirty_layout_requires_save_and_equal_number_representation_is_not_dirty(self):
        scene = self.local()
        for section, key, value in [('top', 'displayName', 'Dirty'), ('initialView', 'eye', [1, 2, 3]),
                                    ('defaults', 'lighting', 'dusk')]:
            body = self.check_body(scene)
            (body['snapshot'] if section == 'top' else body['snapshot'][section])[key] = value
            self.expect('SCENE_DRAFT_REQUIRES_SAVE', lambda: self.check(body))
        body = self.check_body(scene)
        body['snapshot']['initialView']['eye'][1] = float(body['snapshot']['initialView']['eye'][1])
        self.check(body)

    def test_direct_local_model_change_is_rejected_without_replacement_receipt(self):
        scene = self.local(); request = self.f.body(scene)
        request['snapshot']['instances'][0]['modelVersionId'] = self.candidate['versionId']
        self.expect('SCENE_SCOPE_UNSUPPORTED', lambda: self.save(request))
        self.expect('SCENE_SCOPE_UNSUPPORTED', lambda: self.f.check(self.f.check_body(scene, request['snapshot'], kind='validate')))

    def test_model_replacement_requires_explicit_unlocked_target_and_calibrated_resource(self):
        locked = self.local(locked=True)
        self.expect('INSTANCE_POSITION_LOCKED', lambda: self.check(self.check_body(locked)))
        scene = self.local()
        self.can_place = False
        self.expect('MODEL_CALIBRATION_REQUIRED', lambda: self.check(self.check_body(scene)))
        self.can_place = True
        self.expect('SCENE_SCOPE_UNSUPPORTED', lambda: self.check(self.check_body(scene), details=None))
        self.expect('INVALID_REQUEST', lambda: self.check(self.check_body(scene, candidateModelVersionId=self.f.model['versionId'])))
        self.expect('NOT_FOUND_OR_FORBIDDEN', lambda: self.check(self.check_body(scene, sceneModelInstanceId=str(uuid4()))))

    def test_exact_model_and_terrain_request_unions_reject_extra_fields(self):
        scene = self.local()
        for extra in ({'strategy': 'keep_height'}, {'anchor': {}}, {'candidateTerrainVersionId': self.new_terrain['terrainVersionId']}):
            self.expect('INVALID_REQUEST', lambda: self.check(self.check_body(scene, **extra)))
        self.expect('SCENE_SCOPE_UNSUPPORTED', lambda: self.check(self.check_body(scene, 'terrain')))

    def test_receipt_cannot_be_forged_or_reused_in_another_signing_namespace(self):
        scene = self.local(); checked = self.check(self.check_body(scene)); request = self.request(scene, checked)
        for receipt in ('forged', self.f.anchored_request(scene)['spatialChange']['receipt']):
            changed = copy.deepcopy(request); changed['spatialChange']['receipt'] = receipt
            self.expect('SPATIAL_PRECHECK_INVALID', lambda: self.save(changed))
        changed = copy.deepcopy(request); changed['spatialChange']['kind'] = 'terrain'
        self.expect('SPATIAL_PRECHECK_INVALID', lambda: self.save(changed))

    def test_receipt_binds_actor_grant_scene_and_exact_proposed_snapshot(self):
        scene = self.local(); request = self.request(scene, self.check(self.check_body(scene)))
        self.expect('SPATIAL_PRECHECK_INVALID', lambda: self.save(request, actor='other-admin'))
        self.expect('SPATIAL_PRECHECK_INVALID', lambda: self.save(request, grant='grant:2'))
        for key, value in [('displayName', 'Changed'), ('visible', False)]:
            changed = copy.deepcopy(request); changed['snapshot']['instances'][0][key] = value
            self.expect('SPATIAL_PRECHECK_INVALID', lambda: self.save(changed))
        changed = copy.deepcopy(request); changed['snapshot']['instances'][0]['placement']['headingDeg'] += 1e-12
        self.expect('SPATIAL_PRECHECK_INVALID', lambda: self.save(changed))
        other = self.local(); changed = copy.deepcopy(request)
        changed.update(sceneId=other['sceneId'], expectedSceneRevision=other['sceneRevision'])
        self.expect('SPATIAL_PRECHECK_INVALID', lambda: self.save(changed))

    def test_stale_head_precedes_receipt_validation(self):
        scene = self.local(); request = self.request(scene, self.check(self.check_body(scene)))
        self.f.save(self.f.body(scene))
        request['spatialChange']['receipt'] = 'forged'
        self.expect('SCENE_CHANGED', lambda: self.save(request))

    def test_lost_response_replays_once_without_geometry_and_still_requires_authorization(self):
        scene = self.geographic(); request = self.request(scene, self.check(self.check_body(scene)))
        saved = self.save(request); counts, calls = self.f.counts(), self.geometry_calls
        self.assertEqual(self.save(request), saved)
        self.assertEqual(self.f.counts(), counts); self.assertEqual(self.geometry_calls, calls)
        changed = copy.deepcopy(request); changed['snapshot']['displayName'] = 'Another payload'
        self.expect('REQUEST_CONFLICT', lambda: self.save(changed))
        self.f.allowed = False
        self.expect('SCENE_WRITE_FORBIDDEN', lambda: self.save(request))

    def test_final_revocation_rolls_back_head_audit_and_both_resource_tables(self):
        scene = self.local(); request = self.request(scene, self.check(self.check_body(scene)))
        before = self.f.counts(); calls = []
        def revoke():
            calls.append(True)
            if len(calls) == 2: raise PreviewError(403, 'SCENE_WRITE_FORBIDDEN')
        self.expect('SCENE_WRITE_FORBIDDEN', lambda: self.save(request, authorize=revoke))
        self.assertEqual(self.f.counts(), before)
        self.assertEqual(self.f.opened(scene)['sceneRevision'], scene['sceneRevision'])

    def test_changed_model_content_identity_after_preview_cannot_be_saved(self):
        scene = self.local(); request = self.request(scene, self.check(self.check_body(scene)))
        before = self.f.counts(); self.f.content_revision = 'model-content:'+'9'*64
        self.expect('RESOURCE_CHANGED', lambda: self.save(request))
        self.assertEqual(self.f.counts(), before)

    def test_terrain_keep_height_retains_old_source_and_all_old_revisions(self):
        scene = self.geographic(); before = self.f.counts()
        checked = self.check(self.check_body(scene, 'terrain'))
        self.assertEqual(self.f.counts(), before)
        self.assertEqual(checked['proposedSnapshot']['instances'][0]['placement']['height']['mode'], 'absolute')
        self.assertEqual(checked['proposedSnapshot']['initialView'], scene['snapshot']['initialView'])
        self.save(self.request(scene, checked)); current = self.f.opened(scene)
        self.assertEqual(current['terrainRefs'], [self.new_terrain])
        self.assertEqual(current['heightProvenance'][0]['previousTerrainRef'], self.f.terrain)
        self.assertEqual(self.f.opened(scene, scene['sceneRevision'])['terrainRefs'], [self.f.terrain])
        with self.f.models.connect() as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('delete from terrain_versions where id=?', (self.f.terrain['terrainVersionId'],))

    def test_terrain_resample_keeps_offset_and_changes_only_ground_height(self):
        scene = self.geographic()
        checked = self.check(self.check_body(scene, 'terrain', strategy='resample_ground'))
        before = scene['snapshot']['instances'][0]['placement']['height']
        after = checked['proposedSnapshot']['instances'][0]['placement']['height']
        self.assertEqual(after['offsetM'], before['offsetM'])
        self.assertEqual(after['sampledHeightM'], before['sampledHeightM']+25)
        self.save(self.request(scene, checked))

    def test_ordinary_save_and_model_replacement_retain_unchanged_estimated_height_basis(self):
        scene = self.geographic()
        self.save(self.request(scene, self.check(self.check_body(scene, 'terrain'))))
        current = self.f.opened(scene)
        original_note = copy.deepcopy(current['heightProvenance'][0])
        request = self.f.body(current); request['snapshot']['displayName'] = 'Renamed after replacement'
        self.save(request); renamed = self.f.opened(scene)
        note = renamed['heightProvenance'][0]
        self.assertEqual(note['kind'], 'retained_height_basis')
        self.assertEqual(note['basisKind'], 'terrain_estimate_preserved_as_absolute')
        self.assertEqual(note['basisSceneRevision'], current['sceneRevision'])
        self.assertEqual(note['previousTerrainRef'], original_note['previousTerrainRef'])
        self.assertEqual(note['previousHeight'], original_note['previousHeight'])
        checked = self.check(self.check_body(renamed))
        self.assertEqual(checked['heightProvenance'][0], note)
        self.save(self.request(renamed, checked))
        self.assertEqual(self.f.opened(scene)['heightProvenance'][0], note)

    def test_moved_absolute_instance_retains_original_sample_not_new_position(self):
        scene = self.geographic()
        self.save(self.request(scene, self.check(self.check_body(scene, 'terrain'))))
        current = self.f.opened(scene); source = current['heightProvenance'][0]['previousHeight']
        request = self.f.body(current)
        request['snapshot']['instances'][0]['placement']['position']['longitude'] += .01
        self.save(request); note = self.f.opened(scene)['heightProvenance'][0]
        self.assertEqual(note['kind'], 'retained_height_basis')
        self.assertEqual(note['previousHeight']['sampleLongitude'], source['sampleLongitude'])
        self.assertNotEqual(note['previousHeight']['sampleLongitude'], request['snapshot']['instances'][0]['placement']['position']['longitude'])

    def test_second_terrain_replacement_uses_real_saved_estimate_basis_and_keeps_new_operation_proof(self):
        scene = self.geographic()
        self.save(self.request(scene, self.check(self.check_body(scene, 'terrain'))))
        current = self.f.opened(scene)
        first_basis = copy.deepcopy(current['heightProvenance'][0])
        third = {'terrainVersionId': str(uuid4()), 'contentRevision': 'terrain-content:fixture-3',
                 'sha256': '6'*64, 'reportSha256': '7'*64}
        self.terrains[third['terrainVersionId']] = third
        with self.f.models.connect() as db:
            db.execute('insert into terrain_versions values (?,?,?,?,?,?,?,?,?,?)', (
                third['terrainVersionId'], third['sha256'], third['contentRevision'], 'Third synthetic terrain',
                '{}', '{}', third['reportSha256'], '[]', 0, '2026-10-22T00:02:00Z'))
        checked = self.check(self.check_body(current, 'terrain', candidateTerrainVersionId=third['terrainVersionId']))
        note = checked['heightProvenance'][0]
        self.assertEqual(note['kind'], 'retained_height_basis')
        self.assertEqual(note['basisKind'], 'terrain_estimate_preserved_as_absolute')
        self.assertEqual(note['previousTerrainRef'], self.new_terrain)
        self.assertEqual(note['previousHeightProvenance']['kind'], 'height_basis_summary')
        self.assertEqual(note['previousHeightProvenance']['previousSceneRevision'], current['sceneRevision'])
        self.assertEqual(note['previousHeightProvenance']['basis'], first_basis['heightBasis'])
        self.assertEqual(note['heightBasis']['terrainRef'], self.f.terrain)
        self.save(self.request(current, checked))
        reopened = self.f.opened(scene)
        self.assertEqual(reopened['heightProvenance'][0], note)
        self.assertEqual(reopened['validation']['impact']['newTerrainRef'], third)
        self.assertEqual(reopened['snapshot']['instances'][0]['placement']['height'], current['snapshot']['instances'][0]['placement']['height'])

    def test_repeated_terrain_replacements_keep_flat_bounded_original_height_basis(self):
        scene = self.geographic()
        original_height = copy.deepcopy(scene['snapshot']['instances'][0]['placement']['height'])
        sizes, depths = [], []
        def depth(value):
            if isinstance(value, dict): return 1+max((depth(item) for item in value.values()), default=0)
            if isinstance(value, list): return 1+max((depth(item) for item in value), default=0)
            return 0
        for index in range(32):
            previous_revision = scene['sceneRevision']
            candidate = self.new_terrain if index % 2 == 0 else self.f.terrain
            checked = self.check(self.check_body(scene, 'terrain', candidateTerrainVersionId=candidate['terrainVersionId']))
            self.save(self.request(scene, checked)); scene = self.f.opened(scene)
            note = scene['heightProvenance'][0]
            self.assertEqual(note['heightBasis']['height'], original_height)
            self.assertEqual(note['heightBasis']['terrainRef'], self.f.terrain)
            self.assertEqual(note['previousHeightProvenance']['previousSceneRevision'], previous_revision)
            self.assertEqual(note['previousHeightProvenance']['basis'], note['heightBasis'])
            self.assertEqual(note['previousTerrainRef'], self.f.terrain if index % 2 == 0 else self.new_terrain)
            sizes.append(len(json.dumps(scene['heightProvenance']).encode()))
            depths.append(depth(scene['heightProvenance']))
        self.assertLessEqual(max(sizes), 4096)
        self.assertLessEqual(max(depths), 8)
        self.assertLessEqual(max(sizes[1:])-min(sizes[1:]), 100)

    def test_changed_height_or_source_does_not_reuse_estimate_or_copy_basis_to_new_instance(self):
        for field, value in [('valueM', 303), ('sourceNote', 'New independent height declaration')]:
            scene = self.geographic()
            self.save(self.request(scene, self.check(self.check_body(scene, 'terrain'))))
            current = self.f.opened(scene); request = self.f.body(current)
            request['snapshot']['instances'][0]['placement']['height'][field] = value
            self.save(request); note = self.f.opened(scene)['heightProvenance'][0]
            self.assertEqual(note['kind'], 'declared_absolute')
            self.assertNotIn('previousTerrainRef', note)
        scene = self.geographic()
        self.save(self.request(scene, self.check(self.check_body(scene, 'terrain'))))
        current = self.f.opened(scene); request = self.f.body(current)
        added = copy.deepcopy(request['snapshot']['instances'][0]); added['sceneModelInstanceId'] = str(uuid4())
        request['snapshot']['instances'].append(added)
        self.save(request); notes = self.f.opened(scene)['heightProvenance']
        self.assertEqual(notes[0]['kind'], 'retained_height_basis')
        self.assertEqual(notes[1]['kind'], 'declared_absolute')
        self.assertNotIn('previousTerrainRef', notes[1])

    def test_locked_terrain_instance_accepts_keep_height_but_refuses_actual_height_change(self):
        scene = self.geographic(locked=True)
        self.expect('INSTANCE_POSITION_LOCKED', lambda: self.check(self.check_body(scene, 'terrain', strategy='resample_ground')))
        checked = self.check(self.check_body(scene, 'terrain'))
        self.save(self.request(scene, checked))
        self.assertTrue(self.f.opened(scene)['snapshot']['instances'][0]['positionLocked'])

    def test_terrain_callback_cannot_change_unrelated_scene_or_instance_fields(self):
        scene = self.geographic()
        for change in ('camera', 'model', 'name', 'longitude'):
            def broken(previous, candidate, strategy):
                result = self.terrain_preview(previous, candidate, strategy)
                snapshot = result['snapshot']
                if change == 'camera': snapshot['initialView']['eye'][0] += 1
                elif change == 'model': snapshot['instances'][0]['modelVersionId'] = self.candidate['versionId']
                elif change == 'name': snapshot['instances'][0]['displayName'] = 'Changed'
                else: snapshot['instances'][0]['placement']['position']['longitude'] += .001
                return result
            self.expect('INVALID_GEOMETRY_RESULT', lambda: self.check(self.check_body(scene, 'terrain'), terrain=broken))

    def test_changed_terrain_proof_after_preview_and_recomputed_candidate_are_refused(self):
        scene = self.geographic(); request = self.request(scene, self.check(self.check_body(scene, 'terrain', strategy='resample_ground')))
        before = self.f.counts()
        self.sample_delta = 26.0
        self.expect('SPATIAL_PRECHECK_INVALID', lambda: self.save(request))
        self.assertEqual(self.f.counts(), before)
        self.sample_delta = 25.0; self.new_terrain['reportSha256'] = 'f'*64
        self.expect('SPATIAL_PRECHECK_INVALID', lambda: self.save(request))
        self.assertEqual(self.f.counts(), before)

    def test_terrain_replacement_runs_outside_write_lock_and_final_cas_stops_race(self):
        scene = self.geographic(); request = self.request(scene, self.check(self.check_body(scene, 'terrain')))
        def race():
            self.on_replacement = None
            self.save(self.f.body(scene))
        self.on_replacement = race
        self.expect('SCENE_CHANGED', lambda: self.save(request))
        self.assertEqual(self.f.opened(scene)['terrainRefs'], scene['terrainRefs'])

    def test_browser_number_round_trip_and_negative_zero_do_not_invalidate_model_receipt(self):
        scene = self.local(); stored = self.f.body(scene)
        stored['snapshot']['instances'][0]['placement']['headingDeg'] = 30.0
        stored['snapshot']['instances'][0]['placement']['position']['xM'] = -0.0
        self.f.save(stored); scene = self.f.opened(scene)
        request = self.request(scene, self.check(self.check_body(scene)))
        request['snapshot']['instances'][0]['placement']['headingDeg'] = 30
        request['snapshot']['instances'][0]['placement']['position']['xM'] = 0
        self.save(request)

    def test_terrain_signature_still_rejects_direct_or_tampered_replacement(self):
        scene = self.geographic(); request = self.request(scene, self.check(self.check_body(scene, 'terrain')))
        direct = copy.deepcopy(request); direct.pop('spatialChange')
        self.expect('SCENE_SCOPE_UNSUPPORTED', lambda: self.save(direct))
        changed = copy.deepcopy(request); changed['snapshot']['instances'][0]['placement']['height']['valueM'] += 1e-12
        self.expect('SPATIAL_PRECHECK_INVALID', lambda: self.save(changed))
        self.expect('INVALID_REQUEST', lambda: self.check(self.check_body(scene, 'terrain', candidateTerrainVersionId=self.f.terrain['terrainVersionId'])))


if __name__ == '__main__': unittest.main()
