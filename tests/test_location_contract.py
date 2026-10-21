import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / 'tests/fixtures/location_contract.json'
spec = importlib.util.spec_from_file_location('location_contract', ROOT / 'tools/location_contract.py')
contract = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = contract
spec.loader.exec_module(contract)


class LocationContractTests(unittest.TestCase):
    def setUp(self):
        self.suite = json.loads(FIXTURES.read_text(encoding='utf-8'))
        self.request = copy.deepcopy(self.suite['baseRequest'])
        self.facts = copy.deepcopy(self.suite['baseFacts'])

    def ref(self, uid):
        return {'ontobaseConnectionId': 'fixture-ob', 'projectCode': 'fixture-project',
                'entityUid': 'fixture-' + uid}

    def evaluate(self):
        return contract.evaluate(self.request, self.facts)

    def assert_unlocated(self, code):
        result = self.evaluate()
        self.assertEqual(result['reasonCode'], code)
        self.assertEqual(result['locationMode'], 'unlocated')
        self.assertIsNone(result['locatedObjectRef'])
        for key in ('geometryQuality', 'modelVersionId', 'sceneModelInstanceId', 'componentKey'):
            self.assertIsNone(result[key])
        self.assertEqual(result['componentKeys'], [])
        self.assertEqual(result['path'], [])
        return result

    def history(self):
        self.request.update(resolutionMode='history', asOf=self.facts['resolvedAsOf'],
                            sceneRevision='fixture-scene-r1')

    def multi_representation(self):
        original = self.facts['representations'][2]
        original['reviewedPrimary'] = False
        alternative = copy.deepcopy(original)
        alternative['componentKeys'] = ['fixture-cn-body-alt']
        self.facts['representations'].append(alternative)
        return original, alternative

    def test_curated_request_response_examples_match_exactly(self):
        report = contract.run_suite(FIXTURES)
        for case in report['cases']:
            with self.subTest(case=case['caseId']):
                self.assertEqual(case['actual'], case['expected'])
        self.assertEqual(report['caseCount'], 32)
        self.assertEqual(report['passedCount'], 32)
        self.assertFalse(report['realIntegrationPassed'])
        for gate in ('G1Passed', 'G2Passed', 'G3Passed'):
            self.assertFalse(report[gate])

    def test_child_identity_and_parent_geometry_remain_separate(self):
        before = copy.deepcopy(self.facts)
        result = self.evaluate()
        self.assertEqual(result['selectedObjectRef'], self.ref('controller'))
        self.assertEqual(result['locatedObjectRef'], self.ref('cn'))
        self.assertEqual(result['componentKeys'], ['fixture-cn-body', 'fixture-cn-door'])
        self.assertIn('内部坐标未知', result['reason'])
        self.assertNotIn('directBinding', result)  # No fabricated child binding or cabinet coordinate.
        self.assertEqual(self.facts, before)

    def test_denied_project_never_reads_object_or_path_payload(self):
        self.facts['access']['project'] = False
        self.facts['objects'] = [{'private': 'fixture-hidden-name'}]
        self.facts['hierarchy'] = {'private': 'fixture-hidden-path'}
        result = self.evaluate()
        self.assertEqual(result['code'], 'FORBIDDEN')
        self.assertEqual(set(result), {'code', 'message', 'retryable', 'requestId'})
        self.assertNotIn('fixture-hidden', json.dumps(result))

    def test_missing_and_invisible_object_have_the_same_safe_error(self):
        self.facts['objects'] = self.facts['objects'][1:]
        missing = self.evaluate()
        self.setUp()
        self.facts['access']['objectRefs'] = self.facts['access']['objectRefs'][1:]
        self.assertEqual(missing, self.evaluate())

    def test_same_uid_in_another_connection_is_not_the_same_object(self):
        self.request['selectedObjectRef']['ontobaseConnectionId'] = 'fixture-other-ob'
        self.assertEqual(self.evaluate()['code'], 'NOT_FOUND_OR_FORBIDDEN')

    def test_current_permission_is_checked_for_history_too(self):
        self.history()
        self.facts['access']['objectRefs'] = []
        self.assertEqual(self.evaluate()['code'], 'NOT_FOUND_OR_FORBIDDEN')

    def test_hidden_ancestor_does_not_leak_names_or_partial_path(self):
        self.facts['access']['objectRefs'].remove(self.ref('unit'))
        self.facts['hierarchy']['path'][1]['privateLabel'] = 'fixture-hidden-parent-name'
        result = self.assert_unlocated('PATH_UNAVAILABLE')
        self.assertNotIn('fixture-hidden-parent-name', json.dumps(result))
        self.assertEqual(result['selectedObjectRef'], self.ref('controller'))

    def test_canonical_in_another_project_is_not_exposed(self):
        canonical = self.ref('canonical') | {'projectCode': 'fixture-other-project'}
        self.facts['objects'][0].update(resolution='merged', canonicalRef=canonical)
        self.facts['access']['objectRefs'].append(canonical)
        result = self.assert_unlocated('IDENTITY_CHANGED')
        self.assertIsNone(result['canonicalObjectRef'])
        self.assertEqual(result['selectedObjectRef'], self.ref('controller'))

    def test_retired_or_merged_ancestor_does_not_fall_back_to_unit(self):
        for change, code in (({'lifecycle': 'retired'}, 'OBJECT_RETIRED'),
                             ({'resolution': 'merged'}, 'IDENTITY_CHANGED')):
            with self.subTest(change=change):
                self.setUp()
                self.facts['objects'][3].update(change)
                self.assert_unlocated(code)

    def test_changed_entity_revision_invalidates_old_binding(self):
        self.facts['objects'][3]['entityRevision'] = 'fixture-entity-r2'
        self.assert_unlocated('IDENTITY_CHANGED')

    def test_wrong_model_binding_or_component_cannot_locate(self):
        changes = ({'modelVersionId': 'fixture-model-v2'},
                   {'bindingRevision': 'fixture-binding-r2'},
                   {'sceneRevision': 'fixture-scene-r2'},
                   {'componentKeys': ['fixture-missing-component']},
                   {'componentKeys': ['fixture-cn-body', 'fixture-cn-body']})
        for change in changes:
            with self.subTest(change=change):
                self.setUp()
                self.facts['representations'][2].update(change)
                self.assert_unlocated('REVISION_CONFLICT')

    def test_draft_binding_is_not_a_published_child_binding(self):
        draft = copy.deepcopy(self.facts['representations'][2])
        draft.update(objectRef=self.ref('controller'), status='draft')
        self.facts['representations'].append(draft)
        self.assertEqual(self.evaluate()['locationMode'], 'ancestor_proxy')

    def test_single_reviewed_primary_selects_a_complete_representation(self):
        original, alternative = self.multi_representation()
        original['reviewedPrimary'] = True
        self.assertEqual(self.evaluate()['componentKeys'], original['componentKeys'])
        self.assertNotEqual(self.evaluate()['componentKeys'], alternative['componentKeys'])

    def test_two_reviewed_primaries_still_require_selection(self):
        original, alternative = self.multi_representation()
        original['reviewedPrimary'] = alternative['reviewedPrimary'] = True
        result = self.assert_unlocated('MULTIPLE_REPRESENTATIONS')
        self.assertEqual(len(result['representationChoices']), 2)

    def test_representation_choice_is_checked_again_after_republication(self):
        original, _ = self.multi_representation()
        self.request['representationChoice'] = {k: copy.deepcopy(original[k]) for k in contract.CHOICE_FIELDS}
        self.request['representationChoice']['sceneRevision'] = 'fixture-old-scene'
        self.assert_unlocated('REVISION_CONFLICT')

    def test_explicit_instance_filters_other_independent_representations(self):
        original, alternative = self.multi_representation()
        instance = copy.deepcopy(self.facts['scene']['instances'][0])
        instance.update(sceneModelInstanceId='fixture-instance-2', modelVersionId='fixture-model-v2')
        self.facts['scene']['instances'].append(instance)
        alternative.update(sceneModelInstanceId='fixture-instance-2', modelVersionId='fixture-model-v2')
        self.request['sceneModelInstanceId'] = 'fixture-instance-2'
        result = self.evaluate()
        self.assertEqual(result['modelVersionId'], 'fixture-model-v2')
        self.assertEqual(result['componentKeys'], alternative['componentKeys'])
        self.assertNotEqual(result['sceneModelInstanceId'], original['sceneModelInstanceId'])

    def test_representation_in_another_installation_cannot_be_selected(self):
        self.facts['scene']['instances'][0]['installationContextId'] = 'fixture-other-installation'
        self.assert_unlocated('INSTANCE_MISMATCH')

    def test_explicit_other_installation_is_rejected_without_matching_geometry(self):
        instance = copy.deepcopy(self.facts['scene']['instances'][0])
        instance.update(sceneModelInstanceId='fixture-instance-2',
                        installationContextId='fixture-other-installation')
        self.facts['scene']['instances'].append(instance)
        self.request['sceneModelInstanceId'] = 'fixture-instance-2'
        self.assert_unlocated('INSTANCE_MISMATCH')

    def test_cycle_and_discontinuous_chain_are_unlocated(self):
        self.facts['hierarchy']['path'][1]['parentRef'] = self.ref('controller')
        self.assert_unlocated('CYCLE_DETECTED')
        self.setUp()
        self.facts['hierarchy']['path'][1]['childRef'] = self.ref('ct')
        self.assert_unlocated('PATH_UNAVAILABLE')

    def test_unconfirmed_or_unsupported_relation_is_not_accepted(self):
        for change in ({'status': 'candidate'}, {'status': 'electrical_connection'}, {'evidenceRefs': []}):
            with self.subTest(change=change):
                self.setUp()
                self.facts['hierarchy']['path'][0].update(change)
                self.assert_unlocated('NO_CONFIRMED_PATH')

    def test_relation_end_is_exclusive_and_invalid_intervals_are_rejected(self):
        first = self.facts['hierarchy']['path'][0]
        first['validTo'] = self.facts['resolvedAsOf']
        self.assert_unlocated('NO_CONFIRMED_PATH')
        first['validFrom'], first['validTo'] = '2026-10-21T00:00:00Z', '2026-10-01T00:00:00Z'
        self.assert_unlocated('NO_CONFIRMED_PATH')

    def test_explicit_utc_required_for_request_and_relation_times(self):
        for bad in ('2026-10-20T06:00:00', '2026-10-20T14:00:00+08:00', 'not-a-time'):
            with self.subTest(timestamp=bad):
                with self.assertRaises(contract.FixtureError):
                    contract.instant(bad)

    def test_equivalent_utc_serializations_use_the_same_snapshot(self):
        self.facts['hierarchy']['resolvedAsOf'] = '2026-10-20T06:00:00+00:00'
        self.assertEqual(self.evaluate(), self.suite['baseExpected'])

    def test_depth_and_incomplete_snapshot_signals_are_not_success(self):
        for value, code in (('unavailable', 'PATH_UNAVAILABLE'), ('truncated', 'DEPTH_LIMIT'),
                            ('multiple_parents', 'MULTIPLE_PARENTS'), ('cycle', 'CYCLE_DETECTED')):
            with self.subTest(completeness=value):
                self.facts['hierarchy']['completeness'] = value
                self.assert_unlocated(code)
        self.setUp()
        self.facts['hierarchy']['path'] *= 17
        self.assert_unlocated('DEPTH_LIMIT')

    def test_confirmed_root_without_geometry_is_not_a_fake_location(self):
        self.facts['hierarchy']['path'] = []
        self.assert_unlocated('NO_GEOMETRY')

    def test_explicit_history_tree_is_required_even_for_direct_geometry(self):
        self.history()
        self.request.update(selectedObjectRef=self.ref('cn'), hierarchyRevision='fixture-missing-tree')
        self.assert_unlocated('HISTORY_UNAVAILABLE')

    def test_missing_binding_history_does_not_report_current_binding(self):
        self.history()
        self.facts['scene']['unavailableParts'] = ['binding']
        result = self.assert_unlocated('HISTORY_UNAVAILABLE')
        self.assertIsNone(result['bindingRevision'])

    def test_authority_timestamp_mismatch_is_an_error_even_with_direct_geometry(self):
        self.history()
        self.request['selectedObjectRef'] = self.ref('cn')
        self.request['asOf'] = '2026-10-01T00:00:00Z'
        self.assertEqual(self.evaluate()['code'], 'REVISION_CONFLICT')

    def test_history_hierarchy_mismatch_never_uses_latest_tree(self):
        self.history()
        self.facts['hierarchy']['resolvedAsOf'] = '2026-10-01T00:00:00Z'
        self.assertEqual(self.evaluate()['code'], 'REVISION_CONFLICT')

    def test_history_requires_both_time_and_scene_revision(self):
        self.request['resolutionMode'] = 'history'
        with self.assertRaises(contract.FixtureError):
            self.evaluate()
        self.request['asOf'] = self.facts['resolvedAsOf']
        with self.assertRaises(contract.FixtureError):
            self.evaluate()

    def test_live_cannot_claim_authoritative_time_or_revisions(self):
        for key, value in (('asOf', self.facts['resolvedAsOf']), ('sceneRevision', 'fixture-scene-r1'),
                           ('hierarchyRevision', 'fixture-tree-r1')):
            with self.subTest(key=key):
                self.setUp()
                self.request[key] = value
                with self.assertRaises(contract.FixtureError):
                    self.evaluate()

    def test_client_capabilities_or_parent_paths_cannot_be_supplied(self):
        for key in ('capabilities', 'parentRef', 'path'):
            with self.subTest(key=key):
                self.setUp()
                self.request[key] = []
                with self.assertRaises(contract.FixtureError):
                    self.evaluate()

    def test_real_object_identifiers_are_rejected_by_this_fixture_tool(self):
        self.request['selectedObjectRef']['entityUid'] = 'real-uid-not-a-fixture'
        with self.assertRaises(contract.FixtureError):
            self.evaluate()

    def test_string_false_is_not_a_trusted_boolean_permission(self):
        self.facts['access']['project'] = 'false'
        with self.assertRaises(contract.FixtureError):
            self.evaluate()

    def test_returned_collections_do_not_mutate_inputs(self):
        result = self.evaluate()
        result['componentKeys'].clear()
        result['selectedObjectRef']['entityUid'] = 'fixture-changed'
        result['path'][0]['evidenceRefs'].clear()
        self.assertEqual(self.evaluate(), self.suite['baseExpected'])

    def test_evaluation_and_fixture_suite_never_open_a_network_socket(self):
        with patch('socket.socket', side_effect=AssertionError('no network')):
            self.assertEqual(contract.run_suite(FIXTURES)['status'], 'passed')


class LocationContractRunnerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.suite = json.loads(FIXTURES.read_text(encoding='utf-8'))

    def write_suite(self):
        path = self.root / 'fixture.json'
        path.write_text(json.dumps(self.suite), encoding='utf-8')
        return path

    def test_runner_exports_complete_inputs_and_real_validation_stays_false(self):
        output = self.root / 'report'
        with patch.object(sys, 'argv', ['location_contract', '--fixtures', str(FIXTURES), '--output', str(output)]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(contract.main(), 0)
        report = json.loads((output / 'report.json').read_text())
        self.assertEqual(report['verificationScope'], 'offline_contract_only')
        self.assertFalse(report['realIntegrationPassed'])
        self.assertIn('recordedAuthority', report['cases'][0])
        self.assertEqual(report['cases'][0]['actual'], report['cases'][0]['expected'])

    def test_wrong_expected_response_fails_and_is_saved_for_review(self):
        self.suite['cases'][0]['expected'] = {'locationMode': 'direct_geometry'}
        path, output = self.write_suite(), self.root / 'failed-report'
        with patch.object(sys, 'argv', ['location_contract', '--fixtures', str(path), '--output', str(output)]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(contract.main(), 1)
        report = json.loads((output / 'report.json').read_text())
        self.assertEqual(report['status'], 'failed')
        self.assertFalse(report['cases'][0]['passed'])

    def test_existing_report_directory_is_never_overwritten(self):
        sentinel = self.root / 'report.json'
        sentinel.write_text('preserve', encoding='utf-8')
        with patch.object(sys, 'argv', ['location_contract', '--fixtures', str(FIXTURES), '--output', str(self.root)]), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(contract.main(), 1)
        self.assertEqual(sentinel.read_text(), 'preserve')

    def test_malformed_input_has_an_explicit_failed_report(self):
        bad, output = self.root / 'bad.json', self.root / 'bad-report'
        bad.write_text('{', encoding='utf-8')
        with patch.object(sys, 'argv', ['location_contract', '--fixtures', str(bad), '--output', str(output)]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(contract.main(), 1)
        report = json.loads((output / 'report.json').read_text())
        self.assertEqual(report['status'], 'failed')
        self.assertFalse(report['realIntegrationPassed'])

    def test_missing_synthetic_label_empty_or_duplicate_suite_cannot_pass(self):
        for mutate in (lambda s: s.update(fixtureKind='live'), lambda s: s.update(cases=[]),
                       lambda s: s['cases'].append(s['cases'][0])):
            with self.subTest(mutation=mutate):
                self.suite = json.loads(FIXTURES.read_text(encoding='utf-8'))
                mutate(self.suite)
                with self.assertRaises(contract.FixtureError):
                    contract.run_suite(self.write_suite())

    def test_duplicate_json_fields_are_rejected(self):
        path = self.root / 'duplicate.json'
        path.write_text('{"fixtureKind":"live","fixtureKind":"synthetic_location_contract"}')
        with self.assertRaises(contract.FixtureError):
            contract.run_suite(path)

    def test_unknown_case_overrides_and_conflicting_expectations_are_rejected(self):
        for key, value in (('facts', {'accessTypo': True}), ('request', {'sceneTypo': 'fixture-scene'}),
                           ('expectedError', {'code': 'FORBIDDEN'})):
            with self.subTest(key=key):
                self.suite = json.loads(FIXTURES.read_text(encoding='utf-8'))
                self.suite['cases'][0][key] = value
                with self.assertRaises(contract.FixtureError):
                    contract.run_suite(self.write_suite())


if __name__ == '__main__':
    unittest.main()
