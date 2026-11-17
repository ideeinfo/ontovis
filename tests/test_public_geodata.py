"""Public COG boundary, real crop/import, async permissions and retention.

Remote services are replaced by explicit local COG fixtures in the automated
suite. A separate bounded live-source observation is kept in output.
"""
import copy
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

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform

from apps.api.authority import PreviewError
from apps.api.imagery_library import ImageryLibrary
from apps.api.model_library import ModelLibrary
from apps.api.public_geo_process import fetch
from apps.api.public_geo_sources import asset_url, imagery_group, region
from apps.api.public_geodata import PublicGeoData
from apps.api.session_http import handler_type
from apps.api.terrain_library import TerrainLibrary
from apps.api.workbench_server import WorkbenchSessions
import tests.test_project_model_http as http


def request(**changes):
    lon, lat = transform('EPSG:32649', 'EPSG:4326', [500480], [3699520])
    return {'clientRequestId': str(uuid4()), 'longitude': lon[0], 'latitude': lat[0], 'radiusKm': .5,
            'name': 'Synthetic public overview', 'terrain': True, 'imagery': True, **changes}


def source_item(identifier='S2B_T49SGT_20261013T031635_L2A'):
    prefix = 'https://e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com/sentinel-2-c1-l2a/49/S/GT/2026/10/'+identifier+'/'
    return {'id': identifier, 'bbox': [110, 30, 115, 35], 'properties': {'datetime':'2026-10-13T03:00:00Z','eo:cloud_cover':1},
            'assets': {'visual': {'href': prefix+'TCI.tif'}, 'scl': {'href': prefix+'SCL.tif'}}}


def fixtures(root):
    paths = {}
    for name, count, size, step, dtype in [('data',1,64,30,'float32'),('visual',3,192,10,'uint8'),('scl',1,96,20,'uint8')]:
        path = root/(name+'.tif')
        data = np.full((count,size,size), 100 if name != 'scl' else 4, dtype=dtype)
        if name == 'scl': data[:,20:24,20:24] = 9
        with rasterio.open(path,'w',driver='GTiff',height=size,width=size,count=count,dtype=dtype,
                           crs='EPSG:32649' if name != 'data' else 'EPSG:4326',
                           transform=from_origin(500000,3700000,step,step) if name != 'data' else from_origin(111,33.45,.0003,.0003)) as target:
            target.write(data)
        paths[name] = str(path)
    # Source DEM must really be geographic; enclose the shared UTM center.
    values = np.full((1,100,100),123,dtype='float32')
    lon,lat = transform('EPSG:32649','EPSG:4326',[500480],[3699520])
    with rasterio.open(paths['data'],'w',driver='GTiff',height=100,width=100,count=1,dtype='float32',crs='EPSG:4326',
                       transform=from_origin(lon[0]-.015,lat[0]+.015,.0003,.0003)) as target: target.write(values)
    return paths


class PublicSourceBoundaryTests(unittest.TestCase):
    def expect(self,code,callback):
        with self.assertRaises(PreviewError) as caught: callback()
        self.assertEqual(caught.exception.code,code)

    def test_coordinate_radius_type_and_date_line_limits(self):
        self.assertEqual(region(request())['name'],'Synthetic public overview')
        for change in ({'longitude':float('nan')},{'latitude':84},{'radiusKm':.1},{'radiusKm':11},{'longitude':True},
                       {'terrain':False,'imagery':False},{'name':'\nprivate'},{'longitude':179.999,'radiusKm':10}):
            with self.subTest(change=change),self.assertRaises(PreviewError):region(request(**change))
        self.expect('INVALID_REQUEST',lambda:region({**request(),'url':'http://127.0.0.1'}))

    def test_only_exact_public_cog_urls_are_accepted(self):
        good=source_item();self.assertTrue(asset_url(good,'visual').endswith('/TCI.tif'))
        name='Copernicus_DSM_COG_10_N33_00_E113_00_DEM'
        dem={'assets':{'data':{'href':'s3://copernicus-dem-30m/'+name+'/'+name+'.tif'}}}
        self.assertTrue(asset_url(dem,'data').startswith('https://copernicus-dem-30m.s3.eu-central-1.amazonaws.com/'))
        for url in ('http://127.0.0.1/TCI.tif','https://evil.example/TCI.tif',asset_url(good,'visual')+'?url=http://127.0.0.1',
                    asset_url(good,'visual').replace('https://','https://user@'),asset_url(good,'visual')+'/../private'):
            item=copy.deepcopy(good);item['assets']['visual']['href']=url
            self.expect('PUBLIC_SOURCE_UNAVAILABLE',lambda:asset_url(item,'visual'))

    def test_same_date_selection_requires_full_enclosing_bbox_and_quality(self):
        day,items=imagery_group([source_item()],[111,31,112,32]);self.assertEqual(day,'2026-10-13');self.assertEqual(len(items),1)
        self.expect('PUBLIC_COVERAGE_UNAVAILABLE',lambda:imagery_group([source_item()],[119,31,120,32]))
        cloudy=source_item();cloudy['properties']['eo:cloud_cover']=90
        self.expect('PUBLIC_COVERAGE_UNAVAILABLE',lambda:imagery_group([cloudy],[111,31,112,32]))


class PublicGeoDataTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        self.library=ModelLibrary(self.root/'private','fixture-project',str(uuid4()))
        self.terrains=TerrainLibrary(self.library,python_executable=sys.executable)
        self.images=ImageryLibrary(self.library,python_executable=sys.executable)
        self.manager=PublicGeoData(self.library,self.terrains,self.images)
        self.addCleanup(self.terrains.close);self.addCleanup(self.manager.close)
        self.paths=fixtures(self.root)
        self.item=source_item()

    def expect(self,code,callback):
        with self.assertRaises(PreviewError) as caught: callback()
        self.assertEqual(caught.exception.code,code)

    def crop(self,work,identifier,guard):
        guard()
        return fetch(json.loads((work/'request.json').read_text()),work,
                     source_catalog=lambda collection,bbox:[self.item],source_url=lambda item,key:self.paths[key])

    def wait(self,job):
        deadline=time.monotonic()+25
        while job['state']=='processing' and time.monotonic()<deadline:
            time.sleep(.05);job=self.manager.job(job['jobId'],'synthetic-admin',lambda:None)
        self.assertNotEqual(job['state'],'processing',job)
        return job

    def counts(self):
        with self.library.connect() as db:return [db.execute('select count(*) from '+table).fetchone()[0] for table in ('terrain_versions','imagery_versions')]

    def test_actual_circle_crop_and_import_creates_fixed_resources_and_replay_does_not_duplicate(self):
        body=request()
        with patch.object(self.manager,'_fetch',side_effect=self.crop):
            job=self.wait(self.manager.start(body,'synthetic-admin',lambda:None))
        self.assertEqual(job['state'],'ready',job);self.assertEqual(self.counts(),[1,1])
        terrain=self.terrains.version(job['results']['terrainVersionId'],lambda:None)
        image=self.images.version(job['results']['imageryVersionId'],lambda:None)
        self.assertEqual(terrain['report']['source']['verticalDatum'],'EGM2008')
        self.assertEqual(image['report']['pixelSize'],[20.0,20.0])
        self.assertEqual(image['metadata']['acquiredAt'],'2026-10-13')
        self.assertIn('20 m',image['metadata']['qualityNote'])
        self.assertLess(job['results']['imagery']['validFractionOfCircle'],1)
        self.assertIn('produced using Copernicus WorldDEM-30',terrain['report']['source']['licenseNote'])
        replay=self.manager.start(body,'synthetic-admin',lambda:None)
        self.assertEqual(replay['jobId'],job['jobId']);self.assertEqual(self.counts(),[1,1])
        self.assertEqual(self.manager.job(None,'synthetic-admin',lambda:None)['request']['radiusKm'],.5)
        self.expect('NOT_FOUND_OR_FORBIDDEN',lambda:self.manager.job(None,'another-user',lambda:None))
        self.expect('REQUEST_CONFLICT',lambda:self.manager.start({**body,'name':'Changed'},'synthetic-admin',lambda:None))
        self.assertEqual(list((self.library.root/'temporary').glob('public-geodata-*')),[])

    def test_cancel_and_busy_do_not_import_partial_bytes(self):
        started=Event()
        def wait_cancel(work,identifier,guard):
            started.set()
            while not self.manager.cancelled.wait(.02):guard()
            guard()
        with patch.object(self.manager,'_fetch',side_effect=wait_cancel):
            job=self.manager.start(request(),'synthetic-admin',lambda:None);self.assertTrue(started.wait(2))
            self.expect('PUBLIC_ACQUISITION_BUSY',lambda:self.manager.start(request(),'synthetic-admin',lambda:None))
            self.expect('NOT_FOUND_OR_FORBIDDEN',lambda:self.manager.job(job['jobId'],'another-user',lambda:None))
            current=self.manager.job(job['jobId'],'synthetic-admin',lambda:None)
            self.manager._change(job['jobId'], stage='terrain_source')
            self.expect('PUBLIC_JOB_CHANGED',lambda:self.manager.cancel(current['jobId'],current['jobRevision'],'synthetic-admin',lambda:None))
            current=self.manager.job(job['jobId'],'synthetic-admin',lambda:None)
            self.manager.cancel(current['jobId'],current['jobRevision'],'synthetic-admin',lambda:None)
            final=self.wait(job)
        self.assertEqual(final['state'],'cancelled',final);self.assertEqual(self.counts(),[0,0])

    def test_revoked_guard_stops_before_import_and_is_not_persisted(self):
        live=Event();live.set();started=Event();release=Event()
        def guard():
            if not live.is_set():raise PreviewError(403,'FORBIDDEN')
        def crop(work,identifier,authorize):
            started.set();release.wait(2);authorize()
        with patch.object(self.manager,'_fetch',side_effect=crop):
            job=self.manager.start(request(),'synthetic-admin',guard);self.assertTrue(started.wait(2));live.clear();release.set()
            final=self.wait(job)
        self.assertEqual((final['state'],final['errorCode']),('failed','FORBIDDEN'));self.assertEqual(self.counts(),[0,0])
        with self.library.connect() as db:record=dict(db.execute('select * from public_geo_jobs').fetchone())
        self.assertNotIn('session',str(record).lower());self.assertNotIn('password',str(record).lower())

    def test_failure_after_terrain_retains_successful_version_and_reports_partial_result(self):
        with patch.object(self.manager,'_fetch',side_effect=self.crop),patch.object(self.images,'upload',side_effect=PreviewError(503,'PUBLIC_SOURCE_UNAVAILABLE')):
            final=self.wait(self.manager.start(request(),'synthetic-admin',lambda:None))
        self.assertEqual(final['state'],'failed',final);self.assertEqual(self.counts(),[1,0]);self.assertIn('terrainVersionId',final['results'])
        self.assertNotIn('imageryVersionId',final['results'])

    def test_malformed_worker_report_finishes_failed_instead_of_stranding_processing(self):
        malformed = {'terrain': {'records': [{'itemId': 123}], 'resampling': 'test'}}
        with patch.object(self.manager, '_fetch', return_value=malformed):
            final = self.wait(self.manager.start(request(imagery=False), 'synthetic-admin', lambda:None))
        self.assertEqual((final['state'], final['errorCode']), ('failed', 'PUBLIC_SOURCE_UNAVAILABLE'))
        self.assertEqual(self.counts(), [0, 0])

    def test_restart_recovers_versions_committed_before_manager_result_was_saved(self):
        with patch.object(self.manager, '_fetch', side_effect=self.crop):
            ready = self.wait(self.manager.start(request(), 'synthetic-admin', lambda:None))
        self.assertEqual(ready['state'], 'ready', ready)
        while self.manager.active is not None: time.sleep(.01)
        with self.library.connect() as db:
            db.execute("update public_geo_jobs set state='processing',results='{}',stage='imagery_import' where id=?", (ready['jobId'],))
        restarted = PublicGeoData(self.library, self.terrains, self.images)
        self.addCleanup(restarted.close)
        final = restarted.job(ready['jobId'], 'synthetic-admin', lambda:None)
        self.assertEqual(final['errorCode'], 'PUBLIC_PROCESSING_INTERRUPTED')
        self.assertEqual(final['results']['terrainVersionId'], ready['results']['terrainVersionId'])
        self.assertEqual(final['results']['imageryVersionId'], ready['results']['imageryVersionId'])
        self.assertEqual(self.counts(), [1, 1])

    def test_restart_never_resumes_credentials_or_adopts_partial_output(self):
        body=region(request());identifier=str(uuid4());now='2026-10-23T00:00:00Z'
        with self.library.connect() as db:
            db.execute('insert into public_geo_jobs values (?,?,?,?,?,?,?,?,?,?,?)',(identifier,'synthetic-admin',body['clientRequestId'],json.dumps(body),'processing','queued','old','{}',None,now,now))
        partial=self.library.root/'temporary'/('public-geodata-'+identifier);partial.mkdir();(partial/'partial').write_bytes(b'partial')
        restarted=PublicGeoData(self.library,self.terrains,self.images)
        self.addCleanup(restarted.close)
        value=restarted.job(identifier,'synthetic-admin',lambda:None)
        self.assertEqual((value['state'],value['errorCode']),('failed','PUBLIC_PROCESSING_INTERRUPTED'));self.assertFalse(partial.exists())


