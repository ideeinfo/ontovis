"""Legacy reuse and terrain discovery with synthetic GLB and private SQLite.

Terrain directory fixtures exercise metadata pagination only, not GIS processing.
"""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from threading import Barrier, Thread
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.model_library import ModelLibrary
from apps.api.model_validation import validate
from apps.api.project_model_library import ProjectModelLibrary
from apps.api.scene_library import SceneLibrary
from apps.api.terrain_library import TerrainLibrary
from tests.test_model_upload import glb


class ResourceReuseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.context = str(uuid4())
        self.library = ModelLibrary(self.root / 'private', 'fixture-project', self.context)
        self.models = ProjectModelLibrary(self.library)
        self.source = glb(self.root / 'synthetic.glb'); self.data = self.source.read_bytes()
        result = validate(self.source)
        result['components'].append({'componentKey':'proxy:fixture', 'displayName':'Explicit schematic',
            'nodeIndices':[], 'keyStability':'version_local', 'geometryQuality':'proxy_schematic', 'bounds':[[0,0,0],[1,1,1]]})
        self.legacy = self.library.save_upload(self.source, {'expectedSessionRevision':'transport-only',
            'expectedLibraryRevision':'library:0', 'clientRequestId':str(uuid4()), 'displayName':'既有测试模型',
            'sourceNote':'Synthetic reusable model', 'rightsDeclared':True}, 'original-author', result, lambda:None)
        for index in range(3):
            self.library.bind({'modelVersionId':self.legacy['versionId'], 'entityUid':f'private-fixture-{index}',
                'componentKey':f'component:{index}',
                'expectedEntityRevision':'object:1', 'expectedHierarchyRevision':'hierarchy:1',
                'expectedModelRevision':index+1, 'clientRequestId':str(uuid4())}, 'original-author', lambda:None)

    def body(self, **changes):
        return {'legacyModelVersionId':self.legacy['versionId'], 'expectedModelRevision':4,
            'expectedSha256':self.legacy['sha256'], 'expectedLibraryRevision':self.library.listing()['libraryRevision'],
            'purpose':'equipment', 'clientRequestId':str(uuid4()), **changes}

    def imported(self, body=None, **options):
        return self.models.import_existing(body or self.body(), options.get('actor','resource-admin'), options.get('guard',lambda:None))

    def count(self):
        with self.library.connect() as db:
            return tuple(db.execute('select count(*) from ' + table).fetchone()[0] for table in (
                'versions','project_model_assets','project_model_versions','project_model_requests','project_model_audit'))

    def old_records(self):
        with self.library.connect() as db:
            return [[dict(row) for row in db.execute(sql, args)] for sql,args in (
                ('select * from versions where id=?',(self.legacy['versionId'],)),
                ('select * from bindings order by entity_uid',()), ('select * from audit order by id',()))]

    def expect(self, code, callback):
        with self.assertRaises(PreviewError) as caught: callback()
        self.assertEqual(caught.exception.code,code)

    def assert_slot(self):
        self.assertTrue(self.library.slots.acquire(blocking=False)); self.library.slots.release()

    def test_catalog_discloses_counts_and_original_rights_without_engineering_uids(self):
        view = self.models.legacy_candidates(lambda:None); item = view['items'][0]
        self.assertEqual(item['modelRevision'],4); self.assertTrue(item['sourceRightsDeclared']); self.assertTrue(item['canImport'])
        self.assertEqual(item['legacyBindingCount'],3); self.assertFalse(item['canPlace'])
        self.assertNotIn('private-fixture-',json.dumps(view)); self.assertNotIn('bindings',item)
        self.assertEqual(view['libraryRevision'],self.library.listing()['libraryRevision'])
        value = self.imported()
        item = self.models.legacy_candidates(lambda:None)['items'][0]
        self.assertFalse(item['canImport']); self.assertEqual(item['importedResource'],{
            'modelAssetId':value['modelAssetId'],'modelVersionId':value['modelVersionId']})

    def test_import_copies_fixed_bytes_and_proxies_without_adopting_bindings_or_old_scene(self):
        scenes = SceneLibrary(self.library)
        scene = scenes.create({'displayName':'Preserved scene','clientRequestId':str(uuid4())},'fixture-admin',lambda:None,lambda value:None,lambda *args:None)
        snapshot = json.loads(json.dumps(scene['snapshot']))
        snapshot['instances'] = [{'sceneModelInstanceId':str(uuid4()), 'displayName':'Preserved placement',
            'modelVersionId':self.legacy['versionId'], 'placement':{'position':{'mode':'local','xM':0,'zM':0},
                'height':{'mode':'local_relative','relativeHeightM':0},'headingDeg':0},
            'visible':True,'positionLocked':False,'rootBinding':None,'componentBindings':[]}]
        scenes.save({'sceneId':scene['sceneId'],'expectedSceneRevision':scene['sceneRevision'],'clientRequestId':str(uuid4()),
            'snapshot':snapshot,'reviewedEngineering':[],'rootBindingChanges':[]},'fixture-admin',lambda:None,lambda value:None,lambda *args:None)
        previous_scene = scenes.open(scene['sceneId'],'fixture-admin',lambda:None)
        before = self.old_records(); previous = self.library.version(self.legacy['versionId'])
        with patch.object(self.library,'process',side_effect=AssertionError('Reuse must not replace the existing validation report')):
            value = self.imported()
        self.assertNotEqual(value['modelVersionId'],previous['versionId'])
        self.assertEqual(value['sourceModelVersionId'],previous['versionId']); self.assertEqual(value['calibration'],{'state':'unverified'})
        self.assertFalse(value['canPlace']); self.assertEqual(value['sourceNote'],previous['sourceNote'])
        self.assertEqual(value['displayName'],previous['displayName']); self.assertEqual(value['report'],previous['report'])
        self.assertEqual(value['components'],previous['components']); self.assertEqual(self.old_records(),before)
        self.assertEqual(self.library.version(value['modelVersionId'])['bindings'],[])
        self.assertEqual(scenes.open(scene['sceneId'],'fixture-admin',lambda:None),previous_scene)
        self.assertEqual(self.models.content(value['modelVersionId'],value['contentRevision'],value['sha256'],lambda:None),self.data)
        source = self.library.root/'files'/(previous['versionId']+'.glb'); target = self.library.root/'files'/(value['modelVersionId']+'.glb')
        self.assertNotEqual(source.stat().st_ino,target.stat().st_ino); self.assertEqual(target.stat().st_mode & 0o777,0o600)

    def test_original_rights_must_be_boolean_true_for_the_exact_uploaded_version_and_sha(self):
        with self.library.connect() as db:
            audit = dict(db.execute("select * from audit where action='model_uploaded'").fetchone())
        for payload,version in [({},audit['version_id']),({'rightsDeclared':False},audit['version_id']),
            ({'rightsDeclared':1},audit['version_id']),({'rightsDeclared':'true'},audit['version_id']),
            ({'rightsDeclared':True,'sha256':'0'*64},audit['version_id']),
            ({'rightsDeclared':True,'sha256':self.legacy['sha256']},str(uuid4()))]:
            with self.subTest(payload=payload):
                with self.library.connect() as db:
                    db.execute('update audit set payload=?,version_id=? where id=?',(json.dumps(payload),version,audit['id']))
                self.assertFalse(self.models.legacy_candidates(lambda:None)['items'][0]['canImport'])
                self.expect('MODEL_SOURCE_RIGHTS_REQUIRED',lambda:self.imported())
        self.assertEqual(self.count(),(1,0,0,0,0)); self.assertEqual(list((self.library.root/'temporary').iterdir()),[])

    def test_same_request_replays_before_new_library_or_old_binding_revision_checks(self):
        body = self.body(); first = self.imported(body)
        with self.library.connect() as db: db.execute('update versions set revision=revision+1 where id=?',(self.legacy['versionId'],))
        self.assertEqual(self.imported(body),first)
        self.expect('REQUEST_CONFLICT',lambda:self.imported({**body,'purpose':'environment'}))
        self.expect('MODEL_ALREADY_IMPORTED',lambda:self.imported(self.body(expectedModelRevision=5)))
        self.expect('MODEL_ALREADY_IMPORTED',lambda:self.imported(self.body(expectedModelRevision=5),actor='second-admin'))
        self.assertEqual(self.count(),(2,1,1,1,1))

    def test_source_and_library_conditions_and_exact_business_fields(self):
        for changes,code in [({'expectedModelRevision':3},'RESOURCE_CHANGED'),({'expectedSha256':'0'*64},'RESOURCE_CHANGED'),
            ({'expectedLibraryRevision':'library:stale'},'MODEL_LIBRARY_CHANGED'),({'expectedModelRevision':True},'INVALID_REQUEST'),
            ({'purpose':'wind-only'},'INVALID_REQUEST'),({'rightsDeclared':True},'INVALID_REQUEST'),
            ({'path':'/untrusted.glb'},'INVALID_REQUEST'),({'url':'https://untrusted.invalid'},'INVALID_REQUEST'),
            ({'calibration':{}},'INVALID_REQUEST')]:
            self.expect(code,lambda:self.imported(self.body(**changes)))
        self.assertEqual(self.count(),(1,0,0,0,0)); self.assert_slot()

    def test_tampered_or_symlinked_legacy_file_is_never_registered(self):
        source = self.library.root/'files'/(self.legacy['versionId']+'.glb')
        source.write_bytes(b'x'*len(self.data)); self.expect('RESOURCE_CHANGED',lambda:self.imported())
        source.unlink(); fixture = self.root/'replacement.glb'; fixture.write_bytes(self.data); source.symlink_to(fixture)
        self.expect('RESOURCE_CHANGED',lambda:self.imported()); self.assertEqual(self.count(),(1,0,0,0,0)); self.assert_slot()

    def test_revocation_at_publication_rolls_back_new_rows_and_copy(self):
        before = self.old_records()
        def guard():
            with self.library.connect() as db: registered = db.execute('select count(*) from versions').fetchone()[0]
            if len(list((self.library.root/'files').glob('*.glb'))) > registered: raise PreviewError(403,'MODEL_WRITE_FORBIDDEN')
        body = self.body(); self.expect('MODEL_WRITE_FORBIDDEN',lambda:self.imported(body,guard=guard))
        self.assertEqual(self.count(),(1,0,0,0,0)); self.assertEqual(self.old_records(),before)
        self.assertEqual(len(list((self.library.root/'files').iterdir())),1); self.assert_slot()
        self.imported(body)

    def test_source_revision_and_file_are_rechecked_after_private_copy(self):
        original = self.models._commit; body = self.body()
        def changed_revision(*args,**kwargs):
            with self.library.connect() as db: db.execute('update versions set revision=revision+1 where id=?',(self.legacy['versionId'],))
            return original(*args,**kwargs)
        with patch.object(self.models,'_commit',side_effect=changed_revision):
            self.expect('RESOURCE_CHANGED',lambda:self.imported(body))
        self.assertEqual(self.count(),(1,0,0,0,0)); self.assert_slot()

    def test_source_fingerprint_recheck_after_final_authorization(self):
        source = self.library.root/'files'/(self.legacy['versionId']+'.glb')
        def guard():
            if len(list((self.library.root/'files').glob('*.glb'))) == 2: source.write_bytes(b'x'*len(self.data))
        self.expect('RESOURCE_CHANGED',lambda:self.imported(guard=guard))
        self.assertEqual(self.count(),(1,0,0,0,0)); self.assertEqual(len(list((self.library.root/'files').iterdir())),1); self.assert_slot()

    def test_capacity_and_publish_failure_preserve_original_and_release_slot(self):
        before = self.old_records()
        for constant,value in [('MAX_VERSIONS',1),('MAX_TOTAL_BYTES',len(self.data)*2-1)]:
            with patch('apps.api.project_model_library.'+constant,value): self.expect('MODEL_LIBRARY_FULL',lambda:self.imported())
        with patch('apps.api.project_model_library._sync_directory',side_effect=OSError('synthetic fsync failure')):
            self.expect('MODEL_STORAGE_UNAVAILABLE',lambda:self.imported())
        self.assertEqual(self.count(),(1,0,0,0,0)); self.assertEqual(self.old_records(),before)
        self.assertEqual(list((self.library.root/'temporary').iterdir()),[]); self.assert_slot()

    def test_two_storage_clients_allow_only_one_import_for_a_legacy_version(self):
        second = ProjectModelLibrary(ModelLibrary(self.library.root,'fixture-project',self.context))
        barrier = Barrier(2); results = []
        originals = (self.models._commit,second._commit)
        def commit(index):
            def call(*args,**kwargs): barrier.wait(timeout=3); return originals[index](*args,**kwargs)
            return call
        def run(models,body):
            try: results.append(models.import_existing(body,'resource-admin',lambda:None)['modelVersionId'])
            except PreviewError as error: results.append(error.code)
        bodies = [self.body(),self.body()]
        with patch.object(self.models,'_commit',side_effect=commit(0)),patch.object(second,'_commit',side_effect=commit(1)):
            threads = [Thread(target=run,args=arguments) for arguments in ((self.models,bodies[0]),(second,bodies[1]))]
            for thread in threads: thread.start()
            for thread in threads: thread.join(timeout=5); self.assertFalse(thread.is_alive())
        self.assertEqual(len(results),2); self.assertEqual(results.count('MODEL_ALREADY_IMPORTED'),1)
        self.assertEqual(self.count(),(2,1,1,1,1)); self.assertEqual(list((self.library.root/'temporary').iterdir()),[])


