"""Offline recovery on synthetic/copied stores and a real SIGKILL crash window."""
import copy
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.api.model_library import ModelLibrary
from apps.api.model_validation import validate
from apps.api.scene_library import SceneLibrary
from tests.test_model_upload import glb
from tools.model_store_recovery import RecoveryError, apply, preview
import tools.model_store_recovery as recovery


class ModelStoreRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.store=self.root/'private'
        self.library=ModelLibrary(self.store,'synthetic-project',str(uuid4()))
        source=glb(self.root/'source.glb')
        self.model=self.library.save_upload(source,{'expectedSessionRevision':'synthetic-session',
            'expectedLibraryRevision':self.library.listing()['libraryRevision'],'clientRequestId':str(uuid4()),
            'displayName':'Synthetic model','sourceNote':'Synthetic data only','rightsDeclared':True},
            'fixture-admin',validate(source),lambda:None)
        self.library.bind({'modelVersionId':self.model['versionId'],
            'componentKey':self.model['components'][0]['componentKey'],'entityUid':'synthetic-cabinet',
            'expectedEntityRevision':'entity:1','expectedHierarchyRevision':'hierarchy:1',
            'expectedModelRevision':self.model['modelRevision'],'clientRequestId':str(uuid4())},
            'fixture-admin',lambda:None)
        self.scenes=SceneLibrary(self.library)
        scene=self.scenes.create({'displayName':'Synthetic scene','clientRequestId':str(uuid4())},
            'fixture-admin',lambda:None,lambda snapshot:None,lambda snapshot,reviewed,changes:None)
        snapshot=copy.deepcopy(scene['snapshot'])
        snapshot['instances']=[{'sceneModelInstanceId':str(uuid4()),'displayName':'Synthetic instance',
            'modelVersionId':self.model['versionId'],'placement':{'position':{'mode':'local','xM':1,'zM':2},
            'height':{'mode':'local_relative','relativeHeightM':0},'headingDeg':0},'visible':True,
            'positionLocked':False,'rootBinding':None,'componentBindings':[]}]
        self.scene=self.scenes.save({'sceneId':scene['sceneId'],'expectedSceneRevision':scene['sceneRevision'],
            'clientRequestId':str(uuid4()),'snapshot':snapshot,'reviewedEngineering':[],
            'rootBindingChanges':[]},'fixture-admin',lambda:None,lambda snapshot:None,
            lambda snapshot,reviewed,changes:None)
        self.registered=self.store/'files'/(self.model['versionId']+'.glb')

    def state(self,store=None):
        store=store or self.store
        with closing(sqlite3.connect((store/'library.sqlite3').as_uri()+'?mode=ro',uri=True)) as db:
            data='\n'.join(db.iterdump())
        return {'database':hashlib.sha256(data.encode()).hexdigest(),
                'registered':hashlib.sha256((store/'files'/self.registered.name).read_bytes()).hexdigest()}

    def orphan(self,name=None,data=b'orphan',directory='files'):
        path=self.store/directory/(name or str(uuid4())+'.glb');path.write_bytes(data);return path

    def expect(self,code,callback):
        with self.assertRaises(RecoveryError) as caught:callback()
        self.assertEqual(caught.exception.code,code)
        self.assertTrue(caught.exception.public()['repreviewRequired'])
        return caught.exception

    def test_preview_uses_readonly_sqlite_and_does_not_initialize_or_clean_library(self):
        temporary=self.orphan('upload-kept_until_apply.glb',directory='temporary')
        before=self.state();before_names=sorted(str(path.relative_to(self.store)) for path in self.store.rglob('*'))
        connect=sqlite3.connect
        with (patch('apps.api.model_library.ModelLibrary.__init__',side_effect=AssertionError('Do not initialize')),
              patch('tools.model_store_recovery.sqlite3.connect',wraps=connect) as called):
            report=preview(self.store)
        self.assertIn('?mode=ro',called.call_args.args[0]);self.assertTrue(called.call_args.kwargs['uri'])
        self.assertTrue(temporary.exists());self.assertEqual(self.state(),before)
        self.assertEqual(sorted(str(path.relative_to(self.store)) for path in self.store.rglob('*')),before_names)
        self.assertEqual(report['registered']['count'],1);self.assertEqual(report['candidateCount'],1)
        self.assertEqual(report['candidates'][0]['sha256'],hashlib.sha256(b'orphan').hexdigest())
        self.assertEqual(report['candidateBytes'],6);self.assertEqual(len(report['reportSha256']),64)
        self.assertEqual(preview(self.store),report)

    def test_apply_requires_explicit_offline_declaration_and_current_report(self):
        orphan=self.orphan();report=preview(self.store);before=self.state()
        self.expect('OFFLINE_REQUIRED',lambda:apply(self.store,report['reportSha256']))
        self.expect('OFFLINE_REQUIRED',lambda:apply(self.store,report['reportSha256'],service_stopped=1))
        self.expect('REPORT_CHANGED',lambda:apply(self.store,'0'*64,service_stopped=True))
        self.assertTrue(orphan.exists());self.assertEqual(self.state(),before)

    def test_only_strict_known_candidates_are_removed_and_business_data_is_unchanged(self):
        orphan=self.orphan()
        known=[self.orphan(name,directory='temporary') for name in (
            'upload-fixture_1.glb','project-upload-fixture-2.glb','project-calibration-fixture3.glb','scene-geometry-fixture4.json')]
        unknown=[self.orphan(name,directory='temporary') for name in (
            'notes.txt','upload-bad.part.glb','upload-.glb','scene-geometry-unicode名.json')]
        unknown.append(self.orphan('UPPERCASE.glb'))
        directory=self.store/'temporary'/'project-upload-directory.glb';directory.mkdir()
        report=preview(self.store);before=self.state()
        self.assertEqual(report['candidateCount'],5)
        result=apply(self.store,report['reportSha256'],service_stopped=True)
        self.assertEqual(result['removedCount'],5);self.assertFalse(result['deletionIsAtomic'])
        self.assertTrue(all(not path.exists() for path in [orphan,*known]))
        self.assertTrue(all(path.exists() for path in unknown));self.assertTrue(directory.is_dir())
        self.assertEqual(self.state(),before);self.assertEqual(preview(self.store)['candidateCount'],0)

    def test_report_changes_are_rejected_before_any_candidate_deletion(self):
        first=self.orphan();report=preview(self.store);second=self.orphan()
        self.expect('REPORT_CHANGED',lambda:apply(self.store,report['reportSha256'],service_stopped=True))
        self.assertTrue(first.exists());self.assertTrue(second.exists())
        report=preview(self.store);first.write_bytes(b'new content')
        self.expect('REPORT_CHANGED',lambda:apply(self.store,report['reportSha256'],service_stopped=True))
        self.assertTrue(first.exists());self.assertTrue(second.exists())

    def test_registered_missing_or_tampered_file_stops_preview_and_apply(self):
        orphan=self.orphan();report=preview(self.store);original=self.registered.read_bytes()
        self.registered.write_bytes(b'x'*len(original))
        self.expect('REGISTERED_MODEL_CHANGED',lambda:preview(self.store))
        self.expect('REGISTERED_MODEL_CHANGED',lambda:apply(self.store,report['reportSha256'],service_stopped=True))
        self.assertTrue(orphan.exists())
        self.registered.unlink()
        self.expect('REGISTERED_MODEL_CHANGED',lambda:preview(self.store));self.assertTrue(orphan.exists())

    def test_dangling_binding_and_retained_references_stop_before_candidate_inspection_or_deletion(self):
        orphan=self.orphan();report=preview(self.store)
        with closing(sqlite3.connect(self.store/'library.sqlite3')) as db:
            self.assertIsNone(db.execute("select name from sqlite_master where name='terrain_versions'").fetchone())
            self.assertEqual(db.execute('select count(*) from scene_terrain_uses').fetchone()[0],0)
            self.assertEqual(db.execute('pragma foreign_key_check').fetchall(),[])
            # Reproduce an already-damaged store without using the service's
            # foreign-key-protected connection; do not silently repair its rows.
            self.assertEqual(db.execute('pragma foreign_keys').fetchone()[0],0)
            db.execute('delete from versions');db.commit()
            violations=db.execute('pragma foreign_key_check').fetchall()
            self.assertEqual({row[0] for row in violations},{'bindings','scene_resource_uses'})
        before=self.state()
        with patch('tools.model_store_recovery._fingerprint',side_effect=AssertionError('Invalid references must reject before file inspection')):
            self.expect('INVALID_STORE',lambda:preview(self.store))
            self.expect('INVALID_STORE',lambda:apply(self.store,report['reportSha256'],service_stopped=True))
        self.assertTrue(orphan.exists());self.assertTrue(self.registered.exists())
        self.assertEqual(self.state(),before)

    def test_registered_symlink_and_known_orphan_symlink_are_rejected_without_following(self):
        outside=self.root/'outside.glb';outside.write_bytes(self.registered.read_bytes())
        self.registered.unlink();self.registered.symlink_to(outside)
        self.expect('REGISTERED_MODEL_CHANGED',lambda:preview(self.store));self.assertTrue(outside.exists())
        self.registered.unlink();shutil.copyfile(outside,self.registered)
        link=self.store/'files'/(str(uuid4())+'.glb');link.symlink_to(outside)
        self.expect('UNSAFE_STORE',lambda:preview(self.store));self.assertTrue(outside.exists());self.assertTrue(link.is_symlink())

    def test_unknown_symlink_is_preserved_and_never_used_as_a_cleanup_target(self):
        outside=self.root/'outside';outside.write_bytes(b'do not delete')
        link=self.store/'temporary'/'unknown-link';link.symlink_to(outside)
        orphan=self.orphan();report=preview(self.store)
        apply(self.store,report['reportSha256'],service_stopped=True)
        self.assertTrue(link.is_symlink());self.assertEqual(outside.read_bytes(),b'do not delete');self.assertFalse(orphan.exists())

    def test_root_files_temporary_and_database_symlinks_are_rejected(self):
        link=self.root/'alias';link.symlink_to(self.store,target_is_directory=True)
        self.expect('UNSAFE_STORE',lambda:preview(link))
        for name in ('files','temporary','library.sqlite3'):
            path=self.store/name;actual=self.store/(name+'-actual');path.rename(actual);path.symlink_to(actual,target_is_directory=actual.is_dir())
            self.expect('UNSAFE_STORE',lambda:preview(self.store))
            path.unlink();actual.rename(path)

    def test_fixed_table_shape_is_required_instead_of_accepting_an_arbitrary_manifest(self):
        with self.library.connect() as db:db.execute('alter table versions add column unexpected text')
        orphan=self.orphan();self.expect('INVALID_STORE',lambda:preview(self.store));self.assertTrue(orphan.exists())

    def test_versions_view_is_not_treated_as_private_store(self):
        with self.library.connect() as db:
            db.execute('alter table versions rename to hidden_versions')
            db.execute('create view versions as select * from hidden_versions')
        self.expect('INVALID_STORE',lambda:preview(self.store))

    def test_noncanonical_registered_id_cannot_be_used_as_a_file_path(self):
        orphan=self.orphan()
        with closing(sqlite3.connect(self.store/'library.sqlite3')) as db:
            db.execute('update versions set id=?',('../outside',));db.commit()
        self.expect('INVALID_STORE',lambda:preview(self.store));self.assertTrue(orphan.exists())

    def test_wal_format_is_rejected_before_sqlite_can_create_shared_memory_files(self):
        with closing(sqlite3.connect(self.store/'library.sqlite3')) as db:
            self.assertEqual(db.execute('pragma journal_mode=wal').fetchone()[0],'wal')
        names=sorted(path.name for path in self.store.iterdir())
        with patch('tools.model_store_recovery.sqlite3.connect') as connect:
            self.expect('STORE_FORMAT_UNSUPPORTED',lambda:preview(self.store));connect.assert_not_called()
        self.assertEqual(sorted(path.name for path in self.store.iterdir()),names)

    def test_all_candidate_prechecks_finish_before_first_unlink(self):
        first=self.orphan('00000000-0000-4000-8000-000000000001.glb')
        second=self.orphan('00000000-0000-4000-8000-000000000002.glb')
        report=preview(self.store);before=self.state();fingerprint=recovery._fingerprint;calls=[]
        def change_during_precheck(path):
            if path==second:
                calls.append(True)
                if len(calls)==2:path.write_bytes(b'changed after report regeneration')
            return fingerprint(path)
        with patch('tools.model_store_recovery._fingerprint',side_effect=change_during_precheck):
            self.expect('REPORT_CHANGED',lambda:apply(self.store,report['reportSha256'],service_stopped=True))
        self.assertEqual(len(calls),2);self.assertTrue(first.exists());self.assertTrue(second.exists())
        self.assertEqual(self.state(),before)

    def test_active_writer_or_exclusive_transaction_is_bounded_without_deletion(self):
        orphan=self.orphan();report=preview(self.store)
        with self.library.connect() as db:
            db.execute('begin immediate')
            started=time.monotonic()
            self.expect('STORE_BUSY',lambda:apply(self.store,report['reportSha256'],service_stopped=True))
            self.assertLess(time.monotonic()-started,2);self.assertTrue(orphan.exists())
        with self.library.connect() as db:
            db.execute('begin exclusive');started=time.monotonic()
            self.expect('STORE_BUSY',lambda:preview(self.store))
            self.assertLess(time.monotonic()-started,2);self.assertTrue(orphan.exists())
        self.assertEqual(preview(self.store),report)

    def test_partial_filesystem_failure_requires_new_preview_without_claiming_atomicity(self):
        first=self.orphan('00000000-0000-4000-8000-000000000001.glb')
        second=self.orphan('00000000-0000-4000-8000-000000000002.glb')
        report=preview(self.store);before=self.state();unlink=os.unlink;calls=[]
        def fail_second(path,*args,**kwargs):
            if Path(path)==second:raise OSError('synthetic filesystem failure')
            calls.append(str(path));return unlink(path,*args,**kwargs)
        with patch('tools.model_store_recovery.os.unlink',side_effect=fail_second):
            error=self.expect('RECOVERY_PARTIAL_FAILURE',lambda:apply(self.store,report['reportSha256'],service_stopped=True))
        self.assertFalse(first.exists());self.assertTrue(second.exists())
        self.assertEqual(error.public()['removedCandidates'],[{'directory':'files','name':first.name}])
        self.assertFalse(error.public()['deletionIsAtomic']);self.assertEqual(self.state(),before)
        fresh=preview(self.store);self.assertNotEqual(fresh['reportSha256'],report['reportSha256'])
        self.expect('REPORT_CHANGED',lambda:apply(self.store,report['reportSha256'],service_stopped=True))
        self.assertEqual(apply(self.store,fresh['reportSha256'],service_stopped=True)['removedCount'],1)

    def test_copied_store_survives_replace_then_sigkill_with_uncommitted_database_row(self):
        copied=self.root/'offline-copy';shutil.copytree(self.store,copied)
        before=self.state(copied);identifier=str(uuid4())
        script=r'''import json,os,signal,sqlite3,sys
from pathlib import Path
root=Path(sys.argv[1]);identifier=sys.argv[2]
db=sqlite3.connect(root/'library.sqlite3');db.execute('begin immediate')
row=list(db.execute('select * from versions limit 1').fetchone())
source=root/'files'/(row[0]+'.glb');temporary=root/'temporary'/'project-upload-crash.glb'
temporary.write_bytes(source.read_bytes())
with temporary.open('rb') as file:os.fsync(file.fileno())
os.replace(temporary,root/'files'/(identifier+'.glb'))
fd=os.open(root/'files',os.O_RDONLY);os.fsync(fd);os.close(fd)
row[0]=identifier;row[1]=identifier;db.execute('insert into versions values (?,?,?,?,?,?,?,?,?,?,?)',row)
os.kill(os.getpid(),signal.SIGKILL)
'''
        crashed=subprocess.run([sys.executable,'-c',script,str(copied),identifier],capture_output=True,timeout=5)
        self.assertEqual(crashed.returncode,-signal.SIGKILL,crashed.stderr.decode())
        with closing(sqlite3.connect(copied/'library.sqlite3')) as db:
            self.assertEqual(db.execute('select count(*) from versions').fetchone()[0],1)
            self.assertEqual(db.execute('select count(*) from bindings').fetchone()[0],1)
            self.assertEqual(db.execute('select count(*) from scene_resource_uses').fetchone()[0],1)
        report=preview(copied)
        self.assertEqual(report['candidateCount'],1);self.assertEqual(report['candidates'][0]['name'],identifier+'.glb')
        result=apply(copied,report['reportSha256'],service_stopped=True)
        self.assertEqual(result['removedCount'],1);self.assertEqual(self.state(copied),before)
        self.assertEqual(self.state(),before)

    def test_cli_requires_offline_flag_and_does_not_accept_remote_root(self):
        orphan=self.orphan();before=self.state()
        command=[sys.executable,'-m','tools.model_store_recovery']
        result=subprocess.run(command+['preview','--root',str(self.store)],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr);report=json.loads(result.stdout)
        result=subprocess.run(command+['apply','--root',str(self.store),'--expected-report-sha256',report['reportSha256']],
                              capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,2);self.assertIn('--service-stopped',result.stderr)
        self.assertTrue(orphan.exists())
        result=subprocess.run(command+['apply','--root',str(self.store),'--expected-report-sha256',report['reportSha256'],'--service-stopped'],
                              capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr);self.assertFalse(orphan.exists())
        self.assertEqual(self.state(),before)
        result=subprocess.run(command+['preview','--root','https://invalid.example/store'],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,2);self.assertEqual(json.loads(result.stdout)['code'],'INVALID_STORE')


if __name__=='__main__':unittest.main()