class PublicGeoHttpTests(unittest.TestCase):
    request=http.ProjectModelHttpTests.request
    login=http.ProjectModelHttpTests.login
    authority=http.ProjectModelHttpTests.authority

    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup);self.root=Path(directory.name)
        self.sessions=WorkbenchSessions('http://127.0.0.1:1234','fixture-project',http.CONTEXT,library_root=self.root/'private',
                                        terrain_python=Path(sys.executable),factory=http.SceneAuthority)
        self.addCleanup(self.sessions.terrains.close);self.addCleanup(self.sessions.public_geodata.close)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler_type(self.sessions,http.ORIGIN,development=True))
        self.thread=Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.thread.join);self.addCleanup(self.server.shutdown)
        self.admin=self.login('synthetic-public-admin')

    def test_admin_start_is_short_owned_session_conditioned_and_reader_cannot_write(self):
        started,release=Event(),Event()
        def blocked(work,identifier,guard):
            started.set();release.wait(2);guard();raise PreviewError(422,'PUBLIC_COVERAGE_UNAVAILABLE')
        with patch.object(self.sessions.public_geodata,'_fetch',side_effect=blocked):
            begin=time.monotonic();status,value,headers=self.request('/api/workbench/public-geodata/start',request())
            self.assertEqual(status,202,value);self.assertLess(time.monotonic()-begin,1);self.assertEqual(headers['Cache-Control'],'no-store')
            self.assertTrue(started.wait(2))
            reader=self.login('synthetic-reader');self.authority(reader).role='reader'
            self.assertEqual(self.request('/api/workbench/public-geodata/start',request(),client=reader)[0],403)
            self.assertEqual(self.request('/api/workbench/public-geodata/job',{'jobId':value['jobId']},client=reader)[0],404)
            self.assertEqual(self.request('/api/workbench/public-geodata/job',{'jobId':value['jobId']},client=False)[0],401)
            self.assertEqual(self.request('/api/workbench/public-geodata/start',request(),headers={'Origin':'https://evil.example'})[0],403)
            self.assertEqual(self.request('/api/workbench/public-geodata/job',{'jobId':value['jobId'],'expectedSessionRevision':'stale'})[0],409)
            self.assertEqual(self.request('/api/workbench/public-geodata/job/extra',{})[0],404)
            release.set()

