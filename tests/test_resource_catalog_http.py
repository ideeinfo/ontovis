"""Three new resource paths over real HTTP, SQLite and synthetic private GLB.

Terrain worker output is controlled metadata, not a claim of GIS acceptance.
"""
import base64
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
from threading import Event, Thread
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.api.model_validation import validate
from apps.api.session_http import handler_type
from apps.api.workbench_server import WorkbenchSessions
from tests.test_model_upload import glb
import tests.test_project_model_http as model_http
from tests.test_resource_reuse import add_terrain
from tests.test_scene_http import SceneAuthority, CONTEXT, ORIGIN
from tests.test_terrain_library import FAKE_PROCESSOR


LEGACY = '/api/workbench/resources/models/legacy'
IMPORT = '/api/workbench/resources/model/import-existing'
TERRAINS = '/api/workbench/terrains'


class ResourceCatalogHttpTests(unittest.TestCase):
    request = model_http.ProjectModelHttpTests.request
    login = model_http.ProjectModelHttpTests.login
    authority = model_http.ProjectModelHttpTests.authority
    expect = model_http.ProjectModelHttpTests.expect

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        executable = self.root/'controlled-worker'
        executable.write_text('#!'+sys.executable+'\n'+FAKE_PROCESSOR); executable.chmod(0o700)
        executable.with_suffix('.control').write_text('{}')
        self.sessions = WorkbenchSessions('http://127.0.0.1:1234','fixture-project',CONTEXT,
            library_root=self.root/'private',terrain_python=executable,factory=SceneAuthority)
        self.addCleanup(self.sessions.terrains.close)
        source = glb(self.root/'synthetic.glb'); self.data = source.read_bytes()
        self.legacy = self.sessions.library.save_upload(source,{'expectedSessionRevision':'transport-only',
            'expectedLibraryRevision':'library:0','clientRequestId':str(uuid4()),'displayName':'既有设备模型',
            'sourceNote':'Synthetic HTTP fixture','rightsDeclared':True},'fixture-original',validate(source),lambda:None)
        for index in range(3):
            self.sessions.library.bind({'modelVersionId':self.legacy['versionId'],'entityUid':f'private-fixture-{index}',
                'componentKey':f'component:{index}','expectedEntityRevision':'object:1','expectedHierarchyRevision':'hierarchy:1',
                'expectedModelRevision':index+1,'clientRequestId':str(uuid4())},'fixture-original',lambda:None)
        self.server = ThreadingHTTPServer(('127.0.0.1',0),handler_type(self.sessions,ORIGIN,development=True))
        self.thread = Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
        self.addCleanup(self.server.server_close); self.addCleanup(self.thread.join); self.addCleanup(self.server.shutdown)
        self.admin = self.login('fixture-admin')

    def body(self, **changes):
        return {'legacyModelVersionId':self.legacy['versionId'],'expectedModelRevision':4,
            'expectedSha256':self.legacy['sha256'],'expectedLibraryRevision':self.sessions.library.listing()['libraryRevision'],
            'purpose':'equipment','clientRequestId':str(uuid4()),**changes}

    def test_member_discovers_legacy_and_empty_terrain_permissions_without_default_equipment(self):
        reader = self.login('fixture-reader'); self.authority(reader).role = 'reader'
        for client in (self.admin,reader):
            status,legacy,_ = self.request(LEGACY,client=client)
            self.assertEqual(status,200,legacy); self.assertEqual(legacy['items'][0]['legacyBindingCount'],3)
            self.assertTrue(legacy['items'][0]['sourceRightsDeclared']); self.assertNotIn('private-fixture-',json.dumps(legacy))
            status,terrains,_ = self.request(TERRAINS,client=client)
            self.assertEqual(status,200,terrains); self.assertEqual(terrains['items'],[])
            self.assertEqual(terrains['capabilities']['canUpload'],client is self.admin)
            self.assertEqual(terrains['limits']['maxUploadBytes'],256*1024*1024)
            self.assertNotIn(str(self.root),json.dumps(terrains))
            self.assertFalse(any('/installations/' in path for _,path in self.authority(client).calls))

    def test_import_reuses_original_declaration_and_preserves_old_three_links(self):
        before = self.sessions.library.version(self.legacy['versionId']); body = self.body()
        status,value,_ = self.request(IMPORT,body)
        self.assertEqual(status,200,value); self.assertFalse(value['canPlace']); self.assertEqual(value['calibration'],{'state':'unverified'})
        self.assertEqual(value['sourceModelVersionId'],self.legacy['versionId'])
        self.assertEqual(self.sessions.library.version(self.legacy['versionId']),before)
        self.assertEqual(self.sessions.library.version(value['modelVersionId'])['bindings'],[])
        status,data,headers = self.request('/api/workbench/resources/model/content',{
            'modelVersionId':value['modelVersionId'],'expectedContentRevision':value['contentRevision'],'expectedSha256':value['sha256']})
        self.assertEqual(status,200,data); self.assertEqual(data,self.data)
        self.assertEqual(headers['X-Content-SHA256'],value['sha256'])
        status,listed,_ = self.request(LEGACY)
        self.assertEqual(status,200,listed); self.assertFalse(listed['items'][0]['canImport'])
        self.assertEqual(listed['items'][0]['importedResource']['modelVersionId'],value['modelVersionId'])
        second_session = self.login('fixture-admin')
        status,replay,_ = self.request(IMPORT,body,client=second_session)
        self.assertEqual(status,200,replay); self.assertEqual(replay['modelVersionId'],value['modelVersionId'])
        self.expect(self.request(IMPORT,self.body()),409,'MODEL_ALREADY_IMPORTED')
        self.assertFalse(any('/installations/' in path for _,path in self.authority().calls))

    def test_missing_original_declaration_remains_discoverable_but_cannot_be_self_asserted(self):
        with self.sessions.library.connect() as db: db.execute("update audit set payload='{}' where action='model_uploaded'")
        status,view,_ = self.request(LEGACY)
        self.assertEqual(status,200); self.assertFalse(view['items'][0]['canImport']); self.assertFalse(view['items'][0]['sourceRightsDeclared'])
        self.expect(self.request(IMPORT,self.body()),422,'MODEL_SOURCE_RIGHTS_REQUIRED')
        self.expect(self.request(IMPORT,self.body(rightsDeclared=True)),422,'INVALID_REQUEST')
        self.assertEqual(len(self.sessions.library.listing()['items']),1)

    def test_anonymous_member_and_revoked_project_boundaries(self):
        for path in (LEGACY,IMPORT,TERRAINS):
            self.expect(self.request(path,self.body() if path==IMPORT else {},client=False),401,'SESSION_EXPIRED')
        reader = self.login('fixture-reader'); self.authority(reader).role = 'reader'
        self.expect(self.request(IMPORT,self.body(),client=reader),403,'MODEL_WRITE_FORBIDDEN')
        self.assertEqual(self.request(LEGACY,client=reader)[0],200)
        self.authority(reader).allowed = False
        for path in (LEGACY,TERRAINS): self.expect(self.request(path,client=reader),403,'FORBIDDEN')

    def test_import_checks_exact_fields_revision_fingerprint_and_library_conditions(self):
        for changes,status,code in [({'expectedModelRevision':3},409,'RESOURCE_CHANGED'),
            ({'expectedSha256':'0'*64},409,'RESOURCE_CHANGED'),({'expectedLibraryRevision':'library:old'},409,'MODEL_LIBRARY_CHANGED'),
            ({'expectedModelRevision':True},422,'INVALID_REQUEST'),({'path':'/untrusted.glb'},422,'INVALID_REQUEST'),
            ({'url':'https://untrusted.invalid'},422,'INVALID_REQUEST'),({'matrix':[0]*16},422,'INVALID_REQUEST'),
            ({'legacyModelVersionId':str(uuid4())},404,'NOT_FOUND_OR_FORBIDDEN')]:
            self.expect(self.request(IMPORT,self.body(**changes)),status,code)
        self.expect(self.request(LEGACY,{'projectCode':'foreign'}),422,'INVALID_REQUEST')
        self.expect(self.request(TERRAINS,{'serverPath':'/untrusted'}),422,'INVALID_REQUEST')
        self.assertEqual(len(self.sessions.library.listing()['items']),1)

    def test_role_loss_after_reading_source_prevents_registration_but_keeps_read_access(self):
        original = self.sessions.project_models._content
        def read(value):
            result = original(value)
            if value['modelVersionId']==self.legacy['versionId']: self.authority().role = 'reader'
            return result
        with patch.object(self.sessions.project_models,'_content',side_effect=read):
            self.expect(self.request(IMPORT,self.body()),403,'MODEL_WRITE_FORBIDDEN')
        self.assertEqual(len(self.sessions.library.listing()['items']),1)
        self.assertEqual(self.request(LEGACY)[0],200); self.assertFalse(self.request(TERRAINS)[1]['capabilities']['canUpload'])

    def test_logout_during_private_copy_cannot_publish_or_return_old_success(self):
        entered,release = Event(),Event(); results = []; original = self.sessions.project_models._content
        def read(value):
            result = original(value)
            if value['modelVersionId']==self.legacy['versionId']:
                entered.set(); release.wait(timeout=3)
            return result
        body = self.body()
        with patch.object(self.sessions.project_models,'_content',side_effect=read):
            thread = Thread(target=lambda:results.append(self.request(IMPORT,body))); thread.start()
            self.assertTrue(entered.wait(timeout=3))
            self.assertEqual(self.request('/api/session/logout')[0],200)
            release.set(); thread.join(timeout=5); self.assertFalse(thread.is_alive())
        self.expect(results[0],401,'SESSION_EXPIRED')
        self.assertEqual(len(self.sessions.library.listing()['items']),1)
        self.assertEqual(list((self.sessions.library.root/'temporary').iterdir()),[])

    def test_terrain_catalog_fixed_paging_grants_and_new_version_expiry(self):
        identifiers = sorted(add_terrain(self.sessions.terrains,'地区地形') for _ in range(3))
        status,first,_ = self.request(TERRAINS,{'q':'地区','limit':2})
        self.assertEqual(status,200,first)
        status,second,_ = self.request(TERRAINS,{'q':'地区','limit':2,'cursor':first['nextCursor']})
        self.assertEqual(status,200,second)
        self.assertEqual([row['terrainVersionId'] for row in first['items']+second['items']],identifiers)
        self.assertEqual(first['items'][0]['sourceHorizontalCrs'],'EPSG:4326')
        self.assertEqual(first['items'][0]['coverageWgs84'],[110,32,111,33])
        reader = self.login('fixture-reader'); self.authority(reader).role = 'reader'
        self.expect(self.request(TERRAINS,{'q':'地区','limit':2,'cursor':first['nextCursor']},client=reader),422,'INVALID_REQUEST')
        self.authority().grant = 'grant:2'
        self.expect(self.request(TERRAINS,{'q':'地区','limit':2,'cursor':first['nextCursor']}),422,'INVALID_REQUEST')
        self.authority().grant = 'grant:1'; add_terrain(self.sessions.terrains,'New terrain')
        self.expect(self.request(TERRAINS,{'q':'地区','limit':2,'cursor':first['nextCursor']}),409,'SNAPSHOT_EXPIRED')
        self.expect(self.request(TERRAINS,{'limit':101}),422,'INVALID_REQUEST')

    def test_only_completed_terrain_jobs_appear_and_old_missing_summary_fields_are_unknown(self):
        metadata = {'expectedSessionRevision':self.admin['revision'],'clientRequestId':str(uuid4()),'displayName':'Controlled fixture',
            'sourceNote':'Synthetic test fixture','licenseNote':'Synthetic test','rightsDeclared':True,'verticalDatum':'EGM2008','heightUnit':'m'}
        header = base64.b64encode(json.dumps(metadata).encode()).decode()
        status,job,_ = self.request(TERRAINS+'/upload',raw=b'II*\x00synthetic-terrain-fixture',
            headers={'Content-Type':'image/tiff','X-Terrain-Metadata':header})
        self.assertEqual(status,202,job)
        deadline = time.monotonic()+4
        while time.monotonic()<deadline:
            status,current,_ = self.request(TERRAINS+'/job',{'jobId':job['jobId']})
            self.assertEqual(status,200,current)
            if current['state'] in ('ready','failed','cancelled'): break
            time.sleep(.01)
        self.assertEqual(current['state'],'ready',current)
        status,view,_ = self.request(TERRAINS)
        self.assertEqual(status,200,view); self.assertEqual(len(view['items']),1)
        self.assertEqual(view['items'][0]['terrainVersionId'],current['terrainVersionId'])
        self.assertIsNone(view['items'][0]['sourceHorizontalCrs']); self.assertIsNone(view['items'][0]['coverageWgs84'])
        self.assertEqual(view['items'][0]['verticalDatum'],'EGM2008')


if __name__ == '__main__': unittest.main()
