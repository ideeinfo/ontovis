"""Staging transactions and concurrent processes in an owned PostgreSQL DB."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

from tests import test_project_registry_postgres as fixture
from tools import model_store_backup as paired, project_store_backup as backups
from tools import project_registry_postgres as migration

BASE_URL = os.environ.get('ONTOVIS_REGISTRY_TEST_DATABASE_URL')


@unittest.skipUnless(BASE_URL, 'Owned PostgreSQL test database is not configured')
class RegistryPostgresIntegrationTests(unittest.TestCase):
    export = fixture.RegistryPackageTests.export

    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo
        cls.driver, cls.sql = psycopg, sql
        cls.database_name = 'ontovis_registry_' + uuid4().hex[:12]
        cls.admin_url = make_conninfo(BASE_URL, dbname='postgres')
        cls.target_url = make_conninfo(BASE_URL, dbname=cls.database_name)
        cls.created = False
        with psycopg.connect(cls.admin_url, autocommit=True) as connection:
            connection.execute(sql.SQL('create database {}').format(sql.Identifier(cls.database_name)))
        cls.created = True

    @classmethod
    def tearDownClass(cls):
        if not cls.created:
            return
        assert cls.database_name.startswith('ontovis_registry_')
        with cls.driver.connect(cls.admin_url, autocommit=True) as connection:
            connection.execute('select pg_terminate_backend(pid) from pg_stat_activity where datname=%s', (cls.database_name,))
            connection.execute(cls.sql.SQL('drop database {}').format(cls.sql.Identifier(cls.database_name)))

    def setUp(self):
        fixture.RegistryPackageTests.setUp(self)
        self.exported = self.export()
        self.sha = self.exported['packageSha256']
        self.request = str(uuid4())
        with self.driver.connect(self.target_url) as connection:
            connection.execute('drop schema if exists '+migration.SCHEMA+' cascade')

    def stage(self, **kwargs):
        return migration.postgres_package(self.package, self.sha, self.request, self.target_url, **kwargs)

    def namespace(self):
        with self.driver.connect(self.target_url) as connection:
            return connection.execute('select to_regnamespace(%s)', (migration.SCHEMA,)).fetchone()[0]

    def rows(self):
        with self.driver.connect(self.target_url) as connection:
            return {name: connection.execute('select to_jsonb(t),xmin::text from '+migration.SCHEMA+'.'+name
                                             +' t order by to_jsonb(t)::text').fetchall()
                    for name in (*migration.COLUMNS, 'migration_receipt')}

    def test_exact_metadata_roundtrip_and_fixed_receipt_leave_source_and_package_untouched(self):
        before=paired._inventory(self.backup)
        packet=(self.package.read_bytes(),self.package.stat().st_mtime_ns)
        result=self.stage()
        self.assertEqual(result['tables'],dict(registry_meta=1,project_workspaces=1,shared_model_store=1))
        self.assertEqual(result['stageReceiptId'],self.request)
        self.assertFalse(result['runtimeActivated']);self.assertFalse(result['engineeringAuthorityChanged'])
        self.assertEqual(self.stage(verify_only=True),result)
        self.assertEqual(paired._inventory(self.backup),before)
        self.assertEqual((self.package.read_bytes(),self.package.stat().st_mtime_ns),packet)
        with self.driver.connect(self.target_url) as connection,connection.cursor() as cur:
            self.assertEqual(migration._read_rows(cur),migration.load_package(self.package,self.sha)['registry'])

    def test_replay_reuses_receipt_and_never_updates_rows_or_row_versions(self):
        result=self.stage();before=self.rows()
        self.assertEqual(self.stage(),result)
        self.assertEqual(self.rows(),before)

    def test_verify_uses_a_real_repeatable_read_read_only_transaction(self):
        expected=self.stage();before=self.rows();observed=[]
        original=migration._verified
        def observe(cur,*args):
            cur.execute('show transaction_read_only');observed.append(cur.fetchone()[0])
            cur.execute('show transaction_isolation');observed.append(cur.fetchone()[0])
            return original(cur,*args)
        with patch.object(migration,'_verified',observe):self.assertEqual(self.stage(verify_only=True),expected)
        self.assertEqual(observed,['on','repeatable read'])
        self.assertEqual(self.rows(),before)

    def test_verify_empty_target_never_creates_schema(self):
        with self.assertRaises(migration.MigrationError) as caught:self.stage(verify_only=True)
        self.assertEqual(caught.exception.code,'REGISTRY_TARGET_EMPTY')
        self.assertIsNone(self.namespace())

    def test_different_request_cannot_adopt_an_existing_target(self):
        self.stage();before=self.rows()
        with self.assertRaises(migration.MigrationError) as caught:
            migration.postgres_package(self.package,self.sha,str(uuid4()),self.target_url)
        self.assertEqual(caught.exception.code,'REGISTRY_TARGET_OCCUPIED')
        self.assertEqual(self.rows(),before)

    def test_changed_source_cannot_overwrite_the_original_request(self):
        self.stage();before=self.rows()
        self.sessions.registry.mark(self.workspace,'blocked','SYNTHETIC_CHANGED')
        backup=self.root/'B1'
        receipt=backups.snapshot(self.sessions.registry.root,backup,library_root=self.sessions.shared.library.root,service_stopped=True)
        package=self.root/'B1-package.json'
        exported=migration.export_package(backup,receipt['manifestSha256'],package)
        with self.assertRaises(migration.MigrationError) as caught:
            migration.postgres_package(package,exported['packageSha256'],self.request,self.target_url)
        self.assertEqual(caught.exception.code,'REGISTRY_REQUEST_CONFLICT')
        self.assertEqual(self.rows(),before)

    def test_changed_staged_rows_are_detected_and_never_repaired_implicitly(self):
        self.stage()
        with self.driver.connect(self.target_url) as connection:
            connection.execute("update "+migration.SCHEMA+".project_workspaces set state='blocked'")
        before=self.rows()
        for verify in (False,True):
            with self.subTest(verify=verify),self.assertRaises(migration.MigrationError) as caught:
                self.stage(verify_only=verify)
            self.assertEqual(caught.exception.code,'REGISTRY_TARGET_CHANGED')
            self.assertEqual(self.rows(),before)

    def test_unknown_existing_schema_is_preserved(self):
        with self.driver.connect(self.target_url) as connection:
            connection.execute('create schema '+migration.SCHEMA)
            connection.execute('create table '+migration.SCHEMA+'.opaque (value text)')
            connection.execute('insert into '+migration.SCHEMA+".opaque values ('synthetic opaque record')")
        with self.assertRaises(migration.MigrationError) as caught:self.stage()
        self.assertEqual(caught.exception.code,'REGISTRY_TARGET_PROFILE_CHANGED')
        with self.driver.connect(self.target_url) as connection:
            self.assertEqual(connection.execute('select * from '+migration.SCHEMA+'.opaque').fetchall(),[('synthetic opaque record',)])

    def test_mid_import_database_error_rolls_back_schema_and_all_rows_then_same_request_can_retry(self):
        def interrupted(cur, registry):
            row=registry['registry_meta'][0]
            cur.execute('insert into '+migration.SCHEMA+'.registry_meta values (%s,%s,%s)',
                        (row['id'],row['schema_version'],row['connection_id']))
            cur.execute('select * from '+migration.SCHEMA+'.synthetic_missing_relation')
        with patch.object(migration,'_write_rows',interrupted),self.assertRaises(migration.MigrationError):self.stage()
        self.assertIsNone(self.namespace())
        self.assertEqual(self.stage()['stageReceiptId'],self.request)

    def test_two_actual_cli_processes_replay_the_same_atomic_import(self):
        command=[sys.executable,'-m','tools.project_registry_postgres','stage','--package',str(self.package),
                 '--package-sha256',self.sha,'--request-id',self.request]
        environment={**os.environ,'ONTOVIS_REGISTRY_STAGE_DSN':self.target_url}
        processes=[]
        try:
            for _ in range(2):
                processes.append(subprocess.Popen(command,cwd=Path(__file__).resolve().parents[1],env=environment,
                                                   stdout=subprocess.PIPE,stderr=subprocess.PIPE))
            results=[]
            for process in processes:
                stdout,stderr=process.communicate(timeout=25)
                self.assertEqual(process.returncode,0,stderr.decode())
                results.append(json.loads(stdout))
            self.assertEqual(results[0],results[1])
            self.assertEqual(self.stage(verify_only=True),results[0])
            self.assertEqual(len(self.rows()['migration_receipt']),1)
        finally:
            for process in processes:
                if process.poll() is None:process.kill();process.wait(timeout=5)
                if process.stdout:process.stdout.close()
                if process.stderr:process.stderr.close()

    def test_competing_request_ids_have_only_one_winner(self):
        def run(request):
            try:return migration.postgres_package(self.package,self.sha,request,self.target_url)
            except migration.MigrationError as error:return error.code
        requests=[self.request,str(uuid4())]
        with ThreadPoolExecutor(max_workers=2) as executor:results=list(executor.map(run,requests))
        self.assertEqual(sum(type(result) is dict for result in results),1)
        self.assertIn('REGISTRY_TARGET_OCCUPIED',results)
        self.assertEqual(len(self.rows()['migration_receipt']),1)
        self.assertEqual(len(self.rows()['project_workspaces']),1)

    def test_database_scope_and_state_constraints_remain_authoritative(self):
        self.stage()
        for statement in ("update "+migration.SCHEMA+".project_workspaces set state='confirmed'",
                          "update "+migration.SCHEMA+".project_workspaces set ontobase_connection_id='foreign-connection'"):
            with self.subTest(statement=statement),self.assertRaises(self.driver.IntegrityError):
                with self.driver.connect(self.target_url) as connection:connection.execute(statement)
        self.assertEqual(self.stage(verify_only=True)['stageReceiptId'],self.request)


if __name__=='__main__':unittest.main()
