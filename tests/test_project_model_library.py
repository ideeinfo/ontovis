"""Project model versions over real private SQLite, files and synthetic GLB."""
import copy
import hashlib
import io
import json
import math
from pathlib import Path
import sqlite3
import tempfile
from threading import Barrier, Thread
import unittest
from unittest.mock import patch
from uuid import uuid4
from uuid import UUID

from apps.api.authority import PreviewError
from apps.api.model_library import ModelLibrary
from apps.api.model_validation import MAX_BYTES, validate
from apps.api.project_model_library import ProjectModelLibrary
from apps.api.scene_library import SceneLibrary
from tests.test_model_upload import glb


CONTEXT = '00000000-0000-0000-0000-000000000071'


class Guard:
    def __init__(self): self.allowed = True
    def __call__(self):
        if not self.allowed: raise PreviewError(403, 'MODEL_WRITE_FORBIDDEN')


class ProjectModelLibraryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.old = ModelLibrary(self.root / 'private', 'fixture-project', CONTEXT)
        self.models = ProjectModelLibrary(self.old)
        self.path = glb(self.root / 'source.glb')
        self.data = self.path.read_bytes()
        self.guard = Guard()

    def metadata(self, **changes):
        return {'expectedLibraryRevision': self.old.listing()['libraryRevision'], 'clientRequestId': str(uuid4()),
            'displayName': '合成设备模型', 'purpose': 'equipment', 'sourceNote': 'Synthetic fixture only',
            'rightsDeclared': True, **changes}

    def upload(self, metadata=None, *, actor='fixture-admin', guard=None, data=None):
        data = self.data if data is None else data
        return self.models.upload(io.BytesIO(data), len(data), metadata or self.metadata(), actor, guard or self.guard)

    def calibration(self, source, **changes):
        return {'modelVersionId': source['modelVersionId'], 'expectedContentRevision': source['contentRevision'],
            'expectedLibraryRevision': self.old.listing()['libraryRevision'], 'clientRequestId': str(uuid4()),
            'calibration': {'unit': 'm', 'axes': 'Y_UP_RIGHT_HANDED',
                            'basePoint': [10, 2, -3], 'forward': [4, 0, 3]}, **changes}

    def calibrate(self, source, body=None, *, actor='fixture-admin', guard=None):
        return self.models.calibrate(body or self.calibration(source), actor, guard or self.guard)

    def listing(self, **kwargs):
        return self.models.listing('fixture-admin', self.guard, access_revision='grant:1', **kwargs)

    def model(self, value, guard=None):
        return self.models.model(value['modelAssetId'], value['modelVersionId'], guard or self.guard)

    def counts(self):
        with self.old.connect() as db:
            return tuple(db.execute('select count(*) from ' + table).fetchone()[0] for table in (
                'versions', 'project_model_assets', 'project_model_versions', 'project_model_requests', 'project_model_audit'))

    def retain_synthetic_versions(self, source, total, *, legacy_versions=0):
        # Populate retained rows/files without rerunning the GLB worker per row.
        with self.old.connect() as db:
            existing = db.execute('select count(*) from versions').fetchone()[0]
            for index in range(total - existing):
                identifier, asset_id = str(uuid4()), str(uuid4())
                (self.old.root / 'files' / (identifier + '.glb')).write_bytes(self.data)
                db.execute('insert into versions select ?,?,actor,name,source_note,sha256,bytes,created_at,revision,components,report from versions where id=?',
                           (identifier, str(uuid4()), source['modelVersionId']))
                if index < legacy_versions: continue
                db.execute('insert into project_model_assets select ?,project_code,name,purpose,revision,created_at from project_model_assets where id=?',
                           (asset_id, source['modelAssetId']))
                db.execute('insert into project_model_versions select ?,?,content_revision,calibration,null from project_model_versions where version_id=?',
                           (identifier, asset_id, source['modelVersionId']))
            db.execute('update library set revision=revision+? where id=1', (total - existing,))

    def expect(self, code, callback):
        with self.assertRaises(PreviewError) as caught: callback()
        self.assertEqual(caught.exception.code, code)

    def test_upload_is_project_resource_unverified_and_fixed_file_survives_reopen(self):
        value = self.upload()
        self.assertEqual(value['state'], 'ready')
        self.assertEqual(value['calibration'], {'state': 'unverified'})
        self.assertFalse(value['canPlace'])
        self.assertEqual(value['sha256'], hashlib.sha256(self.data).hexdigest())
        self.assertNotIn('bindings', value)
        self.assertNotIn('modelRevision', value)
        self.assertNotIn(str(self.root), json.dumps(value))
        self.assertEqual(self.counts(), (1, 1, 1, 1, 1))
        reopened = ProjectModelLibrary(ModelLibrary(self.root / 'private', 'fixture-project', CONTEXT))
        result = reopened.model(value['modelAssetId'], value['modelVersionId'], self.guard)
        self.assertEqual(result['contentRevision'], value['contentRevision'])
        self.assertEqual(reopened.content(value['modelVersionId'], value['contentRevision'], value['sha256'], self.guard), self.data)
        self.assertEqual((self.old.root / 'files' / (value['modelVersionId'] + '.glb')).stat().st_mode & 0o777, 0o600)

    def test_append_fixed_version_reuses_asset_without_modifying_old_version(self):
        first = self.upload()
        second = self.upload(self.metadata(modelAssetId=first['modelAssetId']))
        self.assertEqual(first['modelAssetId'], second['modelAssetId'])
        self.assertNotEqual(first['modelVersionId'], second['modelVersionId'])
        self.assertEqual(self.model(first)['contentRevision'], first['contentRevision'])
        listed = self.listing()['items']
        self.assertEqual(len(listed), 1)
        self.assertEqual(len(listed[0]['versions']), 2)
        self.assertNotEqual(first['assetRevision'], listed[0]['assetRevision'])
        self.expect('MODEL_ASSET_CHANGED', lambda: self.upload(self.metadata(modelAssetId=first['modelAssetId'], purpose='environment')))
        self.expect('MODEL_ASSET_CHANGED', lambda: self.upload(self.metadata(modelAssetId=first['modelAssetId'], displayName='Implicit rename')))

    def test_calibration_creates_fixed_new_version_server_identity_and_rigid_matrix(self):
        source = self.upload()
        body = self.calibration(source)
        calibrated = self.calibrate(source, body)
        self.assertEqual(calibrated['sha256'], source['sha256'])
        self.assertNotEqual(calibrated['modelVersionId'], source['modelVersionId'])
        self.assertNotEqual(calibrated['contentRevision'], source['contentRevision'])
        self.assertEqual(calibrated['sourceModelVersionId'], source['modelVersionId'])
        self.assertTrue(calibrated['canPlace'])
        calibration = calibrated['calibration']
        self.assertEqual(calibration['verifiedBy'], 'fixture-admin')
        self.assertRegex(calibration['verifiedAt'], r'^20\d\d-\d\d-\d\dT')
        matrix = calibration['modelToCalibrated']
        def apply(point): return [sum(matrix[4 * column + row] * point[column] for column in range(3)) + matrix[12 + row] for row in range(3)]
        for number in apply(body['calibration']['basePoint']): self.assertAlmostEqual(number, 0)
        direction = [sum(matrix[4 * column + row] * calibration['forward'][column] for column in range(3)) for row in range(3)]
        for actual, expected in zip(direction, [0, 0, -1]): self.assertAlmostEqual(actual, expected)
        for left in range(3):
            for right in range(3):
                self.assertAlmostEqual(sum(matrix[4 * left + row] * matrix[4 * right + row] for row in range(3)), int(left == right))
        determinant = matrix[0] * matrix[10] - matrix[8] * matrix[2]
        self.assertAlmostEqual(determinant, 1)
        self.assertEqual(calibrated['components'], source['components'])
        self.assertEqual(calibrated['report']['calibrationVerification']['calibratedBounds'], [[5.4, -2.0, 2.2], [8.4, -1.0, 6.2]])
        self.assertFalse(self.model(source)['canPlace'])
        self.assertEqual(self.models.content(source['modelVersionId'], source['contentRevision'], source['sha256'], self.guard), self.data)
        self.assertEqual(self.models.content(calibrated['modelVersionId'], calibrated['contentRevision'], calibrated['sha256'], self.guard), self.data)

    def test_calibration_supports_positive_negative_axes_and_declared_base_origin(self):
        source = self.upload()
        for forward in ([0, 0, -1], [0, 0, 1], [1, 0, 0], [-1, 0, 0]):
            body = self.calibration(source)
            body['calibration'].update(basePoint=[0, 0, 0], forward=forward)
            value = self.calibrate(source, body)
            matrix = value['calibration']['modelToCalibrated']
            self.assertAlmostEqual(matrix[0] * forward[0] + matrix[8] * forward[2], 0)
            self.assertAlmostEqual(matrix[2] * forward[0] + matrix[10] * forward[2], -1)
            self.assertEqual(matrix[12:15], [0, 0, 0])

    def test_nonzero_subnormal_forward_is_normalized_without_scale_or_overflow(self):
        source = self.upload()
        body = self.calibration(source)
        body['calibration']['forward'] = [5e-324, 0, 5e-324]
        calibration = self.calibrate(source, body)['calibration']
        self.assertAlmostEqual(math.hypot(calibration['forward'][0], calibration['forward'][2]), 1)
        matrix = calibration['modelToCalibrated']
        self.assertAlmostEqual(matrix[0] ** 2 + matrix[2] ** 2, 1)

    def test_upload_and_calibration_replay_prioritize_real_actor_action_over_stale_revision(self):
        metadata = self.metadata(expectedSessionRevision='first-transport')
        source = self.upload(metadata)
        replay = self.upload({**metadata, 'expectedSessionRevision': 'different-transport'})
        self.assertEqual(source, replay)
        self.expect('REQUEST_CONFLICT', lambda: self.upload({**metadata, 'sourceNote': 'different'}))
        other = self.upload({**metadata, 'expectedLibraryRevision': self.old.listing()['libraryRevision']}, actor='other-admin')
        self.assertNotEqual(other['modelVersionId'], source['modelVersionId'])
        body = self.calibration(source, clientRequestId=metadata['clientRequestId'], expectedSessionRevision='transport-one')
        calibrated = self.calibrate(source, body)
        self.assertEqual(self.calibrate(source, {**body, 'expectedSessionRevision': 'transport-two'}), calibrated)
        different = copy.deepcopy(body); different['calibration']['basePoint'][0] = 11
        self.expect('REQUEST_CONFLICT', lambda: self.calibrate(source, different))
        self.assertEqual(self.counts(), (3, 2, 3, 3, 3))

    def test_same_request_id_different_bytes_is_a_conflict(self):
        metadata = self.metadata()
        self.upload(metadata)
        different = glb(self.root / 'different.glb', lambda document: document['nodes'][0].update(translation=[99, 0, 0])).read_bytes()
        self.expect('REQUEST_CONFLICT', lambda: self.upload(metadata, data=different))
        self.assertEqual(self.counts(), (1, 1, 1, 1, 1))

    def test_expected_library_and_content_conditions_reject_without_audit_or_files(self):
        stale = self.metadata()
        source = self.upload()
        before = self.counts()
        self.expect('MODEL_LIBRARY_CHANGED', lambda: self.upload(stale))
        body = self.calibration(source, expectedContentRevision='wrong-fixed-content')
        self.expect('RESOURCE_CHANGED', lambda: self.calibrate(source, body))
        body = self.calibration(source, expectedLibraryRevision=stale['expectedLibraryRevision'])
        self.expect('MODEL_LIBRARY_CHANGED', lambda: self.calibrate(source, body))
        self.assertEqual(self.counts(), before)
        self.assertEqual(len(list((self.old.root / 'files').glob('*.glb'))), 1)
        self.assertEqual(list((self.old.root / 'temporary').iterdir()), [])

    def test_two_actual_sqlite_writers_using_one_head_commit_only_one_version(self):
        other_old = ModelLibrary(self.old.root, 'fixture-project', CONTEXT)
        other = ProjectModelLibrary(other_old)
        barrier, results = Barrier(2), []
        revision = self.old.listing()['libraryRevision']
        def process(path):
            result = validate(path); barrier.wait(timeout=3); return result
        def write(models):
            try:
                value = models.upload(io.BytesIO(self.data), len(self.data), self.metadata(expectedLibraryRevision=revision), 'fixture-admin', self.guard)
                results.append(value['modelVersionId'])
            except PreviewError as error: results.append(error.code)
        with patch.object(self.old, 'process', side_effect=process), patch.object(other_old, 'process', side_effect=process):
            threads = [Thread(target=write, args=(models,)) for models in (self.models, other)]
            for thread in threads: thread.start()
            for thread in threads: thread.join(5)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(results.count('MODEL_LIBRARY_CHANGED'), 1)
        self.assertEqual(self.counts(), (1, 1, 1, 1, 1))
        self.assertEqual(len(list((self.old.root / 'files').glob('*.glb'))), 1)

    def test_authorization_start_replay_and_final_commit_failure_leave_no_success_audit(self):
        self.guard.allowed = False
        self.expect('MODEL_WRITE_FORBIDDEN', lambda: self.upload())
        self.assertEqual(self.counts(), (0, 0, 0, 0, 0))
        self.guard.allowed = True
        metadata = self.metadata(); source = self.upload(metadata)
        self.guard.allowed = False
        self.expect('MODEL_WRITE_FORBIDDEN', lambda: self.upload(metadata))
        self.expect('MODEL_WRITE_FORBIDDEN', lambda: self.model(source))
        self.guard.allowed = True
        before = self.counts()
        def final_guard():
            with self.old.connect() as db:
                # A second connection cannot see the uncommitted registration;
                # filesystem publication identifies the final transaction check.
                count = db.execute('select count(*) from versions').fetchone()[0]
            if len(list((self.old.root / 'files').glob('*.glb'))) > count:
                raise PreviewError(403, 'MODEL_WRITE_FORBIDDEN')
        self.expect('MODEL_WRITE_FORBIDDEN', lambda: self.calibrate(source, guard=final_guard))
        self.assertEqual(self.counts(), before)
        self.assertEqual(len(list((self.old.root / 'files').glob('*.glb'))), 1)
        self.assertEqual(list((self.old.root / 'temporary').iterdir()), [])

    def test_revocation_after_processing_or_receiving_prevents_registration(self):
        original = self.old.process
        def process(path):
            result = original(path); self.guard.allowed = False; return result
        with patch.object(self.old, 'process', side_effect=process):
            self.expect('MODEL_WRITE_FORBIDDEN', lambda: self.upload())
        self.guard.allowed = True
        guard = self.guard
        class Stream(io.BytesIO):
            def read(self, length):
                data = super().read(length); guard.allowed = False; return data
        self.expect('MODEL_WRITE_FORBIDDEN', lambda: self.models.upload(Stream(self.data), len(self.data), self.metadata(), 'fixture-admin', self.guard))
        self.assertEqual(self.counts(), (0, 0, 0, 0, 0))

    def test_private_content_rechecks_authorization_after_bytes_and_refuses_fingerprint_or_paths(self):
        source = self.upload()
        self.expect('RESOURCE_CHANGED', lambda: self.models.content(source['modelVersionId'], 'stale', source['sha256'], self.guard))
        self.expect('RESOURCE_CHANGED', lambda: self.models.content(source['modelVersionId'], source['contentRevision'], '0' * 64, self.guard))
        self.expect('INVALID_REQUEST', lambda: self.models.content('../source.glb', source['contentRevision'], source['sha256'], self.guard))
        original = self.models._content
        def read(value):
            result = original(value); self.guard.allowed = False; return result
        with patch.object(self.models, '_content', side_effect=read):
            self.expect('MODEL_WRITE_FORBIDDEN', lambda: self.models.content(source['modelVersionId'], source['contentRevision'], source['sha256'], self.guard))

    def test_tampered_file_and_symlink_never_become_calibrated_or_readable(self):
        source = self.upload()
        path = self.old.root / 'files' / (source['modelVersionId'] + '.glb')
        path.write_bytes(b'x' * len(self.data))
        self.expect('RESOURCE_CHANGED', lambda: self.model(source))
        self.expect('RESOURCE_CHANGED', lambda: self.calibrate(source))
        path.unlink(); path.symlink_to(self.path)
        self.expect('RESOURCE_CHANGED', lambda: self.model(source))
        self.assertEqual(self.counts(), (1, 1, 1, 1, 1))

    def test_unknown_fields_server_only_calibration_and_invalid_vectors_are_refused(self):
        for field in ('url', 'path', 'actor', 'bindings', 'calibration'):
            self.expect('INVALID_REQUEST', lambda: self.upload(self.metadata(**{field: 'untrusted'})))
        self.expect('MODEL_RIGHTS_REQUIRED', lambda: self.upload(self.metadata(rightsDeclared=False)))
        source = self.upload()
        for alteration, code in (
                (lambda item: item.update(verifiedBy='spoofed'), 'INVALID_REQUEST'),
                (lambda item: item.update(verifiedAt='spoofed'), 'INVALID_REQUEST'),
                (lambda item: item.update(modelToCalibrated=[1] * 16), 'INVALID_REQUEST'),
                (lambda item: item.update(unit='mm'), 'UNSUPPORTED_CALIBRATION'),
                (lambda item: item.update(axes='Z_UP'), 'UNSUPPORTED_CALIBRATION'),
                (lambda item: item.update(forward=[0, 0, 0]), 'INVALID_CALIBRATION'),
                (lambda item: item.update(forward=[1, 1, 0]), 'INVALID_CALIBRATION'),
                (lambda item: item.update(basePoint=[True, 0, 0]), 'INVALID_REQUEST'),
                (lambda item: item.update(basePoint=[math.nan, 0, 0]), 'INVALID_REQUEST'),
                (lambda item: item.update(basePoint=[math.inf, 0, 0]), 'INVALID_REQUEST'),
                (lambda item: item.update(basePoint=[10 ** 1000, 0, 0]), 'INVALID_REQUEST')):
            body = self.calibration(source); alteration(body['calibration'])
            self.expect(code, lambda: self.calibrate(source, body))
        self.assertEqual(self.counts(), (1, 1, 1, 1, 1))

    def test_byte_version_and_total_capacity_include_legacy_and_physical_files(self):
        self.expect('MODEL_LIMIT_EXCEEDED', lambda: self.models.upload(io.BytesIO(), MAX_BYTES + 1, self.metadata(), 'fixture-admin', self.guard))
        self.expect('INVALID_MODEL', lambda: self.models.upload(io.BytesIO(b'short'), len(self.data), self.metadata(), 'fixture-admin', self.guard))
        source = self.upload()
        with patch('apps.api.project_model_library.MAX_VERSIONS', 1):
            self.expect('MODEL_LIBRARY_FULL', lambda: self.calibrate(source))
        orphan = self.old.root / 'files' / (str(uuid4()) + '.glb')
        orphan.write_bytes(self.data)
        with patch('apps.api.project_model_library.MAX_TOTAL_BYTES', len(self.data) * 2):
            self.expect('MODEL_LIBRARY_FULL', lambda: self.upload())
        self.assertEqual(self.counts(), (1, 1, 1, 1, 1))

    def test_failed_publish_and_directory_fsync_roll_back_file_and_all_database_rows(self):
        for failure in ('apps.api.project_model_library.os.replace', 'apps.api.project_model_library._sync_directory'):
            with patch(failure, side_effect=OSError('synthetic storage failure')):
                self.expect('MODEL_STORAGE_UNAVAILABLE', lambda: self.upload())
            self.assertEqual(self.counts(), (0, 0, 0, 0, 0))
            self.assertEqual(list((self.old.root / 'files').iterdir()), [])
            self.assertEqual(list((self.old.root / 'temporary').iterdir()), [])

    def test_failed_upload_cleanup_releases_slot_without_registering_staged_bytes(self):
        original_unlink = Path.unlink
        def denied_cleanup(path, *args, **kwargs):
            if path.parent == self.old.root / 'temporary' and path.name.startswith('project-upload-'):
                raise PermissionError('synthetic staging cleanup denied')
            return original_unlink(path, *args, **kwargs)
        with patch.object(self.old, 'process', side_effect=PreviewError(422, 'INVALID_MODEL')), \
                patch.object(Path, 'unlink', new=denied_cleanup):
            with self.assertRaises(PreviewError) as caught:
                self.upload()
        self.assertEqual((caught.exception.status, caught.exception.code), (503, 'MODEL_STORAGE_UNAVAILABLE'))
        self.assertEqual(self.counts(), (0, 0, 0, 0, 0))
        self.assertEqual(list((self.old.root / 'files').iterdir()), [])
        retained = list((self.old.root / 'temporary').iterdir())
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0].read_bytes(), self.data)
        self.assertTrue(self.old.slots.acquire(blocking=False))
        self.old.slots.release()
        recovered = self.upload()
        self.assertEqual(self.models.content(recovered['modelVersionId'], recovered['contentRevision'],
                                            recovered['sha256'], self.guard), self.data)
        self.assertEqual(self.counts(), (1, 1, 1, 1, 1))
        self.assertEqual(list((self.old.root / 'temporary').iterdir()), retained)

    def test_committed_calibration_cleanup_releases_slot_and_replays_same_fixed_version(self):
        source = self.upload()
        body = self.calibration(source)
        original_unlink = Path.unlink
        def denied_cleanup(path, *args, **kwargs):
            if path.parent == self.old.root / 'temporary' and path.name.startswith('project-calibration-'):
                raise PermissionError('synthetic staging cleanup denied')
            return original_unlink(path, *args, **kwargs)
        with patch.object(Path, 'unlink', new=denied_cleanup):
            with self.assertRaises(PreviewError) as caught:
                self.calibrate(source, body)
        self.assertEqual((caught.exception.status, caught.exception.code), (503, 'MODEL_STORAGE_UNAVAILABLE'))
        self.assertEqual(self.counts(), (2, 1, 2, 2, 2))
        self.assertEqual(len(list((self.old.root / 'files').iterdir())), 2)
        self.assertEqual(list((self.old.root / 'temporary').iterdir()), [])
        self.assertTrue(self.old.slots.acquire(blocking=False))
        self.old.slots.release()
        fixed = [item for item in self.listing()['items'][0]['versions'] if item['canPlace']]
        self.assertEqual(len(fixed), 1)
        with patch.object(self.models, '_commit') as commit:
            recovered = self.calibrate(source, body)
        commit.assert_not_called()
        self.assertEqual(recovered['modelVersionId'], fixed[0]['modelVersionId'])
        self.assertEqual(self.models.content(recovered['modelVersionId'], recovered['contentRevision'],
                                            recovered['sha256'], self.guard), self.data)
        self.assertEqual(self.counts(), (2, 1, 2, 2, 2))
        next_version = self.calibrate(recovered)
        self.assertNotEqual(next_version['modelVersionId'], recovered['modelVersionId'])
        self.assertEqual(self.counts(), (3, 1, 3, 3, 3))

    def test_fifty_retained_versions_allow_paging_and_full_library_replay(self):
        self.assertEqual(self.models.capabilities()['maxVersions'], 50)
        source = self.upload()
        self.retain_synthetic_versions(source, 48, legacy_versions=1)
        metadata = self.metadata()
        uploaded = self.upload(metadata)
        body = self.calibration(uploaded)
        calibrated = self.calibrate(uploaded, body)
        before = self.counts()
        self.assertEqual(before[:3], (50, 48, 49))

        items, cursor = [], None
        while True:
            page = self.listing(limit=7, **({'cursor': cursor} if cursor else {}))
            items.extend(page['items'])
            cursor = page['nextCursor']
            if cursor is None: break
        self.assertEqual(len(items), 48)
        self.assertEqual(len({item['modelAssetId'] for item in items}), 48)
        self.assertEqual(sum(len(item['versions']) for item in items), 49)

        self.expect('MODEL_LIBRARY_FULL', lambda: self.upload())
        self.expect('MODEL_LIBRARY_FULL', lambda: self.calibrate(uploaded))
        self.assertEqual(self.upload(metadata), uploaded)
        self.assertEqual(self.calibrate(uploaded, body), calibrated)
        self.assertEqual(self.counts(), before)
        self.assertEqual(len(list((self.old.root / 'files').glob('*.glb'))), 50)
        self.assertEqual(list((self.old.root / 'temporary').iterdir()), [])

    def test_byte_budget_still_blocks_upload_and_calibration_above_twenty_versions(self):
        source = self.upload()
        self.retain_synthetic_versions(source, 21)
        before = self.counts()
        with patch('apps.api.project_model_library.MAX_TOTAL_BYTES', len(self.data) * 22 - 1):
            self.expect('MODEL_LIBRARY_FULL', lambda: self.upload())
            self.expect('MODEL_LIBRARY_FULL', lambda: self.calibrate(source))
        self.assertEqual(self.counts(), before)
        self.assertEqual(len(list((self.old.root / 'files').glob('*.glb'))), 21)
        self.assertEqual(list((self.old.root / 'temporary').iterdir()), [])

    def test_changed_output_after_publication_is_not_registered_as_ready(self):
        def mutate_published_artifact():
            for path in (self.old.root / 'files').glob('*.glb'):
                path.write_bytes(b'x' * len(self.data))
        self.expect('RESOURCE_CHANGED', lambda: self.upload(guard=mutate_published_artifact))
        self.assertEqual(self.counts(), (0, 0, 0, 0, 0))
        self.assertEqual(list((self.old.root / 'files').iterdir()), [])

    def test_publication_collision_never_removes_a_preexisting_fixed_file(self):
        source = self.upload()
        with patch('apps.api.project_model_library.uuid4', return_value=UUID(source['modelVersionId'])):
            self.expect('RESOURCE_CHANGED', lambda: self.upload(self.metadata(modelAssetId=source['modelAssetId'])))
        self.assertEqual(self.models.content(source['modelVersionId'], source['contentRevision'], source['sha256'], self.guard), self.data)
        self.assertEqual(self.counts(), (1, 1, 1, 1, 1))

    def test_restricted_static_validator_rejects_embedded_external_urls_without_registration(self):
        path = glb(self.root / 'external.glb', lambda document: document['buffers'][0].update(uri='https://untrusted.invalid/resource.bin'))
        self.expect('UNSUPPORTED_MODEL', lambda: self.upload(data=path.read_bytes()))
        self.assertEqual(self.counts(), (0, 0, 0, 0, 0))
        self.assertEqual(list((self.old.root / 'temporary').iterdir()), [])

    def test_listing_filter_pagination_cursors_bind_actor_permission_filter_and_snapshot(self):
        for name, purpose in (('设备甲', 'equipment'), ('环境甲', 'environment'), ('设备乙', 'equipment')):
            self.upload(self.metadata(displayName=name, purpose=purpose))
        first = self.listing(limit=1)
        second = self.listing(limit=1, cursor=first['nextCursor'])
        self.assertNotEqual(first['items'][0]['modelAssetId'], second['items'][0]['modelAssetId'])
        self.assertEqual(len(self.listing(q='设备', purpose='equipment')['items']), 2)
        for options in ({'q': '设备'}, {'purpose': 'equipment'}, {'access_revision': 'grant:changed'}, {'actor': 'another-admin'}):
            arguments = {'actor': 'fixture-admin', 'access_revision': 'grant:1', 'limit': 1, 'cursor': first['nextCursor'], **options}
            actor = arguments.pop('actor')
            self.expect('INVALID_REQUEST', lambda: self.models.listing(actor, self.guard, **arguments))
        self.expect('INVALID_REQUEST', lambda: self.listing(cursor='forged'))
        self.upload(self.metadata(displayName='新增'))
        self.expect('SNAPSHOT_EXPIRED', lambda: self.listing(limit=1, cursor=first['nextCursor']))
        self.expect('SNAPSHOT_EXPIRED', lambda: self.listing(expected_library_revision=first['libraryRevision']))

    def test_legacy_candidates_do_not_adopt_or_copy_engineering_bindings(self):
        candidate = self.root / 'legacy.glb'; candidate.write_bytes(self.data)
        metadata = {key: value for key, value in self.metadata().items() if key != 'purpose'}
        metadata['expectedSessionRevision'] = 'legacy-transport'
        legacy = self.old.save_upload(candidate, metadata, 'fixture-admin', validate(candidate), self.guard)
        self.old.bind({'modelVersionId': legacy['versionId'], 'entityUid': 'fixture-cabinet', 'componentKey': 'component:0',
            'expectedEntityRevision': 'engineering:1', 'expectedHierarchyRevision': 'hierarchy:1',
            'expectedModelRevision': legacy['modelRevision'], 'clientRequestId': str(uuid4())}, 'fixture-admin', self.guard)
        report = self.models.legacy_candidates(self.guard)
        self.assertFalse(report['adoptionPerformed'])
        self.assertEqual(report['items'][0]['legacyBindingCount'], 1)
        self.assertEqual(self.listing()['items'], [])
        identity = self.models.content_identity(legacy['versionId'])
        self.assertEqual(identity['contentRevision'], 'sha256:' + legacy['sha256'])
        self.assertEqual(identity['calibrationState'], 'legacy_unverified')
        self.assertFalse(identity['isProjectResource'])
        self.assertIsNone(identity['modelAssetId'])
        self.expect('NOT_FOUND_OR_FORBIDDEN', lambda: self.models.model(str(uuid4()), legacy['versionId'], self.guard))
        source = self.upload()
        self.assertEqual(self.old.version(source['modelVersionId'])['bindings'], [])
        self.assertEqual(len(self.old.version(legacy['versionId'])['bindings']), 1)

    def test_content_identity_inside_transaction_tracks_calibration_but_not_legacy_binding_revision(self):
        source = self.upload(); calibrated = self.calibrate(source)
        with self.old.connect() as db:
            db.execute('begin immediate')
            identity = self.models.content_identity(calibrated['modelVersionId'], db)
            self.assertEqual(identity['contentRevision'], calibrated['contentRevision'])
            self.assertEqual(identity['modelAssetId'], calibrated['modelAssetId'])
            self.assertTrue(identity['canPlace'])
            self.assertTrue(db.in_transaction)
        self.expect('MODEL_NOT_FOUND', lambda: self.old.bind({'modelVersionId': calibrated['modelVersionId'], 'entityUid': 'fixture-cabinet', 'componentKey': 'component:0',
            'expectedEntityRevision': 'engineering:1', 'expectedHierarchyRevision': 'hierarchy:1',
            'expectedModelRevision': 1, 'clientRequestId': str(uuid4())}, 'fixture-admin', self.guard))
        self.assertEqual(self.models.content_identity(calibrated['modelVersionId']), identity)
        self.assertNotIn('bindings', self.model(calibrated))
        self.assertEqual(self.model(calibrated)['components'], calibrated['components'])

    def test_fixed_content_and_calibration_cannot_be_updated_or_removed_in_sqlite(self):
        source = self.upload(); calibrated = self.calibrate(source)
        for sql, args in (
                ('update project_model_versions set calibration=? where version_id=?', ('{}', calibrated['modelVersionId'])),
                ('delete from project_model_versions where version_id=?', (calibrated['modelVersionId'],)),
                ('update versions set components=? where id=?', ('[]', calibrated['modelVersionId'])),
                ('delete from versions where id=?', (calibrated['modelVersionId'],))):
            with self.assertRaises(sqlite3.IntegrityError):
                with self.old.connect() as db: db.execute(sql, args)
        self.assertTrue(self.model(calibrated)['canPlace'])

    def test_scene_fk_uses_new_versions_and_old_snapshot_stays_fixed_after_recalibration(self):
        source = self.upload(); calibrated = self.calibrate(source)
        scenes = SceneLibrary(self.old)
        def resources(snapshot):
            for item in snapshot['instances']:
                if not self.models.content_identity(item['modelVersionId'])['canPlace']:
                    raise PreviewError(422, 'MODEL_CALIBRATION_REQUIRED')
        scene = scenes.create({'displayName': 'Synthetic scene', 'clientRequestId': str(uuid4())},
            'fixture-admin', self.guard, resources, lambda *_: None)
        snapshot = copy.deepcopy(scene['snapshot'])
        snapshot['instances'] = [{'sceneModelInstanceId': str(uuid4()), 'displayName': '设备A',
            'modelVersionId': calibrated['modelVersionId'], 'placement': {'position': {'mode': 'local', 'xM': 0, 'zM': 0},
                'height': {'mode': 'local_relative', 'relativeHeightM': 0}, 'headingDeg': 0},
            'visible': True, 'positionLocked': False, 'rootBinding': None, 'componentBindings': []}]
        body = {'sceneId': scene['sceneId'], 'expectedSceneRevision': scene['sceneRevision'],
            'clientRequestId': str(uuid4()), 'snapshot': snapshot, 'reviewedEngineering': [], 'rootBindingChanges': []}
        saved = scenes.save(body, 'fixture-admin', self.guard, resources, lambda *_: None)
        replacement = self.calibrate(calibrated)
        fixed = scenes.open(scene['sceneId'], 'fixture-admin', self.guard, saved['sceneRevision'])
        self.assertEqual(fixed['snapshot']['instances'][0]['modelVersionId'], calibrated['modelVersionId'])
        self.assertNotEqual(calibrated['modelVersionId'], replacement['modelVersionId'])
        self.expect('RESOURCE_IN_USE', lambda: scenes.assert_model_unused(calibrated['modelVersionId'], self.guard))
        uncalibrated = copy.deepcopy(body['snapshot']['instances'][0])
        uncalibrated.update(sceneModelInstanceId=str(uuid4()), modelVersionId=source['modelVersionId'])
        body['snapshot']['instances'].append(uncalibrated)
        body['clientRequestId'] = str(uuid4()); body['expectedSceneRevision'] = saved['sceneRevision']
        self.expect('MODEL_CALIBRATION_REQUIRED', lambda: scenes.save(body, 'fixture-admin', self.guard, resources, lambda *_: None))


if __name__ == '__main__': unittest.main()
