"""Actual PG registry and ProjectSessions on owned, disposable test databases."""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.project_sessions import ProjectSessions
from apps.api import postgres_project_workspaces as pg
from tests import test_project_registry_postgres as fixture
from tests.test_project_workspaces import ProjectsAuthority
from tools import project_registry_runtime as migration
from tools import model_store_backup as paired, project_store_backup as backups

BASE_URL=os.environ.get('ONTOVIS_REGISTRY_TEST_DATABASE_URL')


@unittest.skipUnless(BASE_URL,'Set ONTOVIS_REGISTRY_TEST_DATABASE_URL for an owned disposable ONTOVis database')
class RegistryRuntimeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo
        cls.driver,cls.sql=psycopg,sql
        cls.database_name='ontovis_runtime_'+uuid4().hex[:12]
        cls.admin_url=make_conninfo(BASE_URL,dbname='postgres')
        cls.target_url=make_conninfo(BASE_URL,dbname=cls.database_name)
        with psycopg.connect(cls.admin_url,autocommit=True) as connection:
            connection.execute(sql.SQL('create database {}').format(sql.Identifier(cls.database_name)))

    @classmethod
    def tearDownClass(cls):
        with cls.driver.connect(cls.admin_url,autocommit=True) as connection:
            connection.execute('select pg_terminate_backend(pid) from pg_stat_activity where datname=%s and pid<>pg_backend_pid()', (cls.database_name,))
            connection.execute(cls.sql.SQL('drop database {}').format(cls.sql.Identifier(cls.database_name)))

    def setUp(self):
        fixture.RegistryPackageTests.setUp(self)
        with self.driver.connect(self.target_url) as connection:
            connection.execute('drop schema if exists '+pg.SCHEMA+' cascade')
        self.scene=self.sessions._workspace(self.workspace).scenes.create(
            {'clientRequestId':str(uuid4()),'displayName':'Retained scene'},
            'synthetic',lambda:None,lambda _:None,lambda *_:None)
        self.backup=self.root/'B1'
        self.receipt=backups.snapshot(self.sessions.registry.root,self.backup,
            library_root=self.sessions.shared.library.root,service_stopped=True)
        self.source=paired._inventory(self.backup)
        self.target=self.root/'runtime'
        class Authority(ProjectsAuthority):
            projects={'SYNTHETIC-A':'Existing project','SYNTHETIC-B':'New project'}
            permissions={'member':{'SYNTHETIC-A':'admin','SYNTHETIC-B':'admin'}}
        self.authority=Authority

    def activate(self, destination=None, backup=None, digest=None):
        return migration.activate_new(backup or self.backup,digest or self.receipt['manifestSha256'],
                                      self.target_url,destination or self.target,service_stopped=True)

    def start(self, root=None, **extra):
        root=root or self.target
        sessions=ProjectSessions('http://127.0.0.1:1',library_root=root/'workbench-library',workspace_root=root/'project-spaces',
            registry_backend='postgres',registry_database_url=self.target_url,factory=self.authority,**extra)
        self.addCleanup(sessions.close)
        return sessions

    def login(self, sessions):
        sid,row=sessions.anonymous()
        sid,view=sessions.login(sid,{'username':'member','password':'synthetic-only','expectedSessionRevision':row.revision},'pg-test')
        return sid,{'expectedSessionRevision':view['sessionRevision'],
                    'projectRef':{'ontobaseConnectionId':'ontobase-primary','projectCode':'SYNTHETIC-A'}}

    def capture(self):
        with self.driver.connect(self.target_url) as connection,connection.cursor() as cursor:
            return pg.rows(cursor)

    def snapshot(self, target):
        return migration.snapshot(self.target/'project-spaces',target,self.target_url,
                                  library_root=self.target/'workbench-library',service_stopped=True)

    def test_native_sessions_read_original_scene_and_recheck_current_permissions(self):
        self.activate();sessions=self.start();sid,body=self.login(sessions)
        opened=sessions.scene_request(sid,'/api/workbench/scenes/open',{**body,'sceneId':self.scene['sceneId']})
        self.assertEqual(opened['sceneRevision'],self.scene['sceneRevision'])
        self.assertEqual(opened['workspaceId'],self.workspace['workspace_id'])
        self.assertFalse((self.target/'project-spaces/registry.sqlite3').exists())
        self.authority.permissions['member']={}
        with self.assertRaises(PreviewError) as caught:
            sessions.scene_request(sid,'/api/workbench/scenes/open',{**body,'sceneId':self.scene['sceneId']})
        self.assertEqual(caught.exception.code,'FORBIDDEN')
        self.authority.permissions['member']={'SYNTHETIC-A':'member','SYNTHETIC-B':'member'}
        before=self.capture()
        for code in ('SYNTHETIC-A','SYNTHETIC-B'):
            with self.assertRaises(PreviewError) as caught:
                sessions.scene_request(sid,'/api/workbench/scenes/create',{**body,
                    'projectRef':{**body['projectRef'],'projectCode':code},'clientRequestId':str(uuid4()),'displayName':'Denied'})
            self.assertEqual(caught.exception.code,'SCENE_WRITE_FORBIDDEN')
        self.assertEqual(self.capture(),before)
        self.assertEqual(paired._inventory(self.backup),self.source)

    def test_runtime_project_creation_is_idempotent_and_project_scope_isolated(self):
        self.activate();sessions=self.start();sid,body=self.login(sessions)
        request=str(uuid4());body={**body,'projectRef':{**body['projectRef'],'projectCode':'SYNTHETIC-B'},
            'clientRequestId':request,'displayName':'Created on PG registry'}
        def create(_):return sessions.scene_request(sid,'/api/workbench/scenes/create',body)
        with ThreadPoolExecutor(max_workers=4) as executor:values=list(executor.map(create,range(4)))
        self.assertEqual(len({item['sceneId'] for item in values}),1)
        row=sessions.registry.lookup('SYNTHETIC-B')
        self.assertEqual(row['state'],'ready')
        with self.assertRaises(PreviewError) as caught:
            sessions.scene_request(sid,'/api/workbench/scenes/open',{
                'expectedSessionRevision':body['expectedSessionRevision'],'projectRef':body['projectRef'],
                'sceneId':self.scene['sceneId']})
        self.assertEqual(caught.exception.code,'NOT_FOUND_OR_FORBIDDEN')
        sessions.close();reopened=self.start()
        self.assertEqual(reopened.registry.lookup('SYNTHETIC-B'),row)

    def test_state_cas_preserves_noop_revision_and_refuses_stale_or_wrong_scope(self):
        self.activate();sessions=self.start();row=sessions.registry.lookup('SYNTHETIC-A')
        original=copy.deepcopy(row);sessions.registry.mark(row,'ready')
        self.assertEqual(row,original)
        sessions.registry.mark(row,'blocked','synthetic evidence')
        self.assertNotEqual(row['registry_revision'],original['registry_revision'])
        for stale in (original,{**row,'project_code':'SYNTHETIC-B'}):
            with self.assertRaises(PreviewError) as caught:sessions.registry.mark(stale,'ready')
            self.assertEqual(caught.exception.code,'REGISTRY_REVISION_CHANGED')
        self.assertEqual(sessions.registry.lookup('SYNTHETIC-A'),row)

    def test_mispaired_copy_wrong_connection_and_wrong_marker_cannot_start(self):
        self.activate();other=self.root/'copied';shutil.copytree(self.target,other)
        wrong_model=self.root/'wrong-model';wrong_model.mkdir()
        for call,code in ((lambda:self.start(other),'REGISTRY_ROOT_MISMATCH'),
                          (lambda:self.start(ontobase_connection_id='other-source'),'REGISTRY_SCOPE_MISMATCH'),
                          (lambda:self.start(model_root=wrong_model),'REGISTRY_ROOT_MISMATCH')):
            with self.assertRaises(PreviewError) as caught:call()
            self.assertEqual(caught.exception.code,code)
        marker=self.target/'project-spaces'/pg.MARKER
        value=json.loads(marker.read_text());value['storeId']=str(uuid4());marker.write_text(json.dumps(value))
        with self.assertRaises(PreviewError) as caught:self.start()
        self.assertEqual(caught.exception.code,'REGISTRY_ROOT_MISMATCH')

    def test_active_runtime_blocks_second_process_and_backup_without_changing_files(self):
        self.activate();sessions=self.start();before=paired._inventory(self.target)
        env={**os.environ,'ONTOVIS_REGISTRY_DSN':self.target_url}
        command=[sys.executable,'-m','apps.api.workbench_server','--registry-backend','postgres','--port','0',
            '--library-root',str(self.target/'workbench-library'),'--workspace-root',str(self.target/'project-spaces')]
        result=subprocess.run(command,env=env,cwd=Path(__file__).resolve().parents[1],capture_output=True,timeout=15)
        self.assertEqual(result.returncode,2);self.assertIn(b'REGISTRY_IN_USE',result.stderr)
        with self.assertRaises(PreviewError) as caught:self.snapshot(self.root/'blocked-backup')
        self.assertEqual(caught.exception.code,'REGISTRY_IN_USE')
        self.assertEqual(paired._inventory(self.target),before)
        self.assertFalse((self.root/'blocked-backup').exists())
        sessions.close()
        process=subprocess.Popen(command,env=env,cwd=Path(__file__).resolve().parents[1],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.assertTrue(select.select([process.stdout],[],[],10)[0],'service did not start')
            self.assertEqual(process.stdout.readline().strip(),'ONTOVis evidence workbench ready')
            with self.assertRaises(PreviewError) as caught:pg.RegistryConnection(self.target_url)
            self.assertEqual(caught.exception.code,'REGISTRY_IN_USE')
        finally:
            process.terminate();process.communicate(timeout=10)

    def test_current_pg_rows_and_complete_files_survive_backup_sqlite_restore_and_pg_reactivation(self):
        self.activate();sessions=self.start();sid,body=self.login(sessions)
        created=sessions.scene_request(sid,'/api/workbench/scenes/create',{**body,
            'projectRef':{**body['projectRef'],'projectCode':'SYNTHETIC-B'},'clientRequestId':str(uuid4()),'displayName':'After migration'})
        preparing=sessions.registry.prepare('SYNTHETIC-INCOMPLETE')
        blocked=sessions.registry.prepare('SYNTHETIC-BLOCKED');sessions.registry.mark(blocked,'blocked','synthetic mismatch')
        sessions.close();before=self.capture();files=paired._inventory(self.target)
        backup=self.root/'PG-B2';receipt=self.snapshot(backup)
        backups.verify(backup,receipt['manifestSha256'])
        self.assertEqual(self.capture(),before);self.assertEqual(paired._inventory(self.target),files)
        restored=self.root/'restored';backups.restore_new(backup,restored,receipt['manifestSha256'],service_stopped=True)
        sqlite_sessions=ProjectSessions('http://127.0.0.1:1',library_root=restored/'workbench-library',
                                       workspace_root=restored/'project-spaces',factory=self.authority)
        self.addCleanup(sqlite_sessions.close)
        self.assertEqual(sqlite_sessions.registry.lookup('SYNTHETIC-INCOMPLETE')['workspace_id'],preparing['workspace_id'])
        self.assertEqual(sqlite_sessions.registry.lookup('SYNTHETIC-BLOCKED')['block_reason'],'synthetic mismatch')
        self.assertEqual(sqlite_sessions.registry.summary('SYNTHETIC-B')['sceneCount'],1)
        sqlite_sessions.close()
        with self.driver.connect(self.target_url) as connection:connection.execute('drop schema '+pg.SCHEMA+' cascade')
        recovered=self.root/'pg-recovered';self.activate(recovered,backup,receipt['manifestSha256'])
        service=self.start(recovered);sid,body=self.login(service)
        opened=service.scene_request(sid,'/api/workbench/scenes/open',{**body,
            'projectRef':{**body['projectRef'],'projectCode':'SYNTHETIC-B'},'sceneId':created['sceneId']})
        self.assertEqual(opened['sceneRevision'],created['sceneRevision'])
        self.assertEqual(opened['workspaceId'],created['workspaceId'])
        self.assertEqual(paired._inventory(self.backup),self.source)

    def test_failed_snapshot_keeps_partial_directory_without_manifest_and_releases_ownership(self):
        self.activate();before=self.capture();files=paired._inventory(self.target)
        with patch.object(backups,'_capture',side_effect=paired.BackupError('SYNTHETIC_VERIFY_FAILURE')):
            with self.assertRaises(paired.BackupError):self.snapshot(self.root/'failed')
        self.assertTrue((self.root/'failed').exists());self.assertFalse((self.root/'failed/manifest.json').exists())
        self.assertEqual(self.capture(),before);self.assertEqual(paired._inventory(self.target),files)
        write=migration._write
        def fail_after_write(*args):
            write(*args)
            raise OSError('synthetic late fsync error')
        with patch.object(migration,'_write',side_effect=fail_after_write),self.assertRaises(OSError):
            self.snapshot(self.root/'late-failure')
        self.assertFalse((self.root/'late-failure/manifest.json').exists())
        self.snapshot(self.root/'retry-new')

    def test_external_pg_change_during_copy_prevents_a_published_snapshot(self):
        self.activate();copy_tree=backups._copy_tree;changed=False
        def copying(*args):
            nonlocal changed
            copy_tree(*args)
            if not changed:
                changed=True
                with self.driver.connect(self.target_url) as connection:
                    connection.execute('update '+pg.SCHEMA+".project_workspaces set block_reason='synthetic concurrent change'")
        with patch.object(backups,'_copy_tree',side_effect=copying),self.assertRaises(PreviewError) as caught:
            self.snapshot(self.root/'raced')
        self.assertEqual(caught.exception.code,'REGISTRY_SOURCE_CHANGED')
        self.assertFalse((self.root/'raced/manifest.json').exists())

    def test_occupied_target_and_failed_activation_never_overwrite_or_publish_partial_schema(self):
        with patch.object(migration,'_write',side_effect=OSError('synthetic disk failure')),self.assertRaises(OSError):self.activate()
        with self.driver.connect(self.target_url) as connection:
            self.assertIsNone(connection.execute('select to_regnamespace(%s)',(pg.SCHEMA,)).fetchone()[0])
        self.assertFalse((self.target/'manifest.json').exists())
        self.activate(self.root/'retry')
        before=self.capture()
        with self.assertRaises(PreviewError) as caught:self.activate(self.root/'occupied')
        self.assertEqual(caught.exception.code,'REGISTRY_TARGET_OCCUPIED')
        self.assertFalse((self.root/'occupied').exists());self.assertEqual(self.capture(),before)

    def test_connection_loss_fails_closed_and_initialization_error_releases_pg_owner(self):
        self.activate()
        with patch('apps.api.project_sessions.WorkbenchSessions',side_effect=ValueError('synthetic init error')):
            with self.assertRaisesRegex(ValueError,'synthetic init error'):self.start()
        service=self.start();service.registry.connection.close()
        with self.assertRaises(PreviewError) as caught:service.registry.prepare('MUST-NOT-BE-CREATED')
        self.assertEqual(caught.exception.code,'REGISTRY_CONNECTION_CLOSED')
        service.close();reopened=self.start()
        self.assertIsNone(reopened.registry.lookup('MUST-NOT-BE-CREATED'))

    def test_snapshot_uses_real_readonly_transactions_and_rejects_unknown_runtime_schema(self):
        from psycopg.conninfo import make_conninfo
        self.activate();before=self.capture()
        readonly=make_conninfo(self.target_url,options='-c default_transaction_read_only=on')
        receipt=migration.snapshot(self.target/'project-spaces',self.root/'readonly-backup',readonly,
            library_root=self.target/'workbench-library',service_stopped=True)
        self.assertEqual(receipt['postgresWrites'],0)
        self.assertEqual(self.capture(),before)
        with self.driver.connect(self.target_url) as connection:
            connection.execute('alter table '+pg.SCHEMA+'.project_workspaces add column unknown text')
        with self.assertRaises(PreviewError) as caught:self.start()
        self.assertEqual(caught.exception.code,'REGISTRY_PROFILE_CHANGED')

    def test_dedicated_database_guard_and_database_constraints_reject_scope_changes(self):
        with self.assertRaises(PreviewError) as caught:pg.RegistryConnection(self.admin_url)
        self.assertEqual(caught.exception.code,'REGISTRY_DEDICATED_DATABASE_REQUIRED')
        self.activate();before=self.capture()
        for change in ("state='confirmed'", "ontobase_connection_id='foreign-source'"):
            with self.assertRaises(self.driver.IntegrityError):
                with self.driver.connect(self.target_url) as connection:
                    connection.execute('update '+pg.SCHEMA+'.project_workspaces set '+change)
        self.assertEqual(self.capture(),before)
        service=self.start()
        with patch.object(pg,'MAX_WORKSPACES',1):
            self.assertEqual(service.registry.prepare('SYNTHETIC-A')['workspace_id'],self.workspace['workspace_id'])
            with self.assertRaises(PreviewError) as caught:service.registry.prepare('OVER-CAPACITY')
            self.assertEqual(caught.exception.code,'REGISTRY_CAPACITY_REACHED')
        self.assertEqual(self.capture(),before)

    def test_terminated_pg_owner_does_not_reconnect_or_create_a_project(self):
        self.activate();sessions=self.start();pid=sessions.registry.connection.db.info.backend_pid
        with self.driver.connect(self.target_url) as connection:
            self.assertTrue(connection.execute('select pg_terminate_backend(%s) where exists('
                'select 1 from pg_stat_activity where pid=%s and datname=%s)',(pid,pid,self.database_name)).fetchone()[0])
        with self.assertRaises(PreviewError) as caught:sessions.registry.prepare('MUST-NOT-RECONNECT')
        self.assertEqual(caught.exception.code,'REGISTRY_POSTGRES_UNAVAILABLE')
        sessions.close();other=self.start()
        self.assertIsNone(other.registry.lookup('MUST-NOT-RECONNECT'))


if __name__=='__main__':unittest.main()
