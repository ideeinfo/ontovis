"""Source metadata uses independent immutable revisions over real model files."""
import copy
import hashlib
import io
import json
import math
import sqlite3
from threading import Barrier, Thread
import unittest
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.model_resource_metadata import FIELD_UNITS, MAX_METADATA_BYTES, ModelResourceMetadata, validate_metadata
from apps.api.project_model_library import ProjectModelLibrary
from apps.api.model_library import ModelLibrary
from apps.api.scene_library import SceneLibrary
from apps.api.legacy_scene_registry import LegacySceneRegistry
from tests import test_project_model_library as project
from tests import test_model_store_backup as paired
import tools.model_store_backup as backup


def record():
    source = {'url': 'https://example.test/turbine.html', 'locator': 'static specification table',
        'lineStart': 10, 'lineEnd': 12, 'pageSha256': 'a' * 64,
        'fetchedAt': '2026-10-23T12:00:00Z', 'localSnapshot': 'fixtures/turbine.html'}
    def evidence(value, kind='page_declared'):
        return {'value': value, 'rawValue': str(value), 'unit': 'm', 'source': copy.deepcopy(source),
            'kind': kind, 'confidence': 'source_asserted_unverified', 'scope': 'type',
            'note': 'Synthetic conflicting source evidence; no engineering assertion.'}
    fields = dict.fromkeys(FIELD_UNITS)
    fields['hubHeightM'] = [evidence(80), evidence(82, 'program_geometry_parameter')]
    return {'schemaVersion': 1, 'resourceKey': 'synthetic-turbine', 'displayName': '合成来源机型',
        'resourceClass': 'public_source_model', 'verificationStatus': 'source_only_not_oem_verified',
        'sourcePage': {'url': source['url'], 'sha256': source['pageSha256'], 'fetchedAt': source['fetchedAt'],
                       'localSnapshot': source['localSnapshot']},
        'fields': fields, 'teachingVariants': [], 'cautions': ['测试数据，不是安装属性。'],
        'excludedRuntimeValues': [{'name': 'currentPowerOutput', 'reason': '运行模拟，非静态规格',
                                  'rawValue': '0', 'source': copy.deepcopy(source)}],
        'modelBasis': {'summary': 'Synthetic source basis.', 'source': copy.deepcopy(source), 'note': 'No HTML imported.'}}


