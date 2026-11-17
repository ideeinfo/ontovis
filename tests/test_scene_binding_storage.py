"""Real SQLite binding storage with explicit synthetic engineering authority proofs.

No OntoBase reads or measured geometry are implied by this fixture. Authority
reader, geometry and HTTP permissions have independent integration suites.
"""
import copy
import json
import unittest
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.scene_bindings import (VerifiedBinding, derive_binding_issues, required_engineering_refs,
    root_change_reviews, validate_expectations, validate_root_changes)
from apps.api.scene_library import SceneLibrary, validate_local_snapshot
from tests import test_scene_replacement as replacement_fixture


class SceneBindingStorageTests(unittest.TestCase):
    def setUp(self):
        self.r = replacement_fixture.SceneReplacementTests('test_model_preview_cancel_is_read_only_and_save_retains_old_identity_and_references')
        self.r.setUp(); self.addCleanup(self.r.doCleanups)
        self.f = self.r.f
        self.scope = {'connection_id': 'synthetic-connection', 'project_code': self.f.scenes.project_code}
        self.entity_revision, self.hierarchy_revision = 'entity:1', 'hierarchy:1'
        self.calls, self.on_check = [], None

    def ref(self, uid):
        return {'ontobaseConnectionId': self.scope['connection_id'], 'projectCode': self.scope['project_code'], 'entityUid': uid}

    def expectation(self, ref):
        return {'ref': ref, 'expectedEntityRevision': self.entity_revision,
                'installationContextId': 'ctx-' + ref['entityUid'].split('-')[-1],
                'expectedHierarchyRevision': self.hierarchy_revision}

    def checker(self, snapshot, reviewed, changes, *, previous_snapshot, previous_revision, previous_validation, mode):
        self.calls.append((mode, copy.deepcopy(reviewed), copy.deepcopy(previous_validation)))
        if self.on_check is not None: self.on_check(mode)
        impact = root_change_reviews(previous_snapshot, previous_revision, snapshot, **self.scope)
        canonical = [{key: value for key, value in item.items() if key != 'removedBindings'} for item in impact]
        if mode == 'save':
            canonical = validate_root_changes(previous_snapshot, previous_revision, snapshot, changes, **self.scope)
        refs = required_engineering_refs(snapshot, previous_snapshot=previous_snapshot,
            binding_issues=previous_validation.get('bindingIssues', []), root_changes=canonical, **self.scope)
        expected = [self.expectation(ref) for ref in refs]
        if mode == 'save':
            actual = validate_expectations(reviewed, required_refs=refs, **self.scope)
            if actual != expected: raise PreviewError(409, 'ENGINEERING_CHANGED')
        proofs = [VerifiedBinding(item['sceneModelInstanceId'], item['modelVersionId'], binding['objectRef'],
                     self.expectation(binding['objectRef'])['installationContextId'], tuple(sorted(binding['componentKeys'])),
                     self.entity_revision, self.hierarchy_revision)
                  for item in snapshot['instances'] for binding in item['componentBindings']]
        issues = derive_binding_issues(previous_snapshot, previous_revision, snapshot, previous_validation.get('bindingIssues', []),
            verified_bindings=proofs, verified_objects=expected, historical_expectations=previous_validation.get('engineeringExpectations', []),
            current_components={item['modelVersionId']: ['ct', 'cn'] for item in snapshot['instances']},
            root_changes=canonical, **self.scope)
        return {'engineeringExpectations': expected, 'bindingIssues': issues,
                'rootBindingChanges': canonical, 'rootBindingImpact': impact}

    def open(self, scene, revision=None, checker=None):
        return self.f.scenes.open(scene['sceneId'], 'admin', self.f.authorize, revision,
                                  engineering_check=checker or self.checker)

    def check(self, scene, snapshot, checker=None):
        return self.f.scenes.check({'kind': 'validate', 'sceneId': scene['sceneId'],
            'expectedSceneRevision': scene['sceneRevision'], 'snapshot': snapshot},
            'admin', self.f.authorize, self.r.resources, self.f.engineering,
            access_revision=self.f.grant, engineering_check=checker or self.checker)

    def request(self, scene, snapshot):
        preview = self.check(scene, snapshot)
        body = self.f.body(scene, preview['proposedSnapshot'])
        body['reviewedEngineering'] = preview['reviewedEngineering']
        body['rootBindingChanges'] = preview['rootBindingChanges']
        return body

    def save(self, body, *, checker=None, authorize=None):
        return self.f.scenes.save(body, 'admin', authorize or self.f.authorize, self.r.resources,
            self.f.engineering, validate_geometry=self.r.geometry, access_revision=self.f.grant,
            terrain_replacement=self.r.terrain_preview, model_details=self.r.model_details,
            engineering_check=checker or self.checker)

    def bound_scene(self, count=1, *, locked=False):
        scene = self.f.create(); snapshot = copy.deepcopy(scene['snapshot'])
        snapshot['instances'] = [self.f.item(locked=locked) for _ in range(count)]
        for index, item in enumerate(snapshot['instances']):
            item['rootBinding'] = {'objectRef': self.ref('root-' + chr(65 + index))}
        self.save(self.request(scene, snapshot)); scene = self.open(scene)
        snapshot = copy.deepcopy(scene['snapshot'])
        for index, item in enumerate(snapshot['instances']):
            item['componentBindings'] = [{'objectRef': self.ref('CT-' + chr(65 + index)), 'componentKeys': ['ct']}]
        self.save(self.request(scene, snapshot))
        return self.open(scene)

    def expect(self, code, operation):
        with self.assertRaises(PreviewError) as caught: operation()
        self.assertEqual(caught.exception.code, code)

    def stored_validation(self, revision):
        with self.f.models.connect() as db:
            return json.loads(db.execute('select validation from scene_spatial_validations where revision=?', (revision,)).fetchone()[0])

    def test_two_instances_same_component_key_have_independent_refs_and_retained_snapshots(self):
        scene = self.bound_scene(2)
        self.assertEqual(scene['validation']['scope'], 'local_plane_bound')
        self.assertEqual([item['componentBindings'][0]['objectRef']['entityUid'] for item in scene['snapshot']['instances']], ['CT-A', 'CT-B'])
        self.assertEqual(len(self.stored_validation(scene['sceneRevision'])['engineeringExpectations']), 4)
        body = self.request(scene, scene['snapshot']); self.save(body)
        self.assertEqual(self.open(scene, scene['sceneRevision'])['snapshot'], scene['snapshot'])

    def test_no_checker_retains_unbound_gate_and_caps_are_explicit(self):
        scene = self.bound_scene()
        self.expect('SCENE_SCOPE_UNSUPPORTED', lambda: self.f.scenes.open(scene['sceneId'], 'admin', self.f.authorize))
        self.expect('SCENE_SCOPE_UNSUPPORTED', lambda: self.f.save(self.f.body(scene)))
        self.assertFalse(SceneLibrary.capabilities()['supportsEngineeringBindings'])
        self.assertEqual(SceneLibrary.capabilities(engineering=True)['storageScope'], 'project_scenes')

    def test_root_change_preview_is_readonly_and_requires_exact_reviewed_removal(self):
        scene = self.bound_scene(); before = self.f.counts()
        snapshot = copy.deepcopy(scene['snapshot']); item = snapshot['instances'][0]
        item['rootBinding'] = {'objectRef': self.ref('root-B')}; item['componentBindings'] = []
        body = self.request(scene, snapshot)
        preview = self.check(scene, snapshot)
        self.assertEqual(preview['rootBindingImpact'][0]['removedBindings'], scene['snapshot']['instances'][0]['componentBindings'])
        self.assertEqual(self.f.counts(), before)
        bad = copy.deepcopy(body); bad['rootBindingChanges'] = []
        self.expect('ENGINEERING_CHANGED', lambda: self.save(bad))
        bad = copy.deepcopy(body); bad['rootBindingChanges'][0]['reviewedRemovedBindingsDigest'] = '0'*64
        self.expect('ENGINEERING_CHANGED', lambda: self.save(bad))
        self.save(body); self.assertEqual(self.open(scene)['snapshot'], snapshot)

    def test_position_lock_allows_association_changes_but_still_rejects_movement(self):
        scene = self.bound_scene(locked=True)
        snapshot = copy.deepcopy(scene['snapshot']); snapshot['instances'][0]['componentBindings'] = []
        self.save(self.request(scene, snapshot)); scene = self.open(scene)
        moved = copy.deepcopy(scene['snapshot']); moved['instances'][0]['placement']['position']['xM'] += 1
        self.expect('INSTANCE_POSITION_LOCKED', lambda: self.check(scene, moved))

    def test_save_uses_original_reviewed_revisions_and_does_not_accept_new_preflight_facts(self):
        scene = self.bound_scene(); body = self.request(scene, scene['snapshot']); before = self.f.counts()
        self.entity_revision = 'entity:2'
        self.assertEqual(self.check(scene, scene['snapshot'])['reviewedEngineering'][0]['expectedEntityRevision'], 'entity:2')
        self.expect('ENGINEERING_CHANGED', lambda: self.save(body))
        self.assertEqual(self.f.counts(), before)

    def test_removing_internal_binding_still_requires_review_of_removed_object(self):
        scene = self.bound_scene(); snapshot = copy.deepcopy(scene['snapshot'])
        snapshot['instances'][0]['componentBindings'] = []
        body = self.request(scene, snapshot)
        self.assertEqual({item['ref']['entityUid'] for item in body['reviewedEngineering']}, {'root-A', 'CT-A'})
        body['reviewedEngineering'] = [item for item in body['reviewedEngineering'] if item['ref']['entityUid'] != 'CT-A']
        self.expect('ENGINEERING_CHANGED', lambda: self.save(body))

    def test_final_engineering_revision_change_rolls_back_revision_uses_and_idempotency(self):
        scene = self.bound_scene(); body = self.request(scene, scene['snapshot']); before = self.f.counts(); saves = []
        def change(mode):
            if mode == 'save':
                saves.append(True)
                if len(saves) == 2: self.hierarchy_revision = 'hierarchy:2'
        self.on_check = change
        self.expect('ENGINEERING_CHANGED', lambda: self.save(body))
        self.assertEqual(self.f.counts(), before)

    def test_final_logout_rolls_back_all_new_scene_state(self):
        scene = self.bound_scene(); body = self.request(scene, scene['snapshot']); before = self.f.counts(); calls = []
        def logout():
            calls.append(True)
            if len(calls) == 2: raise PreviewError(401, 'SESSION_REQUIRED')
        self.expect('SESSION_REQUIRED', lambda: self.save(body, authorize=logout))
        self.assertEqual(self.f.counts(), before)

    def test_open_revalidates_dynamically_without_mutating_saved_facts_or_history(self):
        scene = self.bound_scene(); saved = self.stored_validation(scene['sceneRevision'])
        self.entity_revision = 'entity:2'
        opened = self.open(scene)
        self.assertEqual(opened['reviewedEngineering'][0]['expectedEntityRevision'], 'entity:2')
        self.assertEqual(self.stored_validation(scene['sceneRevision']), saved)
        self.assertEqual(opened['snapshot'], scene['snapshot'])

    def test_unknown_instance_in_server_result_is_rejected_before_save(self):
        scene = self.bound_scene(); before = self.f.counts(); body = self.request(scene, scene['snapshot'])
        def invalid(*args, **kwargs):
            facts = self.checker(*args, **kwargs)
            facts['bindingIssues'] = [{'sceneModelInstanceId': str(uuid4()), 'objectRef': self.ref('CT-A'), 'blocking': True}]
            return facts
        self.expect('INVALID_ENGINEERING_RESULT', lambda: self.save(body, checker=invalid))
        self.assertEqual(self.f.counts(), before)

    def test_client_cannot_write_validation_or_server_expectations(self):
        scene = self.bound_scene(); body = self.request(scene, scene['snapshot'])
        body['snapshot']['engineeringExpectations'] = []
        self.expect('INVALID_REQUEST', lambda: self.save(body))
        body = self.request(scene, scene['snapshot']); body['validation'] = {'bindingIssues': []}
        self.expect('INVALID_REQUEST', lambda: self.save(body))

    def test_model_replacement_clears_internal_bindings_and_keeps_root_and_blocking_issue(self):
        scene = self.bound_scene(); before = self.f.counts()
        checked = self.f.scenes.replacement_check(self.r.check_body(scene), 'admin', self.f.authorize,
            self.r.resources, self.f.engineering, self.r.geometry, self.r.terrain_preview,
            self.r.model_details, access_revision=self.f.grant, engineering_check=self.checker)
        self.assertEqual(self.f.counts(), before)
        item = checked['proposedSnapshot']['instances'][0]
        self.assertEqual(item['rootBinding'], scene['snapshot']['instances'][0]['rootBinding'])
        self.assertEqual(item['componentBindings'], [])
        self.assertEqual(checked['validation']['bindingIssues'][0]['objectRef'], self.ref('CT-A'))
        body = self.f.body(scene, checked['proposedSnapshot'])
        body.update(spatialChange=checked['spatialChange'], reviewedEngineering=checked['reviewedEngineering'], rootBindingChanges=checked['rootBindingChanges'])
        self.save(body); current = self.open(scene)
        self.assertEqual(len(current['validation']['bindingIssues']), 1)
        self.save(self.request(current, current['snapshot']))
        self.assertEqual(len(self.open(scene)['validation']['bindingIssues']), 1)
        self.assertTrue(self.open(scene, scene['sceneRevision'])['snapshot']['instances'][0]['componentBindings'])

    def test_explicit_current_binding_can_resolve_only_its_own_issue(self):
        scene = self.bound_scene()
        checked = self.f.scenes.replacement_check(self.r.check_body(scene), 'admin', self.f.authorize,
            self.r.resources, self.f.engineering, self.r.geometry, self.r.terrain_preview,
            self.r.model_details, access_revision=self.f.grant, engineering_check=self.checker)
        body = self.f.body(scene, checked['proposedSnapshot'])
        body.update(spatialChange=checked['spatialChange'], reviewedEngineering=checked['reviewedEngineering'], rootBindingChanges=[])
        self.save(body); current = self.open(scene)
        snapshot = copy.deepcopy(current['snapshot'])
        snapshot['instances'][0]['componentBindings'] = [{'objectRef': self.ref('CT-A'), 'componentKeys': ['ct']}]
        self.save(self.request(current, snapshot))
        self.assertEqual(self.open(scene)['validation']['bindingIssues'], [])

    def test_geographic_binding_save_and_model_replacement_keep_fixed_geometry(self):
        scene = self.r.geographic(); snapshot = copy.deepcopy(scene['snapshot'])
        snapshot['instances'][0]['rootBinding'] = {'objectRef': self.ref('root-A')}
        preview = self.f.scenes.check({'kind': 'validate', 'sceneId': scene['sceneId'],
            'expectedSceneRevision': scene['sceneRevision'], 'snapshot': snapshot}, 'admin', self.f.authorize,
            self.r.resources, self.f.engineering, self.r.geometry, access_revision=self.f.grant, engineering_check=self.checker)
        body = self.f.body(scene, snapshot)
        body.update(reviewedEngineering=preview['reviewedEngineering'], rootBindingChanges=preview['rootBindingChanges'])
        self.save(body); scene = self.open(scene)
        self.assertEqual(scene['validation']['scope'], 'projected_site_bound')
        checked = self.f.scenes.replacement_check(self.r.check_body(scene), 'admin', self.f.authorize,
            self.r.resources, self.f.engineering, self.r.geometry, self.r.terrain_preview, self.r.model_details,
            access_revision=self.f.grant, engineering_check=self.checker)
        body = self.f.body(scene, checked['proposedSnapshot'])
        body.update(spatialChange=checked['spatialChange'], reviewedEngineering=checked['reviewedEngineering'], rootBindingChanges=[])
        self.save(body); opened = self.open(scene)
        self.assertEqual(opened['snapshot']['coordinateFrame'], scene['snapshot']['coordinateFrame'])
        self.assertEqual(opened['snapshot']['instances'][0]['placement'], scene['snapshot']['instances'][0]['placement'])
        self.assertEqual(opened['terrainRefs'], scene['terrainRefs'])

    def test_first_anchor_preserves_existing_bindings_and_signed_full_layout(self):
        scene = self.bound_scene()
        checked = self.f.scenes.check(self.f.check_body(scene), 'admin', self.f.authorize, self.r.resources,
            self.f.engineering, self.f.geometry, self.f.preview, access_revision=self.f.grant, engineering_check=self.checker)
        self.assertEqual(checked['proposedSnapshot']['instances'][0]['componentBindings'], scene['snapshot']['instances'][0]['componentBindings'])
        body = self.f.body(scene, checked['proposedSnapshot'])
        body.update(spatialChange=checked['spatialChange'], reviewedEngineering=checked['reviewedEngineering'], rootBindingChanges=[])
        self.save(body)
        self.assertEqual(self.open(scene)['validation']['scope'], 'projected_site_bound')

    def test_unknown_or_extra_server_facts_cannot_be_persisted(self):
        scene = self.bound_scene(); body = self.request(scene, scene['snapshot']); before = self.f.counts()
        def invalid(*args, **kwargs):
            result = self.checker(*args, **kwargs); result['published'] = True
            return result
        self.expect('INVALID_REQUEST', lambda: self.save(body, checker=invalid))
        self.assertEqual(self.f.counts(), before)

    def test_entire_scene_binding_and_component_key_budgets_are_not_per_instance_only(self):
        scene = self.f.create(); snapshot = copy.deepcopy(scene['snapshot'])
        snapshot['instances'] = [self.f.item(), self.f.item()]
        for item in snapshot['instances']:
            item['rootBinding'] = {'objectRef': self.ref('root-A')}
            item['componentBindings'] = [{'objectRef': self.ref('CT-A'), 'componentKeys': ['key-'+str(n) for n in range(501)]}]
        self.expect('SCENE_LIMIT_EXCEEDED', lambda: validate_local_snapshot(snapshot, engineering=True))
        for item in snapshot['instances']:
            item['componentBindings'] = [{'objectRef': self.ref('object-'+str(n)), 'componentKeys': ['key-'+str(n)]} for n in range(501)]
        self.expect('SCENE_LIMIT_EXCEEDED', lambda: validate_local_snapshot(snapshot, engineering=True))

    def test_successful_save_replays_exact_result_and_still_checks_current_session(self):
        scene = self.bound_scene(); body = self.request(scene, scene['snapshot'])
        first = self.save(body); counts = self.f.counts()
        self.assertEqual(self.save(body), first); self.assertEqual(self.f.counts(), counts)
        self.f.allowed = False
        self.expect('SCENE_WRITE_FORBIDDEN', lambda: self.save(body))
