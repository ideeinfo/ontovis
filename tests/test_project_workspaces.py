"""Real SQLite spaces and existing scene services, with bounded synthetic source projects."""
import copy
import shutil
import io
from pathlib import Path
import sqlite3
import tempfile
from threading import Thread
import unittest
from urllib.parse import unquote
from uuid import uuid4
from unittest.mock import patch

from apps.api.authority import PreviewError
from apps.api.model_library import ModelLibrary
from apps.api.project_sessions import ProjectSessions
from apps.api.scene_library import SceneLibrary


class ProjectsAuthority:
    projects = {'A': 'Project A', 'B': 'Project B'}
    permissions = {'member': {'A': 'admin', 'B': 'admin'}, 'empty': {}}

    def __init__(self, _url):
        self.username = None

    def request(self, method, path, body=None):
        if path == '/api/v1/auth/login':
            return {'token': 'synthetic-token', 'user': {'username': body['username']}}
        if path == '/api/v1/auth/me':
            return {'user': {'username': self.username, 'is_active': True}}
        grants = self.permissions[self.username]
        if path == '/api/v1/projects':
            return {'items': [{'project_code': k, 'project_name': v, 'status': 'active', 'description': ''}
                              for k, v in self.projects.items() if k in grants]}
        code = unquote(path.split('/')[4])
        if code not in grants:
            raise PreviewError(403, 'FORBIDDEN')
        if path.endswith('/access'):
            return {'projectCode': code, 'projectName': self.projects[code], 'role': grants[code],
                    'accessRevision': code + ':' + grants[code],
                    'capabilities': ['objects.read', 'objects.resolve', 'installations.read', 'hierarchy.read']}
        raise AssertionError((method, path))


class ProjectWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        ProjectsAuthority.permissions = {'member': {'A': 'admin', 'B': 'admin'}, 'empty': {}}
        self.sessions = ProjectSessions('http://127.0.0.1:18001', library_root=self.root / 'legacy',
            workspace_root=self.root / 'projects', factory=ProjectsAuthority)
        self.addCleanup(self.sessions.close)
        sid, row = self.sessions.anonymous()
        self.sid, view = self.sessions.login(sid, {'username': 'member', 'password': 'synthetic-fixture',
            'expectedSessionRevision': row.revision}, 'fixture')
        self.revision = view['sessionRevision']

    def payload(self, project=None, **body):
        return {'expectedSessionRevision': self.revision,
                **({'projectRef': {'ontobaseConnectionId': 'ontobase-primary', 'projectCode': project}} if project else {}), **body}

    def call(self, path, project=None, **body):
        return self.sessions.scene_request(self.sid, '/api/workbench/' + path, self.payload(project, **body))

    def create(self, project='A', request_id=None, **info):
        return self.call('scenes/create', project, clientRequestId=request_id or str(uuid4()), displayName='First', **info)

    def assertCode(self, code, call):
        with self.assertRaises(PreviewError) as error:
            call()
        self.assertEqual(error.exception.code, code)

    def test_directory_reads_do_not_create_project_storage_and_empty_identity_can_login(self):
        listing = self.sessions.projects_request(self.sid, '/api/workbench/projects', self.payload())
        self.assertEqual([r['projectRef']['projectCode'] for r in listing['items']], ['A', 'B'])
        self.assertEqual(list(self.sessions.registry.root.glob('libraries/*')), [])
        self.assertEqual(self.call('scenes', 'A')['items'], [])
        self.assertIsNone(self.sessions.registry.lookup('A'))
        sid, row = self.sessions.anonymous()
        sid, view = self.sessions.login(sid, {'username': 'empty', 'password': 'synthetic-fixture',
            'expectedSessionRevision': row.revision}, 'fixture-empty')
        self.assertEqual(view['state'], 'active')
        self.assertEqual(self.sessions.projects_request(sid, '/api/workbench/projects',
            {'expectedSessionRevision': view['sessionRevision']})['items'], [])

    def test_required_scope_new_project_without_installation_and_two_spaces(self):
        self.assertCode('PROJECT_REQUIRED', lambda: self.create(None))
        request = str(uuid4())
        a, b = self.create('A', request), self.create('B', request)
        self.assertNotEqual(a['sceneId'], b['sceneId'])
        self.assertNotEqual(a['workspaceId'], b['workspaceId'])
        self.assertEqual(self.create('A', request)['sceneRevision'], a['sceneRevision'])
        self.assertCode('NOT_FOUND_OR_FORBIDDEN', lambda: self.call('scenes/open', 'B', sceneId=a['sceneId']))
        self.assertEqual(len(self.call('scenes', 'A')['items']), 1)
        self.assertEqual(len(self.call('scenes', 'B')['items']), 1)
        service = self.sessions.services[a['workspaceId']]
        with service.library.connect() as db:
            self.assertIsNone(db.execute('select context_id from library').fetchone()[0])
            self.assertEqual(db.execute('select workspace_id from scenes').fetchone()[0], a['workspaceId'])
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("update scenes set project_code='B'")

    def test_scene_basic_information_history_replay_and_old_writer_guard(self):
        scene = self.create(description='Purpose\nSynthetic')
        body = {'sceneId': scene['sceneId'], 'expectedSceneRevision': scene['sceneRevision'],
                'clientRequestId': str(uuid4()), 'snapshot': copy.deepcopy(scene['snapshot']),
                'reviewedEngineering': [], 'rootBindingChanges': [], 'sceneInfoWriteVersion': 1}
        body['snapshot'].update(displayName='Renamed', description='Updated')
        saved = self.call('scenes/save', 'A', **body)
        self.assertEqual(self.call('scenes', 'A')['items'][0]['displayName'], 'Renamed')
        self.assertEqual(self.call('scenes/save', 'A', **body)['sceneRevision'], saved['sceneRevision'])
        old = self.call('scenes/open', 'A', sceneId=scene['sceneId'], sceneRevision=scene['sceneRevision'])
        self.assertEqual(old['snapshot']['description'], 'Purpose\nSynthetic')
        stale = copy.deepcopy(body); stale['clientRequestId'] = str(uuid4())
        self.assertCode('SCENE_CHANGED', lambda: self.call('scenes/save', 'A', **stale))
        stale['expectedSceneRevision'] = saved['sceneRevision']
        stale['snapshot'].pop('description'); stale.pop('sceneInfoWriteVersion')
        self.assertCode('SCENE_INFO_WRITE_VERSION_REQUIRED', lambda: self.call('scenes/save', 'A', **stale))

    def test_project_denial_keeps_identity_and_other_project_usable(self):
        a, b = self.create('A'), self.create('B')
        del ProjectsAuthority.permissions['member']['A']
        self.assertCode('FORBIDDEN', lambda: self.call('scenes/open', 'A', sceneId=a['sceneId']))
        self.assertEqual(self.sessions.inspect(self.sid)['state'], 'active')
        self.assertEqual(self.call('scenes/open', 'B', sceneId=b['sceneId'])['sceneId'], b['sceneId'])

    def test_initialization_concurrency_and_scope_corruption(self):
        results = []
        threads = [Thread(target=lambda: results.append(self.create('A'))) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]['workspaceId'], results[1]['workspaceId'])
        service = self.sessions.services[results[0]['workspaceId']]
        with sqlite3.connect(service.library.root / 'library.sqlite3') as db:
            db.execute("update workspace_scope set ontobase_connection_id='wrong'")
        self.assertCode('WORKSPACE_SCOPE_INVALID', lambda: self.call('scenes', 'A'))

    def test_partial_preparation_reuses_identity_and_blocked_space_never_reopens(self):
        with patch('apps.api.project_sessions.WorkbenchSessions', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):
                self.create('A')
        prior = self.sessions.registry.lookup('A')
        self.assertEqual(prior['state'], 'preparing')
        saved = self.create('A')
        self.assertEqual(saved['workspaceId'], prior['workspace_id'])
        self.sessions.registry.mark(prior, 'blocked', 'confirmed_source_conflict')
        # A new dispatcher after restart must not silently reuse a blocked source code.
        root = ProjectSessions('http://127.0.0.1:18001', library_root=self.root / 'none',
            workspace_root=self.sessions.registry.root, factory=ProjectsAuthority)
        self.addCleanup(root.close)
        self.assertCode('WORKSPACE_SCOPE_INVALID', lambda: root._workspace(root.registry.lookup('A')))

    def test_legacy_registration_keeps_snapshot_and_business_revision(self):
        legacy = ModelLibrary(self.root / 'old-library', 'A', str(uuid4()))
        scenes = SceneLibrary(legacy)
        original = scenes.create({'displayName': 'Legacy', 'clientRequestId': str(uuid4())},
            'fixture', lambda: None, lambda _: None, lambda *_: None)
        with legacy.connect() as db:
            before = tuple(db.execute('select revision,snapshot from scene_revisions').fetchone())
            context = db.execute('select context_id from library').fetchone()[0]
        from apps.api.workbench_server import WorkbenchSessions
        WorkbenchSessions('http://127.0.0.1:18001','A',context,library_root=legacy.root,factory=ProjectsAuthority)
        shutil.copytree(legacy.root,self.root/'before-migration')
        root = ProjectSessions('http://127.0.0.1:18001', 'A', context, library_root=legacy.root,
            workspace_root=self.root / 'migrated', factory=ProjectsAuthority)
        self.addCleanup(root.close)
        from tools.project_scope_verification import verify_legacy_scope_upgrade
        proof=verify_legacy_scope_upgrade(self.root/'before-migration',legacy.root)
        self.assertTrue(proof['originalBusinessRowsPreserved'])
        with legacy.connect() as db:
            self.assertEqual(tuple(db.execute('select revision,snapshot from scene_revisions').fetchone()), before)
            self.assertEqual(db.execute('select head_revision from scenes').fetchone()[0], original['sceneRevision'])
            self.assertIsNotNone(db.execute('select workspace_id from scenes').fetchone()[0])

    def test_all_project_stores_backup_and_restore_new_without_legacy_context(self):
        from tools.project_store_backup import snapshot, verify, restore_new
        a, b = self.create('A'), self.create('B')
        self.sessions.close()
        receipt = snapshot(self.sessions.registry.root, self.root / 'B0', library_root=self.sessions.shared.library.root, service_stopped=True)
        report = verify(self.root / 'B0', receipt['manifestSha256'])
        self.assertEqual(len(report['spaces']), 2)
        restored = restore_new(self.root / 'B0', self.root / 'restored', receipt['manifestSha256'], service_stopped=True)
        self.assertEqual(restored['manifestSha256'], receipt['manifestSha256'])
        root = ProjectSessions('http://127.0.0.1:18001', library_root=self.root / 'restored' / 'workbench-library',
            workspace_root=self.root / 'restored' / 'project-spaces', factory=ProjectsAuthority)
        self.addCleanup(root.close)
        for item in (a, b):
            space = root.registry.lookup(item['projectRef']['projectCode'])
            self.assertEqual(space['workspace_id'], item['workspaceId'])
            with root._workspace(space).library.connect() as db:
                self.assertEqual(db.execute('select head_revision from scenes').fetchone()[0], item['sceneRevision'])

    def test_model_upload_replay_and_content_share_identity_across_projects(self):
        from tests.test_model_upload import glb
        data = glb(self.root / 'synthetic.glb').read_bytes()
        request_id = str(uuid4())
        versions = []
        for code in ('A', 'B'):
            result = self.sessions.resource_upload(self.sid, self.payload(code, expectedLibraryRevision='library:0',
                clientRequestId=request_id, displayName='Shared shape', purpose='equipment',
                sourceNote='Synthetic geometry', rightsDeclared=True), io.BytesIO(data), len(data))
            versions.append(result)
        a, b = versions
        self.assertEqual(a['modelVersionId'], b['modelVersionId'])
        self.assertNotIn('projectRef', a)
        for code in (None, 'A', 'B'):
            result = self.sessions.resource_request(self.sid, '/api/workbench/resources/model/content',
                self.payload(code, modelVersionId=a['modelVersionId'],
                    expectedContentRevision=a['contentRevision'], expectedSha256=a['sha256']))
            self.assertEqual(result['content'], data)
        self.assertIsNone(self.sessions.registry.lookup('A'))
        self.assertIsNone(self.sessions.registry.lookup('B'))

    def test_backup_preserves_incomplete_space_without_declaring_it_ready(self):
        from tools.project_store_backup import snapshot, verify, restore_new
        workspace = self.sessions.registry.prepare('A')
        result = snapshot(self.sessions.registry.root, self.root / 'incomplete-B1', library_root=self.sessions.shared.library.root, service_stopped=True)
        report = verify(self.root / 'incomplete-B1', result['manifestSha256'])
        self.assertEqual(report['spaces'][workspace['workspace_id']]['state'], 'preparing')
        self.assertIsNone(report['spaces'][workspace['workspace_id']]['database'])
        restore_new(self.root / 'incomplete-B1', self.root / 'incomplete-restored', result['manifestSha256'], service_stopped=True)

    def test_initialization_recovers_an_empty_sqlite_created_before_process_exit(self):
        workspace = self.sessions.registry.prepare('A')
        path = self.sessions.registry.path(workspace)
        path.mkdir(parents=True)
        sqlite3.connect(path/'library.sqlite3').close()
        created = self.create('A')
        self.assertEqual(created['workspaceId'], workspace['workspace_id'])


if __name__ == '__main__':
    unittest.main()
