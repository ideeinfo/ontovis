"""Synthetic authority contract tests; no OntoBase account, network or database.

The fixture uses the existing live resolve/installations wire shapes, including
nearest-parent-first paths and independent per-request snapshots.
"""
import copy
from urllib.parse import parse_qs, urlsplit
import unittest
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.scene_engineering import SceneEngineeringReader


PROJECT = 'synthetic project/1'
CONNECTION = 'synthetic-ontobase'
CTX = '00000000-0000-0000-0000-000000000071'
OTHER_CTX = '00000000-0000-0000-0000-000000000072'
ROOT, CABINET, CHILD, OTHER_ROOT = 'synthetic-root-A', 'synthetic-CN', 'synthetic-device/A?x=1&z=2', 'synthetic-root-B'


class SyntheticAuthority:
    def __init__(self):
        self.allowed = True
        self.calls = []
        self.after = None
        self.resolve_project = PROJECT
        self.resolution = 'exact'
        self.missing_context = False
        self.ancestor_edit = None
        self.children_edit = None
        self.contexts = {CTX: self.context(CTX, ROOT), OTHER_CTX: self.context(OTHER_CTX, OTHER_ROOT)}
        self.objects = {ROOT: self.object(ROOT, CTX), CABINET: self.object(CABINET, CTX),
            CHILD: self.object(CHILD, CTX), OTHER_ROOT: self.object(OTHER_ROOT, OTHER_CTX),
            'definition': self.object('definition', None, scope='definition'),
            'unclassified': self.object('unclassified', None, scope='unclassified')}
        self.parents = {CHILD: CABINET, CABINET: ROOT}
        self.relations = {(child, parent): self.relation(child, parent) for child, parent in self.parents.items()}

    @staticmethod
    def context(identifier, root):
        return {'installationContextId': identifier, 'projectCode': PROJECT, 'displayName': 'Synthetic installation',
            'purpose': 'demonstration', 'basis': 'Synthetic reviewed demonstration', 'rootEntityUid': root,
            'hierarchyRevision': identifier + ':7', 'engineeringUseAllowed': False}

    @staticmethod
    def object(uid, context, scope='installation'):
        return {'entityUid': uid, 'objectKind': 'equipment', 'displayName': 'Synthetic ' + uid,
            'reviewStatus': 'unclassified', 'classification': None, 'entityRevision': 'incarnation-'+uid+':1',
            'lifecycle': 'active', 'identifiers': [], 'installationContextId': context, 'objectScope': scope,
            'sourceTemplateEntityUid': 'synthetic-shared-definition' if context else None,
            'installationPurpose': 'demonstration' if context else None, 'hasChildren': uid in (ROOT, CABINET),
            'privateServerPath': '/private/source/not-a-public-field'}

    @staticmethod
    def relation(child, parent):
        identifier = str(uuid4())
        return {'relationId': identifier, 'relationRevision': identifier+':7', 'childEntityUid': child,
            'parentEntityUid': parent, 'status': 'assumed', 'validFrom': '2026-10-22T00:00:00Z', 'validTo': None,
            'evidenceRefs': [], 'reason': 'Synthetic parent relation', 'reviewedBy': 'synthetic-reviewer',
            'recordedAt': '2026-10-22T00:00:00Z', 'privateDatabasePath': '/private/not-public'}

    def guard(self):
        if not self.allowed:
            raise PreviewError(403, 'FORBIDDEN')

    def request(self, method, path, body=None):
        self.calls.append((method, path, copy.deepcopy(body)))
        parts, query = urlsplit(path), parse_qs(urlsplit(path).query)
        if method == 'POST' and parts.path.endswith('/objects/resolve'):
            assert set(body) in ({'entityUids', 'resolutionMode'}, {'entityUids', 'resolutionMode', 'installationContextId'})
            assert body['resolutionMode'] == 'live' and 0 < len(body['entityUids']) <= 50
            items = []
            for uid in body['entityUids']:
                item = self.objects.get(uid)
                if item and body.get('installationContextId') not in (None, item['installationContextId']): item = None
                items.append({'requestedEntityUid': uid, 'canonicalEntityUid': uid if item else None,
                    'resolution': self.resolution if item else 'unavailable', 'reasonCode': None if item else 'NOT_FOUND_OR_FORBIDDEN',
                    'object': item, 'canonicalObject': item})
            value = {'projectCode': self.resolve_project, 'items': items, 'resolutionMode': 'live', 'resolvedAsOf': '2026-10-22T00:00:00Z'}
        else:
            assert method == 'GET' and '/installations/' in parts.path
            identifier = parts.path.split('/installations/')[1].split('/')[0]
            if self.missing_context or identifier not in self.contexts:
                raise PreviewError(404, 'NOT_FOUND_OR_FORBIDDEN')
            context = self.contexts[identifier]
            common = {key: context[key] for key in ('projectCode', 'installationContextId', 'hierarchyRevision', 'purpose', 'engineeringUseAllowed')}
            common.update(resolvedAsOf='2026-10-22T00:00:00Z', objectMetadataMode='current')
            if parts.path.endswith('/ancestors'):
                assert set(query) == {'entityUid', 'resolutionMode'} and query['resolutionMode'] == ['live']
                uid = query['entityUid'][0]; node, path_items = uid, []
                while node in self.parents:
                    parent = self.parents[node]
                    path_items.append({'object': self.objects[parent], 'relation': self.relations[node, parent]})
                    node = parent
                complete = node == context['rootEntityUid']
                value = {**common, 'entityUid': uid, 'resolutionMode': 'live', 'path': path_items,
                    'completeness': 'complete' if complete else 'incomplete', 'reasonCode': None if complete else 'PATH_UNAVAILABLE'}
                if self.ancestor_edit: self.ancestor_edit(value)
            elif parts.path.endswith('/children'):
                assert set(query) <= {'parentEntityUid', 'limit', 'resolutionMode', 'cursor'}
                assert query['limit'] == ['50'] and query['resolutionMode'] == ['live']
                uid = query['parentEntityUid'][0]
                value = {**common, 'items': [{'object': self.objects[child], 'relation': self.relations[child, parent]}
                    for child, parent in self.parents.items() if parent == uid], 'nextCursor': 'synthetic-opaque-cursor',
                    'snapshotRevision': context['hierarchyRevision']+':catalog-hash', 'retrievedAt': '2026-10-22T00:00:00Z'}
                if self.children_edit: self.children_edit(value)
            else:
                assert not query
                value = {'item': context}
        result = copy.deepcopy(value)
        if self.after: self.after(self, method, path, body)
        return result


