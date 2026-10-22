"""Project resource HTTP with real private GLB/SQLite and synthetic authority."""
import base64
import copy
import hashlib
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
from threading import Event, Thread
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.api.session_http import handler_type
from apps.api.workbench_server import WorkbenchSessions
from apps.api.model_validation import MAX_BYTES
from tests.test_scene_http import SceneAuthority, ORIGIN, CONTEXT
from tests.test_model_upload import glb


class ProjectModelHttpTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.sessions = WorkbenchSessions('http://127.0.0.1:1234', 'fixture-project', CONTEXT,
            library_root=self.root / 'private', factory=SceneAuthority)
        self.data = glb(self.root / 'synthetic.glb').read_bytes()
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
        if client: actual['Cookie'] = client['cookie']
        if method == 'POST':
            actual['Content-Type'] = 'application/json'
            if raw is None:
                raw = json.dumps({**({'expectedSessionRevision': client['revision']} if client else {}), **(body or {})}).encode()
        for key, value in (headers or {}).items():
            if value is None: actual.pop(key, None)
            else: actual[key] = value
        connection = HTTPConnection(*self.server.server_address, timeout=8)
        try:
            connection.request(method, path, raw, actual)
            response = connection.getresponse()
            response_headers = dict(response.getheaders())
            data = response.read()
            value = json.loads(data) if response_headers.get('Content-Type', '').startswith('application/json') else data
            return response.status, value, response_headers
        finally: connection.close()

    def login(self, username):
        status, view, headers = self.request('/api/session', client=False, method='GET')
        self.assertEqual(status, 200)
        status, view, headers = self.request('/api/session/login', client=False,
            body={'username': username, 'password': 'synthetic-password', 'expectedSessionRevision': view['sessionRevision']},
            headers={'Cookie': headers['Set-Cookie'].split(';', 1)[0]})
        self.assertEqual(status, 200)
        return {'cookie': headers['Set-Cookie'].split(';', 1)[0], 'revision': view['sessionRevision']}

    def authority(self, client=None):
        return self.sessions.rows[(client or self.admin)['cookie'].split('=', 1)[1]].authority

    def listing(self, body=None, **options):
        return self.request('/api/workbench/resources/models', body or {}, **options)

    def metadata(self, **changes):
        status, value, _ = self.listing()
        self.assertEqual(status, 200, value)
        return {'expectedSessionRevision': self.admin['revision'], 'expectedLibraryRevision': value['libraryRevision'],
            'clientRequestId': str(uuid4()), 'displayName': '合成设备模型', 'purpose': 'equipment',
            'sourceNote': 'Synthetic geometry for HTTP tests', 'rightsDeclared': True, **changes}

    def upload(self, metadata=None, *, data=None, client=None):
        metadata = self.metadata() if metadata is None else metadata
        header = base64.b64encode(json.dumps(metadata).encode()).decode()
        return self.request('/api/workbench/resources/model/upload', raw=self.data if data is None else data,
            client=client, headers={'Content-Type': 'model/gltf-binary', 'X-Model-Metadata': header})

    def new_version(self):
        status, value, _ = self.upload()
        self.assertEqual(status, 200, value)
        return value

    def calibration(self, version):
        return {'modelVersionId': version['modelVersionId'], 'expectedContentRevision': version['contentRevision'],
            'expectedLibraryRevision': self.listing()[1]['libraryRevision'], 'clientRequestId': str(uuid4()),
            'calibration': {'unit': 'm', 'axes': 'Y_UP_RIGHT_HANDED', 'basePoint': [0, 0, 0], 'forward': [0, 0, -1]}}

    def calibrate(self, body, **options):
        return self.request('/api/workbench/resources/model/calibrate', body, **options)

    def model(self, version, **options):
        return self.request('/api/workbench/resources/model',
            {'modelAssetId': version['modelAssetId'], 'modelVersionId': version['modelVersionId']}, **options)

    def content(self, version, **options):
        return self.request('/api/workbench/resources/model/content',
            {'modelVersionId': version['modelVersionId'], 'expectedContentRevision': version['contentRevision'],
             'expectedSha256': version['sha256']}, **options)

    def expect(self, response, status, code):
        self.assertEqual(response[0], status, response[1])
        self.assertEqual(response[1], {'code': code})

    def test_real_upload_append_calibration_and_fixed_content_without_default_installation(self):
        self.assertIsNone(self.sessions.model)
        first = self.new_version()
        self.assertFalse(first['canPlace'])
        self.assertEqual(first['calibrationState'], 'unverified')
        self.assertEqual(first['capabilities']['scope'], 'project_static_glb_resources')
        self.assertEqual(first['limits']['maxUploadBytes'], MAX_BYTES)
        body = self.calibration(first)
        status, calibrated, _ = self.calibrate(body)
        self.assertEqual(status, 200, calibrated)
        self.assertTrue(calibrated['canPlace'])
        self.assertEqual(calibrated['calibration']['verifiedBy'], 'fixture-admin')
        self.assertNotEqual(calibrated['modelVersionId'], first['modelVersionId'])
        self.assertEqual(calibrated['modelAssetId'], first['modelAssetId'])
        for version in (first, calibrated):
            self.assertEqual(self.model(version)[0], 200)
            status, data, headers = self.content(version)
            self.assertEqual(status, 200, data)
            self.assertEqual(data, self.data)
            self.assertEqual(headers['Content-Type'], 'model/gltf-binary')
            self.assertEqual(headers['X-Content-SHA256'], hashlib.sha256(data).hexdigest())
            self.assertEqual(headers['Cache-Control'], 'no-store')
        status, appended, _ = self.upload(self.metadata(modelAssetId=first['modelAssetId']))
        self.assertEqual(status, 200, appended)
        self.assertEqual(appended['modelAssetId'], first['modelAssetId'])
        self.assertFalse(appended['canPlace'])
        listed = self.listing()[1]
        self.assertEqual(len(listed['items']), 1)
        self.assertEqual(len(listed['items'][0]['versions']), 3)
        self.assertFalse(any('/installations/' in path for _, path in self.authority().calls))
        self.assertNotIn(str(self.root), json.dumps(listed))

    def test_anonymous_member_and_revoked_project_cannot_write(self):
        version = self.new_version()
        member = self.login('fixture-reader'); self.authority(member).role = 'reader'
        self.assertEqual(self.model(version, client=member)[0], 200)
        self.assertFalse(self.listing(client=member)[1]['capabilities']['canUpload'])
        metadata = self.metadata(expectedSessionRevision=member['revision'])
        self.expect(self.upload(metadata, client=member), 403, 'MODEL_WRITE_FORBIDDEN')
        self.expect(self.calibrate(self.calibration(version), client=member), 403, 'MODEL_WRITE_FORBIDDEN')
        self.expect(self.listing(client=False), 401, 'SESSION_EXPIRED')
        self.authority().allowed = False
        self.expect(self.model(version), 403, 'FORBIDDEN')

    def test_transport_session_is_not_business_idempotency_identity(self):
        metadata = self.metadata()
        first = self.upload(metadata)
        self.assertEqual(first[0], 200)
        self.assertEqual(self.upload(metadata)[1]['modelVersionId'], first[1]['modelVersionId'])
        second_session = self.login('fixture-admin')
        metadata['expectedSessionRevision'] = second_session['revision']
        self.assertEqual(self.upload(metadata, client=second_session)[1]['modelVersionId'], first[1]['modelVersionId'])
        changed = dict(metadata, sourceNote='Different business body')
        self.expect(self.upload(changed, client=second_session), 409, 'REQUEST_CONFLICT')
        with self.sessions.library.connect() as db:
            self.assertEqual(db.execute('select count(*) from project_model_audit').fetchone()[0], 1)

    def test_old_library_revision_and_old_content_revision_are_refused(self):
        first = self.new_version(); body = self.calibration(first)
        self.new_version()
        self.expect(self.calibrate(body), 409, 'MODEL_LIBRARY_CHANGED')
        body = self.calibration(first); body['expectedContentRevision'] = 'model-content:' + '0' * 64
        self.expect(self.calibrate(body), 409, 'RESOURCE_CHANGED')

    def test_server_computes_calibration_identity_not_client_matrix_or_verifier(self):
        version = self.new_version()
        for field, value in [('modelToCalibrated', [1] * 16), ('verifiedBy', 'another-user'), ('state', 'verified')]:
            body = self.calibration(version); body['calibration'][field] = value
            self.expect(self.calibrate(body), 422, 'INVALID_REQUEST')
        body = self.calibration(version); body['calibration']['forward'] = [0, 0, 0]
        self.expect(self.calibrate(body), 422, 'INVALID_CALIBRATION')
        self.assertEqual(len(self.listing()[1]['items'][0]['versions']), 1)

    def test_role_loss_and_access_change_during_model_processing_roll_back_upload(self):
        original = self.sessions.library.process
        metadata = self.metadata()
        def changed(path):
            value = original(path); self.authority().role = 'reader'; return value
        with patch.object(self.sessions.library, 'process', side_effect=changed):
            self.expect(self.upload(metadata), 403, 'MODEL_WRITE_FORBIDDEN')
        self.authority().role = 'admin'
        self.assertEqual(self.listing()[1]['items'], [])
        def revised(path):
            value = original(path); self.authority().grant = 'grant:2'; return value
        with patch.object(self.sessions.library, 'process', side_effect=revised):
            self.expect(self.upload(self.metadata()), 409, 'ACCESS_CHANGED')
        self.assertEqual(self.listing()[1]['items'], [])
        self.assertEqual(list((self.sessions.library.root / 'files').iterdir()), [])

    def test_logout_during_processing_discards_upload_and_private_response(self):
        entered, release, result = Event(), Event(), []
        original = self.sessions.library.process
        def delayed(path):
            entered.set(); release.wait(3); return original(path)
        metadata = self.metadata()
        with patch.object(self.sessions.library, 'process', side_effect=delayed):
            worker = Thread(target=lambda: result.append(self.upload(metadata))); worker.start()
            self.assertTrue(entered.wait(2))
            self.assertEqual(self.request('/api/session/logout')[0], 200)
            release.set(); worker.join(4)
        self.expect(result[0], 401, 'SESSION_EXPIRED')
        with self.sessions.library.connect() as db:
            self.assertEqual(db.execute('select count(*) from project_model_versions').fetchone()[0], 0)
        self.assertEqual(list((self.sessions.library.root / 'files').iterdir()), [])

    def test_late_content_after_logout_never_returns_binary(self):
        version = self.new_version(); entered, release, result = Event(), Event(), []
        original = self.sessions.project_models.content
        def delayed(*args):
            data = original(*args); entered.set(); release.wait(3); return data
        with patch.object(self.sessions.project_models, 'content', side_effect=delayed):
            worker = Thread(target=lambda: result.append(self.content(version))); worker.start()
            self.assertTrue(entered.wait(2)); self.assertEqual(self.request('/api/session/logout')[0], 200)
            release.set(); worker.join(4)
        self.expect(result[0], 401, 'SESSION_EXPIRED')

    def test_fixed_sha_and_calibration_revision_are_checked_for_binary_read(self):
        version = self.new_version()
        wrong = dict(version, sha256='0' * 64)
        self.expect(self.content(wrong), 409, 'RESOURCE_CHANGED')
        wrong = dict(version, contentRevision='model-content:' + '0' * 64)
        self.expect(self.content(wrong), 409, 'RESOURCE_CHANGED')
        path = self.sessions.library.root / 'files' / (version['modelVersionId'] + '.glb')
        data = bytearray(path.read_bytes()); data[-1] ^= 1; path.write_bytes(data)
        self.expect(self.content(version), 409, 'RESOURCE_CHANGED')

    def test_server_project_actor_and_artifact_paths_cannot_be_selected_by_client(self):
        version = self.new_version()
        for field in ({'projectCode': 'foreign'}, {'actor': 'other'}, {'url': 'https://invalid.example'}, {'path': '/private/file'}):
            self.expect(self.listing(field), 422, 'INVALID_REQUEST')
        self.expect(self.request('/api/workbench/resources/model', {'modelAssetId': str(uuid4()), 'modelVersionId': version['modelVersionId']}), 404, 'NOT_FOUND_OR_FORBIDDEN')
        self.authority().project = 'foreign-project'
        self.expect(self.model(version), 403, 'FORBIDDEN')

    def test_usage_counts_are_real_scene_references_and_retained_history(self):
        version = self.new_version()
        base = self.request('/api/workbench/scenes/create', {'displayName': '合成场景', 'clientRequestId': str(uuid4())})[1]
        snapshot = copy.deepcopy(base['snapshot'])
        snapshot['instances'] = [{'sceneModelInstanceId': str(uuid4()), 'displayName': '实例A', 'modelVersionId': version['modelVersionId'],
            'placement': {'position': {'mode': 'local', 'xM': 0, 'zM': 0}, 'height': {'mode': 'local_relative', 'relativeHeightM': 0}, 'headingDeg': 0},
            'visible': True, 'positionLocked': False, 'rootBinding': None, 'componentBindings': []}]
        # An unverified resource remains previewable; it must be calibrated before new scene placement.
        body = {'sceneId': base['sceneId'], 'expectedSceneRevision': base['sceneRevision'], 'clientRequestId': str(uuid4()), 'snapshot': snapshot,
                'reviewedEngineering': [], 'rootBindingChanges': []}
        self.expect(self.request('/api/workbench/scenes/save', body), 409, 'MODEL_CALIBRATION_REQUIRED')
        status, calibrated, _ = self.calibrate(self.calibration(version)); self.assertEqual(status, 200, calibrated)
        snapshot['instances'][0]['modelVersionId'] = calibrated['modelVersionId']
        status, saved, _ = self.request('/api/workbench/scenes/save', body); self.assertEqual(status, 200, saved)
        used = self.request('/api/workbench/resources/uses', {'resourceKind': 'model', 'versionId': calibrated['modelVersionId']})[1]
        self.assertEqual(used['currentInstanceCount'], 1)
        snapshot['instances'] = []
        body.update(expectedSceneRevision=saved['sceneRevision'], clientRequestId=str(uuid4()))
        self.assertEqual(self.request('/api/workbench/scenes/save', body)[0], 200)
        used = self.request('/api/workbench/resources/uses', {'resourceKind': 'model', 'versionId': calibrated['modelVersionId']})[1]
        self.assertEqual(used['currentInstanceCount'], 0)
        self.assertEqual(used['retainedInstanceCount'], 1)
        self.assertEqual(used['retainedReferenceCount'], 1)

    def test_strict_metadata_json_limits_and_origin_are_preserved(self):
        self.expect(self.listing(raw=b'{"expectedSessionRevision":"a","expectedSessionRevision":"b"}'), 422, 'INVALID_REQUEST')
        self.expect(self.listing(headers={'Origin': 'https://other.example'}), 403, 'FORBIDDEN')
        self.expect(self.listing(raw=b' ' * 16385), 413, 'INVALID_REQUEST')
        metadata = self.metadata(); metadata['rightsDeclared'] = False
        self.expect(self.upload(metadata), 422, 'MODEL_RIGHTS_REQUIRED')
        metadata = self.metadata(); metadata['path'] = '/private/model.glb'
        self.expect(self.upload(metadata), 422, 'INVALID_REQUEST')
        self.expect(self.upload(data=b'not a model'), 413, 'MODEL_LIMIT_EXCEEDED')
        self.expect(self.request('/api/workbench/resources/model/upload', raw=self.data,
            headers={'Content-Type': 'model/gltf-binary', 'X-Model-Metadata': 'invalid%%%'}), 422, 'INVALID_REQUEST')
        header = base64.b64encode(json.dumps(self.metadata()).encode()).decode()
        self.expect(self.request('/api/workbench/resources/model/upload', raw=b'',
            headers={'Content-Type': 'model/gltf-binary', 'X-Model-Metadata': header, 'Content-Length': str(MAX_BYTES + 1)}), 413, 'MODEL_LIMIT_EXCEEDED')

    def test_duplicate_transport_headers_are_rejected_for_old_and_new_uploads(self):
        header = base64.b64encode(json.dumps(self.metadata()).encode()).decode()
        for path in ('/api/workbench/models/upload', '/api/workbench/resources/model/upload'):
            for duplicate in ('Content-Type', 'Content-Length', 'Transfer-Encoding', 'X-Model-Metadata'):
                connection = HTTPConnection(*self.server.server_address, timeout=3)
                try:
                    connection.putrequest('POST', path, skip_host=True)
                    for key, value in [('Host', '127.0.0.1:4180'), ('Origin', ORIGIN), ('Cookie', self.admin['cookie']),
                                       ('Content-Type', 'model/gltf-binary'), ('Content-Length', str(len(self.data))), ('X-Model-Metadata', header)]:
                        connection.putheader(key, value)
                    connection.putheader(duplicate, {'Content-Type': 'model/gltf-binary', 'Content-Length': str(len(self.data)),
                        'Transfer-Encoding': 'chunked', 'X-Model-Metadata': header}[duplicate])
                    connection.endheaders(self.data)
                    response = connection.getresponse()
                    self.assertEqual(response.status, 415)
                    self.assertEqual(json.loads(response.read()), {'code': 'INVALID_REQUEST'})
                finally: connection.close()


if __name__ == '__main__': unittest.main()
