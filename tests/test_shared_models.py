"""Shared fixed model identities, independent project scenes and filtered usage."""
import copy
import io
import json
import unittest
from uuid import uuid4

from apps.api.project_sessions import ProjectSessions
from apps.api.authority import PreviewError
from tests import test_project_workspaces as project_fixtures
from tests.test_project_workspaces import ProjectsAuthority
from tests.test_model_upload import glb


class SharedModelTests(unittest.TestCase):
    setUp = project_fixtures.ProjectWorkspaceTests.setUp
    payload = project_fixtures.ProjectWorkspaceTests.payload
    call = project_fixtures.ProjectWorkspaceTests.call
    create = project_fixtures.ProjectWorkspaceTests.create
    assertCode = project_fixtures.ProjectWorkspaceTests.assertCode

    def resource(self, path, **body):
        return self.sessions.resource_request(self.sid, '/api/workbench/resources/' + path, self.payload(**body))

    def upload(self):
        data = glb(self.root / 'shape.glb').read_bytes()
        return self.sessions.resource_upload(self.sid, self.payload(expectedLibraryRevision='library:0',
            clientRequestId=str(uuid4()), displayName='Shared synthetic model', purpose='equipment',
            sourceNote='Synthetic geometry', rightsDeclared=True), io.BytesIO(data), len(data))

    def calibrated(self):
        value = self.upload()
        return self.resource('model/calibrate', modelVersionId=value['modelVersionId'],
            expectedContentRevision=value['contentRevision'], expectedLibraryRevision=value['libraryRevision'],
            calibration={'unit': 'm', 'axes': 'Y_UP_RIGHT_HANDED', 'basePoint': [0, 0, 0], 'forward': [0, 0, -1]},
            clientRequestId=str(uuid4()))

    def save_instance(self, scene, version):
        snapshot = copy.deepcopy(scene['snapshot'])
        snapshot['instances'] = [{'sceneModelInstanceId': str(uuid4()), 'displayName': 'Independent instance',
            'modelVersionId': version['modelVersionId'], 'placement': {'position': {'mode': 'local', 'xM': 20, 'zM': 10},
                'height': {'mode': 'local_relative', 'relativeHeightM': 0}, 'headingDeg': 0},
            'visible': True, 'positionLocked': False, 'rootBinding': None, 'componentBindings': []}]
        return self.call('scenes/save', scene['projectRef']['projectCode'], sceneId=scene['sceneId'],
            expectedSceneRevision=scene['sceneRevision'], snapshot=snapshot, clientRequestId=str(uuid4()),
            reviewedEngineering=[], rootBindingChanges=[], sceneInfoWriteVersion=1)

    def test_shared_basic_info_is_editable_by_maintainer_and_readable_without_project(self):
        model = self.calibrated()
        body = {'modelAssetId': model['modelAssetId'], 'modelVersionId': model['modelVersionId'],
            'expectedAssetRevision': model['assetRevision'], 'clientRequestId': str(uuid4()),
            'displayName': 'Shared edited model', 'purpose': 'equipment', 'description': 'Shared description'}
        value = self.resource('model/info/save', **body)
        self.assertEqual(value['displayName'], 'Shared edited model')
        self.assertNotIn('projectRef', value)
        self.assertEqual(self.resource('models')['items'][0]['displayName'], value['displayName'])
        ProjectsAuthority.permissions['member'] = {}
        self.assertFalse(self.resource('models')['capabilities']['canEditInfo'])
        self.assertEqual(self.resource('model', modelAssetId=model['modelAssetId'],
            modelVersionId=model['modelVersionId'])['description'], value['description'])
        self.assertCode('MODEL_WRITE_FORBIDDEN', lambda: self.resource('model/info/save', **body))
        self.assertEqual(self.sessions.inspect(self.sid)['state'], 'active')

    def test_login_without_project_can_read_shared_models_but_not_write(self):
        model = self.calibrated()
        catalog = self.resource('models')
        self.assertEqual(catalog['capabilities']['scope'], 'shared_static_glb_resources')
        self.assertNotIn('projectRef', catalog)
        self.assertEqual(len(catalog['items']), 1)
        ProjectsAuthority.permissions['member'] = {}
        listing = self.resource('models')
        self.assertEqual(listing['items'], catalog['items'])
        self.assertFalse(listing['capabilities']['canUpload'])
        self.resource('model/content', modelVersionId=model['modelVersionId'],
            expectedContentRevision=model['contentRevision'], expectedSha256=model['sha256'])
        self.assertCode('MODEL_WRITE_FORBIDDEN', lambda: self.resource('model/calibrate',
            modelVersionId=model['modelVersionId']))
        self.assertEqual(self.sessions.inspect(self.sid)['state'], 'active')

    def test_same_version_in_two_projects_creates_instances_without_copying_models(self):
        model = self.calibrated()
        before = sorted(self.sessions.shared.library.root.rglob('*.glb'))
        a, b = self.create('A'), self.create('B')
        self.save_instance(a, model)
        self.save_instance(b, model)
        opened = [self.call('scenes/open', code, sceneId=scene['sceneId']) for code, scene in [('A', a), ('B', b)]]
        self.assertEqual([x['resourceRefs'][0]['modelVersionId'] for x in opened], [model['modelVersionId']] * 2)
        self.assertNotEqual(opened[0]['snapshot']['instances'][0]['sceneModelInstanceId'],
                            opened[1]['snapshot']['instances'][0]['sceneModelInstanceId'])
        for item in opened:
            with self.sessions.services[item['workspaceId']].library.connect() as db:
                self.assertEqual(db.execute('select count(*) from versions').fetchone()[0], 0)
                self.assertFalse(db.execute('pragma foreign_key_check').fetchall())
        self.assertEqual(sorted(self.sessions.shared.library.root.rglob('*.glb')), before)
        self.assertEqual(len(self.resource('models')['items'][0]['versions']), 2)
        use = self.resource('uses', resourceKind='model', versionId=model['modelVersionId'], limit=1)
        self.assertEqual(use['currentInstanceCount'], 2)
        self.assertIsNotNone(use['nextCursor'])
        del ProjectsAuthority.permissions['member']['A']
        current = self.resource('uses', resourceKind='model', versionId=model['modelVersionId'])
        self.assertEqual(current['currentInstanceCount'], 1)
        self.assertEqual([x['projectRef']['projectCode'] for x in current['items']], ['B'])
        self.assertCode('SNAPSHOT_EXPIRED', lambda: self.resource('uses', resourceKind='model',
            versionId=model['modelVersionId'], limit=1, cursor=use['nextCursor']))
        self.assertCode('FORBIDDEN', lambda: self.call('scenes/open', 'A', sceneId=a['sceneId']))
        self.assertEqual(self.resource('model', modelAssetId=model['modelAssetId'],
            modelVersionId=model['modelVersionId'])['sha256'], model['sha256'])

    def test_shared_write_rechecks_grants_and_replay_after_revocation(self):
        model = self.upload()
        row = self.sessions.current(self.sid)
        _, authorize, _, _ = self.sessions.shared_access.authorize(self.sid, self.payload(), writing=True)
        ProjectsAuthority.permissions['member'] = {}
        self.assertCode('MODEL_WRITE_FORBIDDEN', authorize)
        self.assertCode('MODEL_WRITE_FORBIDDEN', lambda: self.resource('model/metadata/save'))
        self.assertIs(self.sessions.current(self.sid), row)
        self.assertCode('RESOURCE_CHANGED', lambda: self.resource('model/content', modelVersionId=model['modelVersionId'],
            expectedContentRevision=model['contentRevision'], expectedSha256='0' * 64))

    def test_full_backup_preserves_shared_store_and_cross_project_references(self):
        from tools.project_store_backup import snapshot, verify, restore_new
        from tools.model_store_backup import BackupError
        model = self.calibrated()
        a, b = self.create('A'), self.create('B')
        self.save_instance(a, model)
        self.save_instance(b, model)
        root = self.sessions.shared.library.root
        self.sessions.close()
        with self.assertRaises(BackupError):
            snapshot(self.sessions.registry.root, self.root / 'missing-shared', service_stopped=True)
        result = snapshot(self.sessions.registry.root, self.root / 'B1-shared', library_root=root, service_stopped=True)
        report = verify(self.root / 'B1-shared', result['manifestSha256'])
        self.assertEqual(report['sharedModels']['connectionId'], 'ontobase-primary')
        restored = self.root / 'shared-restored'
        restore_new(self.root / 'B1-shared', restored, result['manifestSha256'], service_stopped=True)
        sessions = ProjectSessions('http://127.0.0.1:18001', library_root=restored / 'workbench-library',
            workspace_root=restored / 'project-spaces', factory=ProjectsAuthority)
        self.addCleanup(sessions.close)
        self.assertEqual(sessions.shared.project_models.content_identity(model['modelVersionId'])['sha256'], model['sha256'])
        target = sessions._workspace(sessions.registry.lookup('B'))
        with target.library.connect() as db:
            self.assertEqual(db.execute('select model_version_id from scene_resource_uses').fetchone()[0], model['modelVersionId'])
        # Valid SQLite, but a broken external fixed-version reference must fail backup.
        with target.library.connect() as db:
            db.execute('drop trigger scene_revision_no_update')
            row = db.execute('select revision,resource_refs from scene_revisions where resource_refs!=?', ('[]',)).fetchone()
            refs = json.loads(row[1]); refs[0]['sha256'] = '0' * 64
            db.execute('update scene_revisions set resource_refs=? where revision=?', (json.dumps(refs), row[0]))
        with self.assertRaises(BackupError) as error:
            snapshot(sessions.registry.root, self.root / 'bad-reference', library_root=sessions.shared.library.root, service_stopped=True)
        self.assertEqual(error.exception.code, 'INVALID_SHARED_MODEL_REFERENCE')

    def test_backup_preserves_configuration_history_and_rejects_a_missing_model(self):
        from apps.api.equipment_configurations import EquipmentConfigurations
        from tools.project_store_backup import snapshot, restore_new
        from tools.model_store_backup import BackupError
        model=self.calibrated();self.create('B')
        workspace=self.sessions._workspace(self.sessions.registry.lookup('B'))
        store=workspace.equipment_store();cid=str(uuid4())
        body={'configurationId':cid,'expectedConfigurationRevision':None,'clientRequestId':str(uuid4()),
            'snapshot':{'displayName':'共享设备型号','objectKind':'equipment','rootDefinition':None,
                'models':[{'modelVersionId':model['modelVersionId'],'mappings':[]}]}}
        saved=store.save(body,'member',lambda:None,lambda _:None,lambda _:model['components'])
        root=self.sessions.shared.library.root;self.sessions.close()
        receipt=snapshot(self.sessions.registry.root,self.root/'configuration-backup',library_root=root,service_stopped=True)
        restored=self.root/'configuration-restored'
        restore_new(self.root/'configuration-backup',restored,receipt['manifestSha256'],service_stopped=True)
        sessions=ProjectSessions('http://127.0.0.1:18001',library_root=restored/'workbench-library',
            workspace_root=restored/'project-spaces',factory=ProjectsAuthority)
        self.addCleanup(sessions.close)
        target=sessions._workspace(sessions.registry.lookup('B'))
        self.assertEqual(target.equipment_store().detail(cid,None,lambda:None)['configurationRevision'],saved['configurationRevision'])
        with target.library.connect() as db:
            db.execute('drop trigger equipment_configuration_history_no_update')
            snapshot_value=body['snapshot'];snapshot_value['models'][0]['modelVersionId']=str(uuid4())
            db.execute('update equipment_configuration_revisions set snapshot=?',(json.dumps(snapshot_value),))
        with self.assertRaises(BackupError) as error:
            snapshot(sessions.registry.root,self.root/'broken-configuration',library_root=sessions.shared.library.root,service_stopped=True)
        self.assertEqual(error.exception.code,'INVALID_SHARED_MODEL_REFERENCE')

    def test_shared_binary_read_does_not_enumerate_projects(self):
        model = self.upload()
        authority = self.sessions.current(self.sid).authority
        original = authority.request
        def request(method, path, body=None):
            self.assertNotEqual(path, '/api/v1/projects')
            return original(method, path, body)
        authority.request = request
        self.resource('model/content', modelVersionId=model['modelVersionId'],
            expectedContentRevision=model['contentRevision'], expectedSha256=model['sha256'])


if __name__ == '__main__':
    unittest.main()
