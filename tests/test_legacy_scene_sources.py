"""Private real GLB/SQLite sources, with the actual Reader and synthetic OB APIs."""
import copy
import hashlib
import json
import struct
from unittest.mock import patch
import unittest

from apps.api.authority import PreviewError
from apps.api.legacy_scene_sources import LegacySceneSources
from apps.api.model_assets import ModelAsset
from apps.api.scene_engineering import SceneEngineeringReader
from tests import test_legacy_scene_registry as registry
from tests import test_scene_engineering as engineering


class LegacySceneSourcesTests(unittest.TestCase):
    def setUp(self):
        self.fixture = registry.LegacySceneRegistryTests()
        original = registry.glb
        def depth_glb(path):
            original(path); raw = path.read_bytes()
            path.write_bytes(raw[:-4]+struct.pack('<f', 1))
            return path
        with patch.object(registry, 'glb', side_effect=depth_glb): self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.source = engineering.SyntheticAuthority()
        self.source.resolve_project = f.registry.project
        self.source.contexts = {f.context: self.source.context(f.context, 'ROOT')}
        self.source.contexts[f.context].update(projectCode=f.registry.project, hierarchyRevision=f.context+':1')
        self.source.objects = {uid: {**self.source.object(uid, f.context), 'entityRevision': 'object:1'}
                               for uid in ('ROOT', 'CT', 'CN1', 'CN')}
        self.source.parents = {uid: 'ROOT' for uid in ('CT', 'CN1', 'CN')}
        self.source.relations = {(uid, 'ROOT'): self.source.relation(uid, 'ROOT') for uid in self.source.parents}
        for relation in self.source.relations.values():
            relation['relationRevision'] = relation['relationId']+':1'
        self.reader = SceneEngineeringReader(self.source, 'synthetic-connection', f.registry.project, self.source.guard)
        self.fixed_root = f.root/'fixed'; self.fixed_root.mkdir()
        (self.fixed_root/'model.glb').write_bytes(f.library.content(f.library.version(f.legacy['versionId'])))
        parts = {part['componentKey']: part for part in f.library.version(f.legacy['versionId'])['components']}
        self.config = {'schemaVersion': 1, 'projectCode': f.registry.project, 'installationContextId': f.context,
            'rootEntityUid': 'ROOT', 'sha256': f.legacy['sha256'], 'licenceBasis': 'Synthetic declared source',
            'sourceModelSha256': f.legacy['sha256'], 'bindings': [{'entityUid': role, 'entityRevision': 'object:1',
                'componentKey': role, 'geometryQuality': parts[key]['geometryQuality'], 'bounds': parts[key]['bounds']}
                for role, key in (('CT', 'proxy:CT'), ('CN1', 'proxy:CN1'), ('CN', 'component:2'))]}
        self.reload()

    def reload(self):
        (self.fixed_root/'model.json').write_text(json.dumps(self.config))
        f = self.fixture
        self.sources = LegacySceneSources(f.library, ModelAsset(self.fixed_root, f.registry.project, f.context), self.reader)
        catalog = self.sources.inventory(); self.catalog = catalog
        f.body['expectedLibraryRevision'] = catalog['libraryRevision']; f.body['defaultSourceKey'] = catalog['defaultSourceKey']
        for item in f.body['sources']:
            if item['sourceKind'] == 'fixed_model': item['sourceKey'] = catalog['defaultSourceKey']
            item['expectedSourceDigest'] = next(source['sourceDigest'] for source in catalog['items']
                if (source['sourceKind'], source['sourceKey']) == (item['sourceKind'], item['sourceKey']))

    def check(self):
        return self.fixture.check(validator=self.sources)

    def expect(self, code, action):
        with self.assertRaises(PreviewError) as caught: action()
        self.assertEqual(caught.exception.code, code)

    def test_exact_sources_remain_separate_and_check_does_not_write_or_expose_private_facts(self):
        before = self.fixture.counts(); self.check()
        self.assertEqual(self.fixture.counts(), before)
        self.assertEqual(len(self.catalog['items']), 2)
        self.assertEqual(self.catalog['defaultSourceKey'], hashlib.sha256((self.fixed_root/'model.json').read_bytes()).hexdigest())
        self.assertTrue(all(set(item) == {'sourceKind', 'sourceKey', 'sourceDigest'} for item in self.catalog['items']))
        self.assertNotIn(str(self.fixed_root), json.dumps(self.catalog)); self.assertNotIn('ROOT', json.dumps(self.catalog))
        self.assertTrue(any('/ancestors?' in path for _, path, _ in self.source.calls))

    def test_changed_file_after_inventory_and_before_activation_is_rejected(self):
        checked = self.check(); f = self.fixture
        raw = (self.fixed_root/'model.glb').read_bytes()
        (self.fixed_root/'model.glb').write_bytes(raw[:-1]+bytes([raw[-1]^1]))
        body = {**f.body, 'receipt': checked['receipt'], 'clientRequestId': registry.uuid4().__str__()}
        self.expect('LEGACY_SOURCE_CHANGED', lambda: f.activate(body, validator=self.sources))
        self.assertEqual(f.counts(), [0, 0, 0])

    def test_original_rights_cannot_be_replaced_by_target_or_browser_declaration(self):
        with self.fixture.library.connect() as db:
            db.execute("update audit set payload=? where action='model_uploaded'", (json.dumps({'rightsDeclared': False}),))
        self.reload()
        self.expect('MODEL_SOURCE_RIGHTS_REQUIRED', self.check)

    def test_current_cabinet_entity_or_hierarchy_change_does_not_silently_upgrade_old_conditions(self):
        for kind in ('entity', 'hierarchy'):
            with self.subTest(kind=kind):
                old = copy.deepcopy((self.source.objects, self.source.contexts))
                if kind == 'entity': self.source.objects['CT']['entityRevision'] = 'object:2'
                else: self.source.contexts[self.fixture.context]['hierarchyRevision'] = self.fixture.context+':2'
                self.expect('ENGINEERING_CHANGED', self.check)
                self.source.objects, self.source.contexts = old

    def test_incomplete_chain_and_project_or_session_revocation_never_yield_current_proof(self):
        self.source.ancestor_edit = lambda value: value.update(completeness='incomplete', reasonCode='PATH_UNAVAILABLE')
        self.expect('ENGINEERING_CHANGED', self.check)
        self.source.ancestor_edit = None; self.source.allowed = False
        self.expect('FORBIDDEN', self.check)
        self.assertEqual(self.fixture.counts(), [0, 0, 0])

    def test_copied_directory_or_changed_node_indices_cannot_override_real_glb(self):
        f = self.fixture
        with f.library.connect() as db:
            row = db.execute('select components from versions where id=?', (f.legacy['versionId'],)).fetchone()
            parts = json.loads(row[0]); parts[0]['nodeIndices'] = [1999]
            db.execute('update versions set components=? where id=?', (json.dumps(parts), f.legacy['versionId']))
        self.reload(); self.expect('LEGACY_TARGET_INVALID', self.check)

    def test_only_identical_float32_source_cn_bounds_are_compatible_and_proxies_stay_exact(self):
        cn = next(row for row in self.config['bindings'] if row['componentKey'] == 'CN')
        cn['bounds'][1][0] += 1e-8
        self.reload(); self.check()
        cn['bounds'][1][0] += 0.001
        self.reload(); self.expect('LEGACY_SOURCE_NOT_MIGRATABLE', self.check)
        cn['bounds'][1][0] = 1
        next(row for row in self.config['bindings'] if row['componentKey'] == 'CT')['bounds'][1][0] += 1e-8
        self.reload(); self.expect('LEGACY_SOURCE_NOT_MIGRATABLE', self.check)

    def test_final_recheck_catches_late_fixed_or_target_file_replacement(self):
        original = self.sources._finish
        for path in (self.fixed_root/'model.json', self.fixed_root/'model.glb',
                     self.fixture.library.root/'files'/(self.fixture.model['modelVersionId']+'.glb')):
            with self.subTest(file=path.name):
                raw = path.read_bytes()
                def mutate(files):
                    path.write_bytes(raw+b' '); original(files)
                with patch.object(self.sources, '_finish', side_effect=mutate):
                    self.expect('LEGACY_SOURCE_CHANGED', self.check)
                path.write_bytes(raw)

    def test_symlink_private_artifact_and_fixed_source_are_rejected(self):
        path = self.fixed_root/'model.glb'; saved = path.with_suffix('.saved'); path.rename(saved); path.symlink_to(saved)
        self.expect('LEGACY_SOURCE_CHANGED', self.sources.inventory)

    def test_absent_fixed_model_has_no_guessed_uploaded_default(self):
        self.expect('LEGACY_REGISTRY_UNAVAILABLE', lambda: LegacySceneSources(self.fixture.library, None, self.reader))

    def test_source_probing_uses_existing_bounded_slot_and_failure_always_releases_it(self):
        library = self.fixture.library
        self.assertTrue(library.slots.acquire(blocking=False))
        try: self.expect('MODEL_BUSY', self.check)
        finally: library.slots.release()
        with patch.object(library, 'process', side_effect=PreviewError(422, 'INVALID_MODEL')):
            self.expect('INVALID_MODEL', self.check)
        self.assertTrue(library.slots.acquire(blocking=False)); library.slots.release()
        self.check()

    def test_multiple_identical_uploads_require_explicit_preserved_source_not_latest(self):
        f = self.fixture
        # A second catalogue with the same geometry is still a separate source.
        original = registry.glb
        def depth_glb(path):
            original(path); raw = path.read_bytes(); path.write_bytes(raw[:-4]+struct.pack('<f', 1)); return path
        with patch.object(registry, 'glb', side_effect=depth_glb): legacy, model = f.new_model()
        scene = f.new_scene(model)
        f.body['sources'].append({'sourceKind': 'uploaded_version', 'sourceKey': legacy['versionId'],
            'expectedSourceDigest': 'a'*64, 'sceneId': scene['sceneId'], 'expectedSceneRevision': scene['sceneRevision'],
            'sceneModelInstanceId': scene['snapshot']['instances'][0]['sceneModelInstanceId']})
        self.reload(); self.check()  # Explicit preservation lineage chooses the original fixed candidate.
        verified = f.models.calibrate({'modelVersionId': f.model['modelVersionId'],
            'expectedContentRevision': f.model['contentRevision'], 'expectedLibraryRevision': f.library.listing()['libraryRevision'],
            'clientRequestId': str(registry.uuid4()), 'calibration': {'unit': 'm', 'axes': 'Y_UP_RIGHT_HANDED',
            'basePoint': [0, 0, 0], 'forward': [0, 0, -1]}}, 'synthetic-admin', f.authorize)
        target = f.new_scene(verified)
        f.body['sources'][0].update(sceneId=target['sceneId'], expectedSceneRevision=target['sceneRevision'],
            sceneModelInstanceId=target['snapshot']['instances'][0]['sceneModelInstanceId'])
        self.reload(); self.expect('LEGACY_SOURCE_NOT_MIGRATABLE', self.check)


if __name__ == '__main__': unittest.main()
