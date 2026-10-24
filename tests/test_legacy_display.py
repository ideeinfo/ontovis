"""Explicit legacy display on synthetic GLB/private SQLite; no field calibration."""
import copy
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.scene_library import SceneLibrary
from tests import test_resource_reuse as reuse


class LegacyDisplayTests(unittest.TestCase):
    setUp = reuse.ResourceReuseTests.setUp
    body = reuse.ResourceReuseTests.body
    imported = reuse.ResourceReuseTests.imported
    count = reuse.ResourceReuseTests.count
    old_records = reuse.ResourceReuseTests.old_records
    expect = reuse.ResourceReuseTests.expect
    assert_slot = reuse.ResourceReuseTests.assert_slot

    def preservation(self, source, **changes):
        return {'modelVersionId': source['modelVersionId'], 'expectedContentRevision': source['contentRevision'],
            'expectedLibraryRevision': self.library.listing()['libraryRevision'], 'clientRequestId': str(uuid4()),
            'preservationBasis': {'mode': 'preserve_legacy_display', 'sourceNote': 'Preserve synthetic old display; no field direction.'}, **changes}

    def preserve(self, source, body=None, *, actor='resource-admin', guard=None):
        return self.models.preserve_legacy_display(body or self.preservation(source), actor, guard or (lambda: None))

    def ordinary_upload(self):
        return self.models.upload(io.BytesIO(self.data), len(self.data), {
            'expectedLibraryRevision': self.library.listing()['libraryRevision'], 'clientRequestId': str(uuid4()),
            'displayName': 'Ordinary synthetic upload', 'purpose': 'equipment', 'sourceNote': 'Synthetic data',
            'rightsDeclared': True}, 'resource-admin', lambda: None)

    def calibration(self, source):
        return self.models.calibrate({'modelVersionId': source['modelVersionId'],
            'expectedContentRevision': source['contentRevision'], 'expectedLibraryRevision': self.library.listing()['libraryRevision'],
            'clientRequestId': str(uuid4()), 'calibration': {'unit': 'm', 'axes': 'Y_UP_RIGHT_HANDED',
                'basePoint': [0, 0, 0], 'forward': [0, 0, -1]}}, 'resource-admin', lambda: None)

    def test_preservation_creates_fixed_identity_display_with_exact_source_and_no_binding_or_quality_upgrade(self):
        source = self.imported(); previous = copy.deepcopy(source); old = self.old_records()
        result = self.preserve(source)
        self.assertEqual(self.count(), (3, 1, 2, 2, 2))
        self.assertEqual(result['modelAssetId'], source['modelAssetId'])
        self.assertNotEqual(result['modelVersionId'], source['modelVersionId'])
        self.assertNotEqual(result['contentRevision'], source['contentRevision'])
        self.assertEqual(result['sha256'], source['sha256']); self.assertEqual(result['components'], source['components'])
        self.assertTrue(result['canPlace']); self.assertFalse(result['canPlaceGeographic'])
        self.assertEqual(result['calibrationState'], 'legacy_display')
        calibration = result['calibration']
        self.assertEqual(calibration['modelToCalibrated'], [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1])
        self.assertEqual(calibration['sourceModelVersionId'], self.legacy['versionId'])
        self.assertEqual(calibration['sourceSha256'], self.legacy['sha256'])
        self.assertEqual(calibration['preservedBy'], 'resource-admin'); self.assertRegex(calibration['preservedAt'], r'^20\d\d-')
        self.assertTrue({'basePoint','forward','verifiedBy','verifiedAt'}.isdisjoint(calibration))
        self.assertEqual(result['report']['coordinateVerification'], 'legacy_display_preserved')
        self.assertNotIn('calibrationVerification', result['report'])
        self.assertEqual(result['sourceModelVersionId'], source['modelVersionId'])
        self.assertEqual(self.models.content(result['modelVersionId'], result['contentRevision'], result['sha256'], lambda: None), self.data)
        self.assertEqual(self.models.model(source['modelAssetId'], source['modelVersionId'], lambda: None)['calibration'], previous['calibration'])
        self.assertEqual(self.old_records(), old)
        self.assertEqual(self.library.version(result['modelVersionId'])['bindings'], [])
        identity = self.models.content_identity(result['modelVersionId'])
        self.assertTrue(identity['canPlace']); self.assertFalse(identity['canPlaceGeographic'])
        self.assertEqual(identity['contentRevision'], result['contentRevision'])
        self.assertFalse(self.models.content_identity(source['modelVersionId'])['canPlaceGeographic'])

    def test_new_upload_verified_and_already_preserved_versions_cannot_request_preservation(self):
        self.expect('INVALID_REQUEST', lambda: self.preserve(self.ordinary_upload()))
        source = self.imported(); preserved = self.preserve(source); verified = self.calibration(source)
        self.assertTrue(verified['canPlaceGeographic'])
        for version in (preserved, verified):
            with self.subTest(state=version['calibrationState']):
                before = self.count()
                self.expect('INVALID_REQUEST', lambda: self.preserve(version))
                self.assertEqual(self.count(), before); self.assert_slot()

    def test_preservation_body_cannot_self_assert_matrix_state_author_source_or_unknown_basis(self):
        source = self.imported(); original = self.preservation(source)
        for field in ('matrix', 'verifiedBy', 'preservedBy', 'sourceSha256', 'state'):
            for nested in (False, True):
                with self.subTest(field=field, nested=nested):
                    body = copy.deepcopy(original)
                    (body['preservationBasis'] if nested else body)[field] = 'client-untrusted'
                    self.expect('INVALID_REQUEST', lambda: self.preserve(source, body))
        for value in ({'mode': 'verified', 'sourceNote': 'Synthetic'}, {'mode': 'preserve_legacy_display', 'sourceNote': ''}):
            self.expect('INVALID_REQUEST', lambda: self.preserve(source, {**original, 'preservationBasis': value}))
        self.assertEqual(self.count(), (2, 1, 1, 1, 1))

    def test_original_permission_audit_and_import_action_are_required_again(self):
        source = self.imported()
        with self.library.connect() as db:
            db.execute("update audit set payload='{}' where action='model_uploaded'")
        self.expect('MODEL_SOURCE_RIGHTS_REQUIRED', lambda: self.preserve(source))
        with self.library.connect() as db:
            db.execute("update audit set payload=? where action='model_uploaded'", (json.dumps({'sha256': self.legacy['sha256'], 'rightsDeclared': True}),))
            db.execute("delete from project_model_audit where action='import_existing'")
        self.expect('INVALID_REQUEST', lambda: self.preserve(source))
        self.assertEqual(self.count(), (2, 1, 1, 1, 0)); self.assert_slot()

    def test_changed_or_symlinked_old_source_cannot_certify_an_unchanged_import_copy(self):
        source = self.imported(); path = self.library.root/'files'/(self.legacy['versionId']+'.glb')
        original = path.read_bytes()
        path.write_bytes(original[:-1]+bytes([original[-1]^1]))
        self.expect('RESOURCE_CHANGED', lambda: self.preserve(source))
        path.unlink(); path.symlink_to(self.library.root/'files'/(source['modelVersionId']+'.glb'))
        self.expect('RESOURCE_CHANGED', lambda: self.preserve(source))
        self.assertEqual(self.count(), (2, 1, 1, 1, 1)); self.assert_slot()

    def test_idempotency_replays_before_library_changes_but_rechecks_authorization_and_actor_namespace(self):
        source = self.imported(); body = self.preservation(source); first = self.preserve(source, body)
        self.ordinary_upload()
        self.assertEqual(self.preserve(source, body), first)
        self.expect('REQUEST_CONFLICT', lambda: self.preserve(source, {**body,
            'preservationBasis': {**body['preservationBasis'], 'sourceNote': 'Changed declaration'}}))
        def denied(): raise PreviewError(403, 'MODEL_WRITE_FORBIDDEN')
        self.expect('MODEL_WRITE_FORBIDDEN', lambda: self.preserve(source, body, guard=denied))
        other = self.preserve(source, {**body, 'expectedLibraryRevision': self.library.listing()['libraryRevision']}, actor='another-admin')
        self.assertNotEqual(other['modelVersionId'], first['modelVersionId'])

    def test_old_content_and_library_cas_reject_without_registering_or_leaking_slot(self):
        source = self.imported(); before = self.count()
        for field in ('expectedContentRevision', 'expectedLibraryRevision'):
            self.expect('RESOURCE_CHANGED' if field == 'expectedContentRevision' else 'MODEL_LIBRARY_CHANGED',
                lambda: self.preserve(source, self.preservation(source, **{field: 'stale:1'})))
            self.assertEqual(self.count(), before); self.assert_slot()
        self.assertEqual(list((self.library.root/'temporary').iterdir()), [])

    def test_revocation_at_final_commit_rolls_back_new_version_and_private_file(self):
        source = self.imported(); before = self.count(); files = sorted((self.library.root/'files').iterdir()); calls = []
        def authorize():
            calls.append(True)
            if len(calls) == 4: raise PreviewError(403, 'MODEL_WRITE_FORBIDDEN')
        self.expect('MODEL_WRITE_FORBIDDEN', lambda: self.preserve(source, guard=authorize))
        self.assertEqual(len(calls), 4); self.assertEqual(self.count(), before)
        self.assertEqual(sorted((self.library.root/'files').iterdir()), files); self.assert_slot()

    def test_source_bytes_are_rechecked_after_final_authorization(self):
        source = self.imported(); before = self.count()
        for identifier in (self.legacy['versionId'], source['modelVersionId']):
            with self.subTest(imported=identifier == source['modelVersionId']):
                calls = []; path = self.library.root/'files'/(identifier+'.glb'); original = path.read_bytes()
                def authorize():
                    calls.append(True)
                    if len(calls) == 4: path.write_bytes(original[:-1]+bytes([original[-1]^1]))
                try: self.expect('RESOURCE_CHANGED', lambda: self.preserve(source, guard=authorize))
                finally: path.write_bytes(original)
                self.assertEqual(self.count(), before); self.assert_slot()

    def test_cleanup_failure_releases_slot_and_original_request_can_recover_committed_version(self):
        source = self.imported(); body = self.preservation(source); unlink = Path.unlink
        def fail(path, *args, **options):
            if path.name.startswith('project-calibration-'): raise PermissionError('Synthetic cleanup failure')
            return unlink(path, *args, **options)
        with patch.object(Path, 'unlink', fail):
            self.expect('MODEL_STORAGE_UNAVAILABLE', lambda: self.preserve(source, body))
        self.assert_slot(); self.assertEqual(self.count(), (3, 1, 2, 2, 2))
        self.assertEqual(self.preserve(source, body)['calibrationState'], 'legacy_display')

    def test_normal_calibration_from_preserved_version_creates_new_verified_content(self):
        source = self.imported(); preserved = self.preserve(source); verified = self.calibration(preserved)
        self.assertNotEqual(verified['modelVersionId'], preserved['modelVersionId'])
        self.assertEqual(verified['calibrationState'], 'verified'); self.assertTrue(verified['canPlaceGeographic'])
        self.assertEqual(verified['sourceModelVersionId'], preserved['modelVersionId'])
        self.assertEqual(verified['report']['coordinateVerification'], 'operator_calibrated')
        self.assertEqual(self.models.model(preserved['modelAssetId'], preserved['modelVersionId'], lambda: None)['calibrationState'], 'legacy_display')

    def test_local_replacement_summary_keeps_unknown_base_and_forward_but_geo_summary_refuses(self):
        value = self.preserve(self.imported())
        ref = {key: value[key] for key in ('modelAssetId','modelVersionId','contentRevision','sha256')}
        summary = SceneLibrary._model_summary(value, value['modelVersionId'], ref, frame_mode='local_plane')
        self.assertIsNone(summary['basePoint']); self.assertIsNone(summary['forward'])
        self.assertEqual(summary['componentCount'], len(value['components']))
        self.expect('MODEL_GEOGRAPHIC_CALIBRATION_REQUIRED',
            lambda: SceneLibrary._model_summary(value, value['modelVersionId'], ref, frame_mode='projected_site'))


if __name__ == '__main__': unittest.main()
