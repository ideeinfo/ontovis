"""Real SQLite registry transactions with synthetic sources and proof callbacks.

No OntoBase, actual legacy identities, migration apply or current-user proof.
"""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from threading import Event, Thread
import unittest
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.legacy_scene_registry import LegacySceneRegistry, source_set_digest
from apps.api.model_library import ModelLibrary
from apps.api.model_validation import validate
from apps.api.project_model_library import ProjectModelLibrary
from apps.api.scene_library import SceneLibrary
from tests.test_model_upload import glb


class LegacySceneRegistryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.context = str(uuid4())
        self.library = ModelLibrary(self.root/'private', 'synthetic-registry-project', self.context)
        self.models = ProjectModelLibrary(self.library)
        self.scenes = SceneLibrary(self.library, model_identity=self.models.content_identity)
        self.registry = LegacySceneRegistry(self.library)
        self.allowed = True; self.proof = 'current-synthetic-proof:1'; self.validator_calls = 0
        self.fixed_key = 'f'*64; self.source_digests = {self.fixed_key: 'e'*64}
        self.legacy, self.model = self.new_model()
        self.default_scene = self.new_scene(self.model)
        self.upload_scene = self.new_scene(self.model)
        self.body = {'expectedLibraryRevision': self.library.listing()['libraryRevision'],
            'defaultSourceKey': self.fixed_key, 'sources': [
                self.source('fixed_model', self.fixed_key, self.default_scene),
                self.source('uploaded_version', self.legacy['versionId'], self.upload_scene)]}

    def authorize(self):
        if not self.allowed: raise PreviewError(403, 'SCENE_WRITE_FORBIDDEN')

    def ref(self, uid):
        return {'ontobaseConnectionId': 'synthetic-connection', 'projectCode': 'synthetic-registry-project', 'entityUid': uid}

    def engineering(self, snapshot, *args, **kwargs):
        uids = {binding['objectRef']['entityUid'] for item in snapshot['instances'] for binding in item['componentBindings']}
        uids.update(item['rootBinding']['objectRef']['entityUid'] for item in snapshot['instances'] if item['rootBinding'])
        return {'engineeringExpectations': [{'ref': self.ref(uid), 'expectedEntityRevision': 'object:1',
            'installationContextId': self.context, 'expectedHierarchyRevision': self.context+':1'} for uid in sorted(uids)],
            'bindingIssues': [], 'rootBindingChanges': [], 'rootBindingImpact': []}

    def resources(self, snapshot):
        for item in snapshot['instances']:
            value = self.models.content_identity(item['modelVersionId'])
            self.models.content(item['modelVersionId'], value['contentRevision'], value['sha256'], self.authorize)

    def new_model(self):
        path = glb(self.root/(str(uuid4())+'.glb'))
        report = validate(path)
        report['components'] += [{'componentKey': 'proxy:'+role, 'displayName': role, 'nodeIndices': [],
            'keyStability': 'version_local', 'geometryQuality': 'proxy_schematic', 'bounds': [[0, 0, 0], [1, 2, 1]]}
            for role in ('CT', 'CN1')]
        legacy = self.library.save_upload(path, {'expectedSessionRevision': 'synthetic-transport',
            'expectedLibraryRevision': self.library.listing()['libraryRevision'], 'clientRequestId': str(uuid4()),
            'displayName': 'Synthetic original', 'sourceNote': 'Synthetic source only', 'rightsDeclared': True},
            'synthetic-original-author', report, self.authorize)
        for index, (uid, key) in enumerate((('CT', 'proxy:CT'), ('CN1', 'proxy:CN1'), ('CN', 'component:2'))):
            self.library.bind({'modelVersionId': legacy['versionId'], 'entityUid': uid, 'componentKey': key,
                'expectedEntityRevision': 'object:1', 'expectedHierarchyRevision': self.context+':1',
                'expectedModelRevision': index+1, 'clientRequestId': str(uuid4())}, 'synthetic-admin', self.authorize)
        imported = self.models.import_existing({'legacyModelVersionId': legacy['versionId'], 'expectedModelRevision': 4,
            'expectedSha256': legacy['sha256'], 'expectedLibraryRevision': self.library.listing()['libraryRevision'],
            'purpose': 'equipment', 'clientRequestId': str(uuid4())}, 'synthetic-admin', self.authorize)
        model = self.models.preserve_legacy_display({'modelVersionId': imported['modelVersionId'],
            'expectedContentRevision': imported['contentRevision'], 'expectedLibraryRevision': self.library.listing()['libraryRevision'],
            'clientRequestId': str(uuid4()), 'preservationBasis': {'mode': 'preserve_legacy_display',
            'sourceNote': 'Preserve synthetic display only'}}, 'synthetic-admin', self.authorize)
        self.source_digests[legacy['versionId']] = hashlib.sha256(('source:'+legacy['versionId']).encode()).hexdigest()
        return legacy, model

    def new_scene(self, model):
        scene = self.scenes.create({'displayName': 'Synthetic compatibility scene', 'clientRequestId': str(uuid4())},
            'synthetic-admin', self.authorize, self.resources, lambda *args: None, engineering_check=self.engineering)
        snapshot = copy.deepcopy(scene['snapshot'])
        snapshot['instances'] = [{'sceneModelInstanceId': str(uuid4()), 'displayName': 'Synthetic original display',
            'modelVersionId': model['modelVersionId'], 'placement': {'position': {'mode': 'local', 'xM': 0, 'zM': 0},
            'height': {'mode': 'local_relative', 'relativeHeightM': 0}, 'headingDeg': 0}, 'visible': True,
            'positionLocked': False, 'rootBinding': {'objectRef': self.ref('ROOT')},
            'componentBindings': [{'objectRef': self.ref(uid), 'componentKeys': [key]}
                for uid, key in (('CT', 'proxy:CT'), ('CN1', 'proxy:CN1'), ('CN', 'component:2'))]}]
        return self.save_scene(scene, snapshot)

    def save_scene(self, scene, snapshot):
        result = self.scenes.save({'sceneId': scene['sceneId'], 'expectedSceneRevision': scene['sceneRevision'],
            'clientRequestId': str(uuid4()), 'snapshot': snapshot, 'reviewedEngineering': [], 'rootBindingChanges': []},
            'synthetic-admin', self.authorize, self.resources, lambda *args: None, engineering_check=self.engineering)
        return self.scenes.open(scene['sceneId'], 'synthetic-admin', self.authorize,
            result['sceneRevision'], engineering_check=self.engineering)

    def source(self, kind, key, scene):
        return {'sourceKind': kind, 'sourceKey': key, 'expectedSourceDigest': self.source_digests[key],
            'sceneId': scene['sceneId'], 'expectedSceneRevision': scene['sceneRevision'],
            'sceneModelInstanceId': scene['snapshot']['instances'][0]['sceneModelInstanceId']}

    def validator(self, db, sources, default):
        self.validator_calls += 1
        self.assertEqual(default, self.fixed_key)
        values = []
        for source in sources:
            if source['expectedSourceDigest'] != self.source_digests[source['sourceKey']]:
                raise PreviewError(409, 'LEGACY_SOURCE_CHANGED')
            values.append({'sourceKind': source['sourceKind'], 'sourceKey': source['sourceKey'],
                           'sourceDigest': self.source_digests[source['sourceKey']]})
        return {'sourceSetDigest': source_set_digest(values), 'engineeringDigest': hashlib.sha256(self.proof.encode()).hexdigest()}

    def check(self, body=None, validator=None, actor='synthetic-admin', access='grant:1'):
        return self.registry.check(body or self.body, actor, self.authorize, validator or self.validator, access_revision=access)

    def activation(self):
        return {**copy.deepcopy(self.body), 'receipt': self.check()['receipt'], 'clientRequestId': str(uuid4())}

    def activate(self, body, **options):
        return self.registry.activate(body, options.get('actor', 'synthetic-admin'),
            options.get('authorize', self.authorize), options.get('validator', self.validator),
            access_revision=options.get('access', 'grant:1'))

    def counts(self):
        with self.library.connect() as db:
            return [db.execute('select count(*) from '+table).fetchone()[0] for table in
                ('legacy_scene_registry_entries', 'legacy_scene_registry_requests', 'legacy_scene_registry_audit')]

    def expect(self, code, action):
        with self.assertRaises(PreviewError) as caught: action()
        self.assertEqual(caught.exception.code, code)

    def test_check_is_readonly_and_activation_atomically_registers_default_all_sources_and_gate(self):
        before = self.counts(); checked = self.check()
        self.assertEqual(self.counts(), before); self.assertEqual(self.validator_calls, 2)
        request = {**self.body, 'receipt': checked['receipt'], 'clientRequestId': str(uuid4())}
        result = self.activate(request)
        self.assertTrue(result['legacyReadOnly']); self.assertEqual(result['sourceCount'], 2)
        self.assertEqual(self.counts(), [2, 1, 1])
        with self.library.connect() as db:
            self.expect('LEGACY_MODEL_READ_ONLY', lambda: self.registry.assert_legacy_writable(db))
        default = self.registry.entry({}, 'synthetic-reader', self.authorize)
        uploaded = self.registry.entry({'sourceKind': 'uploaded_version', 'sourceKey': self.legacy['versionId']}, 'synthetic-reader', self.authorize)
        self.assertEqual(default['entry']['sceneId'], self.default_scene['sceneId'])
        self.assertEqual(uploaded['entry']['sceneId'], self.upload_scene['sceneId'])
        self.assertTrue(default['available']); self.assertEqual(self.validator_calls, 4)

    def test_no_registration_never_guesses_a_default_scene_and_gate_accepts_pre_registry_store(self):
        self.assertEqual(self.registry.entry({}, 'reader', self.authorize),
            {'migrated': False, 'legacyReadOnly': False, 'available': False, 'entry': None, 'reason': 'NOT_REGISTERED'})
        with sqlite3.connect(':memory:') as db: self.registry.assert_legacy_writable(db)
        with self.library.connect() as db: self.registry.assert_legacy_writable(db)

    def test_sources_must_cover_inventory_and_use_distinct_targets_and_explicit_fixed_default(self):
        for mutate in (lambda b: b['sources'].pop(), lambda b: b.update(defaultSourceKey='a'*64),
                lambda b: b['sources'][1].update(sceneId=b['sources'][0]['sceneId']),
                lambda b: b['sources'][1].update(sourceKey=str(uuid4()))):
            body = copy.deepcopy(self.body); mutate(body)
            with self.assertRaises(PreviewError): self.check(body)
        self.assertEqual(self.counts(), [0, 0, 0])

    def test_actor_access_body_and_foreign_receipt_cannot_activate_another_check(self):
        body = self.activation()
        for options in ({'actor': 'another-admin'}, {'access': 'grant:2'}):
            self.expect('LEGACY_PRECHECK_INVALID', lambda: self.activate(body, **options))
        changed = copy.deepcopy(body); changed['sources'][0]['expectedSourceDigest'] = 'b'*64
        def mismatched(db, sources, default):
            return {'sourceSetDigest': 'b'*64, 'engineeringDigest': 'c'*64}
        self.expect('LEGACY_SOURCE_CHANGED', lambda: self.activate(changed, validator=mismatched))
        changed = copy.deepcopy(body); changed['receipt'] = body['receipt'][:-2]+'AA'
        self.expect('LEGACY_PRECHECK_INVALID', lambda: self.activate(changed))
        self.assertEqual(self.counts(), [0, 0, 0])

    def test_old_source_revision_and_current_proof_change_reject_activation(self):
        body = self.activation(); self.proof = 'changed-proof'
        self.expect('LEGACY_PRECHECK_INVALID', lambda: self.activate(body))
        with self.library.connect() as db:
            db.execute("update bindings set entity_revision='object:2' where version_id=? and entity_uid='CT'", (self.legacy['versionId'],))
            db.execute('update library set revision=revision+1 where id=1')
        self.expect('MODEL_LIBRARY_CHANGED', lambda: self.activate(body))
        self.assertEqual(self.counts(), [0, 0, 0])

    def test_source_digest_change_after_check_is_not_replaced_by_new_callback_facts(self):
        body = self.activation(); self.source_digests[self.fixed_key] = 'a'*64
        self.expect('LEGACY_SOURCE_CHANGED', lambda: self.activate(body))
        self.assertEqual(self.counts(), [0, 0, 0])

    def test_regular_scene_signature_key_cannot_sign_a_registry_activation(self):
        body = self.activation()
        with self.library.connect() as db:
            facts = self.registry._collect(db, self.registry._business(self.body), self.validator)
            context = self.registry._context(self.registry._business(self.body), 'synthetic-admin', 'grant:1', facts)
            body['receipt'] = SceneLibrary._cursor(context, SceneLibrary._catalog(db)[1])
        self.expect('LEGACY_PRECHECK_INVALID', lambda: self.activate(body))

    def test_old_saved_conditions_cannot_be_refreshed_just_by_returning_current_proof(self):
        with self.library.connect() as db:
            db.execute("update bindings set entity_revision='object:2' where version_id=? and entity_uid='CT'", (self.legacy['versionId'],))
        self.expect('LEGACY_TARGET_INVALID', self.check)

    def test_normally_verified_resource_still_needs_exact_identity_for_legacy_registration(self):
        verified = self.models.calibrate({'modelVersionId': self.model['modelVersionId'],
            'expectedContentRevision': self.model['contentRevision'], 'expectedLibraryRevision': self.library.listing()['libraryRevision'],
            'clientRequestId': str(uuid4()), 'calibration': {'unit': 'm', 'axes': 'Y_UP_RIGHT_HANDED',
            'basePoint': [1, 0, 0], 'forward': [0, 0, -1]}}, 'synthetic-admin', self.authorize)
        scene = self.new_scene(verified); body = copy.deepcopy(self.body)
        body['expectedLibraryRevision'] = self.library.listing()['libraryRevision']
        body['sources'][0] = self.source('fixed_model', self.fixed_key, scene)
        self.expect('LEGACY_TARGET_INVALID', lambda: self.check(body))

    def test_target_head_change_after_check_is_not_silently_accepted(self):
        body = self.activation(); snapshot = copy.deepcopy(self.default_scene['snapshot']); snapshot['displayName'] = 'Later edit'
        self.save_scene(self.default_scene, snapshot)
        self.expect('SCENE_CHANGED', lambda: self.activate(body))

    def test_target_requires_preserved_coordinates_three_exact_cabinets_and_saved_conditions(self):
        for mutate in (lambda s: s['instances'][0]['placement']['position'].update(xM=1),
                lambda s: s['instances'][0].update(rootBinding=None, componentBindings=[]),
                lambda s: s['instances'][0]['componentBindings'].pop()):
            scene = self.new_scene(self.model); snapshot = copy.deepcopy(scene['snapshot']); mutate(snapshot)
            scene = self.save_scene(scene, snapshot); body = copy.deepcopy(self.body)
            body['sources'][0] = self.source('fixed_model', self.fixed_key, scene)
            self.expect('LEGACY_TARGET_INVALID', lambda: self.check(body))

    def test_withdrawal_at_final_authorization_rolls_back_entries_default_request_and_audit(self):
        body = self.activation(); calls = []
        def authorize():
            calls.append(1)
            if len(calls) == 2: raise PreviewError(403, 'SCENE_WRITE_FORBIDDEN')
        self.expect('SCENE_WRITE_FORBIDDEN', lambda: self.activate(body, authorize=authorize))
        self.assertEqual(self.counts(), [0, 0, 0])
        self.assertFalse(self.registry.entry({}, 'reader', self.authorize)['legacyReadOnly'])

    def test_unknown_result_replays_same_request_after_restart_without_recreating_any_registration(self):
        body = self.activation(); result = self.activate(body); before = self.counts()
        restarted = LegacySceneRegistry(self.library)
        self.assertEqual(restarted.activate(body, 'synthetic-admin', self.authorize, self.validator,
            access_revision='grant:1'), result)
        self.assertEqual(self.counts(), before)
        altered = copy.deepcopy(body); altered['defaultSourceKey'] = 'd'*64
        with self.assertRaises(PreviewError): self.activate(altered)
        changed = copy.deepcopy(body); changed['receipt'] += 'A'
        self.expect('REQUEST_CONFLICT', lambda: self.activate(changed))
        self.allowed = False
        self.expect('SCENE_WRITE_FORBIDDEN', lambda: self.activate(body))

    def test_active_registry_does_not_accept_another_uuid_or_guess_unknown_sources(self):
        body = self.activation(); result = self.activate(body)
        second = {**body, 'clientRequestId': str(uuid4())}
        self.expect('LEGACY_MIGRATION_ALREADY_ACTIVE', lambda: self.activate(second))
        self.proof = 'new-current-proof'
        self.assertEqual(self.activate(body, access='grant:2'), result)
        unknown = self.registry.entry({'sourceKind': 'uploaded_version', 'sourceKey': str(uuid4())}, 'reader', self.authorize)
        self.assertFalse(unknown['migrated']); self.assertIsNone(unknown['entry']); self.assertTrue(unknown['legacyReadOnly'])

    def test_entry_final_revocation_does_not_return_a_private_target(self):
        self.activate(self.activation()); calls = []
        def authorize():
            calls.append(1)
            if len(calls) == 2: raise PreviewError(403, 'SCENE_READ_FORBIDDEN')
        self.expect('SCENE_READ_FORBIDDEN', lambda: self.registry.entry({}, 'reader', authorize))

    def test_entry_follows_same_instance_in_current_head_and_missing_instance_never_picks_another(self):
        self.activate(self.activation()); snapshot = copy.deepcopy(self.default_scene['snapshot'])
        snapshot['displayName'] = 'Later current head'; updated = self.save_scene(self.default_scene, snapshot)
        entry = self.registry.entry({}, 'reader', self.authorize)['entry']
        self.assertEqual(entry['sceneRevision'], updated['sceneRevision'])
        self.assertEqual(entry['registeredSceneRevision'], self.default_scene['sceneRevision'])
        replacement = copy.deepcopy(snapshot['instances'][0]); replacement['sceneModelInstanceId'] = str(uuid4())
        snapshot['instances'] = [replacement]; self.save_scene(updated, snapshot)
        missing = self.registry.entry({}, 'reader', self.authorize)
        self.assertFalse(missing['available']); self.assertIsNone(missing['entry'])
        self.assertEqual(missing['reason'], 'TARGET_INSTANCE_MISSING')

    def test_same_sha_sources_remain_independent_and_cannot_share_the_default_target(self):
        legacy, model = self.new_model(); self.assertEqual(legacy['sha256'], self.legacy['sha256'])
        scene = self.new_scene(model); body = copy.deepcopy(self.body)
        body['sources'].append(self.source('uploaded_version', legacy['versionId'], scene))
        body['expectedLibraryRevision'] = self.library.listing()['libraryRevision']
        wrong = copy.deepcopy(body)
        wrong['sources'][-1] = self.source('uploaded_version', legacy['versionId'], self.new_scene(self.model))
        self.expect('LEGACY_TARGET_INVALID', lambda: self.check(wrong))
        checked = self.check(body)
        self.activate({**body, 'receipt': checked['receipt'], 'clientRequestId': str(uuid4())})
        first = self.registry.entry({'sourceKind': 'uploaded_version', 'sourceKey': self.legacy['versionId']}, 'reader', self.authorize)
        second = self.registry.entry({'sourceKind': 'uploaded_version', 'sourceKey': legacy['versionId']}, 'reader', self.authorize)
        self.assertNotEqual(first['entry']['sceneId'], second['entry']['sceneId'])
        self.assertEqual(self.counts(), [3, 1, 1])

    def test_callback_cannot_change_proof_between_two_checks_or_write_during_readonly_check(self):
        def changed(db, sources, default):
            value = self.validator(db, sources, default); self.proof += ':changed'; return value
        self.expect('LEGACY_SOURCE_CHANGED', lambda: self.check(validator=changed))
        def writing(db, sources, default):
            db.execute("update library set revision=revision+1 where id=1")
            return self.validator(db, sources, default)
        with self.assertRaises(sqlite3.OperationalError): self.check(validator=writing)
        self.assertEqual(self.counts(), [0, 0, 0])

    def test_old_writer_commits_first_and_activation_rejects_stale_library(self):
        body = self.activation(); locked, release = Event(), Event(); outcomes = []
        def old_writer():
            with self.library.connect() as db:
                db.execute('begin immediate'); self.registry.assert_legacy_writable(db)
                db.execute('update library set revision=revision+1 where id=1'); locked.set(); release.wait(2)
        thread = Thread(target=old_writer); thread.start(); self.assertTrue(locked.wait(2))
        def activate():
            try: self.activate(body); outcomes.append('activated')
            except PreviewError as error: outcomes.append(error.code)
        other = Thread(target=activate); other.start(); release.set(); thread.join(3); other.join(3)
        self.assertEqual(outcomes, ['MODEL_LIBRARY_CHANGED']); self.assertEqual(self.counts(), [0, 0, 0])

    def test_activation_commits_first_and_inflight_old_writer_checks_gate_under_its_write_lock(self):
        body = self.activation(); entered, release = Event(), Event(); outcomes = []; calls = []
        def held(db, sources, default):
            value = self.validator(db, sources, default); calls.append(1)
            if len(calls) == 1: entered.set(); release.wait(2)
            return value
        def activate():
            try: self.activate(body, validator=held); outcomes.append('activated')
            except Exception as error: outcomes.append(type(error).__name__)
        thread = Thread(target=activate); thread.start(); self.assertTrue(entered.wait(2))
        def old_writer():
            try:
                with self.library.connect() as db:
                    db.execute('begin immediate'); self.registry.assert_legacy_writable(db)
                    db.execute('update library set revision=revision+1 where id=1')
                outcomes.append('old-written')
            except PreviewError as error: outcomes.append(error.code)
        other = Thread(target=old_writer); other.start(); release.set(); thread.join(3); other.join(3)
        self.assertCountEqual(outcomes, ['activated', 'LEGACY_MODEL_READ_ONLY'])
        self.assertEqual(self.counts(), [2, 1, 1])

    def test_untrusted_json_unknown_fields_partial_entry_and_oversized_request_are_rejected(self):
        for extra in ({'verified': True}, {'sourceSetDigest': 'a'*64}, {'path': '/private/file'}):
            self.expect('INVALID_REQUEST', lambda: self.check({**self.body, **extra}))
        self.expect('INVALID_REQUEST', lambda: self.registry.entry({'sourceKind': 'fixed_model'}, 'reader', self.authorize))
        self.expect('SCENE_LIMIT_EXCEEDED', lambda: self.check({**self.body, 'huge': 'x'*(1024*1024)}))
        self.expect('INVALID_REQUEST', lambda: self.check({**self.body, 'huge': float('nan')}))


if __name__ == '__main__': unittest.main()
