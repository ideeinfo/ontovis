"""Scene checks against synthetic current-user OntoBase wire responses.

No real account, database, engineering writes or model material is used.
"""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.scene_bindings import root_change_reviews
from apps.api.scene_engineering import SceneEngineeringReader
from apps.api.scene_engineering_validation import SceneEngineeringValidator
from tests import test_scene_engineering as fixture
from tests import test_scene_library as storage_fixture


INSTANCE = '00000000-0000-0000-0000-000000000001'
SECOND = '00000000-0000-0000-0000-000000000002'
VERSION = '00000000-0000-0000-0000-000000000011'
NEW_VERSION = '00000000-0000-0000-0000-000000000012'
REVISION = 'scene:synthetic:7'
SCOPE = {'connection_id': fixture.CONNECTION, 'project_code': fixture.PROJECT}


def ref(uid):
    return {'ontobaseConnectionId': fixture.CONNECTION, 'projectCode': fixture.PROJECT, 'entityUid': uid}


def instance(identifier=INSTANCE, root=fixture.ROOT, child=fixture.CHILD, version=VERSION):
    return {'sceneModelInstanceId': identifier, 'modelVersionId': version,
        'rootBinding': {'objectRef': ref(root)} if root else None,
        'componentBindings': [{'objectRef': ref(child), 'componentKeys': ['signal']} ] if child else []}


def snapshot(*instances):
    return {'instances': list(instances)}


