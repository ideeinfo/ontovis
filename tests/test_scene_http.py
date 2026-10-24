"""Actual HTTP scene requests with synthetic project authority and private files."""
import copy
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import socket
import tempfile
from threading import Barrier, Event, Thread
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.model_library import ModelLibrary
from apps.api.model_validation import validate
from apps.api.scene_library import MAX_SCENE_BYTES
from apps.api.session_http import handler_type
from apps.api.workbench_server import WorkbenchSessions
from tests.test_model_upload import glb


CONTEXT = '00000000-0000-0000-0000-000000000071'
ORIGIN = 'http://127.0.0.1:4180'


class SceneAuthority:
    def __init__(self, _base):
        self.allowed = True
        self.expired = False
        self.role = 'admin'
        self.grant = 'grant:1'
        self.project = 'fixture-project'
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path))
        if path == '/api/v1/auth/login':
            return {'token': 'synthetic-token', 'user': {'username': body['username']}}
        if self.expired:
            raise PreviewError(401, 'SESSION_EXPIRED')
        if path == '/api/v1/auth/me':
            return {'user': {'username': self.username, 'is_active': True}}
        if not self.allowed:
            raise PreviewError(403, 'FORBIDDEN')
        if path.endswith('/access'):
            return {'projectCode': self.project, 'role': self.role, 'accessRevision': self.grant,
                    'capabilities': ['objects.read', 'objects.resolve', 'installations.read', 'hierarchy.read']}
        raise AssertionError('Scene requests must not call default installation or arbitrary upstream routes')


