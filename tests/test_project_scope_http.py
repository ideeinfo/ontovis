"""Explicit project scopes through the real same-origin HTTP dispatcher."""
from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from uuid import uuid4

from apps.api.project_sessions import ProjectSessions
from apps.api.session_http import handler_type
from tests.test_project_workspaces import ProjectsAuthority
from tests import test_scene_http as scene_http
ORIGIN=scene_http.ORIGIN


class ProjectScopeHttpTests(unittest.TestCase):
    request = scene_http.SceneHttpTests.request
    login = scene_http.SceneHttpTests.login

    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        ProjectsAuthority.permissions = {'member': {'A': 'admin', 'B': 'admin'}, 'empty': {}}
        self.sessions = ProjectSessions('http://127.0.0.1:18001', library_root=self.root / 'unused',
            workspace_root=self.root / 'projects', factory=ProjectsAuthority)
        self.addCleanup(self.sessions.close)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler_type(self.sessions, ORIGIN, development=True))
        thread = Thread(target=self.server.serve_forever, daemon=True); thread.start()
        self.addCleanup(self.server.server_close); self.addCleanup(thread.join); self.addCleanup(self.server.shutdown)
        self.admin = self.login('member')

    def ref(self, code):
        return {'ontobaseConnectionId': 'ontobase-primary', 'projectCode': code}

    def test_every_business_family_requires_explicit_project_and_catalog_has_all_grants(self):
        status, directory, _ = self.request('/api/workbench/projects', {})
        self.assertEqual(status, 200)
        self.assertEqual([i['projectRef']['projectCode'] for i in directory['items']], ['A', 'B'])
        for path in ['scenes', 'scenes/create', 'scenes/open', 'scenes/save', 'terrains',
                     'terrains/job', 'imagery', 'public-geodata/job', 'objects/context', 'catalog',
                     'evidence/resolve', 'models/binding', 'scenes/legacy-migration/entry']:
            with self.subTest(path=path):
                status, value, _ = self.request('/api/workbench/' + path, {})
                self.assertEqual((status, value['code']), (422, 'PROJECT_REQUIRED'))
        self.assertEqual(self.request('/api/workbench/resources/models', {})[0], 200)
        self.assertIsNone(self.sessions.registry.lookup('A'))

    def test_create_open_revoke_replay_and_no_legacy_default(self):
        request_id = str(uuid4())
        body = {'projectRef': self.ref('A'), 'displayName': 'HTTP synthetic', 'description': 'Purpose', 'clientRequestId': request_id}
        status, a, _ = self.request('/api/workbench/scenes/create', body)
        self.assertEqual(status, 200, a)
        status, replay, _ = self.request('/api/workbench/scenes/create', body)
        self.assertEqual((status, replay['sceneRevision']), (200, a['sceneRevision']))
        status, value, _ = self.request('/api/workbench/scenes/open', {'projectRef': self.ref('B'), 'sceneId': a['sceneId']})
        self.assertEqual(status, 404)
        self.assertNotIn('snapshot', value)
        status, value, _ = self.request('/api/workbench/scenes', {'projectRef': self.ref('B'), 'unexpected': True})
        self.assertEqual(status, 422)
        del ProjectsAuthority.permissions['member']['A']
        self.assertEqual(self.request('/api/workbench/scenes/open', {'projectRef': self.ref('A'), 'sceneId': a['sceneId']})[0], 403)
        self.assertEqual(self.request('/api/session', method='GET')[1]['state'], 'active')
        self.assertEqual(self.request('/api/workbench/scenes', {'projectRef': self.ref('B')})[0], 200)