class SceneEngineeringTests(unittest.TestCase):
    def setUp(self):
        self.authority = SyntheticAuthority()
        self.reader = SceneEngineeringReader(self.authority, CONNECTION, PROJECT, self.authority.guard)

    def expect(self, code, action, status=None):
        with self.assertRaises(PreviewError) as caught: action()
        self.assertEqual(caught.exception.code, code)
        if status is not None: self.assertEqual(caught.exception.status, status)

    def detail(self, uid=CHILD, **options):
        return self.reader.detail(CTX, uid, CTX+':7', **options)

    def test_context_discovery_uses_actual_installation_not_default_equipment(self):
        first = self.reader.context_for_object(CHILD)
        other = self.reader.context_for_object(OTHER_ROOT)
        self.assertEqual(first['expectation'], {'ref': {'ontobaseConnectionId': CONNECTION, 'projectCode': PROJECT, 'entityUid': CHILD},
            'expectedEntityRevision': self.authority.objects[CHILD]['entityRevision'], 'installationContextId': CTX,
            'expectedHierarchyRevision': CTX+':7'})
        self.assertTrue(first['bindingEligible']); self.assertTrue(other['bindingEligible'])
        self.assertEqual([row['object']['entityUid'] for row in first['ancestors']['path']], [CABINET, ROOT])
        self.assertEqual(other['context']['installationContextId'], OTHER_CTX)
        self.assertEqual(other['ancestors']['path'], [])
        self.assertNotEqual(first['objectRef'], other['objectRef'])
        self.assertEqual(first['item']['sourceTemplateEntityUid'], other['item']['sourceTemplateEntityUid'])
        self.assertIn('/synthetic%20project%2F1/', self.authority.calls[0][1])

    def test_root_is_a_complete_zero_ancestor_path_and_status_is_not_confirmation(self):
        value = self.detail(ROOT)
        self.assertEqual(value['root'], value['item'])
        self.assertEqual(value['item']['reviewStatus'], 'unclassified')
        self.assertTrue(value['bindingEligible'])
        self.assertFalse(value['context']['engineeringUseAllowed'])

    def test_legal_multiline_names_basis_and_relation_reasons_are_preserved(self):
        self.authority.contexts[CTX].update(displayName='合成安装\n第二行', basis='图纸依据\n补充说明')
        self.authority.objects[CHILD]['displayName'] = '设备名称\n控制信号'
        self.authority.relations[CHILD, CABINET]['reason'] = '父子关系依据\n补充说明'
        value = self.detail()
        self.assertTrue(value['bindingEligible'])
        self.assertEqual(value['item']['displayName'], '设备名称\n控制信号')
        self.assertEqual(value['context']['displayName'], '合成安装\n第二行')
        self.assertEqual(value['context']['basis'], '图纸依据\n补充说明')
        self.assertEqual(value['ancestors']['path'][0]['relation']['reason'], '父子关系依据\n补充说明')

    def test_definition_and_unclassified_keep_distinct_readable_nonbinding_identity(self):
        for uid, scope in [('definition', 'definition'), ('unclassified', 'unclassified')]:
            self.authority.calls.clear()
            value = self.reader.context_for_object(uid)
            self.assertEqual(value['item']['objectScope'], scope)
            self.assertFalse(value['bindingEligible']); self.assertIsNone(value['expectation'])
            self.assertIsNone(value['context']); self.assertIsNone(value['root'])
            self.assertFalse(any('/installations/' in path for _, path, _ in self.authority.calls))
            self.assertEqual(self.reader.detail(None, uid, None)['item']['entityUid'], uid)

    def test_nonexact_resolution_and_inactive_objects_never_follow_alias(self):
        self.authority.resolution = 'merged'
        self.expect('IDENTITY_CHANGED', lambda: self.reader.context_for_object(CHILD), 409)
        self.authority.resolution = 'exact'; self.authority.objects[CHILD]['lifecycle'] = 'merged'
        self.expect('IDENTITY_CHANGED', lambda: self.reader.context_for_object(CHILD), 409)
        self.expect('NOT_FOUND_OR_FORBIDDEN', lambda: self.reader.context_for_object('unknown-name'), 404)

    def test_canonical_uid_change_is_rejected_even_when_resolution_claims_exact(self):
        original = self.authority.request
        def altered(method, path, body=None):
            value = original(method, path, body)
            if path.endswith('/objects/resolve'): value['items'][0]['canonicalEntityUid'] = ROOT
            return value
        self.authority.request = altered
        self.expect('IDENTITY_CHANGED', lambda: self.reader.context_for_object(CHILD), 409)

    def test_other_project_resolve_or_context_cannot_return_private_context(self):
        self.authority.resolve_project = 'other-project'
        self.expect('NOT_FOUND_OR_FORBIDDEN', lambda: self.reader.context_for_object(CHILD), 403)
        self.authority.resolve_project = PROJECT; self.authority.contexts[CTX]['projectCode'] = 'other-project'
        self.expect('NOT_FOUND_OR_FORBIDDEN', lambda: self.reader.context_for_object(CHILD), 403)

    def test_unknown_context_is_readable_but_explicit_expected_context_cannot_upgrade(self):
        self.authority.missing_context = True
        value = self.reader.context_for_object(CHILD)
        self.assertEqual(value['item']['entityUid'], CHILD)
        self.assertFalse(value['bindingEligible']); self.assertIsNone(value['expectation'])
        self.expect('ENGINEERING_CHANGED', self.detail, 409)

    def test_different_installation_is_rejected_without_borrowing_another_root(self):
        self.expect('NOT_FOUND_OR_FORBIDDEN', lambda: self.reader.detail(OTHER_CTX, CHILD, OTHER_CTX+':7'), 403)
        self.assertFalse(any('/ancestors?' in path for _, path, _ in self.authority.calls))

    def test_incomplete_and_invalid_chain_are_readable_without_binding_proof(self):
        self.authority.parents.pop(CABINET)
        value = self.detail()
        self.assertFalse(value['bindingEligible']); self.assertIsNone(value['expectation'])
        self.authority.parents[CABINET] = ROOT
        self.authority.ancestor_edit = lambda value: value['path'][0]['relation'].update(childEntityUid='wrong-child')
        value = self.reader.context_for_object(CHILD)
        self.assertEqual(value['ancestors']['reasonCode'], 'INVALID_HIERARCHY')
        self.assertEqual(value['ancestors']['path'], [])
        self.assertFalse(value['bindingEligible'])

    def test_claimed_complete_path_without_actual_context_root_is_not_binding_eligible(self):
        self.authority.ancestor_edit = lambda value: value['path'].pop()
        value = self.detail()
        self.assertFalse(value['bindingEligible']); self.assertIsNone(value['root'])

    def test_ancestor_from_another_context_is_not_exposed_as_a_valid_parent(self):
        self.authority.ancestor_edit = lambda value: value['path'][0]['object'].update(installationContextId=OTHER_CTX)
        value = self.detail()
        self.assertEqual(value['ancestors']['path'], [])
        self.assertFalse(value['bindingEligible'])

    def test_explicit_object_and_hierarchy_expectations_refuse_stale_values(self):
        self.expect('ENGINEERING_CHANGED', lambda: self.detail(expected_entity_revision='incarnation:old'), 409)
        self.expect('ENGINEERING_CHANGED', lambda: self.reader.detail(CTX, CHILD, CTX+':6'), 409)
        self.authority.ancestor_edit = lambda value: value.update(hierarchyRevision=CTX+':8')
        self.expect('ENGINEERING_CHANGED', self.detail, 409)

    def test_selected_metadata_change_between_requests_is_detected_without_hierarchy_change(self):
        def change(source, method, path, body):
            if '/ancestors?' in path:
                source.after = None; source.objects[CHILD]['entityRevision'] += '-changed'
        self.authority.after = change
        self.expect('ENGINEERING_CHANGED', self.detail, 409)

    def test_ancestor_revision_change_between_path_and_batch_resolve_is_detected(self):
        def change(source, method, path, body):
            if '/ancestors?' in path:
                source.after = None; source.objects[ROOT]['entityRevision'] += '-changed'
        self.authority.after = change
        self.expect('ENGINEERING_CHANGED', self.detail, 409)

    def test_hierarchy_change_during_final_metadata_read_is_detected(self):
        def change(source, method, path, body):
            if body and 'installationContextId' in body:
                source.after = None; source.contexts[CTX]['hierarchyRevision'] = CTX+':8'
        self.authority.after = change
        self.expect('ENGINEERING_CHANGED', self.detail, 409)

    def test_revocation_during_upstream_read_prevents_late_private_result(self):
        def revoke(source, method, path, body):
            if path.endswith('/installations/'+CTX): source.allowed = False
        self.authority.after = revoke
        self.expect('FORBIDDEN', self.detail, 403)
        self.assertFalse(any('/ancestors?' in path for _, path, _ in self.authority.calls))

    def test_access_revision_change_propagates_instead_of_becoming_an_incomplete_chain(self):
        grant = ['grant:1']
        def authorize():
            if grant[0] != 'grant:1': raise PreviewError(409, 'ACCESS_CHANGED')
        self.reader = SceneEngineeringReader(self.authority, CONNECTION, PROJECT, authorize)
        def change(source, method, path, body):
            if '/ancestors?' in path: grant[0] = 'grant:2'
        self.authority.after = change
        self.expect('ACCESS_CHANGED', self.detail, 409)

    def test_unknown_context_fallback_rechecks_the_object_before_returning_it(self):
        original = self.authority.request
        def changed(method, path, body=None):
            if path.endswith('/installations/'+CTX):
                self.authority.objects[CHILD]['entityRevision'] += '-new'
                raise PreviewError(404, 'NOT_FOUND_OR_FORBIDDEN')
            return original(method, path, body)
        self.authority.request = changed
        self.expect('ENGINEERING_CHANGED', lambda: self.reader.context_for_object(CHILD), 409)

    def test_children_page_keeps_server_cursor_revision_and_exact_parent_edges(self):
        value = self.reader.children(CTX, CABINET, CTX+':7', cursor='opaque +/?')
        self.assertEqual(value['items'][0]['object']['entityUid'], CHILD)
        self.assertEqual(value['items'][0]['relation']['parentEntityUid'], CABINET)
        self.assertEqual(value['snapshotRevision'], CTX+':7:catalog-hash')
        self.assertEqual(value['nextCursor'], 'synthetic-opaque-cursor')
        path = next(path for _, path, _ in self.authority.calls if '/children?' in path)
        self.assertEqual(parse_qs(urlsplit(path).query), {'parentEntityUid': [CABINET], 'limit': ['50'],
            'resolutionMode': ['live'], 'cursor': ['opaque +/?']})

    def test_children_wrong_parent_or_duplicate_identity_is_never_accepted(self):
        self.authority.children_edit = lambda value: value['items'][0]['relation'].update(parentEntityUid=OTHER_ROOT)
        self.expect('SOURCE_UNAVAILABLE', lambda: self.reader.children(CTX, CABINET, CTX+':7'), 502)
        self.authority.children_edit = lambda value: value['items'].append(copy.deepcopy(value['items'][0]))
        self.expect('SOURCE_UNAVAILABLE', lambda: self.reader.children(CTX, CABINET, CTX+':7'), 502)

    def test_full_fifty_child_page_rechecks_metadata_in_bounded_resolve_batches(self):
        self.authority.parents.pop(CHILD)
        for index in range(50):
            uid = f'synthetic-page-child-{index}'
            self.authority.objects[uid] = self.authority.object(uid, CTX)
            self.authority.parents[uid] = CABINET
            self.authority.relations[uid, CABINET] = self.authority.relation(uid, CABINET)
        value = self.reader.children(CTX, CABINET, CTX+':7')
        self.assertEqual(len(value['items']), 50)
        batches = [body['entityUids'] for _, _, body in self.authority.calls if body and 'installationContextId' in body]
        self.assertTrue(any(len(batch) == 50 for batch in batches))
        self.assertTrue(all(len(batch) <= 50 for batch in batches))

    def test_engineering_status_is_current_authority_data_and_future_relation_is_invalid(self):
        self.authority.contexts[CTX].update(purpose='engineering', engineeringUseAllowed=True)
        for uid in (ROOT, CABINET, CHILD): self.authority.objects[uid]['installationPurpose'] = 'engineering'
        for relation in self.authority.relations.values(): relation['status'] = 'confirmed'
        value = self.detail()
        self.assertTrue(value['bindingEligible']); self.assertTrue(value['context']['engineeringUseAllowed'])
        self.assertEqual(value['ancestors']['path'][0]['relation']['status'], 'confirmed')
        self.authority.relations[CHILD, CABINET]['relationRevision'] = self.authority.relations[CHILD, CABINET]['relationId']+':8'
        invalid = self.detail()
        self.assertFalse(invalid['bindingEligible']); self.assertIsNone(invalid['expectation'])

    def test_child_metadata_or_empty_page_context_change_is_refused(self):
        def change(source, method, path, body):
            if '/children?' in path:
                source.after = None; source.objects[CHILD]['entityRevision'] += '-changed'
        self.authority.after = change
        self.expect('ENGINEERING_CHANGED', lambda: self.reader.children(CTX, CABINET, CTX+':7'), 409)
        self.authority = SyntheticAuthority()
        self.reader = SceneEngineeringReader(self.authority, CONNECTION, PROJECT, self.authority.guard)
        def change_empty(source, method, path, body):
            if '/children?' in path:
                source.contexts[CTX]['hierarchyRevision'] = CTX+':8'; source.after = None
        self.authority.after = change_empty
        self.expect('ENGINEERING_CHANGED', lambda: self.reader.children(CTX, CHILD, CTX+':7'), 409)

    def test_only_public_summary_fields_are_returned(self):
        value = self.detail()
        self.assertNotIn('privateServerPath', repr(value))
        self.assertNotIn('privateDatabasePath', repr(value))
        self.assertFalse(any(method not in ('GET', 'POST') or method == 'POST' and not path.endswith('/objects/resolve')
            for method, path, _ in self.authority.calls))

    def test_input_conditions_are_bounded_before_upstream_reads(self):
        for call in (lambda: self.reader.context_for_object(''), lambda: self.reader.context_for_object('a'*513),
            lambda: self.reader.context_for_object('line\nbreak'), lambda: self.reader.context_for_object(CHILD, 1),
            lambda: self.reader.detail('not-a-context', CHILD, 'h1'), lambda: self.reader.detail(CTX, CHILD, None),
            lambda: self.reader.children(CTX, CABINET, CTX+':7', cursor='x'*8193)):
            self.expect('INVALID_REQUEST', call, 422)
        self.assertEqual(self.authority.calls, [])


if __name__ == '__main__': unittest.main()