class PublicGeoBackupTests(unittest.TestCase):
    def test_existing_paired_backup_restores_public_jobs_and_both_imported_resources(self):
        from tests.test_model_store_backup import ModelStoreBackupTests
        from tools.model_store_backup import restore_new, verify
        fixture = ModelStoreBackupTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        library = fixture.fixture.fixture.library
        terrains = TerrainLibrary(library, python_executable=sys.executable)
        images = ImageryLibrary(library, python_executable=sys.executable)
        manager = PublicGeoData(library, terrains, images)
        self.addCleanup(terrains.close); self.addCleanup(manager.close)
        paths = fixtures(fixture.root)
        def crop(work, identifier, guard):
            guard()
            return fetch(json.loads((work/'request.json').read_text()), work,
                source_catalog=lambda collection,bbox:[source_item()], source_url=lambda item,key:paths[key])
        with patch.object(manager, '_fetch', side_effect=crop):
            job = manager.start(request(), 'synthetic-backup-admin', lambda:None)
            deadline = time.monotonic()+20
            while job['state']=='processing' and time.monotonic()<deadline:
                time.sleep(.05); job=manager.job(job['jobId'],'synthetic-backup-admin',lambda:None)
        self.assertEqual(job['state'], 'ready', job)
        manager.close(); terrains.close()
        before = fixture.source_state()
        receipt = fixture.snapshot()
        checked = verify(fixture.destination, receipt['manifestSha256'])
        target = fixture.root/'restored-public-overview'
        restore_new(fixture.destination, target, receipt['manifestSha256'], service_stopped=True)
        self.assertEqual(fixture.tree(target/'workbench-library'), before[0])
        self.assertEqual(fixture.tree(target/'workbench-model'), before[1])
        self.assertEqual(fixture.source_state(), before)
