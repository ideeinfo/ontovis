import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('model_probe', Path(__file__).parents[1] / 'tools/model_probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class ModelProbeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.positions = [(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)]
        self.binary = struct.pack('<9f3H', *(v for p in self.positions for v in p), 0, 1, 2)
        self.document = {
            'asset': {'version': '2.0', 'generator': 'synthetic test fixture'},
            'scene': 0, 'scenes': [{'nodes': [1]}],
            'nodes': [{'name': 'part', 'mesh': 0, 'extras': {'component': 'cabinet', 'sourceObjectId': 77}},
                      {'children': [0]}],
            'meshes': [{'primitives': [{'attributes': {'POSITION': 0}, 'indices': 1}]}],
            'buffers': [{'byteLength': len(self.binary)}],
            'bufferViews': [{'buffer': 0, 'byteLength': 36}, {'buffer': 0, 'byteOffset': 36, 'byteLength': 6}],
            'accessors': [{'bufferView': 0, 'componentType': 5126, 'type': 'VEC3', 'count': 3,
                           'min': [0, 0, 0], 'max': [1, 1, 0]},
                          {'bufferView': 1, 'componentType': 5123, 'type': 'SCALAR', 'count': 3}],
        }

    def write_glb(self, name='source.glb', document=None, binary=None):
        d = self.document if document is None else document
        b = self.binary if binary is None else binary
        raw = json.dumps(d, separators=(',', ':')).encode()
        raw += b' ' * (-len(raw) % 4)
        b += b'\0' * (-len(b) % 4)
        content = struct.pack('<II', len(raw), 0x4E4F534A) + raw + struct.pack('<II', len(b), 0x004E4942) + b
        path = self.root / name
        path.write_bytes(struct.pack('<4sII', b'glTF', 2, 12 + len(content)) + content)
        return path

    def read_changed(self, change):
        doc = copy.deepcopy(self.document)
        change(doc)
        return probe.Glb(self.write_glb(document=doc))

    def assert_code(self, code, callable_, *args, **kwargs):
        with self.assertRaises(probe.ProbeError) as error:
            callable_(*args, **kwargs)
        self.assertEqual(error.exception.code, code)

    def mapping(self, source):
        return {'sourceSha256': source.sha256, 'sourceMapping': [
            {'sourceNodeIndex': 0, 'sourceObjectId': 77, 'component': 'cabinet',
             'destinationGroup': 'part', 'firstTriangle': 0, 'triangleCount': 1}]}

    def claimed_document(self):
        doc = copy.deepcopy(self.document)
        doc['nodes'][0]['extras']['ontoVis'] = {'sourceModelKey': 'fixture-model',
                                               'sourceElementId': 'fixture-element', 'placementId': 'fixture-placement'}
        return doc

    def control(self, model):
        return {'modelSha256': model.sha256, 'units': 'm', 'basis': 'synthetic_fixture',
                'toleranceMetres': .0001, 'points': [
                    {'id': f'p{i}', 'nodeIndex': 0, 'vertexIndex': i, 'expected': list(p)}
                    for i, p in enumerate(self.positions)]}

    def test_real_vertices_not_declared_bounds_drive_report(self):
        model = self.read_changed(lambda d: d['accessors'][0].update(min=[-100, -100, -100], max=[100, 100, 100]))
        self.assertEqual(model.summary()['bounds']['max'], [1, 1, 0])
        self.assertEqual(model.summary()['triangles'], 1)

    def test_nested_trs_and_parent_matrix_are_applied(self):
        doc = copy.deepcopy(self.document)
        doc['nodes'][0]['translation'] = [0, 2, 0]
        doc['nodes'][1]['matrix'] = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 10, 0, 0, 1]
        self.assertEqual(probe.Glb(self.write_glb(document=doc)).point(0, 0, 1), (11, 2, 0))

    def test_quaternion_rotation_and_scale(self):
        doc = copy.deepcopy(self.document)
        doc['nodes'][0].update(rotation=[0, 0, 2**-.5, 2**-.5], scale=[2, 2, 2])
        point = probe.Glb(self.write_glb(document=doc)).point(0, 0, 1)
        self.assertAlmostEqual(point[0], 0)
        self.assertAlmostEqual(point[1], 2)

    def test_magic_length_and_truncated_chunk_are_rejected(self):
        path = self.write_glb()
        original = path.read_bytes()
        for bad in (b'bad', b'bad!' + original[4:], original[:-1]):
            with self.subTest(size=len(bad)):
                path.write_bytes(bad)
                self.assert_code('INVALID_MODEL', probe.Glb, path)

    def test_wrong_fingerprint_is_rejected(self):
        self.assert_code('DIGEST_MISMATCH', probe.Glb, self.write_glb(), '0' * 64)

    def test_unsupported_minimum_asset_version_is_rejected(self):
        self.assert_code('UNSUPPORTED_MODEL', self.read_changed, lambda d: d['asset'].update(minVersion='2.1'))

    def test_oversized_input_is_rejected_before_reading(self):
        with patch.object(probe, 'MAX_BYTES', 20):
            self.assert_code('LIMIT_EXCEEDED', probe.Glb, self.write_glb())

    def test_uri_inputs_never_fetch_network_or_local_files(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('no fetch')) as fetch:
            for uri in ('https://example.com/model.bin', 'file:///private/secret', '../relative.bin'):
                with self.subTest(uri=uri):
                    self.assert_code('EXTERNAL_RESOURCE', self.read_changed, lambda d: d['buffers'][0].update(uri=uri))
            fetch.assert_not_called()

    def test_external_image_is_also_rejected(self):
        self.assert_code('EXTERNAL_RESOURCE', self.read_changed, lambda d: d.update(images=[{'uri': 'texture.png'}]))

    def test_embedded_data_uri_is_explicitly_outside_probe(self):
        self.assert_code('UNSUPPORTED_RESOURCE', self.read_changed,
                         lambda d: d['buffers'][0].update(uri='data:application/octet-stream;base64,AA=='))

    def test_required_extension_is_not_silently_accepted(self):
        self.assert_code('UNSUPPORTED_EXTENSION', self.read_changed, lambda d: d.update(extensionsRequired=['KHR_draco_mesh_compression']))
        self.assert_code('UNSUPPORTED_EXTENSION', self.read_changed,
                         lambda d: d['bufferViews'][0].update(extensions={'EXT_meshopt_compression': {}}))

    def test_sparse_accessors_and_morphs_have_explicit_limits(self):
        self.assert_code('UNSUPPORTED_MODEL', self.read_changed, lambda d: d['accessors'][0].update(sparse={'count': 1}))
        self.assert_code('UNSUPPORTED_MODEL', self.read_changed, lambda d: d['meshes'][0]['primitives'][0].update(targets=[{'POSITION': 0}]))

    def test_buffer_view_and_accessor_bounds_are_checked(self):
        self.assert_code('INVALID_MODEL', self.read_changed, lambda d: d['bufferViews'][0].update(byteLength=999))
        self.assert_code('INVALID_MODEL', self.read_changed, lambda d: d['accessors'][0].update(count=4))

    def test_interleaved_vertex_stride(self):
        doc = copy.deepcopy(self.document)
        b = struct.pack('<12f3H', *(v for p in self.positions for v in (*p, 9.)), 0, 1, 2)
        doc['buffers'][0]['byteLength'] = len(b)
        doc['bufferViews'][0].update(byteStride=16, byteLength=48)
        doc['bufferViews'][1]['byteOffset'] = 48
        model = probe.Glb(self.write_glb(document=doc, binary=b))
        self.assertEqual(model.point(0, 0, 2), (0, 1, 0))

    def test_out_of_range_and_boolean_indices_are_rejected(self):
        b = struct.pack('<9f3H', *(v for p in self.positions for v in p), 0, 1, 3)
        self.assert_code('INVALID_MODEL', probe.Glb, self.write_glb(binary=b))
        self.assert_code('INVALID_MODEL', self.read_changed, lambda d: d['nodes'][0].update(mesh=True))

    def test_nonfinite_binary_and_json_values_are_rejected(self):
        b = struct.pack('<9f3H', float('nan'), 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 2)
        self.assert_code('INVALID_MODEL', probe.Glb, self.write_glb(binary=b))
        for bad in (b'{"a":NaN}', b'{"a":1e400}', b'{"a":1,"a":2}', b'{"a":' + b'1' * 10000 + b'}'):
            self.assert_code('INVALID_JSON', probe.strict_json, bad)

    def test_cycles_and_multiple_parents_are_rejected(self):
        self.assert_code('INVALID_MODEL', self.read_changed, lambda d: d['nodes'][0].update(children=[1]))
        self.assert_code('INVALID_MODEL', self.read_changed, lambda d: d['nodes'].append({'children': [0]}))

    def test_duplicate_scene_roots_are_rejected(self):
        self.assert_code('INVALID_MODEL', self.read_changed, lambda d: d['scenes'][0].update(nodes=[1, 1]))

    def test_source_names_and_legacy_ids_never_become_stable_keys(self):
        model = self.read_changed(lambda d: d['nodes'][1].update(name='part', extras={'sourceObjectId': 77}))
        catalog = model.catalog()
        self.assertEqual(len({r['componentKey'] for r in catalog}), 2)
        self.assertTrue(all(r['keyStability'] == 'version_local' and not r['sourceIdentityVerified'] for r in catalog))
        self.assertEqual(model.summary()['legacyIdDuplicateValues'], 1)

    def test_source_identity_claim_collision_is_reported(self):
        doc = copy.deepcopy(self.document)
        identity = {'sourceModelKey': 'fixture-model', 'sourceElementId': 'fixture-element', 'placementId': 'fixture-placement'}
        for node in doc['nodes']:
            node.setdefault('extras', {})['ontoVis'] = identity
        rows = probe.Glb(self.write_glb(document=doc)).catalog()
        self.assertEqual([r['sourceIdentityState'] for r in rows], ['collision', 'collision'])
        self.assertFalse(any(r['sourceIdentityVerified'] for r in rows))

    def test_incomplete_and_invalid_claims_keep_raw_attributes_and_diagnostics(self):
        cases = [(None, 'invalid', [], ['ontoVis']),
                 ([], 'invalid', [], ['ontoVis']),
                 ({}, 'incomplete', list(probe.IDENTITY_FIELDS), []),
                 ({'sourceModelKey': 'source'}, 'incomplete', ['sourceElementId', 'placementId'], []),
                 ({'sourceModelKey': ' ', 'sourceElementId': True}, 'invalid', ['placementId'],
                  ['sourceModelKey', 'sourceElementId'])]
        for claim, state, missing, invalid in cases:
            with self.subTest(claim=claim):
                doc = copy.deepcopy(self.document)
                doc['nodes'][0]['extras']['ontoVis'] = claim
                model = probe.Glb(self.write_glb(document=doc))
                row = model.catalog()[0]
                self.assertEqual(row['sourceExtras'], doc['nodes'][0]['extras'])
                self.assertEqual(row['sourceIdentityState'], state)
                self.assertEqual(row['sourceIdentityMissingFields'], missing)
                self.assertEqual(row['sourceIdentityInvalidFields'], invalid)
                self.assertIsNone(row['sourceIdentityClaim'])
                self.assertFalse(row['sourceIdentityVerified'])
                self.assertEqual(model.summary()['sourceIdentityStates'], {state: 1, 'missing': 1})

    def test_missing_null_and_non_object_extras_are_preserved_separately(self):
        for extras in (None, [], 'source text', {'properties': {'enabled': True, 'count': 1}}):
            with self.subTest(extras=extras):
                doc = copy.deepcopy(self.document)
                doc['nodes'][0]['extras'] = extras
                row = probe.Glb(self.write_glb(document=doc)).catalog()[0]
                self.assertTrue(row['sourceExtrasPresent'])
                self.assertEqual(row['sourceExtras'], extras)
                self.assertEqual(row['sourceIdentityState'], 'missing')
        doc['nodes'][0].pop('extras')
        row = probe.Glb(self.write_glb(document=doc)).catalog()[0]
        self.assertFalse(row['sourceExtrasPresent'])
        self.assertIsNone(row['sourceExtras'])

    def test_complete_claim_keeps_case_spaces_and_ignores_self_verification(self):
        doc = self.claimed_document()
        claim = doc['nodes'][0]['extras']['ontoVis']
        claim.update(sourceModelKey=' Source:A ', sourceElementId='UID-Ab', verified=True)
        row = probe.Glb(self.write_glb(document=doc)).catalog()[0]
        self.assertEqual(row['sourceIdentityClaim'], {key: claim[key] for key in probe.IDENTITY_FIELDS})
        self.assertEqual(row['sourceExtras']['ontoVis'], claim)
        self.assertEqual(row['sourceIdentityState'], 'unverified_claim')
        self.assertEqual(row['keyStability'], 'version_local')
        self.assertFalse(row['sourceIdentityVerified'])

    def test_cross_version_candidate_survives_node_reorder_and_name_change(self):
        doc = self.claimed_document()
        previous = probe.Glb(self.write_glb('previous.glb', document=doc))
        doc['nodes'].reverse()
        doc['nodes'][0]['children'] = [1]
        doc['nodes'][1]['name'] = 'renamed'
        doc['scenes'][0]['nodes'] = [0]
        current = probe.Glb(self.write_glb(document=doc))
        result = probe.compare_identity_claims(previous, current)
        self.assertEqual(result['counts']['candidate'], 1)
        row = result['entries'][0]
        self.assertEqual(row['previous'][0]['componentKey'], f'{previous.sha256}:node:0')
        self.assertEqual(row['current'][0]['componentKey'], f'{current.sha256}:node:1')
        self.assertTrue(row['nameChanged'])
        self.assertFalse(row['propertiesChanged'])
        self.assertEqual(result['status'], 'review_required')
        for key in ('sourceIdentityVerified', 'geometryCorrespondenceVerified', 'bindingMigrationApproved'):
            self.assertFalse(result[key])

    def test_identity_comparison_does_not_normalize_any_triple_field(self):
        previous = probe.Glb(self.write_glb('previous.glb', document=self.claimed_document()))
        for key in probe.IDENTITY_FIELDS:
            for change in (str.upper, lambda value: value + ' '):
                with self.subTest(key=key, change=change):
                    doc = self.claimed_document()
                    doc['nodes'][0]['extras']['ontoVis'][key] = change(doc['nodes'][0]['extras']['ontoVis'][key])
                    result = probe.compare_identity_claims(previous, probe.Glb(self.write_glb(document=doc)))
                    self.assertEqual(result['counts']['candidate'], 0)
                    self.assertEqual(result['counts']['previous_only'], 1)
                    self.assertEqual(result['counts']['current_only'], 1)

    def test_same_names_indices_and_legacy_ids_never_fill_missing_identity(self):
        model = probe.Glb(self.write_glb())
        result = probe.compare_identity_claims(model, model)
        self.assertEqual(sum(result['counts'].values()), 0)
        self.assertEqual(result['unavailableCounts'], {'previous': {'missing': 2}, 'current': {'missing': 2}})
        self.assertEqual(len(result['unavailable']), 4)

    def test_duplicate_claim_on_either_side_blocks_candidates_including_inactive_nodes(self):
        doc = self.claimed_document()
        unique = probe.Glb(self.write_glb('unique.glb', document=doc))
        doc['nodes'].append({'extras': copy.deepcopy(doc['nodes'][0]['extras'])})
        duplicate = probe.Glb(self.write_glb(document=doc))
        self.assertEqual(duplicate.catalog()[2]['sourceIdentityState'], 'collision')
        self.assertFalse(duplicate.catalog()[2]['activeScene'])
        for previous, current in ((unique, duplicate), (duplicate, unique)):
            with self.subTest(previous=previous.sha256):
                result = probe.compare_identity_claims(previous, current)
                self.assertEqual(result['counts']['candidate'], 0)
                self.assertEqual(result['counts']['collision'], 1)
                self.assertEqual(sum(len(result['entries'][0][side]) for side in ('previous', 'current')), 3)

    def test_unique_inactive_claim_is_reported_without_candidate(self):
        doc = self.claimed_document()
        doc['nodes'].append({'extras': {'ontoVis': doc['nodes'][0]['extras'].pop('ontoVis')}})
        model = probe.Glb(self.write_glb(document=doc))
        result = probe.compare_identity_claims(model, model)
        self.assertEqual(result['counts']['inactive'], 1)
        self.assertEqual(result['counts']['candidate'], 0)

    def test_added_and_removed_claims_are_listed_beside_unchanged_claim(self):
        doc = self.claimed_document()
        doc['nodes'].append(copy.deepcopy(doc['nodes'][0]))
        doc['nodes'][1]['children'].append(2)
        doc['nodes'][2]['extras']['ontoVis']['sourceElementId'] = 'removed'
        previous = probe.Glb(self.write_glb('previous.glb', document=doc))
        doc['nodes'][2]['extras']['ontoVis']['sourceElementId'] = 'added'
        result = probe.compare_identity_claims(previous, probe.Glb(self.write_glb(document=doc)))
        self.assertEqual(result['counts'], {'candidate': 1, 'collision': 0, 'previous_only': 1, 'current_only': 1, 'inactive': 0})

    def test_property_comparison_preserves_json_types_and_never_follows_attribute_uri(self):
        doc = self.claimed_document()
        doc['nodes'][0]['extras']['properties'] = {'enabled': True, 'values': [None, 2, '2'],
                                                  'uri': 'file:///private/not-a-model-resource'}
        previous = probe.Glb(self.write_glb('previous.glb', document=doc))
        doc['nodes'][0]['extras']['properties']['enabled'] = 1
        with patch('urllib.request.urlopen', side_effect=AssertionError('no fetch')) as fetch:
            current = probe.Glb(self.write_glb(document=doc))
            result = probe.compare_identity_claims(previous, current)
            fetch.assert_not_called()
        self.assertTrue(result['entries'][0]['propertiesChanged'])
        self.assertIs(type(previous.catalog()[0]['sourceExtras']['properties']['enabled']), bool)
        self.assertIs(type(current.catalog()[0]['sourceExtras']['properties']['enabled']), int)

    def test_probe_exports_fingerprinted_catalog_and_review_candidates(self):
        previous = self.write_glb('previous.glb', document=self.claimed_document())
        current = self.write_glb(document=self.claimed_document())
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (previous, current)}
        output = self.root / 'identity-result'
        report = probe.run_probe(current, output, previous_path=previous,
                                 previous_sha256=hashlib.sha256(previous.read_bytes()).hexdigest())
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(report['schemaVersion'], 2)
        self.assertFalse(report['releaseReadiness']['eligible'])
        for key in ('catalog', 'identityComparison'):
            artifact = (output / report[key]['file']).read_bytes()
            self.assertEqual(report[key]['sha256'], hashlib.sha256(artifact).hexdigest())
        catalog = json.loads((output / 'components.json').read_bytes())
        self.assertEqual(set(catalog), {'source', 'previous'})
        self.assertEqual(report['identityComparison']['counts']['candidate'], 1)
        for path, baseline in before.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), baseline)

    def test_wrong_previous_fingerprint_fails_without_exporting_candidates(self):
        path = self.write_glb(document=self.claimed_document())
        output = self.root / 'wrong-previous'
        report = probe.run_probe(path, output, previous_path=path, previous_sha256='0' * 64)
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(report['error']['code'], 'DIGEST_MISMATCH')
        self.assertFalse((output / 'components.json').exists())
        self.assertFalse((output / 'identity-candidates.json').exists())

    def test_cli_previous_source_is_wired_and_unpaired_fingerprint_fails(self):
        path = self.write_glb(document=self.claimed_document())
        fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
        output = self.root / 'cli-identity'
        with patch('builtins.print'):
            self.assertEqual(probe.main(['--source', str(path), '--previous-source', str(path),
                                         '--previous-source-sha256', fingerprint, '--output', str(output)]), 0)
            self.assertEqual(probe.main(['--source', str(path), '--previous-source-sha256', fingerprint,
                                         '--output', str(self.root / 'unpaired')]), 1)
        self.assertEqual(json.loads((output / 'identity-candidates.json').read_bytes())['counts']['candidate'], 1)
        failed = json.loads((self.root / 'unpaired/report.json').read_bytes())
        self.assertEqual(failed['error']['code'], 'INVALID_ARGUMENT')

    def test_failed_geometry_controls_never_export_identity_candidates(self):
        path = self.write_glb(document=self.claimed_document())
        control = self.control(probe.Glb(path))
        control['points'][1]['expected'] = [2, 0, 0]
        controls = self.root / 'control.json'
        controls.write_text(json.dumps(control))
        output = self.root / 'failed-with-identity'
        report = probe.run_probe(path, output, previous_path=path, control_points=controls)
        self.assertEqual(report['status'], 'failed')
        self.assertFalse((output / 'identity-candidates.json').exists())

    def test_full_mapping_compares_decoded_triangle_positions(self):
        source = probe.Glb(self.write_glb())
        report = probe.compare_mapping(source, source, self.mapping(source))
        self.assertEqual(report['trianglesCompared'], 1)
        self.assertEqual(report['maximumVertexAxisError'], 0)

    def test_mapping_missing_hash_and_wrong_hash_are_rejected(self):
        source = probe.Glb(self.write_glb())
        sidecar = self.mapping(source)
        for fingerprint in (None, '0' * 64):
            sidecar['sourceSha256'] = fingerprint
            self.assert_code('DIGEST_MISMATCH', probe.compare_mapping, source, source, sidecar)

    def test_mapping_wrong_derivative_hash_is_rejected(self):
        source = probe.Glb(self.write_glb())
        sidecar = self.mapping(source)
        sidecar['derivedSha256'] = '0' * 64
        self.assert_code('DIGEST_MISMATCH', probe.compare_mapping, source, source, sidecar)

    def test_mapping_overlap_cannot_look_complete(self):
        doc = copy.deepcopy(self.document)
        doc['nodes'].append(copy.deepcopy(doc['nodes'][0]))
        doc['nodes'][1]['children'].append(2)
        source = probe.Glb(self.write_glb(document=doc))
        derived = probe.Glb(self.write_glb('derived.glb'))
        sidecar = self.mapping(source)
        sidecar['sourceMapping'].append(dict(sidecar['sourceMapping'][0], sourceNodeIndex=2))
        self.assert_code('INVALID_MAPPING', probe.compare_mapping, source, derived, sidecar)

    def test_mapping_wrong_attributes_and_missing_group_are_rejected(self):
        source = probe.Glb(self.write_glb())
        for change in ({'component': 'wrong'}, {'destinationGroup': 'missing'}, {'firstTriangle': 1}):
            sidecar = self.mapping(source)
            sidecar['sourceMapping'][0].update(change)
            self.assert_code('INVALID_MAPPING', probe.compare_mapping, source, source, sidecar)

    def test_omitted_source_primitive_is_rejected(self):
        doc = copy.deepcopy(self.document)
        doc['meshes'][0]['primitives'].append(copy.deepcopy(doc['meshes'][0]['primitives'][0]))
        source = probe.Glb(self.write_glb(document=doc))
        derived = probe.Glb(self.write_glb('derived.glb'))
        self.assert_code('INCOMPLETE_MAPPING', probe.compare_mapping, source, derived, self.mapping(source))

    def test_displaced_derived_geometry_is_rejected(self):
        source = probe.Glb(self.write_glb())
        doc = copy.deepcopy(self.document)
        doc['nodes'][0]['translation'] = [1, 0, 0]
        derived = probe.Glb(self.write_glb('derived.glb', document=doc))
        self.assert_code('GEOMETRY_MISMATCH', probe.compare_mapping, source, derived, self.mapping(source))

    def test_mirrored_bake_preserves_correspondence_with_winding_flip(self):
        doc = copy.deepcopy(self.document)
        doc['nodes'][0]['scale'] = [-1, 1, 1]
        source = probe.Glb(self.write_glb(document=doc))
        b = struct.pack('<9f3H', 0, 0, 0, -1, 0, 0, 0, 1, 0, 0, 2, 1)
        derived = probe.Glb(self.write_glb('derived.glb', binary=b))
        self.assertEqual(probe.compare_mapping(source, derived, self.mapping(source))['status'], 'passed')

    def test_missing_control_points_do_not_pass_coordinate_review(self):
        result = probe.check_control_points(probe.Glb(self.write_glb()), None)
        self.assertEqual(result['status'], 'not_provided')
        self.assertFalse(result['engineeringCoordinatesVerified'])

    def test_three_fixture_control_points_never_approve_engineering_coordinates(self):
        model = probe.Glb(self.write_glb())
        result = probe.check_control_points(model, self.control(model))
        self.assertEqual(result['status'], 'passed')
        self.assertFalse(result['engineeringCoordinatesVerified'])

    def test_control_point_deviation_and_collinearity_are_not_passed(self):
        model = probe.Glb(self.write_glb())
        control = self.control(model)
        control['points'][1]['expected'] = [2, 0, 0]
        self.assertEqual(probe.check_control_points(model, control)['status'], 'failed')
        control['points'][2]['expected'] = [3, 0, 0]
        self.assert_code('INVALID_CONTROL_POINTS', probe.check_control_points, model, control)

    def test_failed_probe_persists_failed_report_without_changing_source(self):
        path = self.write_glb()
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        output = self.root / 'failed'
        report = probe.run_probe(path, output, source_sha256='0' * 64)
        self.assertEqual(report['status'], 'failed')
        self.assertFalse(report['releaseReadiness']['eligible'])
        self.assertEqual(json.loads((output / 'report.json').read_text())['error']['code'], 'DIGEST_MISMATCH')
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
        self.assertFalse((output / 'components.json').exists())

    def test_existing_output_is_not_overwritten(self):
        path = self.write_glb()
        output = self.root / 'report'
        probe.run_probe(path, output)
        before = (output / 'report.json').read_bytes()
        with self.assertRaises(FileExistsError):
            probe.run_probe(path, output)
        self.assertEqual((output / 'report.json').read_bytes(), before)

    def test_successful_local_probe_still_blocks_engineering_release(self):
        result = probe.run_probe(self.write_glb(), self.root / 'ok')
        self.assertEqual(result['status'], 'passed')
        self.assertFalse(result['releaseReadiness']['eligible'])
        self.assertFalse(result['releaseReadiness']['G2Passed'])

    def test_checked_mapping_binds_both_artifacts_without_stable_identity_claim(self):
        path = self.write_glb()
        model = probe.Glb(path)
        sidecar_path = self.root / 'sidecar.json'
        sidecar_path.write_text(json.dumps(self.mapping(model)))
        output = self.root / 'checked'
        result = probe.run_probe(path, output, derived_path=path, mapping_path=sidecar_path)
        checked = json.loads((output / 'mapping-checked.json').read_text())
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(checked['sourceSha256'], model.sha256)
        self.assertEqual(checked['derivedSha256'], model.sha256)
        self.assertEqual(checked['keyStability'], 'version_local')
        self.assertEqual(result['mapping']['inputSidecarSha256'], hashlib.sha256(sidecar_path.read_bytes()).hexdigest())

    def test_failed_control_points_make_process_exit_unsuccessfully(self):
        path = self.write_glb()
        model = probe.Glb(path)
        control = self.control(model)
        control['points'][1]['expected'] = [2, 0, 0]
        control_path = self.root / 'controls.json'
        control_path.write_text(json.dumps(control))
        with patch('builtins.print'):
            exit_code = probe.main(['--source', str(path), '--control-points', str(control_path),
                                    '--output', str(self.root / 'bad-controls')])
        self.assertEqual(exit_code, 1)


if __name__ == '__main__':
    unittest.main()
