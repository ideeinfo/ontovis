"""Pure binding declarations and explicit synthetic server proofs; no source IO."""
import copy
import unittest
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.scene_bindings import (
    MAX_COMPONENT_BINDINGS, VerifiedBinding, clear_model_replacement_bindings,
    derive_binding_issues, required_engineering_refs, root_change_reviews,
    validate_bindings, validate_expectations, validate_ref, validate_root_changes,
)

SCOPE = {'connection_id': 'synthetic-connection', 'project_code': 'synthetic-project'}


def ref(uid):
    return {'ontobaseConnectionId': SCOPE['connection_id'], 'projectCode': SCOPE['project_code'], 'entityUid': uid}


class SceneBindingTests(unittest.TestCase):
    def setUp(self):
        self.instance_id, self.other_id = str(uuid4()), str(uuid4())
        self.v1, self.v2, self.v3 = str(uuid4()), str(uuid4()), str(uuid4())
        self.root, self.new_root, self.ct, self.cn = ref('root-A'), ref('root-B'), ref('CT-A'), ref('CN-A')
        self.previous = {'instances': [self.instance()]}
        self.revision = 'scene:synthetic-previous'
        self.expectations = [self.expectation(value) for value in (self.root, self.new_root, self.ct, self.cn)]
        self.catalog = {self.v1: ['ct', 'cn'], self.v2: ['ct'], self.v3: ['cn']}

    def instance(self, identifier=None, version=None, root=None, bindings=None):
        return {'sceneModelInstanceId': identifier or self.instance_id, 'modelVersionId': version or self.v1,
                'rootBinding': {'objectRef': root or self.root}, 'componentBindings': bindings if bindings is not None else [
                    {'objectRef': self.ct, 'componentKeys': ['ct']}, {'objectRef': self.cn, 'componentKeys': ['cn']}]}

    def expectation(self, value, context='ctx-A', entity_revision='entity:1', hierarchy='hierarchy:1'):
        return {'ref': value, 'expectedEntityRevision': entity_revision,
                'installationContextId': context, 'expectedHierarchyRevision': hierarchy}

    def proof(self, value, keys, identifier=None, version=None, **changes):
        values = {'scene_model_instance_id': identifier or self.instance_id, 'model_version_id': version or self.v2,
                  'object_ref': value, 'installation_context_id': 'ctx-A', 'component_keys': tuple(keys),
                  'entity_revision': 'entity:1', 'hierarchy_revision': 'hierarchy:1'}
        return VerifiedBinding(**{**values, **changes})

    def replaced(self):
        snapshot = copy.deepcopy(self.previous)
        snapshot['instances'][0]['modelVersionId'] = self.v2
        return clear_model_replacement_bindings(self.previous, snapshot, **SCOPE)

    def derive(self, snapshot, previous=None, issues=(), proofs=(), objects=None, changes=()):
        return derive_binding_issues(previous or self.previous, self.revision, snapshot, list(issues),
            verified_bindings=proofs, verified_objects=self.expectations if objects is None else objects,
            current_components=self.catalog, root_changes=list(changes), **SCOPE)

    def root_changes(self, before, after):
        return [{key: value for key, value in review.items() if key != 'removedBindings'}
                for review in root_change_reviews(before, self.revision, after, **SCOPE)]

    def expect(self, code, action):
        with self.assertRaises(PreviewError) as caught: action()
        self.assertEqual(caught.exception.code, code)

    def test_refs_are_exact_scoped_bounded_and_do_not_accept_identity_claims(self):
        self.assertEqual(validate_ref(self.cn, **SCOPE), self.cn)
        for value in ({**self.cn, 'status': 'confirmed'}, {key: value for key, value in self.cn.items() if key != 'projectCode'},
                      {**self.cn, 'entityUid': True}, {**self.cn, 'entityUid': ' CN-A'}, {**self.cn, 'entityUid': 'x'*513},
                      {**self.cn, 'entityUid': '\ud800'}):
            self.expect('INVALID_REQUEST', lambda: validate_ref(value, **SCOPE))
        self.assertEqual(validate_ref(ref('x'*512), **SCOPE)['entityUid'], 'x'*512)
        self.expect('NOT_FOUND_OR_FORBIDDEN', lambda: validate_ref({**self.cn, 'projectCode': 'another-project'}, **SCOPE))
        self.expect('NOT_FOUND_OR_FORBIDDEN', lambda: validate_ref({**self.cn, 'ontobaseConnectionId': 'another-source'}, **SCOPE))

    def test_root_and_component_whitelists_require_root_and_unique_object_collection(self):
        valid = validate_bindings({'objectRef': self.root}, [{'objectRef': self.ct, 'componentKeys': ['ct.2', 'ct.1']}], **SCOPE)
        self.assertEqual(valid['componentBindings'][0]['componentKeys'], ['ct.1', 'ct.2'])
        self.expect('INVALID_REQUEST', lambda: validate_bindings(None, valid['componentBindings'], **SCOPE))
        self.expect('INVALID_REQUEST', lambda: validate_bindings({'objectRef': self.root, 'confirmed': True}, [], **SCOPE))
        for bindings in ([{'objectRef': self.ct, 'componentKeys': []}],
                         [{'objectRef': self.ct, 'componentKeys': ['ct', 'ct']}],
                         [{'objectRef': self.ct, 'componentKeys': ['ct']}, {'objectRef': self.ct, 'componentKeys': ['cn']}],
                         [{'objectRef': self.ct, 'componentKeys': ['ct']}, {'objectRef': self.cn, 'componentKeys': ['ct']}],
                         [{'objectRef': self.ct, 'componentKeys': ['ct'], 'verified': True}]):
            self.expect('INVALID_REQUEST', lambda: validate_bindings({'objectRef': self.root}, bindings, **SCOPE))

    def test_existing_1000_budget_applies_to_entries_and_total_component_keys(self):
        keys = ['key:'+str(index) for index in range(MAX_COMPONENT_BINDINGS)]
        validate_bindings({'objectRef': self.root}, [{'objectRef': self.ct, 'componentKeys': keys}], **SCOPE)
        self.expect('SCENE_LIMIT_EXCEEDED', lambda: validate_bindings({'objectRef': self.root}, [
            {'objectRef': self.ct, 'componentKeys': keys+['extra']}], **SCOPE))
        self.expect('SCENE_LIMIT_EXCEEDED', lambda: validate_bindings({'objectRef': self.root}, [
            {'objectRef': ref('object:'+str(index)), 'componentKeys': ['key:'+str(index)]} for index in range(1001)], **SCOPE))
        self.expect('SCENE_LIMIT_EXCEEDED', lambda: validate_bindings({'objectRef': self.root}, [
            {'objectRef': self.ct, 'componentKeys': keys}, {'objectRef': self.cn, 'componentKeys': ['more']}], **SCOPE))

    def test_same_component_key_in_two_independent_instances_is_legal(self):
        second = self.instance(identifier=self.other_id)
        snapshot = {'instances': [self.instance(), second]}
        self.assertEqual(root_change_reviews(snapshot, self.revision, snapshot, **SCOPE), [])
        self.assertEqual(required_engineering_refs(snapshot, **SCOPE), sorted([self.root, self.ct, self.cn], key=lambda item: item['entityUid']))

    def test_expectations_have_exact_ref_coverage_and_do_not_claim_authoritative_truth(self):
        values = [self.expectation(self.cn)]
        self.assertEqual(validate_expectations(values, required_refs=[self.cn], **SCOPE), values)
        self.expect('INVALID_REQUEST', lambda: validate_expectations(values+values, **SCOPE))
        self.expect('INVALID_REQUEST', lambda: validate_expectations([{**values[0], 'bindingEligible': True}], **SCOPE))
        self.expect('INVALID_REQUEST', lambda: validate_expectations([{**values[0], 'installationContextId': ''}], **SCOPE))
        self.expect('ENGINEERING_CHANGED', lambda: validate_expectations(values, required_refs=[self.ct], **SCOPE))
        self.expect('ENGINEERING_CHANGED', lambda: validate_expectations(values, required_refs=[], **SCOPE))

    def test_root_digest_is_order_independent_and_bound_to_revision_and_instance(self):
        changed = {'instances': [self.instance(root=self.new_root, bindings=[])]}
        before = copy.deepcopy(self.previous)
        before['instances'][0]['componentBindings'][0]['componentKeys'] = ['ct.2', 'ct.1']
        review = root_change_reviews(before, self.revision, changed, **SCOPE)[0]
        reverse = copy.deepcopy(before)
        for binding in reverse['instances'][0]['componentBindings']: binding['componentKeys'].reverse()
        reverse['instances'][0]['componentBindings'].reverse()
        self.assertEqual(root_change_reviews(reverse, self.revision, changed, **SCOPE)[0], review)
        other_revision = root_change_reviews(before, 'scene:other', changed, **SCOPE)[0]
        self.assertNotEqual(other_revision['reviewedRemovedBindingsDigest'], review['reviewedRemovedBindingsDigest'])
        other_before = {'instances': [self.instance(identifier=self.other_id)]}
        other_after = {'instances': [self.instance(identifier=self.other_id, root=self.new_root, bindings=[])]}
        self.assertNotEqual(root_change_reviews(other_before, self.revision, other_after, **SCOPE)[0]['reviewedRemovedBindingsDigest'], review['reviewedRemovedBindingsDigest'])
        self.assertEqual(len(review['removedBindings']), 2)

    def test_root_change_requires_exact_clear_acknowledgment_and_empty_new_bindings(self):
        changed = {'instances': [self.instance(root=self.new_root, bindings=[])]}
        declarations = self.root_changes(self.previous, changed)
        self.assertEqual(validate_root_changes(self.previous, self.revision, changed, declarations, **SCOPE), declarations)
        self.expect('ENGINEERING_CHANGED', lambda: validate_root_changes(self.previous, self.revision, changed, [], **SCOPE))
        self.expect('ENGINEERING_CHANGED', lambda: validate_root_changes(self.previous, self.revision, changed, declarations*2, **SCOPE))
        for key, value in [('from', self.cn), ('to', self.ct), ('reviewedRemovedBindingsDigest', '0'*64)]:
            bad = copy.deepcopy(declarations); bad[0][key] = value
            self.expect('ENGINEERING_CHANGED', lambda: validate_root_changes(self.previous, self.revision, changed, bad, **SCOPE))
        for value in (False, 1):
            bad = copy.deepcopy(declarations); bad[0]['clearOldComponentBindings'] = value
            self.expect('INVALID_REQUEST', lambda: validate_root_changes(self.previous, self.revision, changed, bad, **SCOPE))
        keep_old = copy.deepcopy(changed); keep_old['instances'][0]['componentBindings'] = self.previous['instances'][0]['componentBindings']
        self.expect('ENGINEERING_CHANGED', lambda: validate_root_changes(self.previous, self.revision, keep_old, declarations, **SCOPE))

    def test_new_root_and_removed_instance_have_explicit_from_to_reviews(self):
        empty = {'instances': []}; added = {'instances': [self.instance(bindings=[])]}
        new_changes = self.root_changes(empty, added)
        self.assertIsNone(new_changes[0]['from']); self.assertEqual(new_changes[0]['to'], self.root)
        validate_root_changes(empty, self.revision, added, new_changes, **SCOPE)
        removed = self.root_changes(self.previous, empty)
        self.assertEqual(removed[0]['from'], self.root); self.assertIsNone(removed[0]['to'])
        validate_root_changes(self.previous, self.revision, empty, removed, **SCOPE)
        self.expect('ENGINEERING_CHANGED', lambda: validate_root_changes(self.previous, self.revision, self.previous, removed, **SCOPE))

    def test_model_replacement_clears_only_changed_instance_and_keeps_root_and_input(self):
        before = {'instances': [self.instance(), self.instance(identifier=self.other_id)]}
        after = copy.deepcopy(before); after['instances'][0]['modelVersionId'] = self.v2
        original = copy.deepcopy(after)
        result = clear_model_replacement_bindings(before, after, **SCOPE)
        self.assertEqual(after, original)
        self.assertEqual(result['instances'][0]['rootBinding'], before['instances'][0]['rootBinding'])
        self.assertEqual(result['instances'][0]['componentBindings'], [])
        self.assertEqual(result['instances'][1], before['instances'][1])
        self.expect('ENGINEERING_CHANGED', lambda: self.derive(after, previous=before))

    def test_model_issues_preserve_original_object_keys_context_and_old_revision(self):
        issues = self.derive(self.replaced())
        self.assertEqual({item['objectRef']['entityUid']: item['code'] for item in issues}, {'CN-A': 'COMPONENT_MISSING', 'CT-A': 'MIGRATION_REQUIRED'})
        for issue in issues:
            self.assertIs(issue['blocking'], True)
            self.assertEqual(issue['installationContextId'], 'ctx-A')
            self.assertEqual(issue['sourceSceneRevision'], self.revision)
            self.assertEqual(issue['previousModelVersionId'], self.v1)
            self.assertNotEqual(issue['objectRef'], self.root)
        self.assertEqual(self.previous['instances'][0]['componentBindings'][0]['componentKeys'], ['ct'])

    def test_missing_context_or_catalog_cannot_create_an_apparently_valid_issue(self):
        self.expect('ENGINEERING_CHANGED', lambda: self.derive(self.replaced(), objects=[]))
        self.catalog.pop(self.v2)
        self.expect('RESOURCE_CHANGED', lambda: self.derive(self.replaced()))

    def test_historical_expectations_only_supply_old_issue_context_not_current_binding_proof(self):
        current = self.replaced()
        issues = derive_binding_issues(self.previous, self.revision, current, [], verified_bindings=[], verified_objects=[],
            historical_expectations=self.expectations, current_components=self.catalog, root_changes=[], **SCOPE)
        self.assertEqual({item['installationContextId'] for item in issues}, {'ctx-A'})
        rebound = copy.deepcopy(current)
        rebound['instances'][0]['componentBindings'] = [{'objectRef': self.ct, 'componentKeys': ['ct']}]
        self.expect('ENGINEERING_CHANGED', lambda: derive_binding_issues(current, self.revision, rebound, issues,
            verified_bindings=[self.proof(self.ct, ['ct'])], verified_objects=[], historical_expectations=self.expectations,
            current_components=self.catalog, root_changes=[], **SCOPE))

    def test_old_issue_context_requires_matching_historical_root_context(self):
        historical = copy.deepcopy(self.expectations)
        next(item for item in historical if item['ref'] == self.root)['installationContextId'] = 'ctx-other'
        self.expect('ENGINEERING_CHANGED', lambda: derive_binding_issues(self.previous, self.revision, self.replaced(), [],
            verified_bindings=[], verified_objects=self.expectations, historical_expectations=historical,
            current_components=self.catalog, root_changes=[], **SCOPE))
        self.expect('ENGINEERING_CHANGED', lambda: derive_binding_issues(self.previous, self.revision, self.replaced(), [],
            verified_bindings=[], verified_objects=self.expectations, historical_expectations=[self.expectation(self.root)],
            current_components=self.catalog, root_changes=[], **SCOPE))

    def test_plain_empty_bindings_and_repeated_model_change_do_not_wash_prior_issues(self):
        current = self.replaced(); issues = self.derive(current)
        self.assertEqual(self.derive(current, previous=current, issues=issues), issues)
        another_version = copy.deepcopy(current); another_version['instances'][0]['modelVersionId'] = self.v3
        self.assertEqual(self.derive(another_version, previous=current, issues=issues), issues)
        # A deliberate unbind without a model change does not invent migration facts.
        unbound = copy.deepcopy(self.previous); unbound['instances'][0]['componentBindings'] = []
        self.assertEqual(self.derive(unbound), [])

    def test_explicit_current_verified_binding_resolves_only_that_object_issue(self):
        current = self.replaced(); issues = self.derive(current)
        bound = copy.deepcopy(current); bound['instances'][0]['componentBindings'] = [{'objectRef': self.ct, 'componentKeys': ['ct']}]
        remaining = self.derive(bound, previous=current, issues=issues, proofs=[self.proof(self.ct, ['ct'])])
        self.assertEqual([item['objectRef'] for item in remaining], [self.cn])
        self.assertEqual(self.derive(bound, previous=current, issues=issues), issues)

    def test_proof_checks_exact_model_ref_context_keys_and_current_revisions(self):
        current = self.replaced(); issues = self.derive(current)
        bound = copy.deepcopy(current); bound['instances'][0]['componentBindings'] = [{'objectRef': self.ct, 'componentKeys': ['ct']}]
        for changes in ({'model_version_id': self.v1}, {'component_keys': ('cn',)}, {'object_ref': self.cn},
                        {'installation_context_id': 'other-context'}, {'entity_revision': 'entity:old'}, {'hierarchy_revision': 'hierarchy:old'}):
            with self.assertRaises(PreviewError):
                self.derive(bound, previous=current, issues=issues, proofs=[self.proof(self.ct, ['ct'], **changes)])
        self.expect('INVALID_REQUEST', lambda: self.derive(bound, previous=current, issues=issues, proofs=[{'verified': True}]))
        self.expect('INVALID_REQUEST', lambda: self.derive(bound, previous=current, issues=issues, proofs=[self.proof(self.ct, ['ct'])]*2))

    def test_binding_in_another_instance_never_resolves_near_layer_issue(self):
        current = self.replaced(); issues = self.derive(current)
        other = self.instance(identifier=self.other_id, version=self.v3, bindings=[{'objectRef': self.cn, 'componentKeys': ['cn']}])
        before = {'instances': current['instances']+[other]}
        result = self.derive(before, previous=before, issues=issues, proofs=[self.proof(self.cn, ['cn'], identifier=self.other_id, version=self.v3)])
        self.assertEqual(result, issues)
        # These source facts require the locator to stop at CN, even though the
        # root or a second independent representation remains available.
        cn_issue = next(item for item in result if item['objectRef'] == self.cn)
        self.assertEqual(cn_issue['sceneModelInstanceId'], self.instance_id)
        self.assertIs(cn_issue['blocking'], True)
        self.assertEqual(before['instances'][0]['rootBinding']['objectRef'], self.root)

    def test_missing_root_or_cross_context_proof_never_resolves_problem(self):
        current = self.replaced(); issues = self.derive(current)
        missing = copy.deepcopy(current); missing['instances'][0]['rootBinding'] = None
        changes = self.root_changes(current, missing)
        self.expect('ENGINEERING_CHANGED', lambda: self.derive(missing, previous=current, issues=issues,
            proofs=[self.proof(self.ct, ['ct'])], changes=changes))
        bound = copy.deepcopy(current); bound['instances'][0]['componentBindings'] = [{'objectRef': self.ct, 'componentKeys': ['ct']}]
        different_context = [self.expectation(value, context='ctx-B' if value == self.ct else 'ctx-A')
                             for value in (self.root, self.ct, self.cn)]
        self.expect('ENGINEERING_CHANGED', lambda: self.derive(bound, previous=current, issues=issues,
            proofs=[self.proof(self.ct, ['ct'], installation_context_id='ctx-B')], objects=different_context))

    def test_ambiguous_source_issue_is_preserved_without_inventing_source_identity(self):
        current = self.replaced(); issues = self.derive(current)
        issues[0]['code'] = 'SOURCE_ID_AMBIGUOUS'
        self.assertEqual(self.derive(current, previous=current, issues=issues), issues)
        original = copy.deepcopy(issues)
        output = self.derive(current, previous=current, issues=issues)
        output[0]['previousComponentKeys'].append('unrelated')
        self.assertEqual(issues, original)

    def test_reviewed_root_change_clears_only_that_instances_old_issues(self):
        current = self.replaced(); issues = self.derive(current)
        second = copy.deepcopy(issues[0]); second['sceneModelInstanceId'] = self.other_id
        before = {'instances': current['instances']+[self.instance(identifier=self.other_id, version=self.v2, bindings=[])]}
        after = copy.deepcopy(before); after['instances'][0]['rootBinding'] = {'objectRef': self.new_root}
        changes = self.root_changes(before, after)
        result = self.derive(after, previous=before, issues=issues+[second], changes=changes)
        self.assertEqual(result, [second])
        self.expect('ENGINEERING_CHANGED', lambda: self.derive(after, previous=before, issues=issues+[second]))

    def test_authority_issue_is_not_cleared_by_model_component_proof(self):
        current = self.replaced()
        issue = {'sceneModelInstanceId': self.instance_id, 'objectRef': self.ct, 'installationContextId': 'ctx-A',
                 'blocking': True, 'kind': 'engineering_changed', 'code': 'PARENT_CHAIN_CHANGED',
                 'expectedEntityRevision': 'entity:old', 'expectedHierarchyRevision': 'hierarchy:old'}
        current['instances'][0]['componentBindings'] = [{'objectRef': self.ct, 'componentKeys': ['ct']}]
        self.assertEqual(self.derive(current, previous=current, issues=[issue], proofs=[self.proof(self.ct, ['ct'])]), [issue])

    def test_required_refs_include_old_removals_and_prior_issues_without_copying_names(self):
        current = self.replaced(); issues = self.derive(current)
        refs = required_engineering_refs(current, previous_snapshot=self.previous, binding_issues=issues, **SCOPE)
        self.assertEqual({item['entityUid'] for item in refs}, {'root-A', 'CT-A', 'CN-A'})
        changed = copy.deepcopy(current); changed['instances'][0]['rootBinding'] = {'objectRef': self.new_root}
        changes = self.root_changes(current, changed)
        refs = required_engineering_refs(changed, previous_snapshot=current, binding_issues=issues, root_changes=changes, **SCOPE)
        self.assertEqual({item['entityUid'] for item in refs}, {'root-A', 'root-B', 'CT-A', 'CN-A'})
        validate_expectations(self.expectations, required_refs=refs, **SCOPE)
        self.expect('INVALID_REQUEST', lambda: required_engineering_refs(current, root_changes=[{'sceneModelInstanceId': True}], **SCOPE))

    def test_required_refs_derive_real_root_changes_before_user_confirmation(self):
        changed = {'instances': [self.instance(root=self.new_root, bindings=[])]}
        refs = required_engineering_refs(changed, previous_snapshot=self.previous, **SCOPE)
        self.assertEqual({item['entityUid'] for item in refs}, {'root-A', 'root-B', 'CT-A', 'CN-A'})
        wrong = self.root_changes(self.previous, changed); wrong[0]['from'] = self.cn
        self.expect('ENGINEERING_CHANGED', lambda: required_engineering_refs(changed, previous_snapshot=self.previous, root_changes=wrong, **SCOPE))

    def test_required_refs_include_ordinary_removed_bindings_with_unchanged_root_and_model(self):
        changed = copy.deepcopy(self.previous)
        changed['instances'][0]['componentBindings'] = []
        refs = required_engineering_refs(changed, previous_snapshot=self.previous, **SCOPE)
        self.assertEqual({item['entityUid'] for item in refs}, {'root-A', 'CT-A', 'CN-A'})

    def test_json_and_instance_limits_precede_unbounded_work(self):
        self.expect('SCENE_LIMIT_EXCEEDED', lambda: required_engineering_refs({'instances': [self.instance(identifier=str(uuid4())) for _ in range(101)]}, **SCOPE))
        self.expect('SCENE_LIMIT_EXCEEDED', lambda: validate_expectations([{'payload': 'x'*(1024*1024)}], **SCOPE))
        duplicate = {'instances': [self.instance(), self.instance()]}
        self.expect('INVALID_REQUEST', lambda: required_engineering_refs(duplicate, **SCOPE))


if __name__ == '__main__': unittest.main()
