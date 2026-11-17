"""Recoverable shared model removal retains fixed content and existing scene uses."""
import copy
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import unittest
from uuid import uuid4
from unittest.mock import patch

from apps.api.authority import PreviewError
from tests import test_project_model_library as project
from tests import test_shared_models as shared
from tests.test_project_workspaces import ProjectsAuthority


class ModelLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = project.ProjectModelLibraryTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.models, self.library, self.guard = self.fixture.models, self.fixture.old, self.fixture.guard
        self.version = self.fixture.calibrate(self.fixture.upload())

    def body(self, **changes):
        value = self.fixture.model(self.version)
        return {'modelAssetId': value['modelAssetId'], 'modelVersionId': value['modelVersionId'],
            'expectedAssetRevision': value['assetRevision'], 'expectedLifecycleRevision': value['lifecycleRevision'],
            'clientRequestId': str(uuid4()), **changes}

    def change(self, body=None, action='delete', guard=None):
        return self.models.lifecycle(body or self.body(), 'fixture-admin', guard or self.guard, action=action)

    def expect(self, code, action):
        with self.assertRaises(PreviewError) as caught: action()
        self.assertEqual(caught.exception.code, code)

    def rows(self):
        with self.library.connect() as db:
            return {name:[tuple(r) for r in db.execute('select * from '+name)] for name in
                ('library','versions','project_model_assets','project_model_versions','project_model_lifecycle',
                 'project_model_requests','project_model_audit','project_model_info_revisions')}

    def test_delete_restore_retains_all_fixed_versions_bytes_and_read_access(self):
        before = self.rows(); files={p.name:p.read_bytes() for p in (self.library.root/'files').iterdir()}
        deleted = self.change(); self.assertEqual(deleted['assetState'], 'deleted')
        self.assertEqual(self.fixture.listing()['items'], [])
        self.assertEqual(len(self.fixture.listing(state='deleted')['items'][0]['versions']), 2)
        value = self.fixture.model(self.version)
        self.assertEqual(value['assetState'], 'deleted')
        self.assertEqual(self.models.content(value['modelVersionId'],value['contentRevision'],value['sha256'],self.guard),self.fixture.data)
        restored = self.change(action='restore'); self.assertEqual(restored['lifecycleRevision'], 2)
        self.assertEqual(len(self.fixture.listing()['items']), 1)
        self.assertEqual(self.fixture.listing(state='deleted')['items'], [])
        after = self.rows()
        for name in ('versions','project_model_versions','project_model_info_revisions'):self.assertEqual(before[name],after[name])
        self.assertEqual(files,{p.name:p.read_bytes() for p in (self.library.root/'files').iterdir()})

    def test_replay_is_fixed_and_rechecks_current_authorization(self):
        body=self.body(); deleted=self.change(body); self.change(action='restore'); before=self.rows()
        self.assertEqual(self.change(body),deleted); self.assertEqual(self.rows(),before)
        self.expect('REQUEST_CONFLICT',lambda:self.change({**body,'expectedLifecycleRevision':1}))
        self.guard.allowed=False
        self.expect('MODEL_WRITE_FORBIDDEN',lambda:self.change(body))
        self.assertEqual(self.rows(),before)

    def test_stale_asset_and_lifecycle_versions_fail_after_restore(self):
        body=self.body(); self.change(body); self.change(action='restore')
        self.expect('MODEL_ASSET_CHANGED',lambda:self.change({**body,'clientRequestId':str(uuid4())}))
        fresh=self.body(expectedLifecycleRevision=0)
        self.expect('MODEL_ASSET_CHANGED',lambda:self.change(fresh))
        self.assertEqual(self.change()['lifecycleRevision'],3)

    def test_final_permission_failure_rolls_back_entire_change(self):
        before=self.rows(); calls=0
        def guard():
            nonlocal calls
            calls+=1
            if calls==2:raise PreviewError(403,'MODEL_WRITE_FORBIDDEN')
        self.expect('MODEL_WRITE_FORBIDDEN',lambda:self.change(guard=guard))
        self.assertEqual(self.rows(),before)

    def test_simultaneous_delete_has_one_winner(self):
        body=self.body(); barrier=Barrier(2)
        def run(_):
            barrier.wait()
            try:self.change({**body,'clientRequestId':str(uuid4())});return 'ok'
            except PreviewError as error:return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:self.assertCountEqual(list(pool.map(run,range(2))),['ok','MODEL_ASSET_CHANGED'])

    def test_extra_fields_invalid_versions_and_unrelated_model_fail_without_writes(self):
        other=self.fixture.upload(); before=self.rows()
        for revision in (True,-1,1.5,'0',2**53):
            self.expect('INVALID_REQUEST',lambda:self.change(self.body(expectedLifecycleRevision=revision)))
        self.expect('INVALID_REQUEST',lambda:self.change(self.body(purge=True)))
        self.expect('NOT_FOUND_OR_FORBIDDEN',lambda:self.change(self.body(modelVersionId=other['modelVersionId'])))
        self.assertEqual(self.rows(),before)

    def test_deleted_asset_cannot_be_edited_calibrated_or_appended(self):
        self.change(); value=self.fixture.model(self.version)
        info={'modelAssetId':value['modelAssetId'],'modelVersionId':value['modelVersionId'],
            'expectedAssetRevision':value['assetRevision'],'clientRequestId':str(uuid4()),
            'displayName':'Changed','purpose':'equipment','description':''}
        self.expect('MODEL_DELETED',lambda:self.models.save_info(info,'fixture-admin',self.guard))
        self.expect('MODEL_DELETED',lambda:self.fixture.calibrate(self.version))
        metadata=self.fixture.metadata(modelAssetId=value['modelAssetId'])
        self.expect('MODEL_DELETED',lambda:self.fixture.upload(metadata))

    def test_catalog_cursor_binds_state_and_is_invalidated_by_lifecycle_change(self):
        self.fixture.upload(); listing=self.fixture.listing(limit=1); token=listing['nextCursor']; self.assertIsNotNone(token)
        self.expect('INVALID_REQUEST',lambda:self.fixture.listing(limit=1,state='deleted',cursor=token))
        self.change()
        self.expect('SNAPSHOT_EXPIRED',lambda:self.fixture.listing(limit=1,cursor=token))
        self.expect('INVALID_REQUEST',lambda:self.fixture.listing(state='purged'))


class SharedModelLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fixture=shared.SharedModelTests(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.model=self.fixture.calibrated()

    def change(self,action='delete',**changes):
        value=self.fixture.resource('model',modelAssetId=self.model['modelAssetId'],modelVersionId=self.model['modelVersionId'])
        return self.fixture.resource('model/'+action,modelAssetId=value['modelAssetId'],modelVersionId=value['modelVersionId'],
            expectedAssetRevision=value['assetRevision'],expectedLifecycleRevision=value['lifecycleRevision'],clientRequestId=str(uuid4()),**changes)

    def test_existing_instances_in_multiple_projects_remain_editable_but_new_uses_are_blocked(self):
        f=self.fixture; a,b,fresh=f.create('A'),f.create('B'),f.create('B'); saved=f.save_instance(a,self.model); saved_b=f.save_instance(b,self.model)
        existing=f.call('scenes/open','A',sceneId=a['sceneId'])
        self.change(); self.assertEqual(f.resource('models')['items'],[])
        opened=f.call('scenes/open','A',sceneId=a['sceneId']); self.assertEqual(opened['snapshot'],existing['snapshot'])
        self.assertEqual(f.call('scenes/open','B',sceneId=b['sceneId'])['sceneRevision'],saved_b['sceneRevision'])
        snapshot=copy.deepcopy(opened['snapshot']); snapshot['instances'][0]['visible']=False
        result=f.call('scenes/save','A',sceneId=a['sceneId'],expectedSceneRevision=saved['sceneRevision'],snapshot=snapshot,
            clientRequestId=str(uuid4()),reviewedEngineering=[],rootBindingChanges=[],sceneInfoWriteVersion=1)
        self.assertNotEqual(result['sceneRevision'],saved['sceneRevision'])
        f.assertCode('MODEL_DELETED',lambda:f.save_instance(fresh,self.model))
        snapshot['instances'].append({**copy.deepcopy(snapshot['instances'][0]),'sceneModelInstanceId':str(uuid4())})
        f.assertCode('MODEL_DELETED',lambda:f.call('scenes/save','A',sceneId=a['sceneId'],expectedSceneRevision=result['sceneRevision'],
            snapshot=snapshot,clientRequestId=str(uuid4()),reviewedEngineering=[],rootBindingChanges=[],sceneInfoWriteVersion=1))
        self.change('restore'); f.save_instance(fresh,self.model)

    def test_lifecycle_requires_current_shared_maintainer_and_keeps_identity_on_denial(self):
        f=self.fixture; ProjectsAuthority.permissions['member']={}
        self.assertFalse(f.resource('models')['capabilities']['canDeleteModels'])
        f.assertCode('MODEL_WRITE_FORBIDDEN',lambda:self.change())
        self.assertEqual(f.sessions.inspect(f.sid)['state'],'active')

    def test_deletion_during_save_validation_is_rechecked_before_scene_commit(self):
        f=self.fixture; scene=f.create('A')
        service=f.sessions._workspace(f.sessions.registry.lookup('A')); original=service.scenes._manifest; first=True
        self.assertIs(service.scenes.model_lock,f.sessions.shared.project_models.lifecycle_lock)
        def manifest(*args,**kwargs):
            nonlocal first
            value=original(*args,**kwargs)
            if first:first=False;self.change()
            return value
        with patch.object(service.scenes,'_manifest',side_effect=manifest):
            f.assertCode('MODEL_DELETED',lambda:f.save_instance(scene,self.model))
        self.assertEqual(f.call('scenes/open','A',sceneId=scene['sceneId'])['snapshot']['instances'],[])
