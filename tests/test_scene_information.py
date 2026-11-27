"""Information-only saves retain every fixed scene fact and concurrency guard."""
import copy
import json
import unittest
from unittest.mock import patch
from uuid import uuid4
from tests import test_scene_library as fixture


class SceneInformationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture.SceneLibraryTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.scene=self.fixture.create();saved=self.fixture.save(self.fixture.body(self.scene,[self.fixture.item()]))
        self.scene=self.fixture.opened(saved)

    def body(self):
        body=self.fixture.body(self.scene)
        body.update(informationOnly=True,sceneInfoWriteVersion=1,environmentWriteVersion=1,expectedLifecycleRevision=0)
        body['snapshot'].update(displayName='本源设备场景',description='名称更新，不改变工程关联。')
        return body

    def test_information_save_preserves_snapshot_validation_and_uses_without_readopting_facts(self):
        f=self.fixture
        # A prior unresolved issue must not disappear or be approved by renaming.
        validation=dict(scope='local_plane_unbound',bindingIssues=[dict(kind='engineering_changed',reason='unreviewed')],engineeringExpectations=[])
        with patch.object(f.scenes,'_local_spatial',return_value=dict(validation=validation,heightProvenance=[],terrainRefs=[])):
            saved=f.save(f.body(self.scene))
        self.scene=f.opened(saved);body=self.body();before=copy.deepcopy(self.scene['snapshot'])
        with f.models.connect() as db:
            uses=[tuple(row) for row in db.execute('select instance_id,model_version_id from scene_resource_uses where revision=?',(self.scene['sceneRevision'],))]
        def no_engineering(*_):raise AssertionError('A label edit cannot approve fresh engineering facts')
        saved=f.save(body,engineering=no_engineering,resources=no_engineering)
        opened=f.opened(saved);expected={**before,'displayName':body['snapshot']['displayName'],'description':body['snapshot']['description']}
        self.assertEqual(expected,opened['snapshot']);self.assertEqual(validation,opened['validation'])
        self.assertEqual(before,f.opened(self.scene,self.scene['sceneRevision'])['snapshot'])
        with f.models.connect() as db:
            self.assertEqual(uses,[tuple(row) for row in db.execute('select instance_id,model_version_id from scene_resource_uses where revision=?',(saved['sceneRevision'],))])
        counts=f.counts();self.assertEqual(saved,f.save(body,engineering=no_engineering,resources=no_engineering));self.assertEqual(counts,f.counts())
        f.allowed=False;f.expect('SCENE_WRITE_FORBIDDEN',lambda:f.save(body));self.assertEqual(counts,f.counts())

    def test_information_mode_rejects_every_non_information_change_and_review_declaration(self):
        f=self.fixture
        for change in (lambda b:b['snapshot']['instances'][0].update(displayName='Other instance'),
                       lambda b:b['snapshot']['instances'][0].update(visible=False),
                       lambda b:b['snapshot']['initialView']['eye'].__setitem__(0,999),
                       lambda b:b.update(reviewedEngineering=[dict(forged=True)]),
                       lambda b:b.update(rootBindingChanges=[dict(forged=True)]),
                       lambda b:b.update(spatialChange=dict(kind='anchor',receipt='forged'))):
            body=self.body();change(body);counts=f.counts()
            with self.subTest(body=body):f.expect('SCENE_INFORMATION_SCOPE',lambda:f.save(body))
            self.assertEqual(counts,f.counts())

    def test_information_save_requires_current_head_lifecycle_and_valid_fields(self):
        f=self.fixture;body=self.body();f.save(body)
        body['clientRequestId']=str(uuid4());f.expect('SCENE_CHANGED',lambda:f.save(body))
        fresh=f.opened(self.scene);body=self.body();body['expectedSceneRevision']=fresh['sceneRevision'];body['expectedLifecycleRevision']=99
        f.expect('SCENE_CHANGED',lambda:f.save(body))
        body['expectedLifecycleRevision']=0;body['snapshot']['displayName']='bad\nname'
        f.expect('INVALID_REQUEST',lambda:f.save(body))

    def test_information_save_rolls_back_when_final_authorization_is_revoked(self):
        f=self.fixture;before=f.counts();calls=[]
        def authorize():
            calls.append(True)
            if len(calls)==2:
                from apps.api.authority import PreviewError
                raise PreviewError(403,'SCENE_WRITE_FORBIDDEN')
        f.expect('SCENE_WRITE_FORBIDDEN',lambda:f.save(self.body(),authorize=authorize))
        self.assertEqual(before,f.counts());self.assertEqual(self.scene['sceneRevision'],f.opened(self.scene)['sceneRevision'])


if __name__=='__main__':unittest.main()
