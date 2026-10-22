"""Private terrain HTTP boundary with real SQLite and a controlled worker.

The subprocess emits synthetic terrain; real GIS validation is tested separately.
"""
import base64
import copy
from contextlib import contextmanager
import hashlib
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import socket
import sys
import tempfile
from threading import Event, Thread, current_thread
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.model_assets import ModelAsset
from apps.api.model_validation import validate
from apps.api.session_http import handler_type
from apps.api.terrain_validation import MAX_BYTES
from apps.api.workbench_server import WorkbenchSessions
from tests.test_scene_http import SceneAuthority, CONTEXT, ORIGIN
from tests.test_terrain_library import FAKE_PROCESSOR
from tests.test_model_upload import glb


PREFIX = '/api/workbench/terrains/'


class TerrainHttpTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.executable = self.root / 'fake-worker'
        self.executable.write_text('#!' + sys.executable + '\n' + FAKE_PROCESSOR)
        self.executable.chmod(0o700)
        self.control = self.executable.with_suffix('.control')
        self.control.write_text('{}')
        self.sessions = WorkbenchSessions('http://127.0.0.1:1234', 'fixture-project', CONTEXT,
            library_root=self.root / 'library', terrain_python=self.executable, factory=SceneAuthority)
        self.terrains = self.sessions.terrains
        self.addCleanup(self.terrains.close)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler_type(self.sessions, ORIGIN, development=True))
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.thread.join)
        self.addCleanup(self.server.shutdown)
        self.admin = self.login('fixture-admin')
        self.data = b'II*\x00synthetic-geotiff-fixture-only'

    def request(self, path, body=None, *, client=None, raw=None, headers=None, method='POST', binary=False):
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
            data = response.read()
            return response.status, data if binary and response.status == 200 else json.loads(data), dict(response.getheaders())
        finally:
            connection.close()

    def login(self, username):
        status, bootstrap, headers = self.request('/api/session', client=False, method='GET')
        self.assertEqual(status, 200)
        status, view, headers = self.request('/api/session/login', client=False,
            body={'username': username, 'password': 'synthetic-password',
                  'expectedSessionRevision': bootstrap['sessionRevision']},
            headers={'Cookie': headers['Set-Cookie'].split(';', 1)[0]})
        self.assertEqual(status, 200)
        return {'cookie': headers['Set-Cookie'].split(';', 1)[0], 'revision': view['sessionRevision']}

    def account(self, client=None):
        return self.sessions.rows[(client or self.admin)['cookie'].split('=', 1)[1]].authority

    def metadata(self, **changes):
        return {'clientRequestId': str(uuid4()), 'displayName': '合成地形', 'sourceNote': 'Synthetic test fixture',
            'licenseNote': 'Synthetic test fixture', 'rightsDeclared': True, 'verticalDatum': 'EGM2008',
            'heightUnit': 'm', **changes}

    def upload(self, metadata=None, *, client=None, data=None, headers=None):
        client = self.admin if client is None else client
        metadata = dict(self.metadata() if metadata is None else metadata)
        if client:
            metadata.setdefault('expectedSessionRevision', client['revision'])
        encoded = base64.b64encode(json.dumps(metadata, ensure_ascii=False).encode()).decode()
        return self.request(PREFIX + 'upload', raw=self.data if data is None else data, client=client,
            headers={'Content-Type': 'image/tiff', 'X-Terrain-Metadata': encoded, **(headers or {})})

    def job(self, item, client=None):
        return self.request(PREFIX + 'job', {'jobId': item['jobId']}, client=client)

    def wait(self, item):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            status, value, _ = self.job(item)
            self.assertEqual(status, 200, value)
            if value['state'] in ('ready', 'failed', 'cancelled'):
                return value
            time.sleep(.01)
        self.fail('The controlled HTTP terrain job did not finish')

    def ready(self):
        status, item, _ = self.upload()
        self.assertEqual(status, 202, item)
        done = self.wait(item)
        self.assertEqual(done['state'], 'ready', done)
        status, version, _ = self.request(PREFIX + 'version', {'terrainVersionId': done['terrainVersionId']})
        self.assertEqual(status, 200, version)
        return done, version

    def blocked(self):
        gate, started = self.root / 'release', self.root / 'started'
        self.control.write_text(json.dumps({'gate': str(gate), 'started': str(started)}))
        status, item, _ = self.upload()
        self.assertEqual(status, 202, item)
        deadline = time.monotonic() + 3
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(started.exists())
        return item, gate

    def content(self, version, artifact=None, **options):
        artifact = artifact or version['artifacts'][0]
        return self.request(PREFIX + 'content', {'terrainVersionId': version['terrainVersionId'],
            'artifactId': artifact['artifactId'], 'expectedSha256': artifact['sha256']}, binary=True, **options)

    def test_uploaded_task_and_fixed_private_version_use_real_http_without_default_installation(self):
        item, version = self.ready()
        self.assertIsNone(self.sessions.model)
        self.assertEqual(version['sha256'], hashlib.sha256(self.data).hexdigest())
        self.assertEqual(version['sessionRevision'], self.admin['revision'])
        self.assertTrue(version['capabilities']['sceneTerrainPlacement'])
        self.assertEqual(version['limits']['maxUploadBytes'], MAX_BYTES)
        self.assertNotIn(str(self.root), json.dumps(version))
        self.assertNotIn('actor', item)
        for artifact in version['artifacts']:
            status, data, headers = self.content(version, artifact)
            self.assertEqual(status, 200)
            self.assertEqual(hashlib.sha256(data).hexdigest(), artifact['sha256'])
            self.assertEqual(headers['Content-Type'], 'application/octet-stream')
            self.assertEqual(headers['X-Content-SHA256'], artifact['sha256'])
            self.assertEqual(headers['X-Session-Revision'], self.admin['revision'])
            self.assertEqual(headers['Cache-Control'], 'no-store')
            self.assertNotIn('Content-Disposition', headers)
        self.assertTrue(all(path.endswith('/access') or path.startswith('/api/v1/auth/')
                            for _, path in self.account().calls))

    def test_anonymous_member_and_revoked_membership_have_no_write_bypass(self):
        self.assertEqual(self.upload(client=False)[0], 401)
        member = self.login('fixture-member')
        self.account(member).role = 'member'
        self.assertEqual(self.upload(client=member)[:2], (403, {'code': 'SCENE_WRITE_FORBIDDEN'}))
        item, version = self.ready()
        self.assertEqual(self.job(item, member)[0], 200)
        self.assertEqual(self.content(version, client=member)[0], 200)
        self.assertEqual(self.request(PREFIX + 'job/cancel', {'jobId': item['jobId'],
            'expectedJobRevision': item['jobRevision'], 'clientRequestId': str(uuid4())}, client=member)[0], 403)
        self.account(member).allowed = False
        self.assertEqual(self.job(item, member)[0], 403)
        self.assertEqual(self.content(version, client=member)[0], 403)

    def test_missing_worker_configuration_fails_closed_after_project_permission(self):
        with patch.object(self.sessions, 'terrains', None):
            self.assertEqual(self.upload()[:2], (503, {'code': 'PROCESSING_UNAVAILABLE'}))
            self.assertEqual(self.request(PREFIX + 'job', {'jobId': str(uuid4())})[0], 503)
            self.account().allowed = False
            self.assertEqual(self.upload()[0], 403)
        unconfigured = WorkbenchSessions('http://127.0.0.1:1234', 'fixture-project', CONTEXT,
            library_root=self.root / 'unconfigured', factory=SceneAuthority)
        self.assertIsNone(unconfigured.terrains)
        self.assertFalse((unconfigured.library.root / 'terrains').exists())

    def test_upload_idempotency_is_actor_metadata_and_bytes_scoped(self):
        metadata = self.metadata()
        status, first, _ = self.upload(metadata)
        self.assertEqual(status, 202)
        self.assertEqual(self.upload(metadata)[1]['jobId'], first['jobId'])
        self.assertEqual(self.upload({**metadata, 'displayName': 'changed'})[0], 409)
        self.assertEqual(self.upload(metadata, data=b'x' * len(self.data))[0], 409)
        other = self.login('fixture-other-admin')
        self.assertNotEqual(self.upload(metadata, client=other)[1]['jobId'], first['jobId'])
        with self.sessions.library.connect() as db:
            self.assertEqual(db.execute('select count(*) from terrain_jobs').fetchone()[0], 2)
            self.assertNotIn(self.admin['revision'], str([tuple(row) for row in db.execute('select payload from terrain_jobs')]))

    def test_cancel_requires_expected_revision_and_uuid_request_then_replays(self):
        item, _ = self.blocked()
        current = self.job(item)[1]
        body = {'jobId': item['jobId'], 'expectedJobRevision': 'stale', 'clientRequestId': str(uuid4())}
        self.assertEqual(self.request(PREFIX + 'job/cancel', body)[:2], (409, {'code': 'JOB_CHANGED'}))
        body['expectedJobRevision'] = current['jobRevision']
        body['clientRequestId'] = 'bad-request-id'
        self.assertEqual(self.request(PREFIX + 'job/cancel', body)[0], 422)
        body['clientRequestId'] = str(uuid4())
        result = self.request(PREFIX + 'job/cancel', body)
        self.assertEqual(result[0], 200)
        self.assertEqual(result[1]['state'], 'cancelled')
        self.assertEqual(self.request(PREFIX + 'job/cancel', body)[1]['state'], 'cancelled')
        self.assertEqual(self.request(PREFIX + 'job/cancel', {**body, 'expectedJobRevision': 'different'})[0], 409)

    def test_logout_during_worker_processing_prevents_later_ready_version(self):
        item, gate = self.blocked()
        self.assertEqual(self.request('/api/session/logout')[0], 200)
        gate.write_text('release')
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            value = self.terrains.job(item['jobId'], lambda: None)
            if value['state'] == 'failed': break
            time.sleep(.01)
        self.assertEqual(value['state'], 'failed')
        self.assertEqual(value['errorCode'], 'SESSION_EXPIRED')
        with self.sessions.library.connect() as db:
            self.assertEqual(db.execute('select count(*) from terrain_versions').fetchone()[0], 0)
        self.assertEqual(list((self.terrains.root / 'versions').iterdir()), [])

    def test_role_revocation_during_worker_processing_prevents_ready(self):
        item, gate = self.blocked()
        self.account().role = 'member'
        gate.write_text('release')
        done = self.wait(item)
        self.assertEqual(done['state'], 'failed')
        self.assertEqual(done['errorCode'], 'SCENE_WRITE_FORBIDDEN')

    def test_access_revision_change_during_processing_prevents_ready(self):
        item, gate = self.blocked()
        self.account().grant = 'grant:changed'
        gate.write_text('release')
        done = self.wait(item)
        self.assertEqual(done['state'], 'failed')
        self.assertEqual(done['errorCode'], 'ACCESS_CHANGED')

    def test_late_content_after_logout_is_discarded(self):
        _, version = self.ready()
        original = self.terrains.content
        entered, release = Event(), Event()
        result = []
        def delayed(*args):
            value = original(*args)
            entered.set()
            self.assertTrue(release.wait(3))
            return value
        with patch.object(self.terrains, 'content', side_effect=delayed):
            thread = Thread(target=lambda: result.append(self.content(version)))
            thread.start()
            self.assertTrue(entered.wait(3))
            self.assertEqual(self.request('/api/session/logout')[0], 200)
            release.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result[0][:2], (401, {'code': 'SESSION_EXPIRED'}))

    def test_late_content_after_membership_revocation_is_discarded(self):
        _, version = self.ready()
        original = self.terrains.content
        def revoked(*args):
            value = original(*args)
            self.account().allowed = False
            return value
        with patch.object(self.terrains, 'content', side_effect=revoked):
            self.assertEqual(self.content(version)[:2], (403, {'code': 'FORBIDDEN'}))

    def test_expired_session_invalidates_transport_and_worker_identity(self):
        item, gate = self.blocked()
        self.account().expired = True
        self.assertEqual(self.job(item)[:2], (401, {'code': 'SESSION_EXPIRED'}))
        self.assertNotIn(self.admin['cookie'].split('=', 1)[1], self.sessions.rows)
        gate.write_text('release')
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            state = self.terrains.job(item['jobId'], lambda: None)['state']
            if state == 'failed': break
            time.sleep(.01)
        self.assertEqual(state, 'failed')

    def test_metadata_duplicate_keys_nonfinite_oversize_and_raw_url_fields_are_refused(self):
        base = {**self.metadata(), 'expectedSessionRevision': self.admin['revision']}
        for data in (b'{"displayName":"a","displayName":"b"}',
                     json.dumps(base).replace('"heightUnit": "m"', '"heightUnit": NaN').encode(), b' ' * 6145):
            self.assertEqual(self.upload(headers={'X-Terrain-Metadata': base64.b64encode(data).decode()})[0], 422)
        self.assertEqual(self.upload(headers={'X-Terrain-Metadata': 'invalid+base64!'})[0], 422)
        self.assertEqual(self.upload(headers={'X-Terrain-Metadata': 'a' * 8193})[0], 422)
        for field in ('url', 'path', 'sourcePath', 'projectCode', 'actor'):
            self.assertEqual(self.upload(self.metadata(**{field: 'https://untrusted.invalid/x.tif'}))[0], 422)
        with self.sessions.library.connect() as db:
            self.assertEqual(db.execute('select count(*) from terrain_jobs').fetchone()[0], 0)

    def test_upload_requires_known_length_original_tiff_and_bounded_bytes(self):
        for headers, expected in (({'Content-Type': 'application/octet-stream'}, 415),
                ({'Content-Type': 'image/tiff; charset=utf-8'}, 415),
                ({'Transfer-Encoding': 'chunked'}, 415), ({'Content-Length': '-1'}, 422),
                ({'Content-Length': 'not-a-number'}, 422), ({'Content-Length': str(MAX_BYTES + 1)}, 413)):
            self.assertEqual(self.upload(headers=headers)[0], expected)
        self.assertEqual(self.upload(data=b'short')[0], 413)

    def test_short_declared_terrain_body_leaves_no_job_or_temporary_file(self):
        metadata = {**self.metadata(), 'expectedSessionRevision': self.admin['revision']}
        connection = HTTPConnection(*self.server.server_address, timeout=5)
        try:
            connection.request('POST', PREFIX + 'upload', b'short', {
                'Host': '127.0.0.1:4180', 'Origin': ORIGIN, 'Cookie': self.admin['cookie'],
                'Content-Type': 'image/tiff', 'Content-Length': '30',
                'X-Terrain-Metadata': base64.b64encode(json.dumps(metadata).encode()).decode()})
            connection.sock.shutdown(socket.SHUT_WR)
            response = connection.getresponse()
            self.assertEqual(response.status, 422)
            self.assertEqual(json.loads(response.read()), {'code': 'INVALID_TERRAIN'})
        finally:
            connection.close()
        self.assertEqual(list((self.terrains.root / 'temporary').iterdir()), [])

    def test_duplicate_transport_headers_and_origin_are_rejected(self):
        metadata = base64.b64encode(json.dumps({**self.metadata(),
            'expectedSessionRevision': self.admin['revision']}).encode()).decode()
        base = {'Host': '127.0.0.1:4180', 'Origin': ORIGIN, 'Cookie': self.admin['cookie'],
            'Content-Type': 'image/tiff', 'Content-Length': str(len(self.data)), 'X-Terrain-Metadata': metadata}
        for duplicate in ('Content-Length', 'X-Terrain-Metadata', 'Content-Type', 'Host', 'Origin'):
            connection = HTTPConnection(*self.server.server_address, timeout=5)
            try:
                connection.putrequest('POST', PREFIX + 'upload', skip_host=True)
                for key, value in base.items(): connection.putheader(key, value)
                connection.putheader(duplicate, base[duplicate])
                connection.endheaders(self.data)
                response = connection.getresponse()
                self.assertIn(response.status, (403, 415))
                response.read()
            finally:
                connection.close()
        for headers in ({'Origin': 'https://other.invalid'}, {'Origin': None}, {'Host': 'other.invalid'}, {'Sec-Fetch-Site': 'cross-site'}):
            self.assertEqual(self.upload(headers=headers)[0], 403)

    def test_unknown_read_keys_cross_project_and_path_artifacts_never_read_files(self):
        _, version = self.ready()
        self.assertEqual(self.request(PREFIX + 'version', {'terrainVersionId': str(uuid4())})[0], 404)
        self.assertEqual(self.request(PREFIX + 'version', {'terrainVersionId': version['terrainVersionId'], 'path': '/etc/passwd'})[0], 422)
        for artifact in ('../source.tif', '/etc/passwd', 'https://untrusted.invalid/file', 'report.json'):
            self.assertEqual(self.content(version, {'artifactId': artifact, 'sha256': '0' * 64})[0], 404)
        self.account().project = 'other-project'
        self.assertEqual(self.content(version)[0], 403)
        self.assertEqual(self.upload()[0], 403)

    def test_file_fingerprint_and_report_tampering_are_explicit_errors(self):
        _, version = self.ready()
        artifact = copy.deepcopy(version['artifacts'][0])
        artifact['sha256'] = '0' * 64
        self.assertEqual(self.content(version, artifact)[:2], (409, {'code': 'RESOURCE_CHANGED'}))
        artifact['sha256'] = 'bad'
        self.assertEqual(self.content(version, artifact)[0], 422)
        first = version['artifacts'][0]
        target = self.terrains.root / 'versions' / version['terrainVersionId'] / 'derived' / first['artifactId']
        target.write_bytes(bytes(first['bytes']))
        self.assertEqual(self.content(version, first)[0], 409)
        (target.parent / 'report.json').write_text('{}')
        self.assertEqual(self.request(PREFIX + 'version', {'terrainVersionId': version['terrainVersionId']})[0], 409)

    def test_private_json_limits_duplicate_keys_and_unlisted_routes_remain_closed(self):
        self.assertEqual(self.request(PREFIX + 'job', raw=b' ' * 16385)[0], 413)
        self.assertEqual(self.request(PREFIX + 'job', raw=b'{"jobId":"a","jobId":"b"}')[0], 422)
        self.assertEqual(self.request(PREFIX + 'job', raw=b'{"jobId":NaN}')[0], 422)
        for path, method in ((PREFIX + 'job', 'GET'), (PREFIX + 'unknown', 'POST'),
                (PREFIX + 'upload?url=x', 'POST'), (PREFIX + 'version?path=x', 'POST')):
            self.assertEqual(self.request(path, method=method)[0], 404)
        self.assertEqual(self.request(PREFIX + 'job', {'jobId': str(uuid4()), 'expectedSessionRevision': 'old'})[0], 409)

    def test_validation_failure_is_failed_job_and_never_an_empty_successful_version(self):
        self.control.write_text(json.dumps({'mode': 'fail'}))
        status, item, _ = self.upload()
        self.assertEqual(status, 202)
        done = self.wait(item)
        self.assertEqual(done['state'], 'failed')
        self.assertEqual(done['errorCode'], 'INVALID_TERRAIN')
        self.assertIsNone(done['terrainVersionId'])
        self.assertEqual(self.request(PREFIX + 'version', {'terrainVersionId': None})[0], 422)

    def test_queue_capacity_refuses_before_consuming_more_uploads(self):
        item, gate = self.blocked()
        self.assertEqual(self.upload()[0], 202)
        self.assertEqual(self.upload()[:2], (429, {'code': 'TERRAIN_BUSY'}))
        gate.write_text('release')
        self.assertEqual(self.wait(item)['state'], 'ready')

    def legacy_fixture(self):
        seed = self.root / 'seed'
        seed.mkdir()
        source = glb(seed / 'model.glb')
        seed.joinpath('model.json').write_text(json.dumps({'schemaVersion': 1,
            'projectCode': 'fixture-project', 'installationContextId': CONTEXT, 'rootEntityUid': 'root',
            'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'bindings': [{'entityUid': key, 'entityRevision': 'object:1', 'componentKey': key,
                'geometryQuality': 'source_candidate' if key == 'CN' else 'proxy_schematic',
                'bounds': [[0, 0, 0], [1, 2, 1]]} for key in ('CT', 'CN1', 'CN')]}))
        self.sessions.model = ModelAsset(seed, 'fixture-project', CONTEXT)
        account = self.account()
        original = account.request
        objects = {key: {'entityUid': key, 'entityRevision': 'object:1', 'installationContextId': CONTEXT,
            'objectKind': 'cabinet' if key != 'root' else 'turbine', 'lifecycle': 'active', 'displayName': key}
            for key in ('root', 'CT', 'CN1', 'CN')}
        def request(method, path, body=None):
            if path.endswith('/installations/' + CONTEXT):
                return {'item': {'projectCode': 'fixture-project', 'installationContextId': CONTEXT,
                    'hierarchyRevision': 'hierarchy:1', 'rootEntityUid': 'root',
                    'purpose': 'demonstration', 'engineeringUseAllowed': False}}
            if path.endswith('/objects/resolve'):
                return {'items': [{'resolution': 'exact', 'object': objects[uid]} for uid in body['entityUids']]}
            if '/ancestors?' in path:
                return {'hierarchyRevision': 'hierarchy:1', 'completeness': 'complete',
                    'path': [{'object': objects['root']}]}
            return original(method, path, body)
        account.request = request
        return source

    def test_terrain_commit_and_all_other_writes_share_sqlite_without_blocking_session_reads_or_logout(self):
        source = self.legacy_fixture()
        library = self.sessions.library
        candidate = self.root / 'initial-upload.glb'
        candidate.write_bytes(source.read_bytes())
        model = library.save_upload(candidate, {'expectedSessionRevision': 'not-stored',
            'expectedLibraryRevision': library.listing()['libraryRevision'], 'clientRequestId': str(uuid4()),
            'displayName': 'Synthetic model', 'sourceNote': 'Synthetic fixture', 'rightsDeclared': True},
            'fixture-admin', validate(candidate), lambda: None)
        status, scene, _ = self.request('/api/workbench/scenes/create',
            {'displayName': 'Synthetic scene', 'clientRequestId': str(uuid4())})
        self.assertEqual(status, 200)
        for operation in ('create', 'save', 'upload', 'binding'):
            with self.subTest(operation=operation):
                observer = self.login('fixture-observer-' + operation)
                held, release, waiting = Event(), Event(), Event()
                worker_guards = 0
                original_guard, original_connect = self.sessions.guard, library.connect
                def guard(sid, row):
                    nonlocal worker_guards
                    if current_thread() is self.terrains.thread:
                        worker_guards += 1
                        if worker_guards == 2:
                            # _commit has begun its real write transaction.
                            held.set()
                            if not release.wait(5): raise AssertionError('The HTTP write did not release the commit barrier')
                    return original_guard(sid, row)
                class Connection:
                    def __init__(self, db): self.db = db
                    def __getattr__(self, key): return getattr(self.db, key)
                    def execute(self, sql, *args):
                        if sql.lower().startswith('begin immediate') and current_thread() is not self_outer.terrains.thread:
                            waiting.set()
                        return self.db.execute(sql, *args)
                self_outer = self
                @contextmanager
                def connect():
                    with original_connect() as db:
                        yield Connection(db)
                metadata = {'expectedLibraryRevision': library.listing()['libraryRevision'],
                    'clientRequestId': str(uuid4()), 'displayName': 'Concurrent upload',
                    'sourceNote': 'Synthetic fixture', 'rightsDeclared': True,
                    'expectedSessionRevision': self.admin['revision']}
                binding = {'modelVersionId': model['versionId'], 'entityUid': 'CN', 'componentKey': 'component:2',
                    'expectedEntityRevision': 'object:1', 'expectedHierarchyRevision': 'hierarchy:1',
                    'expectedModelRevision': library.version(model['versionId'])['modelRevision'],
                    'clientRequestId': str(uuid4())}
                results = []
                def write():
                    if operation == 'create':
                        results.append(self.request('/api/workbench/scenes/create',
                            {'displayName': 'Concurrent scene', 'clientRequestId': str(uuid4())}))
                    elif operation == 'save':
                        results.append(self.request('/api/workbench/scenes/save', {'sceneId': scene['sceneId'],
                            'expectedSceneRevision': scene['sceneRevision'], 'clientRequestId': str(uuid4()),
                            'snapshot': scene['snapshot'], 'reviewedEngineering': [], 'rootBindingChanges': []}))
                    elif operation == 'upload':
                        results.append(self.request('/api/workbench/models/upload', raw=source.read_bytes(),
                            headers={'Content-Type': 'model/gltf-binary',
                                'X-Model-Metadata': base64.b64encode(json.dumps(metadata).encode()).decode()}))
                    else:
                        results.append(self.request('/api/workbench/models/binding', binding))
                with patch.object(self.sessions, 'guard', side_effect=guard), patch.object(library, 'connect', side_effect=connect):
                    status, item, _ = self.upload()
                    self.assertEqual(status, 202)
                    self.assertTrue(held.wait(3))
                    waiting.clear()
                    thread = Thread(target=write)
                    thread.start()
                    try:
                        self.assertTrue(waiting.wait(3))
                        started = time.monotonic()
                        self.assertEqual(self.request('/api/session', client=observer, method='GET')[0], 200)
                        self.assertEqual(self.request('/api/session/logout', client=observer)[0], 200)
                        self.assertLess(time.monotonic() - started, 1.5)
                    finally:
                        release.set()
                        thread.join(5)
                    self.assertFalse(thread.is_alive())
                    self.assertEqual(results[0][0], 200, results)
                    self.assertEqual(self.wait(item)['state'], 'ready')


if __name__ == '__main__':
    unittest.main()
