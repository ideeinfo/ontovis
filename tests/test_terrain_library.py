"""Real SQLite/background-thread terrain lifecycle with a controlled fake worker.

These tests validate queue/storage/auth boundaries, not real GIS processing.
"""
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.model_library import ModelLibrary
from apps.api.terrain_library import TerrainLibrary


FAKE_PROCESSOR=r'''import argparse,hashlib,json,os,struct,sys,time
from pathlib import Path
control=Path(__file__).with_suffix('.control')
settings=json.loads(control.read_text()) if control.exists() else {}
parser=argparse.ArgumentParser();parser.add_argument('source');parser.add_argument('output')
parser.add_argument('--vertical-datum');parser.add_argument('--source',dest='source_note');parser.add_argument('--license');parser.add_argument('--height-unit');parser.add_argument('--relative-reference-id');parser.add_argument('--aoi',nargs=4)
a=parser.parse_args(sys.argv[3:])
if settings.get('started'):Path(settings['started']).write_text('started')
if settings.get('gate'):
 while not Path(settings['gate']).exists():time.sleep(.01)
if settings.get('mode')=='fail':print(json.dumps({'code':'INVALID_TERRAIN'}));sys.exit(2)
if settings.get('mode')=='large':sys.stdout.write('x'*70000);sys.stdout.flush();sys.exit(0)
source=Path(a.source).read_bytes();out=Path(a.output);out.mkdir(mode=0o700)
files={'heights.f64':struct.pack('<4d',1,1,1,1),'mask.u8':bytes([1,1,1,1]),'positions.f32':struct.pack('<12f',0,1,0,1,1,0,0,1,1,1,1,1),'triangles.u32':struct.pack('<6I',0,2,1,1,2,3)}
artifacts=[]
for name,data in files.items():
 (out/name).write_bytes(data);os.chmod(out/name,0o600)
 artifacts.append({'artifactId':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'format':name.split('.')[-1]})
report={'schemaVersion':1,'state':'ready','source':{'sha256':hashlib.sha256(source).hexdigest(),'bytes':len(source),'width':2,'height':2,'verticalDatum':a.vertical_datum},'mesh':{'rows':2,'columns':2,'triangles':2},'artifacts':artifacts,'externalResourcesFetched':0}
(out/'report.json').write_text(json.dumps(report,separators=(',',':')));os.chmod(out/'report.json',0o600)
if settings.get('mode')=='tamper':(out/'positions.f32').write_bytes(bytes(48))
print(json.dumps(report))
'''


class Guard:
    def __init__(self): self.allowed=True; self.calls=0
    def __call__(self):
        self.calls+=1
        if not self.allowed: raise PreviewError(403,'SCENE_WRITE_FORBIDDEN')


class TerrainLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root=Path(self.tmp.name)
        self.model=ModelLibrary(self.root/'private','fixture-project',str(uuid4()))
        self.executable=self.root/'fake-worker'; self.executable.write_text('#!'+sys.executable+'\n'+FAKE_PROCESSOR); self.executable.chmod(0o700)
        self.control=self.executable.with_suffix('.control'); self.control.write_text('{}')
        self.libraries=[]
        self.addCleanup(self.close_all)
        self.guard=Guard(); self.data=b'II*\x00'+b'synthetic-raw-geotiff-input'

    def close_all(self):
        for library in self.libraries: library.close()

    def library(self,**kwargs):
        result=TerrainLibrary(self.model,python_executable=self.executable,**kwargs);self.libraries.append(result);return result

    def metadata(self,**changes):
        return {'clientRequestId':str(uuid4()),'displayName':'合成地形','sourceNote':'Synthetic fixture',
                'licenseNote':'Synthetic test data','rightsDeclared':True,'verticalDatum':'EGM2008','heightUnit':'m',**changes}

    def upload(self,library,metadata=None,guard=None,data=None):
        data=self.data if data is None else data
        return library.upload(io.BytesIO(data),len(data),metadata or self.metadata(),'fixture-admin',guard or self.guard)

    def wait(self,library,job_id,state=None):
        deadline=time.monotonic()+4
        while time.monotonic()<deadline:
            item=library.job(job_id,lambda:None)
            if item['state']==state or state is None and item['state'] in ('ready','failed','cancelled'): return item
            time.sleep(.01)
        self.fail('The bounded test job did not reach '+str(state))

    def expect(self,code,fn):
        with self.assertRaises(PreviewError) as caught:fn()
        self.assertEqual(caught.exception.code,code)

    def blocked_worker(self):
        gate=self.root/'gate'; started=self.root/'started';self.control.write_text(json.dumps({'gate':str(gate),'started':str(started)}))
        library=self.library();item=self.upload(library)
        deadline=time.monotonic()+3
        while not started.exists() and time.monotonic()<deadline:time.sleep(.01)
        self.assertTrue(started.exists())
        return library,item,gate

    def test_real_background_process_registers_fixed_private_artifacts(self):
        library=self.library();item=self.upload(library);done=self.wait(library,item['jobId'])
        self.assertEqual(done['state'],'ready');self.assertNotEqual(item['jobRevision'],done['jobRevision'])
        version=library.version(done['terrainVersionId'],lambda:None)
        self.assertEqual(version['sha256'],hashlib.sha256(self.data).hexdigest())
        self.assertNotIn(str(self.root),json.dumps(version));self.assertNotIn('actor',done)
        for artifact in version['artifacts']:
            self.assertEqual(len(library.content(version['terrainVersionId'],artifact['artifactId'],artifact['sha256'],lambda:None)),artifact['bytes'])
        self.assertEqual(list((library.root/'temporary').iterdir()),[])
        self.assertNotIn('source.tif',json.dumps(version['report']))

    def test_upload_idempotency_matches_actor_payload_and_stream_bytes(self):
        library=self.library(start_worker=False);metadata=self.metadata();first=self.upload(library,metadata)
        self.assertEqual(self.upload(library,metadata)['jobId'],first['jobId'])
        self.expect('REQUEST_CONFLICT',lambda:self.upload(library,{**metadata,'displayName':'different'}))
        self.expect('REQUEST_CONFLICT',lambda:self.upload(library,metadata,data=b'x'*len(self.data)))
        with self.model.connect() as db:self.assertEqual(db.execute('select count(*) from terrain_jobs').fetchone()[0],1)

    def test_request_scope_is_per_real_actor(self):
        library=self.library(start_worker=False);metadata=self.metadata();first=self.upload(library,metadata)
        other=library.upload(io.BytesIO(self.data),len(self.data),metadata,'different-authorized-admin',lambda:None)
        self.assertNotEqual(first['jobId'],other['jobId'])

    def test_queue_capacity_is_reserved_before_receiving_bytes(self):
        library=self.library(start_worker=False);self.upload(library);self.upload(library)
        class NeverRead:
            def read(self,*_):raise AssertionError('The full queue must reject before reading bytes')
        self.expect('TERRAIN_BUSY',lambda:library.upload(NeverRead(),len(self.data),self.metadata(),'fixture-admin',lambda:None))
        self.assertEqual(len(list((library.root/'temporary').iterdir())),2)

    def test_revoked_admin_cannot_submit_read_cancel_or_replay(self):
        library=self.library(start_worker=False);metadata=self.metadata();item=self.upload(library,metadata)
        self.guard.allowed=False
        self.expect('SCENE_WRITE_FORBIDDEN',lambda:self.upload(library,metadata))
        self.expect('SCENE_WRITE_FORBIDDEN',lambda:library.job(item['jobId'],self.guard))
        self.expect('SCENE_WRITE_FORBIDDEN',lambda:library.cancel(item['jobId'],item['jobRevision'],'fixture-admin',self.guard,str(uuid4())))

    def test_revocation_after_processing_begins_rolls_back_output(self):
        library,item,gate=self.blocked_worker();self.guard.allowed=False;gate.write_text('release')
        done=self.wait(library,item['jobId'])
        self.assertEqual(done['state'],'failed');self.assertEqual(done['errorCode'],'SCENE_WRITE_FORBIDDEN')
        with self.model.connect() as db:self.assertEqual(db.execute('select count(*) from terrain_versions').fetchone()[0],0)
        self.assertEqual(list((library.root/'versions').iterdir()),[]);self.assertEqual(list((library.root/'temporary').iterdir()),[])

    def test_failed_validation_never_generates_ready_version(self):
        self.control.write_text(json.dumps({'mode':'fail'}));library=self.library();item=self.upload(library)
        done=self.wait(library,item['jobId']);self.assertEqual(done['state'],'failed');self.assertEqual(done['errorCode'],'INVALID_TERRAIN')
        self.assertEqual(list((library.root/'versions').iterdir()),[]);self.assertEqual(list((library.root/'temporary').iterdir()),[])

    def test_cancel_queued_checks_revision_and_is_idempotent(self):
        library=self.library(start_worker=False);item=self.upload(library);request=str(uuid4())
        self.expect('JOB_CHANGED',lambda:library.cancel(item['jobId'],'stale','fixture-admin',lambda:None,str(uuid4())))
        result=library.cancel(item['jobId'],item['jobRevision'],'fixture-admin',lambda:None,request)
        self.assertEqual(result['state'],'cancelled')
        self.assertEqual(library.cancel(item['jobId'],item['jobRevision'],'fixture-admin',lambda:None,request)['state'],'cancelled')
        self.expect('REQUEST_CONFLICT',lambda:library.cancel(item['jobId'],'different','fixture-admin',lambda:None,request))
        self.assertEqual(list((library.root/'temporary').iterdir()),[])
        with self.model.connect() as db:self.assertEqual(db.execute("select count(*) from terrain_audit where action='cancel_requested'").fetchone()[0],1)

    def test_cancel_running_process_cannot_later_register_ready(self):
        library,item,gate=self.blocked_worker();current=library.job(item['jobId'],lambda:None)
        cancelled=library.cancel(item['jobId'],current['jobRevision'],'fixture-admin',lambda:None,str(uuid4()))
        self.assertEqual(cancelled['state'],'cancelled');gate.write_text('release')
        deadline=time.monotonic()+2
        while list((library.root/'temporary').iterdir()) and time.monotonic()<deadline:time.sleep(.01)
        self.assertEqual(library.job(item['jobId'],lambda:None)['state'],'cancelled')
        self.assertEqual(list((library.root/'versions').iterdir()),[]);self.assertEqual(list((library.root/'temporary').iterdir()),[])

    def test_cancellation_racing_ready_returns_actual_terminal_state(self):
        library=self.library();item=self.upload(library);done=self.wait(library,item['jobId'])
        result=library.cancel(item['jobId'],item['jobRevision'],'fixture-admin',lambda:None,str(uuid4()))
        self.assertEqual(result['state'],'ready');self.assertEqual(result['terrainVersionId'],done['terrainVersionId'])

    def test_restart_fails_unfinished_and_does_not_reuse_identity(self):
        library=self.library(start_worker=False);item=self.upload(library)
        restored=self.library(start_worker=False)
        done=restored.job(item['jobId'],lambda:None)
        self.assertEqual(done['state'],'failed');self.assertEqual(done['errorCode'],'PROCESSING_INTERRUPTED')
        self.assertEqual(restored.callbacks,{});self.assertEqual(list((restored.root/'temporary').iterdir()),[])

    def test_invalid_metadata_file_size_and_truncated_stream_fail_before_queue(self):
        library=self.library(start_worker=False)
        self.expect('TERRAIN_RIGHTS_REQUIRED',lambda:self.upload(library,self.metadata(rightsDeclared=False)))
        self.expect('VERTICAL_DATUM_CONFLICT',lambda:self.upload(library,self.metadata(verticalDatum=[])))
        self.expect('TERRAIN_LIMIT_EXCEEDED',lambda:library.upload(io.BytesIO(),256*1024*1024+1,self.metadata(),'fixture-admin',lambda:None))
        self.expect('INVALID_TERRAIN',lambda:library.upload(io.BytesIO(b'short'),len(self.data),self.metadata(),'fixture-admin',lambda:None))
        self.assertEqual(list((library.root/'temporary').iterdir()),[])
        with self.model.connect() as db:self.assertEqual(db.execute('select count(*) from terrain_jobs').fetchone()[0],0)

    def test_capacity_includes_pending_and_physical_orphan_bytes(self):
        library=self.library(start_worker=False)
        with patch('apps.api.terrain_library.MAX_VERSIONS',1):
            self.upload(library);self.expect('TERRAIN_LIBRARY_FULL',lambda:self.upload(library))
        library.close()
        restored=self.library(start_worker=False)
        (restored.root/'unexpected-private-orphan').write_bytes(b'x'*100)
        with patch('apps.api.terrain_library.MAX_TOTAL_BYTES',100):self.expect('TERRAIN_LIBRARY_FULL',lambda:self.upload(restored))

    def test_tampered_artifacts_report_and_paths_are_never_returned(self):
        library=self.library();item=self.upload(library);done=self.wait(library,item['jobId']);version=library.version(done['terrainVersionId'],lambda:None)
        self.expect('NOT_FOUND_OR_FORBIDDEN',lambda:library.content(version['terrainVersionId'],'../source.tif','x',lambda:None))
        artifact=next(row for row in version['artifacts'] if row['artifactId']=='positions.f32')
        target=library.root/'versions'/version['terrainVersionId']/'derived'/'positions.f32';target.write_bytes(bytes(artifact['bytes']))
        self.expect('RESOURCE_CHANGED',lambda:library.content(version['terrainVersionId'],'positions.f32',artifact['sha256'],lambda:None))
        report_file=target.parent/'report.json';report_file.write_text('{}')
        self.expect('RESOURCE_CHANGED',lambda:library.version(version['terrainVersionId'],lambda:None))

    def test_symlink_private_content_and_revoked_read_guard_fail(self):
        library=self.library();item=self.upload(library);done=self.wait(library,item['jobId']);version=library.version(done['terrainVersionId'],lambda:None)
        artifact=next(row for row in version['artifacts'] if row['artifactId']=='mask.u8')
        target=library.root/'versions'/version['terrainVersionId']/'derived'/'mask.u8';target.unlink();target.symlink_to(self.executable)
        self.expect('RESOURCE_CHANGED',lambda:library.content(version['terrainVersionId'],'mask.u8',artifact['sha256'],lambda:None))
        denied=Guard();denied.allowed=False
        self.expect('SCENE_WRITE_FORBIDDEN',lambda:library.version(version['terrainVersionId'],denied))

    def test_processor_stdout_and_wall_clock_are_bounded(self):
        self.control.write_text(json.dumps({'mode':'large'}));library=self.library();item=self.upload(library)
        self.assertEqual(self.wait(library,item['jobId'])['errorCode'],'TERRAIN_LIMIT_EXCEEDED');library.close()
        gate=self.root/'never';self.control.write_text(json.dumps({'gate':str(gate)}));restored=self.library(process_timeout=1);item=self.upload(restored)
        self.assertEqual(self.wait(restored,item['jobId'])['errorCode'],'TERRAIN_LIMIT_EXCEEDED')

    def test_processor_tamper_and_publish_failure_roll_back_registration(self):
        self.control.write_text(json.dumps({'mode':'tamper'}));library=self.library();item=self.upload(library)
        self.assertEqual(self.wait(library,item['jobId'])['state'],'failed');library.close()
        self.control.write_text('{}');restored=self.library()
        with patch('apps.api.terrain_library.os.replace',side_effect=OSError('synthetic publish failure')):
            item=self.upload(restored);done=self.wait(restored,item['jobId']);self.assertEqual(done['state'],'failed')
        with self.model.connect() as db:self.assertEqual(db.execute('select count(*) from terrain_versions').fetchone()[0],0)
        self.assertEqual(list((restored.root/'versions').iterdir()),[])

    def test_final_authorization_failure_after_rename_rolls_back_db_and_files(self):
        library=self.library()
        def final_guard():
            if list((library.root/'versions').iterdir()): raise PreviewError(403,'SCENE_WRITE_FORBIDDEN')
        item=self.upload(library,guard=final_guard)
        self.assertEqual(self.wait(library,item['jobId'])['state'],'failed')
        with self.model.connect() as db:
            self.assertEqual(db.execute('select count(*) from terrain_versions').fetchone()[0],0)
            self.assertEqual(db.execute("select count(*) from terrain_audit where action='ready'").fetchone()[0],0)
        self.assertEqual(list((library.root/'versions').iterdir()),[])

    def test_close_interrupts_running_and_recovery_does_not_adopt_partial_output(self):
        library,item,_=self.blocked_worker();library.close()
        terminal=library.job(item['jobId'],lambda:None)
        self.assertEqual(terminal['state'],'failed')
        restored=self.library(start_worker=False)
        self.assertEqual(restored.job(item['jobId'],lambda:None)['state'],'failed')
        self.assertEqual(list((restored.root/'temporary').iterdir()),[])
        self.assertEqual(list((restored.root/'versions').iterdir()),[])

    def test_upload_fsync_failure_has_no_queue_record_or_private_partial(self):
        library=self.library(start_worker=False)
        with patch('apps.api.terrain_library._sync_directory',side_effect=OSError('synthetic fsync failure')):
            self.expect('TERRAIN_STORAGE_UNAVAILABLE',lambda:self.upload(library))
        with self.model.connect() as db:self.assertEqual(db.execute('select count(*) from terrain_jobs').fetchone()[0],0)
        self.assertEqual(list((library.root/'temporary').iterdir()),[])
        self.assertEqual((library.receiving,library.receiving_bytes),(0,0))

    def test_two_jobs_are_queued_with_only_one_active_process(self):
        library,first,gate=self.blocked_worker();second=self.upload(library)
        self.assertEqual(library.job(first['jobId'],lambda:None)['state'],'processing')
        self.assertEqual(library.job(second['jobId'],lambda:None)['state'],'queued')
        self.assertEqual(len(library.processes),1)
        gate.write_text('release')
        self.assertEqual(self.wait(library,first['jobId'])['state'],'ready')
        self.assertEqual(self.wait(library,second['jobId'])['state'],'ready')
        with self.model.connect() as db:self.assertEqual(db.execute('select count(*) from terrain_versions').fetchone()[0],2)

    def test_session_revision_and_auth_closure_are_not_persisted(self):
        library=self.library(start_worker=False);marker='sensitive-in-memory-only-session-revision'
        self.upload(library,self.metadata(expectedSessionRevision=marker))
        with self.model.connect() as db:
            rows=[dict(row) for row in db.execute('select * from terrain_jobs')]
        self.assertNotIn(marker,json.dumps(rows));self.assertNotIn('token',json.dumps(rows));self.assertEqual(len(library.callbacks),1)


if __name__=='__main__':unittest.main()
