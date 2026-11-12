"""Bounded source reports over retained GLB; no authority or engineering writes."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from apps.api.authority import PreviewError
from apps.api import model_inspection as inspection
from apps.api.model_validation import validate
from tools.model_probe import Glb
from tests import test_project_model_library as model_fixtures
from tests.test_model_upload import glb


class ModelInspectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = model_fixtures.ProjectModelLibraryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.version = self.fixture.upload()
        self.engine = inspection.ModelInspection(self.fixture.models)
        self.reference = {'modelVersionId': self.version['modelVersionId'],
                          'expectedContentRevision': self.version['contentRevision'],
                          'expectedSha256': self.version['sha256']}

    def read(self, **changes):
        return self.engine.read({**self.reference, **changes}, self.fixture.guard)

    def assertCode(self, code, call):
        with self.assertRaises(PreviewError) as error:
            call()
        self.assertEqual(error.exception.code, code)

    def files(self):
        return {str(path.relative_to(self.fixture.old.root)):
                (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size, path.stat().st_mtime_ns)
                for path in self.fixture.old.root.rglob('*') if path.is_file()}

    def test_default_upload_validation_is_identical_and_does_not_include_source_nodes(self):
        normal = validate(self.fixture.path)
        expanded = validate(self.fixture.path, include_source_nodes=True)
        self.assertNotIn('sourceNodes', normal)
        nodes = expanded.pop('sourceNodes')
        self.assertEqual(normal, expanded)
        self.assertEqual(nodes, Glb(self.fixture.path).catalog())

    def test_real_worker_binds_fixed_version_and_preserves_all_private_files(self):
        before = self.files()
        result = self.read()
        self.assertEqual(result['modelVersionId'], self.reference['modelVersionId'])
        self.assertEqual(result['contentRevision'], self.reference['expectedContentRevision'])
        self.assertEqual(result['sha256'], self.reference['expectedSha256'])
        self.assertEqual(result['processorSha256'], inspection.processor_fingerprint())
        self.assertEqual(result['sourceNodes'], Glb(self.fixture.path).catalog())
        self.assertEqual(result['catalogSha256'], inspection.catalog_digest(result['sourceNodes']))
        self.assertEqual(result['sourceIdentityStates'], {'missing': 3})
        self.assertFalse(result['releaseReadiness']['eligible'])
        self.assertFalse(result['releaseReadiness']['G2Passed'])
        self.assertFalse(result['sourceIdentityVerified'])
        self.assertFalse(result['geometryCorrespondenceVerified'])
        self.assertFalse(result['bindingMigrationApproved'])
        self.assertEqual(self.files(), before)

    def test_raw_types_null_missing_and_attribute_uris_are_preserved_without_fetching(self):
        def change(doc):
            del doc['nodes'][0]['extras']
            doc['nodes'][1]['extras'] = None
            doc['nodes'][2]['extras'] = {'fixtureBool': True, 'fixtureNumber': 1,
                'fixtureArray': [False, 0, None, {'uri': 'https://example.invalid/source'}],
                'ontoVis': {'sourceModelKey': ' Key ', 'sourceElementId': 'PART', 'placementId': ' p ',
                            'sourceIdentityVerified': True, 'bindingMigrationApproved': True}}
        path = glb(self.fixture.root / 'attributes.glb', change)
        with patch('urllib.request.urlopen', side_effect=AssertionError('must never fetch')):
            result = inspection.inspect(path)
        nodes = result['sourceNodes']
        self.assertFalse(nodes[0]['sourceExtrasPresent'])
        self.assertTrue(nodes[1]['sourceExtrasPresent'])
        self.assertIsNone(nodes[1]['sourceExtras'])
        self.assertIs(nodes[2]['sourceExtras']['fixtureBool'], True)
        self.assertEqual(type(nodes[2]['sourceExtras']['fixtureNumber']), int)
        self.assertEqual(nodes[2]['sourceIdentityClaim'], {'sourceModelKey': ' Key ', 'sourceElementId': 'PART', 'placementId': ' p '})
        self.assertEqual(nodes[2]['sourceIdentityState'], 'unverified_claim')
        self.assertFalse(nodes[2]['sourceIdentityVerified'])

    def test_inactive_duplicate_claims_remain_collisions(self):
        def change(doc):
            claim = {'sourceModelKey': 'fixture', 'sourceElementId': 'part', 'placementId': 'place'}
            doc['nodes'][0]['extras']['ontoVis'] = claim
            doc['nodes'].append({'name': 'inactive duplicate', 'extras': {'ontoVis': claim}})
        result = inspection.inspect(glb(self.fixture.root / 'collision.glb', change))
        self.assertEqual(result['sourceIdentityStates'], {'collision': 2, 'missing': 2})
        self.assertFalse(result['sourceNodes'][3]['activeScene'])
        self.assertFalse(result['sourceIdentityVerified'])

    def test_calibrated_fixed_version_keeps_its_calibration_separate_from_raw_source_report(self):
        calibrated = self.fixture.calibrate(self.version)
        reference = {'modelVersionId': calibrated['modelVersionId'], 'expectedContentRevision': calibrated['contentRevision'],
                     'expectedSha256': calibrated['sha256']}
        before = self.fixture.model(calibrated)
        report = self.engine.read(reference, self.fixture.guard)
        self.assertEqual(report['scope'], 'fixed_glb_source_local_only')
        self.assertEqual(report['sourceValidation']['coordinateVerification'], 'unverified')
        self.assertEqual(before, self.fixture.model(calibrated))
        self.assertEqual(before['report']['coordinateVerification'], 'operator_calibrated')

    def test_stale_content_and_extra_fields_never_start_a_worker(self):
        with patch.object(self.engine, '_process', side_effect=AssertionError('must reject before processing')):
            self.assertCode('RESOURCE_CHANGED', lambda: self.read(expectedContentRevision='stale'))
            self.assertCode('RESOURCE_CHANGED', lambda: self.read(expectedSha256='0' * 64))
            self.assertCode('INVALID_REQUEST', lambda: self.read(path='/etc/passwd'))
            self.assertCode('INVALID_REQUEST', lambda: self.read(modelVersionId='../wrong'))
            self.assertCode('INVALID_REQUEST', lambda: self.read(expectedSha256=True))

    def test_shared_processing_slot_is_busy_and_always_released(self):
        self.fixture.old.slots.acquire()
        try:
            self.assertCode('MODEL_BUSY', self.read)
        finally:
            self.fixture.old.slots.release()
        with patch.object(self.engine, '_process', side_effect=PreviewError(422, 'INVALID_MODEL')):
            self.assertCode('INVALID_MODEL', self.read)
        self.assertTrue(self.fixture.old.slots.acquire(blocking=False))
        self.fixture.old.slots.release()
        self.assertEqual(self.read()['sha256'], self.version['sha256'])

    def test_revocation_after_processing_suppresses_all_results(self):
        original = self.engine._process
        def revoke(path):
            value = original(path)
            self.fixture.guard.allowed = False
            return value
        with patch.object(self.engine, '_process', side_effect=revoke):
            self.assertCode('MODEL_WRITE_FORBIDDEN', self.read)
        self.fixture.guard.allowed = True
        self.assertEqual(self.read()['sha256'], self.version['sha256'])

    def test_changed_or_linked_retained_file_never_returns_a_report(self):
        path = self.fixture.old.root / 'files' / (self.version['modelVersionId'] + '.glb')
        data = path.read_bytes()
        path.write_bytes(data + b'changed')
        self.assertCode('RESOURCE_CHANGED', self.read)
        path.write_bytes(data)
        linked = path.with_suffix('.link')
        os.link(path, linked)
        self.assertCode('RESOURCE_CHANGED', self.read)
        linked.unlink()
        path.unlink(); path.symlink_to(self.fixture.path)
        self.assertCode('RESOURCE_CHANGED', self.read)

    def test_source_changed_while_processing_is_rejected(self):
        path = self.fixture.old.root / 'files' / (self.version['modelVersionId'] + '.glb')
        original = self.engine._process
        def changed(source):
            result = original(source)
            path.write_bytes(path.read_bytes() + b'changed')
            return result
        with patch.object(self.engine, '_process', side_effect=changed):
            self.assertCode('RESOURCE_CHANGED', self.read)

    def test_forged_worker_flags_fingerprints_and_node_keys_are_rejected(self):
        result = self.read()
        variants = [None, [], {**result, 'sourceIdentityVerified': True}, {**result, 'bindingMigrationApproved': True},
                    {**result, 'processorSha256': '0' * 64}, {**result, 'catalogSha256': '0' * 64},
                    {**result, 'sourceIdentityStates': {'unverified_claim': 3}}]
        changed = copy.deepcopy(result)
        changed['sourceNodes'][0]['componentKey'] = 'component:0'
        changed['catalogSha256'] = inspection.catalog_digest(changed['sourceNodes'])
        variants.append(changed)
        for value in variants:
            with self.subTest(value=type(value).__name__), patch.object(self.engine, '_process', return_value=value):
                self.assertCode('MODEL_INSPECTION_UNAVAILABLE', self.read)

    def worker_stub(self, program):
        original = subprocess.Popen
        def launch(_args, **kwargs):
            return original([sys.executable, '-c', program], **kwargs)
        return launch

    def test_invalid_worker_output_and_unsupported_errors_are_bounded(self):
        for program, code in [("print('not json')", 'MODEL_INSPECTION_UNAVAILABLE'),
                              ("print('[]')", 'MODEL_INSPECTION_UNAVAILABLE'),
                              ("print('{\"code\":\"UNSUPPORTED_MODEL\"}');exit(2)", 'UNSUPPORTED_MODEL')]:
            with self.subTest(code=code), patch.object(inspection.subprocess, 'Popen', side_effect=self.worker_stub(program)):
                self.assertCode(code, self.read)

    def test_slow_or_oversized_worker_is_killed_and_slot_released(self):
        program = 'import time;time.sleep(60)'
        with patch.object(inspection, 'TIMEOUT_SECONDS', .15), patch.object(inspection.subprocess, 'Popen', side_effect=self.worker_stub(program)):
            self.assertCode('MODEL_LIMIT_EXCEEDED', self.read)
        with patch.object(inspection, 'MAX_OUTPUT_BYTES', 32), patch.object(inspection.subprocess, 'Popen',
                side_effect=self.worker_stub("print('x'*1000)")):
            self.assertCode('MODEL_LIMIT_EXCEEDED', self.read)
        self.assertTrue(self.fixture.old.slots.acquire(blocking=False))
        self.fixture.old.slots.release()

    def test_worker_stops_when_owner_pipe_closes(self):
        ready = self.fixture.root / 'watchdog-ready'
        program = ("import sys,time;from pathlib import Path;from apps.api import model_inspection as m\n"
                   f"def slow(path):\n Path({str(ready)!r}).write_text('ready')\n time.sleep(60)\n"
                   "m.inspect=slow\nm.TIMEOUT_SECONDS=5\nraise SystemExit(m.main())\n")
        process = subprocess.Popen([sys.executable, '-c', program, str(self.fixture.path)],
                                   stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 3
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(ready.exists())
            process.stdin.close()
            self.assertEqual(process.wait(timeout=3), 125)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=3)
            if not process.stdin.closed:
                process.stdin.close()


if __name__ == '__main__':
    unittest.main()