class SceneHttpTests(unittest.TestCase):
    def test_organization_uses_existing_http_permission_revision_and_roundtrip_boundaries(self):
        from tests.test_scene_organization import organization
        scene = self.create(); body = self.save_body(scene, [self.item(), self.item()])
        body['snapshot']['organization'] = organization(
            [item['sceneModelInstanceId'] for item in body['snapshot']['instances']], self.version['versionId'])
        status, saved, _ = self.save(body)
        self.assertEqual(status, 200, saved)
        self.assertEqual(self.open(scene)[1]['snapshot'], body['snapshot'])
        self.assertNotIn('organization', self.open(scene, scene['sceneRevision'])[1]['snapshot'])
        member = self.login('fixture-reader'); self.account(member).role = 'reader'
        self.assertEqual(self.open(scene, client=member)[1]['snapshot'], body['snapshot'])
        opened = self.open(scene)[1]
        denied = self.save_body(opened); denied['snapshot']['organization']['routes'][0]['displayName'] = 'Denied'
        self.assert_response(self.save(denied, client=member), 403, 'SCENE_WRITE_FORBIDDEN')
        invalid = self.save_body(opened); invalid['snapshot']['organization']['groups'][0]['instanceIds'][0] = str(uuid4())
        self.assert_response(self.save(invalid), 422, 'INVALID_SCENE_ORGANIZATION')
        self.assertEqual(self.open(scene)[1]['sceneRevision'], saved['sceneRevision'])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sessions = WorkbenchSessions('http://127.0.0.1:1234', 'fixture-project', CONTEXT,
            library_root=self.root / 'library', factory=SceneAuthority)
        self.library = self.sessions.library
        source = glb(self.root / 'fixture.glb')
        metadata = {'expectedSessionRevision': 'not-used-by-storage',
                    'expectedLibraryRevision': self.library.listing()['libraryRevision'],
                    'clientRequestId': str(uuid4()), 'displayName': 'Synthetic resource',
                    'sourceNote': 'Synthetic test geometry only.', 'rightsDeclared': True}
        self.version = self.library.save_upload(source, metadata, 'fixture-admin', validate(source), lambda: None)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler_type(self.sessions, ORIGIN, development=True))
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.thread.join)
        self.addCleanup(self.server.shutdown)
        self.admin = self.login('fixture-admin')

    def request(self, path, body=None, *, client=None, raw=None, headers=None, method='POST'):
        client = self.admin if client is None else client
        actual = {'Host': '127.0.0.1:4180', 'Origin': ORIGIN}
        if client:
            actual['Cookie'] = client['cookie']
        if method == 'POST':
            actual['Content-Type'] = 'application/json'
            if raw is None:
                raw = json.dumps({**({'expectedSessionRevision': client['revision']} if client else {}),
                                  **(body or {})}, ensure_ascii=False).encode()
        for key, value in (headers or {}).items():
            if value is None:
                actual.pop(key, None)
            else:
                actual[key] = value
        connection = HTTPConnection(*self.server.server_address, timeout=5)
        try:
            connection.request(method, path, raw, actual)
            response = connection.getresponse()
            return response.status, json.loads(response.read()), dict(response.getheaders())
        finally:
            connection.close()

    def login(self, username):
        status, bootstrap, headers = self.request('/api/session', client=False, method='GET')
        self.assertEqual(status, 200)
        cookie = headers['Set-Cookie'].split(';', 1)[0]
        status, view, headers = self.request('/api/session/login', client=False,
            body={'username': username, 'password': 'synthetic-password',
                  'expectedSessionRevision': bootstrap['sessionRevision']}, headers={'Cookie': cookie})
        self.assertEqual(status, 200)
        return {'cookie': headers['Set-Cookie'].split(';', 1)[0], 'revision': view['sessionRevision']}

    def account(self, client=None):
        cookie = (client or self.admin)['cookie']
        return self.sessions.rows[cookie.split('=', 1)[1]].authority

    def create(self, name='合成设备区', client=None, request_id=None):
        status, scene, _ = self.request('/api/workbench/scenes/create',
            {'displayName': name, 'clientRequestId': request_id or str(uuid4())}, client=client)
        self.assertEqual(status, 200, scene)
        return scene

    def item(self):
        return {'sceneModelInstanceId': str(uuid4()), 'displayName': '合成模型实例',
                'modelVersionId': self.version['versionId'],
                'placement': {'position': {'mode': 'local', 'xM': 10, 'zM': 20},
                              'height': {'mode': 'local_relative', 'relativeHeightM': 0}, 'headingDeg': 30},
                'visible': True, 'positionLocked': False, 'rootBinding': None, 'componentBindings': []}

    def save_body(self, scene, items=None):
        snapshot = copy.deepcopy(scene['snapshot'])
        if items is not None:
            snapshot['instances'] = items
        return {'sceneId': scene['sceneId'], 'expectedSceneRevision': scene['sceneRevision'],
                'clientRequestId': str(uuid4()), 'snapshot': snapshot,
                'reviewedEngineering': [], 'rootBindingChanges': []}

    def save(self, body, **options):
        return self.request('/api/workbench/scenes/save', body, **options)

    def open(self, scene, revision=None, **options):
        body = {'sceneId': scene['sceneId']}
        if revision is not None:
            body['sceneRevision'] = revision
        return self.request('/api/workbench/scenes/open', body, **options)

    def assert_response(self, response, status, code):
        self.assertEqual(response[0], status, response[1])
        self.assertEqual(response[1], {'code': code})

    def test_anonymous_requests_never_return_private_scene_data(self):
        self.create()
        for suffix, body in [('', {}), ('/create', {'displayName': 'Denied', 'clientRequestId': str(uuid4())}),
                             ('/open', {'sceneId': str(uuid4())})]:
            self.assert_response(self.request('/api/workbench/scenes' + suffix, body, client=False), 401, 'SESSION_EXPIRED')

    def test_real_http_create_save_open_and_fixed_old_revision(self):
        scene = self.create()
        status, saved, _ = self.save(self.save_body(scene, [self.item(), self.item()]))
        self.assertEqual(status, 200, saved)
        status, current, headers = self.open(scene)
        self.assertEqual(status, 200, current)
        self.assertEqual(current['sceneRevision'], saved['sceneRevision'])
        self.assertEqual(len(current['snapshot']['instances']), 2)
        self.assertEqual(current['resourceRefs'][0]['sha256'], self.version['sha256'])
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(current['sessionRevision'], self.admin['revision'])
        old = self.open(scene, scene['sceneRevision'])[1]
        self.assertEqual(old['snapshot']['instances'], [])
        head = self.request('/api/workbench/scenes/head',
            {'sceneId': scene['sceneId'], 'viewingRevision': scene['sceneRevision']})
        self.assertTrue(head[1]['updateAvailable'])

    def test_response_reports_actual_scope_and_limits_without_default_model(self):
        self.assertIsNone(self.sessions.model)
        status, listed, _ = self.request('/api/workbench/scenes')
        self.assertEqual(status, 200)
        self.assertEqual(listed['capabilities']['scope'], 'project_scenes')
        self.assertTrue(listed['capabilities']['supportsEngineeringBindings'])
        self.assertTrue(listed['capabilities']['localPlaneUnbound'])
        self.assertTrue(listed['capabilities']['canWrite'])
        self.assertTrue(listed['capabilities']['existingUploadedModelVersionsOnly'])
        self.assertEqual(listed['limits']['maxSaveJsonBytes'], MAX_SCENE_BYTES)
        self.assertEqual(listed['limits']['maxReadJsonBytes'], 16384)
        self.assertEqual(listed['limits']['maxInstances'], 100)
        self.assertEqual(listed['limits']['maxComponentBindings'], 1000)
        self.create()
        self.assertFalse(any('/installations/' in path for _, path in self.account().calls))

    def test_project_member_reads_but_cannot_create_or_save(self):
        scene = self.create()
        member = self.login('fixture-reader')
        self.account(member).role = 'reader'
        status, listed, _ = self.request('/api/workbench/scenes', client=member)
        self.assertEqual(status, 200)
        self.assertFalse(listed['capabilities']['canWrite'])
        self.assertEqual(self.open(scene, client=member)[0], 200)
        self.assert_response(self.request('/api/workbench/scenes/create',
            {'displayName': 'Denied', 'clientRequestId': str(uuid4())}, client=member), 403, 'SCENE_WRITE_FORBIDDEN')
        self.assert_response(self.save(self.save_body(scene), client=member), 403, 'SCENE_WRITE_FORBIDDEN')

    def test_actor_is_session_identity_and_client_cannot_choose_project_or_context(self):
        for field in ({'projectCode': 'foreign'}, {'actor': 'another-admin'}, {'installationContextId': CONTEXT},
                      {'url': 'https://untrusted.invalid'}, {'path': '/private/model.glb'}):
            self.assert_response(self.request('/api/workbench/scenes', field), 422, 'INVALID_REQUEST')
        self.create()
        with self.library.connect() as db:
            self.assertEqual(db.execute('select distinct actor from scene_audit').fetchone()[0], 'fixture-admin')

    def test_membership_loss_and_wrong_project_never_return_a_scene(self):
        scene = self.create()
        self.account().allowed = False
        self.assert_response(self.open(scene), 403, 'FORBIDDEN')
        self.account().allowed = True
        self.account().project = 'foreign-project'
        self.assert_response(self.open(scene), 403, 'FORBIDDEN')

    def test_role_loss_during_private_resource_check_rolls_back_save(self):
        scene = self.create()
        original = self.library.content

        def revoked(version):
            value = original(version)
            self.account().role = 'reader'
            return value

        with patch.object(self.library, 'content', side_effect=revoked):
            self.assert_response(self.save(self.save_body(scene, [self.item()])), 403, 'SCENE_WRITE_FORBIDDEN')
        self.assertEqual(self.open(scene)[1]['sceneRevision'], scene['sceneRevision'])
        with self.library.connect() as db:
            self.assertEqual(db.execute('select count(*) from scene_audit').fetchone()[0], 1)

    def test_access_revision_change_during_resource_check_rolls_back_save(self):
        scene = self.create()
        original = self.library.content

        def changed(version):
            value = original(version)
            self.account().grant = 'grant:2'
            return value

        with patch.object(self.library, 'content', side_effect=changed):
            self.assert_response(self.save(self.save_body(scene, [self.item()])), 409, 'ACCESS_CHANGED')
        self.assertEqual(self.open(scene)[1]['sceneRevision'], scene['sceneRevision'])

    def test_two_http_writers_refuse_old_head_and_same_request_replays_once(self):
        scene = self.create()
        body = self.save_body(scene, [self.item()])
        first = self.save(body)
        self.assertEqual(first[0], 200, first[1])
        self.assertEqual(self.save(body)[1], first[1])
        self.assert_response(self.save(self.save_body(scene, [self.item()])), 409, 'SCENE_CHANGED')
        conflict = copy.deepcopy(body)
        conflict['snapshot']['displayName'] = 'Different'
        self.assert_response(self.save(conflict), 409, 'REQUEST_CONFLICT')
        with self.library.connect() as db:
            self.assertEqual(db.execute('select count(*) from scene_revisions').fetchone()[0], 2)

    def test_new_session_replay_preserves_actor_idempotency_without_old_transport_revision(self):
        scene = self.create()
        body = self.save_body(scene, [self.item()])
        first = self.save(body)
        another_session = self.login('fixture-admin')
        self.assertNotEqual(another_session['revision'], self.admin['revision'])
        replay = self.save(body, client=another_session)
        self.assertEqual(replay[0], 200, replay[1])
        self.assertEqual(replay[1]['sceneRevision'], first[1]['sceneRevision'])
        self.assertEqual(replay[1]['sessionRevision'], another_session['revision'])
        with self.library.connect() as db:
            self.assertEqual(db.execute('select count(*) from scene_revisions').fetchone()[0], 2)

    def test_simultaneous_http_writers_commit_only_one_saved_head(self):
        scene = self.create()
        barrier, results = Barrier(2), []

        def write():
            body = self.save_body(scene, [self.item()])
            barrier.wait()
            results.append(self.save(body))

        workers = [Thread(target=write), Thread(target=write)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(5)
        self.assertCountEqual([response[0] for response in results], [200, 409])
        self.assertEqual(next(response for response in results if response[0] == 409)[1]['code'], 'SCENE_CHANGED')

    def test_foreign_project_model_version_is_not_available_to_this_scene(self):
        foreign = ModelLibrary(self.root / 'foreign-library', 'foreign-project', str(uuid4()))
        source = glb(self.root / 'foreign.glb')
        metadata = {'expectedSessionRevision': 'not-used',
            'expectedLibraryRevision': foreign.listing()['libraryRevision'], 'clientRequestId': str(uuid4()),
            'displayName': 'Foreign synthetic resource', 'sourceNote': 'Synthetic only.', 'rightsDeclared': True}
        version = foreign.save_upload(source, metadata, 'foreign-admin', validate(source), lambda: None)
        scene, item = self.create(), self.item()
        item['modelVersionId'] = version['versionId']
        self.assert_response(self.save(self.save_body(scene, [item])), 404, 'NOT_FOUND_OR_FORBIDDEN')

    def test_private_file_tampering_is_refused_and_old_binding_revision_is_independent(self):
        scene = self.create()
        self.assertEqual(self.save(self.save_body(scene, [self.item()]))[0], 200)
        fixed = self.open(scene)[1]
        self.library.bind({'modelVersionId': self.version['versionId'], 'componentKey': 'component:0',
            'entityUid': 'synthetic-cabinet', 'expectedEntityRevision': 'entity:1',
            'expectedHierarchyRevision': 'hierarchy:1', 'expectedModelRevision': 1,
            'clientRequestId': str(uuid4())}, 'fixture-admin', lambda: None)
        current = self.open(scene)
        self.assertEqual(current[0], 200, current[1])
        self.assertEqual(current[1]['sceneRevision'], fixed['sceneRevision'])
        self.assertEqual(current[1]['resourceRefs'], fixed['resourceRefs'])
        (self.library.root / 'files' / (self.version['versionId'] + '.glb')).write_bytes(b'changed')
        self.assert_response(self.open(scene), 409, 'RESOURCE_CHANGED')

    def test_unconfigured_geography_and_malformed_engineering_are_refused(self):
        scene = self.create()
        for change, code in [(lambda value: value['snapshot'].update(coordinateFrame={'mode': 'projected_site'}), 'SCENE_SCOPE_UNSUPPORTED'),
                       (lambda value: value['snapshot'].update(terrain={'terrainVersionId': str(uuid4())}), 'SCENE_SCOPE_UNSUPPORTED'),
                       (lambda value: value['snapshot']['instances'][0].update(rootBinding={'objectRef': {'entityUid': 'fake'}}), 'INVALID_REQUEST')]:
            request = self.save_body(scene, [self.item()])
            change(request)
            self.assert_response(self.save(request), 422, code)
        self.assertEqual(self.open(scene)[1]['snapshot']['instances'], [])

    def test_save_accepts_over_16k_within_actual_budget_but_other_routes_do_not(self):
        scene = self.create()
        body = self.save_body(scene, [self.item() for _ in range(100)])
        self.assertGreater(len(json.dumps(body)), 16384)
        self.assertEqual(self.save(body)[0], 200)
        self.assert_response(self.request('/api/workbench/scenes', raw=b'{}',
            headers={'Content-Length': '16385'}), 413, 'INVALID_REQUEST')
        self.assert_response(self.save({}, raw=b'{}', headers={'Content-Length': str(MAX_SCENE_BYTES + 1)}),
                             413, 'SCENE_LIMIT_EXCEEDED')
        self.assert_response(self.request('/api/workbench/catalog', raw=b'{}',
            headers={'Content-Length': '16385'}), 413, 'INVALID_REQUEST')

    def test_duplicate_json_keys_nonfinite_values_and_invalid_session_are_refused(self):
        for tail in ['"q":"a","q":"b"', '"q":NaN', '"q":1e9999']:
            raw = ('{"expectedSessionRevision":' + json.dumps(self.admin['revision']) + ',' + tail + '}').encode()
            self.assert_response(self.request('/api/workbench/scenes', raw=raw), 422, 'INVALID_REQUEST')
        self.assert_response(self.request('/api/workbench/scenes', {'expectedSessionRevision': 'stale'}),
                             409, 'SESSION_CHANGED')

    def test_origin_host_and_unlisted_routes_remain_closed(self):
        for changes in ({'Origin': 'https://foreign.invalid'}, {'Origin': None}, {'Host': 'foreign.invalid'},
                        {'Sec-Fetch-Site': 'cross-site'}):
            self.assert_response(self.request('/api/workbench/scenes', headers=changes), 403, 'FORBIDDEN')
        for path in ('/api/workbench/scenes/delete', '/api/workbench/scenes?project=other'):
            self.assert_response(self.request(path), 404, 'NOT_FOUND')
        self.assert_response(self.request('/api/workbench/scenes/locate'), 422, 'INVALID_REQUEST')

    def test_duplicate_transport_headers_are_rejected_before_reading_body(self):
        for duplicates, expected in [([('Content-Length', '2'), ('Content-Length', '2')], 422),
                                     ([('Origin', ORIGIN), ('Origin', ORIGIN)], 403),
                                     ([('Host', '127.0.0.1:4180'), ('Host', '127.0.0.1:4180')], 403)]:
            connection = HTTPConnection(*self.server.server_address, timeout=5)
            try:
                connection.putrequest('POST', '/api/workbench/scenes', skip_host=True)
                values = [('Host', '127.0.0.1:4180'), ('Origin', ORIGIN), ('Content-Length', '2')]
                names = {name for name, _ in duplicates}
                for name, value in values:
                    if name not in names:
                        connection.putheader(name, value)
                for name, value in duplicates:
                    connection.putheader(name, value)
                connection.putheader('Content-Type', 'application/json')
                connection.putheader('Cookie', self.admin['cookie'])
                connection.endheaders(b'{}')
                response = connection.getresponse()
                self.assertEqual(response.status, expected)
                self.assertEqual(json.loads(response.read()), {'code': 'INVALID_REQUEST' if expected == 422 else 'FORBIDDEN'})
            finally:
                connection.close()

    def test_short_json_body_cannot_be_accepted_as_a_complete_declared_request(self):
        raw = json.dumps({'expectedSessionRevision': self.admin['revision']}).encode()
        connection = HTTPConnection(*self.server.server_address, timeout=5)
        try:
            connection.request('POST', '/api/workbench/scenes', raw,
                {'Host': '127.0.0.1:4180', 'Origin': ORIGIN, 'Content-Type': 'application/json',
                 'Cookie': self.admin['cookie'], 'Content-Length': str(len(raw) + 10)})
            connection.sock.shutdown(socket.SHUT_WR)
            response = connection.getresponse()
            self.assertEqual(response.status, 422)
            self.assertEqual(json.loads(response.read()), {'code': 'INVALID_REQUEST'})
        finally:
            connection.close()

    def test_logout_during_resource_read_discards_late_private_response(self):
        scene = self.create()
        self.assertEqual(self.save(self.save_body(scene, [self.item()]))[0], 200)
        started, release, result = Event(), Event(), []
        original = self.library.content

        def blocked(version):
            value = original(version)
            started.set()
            release.wait(3)
            return value

        with patch.object(self.library, 'content', side_effect=blocked):
            worker = Thread(target=lambda: result.append(self.open(scene)))
            worker.start()
            self.assertTrue(started.wait(2))
            self.assertEqual(self.request('/api/session/logout')[0], 200)
            release.set()
            worker.join(5)
        self.assertEqual(len(result), 1)
        self.assert_response(result[0], 401, 'SESSION_EXPIRED')

    def test_membership_revocation_after_file_read_discards_late_scene_contents(self):
        scene = self.create()
        self.assertEqual(self.save(self.save_body(scene, [self.item()]))[0], 200)
        original = self.library.content

        def revoked(version):
            value = original(version)
            self.account().allowed = False
            return value

        with patch.object(self.library, 'content', side_effect=revoked):
            self.assert_response(self.open(scene), 403, 'FORBIDDEN')

    def test_upstream_expiry_invalidates_session_and_failure_is_not_empty_success(self):
        self.account().expired = True
        self.assert_response(self.request('/api/workbench/scenes'), 401, 'SESSION_EXPIRED')
        self.assertNotIn(self.admin['cookie'].split('=', 1)[1], self.sessions.rows)

    def test_upstream_outage_is_a_failure_not_an_empty_scene_list(self):
        with patch.object(self.account(), 'request', side_effect=PreviewError(502, 'SOURCE_UNAVAILABLE')):
            self.assert_response(self.request('/api/workbench/scenes'), 502, 'SOURCE_UNAVAILABLE')


if __name__ == '__main__':
    unittest.main()