class ModelResourceMetadataTests(unittest.TestCase):
    def setUp(self):
        self.fixture = project.ProjectModelLibraryTests()
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.models, self.library = self.fixture.models, self.fixture.old
        self.metadata = ModelResourceMetadata(self.models)
        self.version = self.fixture.upload()
        self.guard = self.fixture.guard

    def body(self, **changes):
        return {'modelAssetId': self.version['modelAssetId'], 'modelVersionId': self.version['modelVersionId'],
            'expectedMetadataRevision': None, 'clientRequestId': str(uuid4()), 'metadata': record(), **changes}

    def save(self, body=None, guard=None):
        return self.metadata.save(body or self.body(), 'fixture-admin', guard or self.guard)['item']

    def read(self, **changes):
        return self.metadata.read({'modelAssetId': self.version['modelAssetId'],
            'modelVersionId': self.version['modelVersionId'], **changes}, self.guard)['item']

    def expect(self, code, action):
        with self.assertRaises(PreviewError) as caught:
            action()
        self.assertEqual(caught.exception.code, code)

    def counts(self):
        with self.library.connect() as db:
            return [db.execute('select count(*) from ' + table).fetchone()[0] for table in
                    ('model_resource_metadata_revisions', 'model_resource_metadata_requests', 'model_resource_metadata_audit')]

    def test_empty_then_append_retains_conflicting_evidence_and_original_fixed_model(self):
        self.assertIsNone(self.read())
        before = self.fixture.counts(), self.fixture.listing(), self.fixture.model(self.version)
        original_file = self.models._content(self.version)
        first = self.save()
        self.assertEqual(first['metadata'], record())
        self.assertEqual(first['modelSha256'], hashlib.sha256(original_file).hexdigest())
        self.assertEqual(first, self.read())
        changed = record(); changed['cautions'].append('Later source annotation.')
        second = self.save(self.body(expectedMetadataRevision=first['metadataRevision'], metadata=changed))
        self.assertNotEqual(first['metadataRevision'], second['metadataRevision'])
        self.assertEqual(self.read(), second)
        self.assertEqual(self.read(metadataRevision=first['metadataRevision']), first)
        self.assertEqual(self.fixture.counts(), before[0])
        self.assertEqual(self.fixture.listing(), before[1])
        self.assertEqual(self.fixture.model(self.version), before[2])
        self.assertEqual(self.models._content(self.version), original_file)
        self.assertEqual(self.counts(), [2, 2, 2])

    def test_idempotence_returns_original_after_new_revision_and_rejects_changed_request(self):
        body = self.body(); first = self.save(body)
        self.save(self.body(expectedMetadataRevision=first['metadataRevision']))
        self.assertEqual(self.save(body), first)
        self.assertEqual(self.counts(), [2, 2, 2])
        conflict = copy.deepcopy(body); conflict['metadata']['displayName'] = 'changed'
        self.expect('REQUEST_CONFLICT', lambda: self.save(conflict))
        self.expect('METADATA_CHANGED', lambda: self.save())
        self.expect('METADATA_CHANGED', lambda: self.save(self.body(expectedMetadataRevision=first['metadataRevision'])))

    def test_simultaneous_first_writes_have_one_winner(self):
        barrier, results = Barrier(2), []
        def write():
            barrier.wait()
            try: results.append(self.save()['metadataRevision'])
            except PreviewError as error: results.append(error.code)
        threads = [Thread(target=write) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(6); self.assertFalse(thread.is_alive())
        self.assertEqual(results.count('METADATA_CHANGED'), 1)
        self.assertEqual(self.counts(), [1, 1, 1])

    def test_fixed_versions_and_assets_have_independent_metadata_scopes(self):
        first = self.save()
        calibrated = self.fixture.calibrate(self.version)
        self.assertIsNone(self.metadata.read({'modelAssetId': calibrated['modelAssetId'],
            'modelVersionId': calibrated['modelVersionId']}, self.guard)['item'])
        second = self.save(self.body(modelVersionId=calibrated['modelVersionId']))
        self.assertEqual(second['modelVersionId'], calibrated['modelVersionId'])
        self.assertEqual(self.read(), first)
        other = self.fixture.upload()
        self.expect('NOT_FOUND_OR_FORBIDDEN', lambda: self.save(self.body(modelAssetId=other['modelAssetId'])))
        self.expect('NOT_FOUND_OR_FORBIDDEN', lambda: self.read(metadataRevision=second['metadataRevision']))
        self.expect('NOT_FOUND_OR_FORBIDDEN', lambda: self.save(self.body(modelAssetId=str(uuid4()))))

    def test_other_project_assets_cannot_be_read_or_written(self):
        with self.library.connect() as db:
            db.execute('update project_model_assets set project_code=? where id=?', ('another-project', self.version['modelAssetId']))
        self.expect('NOT_FOUND_OR_FORBIDDEN', self.read)
        self.expect('NOT_FOUND_OR_FORBIDDEN', self.save)
        self.assertEqual(self.counts(), [0, 0, 0])

    def test_authorization_loss_before_commit_rolls_back_every_metadata_row(self):
        calls = 0
        def revoke():
            nonlocal calls
            calls += 1
            if calls == 3: raise PreviewError(403, 'MODEL_WRITE_FORBIDDEN')
        self.expect('MODEL_WRITE_FORBIDDEN', lambda: self.save(guard=revoke))
        self.assertEqual(self.counts(), [0, 0, 0])
        saved = self.save(); self.guard.allowed = False
        self.expect('MODEL_WRITE_FORBIDDEN', self.read)
        self.expect('MODEL_WRITE_FORBIDDEN', lambda: self.save(self.body(expectedMetadataRevision=saved['metadataRevision'])))

    def test_revisions_requests_and_audit_cannot_be_updated_or_deleted(self):
        self.save()
        tables = ('model_resource_metadata_revisions', 'model_resource_metadata_requests', 'model_resource_metadata_audit')
        for table in tables:
            for statement in ('delete from ' + table, 'update ' + table + ' set project_code=project_code'):
                with self.subTest(statement=statement), self.assertRaises(sqlite3.IntegrityError):
                    with self.library.connect() as db: db.execute(statement)
        self.assertEqual(self.counts(), [1, 1, 1])

    def test_metadata_retains_legacy_write_freeze_and_every_scene_snapshot(self):
        scenes = SceneLibrary(self.library, model_identity=self.models.content_identity)
        LegacySceneRegistry(self.library)
        scene = scenes.create({'displayName': 'Synthetic existing scene', 'clientRequestId': str(uuid4())},
            'fixture-admin', self.guard, lambda snapshot: None, lambda *args: None)
        with self.library.connect() as db:
            db.execute("update legacy_scene_registry_state set state='active' where id=1")
            before = {table: [tuple(row) for row in db.execute('select * from ' + table)] for table in
                      ('scene_revisions', 'scenes', 'scene_audit', 'legacy_scene_registry_state')}
        self.assertFalse(self.library.legacy_writable())
        self.save()
        self.assertFalse(self.library.legacy_writable())
        with self.library.connect() as db:
            after = {table: [tuple(row) for row in db.execute('select * from ' + table)] for table in before}
        self.assertEqual(after, before)
        self.assertEqual(scene['snapshot']['instances'], [])

    def test_invalid_bounded_schema_never_stores_partial_metadata(self):
        modifications = [
            lambda r: r.update(schemaVersion=True), lambda r: r.update(schemaVersion=2),
            lambda r: r.update(equipmentUid='must-not-be-accepted'), lambda r: r['fields'].update(windSpeed=[]),
            lambda r: r['fields'].pop('manufacturer'), lambda r: r['fields'].update(hubHeightM=[]),
            lambda r: r['fields']['hubHeightM'][0].update(value=math.nan),
            lambda r: r['fields']['hubHeightM'][0].update(value=math.inf),
            lambda r: r['fields']['hubHeightM'][0].update(value=10 ** 1000),
            lambda r: r['fields']['hubHeightM'][0].update(unit='kW'),
            lambda r: r['fields']['hubHeightM'][0].update(kind=['page_declared']),
            lambda r: r['fields']['hubHeightM'][0]['source'].update(url='javascript:alert(1)'),
            lambda r: r['fields']['hubHeightM'][0]['source'].update(url='https://secret@example.test/'),
            lambda r: r['fields']['hubHeightM'][0]['source'].update(pageSha256='invalid'),
            lambda r: r['fields']['hubHeightM'][0]['source'].update(lineEnd=1),
            lambda r: r['sourcePage'].update(fetchedAt='2026-10-23'),
            lambda r: r['sourcePage'].update(url='https://example.test/\nheader'),
            lambda r: r.update(displayName='bad\x00text'),
            lambda r: r.update(cautions=['x' * 2001]),
            lambda r: r['modelBasis'].update(rawText='x' * 16001),
            lambda r: r['modelBasis'].update(sourceQuality={'status': 'source_only_not_oem_verified',
                'engineeringIdentityVerified': True, 'liveTelemetryIncluded': False}),
            lambda r: r.update(teachingVariants=['geared', 'geared']),
        ]
        for modify in modifications:
            value = record(); modify(value)
            with self.subTest(modify=modifications.index(modify)):
                self.expect('INVALID_REQUEST', lambda: self.save(self.body(metadata=value)))
        self.assertEqual(self.counts(), [0, 0, 0])

    def test_raw_multiline_and_summary_forms_validate_without_execution(self):
        value = record(); value['modelBasis'].pop('summary')
        value['modelBasis']['rawText'] = '<p>Source text\n${neverExecuted()}</p>'
        self.assertEqual(validate_metadata(value), value)
        self.assertEqual(self.save(self.body(metadata=value))['metadata'], value)

    def test_source_quality_is_retained_and_never_promoted_to_engineering_verification(self):
        value = record(); value['modelBasis']['sourceQuality'] = {'status': 'source_only_not_oem_verified',
            'engineeringIdentityVerified': False, 'liveTelemetryIncluded': False}
        self.assertEqual(self.save(self.body(metadata=value))['metadata'], value)

    def test_total_limit_is_checked_before_storage(self):
        value = record(); value['cautions'] = ['x' * 2000] * 32
        value['modelBasis']['summary'] = 'y' * 4000
        self.assertGreater(len(json.dumps(value).encode()), MAX_METADATA_BYTES)
        self.expect('METADATA_LIMIT_EXCEEDED', lambda: self.save(self.body(metadata=value)))


class ModelResourceMetadataBackupTests(unittest.TestCase):
    def test_paired_backup_restores_metadata_history_audit_and_immutable_triggers(self):
        fixture = paired.ModelStoreBackupTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        library = fixture.fixture.fixture.library
        models = ProjectModelLibrary(library); metadata = ModelResourceMetadata(models)
        data = fixture.model.joinpath('model.glb').read_bytes()
        version = models.upload(io.BytesIO(data), len(data), {'expectedLibraryRevision': library.listing()['libraryRevision'],
            'clientRequestId': str(uuid4()), 'displayName': 'Synthetic resource', 'purpose': 'equipment',
            'sourceNote': 'Synthetic backup metadata fixture', 'rightsDeclared': True}, 'fixture-admin', lambda: None)
        body = {'modelAssetId': version['modelAssetId'], 'modelVersionId': version['modelVersionId'],
                'expectedMetadataRevision': None, 'clientRequestId': str(uuid4()), 'metadata': record()}
        first = metadata.save(body, 'fixture-admin', lambda: None)['item']
        body.update(expectedMetadataRevision=first['metadataRevision'], clientRequestId=str(uuid4()))
        second = metadata.save(body, 'fixture-admin', lambda: None)['item']
        before = fixture.source_state(); receipt = fixture.snapshot()
        target = fixture.root / 'restored-metadata'
        backup.restore_new(fixture.destination, target, receipt['manifestSha256'], service_stopped=True)
        self.assertEqual(fixture.tree(target / 'workbench-library'), before[0])
        self.assertEqual(fixture.source_state(), before)
        restored = ModelLibrary(target / 'workbench-library', models.project_code, fixture.fixture.fixture.context)
        reader = ModelResourceMetadata(ProjectModelLibrary(restored))
        ids = {key: version[key] for key in ('modelAssetId', 'modelVersionId')}
        self.assertEqual(reader.read(ids, lambda: None)['item'], second)
        self.assertEqual(reader.read({**ids, 'metadataRevision': first['metadataRevision']}, lambda: None)['item'], first)
        self.assertEqual(reader.save(body, 'fixture-admin', lambda: None)['item'], second)
        with restored.connect() as db:
            self.assertEqual(db.execute('select count(*) from model_resource_metadata_audit').fetchone()[0], 2)
            with self.assertRaises(sqlite3.IntegrityError): db.execute('delete from model_resource_metadata_revisions')


if __name__ == '__main__':
    unittest.main()