def add_terrain(library, name, *, identifier=None, created='2026-10-22T00:00:00Z'):
    identifier = identifier or str(uuid4())
    source = {'horizontalCrs':'EPSG:4326','verticalDatum':'EGM2008','samplingCentreCoverageWgs84':[110,32,111,33]}
    report = json.dumps({'source':source},separators=(',',':'))
    with library.library.connect() as db:
        db.execute('insert into terrain_versions values (?,?,?,?,?,?,?,?,?,?)',
            (identifier,'a'*64,'terrain-content:'+identifier,name,'{}',report,hashlib.sha256(report.encode()).hexdigest(),'[]',0,created))
    return identifier


class TerrainCatalogTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.library = ModelLibrary(Path(temporary.name)/'private','fixture-project',str(uuid4()))
        self.terrains = TerrainLibrary(self.library,python_executable=Path(sys.executable).absolute(),start_worker=False)
        self.addCleanup(self.terrains.close)

    def listing(self, **options):
        return self.terrains.listing('fixture-member',lambda:None,access_revision='grant:1',**options)

    def expect(self, code, callback):
        with self.assertRaises(PreviewError) as caught: callback()
        self.assertEqual(caught.exception.code,code)

    def test_empty_and_fixed_ready_metadata_are_discoverable_without_file_or_gis_reads(self):
        self.assertEqual(self.listing()['items'],[])
        identifier = add_terrain(self.terrains,'合成地形')
        with patch.object(self.terrains,'version',side_effect=AssertionError('Discovery is not a file/GIS scan')):
            value = self.listing()
        self.assertEqual(value['items'],[{'terrainVersionId':identifier,'contentRevision':'terrain-content:'+identifier,
            'displayName':'合成地形','sha256':'a'*64,'createdAt':'2026-10-22T00:00:00Z',
            'sourceHorizontalCrs':'EPSG:4326','verticalDatum':'EGM2008','coverageWgs84':[110,32,111,33]}])
        self.assertIsNone(value['nextCursor']); self.assertNotIn(str(self.library.root),json.dumps(value))

    def test_keyset_pagination_is_stable_for_equal_timestamps_and_filters(self):
        identifiers = sorted(add_terrain(self.terrains,'设备地形') for _ in range(3))
        add_terrain(self.terrains,'Other',created='2026-10-21T00:00:00Z')
        first = self.listing(q='设备',limit=2); second = self.listing(q='设备',limit=2,cursor=first['nextCursor'])
        self.assertEqual([item['terrainVersionId'] for item in first['items']+second['items']],identifiers)
        self.assertIsNone(second['nextCursor']); self.assertEqual(first['snapshotRevision'],second['snapshotRevision'])

    def test_cursor_binds_actor_grant_project_query_limit_and_fixed_catalog(self):
        for _ in range(3): add_terrain(self.terrains,'地形')
        cursor = self.listing(limit=1)['nextCursor']
        for arguments in ({'actor':'other-member'}, {'access_revision':'grant:2'}, {'q':'other'}, {'limit':2}):
            options = {'actor':'fixture-member','access_revision':'grant:1','limit':1,'cursor':cursor,**arguments}
            actor = options.pop('actor')
            self.expect('INVALID_REQUEST',lambda:self.terrains.listing(actor,lambda:None,**options))
        self.expect('INVALID_REQUEST',lambda:self.listing(limit=1,cursor=cursor[:-4]+'xxxx'))
        add_terrain(self.terrains,'Added')
        self.expect('SNAPSHOT_EXPIRED',lambda:self.listing(limit=1,cursor=cursor))

    def test_denial_before_and_after_read_and_invalid_paging_return_no_catalog(self):
        for options in ({'limit':0},{'limit':101},{'limit':True},{'q':'x\n'},{'q':'\ud800'},{'q':'x'*201},{'cursor':'forged'}):
            self.expect('INVALID_REQUEST',lambda:self.listing(**options))
        calls = []
        def denied():
            calls.append(True)
            if len(calls)==2: raise PreviewError(403,'FORBIDDEN')
        self.expect('FORBIDDEN',lambda:self.terrains.listing('member',denied,access_revision='grant:1'))


if __name__ == '__main__': unittest.main()
