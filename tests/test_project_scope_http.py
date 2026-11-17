"""Explicit project scopes through the real same-origin HTTP dispatcher."""
from http.server import ThreadingHTTPServer
from pathlib import Path
import hashlib
import io
import json
import sys
import tempfile
from threading import Thread
import unittest
from uuid import uuid4
from unittest.mock import patch

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
            workspace_root=self.root / 'projects', factory=ProjectsAuthority, terrain_python=Path(sys.executable))
        self.addCleanup(self.sessions.close)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler_type(self.sessions, ORIGIN, development=True))
        thread = Thread(target=self.server.serve_forever, daemon=True); thread.start()
        self.addCleanup(self.server.server_close); self.addCleanup(thread.join); self.addCleanup(self.server.shutdown)
        self.admin = self.login('member')

    def ref(self, code):
        return {'ontobaseConnectionId': 'ontobase-primary', 'projectCode': code}

    def test_material_reads_require_current_project_and_do_not_prepare_a_workspace(self):
        from tests.test_equipment_materials import MODEL, ROLES, SPEC
        path='/api/workbench/equipment/materials/models';calls=[];original=ProjectsAuthority.request
        def source(account,method,target,body=None):
            if '/equipment-materials/models/' in target:
                calls.append(target)
                return dict(model=MODEL,roles=ROLES,revision=0,total=0,items=[],nextCursor=None,canManage=False)
            return original(account,method,target,body)
        with patch.object(ProjectsAuthority,'request',source):
            self.assertEqual(self.request(path,{'specificationId':SPEC})[1]['code'],'PROJECT_REQUIRED')
            for project in ('A','B'):
                status,value,_=self.request(path,{'projectRef':self.ref(project),'specificationId':SPEC})
                self.assertEqual(status,200,value);self.assertEqual(value['projectRef'],self.ref(project))
                self.assertIsNone(value['workspaceId']);self.assertIn('/projects/'+project+'/',calls[-1])
                self.assertIsNone(self.sessions.registry.lookup(project))
            del ProjectsAuthority.permissions['member']['A']
            self.assertEqual(self.request(path,{'projectRef':self.ref('A'),'specificationId':SPEC})[0],403)
            self.assertEqual(self.request(path,{'projectRef':self.ref('B'),'specificationId':SPEC})[0],200)
            self.assertEqual(self.request(path,{'projectRef':self.ref('B'),'specificationId':SPEC},client=False)[0],401)

    def test_every_business_family_requires_explicit_project_and_catalog_has_all_grants(self):
        status, directory, _ = self.request('/api/workbench/projects', {})
        self.assertEqual(status, 200)
        self.assertEqual([i['projectRef']['projectCode'] for i in directory['items']], ['A', 'B'])
        for path in ['scenes', 'scenes/create', 'scenes/open', 'scenes/save', 'terrains',
                     'terrains/job', 'imagery', 'imagery/upload-result', 'imagery/uploads/start', 'imagery/uploads/status',
                     'imagery/uploads/complete', 'imagery/uploads/cancel', 'public-geodata/job', 'objects/context', 'catalog',
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

    def test_imagery_result_cannot_cross_project_and_revocation_keeps_the_other_project_available(self):
        from tests.test_imagery_library import image_bytes, metadata
        for code in ('A', 'B'):
            status, value, _ = self.request('/api/workbench/scenes/create',
                {'projectRef': self.ref(code), 'displayName': 'Synthetic', 'clientRequestId': str(uuid4())})
            self.assertEqual(status, 200, value)
        raw = image_bytes(self.root / 'scoped.tif')
        payload = metadata()
        library = self.sessions._workspace(self.sessions.registry.lookup('A')).imagery
        first = library.upload(io.BytesIO(raw), len(raw), payload, 'member', lambda: None)
        body = {'metadata': payload, 'expectedSourceSha256': hashlib.sha256(raw).hexdigest()}
        path = '/api/workbench/imagery/upload-result'
        status, result, _ = self.request(path, {**body, 'projectRef': self.ref('A')})
        self.assertEqual((status, result['imageryVersionId']), (200, first['imageryVersionId']))
        status, result, _ = self.request(path, {**body, 'projectRef': self.ref('B')})
        self.assertEqual((status, result['state']), (200, 'unknown'))
        self.assertNotIn('imageryVersionId', result)
        del ProjectsAuthority.permissions['member']['A']
        self.assertEqual(self.request(path, {**body, 'projectRef': self.ref('A')})[0], 403)
        self.assertEqual(self.request(path, {**body, 'projectRef': self.ref('B')})[0], 200)

    def test_segmented_upload_ids_cannot_cross_project_and_chunks_require_scope(self):
        from tests.test_imagery_library import image_bytes, metadata
        import base64
        data=image_bytes(self.root/'part.tif')
        body={'metadata':metadata(),'expectedSourceSha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
        status,row,_=self.request('/api/workbench/imagery/uploads/start',{**body,'projectRef':self.ref('A')})
        self.assertEqual(status,200,row)
        self.assertEqual(self.request('/api/workbench/imagery/uploads/status',{'uploadId':row['uploadId'],'projectRef':self.ref('B')})[0],404)
        payload={'uploadId':row['uploadId'],'offset':0,'expectedUploadRevision':row['uploadRevision'],
                 'expectedChunkSha256':hashlib.sha256(data).hexdigest(),'expectedSessionRevision':self.admin['revision']}
        def chunk(ref=None):
            header={**payload,**({'projectRef':ref} if ref else {})}
            return self.request('/api/workbench/imagery/uploads/chunk',raw=data,
                headers={'Content-Type':'application/octet-stream','X-Imagery-Chunk':base64.b64encode(json.dumps(header).encode()).decode()})
        self.assertEqual(chunk()[1]['code'],'PROJECT_REQUIRED')
        self.assertEqual(chunk(self.ref('B'))[0],404)
        self.assertEqual(chunk(self.ref('A'))[0],200)
        self.assertIsNone(self.sessions.registry.lookup('B'))
