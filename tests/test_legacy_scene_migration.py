"""Read-only migration preparation on synthetic private SQLite and real GLB.

Identity/revision/calibration inputs here are explicitly synthetic. No current
OntoBase account, engineering proof, network or migration apply is exercised.
"""
import copy
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.api.model_library import ModelLibrary
from apps.api.model_validation import validate
from tests.test_model_upload import glb
from tools.migrate_legacy_scene import MigrationError, main, plan, read_json, verify, write_report
import tools.migrate_legacy_scene as migration


class LegacySceneMigrationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.store = self.root/'private'
        self.context = str(uuid4())
        self.library = ModelLibrary(self.store, 'synthetic-old7-project', self.context)
        def graph(doc):
            doc['scenes'][0]['nodes'] = list(range(24))
            doc['nodes'] = [{'name': 'controller' if index == 11 else 'synthetic-part-'+str(index),
                'mesh': 0, 'translation': [index*2, 0, 0],
                'extras': {'component': 'controller' if index == 11 else 'synthetic-part-'+str(index)}} for index in range(24)]
        self.source = glb(self.root/'synthetic.glb', graph)
        self.result = validate(self.source)
        self.result['components'] += [{'componentKey': 'proxy:'+role, 'displayName': role,
            'nodeIndices': [], 'keyStability': 'version_local', 'geometryQuality': 'proxy_schematic',
            'bounds': [[-2, 0, -1], [-1, 2, 1]]} for role in ('CT', 'CN1')]
        self.version = self.library.save_upload(self.source, {'expectedSessionRevision': 'synthetic-session:1',
            'expectedLibraryRevision': self.library.listing()['libraryRevision'], 'clientRequestId': str(uuid4()),
            'displayName': 'Synthetic old7', 'sourceNote': 'Synthetic geometry only', 'rightsDeclared': True},
            'synthetic-user', self.result, lambda: None)
        self.inputs = {'schemaVersion': 1, 'projectCode': 'synthetic-old7-project',
            'installationContextId': self.context, 'rootEntityUid': 'synthetic-root',
            'childEntityUid': 'synthetic-child', 'cabinetRefs': {role: 'synthetic-'+role for role in migration.ROLES},
            'defaultSource': {'kind': 'uploaded_version', 'legacyModelVersionId': self.version['versionId']},
            'calibration': None, 'calibrationSourceNote': None}
        self.keys = {'CT': 'proxy:CT', 'CN1': 'proxy:CN1', 'CN': 'component:11'}
        for role in migration.ROLES:
            current = self.library.version(self.version['versionId'])
            self.library.bind({'modelVersionId': self.version['versionId'], 'entityUid': self.inputs['cabinetRefs'][role],
                'componentKey': self.keys[role], 'expectedEntityRevision': 'synthetic-'+role+':1',
                'expectedHierarchyRevision': self.context+':7', 'expectedModelRevision': current['modelRevision'],
                'clientRequestId': str(uuid4())}, 'synthetic-user', lambda: None)
        self.artifact = self.store/'files'/(self.version['versionId']+'.glb')
        self.fixed = self.root/'fixed'; self.fixed.mkdir()
        self.fixed.joinpath('model.glb').write_bytes(self.artifact.read_bytes())
        components = {item['componentKey']: item for item in self.result['components']}
        config = {'schemaVersion': 1, 'projectCode': self.inputs['projectCode'], 'installationContextId': self.context,
            'rootEntityUid': self.inputs['rootEntityUid'], 'sha256': self.version['sha256'],
            'bindings': [{'entityUid': self.inputs['cabinetRefs'][role], 'entityRevision': 'synthetic-'+role+':1',
                'componentKey': role, 'geometryQuality': migration.QUALITY[role],
                'bounds': components[self.keys[role]]['bounds']} for role in migration.ROLES]}
        self.fixed.joinpath('model.json').write_text(json.dumps(config))
        self.manifest = self.root/'manifest.json'
        self.manifest.write_text(json.dumps({'schemaVersion': 1, 'projectCode': self.inputs['projectCode'],
            'installationContextId': self.context, 'rootEntityUid': self.inputs['rootEntityUid'],
            'childEntityUid': self.inputs['childEntityUid'], 'unitLabel': '7', 'sourceModelSha256': 'a'*64,
            'derivedModelSha256': self.version['sha256'], 'bindings': [{key: row[key]
                for key in ('entityUid', 'componentKey', 'geometryQuality')} for row in config['bindings']]}))

    def expect(self, code, action):
        with self.assertRaises(MigrationError) as caught: action()
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn(self.inputs['rootEntityUid'], str(caught.exception))

    def prepare(self, inputs=None, **options):
        return plan(self.store, self.version['versionId'], inputs or self.inputs, **options)

    def valid_calibration(self):
        inputs = copy.deepcopy(self.inputs)
        inputs.update(calibration={'unit': 'm', 'axes': 'Y_UP_RIGHT_HANDED', 'basePoint': [0, 0, 0], 'forward': [0, 0, -1]},
                      calibrationSourceNote='Synthetic test calibration; not a measured location')
        return inputs

    def state(self):
        paths = [self.store/'library.sqlite3', self.artifact, self.fixed/'model.json', self.fixed/'model.glb', self.manifest]
        return {str(path.relative_to(self.root)): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
                for path in paths}

    def update_version(self, field, value):
        self.assertIn(field, ('components', 'report', 'revision'))
        with closing(sqlite3.connect(self.store/'library.sqlite3')) as db, db:
            db.execute('update versions set '+field+'=? where id=?', (json.dumps(value) if field != 'revision' else value, self.version['versionId']))

    def test_plan_verify_are_deterministic_readonly_and_never_obtain_current_engineering_proof(self):
        before = self.state()
        temporary = self.store/'temporary'/'upload-must-remain.glb'; temporary.write_bytes(b'not part of the plan')
        with patch.object(ModelLibrary, '__init__', side_effect=AssertionError('must not initialize')):
            first = self.prepare(session_manifest=self.manifest, fixed_model_root=self.fixed)
            self.assertEqual(first, self.prepare(session_manifest=self.manifest, fixed_model_root=self.fixed))
            checked = verify(self.store, self.version['versionId'], self.inputs, first,
                session_manifest=self.manifest, fixed_model_root=self.fixed)
        self.assertEqual(first['componentCount'], 26); self.assertEqual(first['bindingCount'], 3); self.assertEqual(first['auditCount'], 4)
        self.assertEqual({row['role']: row['componentKey'] for row in first['roleBindings']}, self.keys)
        self.assertEqual(first['versionRevision'], 4)
        self.assertEqual(first['currentEngineeringProof'], {'state': 'not_obtained', 'blocking': True})
        self.assertEqual(first['calibrationState'], 'missing'); self.assertIn('CALIBRATION_REQUIRED', first['blockers'])
        self.assertTrue(checked['inputsUnchanged']); self.assertFalse(checked['ready']); self.assertFalse(checked['applySupported'])
        self.assertEqual(self.state(), before); self.assertTrue(temporary.exists())
        self.assertNotIn('synthetic-user', json.dumps(first)); self.assertNotIn(str(self.store), json.dumps(first))

    def test_database_connections_use_ro_query_only_and_no_library_constructor(self):
        original = sqlite3.connect
        connections = []
        class Observed(sqlite3.Connection):
            def execute(self, sql, *args):
                if sql == 'pragma query_only=on': connections.append(sql)
                self.assert_read(sql)
                return super().execute(sql, *args)
            @staticmethod
            def assert_read(sql):
                assert sql.split()[0].lower() in ('pragma', 'begin', 'select')
        def connect(*args, **kwargs):
            self.assertIn('?mode=ro', args[0]); self.assertTrue(kwargs['uri'])
            return original(*args, factory=Observed, **kwargs)
        with patch.object(migration.sqlite3, 'connect', side_effect=connect): self.prepare()
        self.assertEqual(len(connections), 2)

    def test_valid_calibration_is_input_only_and_preserve_legacy_display_stays_unverified(self):
        values = self.valid_calibration(); result = self.prepare(values)
        self.assertEqual(result['calibrationState'], 'input_provided')
        self.assertNotIn('CALIBRATION_REQUIRED', result['blockers'])
        self.assertEqual(result['blockers'], ['CURRENT_ENGINEERING_PROOF_REQUIRED'])
        self.assertFalse(result['ready']); self.assertFalse(result['canPlace'])
        self.assertNotIn('verifiedBy', json.dumps(result)); self.assertNotIn('modelToCalibrated', json.dumps(result))
        values['calibration'] = {'mode': 'preserve_legacy_display'}
        result = self.prepare(values)
        self.assertEqual(result['calibrationState'], 'legacy_display_only')
        self.assertFalse(result['geographicPlacementAllowed']); self.assertIn('CALIBRATION_REQUIRED', result['blockers'])

    def test_invalid_or_fake_verified_calibration_cannot_be_certified(self):
        for calibration in ({'state': 'verified'}, {**self.valid_calibration()['calibration'], 'active': False},
            {**self.valid_calibration()['calibration'], 'unit': 'mm'},
            {**self.valid_calibration()['calibration'], 'forward': [0, 0, 0]},
            {**self.valid_calibration()['calibration'], 'forward': [0, 1, -1]},
            {**self.valid_calibration()['calibration'], 'basePoint': [float('nan'), 0, 0]}):
            with self.subTest(calibration=repr(calibration)):
                values = self.valid_calibration(); values['calibration'] = calibration
                with self.assertRaises(MigrationError): self.prepare(values)
        values = self.valid_calibration(); values['calibrationSourceNote'] = ''
        self.expect('INVALID_INPUT', lambda: self.prepare(values))

    def test_version_and_default_source_must_be_explicit_and_not_latest(self):
        for version in (None, '', 'latest', str(uuid4()).upper()):
            with self.subTest(version=version):
                with self.assertRaises(MigrationError): plan(self.store, version, self.inputs)
        values = copy.deepcopy(self.inputs); values['defaultSource']['legacyModelVersionId'] = str(uuid4())
        self.expect('SOURCE_MISMATCH', lambda: self.prepare(values))
        self.expect('VERSION_NOT_FOUND', lambda: plan(self.store, str(uuid4()), {**self.inputs,
            'defaultSource': {'kind': 'fixed_model', 'sha256': self.version['sha256']}}))
        self.assertEqual(self.prepare()['legacyModelVersionId'], self.version['versionId'])

    def test_scope_and_five_distinct_role_identities_are_required(self):
        for field, value in [('projectCode', 'other-project'), ('installationContextId', str(uuid4()))]:
            values = copy.deepcopy(self.inputs); values[field] = value
            self.expect('SOURCE_MISMATCH', lambda: self.prepare(values))
        values = copy.deepcopy(self.inputs); values['cabinetRefs']['CT'] = values['rootEntityUid']
        self.expect('AMBIGUOUS_IDENTITY', lambda: self.prepare(values))
        values = copy.deepcopy(self.inputs); values['cabinetRefs']['CT'] = 'unknown-cabinet'
        self.expect('AMBIGUOUS_BINDING', lambda: self.prepare(values))

    def test_bad_registered_bytes_or_reported_length_stop_before_any_plan(self):
        original = self.artifact.read_bytes(); changed = bytearray(original); changed[-1] ^= 1
        self.artifact.write_bytes(changed)
        self.expect('MODEL_CHANGED', self.prepare)
        self.artifact.write_bytes(original[:-4]); self.expect('MODEL_CHANGED', self.prepare)

    def test_actual_probe_rejects_forged_component_bounds_and_node_indices(self):
        original = copy.deepcopy(self.result['components'])
        for field, value in [('bounds', [[0, 0, 0], [1, 1, 1]]), ('nodeIndices', [1999]), ('nodeIndices', [0, 0])]:
            with self.subTest(field=field, value=value):
                changed = copy.deepcopy(original); changed[11][field] = value
                self.update_version('components', changed)
                self.expect('INVALID_DIRECTORY', self.prepare)
        self.update_version('components', original)
        report = copy.deepcopy(self.result['report']); report['bounds']['max'][0] += 1
        self.update_version('report', report); self.expect('INVALID_DIRECTORY', self.prepare)

    def test_missing_ambiguous_or_reclassified_directory_is_not_inferred(self):
        original = copy.deepcopy(self.result['components'])
        for changed in (original[:-1], original+[original[0]],
                        [{**row, 'geometryQuality': 'source_candidate'} if row['componentKey'] == 'proxy:CT' else row for row in original]):
            with self.subTest(count=len(changed)):
                self.update_version('components', changed)
                self.expect('INVALID_DIRECTORY', self.prepare)

    def test_original_rights_must_match_upload_version_request_actor_and_sha(self):
        with closing(sqlite3.connect(self.store/'library.sqlite3')) as db, db:
            db.execute("update audit set payload=? where action='model_uploaded'", (json.dumps({'rightsDeclared': True, 'sha256': '0'*64}),))
        self.expect('SOURCE_RIGHTS_REQUIRED', self.prepare)
        with closing(sqlite3.connect(self.store/'library.sqlite3')) as db, db:
            db.execute("update audit set payload=?,actor='another-user' where action='model_uploaded'", (json.dumps({'rightsDeclared': True, 'sha256': self.version['sha256']}),))
        self.expect('SOURCE_RIGHTS_REQUIRED', self.prepare)

    def test_current_binding_rows_need_their_original_audit_and_no_dangling_reference(self):
        with closing(sqlite3.connect(self.store/'library.sqlite3')) as db, db:
            db.execute("update bindings set entity_revision='unrecorded:2' where component_key='proxy:CT'")
        self.expect('INVALID_SOURCE_AUDIT', self.prepare)
        with closing(sqlite3.connect(self.store/'library.sqlite3')) as db, db:
            db.execute('update bindings set version_id=? where component_key=?', (str(uuid4()), 'proxy:CT'))
        self.expect('INVALID_STORE', self.prepare)

    def test_optional_fixed_model_and_session_manifest_are_cross_checked_without_setting_default(self):
        selected = self.prepare(fixed_model_root=self.fixed, session_manifest=self.manifest)
        self.assertEqual(selected['inputs']['defaultSource']['kind'], 'uploaded_version')
        values = copy.deepcopy(self.inputs)
        values['defaultSource'] = {'kind': 'fixed_model', 'sha256': self.version['sha256']}
        self.expect('SOURCE_MISMATCH', lambda: self.prepare(values))
        self.assertEqual(self.prepare(values, fixed_model_root=self.fixed)['inputs']['defaultSource']['kind'], 'fixed_model')
        manifest = read_json(self.manifest); manifest['bindings'][0]['entityUid'] = 'different-identity'
        self.manifest.write_text(json.dumps(manifest))
        self.expect('SOURCE_MISMATCH', lambda: self.prepare(session_manifest=self.manifest))

    def test_fixed_proxy_geometry_and_revision_must_match_exact_uploaded_catalog(self):
        fixed = read_json(self.fixed/'model.json')
        fixed['bindings'][0]['bounds'][1][1] += 1
        self.fixed.joinpath('model.json').write_text(json.dumps(fixed))
        self.expect('SOURCE_MISMATCH', lambda: self.prepare(fixed_model_root=self.fixed))

    def test_modelasset_optional_source_fields_preserve_legacy_and_readonly_plan(self):
        original = read_json(self.fixed/'model.json')
        legacy = self.prepare(fixed_model_root=self.fixed, session_manifest=self.manifest)
        self.assertFalse(legacy['ready'])
        for optional in ({'licenceBasis': 'Synthetic authorized test source'},
                         {'sourceModelSha256': 'a'*64},
                         {'licenceBasis': 'Synthetic authorized test source', 'sourceModelSha256': 'a'*64}):
            with self.subTest(fields=tuple(optional)):
                self.fixed.joinpath('model.json').write_text(json.dumps({**original, **optional}))
                before = self.state()
                result = self.prepare(fixed_model_root=self.fixed, session_manifest=self.manifest)
                checked = verify(self.store, self.version['versionId'], self.inputs, result,
                    fixed_model_root=self.fixed, session_manifest=self.manifest)
                self.assertTrue(checked['inputsUnchanged']); self.assertEqual(self.state(), before)
                self.assertFalse(result['ready']); self.assertFalse(result['canPlace'])
                self.assertEqual(result['currentEngineeringProof'], {'state': 'not_obtained', 'blocking': True})
                self.assertNotEqual(result['historicalSources']['fixedModel']['configSha256'],
                                    legacy['historicalSources']['fixedModel']['configSha256'])
                self.assertNotIn('Synthetic authorized test source', json.dumps(result))

    def test_optional_source_metadata_has_strict_text_and_sha_limits(self):
        original = read_json(self.fixed/'model.json')
        for field, values in (
                ('licenceBasis', (None, True, 7, {}, '', ' ', ' padded ', 'line\nbreak', 'x'*2001)),
                ('sourceModelSha256', (None, True, 7, {}, '', 'a'*63, 'a'*65, 'A'*64, 'g'*64))):
            for value in values:
                with self.subTest(field=field, value=repr(value)):
                    self.fixed.joinpath('model.json').write_text(json.dumps({**original, field: value}))
                    self.expect('INVALID_INPUT', lambda: self.prepare(fixed_model_root=self.fixed))
        self.fixed.joinpath('model.json').write_text(json.dumps({**original, 'licenceBasis': 'x'*2000,
                                                              'sourceModelSha256': '0'*64}))
        self.assertFalse(self.prepare(fixed_model_root=self.fixed)['ready'])

    def test_optional_modelasset_fields_do_not_allow_unknown_or_proof_metadata(self):
        original = read_json(self.fixed/'model.json')
        for field in ('licenseBasis', 'sourceModelSHA256', 'verifiedBy', 'currentEngineeringProof'):
            with self.subTest(field=field):
                self.fixed.joinpath('model.json').write_text(json.dumps({**original,
                    'licenceBasis': 'Synthetic source only', 'sourceModelSha256': 'a'*64, field: 'not accepted'}))
                self.expect('INVALID_INPUT', lambda: self.prepare(fixed_model_root=self.fixed))

    def test_source_candidate_history_accepts_only_identical_float32_bounds_and_retains_raw_values(self):
        original = read_json(self.fixed/'model.json')
        before = self.prepare(fixed_model_root=self.fixed)
        config = copy.deepcopy(original)
        row = next(row for row in config['bindings'] if row['componentKey'] == 'CN')
        row['bounds'] = [[math.nextafter(number, math.inf) for number in point] for point in row['bounds']]
        self.assertNotEqual(row['bounds'], next(row for row in original['bindings'] if row['componentKey'] == 'CN')['bounds'])
        self.fixed.joinpath('model.json').write_text(json.dumps(config))
        state = self.state()
        result = self.prepare(fixed_model_root=self.fixed)
        self.assertTrue(verify(self.store, self.version['versionId'], self.inputs, result,
                               fixed_model_root=self.fixed)['inputsUnchanged'])
        self.assertEqual(self.state(), state)
        self.assertEqual(result['roleBindings'], before['roleBindings'])
        self.assertEqual(result['directorySha256'], before['directorySha256'])
        self.assertNotEqual(result['historicalSources']['fixedModel']['configSha256'],
                            before['historicalSources']['fixedModel']['configSha256'])
        self.assertEqual(next(row for row in result['historicalSources']['fixedModel']['bindingBounds']
                              if row['role'] == 'CN')['bounds'], row['bounds'])
        self.assertFalse(result['ready'])

    def test_adjacent_float32_source_candidate_coordinate_is_a_geometry_change(self):
        config = read_json(self.fixed/'model.json')
        row = next(row for row in config['bindings'] if row['componentKey'] == 'CN')
        original = row['bounds'][0][0]
        bits = struct.unpack('<I', struct.pack('<f', original))[0]
        row['bounds'][0][0] = struct.unpack('<f', struct.pack('<I', bits+1))[0]
        self.assertNotEqual(struct.pack('<f', original), struct.pack('<f', row['bounds'][0][0]))
        self.fixed.joinpath('model.json').write_text(json.dumps(config))
        self.expect('SOURCE_MISMATCH', lambda: self.prepare(fixed_model_root=self.fixed))

    def test_proxy_historical_bounds_reject_even_same_float32_micro_difference(self):
        original = read_json(self.fixed/'model.json')
        for role in ('CT', 'CN1'):
            with self.subTest(role=role):
                config = copy.deepcopy(original)
                row = next(row for row in config['bindings'] if row['componentKey'] == role)
                number = row['bounds'][0][0]
                row['bounds'][0][0] = math.nextafter(number, math.inf)
                self.assertEqual(struct.pack('<f', number), struct.pack('<f', row['bounds'][0][0]))
                self.fixed.joinpath('model.json').write_text(json.dumps(config))
                self.expect('SOURCE_MISMATCH', lambda: self.prepare(fixed_model_root=self.fixed))

    def test_historical_source_candidate_rejects_float32_overflow_nonfinite_and_nonnumeric_values(self):
        original = read_json(self.fixed/'model.json')
        for value, code in ((1e300, 'SOURCE_MISMATCH'), (10**1000, 'SOURCE_MISMATCH'),
                (float('inf'), 'INVALID_INPUT'), (float('nan'), 'INVALID_INPUT'),
                (True, 'SOURCE_MISMATCH'), ('22', 'SOURCE_MISMATCH')):
            with self.subTest(value=repr(value)):
                config = copy.deepcopy(original)
                next(row for row in config['bindings'] if row['componentKey'] == 'CN')['bounds'][0][0] = value
                self.fixed.joinpath('model.json').write_text(json.dumps(config))
                self.expect(code, lambda: self.prepare(fixed_model_root=self.fixed))

    def test_source_artifact_changed_during_probe_cannot_finish_plan(self):
        original = self.artifact.read_bytes()
        probe = migration.validate
        def changed(path):
            result = probe(path)
            data = bytearray(path.read_bytes()); data[-1] ^= 1; path.write_bytes(data)
            return result
        with patch.object(migration, 'validate', side_effect=changed):
            self.expect('INPUT_CHANGED', self.prepare)
        self.artifact.write_bytes(original)

    def test_verify_rechecks_all_historical_files_after_history_validation(self):
        expected = self.prepare(fixed_model_root=self.fixed, session_manifest=self.manifest)
        history = migration._history
        for path in (self.fixed/'model.glb', self.fixed/'model.json', self.manifest):
            with self.subTest(path=path.name, fixed=path.parent == self.fixed):
                original = path.read_bytes()
                def changed(*args, **kwargs):
                    result = history(*args, **kwargs)
                    if (path.parent == self.fixed) == kwargs.get('fixed', False):
                        if path.suffix == '.glb':
                            data = bytearray(original); data[-1] ^= 1
                            path.write_bytes(data)
                        else:
                            path.write_bytes(original+b' ')
                    return result
                try:
                    with patch.object(migration, '_history', side_effect=changed):
                        self.expect('INPUT_CHANGED', lambda: verify(self.store, self.version['versionId'],
                            self.inputs, expected, fixed_model_root=self.fixed, session_manifest=self.manifest))
                finally:
                    path.write_bytes(original)

    def test_other_context_hierarchy_and_wal_store_are_explicitly_rejected(self):
        with closing(sqlite3.connect(self.store/'library.sqlite3')) as db, db:
            db.execute('update bindings set hierarchy_revision=?', (str(uuid4())+':7',))
        self.expect('SOURCE_MISMATCH', self.prepare)
        with closing(sqlite3.connect(self.store/'library.sqlite3')) as db, db:
            db.execute('pragma journal_mode=wal')
        before = self.state()
        self.expect('STORE_FORMAT_UNSUPPORTED', self.prepare)
        self.assertEqual(self.state(), before)

    def test_verify_rejects_changed_inputs_library_and_forged_plan(self):
        original = self.prepare()
        changed = copy.deepcopy(original); changed['ready'] = True
        self.expect('PLAN_CHANGED', lambda: verify(self.store, self.version['versionId'], self.inputs, changed))
        changed = copy.deepcopy(original); changed['extra'] = 'not part of the plan'
        changed['planSha256'] = migration._digest({key: value for key,value in changed.items() if key != 'planSha256'})
        self.expect('PLAN_CHANGED', lambda: verify(self.store, self.version['versionId'], self.inputs, changed))
        self.expect('PLAN_CHANGED', lambda: verify(self.store, self.version['versionId'], self.valid_calibration(), original))
        self.update_version('revision', 5)
        self.expect('PLAN_CHANGED', lambda: verify(self.store, self.version['versionId'], self.inputs, original))

    def test_symlink_paths_and_database_sidecars_are_rejected_without_following(self):
        alias = self.root/'alias'; alias.symlink_to(self.store, target_is_directory=True)
        self.expect('UNSAFE_PATH', lambda: plan(alias, self.version['versionId'], self.inputs))
        file = self.artifact; saved = file.read_bytes(); file.unlink(); file.symlink_to(self.fixed/'model.glb')
        self.expect('UNSAFE_PATH', self.prepare)
        file.unlink(); file.write_bytes(saved)
        sidecar = Path(str(self.store/'library.sqlite3')+'-wal'); sidecar.symlink_to(self.fixed/'model.glb')
        self.expect('STORE_BUSY', self.prepare)

    def test_existing_project_version_or_unsupported_schema_cannot_be_reinterpreted_as_legacy(self):
        with closing(sqlite3.connect(self.store/'library.sqlite3')) as db, db:
            db.execute('create table project_model_versions(version_id text primary key)')
            db.execute('insert into project_model_versions values (?)', (self.version['versionId'],))
        self.expect('NOT_LEGACY_VERSION', self.prepare)
        with closing(sqlite3.connect(self.store/'library.sqlite3')) as db, db:
            db.execute('drop table project_model_versions'); db.execute('alter table bindings add column secret text')
        self.expect('INVALID_STORE', self.prepare)

    def test_json_and_calibration_cannot_carry_credentials_or_fake_server_fields(self):
        path = self.root/'invalid.json'
        path.write_text('{"schemaVersion":1,"schemaVersion":1}')
        self.expect('INVALID_INPUT', lambda: read_json(path))
        for field in ('username', 'password', 'token', 'verifiedBy', 'currentEngineeringProof'):
            values = copy.deepcopy(self.inputs); values[field] = 'not accepted'
            self.expect('INVALID_INPUT', lambda: self.prepare(values))

    def test_cli_writes_only_explicit_new_private_reports_and_no_apply(self):
        inputs_path = self.root/'inputs.json'; inputs_path.write_text(json.dumps(self.inputs))
        output = self.root/'plan.json'; before = self.state()
        args = ['plan', '--library-root', str(self.store), '--version-id', self.version['versionId'],
            '--inputs', str(inputs_path), '--output', str(output)]
        self.assertEqual(main(args), 0); self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.state(), before)
        verified = self.root/'verified.json'
        args[0] = 'verify'; args[-1] = str(verified); args += ['--plan', str(output)]
        self.assertEqual(main(args), 0); self.assertTrue(read_json(verified)['inputsUnchanged'])
        self.assertFalse(read_json(verified)['ready'])
        self.expect('UNSAFE_OUTPUT', lambda: write_report(output, {}, protected=(self.store,)))
        self.expect('UNSAFE_OUTPUT', lambda: write_report(self.store/'new-report.json', {}, protected=(self.store,)))
        link = self.root/'link.json'; link.symlink_to(self.artifact)
        self.expect('UNSAFE_OUTPUT', lambda: write_report(link, {}))
        result = subprocess.run([sys.executable, str(Path(migration.__file__)), 'apply'], capture_output=True)
        self.assertNotEqual(result.returncode, 0); self.assertEqual(self.state(), before)


if __name__ == '__main__': unittest.main()
