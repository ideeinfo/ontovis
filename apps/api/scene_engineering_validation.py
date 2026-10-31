"""Fresh, server-only engineering checks for one complete scene operation.

The reader owns exact current identities and complete physical chains. This
callback combines those facts with a fixed model's actual component directory;
client review declarations supply concurrency conditions, never facts.
"""
from __future__ import annotations

from .authority import PreviewError
from .scene_bindings import (VerifiedBinding, derive_binding_issues,
    required_engineering_refs, root_change_reviews, validate_bindings,
    validate_expectations, validate_ref, validate_root_changes)


def _require(condition, code='INVALID_REQUEST', status=422):
    if not condition:
        raise PreviewError(status, code)


def _key(ref):
    return ref['ontobaseConnectionId'], ref['projectCode'], ref['entityUid']


def _root(instance):
    value = instance['rootBinding'] if instance is not None else None
    return value['objectRef'] if value is not None else None


class SceneEngineeringValidator:
    def __init__(self, reader, model_components, connection_id, project_code, *, shared_configuration=None):
        _require(callable(getattr(reader, 'context_for_object', None))
                 and callable(getattr(reader, 'authorize', None)) and callable(model_components))
        self.reader, self.model_components = reader, model_components
        self.shared_configuration=shared_configuration
        self.scope = {'connection_id': connection_id, 'project_code': project_code}
        _require(reader.connection_id == connection_id and reader.project_code == project_code)

    def _instances(self, snapshot):
        # The store validates the complete editable snapshot; these pure rules
        # independently validate its binding surface and fixed instance IDs.
        required_engineering_refs(snapshot, **self.scope)
        return {item['sceneModelInstanceId']: {**item, **validate_bindings(
            item['rootBinding'], item['componentBindings'], **self.scope)}
            for item in snapshot['instances']}

    def _read(self, refs):
        selections, expectations, known_objects, known_contexts = {}, {}, {}, {}
        for ref in refs:
            selected = self.reader.context_for_object(ref['entityUid'])
            _require(selected['objectRef'] == ref, 'IDENTITY_CHANGED', 409)
            identity = _key(ref); selections[identity] = selected
            context = selected['context']
            if context is not None:
                identifier = context['installationContextId']
                _require(identifier not in known_contexts or known_contexts[identifier] == context,
                         'ENGINEERING_CHANGED', 409)
                known_contexts[identifier] = context
            objects = [selected['item']] + [entry['object'] for entry in selected['ancestors']['path']]
            for item in objects:
                uid = item['entityUid']
                _require(uid not in known_objects or known_objects[uid] == item, 'ENGINEERING_CHANGED', 409)
                known_objects[uid] = item
            if selected['bindingEligible']:
                expected = validate_expectations([selected['expectation']], **self.scope)[0]
                _require(expected['ref'] == ref and context is not None
                         and expected['installationContextId'] == context['installationContextId']
                         and expected['expectedHierarchyRevision'] == context['hierarchyRevision']
                         and expected['expectedEntityRevision'] == selected['item']['entityRevision'],
                         'ENGINEERING_CHANGED', 409)
                expectations[identity] = expected
        return selections, expectations

    @staticmethod
    def _within(root_ref, selected, current):
        if root_ref is None or not selected['bindingEligible']:
            return False
        root = current.get(_key(root_ref))
        if root is None or not root['bindingEligible']:
            return False
        if root['expectation']['installationContextId'] != selected['expectation']['installationContextId']:
            return False
        uid = root_ref['entityUid']
        return uid == selected['item']['entityUid'] or any(
            entry['object']['entityUid'] == uid for entry in selected['ancestors']['path'])

    def _catalog(self, version):
        components = self.model_components(version)
        _require(type(components) is list, 'RESOURCE_CHANGED', 409)
        keys = []
        for component in components:
            _require(type(component) is dict, 'RESOURCE_CHANGED', 409)
            key = component.get('componentKey')
            _require(type(key) is str and 0 < len(key) <= 512 and key == key.strip()
                     and all(ord(character) >= 32 for character in key), 'RESOURCE_CHANGED', 409)
            keys.append(key)
        _require(len(keys) == len(set(keys)), 'RESOURCE_CHANGED', 409)
        return keys

    @staticmethod
    def _change_code(selected, expectation, legal):
        item = selected['item']
        if item['objectScope'] != 'installation' or item['installationContextId'] != expectation['installationContextId']:
            return 'IDENTITY_CHANGED'
        if not selected['bindingEligible'] or not legal or selected['expectation']['expectedHierarchyRevision'] != expectation['expectedHierarchyRevision']:
            return 'PARENT_CHAIN_CHANGED'
        if item['entityRevision'] != expectation['expectedEntityRevision']:
            return 'ENTITY_CHANGED'
        return None

    def __call__(self, snapshot, reviewed, changes, *, previous_snapshot,
                 previous_revision, previous_validation, mode='check'):
        _require(mode in ('check', 'save', 'open', 'replacement'))
        _require(type(previous_validation) is dict)
        before, after = self._instances(previous_snapshot), self._instances(snapshot)
        shared_uses={}
        if self.shared_configuration:
            shared_uses['sharedConfigurationUses']=previous_validation.get('sharedConfigurationUses',[]) if mode=='open' else []
        if self.shared_configuration and mode!='open':
            for uid,item in after.items():
                root=_root(item)
                config=self.shared_configuration(root['entityUid']) if root else None
                if not config:continue
                shared_uses['sharedConfigurationUses'].append({'sceneModelInstanceId':uid,'equipmentEntityUid':root['entityUid'],
                    'configurationId':config['configurationId'],'configurationRevision':config['configurationRevision']})
                old=before.get(uid)
                _require(item['componentBindings']==(old['componentBindings'] if old else []),
                         'SHARED_CONFIGURATION_REQUIRED',409)
                if old is None or _root(old)!=root or old['modelVersionId']!=item['modelVersionId']:
                    _require(any(m['modelVersionId']==item['modelVersionId'] for m in config['snapshot']['models']),
                             'MODEL_MAPPING_REQUIRED',409)
        old_expectations = validate_expectations(previous_validation.get('engineeringExpectations', []), **self.scope)
        historical = {_key(item['ref']): item for item in old_expectations}
        old_issues = previous_validation.get('bindingIssues', [])
        impacts = root_change_reviews(previous_snapshot, previous_revision, snapshot, **self.scope)
        declarations = [{key: value for key, value in item.items() if key != 'removedBindings'} for item in impacts]
        if mode == 'save':
            declarations = validate_root_changes(previous_snapshot, previous_revision, snapshot, changes, **self.scope)
        else:
            _require(reviewed == [] and changes == [])
            # A root switch cannot carry the old internal associations even in
            # preview; the generated declaration is still not user consent.
            validate_root_changes(previous_snapshot, previous_revision, snapshot, declarations, **self.scope)
        refs = required_engineering_refs(snapshot, previous_snapshot=previous_snapshot,
            binding_issues=old_issues, root_changes=declarations, **self.scope)
        if not refs:
            if mode == 'save': validate_expectations(reviewed, required_refs=[], **self.scope)
            self.reader.authorize()
            return {'engineeringExpectations': [], 'bindingIssues': [],
                    'rootBindingChanges': declarations, 'rootBindingImpact': impacts,**shared_uses}
        selections, current = self._read(refs)
        expectations = [current[key] for key in sorted(current)]
        if mode == 'save':
            declared = validate_expectations(reviewed, required_refs=refs, **self.scope)
            _require(declared == expectations, 'ENGINEERING_CHANGED', 409)

        changed_roots = {item['sceneModelInstanceId'] for item in declarations}
        catalogs, proofs, legal_associations = {}, [], set()
        old_associations = set()
        for identifier, instance in before.items():
            if _root(instance) is not None: old_associations.add((identifier, _key(_root(instance))))
            old_associations.update((identifier, _key(binding['objectRef'])) for binding in instance['componentBindings'])
        # Prior issues are validated by the pure rules below. They are also old
        # associations for deciding whether to report drift or reject a new one.
        for issue in old_issues:
            _require(type(issue) is dict)
            validate_ref(issue.get('objectRef'), **self.scope)
            old_associations.add((issue.get('sceneModelInstanceId'), _key(issue['objectRef'])))

        active = {}
        participating = {issue['sceneModelInstanceId'] for issue in old_issues}
        participating.update(identifier for identifier, item in before.items() if item['componentBindings']
                             and identifier in after and item['modelVersionId'] != after[identifier]['modelVersionId'])
        for identifier, instance in after.items():
            root = _root(instance)
            if root is not None: participating.add(identifier)
            if identifier in participating:
                version = instance['modelVersionId']
                if version not in catalogs: catalogs[version] = self._catalog(version)
            bindings = ([{'objectRef': root, 'componentKeys': None}] if root is not None else []) + instance['componentBindings']
            for binding in bindings:
                ref = binding['objectRef']; identity = identifier, _key(ref)
                selected = selections[_key(ref)]
                legal = self._within(root, selected, selections)
                active[identity] = legal
                # New illegal references cannot become a persisted drift issue.
                _require(legal or mode != 'save' and identity in old_associations
                         and identifier not in changed_roots, 'ENGINEERING_CHANGED', 409)
                if legal: legal_associations.add(identity)
                if binding['componentKeys'] is not None:
                    _require(set(binding['componentKeys']) <= set(catalogs[instance['modelVersionId']]), 'RESOURCE_CHANGED', 409)
                    if mode == 'save' and legal:
                        expected = current[_key(ref)]
                        proofs.append(VerifiedBinding(identifier, instance['modelVersionId'], ref,
                            expected['installationContextId'], tuple(binding['componentKeys']),
                            expected['expectedEntityRevision'], expected['expectedHierarchyRevision']))

        retained = []
        for issue in old_issues:
            identity = issue['sceneModelInstanceId'], _key(issue['objectRef'])
            if issue['kind'] == 'engineering_changed' and mode == 'save' and identity in legal_associations:
                continue
            retained.append(issue)
        issues = derive_binding_issues(previous_snapshot, previous_revision, snapshot, retained,
            verified_bindings=proofs, verified_objects=expectations, current_components=catalogs,
            root_changes=declarations, historical_expectations=old_expectations, **self.scope)
        existing = {(issue['sceneModelInstanceId'], _key(issue['objectRef'])): issue
                    for issue in issues if issue['kind'] == 'engineering_changed'}
        to_check = dict(active)
        for issue in issues:
            identity = issue['sceneModelInstanceId'], _key(issue['objectRef'])
            if identity[0] in after:
                to_check.setdefault(identity, self._within(_root(after[identity[0]]), selections[identity[1]], selections))
        for (identifier, key), legal in sorted(to_check.items()):
            if identifier in changed_roots or mode == 'save' and (identifier, key) in legal_associations:
                continue
            basis = historical.get(key)
            if basis is None:
                _require((identifier, key) not in old_associations, 'ENGINEERING_CHANGED', 409)
                continue
            code = self._change_code(selections[key], basis, legal)
            if code is not None and (identifier, key) not in existing:
                issue = {'sceneModelInstanceId': identifier, 'objectRef': basis['ref'],
                    'installationContextId': basis['installationContextId'], 'blocking': True,
                    'kind': 'engineering_changed', 'code': code,
                    'expectedEntityRevision': basis['expectedEntityRevision'],
                    'expectedHierarchyRevision': basis['expectedHierarchyRevision']}
                issues.append(issue); existing[identifier, key] = issue
        # The pure helper rejects malformed/duplicate persisted issue shapes;
        # deleted instances are removed only by an explicit reviewed root change.
        _require(all(issue['sceneModelInstanceId'] in after for issue in issues), 'ENGINEERING_CHANGED', 409)
        issues.sort(key=lambda item: (item['sceneModelInstanceId'], _key(item['objectRef']),
                                     item['installationContextId'], item['kind']))
        self.reader.authorize()
        return {'engineeringExpectations': expectations, 'bindingIssues': issues,
                'rootBindingChanges': declarations, 'rootBindingImpact': impacts,**shared_uses}