class SceneEngineeringValidationTests(unittest.TestCase):
    def setUp(self):
        self.authority = fixture.SyntheticAuthority()
        self.reader = SceneEngineeringReader(self.authority, fixture.CONNECTION, fixture.PROJECT, self.authority.guard)
        self.catalog_calls = []
        self.catalogs = {VERSION: [{'componentKey': 'signal', 'bounds': [[0, 0, 0], [1, 1, 1]], 'geometryQuality': 'model'}],
                         NEW_VERSION: [{'componentKey': 'signal'}]}
        def components(version):
            self.authority.guard()
            self.catalog_calls.append(version)
            return copy.deepcopy(self.catalogs[version])
        self.validator = SceneEngineeringValidator(self.reader, components, fixture.CONNECTION, fixture.PROJECT)
        self.original = snapshot(instance())
        self.validation = self.facts(self.original)
        self.authority.calls.clear()

    def test_shared_configuration_requires_component_edits_at_project_level(self):
        self.validator.shared_configuration=lambda uid:{'configurationId':'00000000-0000-4000-8000-000000000001','configurationRevision':'equipment-config:1','snapshot':{'models':[{'modelVersionId':VERSION}]}}
        changed=copy.deepcopy(self.original);changed['instances'][0]['componentBindings']=[]
        self.expect('SHARED_CONFIGURATION_REQUIRED',lambda:self.run_check(changed),409)

    def test_new_root_cannot_adopt_a_model_outside_its_shared_configuration(self):
        self.validator.shared_configuration=lambda uid:{'configurationId':'00000000-0000-4000-8000-000000000001','configurationRevision':'equipment-config:1','snapshot':{'models':[{'modelVersionId':NEW_VERSION}]}}
        old=copy.deepcopy(self.original);old['instances']=[]
        current=copy.deepcopy(self.original);current['instances'][0]['componentBindings']=[]
        self.expect('MODEL_MAPPING_REQUIRED',lambda:self.run_check(current,old=old,validation={'engineeringExpectations':[],'bindingIssues':[]}),409)

    def facts(self, scene):
        refs = {}
        for item in scene['instances']:
            if item['rootBinding']: refs[item['rootBinding']['objectRef']['entityUid']] = True
            refs.update({binding['objectRef']['entityUid']: True for binding in item['componentBindings']})
        return {'engineeringExpectations': [self.reader.context_for_object(uid)['expectation'] for uid in sorted(refs)],
                'bindingIssues': []}

    def run_check(self, scene=None, *, old=None, validation=None, reviewed=None, changes=None, mode='check'):
        return self.validator(scene if scene is not None else self.original, reviewed or [], changes or [],
            previous_snapshot=old if old is not None else self.original, previous_revision=REVISION,
            previous_validation=validation if validation is not None else self.validation, mode=mode)

    def expect(self, code, callback, status=None):
        with self.assertRaises(PreviewError) as caught: callback()
        self.assertEqual(caught.exception.code, code)
        if status is not None: self.assertEqual(caught.exception.status, status)

    def save(self, scene=None, **options):
        proposed = scene if scene is not None else self.original
        review = options.pop('reviewed', self.facts(proposed)['engineeringExpectations'])
        return self.run_check(proposed, reviewed=review, mode='save', **options)

    def test_unbound_scenes_do_not_read_models_or_engineering(self):
        scene = snapshot(instance(root=None, child=None))
        value = self.run_check(scene, old=scene, validation={})
        self.assertEqual(value, {key: [] for key in ('engineeringExpectations', 'bindingIssues', 'rootBindingChanges', 'rootBindingImpact')})
        self.assertEqual(self.authority.calls, []); self.assertEqual(self.catalog_calls, [])

    def test_current_explicit_review_is_required_and_demo_not_promoted(self):
        self.expect('ENGINEERING_CHANGED', lambda: self.run_check(mode='save'), 409)
        value = self.save()
        self.assertEqual(value['bindingIssues'], [])
        self.assertEqual(len(value['engineeringExpectations']), 2)
        self.assertEqual(set(value), {'engineeringExpectations', 'bindingIssues', 'rootBindingChanges', 'rootBindingImpact'})
        self.assertNotIn('engineeringUseAllowed', repr(value))
        self.assertFalse(self.authority.contexts[fixture.CTX]['engineeringUseAllowed'])

    def test_same_model_two_installations_keep_independent_objects_and_one_directory(self):
        second_child = 'synthetic-device-B'
        self.authority.objects[second_child] = self.authority.object(second_child, fixture.OTHER_CTX)
        self.authority.parents[second_child] = fixture.OTHER_ROOT
        self.authority.relations[second_child, fixture.OTHER_ROOT] = self.authority.relation(second_child, fixture.OTHER_ROOT)
        scene = snapshot(instance(), instance(SECOND, fixture.OTHER_ROOT, second_child))
        baseline = self.facts(scene)
        value = self.run_check(scene, old=scene, validation=baseline,
            reviewed=baseline['engineeringExpectations'], mode='save')
        self.assertEqual(value['bindingIssues'], [])
        self.assertEqual(len(value['engineeringExpectations']), 4)
        self.assertEqual(self.catalog_calls, [VERSION])
        self.assertEqual({item['installationContextId'] for item in value['engineeringExpectations']}, {fixture.CTX, fixture.OTHER_CTX})

    def test_root_need_not_be_turbine_or_context_root(self):
        self.authority.objects[fixture.CABINET]['objectKind'] = 'control_cabinet'
        scene = snapshot(instance(root=fixture.CABINET))
        value = self.run_check(scene, old=scene, validation=self.facts(scene),
            reviewed=self.facts(scene)['engineeringExpectations'], mode='save')
        self.assertEqual(value['bindingIssues'], [])

    def test_self_object_can_have_component_representation(self):
        scene = snapshot(instance(root=fixture.CABINET, child=fixture.CABINET))
        self.assertEqual(self.run_check(scene, old=scene, validation=self.facts(scene))['bindingIssues'], [])

    def test_definition_and_unclassified_cannot_be_new_bindings(self):
        empty = snapshot(instance(root=None, child=None))
        for uid in ('definition', 'unclassified'):
            with self.subTest(uid=uid):
                self.expect('ENGINEERING_CHANGED', lambda: self.run_check(snapshot(instance(root=uid, child=None)), old=empty, validation={}), 409)

    def test_same_context_sibling_outside_selected_root_is_rejected(self):
        sibling = 'synthetic-sibling'
        self.authority.objects[sibling] = self.authority.object(sibling, fixture.CTX)
        self.authority.parents[sibling] = fixture.ROOT
        self.authority.relations[sibling, fixture.ROOT] = self.authority.relation(sibling, fixture.ROOT)
        old = snapshot(instance(root=fixture.CABINET, child=None))
        scene = snapshot(instance(root=fixture.CABINET, child=sibling))
        self.expect('ENGINEERING_CHANGED', lambda: self.run_check(scene, old=old, validation=self.facts(old)), 409)

    def test_other_installation_component_is_rejected(self):
        scene = snapshot(instance(child=fixture.OTHER_ROOT))
        self.expect('ENGINEERING_CHANGED', lambda: self.run_check(scene, old=snapshot(instance(child=None))), 409)

    def test_cross_project_ref_rejected_before_source_read(self):
        scene = copy.deepcopy(self.original)
        scene['instances'][0]['rootBinding']['objectRef']['projectCode'] = 'another-project'
        self.expect('NOT_FOUND_OR_FORBIDDEN', lambda: self.run_check(scene), 404)
        self.assertEqual(self.authority.calls, [])

    def test_model_keys_must_exist_and_actual_catalog_must_be_unique(self):
        self.catalogs[VERSION] = [{'componentKey': 'other'}]
        self.expect('RESOURCE_CHANGED', self.run_check, 409)
        self.catalogs[VERSION] = [{'componentKey': 'signal'}, {'componentKey': 'signal'}]
        self.expect('RESOURCE_CHANGED', self.run_check, 409)

    def test_object_change_open_blocks_and_save_needs_new_explicit_review(self):
        self.authority.objects[fixture.CHILD]['entityRevision'] += '-new'
        value = self.run_check(mode='open')
        issue = value['bindingIssues'][0]
        self.assertEqual(issue['code'], 'ENTITY_CHANGED')
        self.assertEqual(issue['expectedEntityRevision'], self.validation['engineeringExpectations'][0]['expectedEntityRevision'])
        self.expect('ENGINEERING_CHANGED', lambda: self.save(reviewed=self.validation['engineeringExpectations']), 409)
        self.assertEqual(self.save()['bindingIssues'], [])

    def test_changed_hierarchy_is_not_accepted_by_preflight(self):
        self.authority.contexts[fixture.CTX]['hierarchyRevision'] = fixture.CTX + ':8'
        value = self.run_check()
        self.assertEqual({issue['code'] for issue in value['bindingIssues']}, {'PARENT_CHAIN_CHANGED'})
        self.assertEqual({item['expectedHierarchyRevision'] for item in value['engineeringExpectations']}, {fixture.CTX+':8'})
        self.expect('ENGINEERING_CHANGED', lambda: self.save(reviewed=self.validation['engineeringExpectations']), 409)
        self.assertEqual(self.save()['bindingIssues'], [])

    def test_moved_object_outside_root_blocks_until_legitimate_rebinding(self):
        old = snapshot(instance(root=fixture.CABINET))
        baseline = self.facts(old)
        self.authority.parents[fixture.CHILD] = fixture.ROOT
        self.authority.relations[fixture.CHILD, fixture.ROOT] = self.authority.relation(fixture.CHILD, fixture.ROOT)
        value = self.run_check(old, old=old, validation=baseline, mode='open')
        self.assertEqual(value['bindingIssues'][0]['code'], 'PARENT_CHAIN_CHANGED')
        self.expect('ENGINEERING_CHANGED', lambda: self.run_check(old, old=old, validation=baseline,
            reviewed=self.facts(old)['engineeringExpectations'], mode='save'), 409)

    def test_unknown_context_or_incomplete_chain_uses_only_persisted_basis(self):
        for case in ('context', 'chain'):
            with self.subTest(case=case):
                self.authority.missing_context = case == 'context'
                self.authority.parents = {fixture.CHILD: fixture.CABINET} if case == 'chain' else {fixture.CHILD: fixture.CABINET, fixture.CABINET: fixture.ROOT}
                value = self.run_check(mode='open')
                self.assertTrue(value['bindingIssues'])
                for issue in value['bindingIssues']:
                    self.assertEqual(issue['installationContextId'], fixture.CTX)
                    self.assertEqual(issue['expectedHierarchyRevision'], fixture.CTX+':7')
                self.assertFalse(any(item['ref']['entityUid'] == fixture.CHILD for item in value['engineeringExpectations']))

    def test_installation_becoming_definition_is_identity_issue_not_rebinding(self):
        self.authority.objects[fixture.CHILD].update(objectScope='definition', installationContextId=None, installationPurpose=None)
        value = self.run_check(mode='open')
        self.assertEqual(value['bindingIssues'][0]['code'], 'IDENTITY_CHANGED')
        self.expect('ENGINEERING_CHANGED', lambda: self.save(reviewed=self.validation['engineeringExpectations']), 409)

    def test_missing_old_expectations_blocks_open_and_explicit_review_can_repair(self):
        self.expect('ENGINEERING_CHANGED', lambda: self.run_check(validation={}, mode='open'), 409)
        self.assertEqual(self.save(validation={})['bindingIssues'], [])

    def test_ordinary_component_removal_still_requires_removed_object_review(self):
        scene = snapshot(instance(child=None))
        root_only = self.facts(scene)['engineeringExpectations']
        self.expect('ENGINEERING_CHANGED', lambda: self.save(scene, reviewed=root_only), 409)
        value = self.save(scene, reviewed=self.validation['engineeringExpectations'])
        self.assertEqual(len(value['engineeringExpectations']), 2)

    def test_root_switch_returns_impact_and_requires_exact_digest_then_clears_old(self):
        scene = snapshot(instance(root=fixture.OTHER_ROOT, child=None))
        value = self.run_check(scene)
        self.assertEqual(len(value['rootBindingImpact'][0]['removedBindings']), 1)
        self.assertNotIn('removedBindings', value['rootBindingChanges'][0])
        reviewed = value['engineeringExpectations']
        self.expect('ENGINEERING_CHANGED', lambda: self.save(scene, reviewed=reviewed), 409)
        changed = copy.deepcopy(value['rootBindingChanges']); changed[0]['reviewedRemovedBindingsDigest'] = '0'*64
        self.expect('ENGINEERING_CHANGED', lambda: self.save(scene, reviewed=reviewed, changes=changed), 409)
        self.assertEqual(self.save(scene, reviewed=reviewed, changes=value['rootBindingChanges'])['bindingIssues'], [])

    def test_root_switch_cannot_sneak_old_component_associations_into_new_root(self):
        scene = snapshot(instance(root=fixture.OTHER_ROOT))
        self.expect('ENGINEERING_CHANGED', lambda: self.run_check(scene), 409)

    def test_model_replacement_generates_persistent_issue_and_only_explicit_save_rebind_resolves(self):
        scene = snapshot(instance(child=None, version=NEW_VERSION))
        value = self.run_check(scene, mode='replacement')
        self.assertEqual(value['bindingIssues'][0]['kind'], 'model_version_changed')
        self.assertEqual(value['bindingIssues'][0]['code'], 'MIGRATION_REQUIRED')
        persisted = {'engineeringExpectations': value['engineeringExpectations'], 'bindingIssues': value['bindingIssues']}
        rebound = snapshot(instance(version=NEW_VERSION))
        preflight = self.run_check(rebound, old=scene, validation=persisted)
        self.assertEqual(len(preflight['bindingIssues']), 1)
        result = self.run_check(rebound, old=scene, validation=persisted,
            reviewed=preflight['engineeringExpectations'], mode='save')
        self.assertEqual(result['bindingIssues'], [])

    def test_model_proof_cannot_clear_unresolved_engineering_issue_without_valid_association(self):
        self.authority.objects[fixture.CHILD]['entityRevision'] += '-new'
        changed = self.run_check(mode='open')
        persisted = {key: changed[key] for key in ('engineeringExpectations', 'bindingIssues')}
        removed = snapshot(instance(child=None))
        current = self.facts(self.original)['engineeringExpectations']
        result = self.run_check(removed, validation=persisted, reviewed=current, mode='save')
        self.assertEqual(result['bindingIssues'][0]['kind'], 'engineering_changed')
        self.assertEqual(result['bindingIssues'][0]['code'], 'ENTITY_CHANGED')

    def test_review_extra_duplicate_or_stale_context_cannot_authorize_save(self):
        values = self.validation['engineeringExpectations']
        self.expect('ENGINEERING_CHANGED', lambda: self.save(reviewed=values + [self.reader.context_for_object(fixture.OTHER_ROOT)['expectation']]), 409)
        self.expect('INVALID_REQUEST', lambda: self.save(reviewed=values + [values[0]]), 422)
        stale = copy.deepcopy(values); stale[0]['installationContextId'] = fixture.OTHER_CTX
        self.expect('ENGINEERING_CHANGED', lambda: self.save(reviewed=stale), 409)

    def test_disappeared_nonexact_and_revoked_objects_refuse_entire_open(self):
        self.authority.objects.pop(fixture.CHILD)
        self.expect('NOT_FOUND_OR_FORBIDDEN', lambda: self.run_check(mode='open'), 404)
        self.authority.objects[fixture.CHILD] = self.authority.object(fixture.CHILD, fixture.CTX)
        self.authority.resolution = 'merged'
        self.expect('IDENTITY_CHANGED', lambda: self.run_check(mode='open'), 409)
        self.authority.resolution = 'exact'; self.authority.allowed = False
        self.expect('FORBIDDEN', lambda: self.run_check(mode='open'), 403)

    def test_permission_revoked_during_source_read_is_not_a_partial_success(self):
        def revoke(source, method, path, body):
            if '/ancestors?' in path: source.allowed = False
        self.authority.after = revoke
        self.expect('FORBIDDEN', self.run_check, 403)
        self.assertEqual(self.catalog_calls, [])

    def test_mixed_context_revision_between_individual_reads_is_rejected(self):
        original = self.reader.context_for_object
        count = 0
        def read(uid):
            nonlocal count
            value = original(uid); count += 1
            if count == 1: self.authority.contexts[fixture.CTX]['hierarchyRevision'] = fixture.CTX+':8'
            return value
        self.reader.context_for_object = read
        self.expect('ENGINEERING_CHANGED', self.run_check, 409)

    def storage(self):
        # Real private SQLite/file store and parsed synthetic GLB. Resource
        # calibration/authorization is a separate service callback boundary.
        from apps.api.model_library import ModelLibrary
        from apps.api.model_validation import validate
        from apps.api.scene_library import SceneLibrary
        from tests.test_model_upload import glb
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        models = ModelLibrary(root/'models', fixture.PROJECT, str(uuid4()))
        source = glb(root/'synthetic.glb')
        model = models.save_upload(source, {'expectedSessionRevision': 'synthetic-session:1',
            'expectedLibraryRevision': models.listing()['libraryRevision'], 'clientRequestId': str(uuid4()),
            'displayName': 'Synthetic geometry', 'sourceNote': 'Synthetic test only', 'rightsDeclared': True},
            'synthetic-admin', validate(source), self.authority.guard)
        scenes = SceneLibrary(models)
        def resources(scene):
            for item in scene['instances']: models.version(item['modelVersionId'])
        def old_gate(scene, reviewed, changes):
            self.assertEqual(reviewed, []); self.assertEqual(changes, [])
        checker = SceneEngineeringValidator(self.reader, lambda version: models.version(version)['components'],
            fixture.CONNECTION, fixture.PROJECT)
        scene = scenes.create({'displayName': '合成对象场景', 'clientRequestId': str(uuid4())},
            'synthetic-admin', self.authority.guard, resources, old_gate)
        item = storage_fixture.SceneLibraryTests.item
        # The fixture helper expects only its current model identity.
        holder = type('SyntheticModelHolder', (), {'model': model})()
        proposed = copy.deepcopy(scene['snapshot']); proposed['instances'] = [item(holder, INSTANCE)]
        proposed['instances'][0]['rootBinding'] = {'objectRef': ref(fixture.ROOT)}
        def check(current, candidate, callback=checker):
            return scenes.check({'kind': 'validate', 'sceneId': current['sceneId'],
                'expectedSceneRevision': current['sceneRevision'], 'snapshot': candidate},
                'synthetic-admin', self.authority.guard, resources, old_gate,
                access_revision='synthetic-grant:1', engineering_check=callback)
        def body(current, checked):
            return {'sceneId': current['sceneId'], 'expectedSceneRevision': current['sceneRevision'],
                'clientRequestId': str(uuid4()), 'snapshot': checked['proposedSnapshot'],
                'reviewedEngineering': checked['reviewedEngineering'], 'rootBindingChanges': checked['rootBindingChanges']}
        def save(request, callback=checker):
            return scenes.save(request, 'synthetic-admin', self.authority.guard, resources, old_gate,
                access_revision='synthetic-grant:1', engineering_check=callback)
        def opened(revision=None):
            return scenes.open(scene['sceneId'], 'synthetic-admin', self.authority.guard, revision, engineering_check=checker)
        save(body(scene, check(scene, proposed))); scene = opened()
        proposed = copy.deepcopy(scene['snapshot'])
        proposed['instances'][0]['componentBindings'] = [{'objectRef': ref(fixture.CHILD),
            'componentKeys': [model['components'][0]['componentKey']]}]
        save(body(scene, check(scene, proposed)))
        return models, scenes, opened(), check, body, save, opened, checker

    def test_real_sqlite_persists_expectations_and_open_drift_does_not_rewrite_history(self):
        models, scenes, scene, check, body, save, opened, checker = self.storage()
        old_revision = scene['sceneRevision']
        with models.connect() as db:
            before = db.execute('select validation from scene_spatial_validations where revision=?', (old_revision,)).fetchone()[0]
            counts = tuple(db.execute('select (select count(*) from scene_revisions),(select count(*) from scene_audit)').fetchone())
        self.assertEqual(len(json.loads(before)['engineeringExpectations']), 2)
        self.authority.objects[fixture.CHILD]['entityRevision'] += '-new'
        dynamic = opened(old_revision)
        self.assertEqual(dynamic['snapshot'], scene['snapshot'])
        self.assertEqual(dynamic['validation']['bindingIssues'][0]['code'], 'ENTITY_CHANGED')
        with models.connect() as db:
            self.assertEqual(db.execute('select validation from scene_spatial_validations where revision=?', (old_revision,)).fetchone()[0], before)
            self.assertEqual(tuple(db.execute('select (select count(*) from scene_revisions),(select count(*) from scene_audit)').fetchone()), counts)
        candidate = check(scene, scene['snapshot'])
        self.assertTrue(candidate['validation']['bindingIssues'])
        save(body(scene, candidate))
        self.assertEqual(opened()['validation']['bindingIssues'], [])
        self.assertTrue(opened(old_revision)['validation']['bindingIssues'])

    def test_real_sqlite_final_current_authority_check_rolls_back_without_audit(self):
        models, scenes, scene, check, body, save, opened, checker = self.storage()
        request = body(scene, check(scene, scene['snapshot']))
        with models.connect() as db:
            before = tuple(db.execute('select (select count(*) from scene_revisions),(select count(*) from scene_audit),(select count(*) from scene_requests)').fetchone())
        calls = 0
        def revoke_on_final(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2: self.authority.allowed = False
            return checker(*args, **kwargs)
        self.expect('FORBIDDEN', lambda: save(request, revoke_on_final), 403)
        self.assertEqual(calls, 2)
        with models.connect() as db:
            self.assertEqual(tuple(db.execute('select (select count(*) from scene_revisions),(select count(*) from scene_audit),(select count(*) from scene_requests)').fetchone()), before)


if __name__ == '__main__': unittest.main()
