"""Controlled cutover through real HTTP/SQLite, synthetic current OB authority.

No real account, production source or OntoBase mutation is used. Target scenes
are saved through the real Reader/Validator before the read-only precheck.
"""
import base64
import copy
import hashlib
import json
import struct
from threading import Event, Thread
from unittest.mock import patch
import unittest
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.legacy_scene_registry import LegacySceneRegistry
from apps.api.legacy_scene_sources import LegacySceneSources
from apps.api.model_assets import ModelAsset
from tests import test_legacy_display_http as display
from tests import test_scene_bindings_http as bindings
from tests import test_scene_engineering as engineering


PREFIX = '/api/workbench/scenes/legacy-migration/'


class LegacySceneMigrationHttpTests(unittest.TestCase):
    def setUp(self):
        self.fixture = display.LegacyDisplayHttpTests()
        original = bindings.glb
        def depth_glb(path):
            original(path); raw = path.read_bytes(); path.write_bytes(raw[:-4]+struct.pack('<f', 1)); return path
        with patch.object(bindings, 'glb', side_effect=depth_glb): self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture; self.sessions = f.sessions
        source = f.authority().engineering
        pairs = ((display.CT, 'proxy:CT'), (display.CN1, 'proxy:CN1'), (engineering.CABINET, f.component_key))
        self.bind_requests = []
        for uid, key in pairs:
            body = {'modelVersionId': f.legacy['versionId'], 'entityUid': uid, 'componentKey': key,
                'expectedEntityRevision': source.objects[uid]['entityRevision'], 'expectedHierarchyRevision': engineering.CTX+':7',
                'expectedModelRevision': self.sessions.library.version(f.legacy['versionId'])['modelRevision'],
                'clientRequestId': str(uuid4())}
            self.sessions.library.bind(body, 'synthetic-original', lambda: None); self.bind_requests.append(body)
        root = f.root/'fixed'; root.mkdir(); (root/'model.glb').write_bytes(f.data)
        parts = {part['componentKey']: part for part in f.preserved['components']}
        (root/'model.json').write_text(json.dumps({'schemaVersion': 1, 'projectCode': engineering.PROJECT,
            'installationContextId': engineering.CTX, 'rootEntityUid': engineering.ROOT, 'sha256': f.legacy['sha256'],
            'licenceBasis': 'Synthetic source declaration', 'bindings': [{'entityUid': uid,
                'entityRevision': source.objects[uid]['entityRevision'], 'componentKey': role,
                'geometryQuality': parts[key]['geometryQuality'], 'bounds': parts[key]['bounds']}
                for role, (uid, key) in zip(('CT', 'CN1', 'CN'), pairs)]}))
        self.sessions.model = ModelAsset(root, engineering.PROJECT, engineering.CTX)
        self.default_scene, self.upload_scene = self.new_scene(), self.new_scene()
        status, self.inventory, _ = self.req('sources')
        self.assertEqual(status, 200, self.inventory)
        self.body = {'expectedLibraryRevision': self.inventory['libraryRevision'],
            'defaultSourceKey': self.inventory['defaultSourceKey'], 'sources': [
                {**{key: value for key, value in item.items() if key != 'sourceDigest'},
                    'expectedSourceDigest': item['sourceDigest'], 'sceneId': scene['sceneId'],
                    'expectedSceneRevision': scene['sceneRevision'],
                    'sceneModelInstanceId': scene['snapshot']['instances'][0]['sceneModelInstanceId']}
                for item, scene in zip(self.inventory['items'], (self.default_scene, self.upload_scene))]}

    def req(self, action, body=None, **options):
        return self.fixture.request(PREFIX+action, body or {}, **options)

    def new_scene(self):
        scene = self.fixture.three_cabinets(); snapshot = copy.deepcopy(scene['snapshot'])
        snapshot['instances'][0]['placement'] = {'position': {'mode': 'local', 'xM': 0, 'zM': 0},
            'height': {'mode': 'local_relative', 'relativeHeightM': 0}, 'headingDeg': 0}
        return self.fixture.saved(scene, snapshot)

    def checked(self):
        status, value, _ = self.req('check', self.body)
        self.assertEqual(status, 200, value)
        return {**copy.deepcopy(self.body), 'receipt': value['receipt'], 'clientRequestId': str(uuid4())}

    def activate(self):
        body = self.checked(); status, value, _ = self.req('activate', body)
        self.assertEqual(status, 200, value); return body, value

    def counts(self):
        with self.sessions.library.connect() as db:
            return {table: db.execute('select count(*) from '+table).fetchone()[0] for table in
                ('legacy_scene_registry_entries', 'legacy_scene_registry_requests', 'legacy_scene_registry_audit',
                 'scene_revisions', 'audit', 'versions', 'bindings')}

    def expect(self, response, status, code):
        self.assertEqual(response[0], status, response[1]); self.assertEqual(response[1], {'code': code})

    def test_check_readonly_activate_and_member_entry_keep_distinct_fixed_and_uploaded_targets(self):
        before = self.counts(); body = self.checked(); self.assertEqual(self.counts(), before)
        status, activated, _ = self.req('activate', body)
        self.assertEqual(status, 200, activated); self.assertTrue(activated['legacyReadOnly'])
        reader = self.fixture.login('synthetic-reader'); self.fixture.authority(reader).role = 'reader'
        self.fixture.authority(reader).engineering = self.fixture.authority().engineering
        for source in self.body['sources']:
            response = self.req('entry', {key: source[key] for key in ('sourceKind', 'sourceKey')}, client=reader)
            self.assertEqual(response[0], 200, response[1]); self.assertTrue(response[1]['available'])
            self.assertEqual(response[1]['entry']['sceneId'], source['sceneId'])
        default = self.req('entry', client=reader)[1]
        self.assertEqual(default['entry']['sceneId'], self.default_scene['sceneId'])
        self.assertNotIn('entityUid', json.dumps(default)); self.assertNotIn(str(self.fixture.root), json.dumps(default))
        after = self.counts(); self.assertEqual(after['scene_revisions'], before['scene_revisions'])
        self.assertEqual((after['legacy_scene_registry_entries'], after['legacy_scene_registry_audit']), (2, 1))

    def test_admin_current_grant_origin_body_and_limits_are_enforced_without_default_guessing(self):
        self.expect(self.req('sources', client=False), 401, 'SESSION_EXPIRED')
        reader = self.fixture.login('synthetic-reader'); self.fixture.authority(reader).role = 'reader'
        for action in ('sources', 'check', 'activate'):
            self.expect(self.req(action, self.body if action != 'sources' else {}, client=reader), 403, 'LEGACY_MIGRATION_FORBIDDEN')
        self.assertEqual(self.req('entry', client=reader)[1]['reason'], 'NOT_REGISTERED')
        self.expect(self.req('sources', {'path': '/private'}), 422, 'INVALID_REQUEST')
        self.expect(self.req('check', {**self.body, 'projectCode': 'other'}), 422, 'INVALID_REQUEST')
        self.expect(self.req('entry', {'sourceKind': 'fixed_model', 'sourceKey': 'bad'}), 422, 'INVALID_REQUEST')
        self.expect(self.req('sources', headers={'Origin': 'https://foreign.invalid'}), 403, 'FORBIDDEN')
        self.expect(self.req('sources', raw=b'{"x":1,"x":2}'), 422, 'INVALID_REQUEST')
        self.expect(self.req('sources', raw=b' '*16385), 413, 'INVALID_REQUEST')
        self.expect(self.req('check', raw=b'{}', headers={'Content-Length': str(1024*1024+1)}), 413, 'SCENE_LIMIT_EXCEEDED')
        self.expect(self.req('check', raw=b'{"x":NaN}'), 422, 'INVALID_REQUEST')
        self.expect(self.req('check', raw=b' '*16385), 422, 'INVALID_REQUEST')

    def test_old_revision_and_forged_receipt_never_register_or_change_saved_targets(self):
        body = self.checked(); before = self.counts()
        self.expect(self.req('activate', {**body, 'receipt': body['receipt']+'A'}), 409, 'LEGACY_PRECHECK_INVALID')
        candidate = copy.deepcopy(self.default_scene['snapshot']); candidate['displayName'] = 'Later edit'
        self.fixture.saved(self.default_scene, candidate)
        self.expect(self.req('activate', body), 409, 'SCENE_CHANGED')
        self.assertEqual(self.counts()['legacy_scene_registry_entries'], before['legacy_scene_registry_entries'])

    def test_old_upload_and_binding_are_stopped_in_store_before_replay_but_project_resources_still_work(self):
        self.activate(); before = self.counts(); f = self.fixture
        for body in (self.bind_requests[0], {**self.bind_requests[0], 'clientRequestId': str(uuid4())}):
            self.expect(f.request('/api/workbench/models/binding', body), 409, 'LEGACY_MODEL_READ_ONLY')
        metadata = {'expectedSessionRevision': f.admin['revision'],
            'expectedLibraryRevision': self.sessions.library.listing()['libraryRevision'], 'clientRequestId': str(uuid4()),
            'displayName': 'Forbidden old upload', 'sourceNote': 'Synthetic old source', 'rightsDeclared': True}
        self.expect(f.request('/api/workbench/models/upload', raw=f.data,
            headers={'Content-Type': 'model/gltf-binary', 'X-Model-Metadata': base64.b64encode(json.dumps(metadata).encode()).decode()}),
            409, 'LEGACY_MODEL_READ_ONLY')
        self.assertEqual(self.counts(), before)
        status, resource, _ = f.upload()
        self.assertEqual(status, 200, resource)
        self.assertFalse(resource['canPlace'])
        self.assertTrue(f.open_ok(self.default_scene)['snapshot']['instances'])

    def test_precheck_source_change_and_current_engineering_change_never_autorefresh(self):
        body = self.checked(); f = self.fixture
        f.authority().engineering.objects[display.CT]['entityRevision'] = 'changed:2'
        self.expect(self.req('activate', body), 409, 'ENGINEERING_CHANGED')
        self.assertEqual(self.counts()['legacy_scene_registry_entries'], 0)

    def test_late_role_withdrawal_rolls_back_registration_and_success_replays_original_uuid(self):
        body = self.checked(); original = self.sessions.legacy_registry._collect; calls = []
        def revoke(*args):
            result = original(*args); calls.append(1)
            if len(calls) == 2: self.fixture.authority().role = 'reader'
            return result
        with patch.object(self.sessions.legacy_registry, '_collect', side_effect=revoke):
            self.expect(self.req('activate', body), 403, 'LEGACY_MIGRATION_FORBIDDEN')
        self.assertEqual(self.counts()['legacy_scene_registry_entries'], 0)
        self.fixture.authority().role = 'admin'
        status, result, _ = self.req('activate', body); self.assertEqual(status, 200, result)
        before = self.counts(); status, replay, _ = self.req('activate', body)
        self.assertEqual(status, 200, replay); self.assertEqual(replay['activationId'], result['activationId'])
        self.assertEqual(self.counts(), before)
        self.fixture.authority().allowed = False
        self.expect(self.req('activate', body), 403, 'FORBIDDEN')

    def test_current_registered_instance_removal_returns_unavailable_without_searching_another_scene(self):
        self.activate(); f = self.fixture
        candidate = copy.deepcopy(self.default_scene['snapshot']); candidate['instances'] = []
        f.saved(self.default_scene, candidate)
        response = self.req('entry')[1]
        self.assertTrue(response['migrated']); self.assertFalse(response['available'])
        self.assertIsNone(response['entry']); self.assertEqual(response['reason'], 'TARGET_INSTANCE_MISSING')

    def test_logout_during_upstream_read_clears_result_and_never_registers(self):
        body = self.checked(); f = self.fixture; authority = f.authority()
        def expire(_source, method, path, _body):
            if '/ancestors?' in path:
                authority.engineering.after = None
                self.sessions.logout(f.admin['cookie'].split('=', 1)[1], f.admin['revision'])
        authority.engineering.after = expire
        self.expect(self.req('activate', body), 401, 'SESSION_EXPIRED')
        self.assertEqual(self.counts()['legacy_scene_registry_entries'], 0)

    def test_direct_upstream_401_invalidates_current_session_instead_of_leaving_private_read_access(self):
        authority = self.fixture.authority(); request = authority.engineering.request
        def expired(method, path, body=None):
            if '/ancestors?' in path: raise PreviewError(401, 'SESSION_EXPIRED')
            return request(method, path, body)
        with patch.object(authority.engineering, 'request', side_effect=expired):
            self.expect(self.req('check', self.body), 401, 'SESSION_EXPIRED')
        self.expect(self.req('entry'), 401, 'SESSION_EXPIRED')
        self.assertEqual(self.counts()['legacy_scene_registry_entries'], 0)

    def test_activation_write_lock_wins_against_already_started_legacy_replay_without_session_blocking(self):
        body = self.checked(); entered, release, writer_started = Event(), Event(), Event()
        original = LegacySceneSources.__call__; results = {}
        def paused(instance, *args):
            if not entered.is_set():
                entered.set()
                if not release.wait(3): raise AssertionError('Controlled activation release timed out')
            return original(instance, *args)
        def activate(): results['activation'] = self.req('activate', body)
        def bind():
            writer_started.set()
            try: self.sessions.library.bind(self.bind_requests[0], 'synthetic-original', lambda: None)
            except PreviewError as error: results['old'] = error.code
        with patch.object(LegacySceneSources, '__call__', paused):
            activating = Thread(target=activate); activating.start()
            try:
                self.assertTrue(entered.wait(3))
                writing = Thread(target=bind); writing.start(); self.assertTrue(writer_started.wait(1))
                # A concurrent read of another session remains usable while the
                # registry holds SQLite's writer, with no service mutex held.
                member = self.fixture.login('synthetic-other-reader'); self.fixture.authority(member).role = 'reader'
                self.assertEqual(self.req('entry', client=member)[0], 200)
            finally:
                release.set(); activating.join(5)
                if 'writing' in locals(): writing.join(5)
        self.assertFalse(activating.is_alive()); self.assertFalse(writing.is_alive())
        self.assertEqual(results['activation'][0], 200, results)
        self.assertEqual(results['old'], 'LEGACY_MODEL_READ_ONLY')

    def test_legacy_write_lock_wins_then_prechecked_activation_rejects_changed_source(self):
        body = self.checked(); entered, release = Event(), Event(); results = {}
        old = {**self.bind_requests[0], 'expectedModelRevision': self.sessions.library.version(
            self.fixture.legacy['versionId'])['modelRevision'], 'clientRequestId': str(uuid4())}
        def pause():
            entered.set()
            if not release.wait(3): raise AssertionError('Controlled old-write release timed out')
        def write():
            self.sessions.library.bind(old, 'synthetic-original', pause); results['old'] = 'committed'
        def activate(): results['activation'] = self.req('activate', body)
        writing = Thread(target=write); writing.start()
        try:
            self.assertTrue(entered.wait(2)); activating = Thread(target=activate); activating.start()
        finally:
            release.set(); writing.join(5)
            if 'activating' in locals(): activating.join(5)
        self.assertFalse(writing.is_alive()); self.assertFalse(activating.is_alive())
        self.assertEqual(results['old'], 'committed')
        self.expect(results['activation'], 409, 'MODEL_LIBRARY_CHANGED')
        self.assertEqual(self.counts()['legacy_scene_registry_entries'], 0)

    def test_final_authorization_file_change_cannot_return_receipt_or_commit_registration(self):
        f = self.fixture; authority = f.authority()
        paths = (self.sessions.model.root/'model.glb',
                 self.sessions.library.root/'files'/(f.preserved['modelVersionId']+'.glb'))
        for action in ('check', 'activate'):
            for path in paths:
                with self.subTest(action=action, file=path.name):
                    body = self.checked() if action == 'activate' else copy.deepcopy(self.body)
                    raw = path.read_bytes(); armed = []; calls = []
                    collect = self.sessions.legacy_registry._collect; request = authority.request
                    def collected(*args):
                        value = collect(*args); calls.append(1)
                        if len(calls) == 2: armed.append(True)
                        return value
                    def change(method, route, payload=None):
                        value = request(method, route, payload)
                        if armed and route.endswith('/access'):
                            armed.clear(); path.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
                        return value
                    try:
                        with patch.object(self.sessions.legacy_registry, '_collect', side_effect=collected):
                            with patch.object(authority, 'request', side_effect=change):
                                self.expect(self.req(action, body), 409, 'LEGACY_SOURCE_CHANGED')
                    finally: path.write_bytes(raw)
                    self.assertEqual(self.counts()['legacy_scene_registry_entries'], 0)


if __name__ == '__main__': unittest.main()
