"""The model lifecycle endpoints use the existing session, origin and JSON boundaries."""
import unittest
from uuid import uuid4
from tests import test_project_model_http as fixture


class ModelLifecycleHttpTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture.ProjectModelHttpTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.version=self.fixture.new_version()

    def body(self):
        f=self.fixture;status,value,_=f.model(self.version);self.assertEqual(status,200)
        return {'modelAssetId':value['modelAssetId'],'modelVersionId':value['modelVersionId'],
            'expectedAssetRevision':value['assetRevision'],'expectedLifecycleRevision':value['lifecycleRevision'],'clientRequestId':str(uuid4())}

    def test_lifecycle_listing_fixed_content_restore_and_no_purge(self):
        f=self.fixture;status,deleted,headers=f.request('/api/workbench/resources/model/delete',self.body())
        self.assertEqual(status,200,deleted);self.assertEqual(deleted['assetState'],'deleted');self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertEqual(f.listing()[1]['items'],[]);self.assertEqual(len(f.listing({'state':'deleted'})[1]['items']),1)
        self.assertEqual(f.content(self.version)[0],200)
        status,value,_=f.request('/api/workbench/resources/model/restore',self.body());self.assertEqual(status,200,value)
        self.assertEqual(len(f.listing()[1]['items']),1)
        for suffix in ('purge','delete/extra','delete/','restore/extra'):
            self.assertEqual(f.request('/api/workbench/resources/model/'+suffix,self.body())[0],404)

    def test_reader_revoked_and_bad_origin_cannot_change_lifecycle(self):
        f=self.fixture;body=self.body();reader=f.login('fixture-reader');f.authority(reader).role='reader'
        for action in ('delete','restore'):
            status,value,_=f.request('/api/workbench/resources/model/'+action,body,client=reader)
            self.assertEqual((status,value['code']),(403,'MODEL_WRITE_FORBIDDEN'))
        status,value,_=f.request('/api/workbench/resources/model/delete',body,headers={'Origin':'https://outside.invalid'})
        self.assertEqual(status,403)
        self.assertEqual(f.request('/api/workbench/resources/model/delete',body,client=False)[0],401)
        self.assertEqual(len(f.listing()[1]['items']),1)

    def test_strict_fields_json_limit_and_stale_replay(self):
        f=self.fixture;body=self.body();path='/api/workbench/resources/model/delete'
        self.assertEqual(f.request(path,{**body,'purge':True})[0],422)
        self.assertEqual(f.request(path,raw=b' '*16385)[0],413)
        first=f.request(path,body);self.assertEqual(first[0],200,first[1]);self.assertEqual(f.request(path,body)[1],first[1])
        self.assertEqual(f.request(path,{**body,'clientRequestId':str(uuid4())})[0],409)
