"""Current offline-registry profile and safe staging inputs, without PostgreSQL."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.api.project_sessions import ProjectSessions
from tests.test_project_workspaces import ProjectsAuthority
from tools import model_store_backup as paired, project_store_backup as backups
from tools import project_registry_postgres as migration


class RegistryPackageTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve()
        self.sessions=ProjectSessions('http://127.0.0.1:1',library_root=self.root/'shared',
                                     workspace_root=self.root/'projects',factory=ProjectsAuthority)
        self.addCleanup(self.sessions.close)
        self.workspace=self.sessions.registry.prepare('SYNTHETIC-A')
        self.sessions._workspace(self.workspace)
        self.backup=self.root/'B0'
        self.receipt=backups.snapshot(self.sessions.registry.root,self.backup,
                                     library_root=self.sessions.shared.library.root,service_stopped=True)
        self.package=self.root/'registry-package.json'

    def export(self, destination=None):
        return migration.export_package(self.backup,self.receipt['manifestSha256'],destination or self.package)

    def test_verified_backup_exports_exact_original_scope_and_uuid_without_source_changes(self):
        before=paired._inventory(self.backup)
        receipt=self.export();value=migration.load_package(self.package,receipt['packageSha256'])
        self.assertEqual(value['registry']['project_workspaces'],[self.sessions.registry.lookup('SYNTHETIC-A')])
        self.assertEqual(value['sourceRegistrySha256'],self.receipt_source_registry_sha())
        self.assertEqual(value['sourceManifestSha256'],self.receipt['manifestSha256'])
        self.assertEqual(paired._inventory(self.backup),before)
        self.assertEqual(self.package.stat().st_mode & 0o777,0o600)
        self.assertEqual(set(value['registry']),set(migration.COLUMNS))
        self.assertNotIn('password',self.package.read_text().lower())

    def receipt_source_registry_sha(self):
        return hashlib.sha256((self.backup/'project-spaces/registry.sqlite3').read_bytes()).hexdigest()

    def test_source_manifest_or_registered_bytes_change_cannot_export(self):
        with self.assertRaises(paired.BackupError):
            migration.export_package(self.backup,'0'*64,self.package)
        self.assertFalse(self.package.exists())
        (self.backup/'project-spaces/registry.sqlite3').write_bytes(b'changed')
        with self.assertRaises((paired.BackupError,ValueError)):
            self.export()
        self.assertFalse(self.package.exists())

    def test_export_refuses_overwrite_and_output_inside_the_source_backup(self):
        self.export();before=self.package.read_bytes()
        with self.assertRaises(FileExistsError):self.export()
        self.assertEqual(self.package.read_bytes(),before)
        with self.assertRaises(migration.MigrationError) as caught:self.export(self.backup/'new.json')
        self.assertEqual(caught.exception.code,'REGISTRY_SOURCE_OUTPUT_OVERLAP')
        self.assertFalse((self.backup/'new.json').exists())

    def test_unknown_source_schema_is_not_silently_dropped(self):
        with self.sessions.registry.connect() as db:db.execute('create table future_scope (value text)')
        backup=self.root/'B1'
        receipt=backups.snapshot(self.sessions.registry.root,backup,library_root=self.sessions.shared.library.root,service_stopped=True)
        with self.assertRaises(migration.MigrationError) as caught:
            migration.export_package(backup,receipt['manifestSha256'],self.package)
        self.assertEqual(caught.exception.code,'REGISTRY_PROFILE_UNSUPPORTED')
        self.assertFalse(self.package.exists())

    def test_changed_package_or_missing_digest_is_rejected_before_database_use(self):
        receipt=self.export()
        for digest in (None,'bad','0'*64):
            with self.subTest(digest=digest),self.assertRaises(migration.MigrationError):
                migration.postgres_package(self.package,digest,str(uuid4()),'unused-private-config')
        self.package.write_bytes(self.package.read_bytes()+b' ')
        with self.assertRaises(migration.MigrationError) as caught:
            migration.load_package(self.package,receipt['packageSha256'])
        self.assertEqual(caught.exception.code,'REGISTRY_PACKAGE_CHANGED')

    def test_cross_connection_and_duplicate_identity_scope_are_rejected(self):
        receipt=self.export();original=migration.load_package(self.package,receipt['packageSha256'])
        for field,new_value in (('ontobase_connection_id','other-connection'),('workspace_id','not-a-uid'),
                                ('storage_key','../source'),('legacy_context_id','not-a-uid'),
                                ('state','confirmed'),('created_at','2026-10-25T00:00:00')):
            value=copy.deepcopy(original);value['registry']['project_workspaces'][0][field]=new_value
            with self.subTest(field=field),self.assertRaises(migration.MigrationError):migration._package(value)
        value=copy.deepcopy(original);value['registry']['project_workspaces'].append(value['registry']['project_workspaces'][0].copy())
        with self.assertRaises(migration.MigrationError):migration._package(value)

    def test_preparing_and_blocked_spaces_are_retained_without_promoting_them(self):
        ready=self.workspace['workspace_id']
        self.sessions.registry.prepare('SYNTHETIC-B')
        blocked=self.sessions.registry.prepare('SYNTHETIC-C');self.sessions.registry.mark(blocked,'blocked','SYNTHETIC_INCOMPLETE')
        backup=self.root/'incomplete-B1'
        receipt=backups.snapshot(self.sessions.registry.root,backup,library_root=self.sessions.shared.library.root,service_stopped=True)
        exported=migration.export_package(backup,receipt['manifestSha256'],self.package)
        rows=migration.load_package(self.package,exported['packageSha256'])['registry']['project_workspaces']
        self.assertEqual({row['state'] for row in rows},{'ready','preparing','blocked'})
        self.assertEqual(next(row for row in rows if row['workspace_id']==ready)['state'],'ready')
        self.assertEqual(next(row for row in rows if row['project_code']=='SYNTHETIC-C')['block_reason'],'SYNTHETIC_INCOMPLETE')

    def test_duplicate_json_keys_and_extra_protocol_fields_are_refused(self):
        receipt=self.export();raw=self.package.read_bytes()
        duplicate=b'{"format":"wrong",'+raw[1:]
        self.package.write_bytes(duplicate)
        with self.assertRaises(migration.MigrationError):
            migration.load_package(self.package,hashlib.sha256(duplicate).hexdigest())
        for malformed in (b'['*2000+b']'*2000, raw.decode('utf-8').encode('utf-16')):
            self.package.write_bytes(malformed)
            with self.assertRaises(migration.MigrationError):
                migration.load_package(self.package,hashlib.sha256(malformed).hexdigest())
        value=json.loads(raw);value['activateRuntime']=True
        with self.assertRaises(migration.MigrationError):migration._package(value)

    def test_budget_is_enforced_before_reading_an_oversized_package(self):
        self.package.write_bytes(b'x'*32)
        with patch.object(migration,'MAX_PACKAGE_BYTES',16),self.assertRaises(migration.MigrationError) as caught:
            migration.load_package(self.package,hashlib.sha256(b'x'*32).hexdigest())
        self.assertEqual(caught.exception.code,'REGISTRY_BUDGET_EXCEEDED')

    def test_symlink_and_hardlink_packages_are_not_imported(self):
        receipt=self.export();link=self.root/'link.json';link.symlink_to(self.package)
        with self.assertRaises((migration.MigrationError,paired.BackupError,OSError)):
            migration.load_package(link,receipt['packageSha256'])
        link.unlink();os.link(self.package,link)
        with self.assertRaises(migration.MigrationError):migration.load_package(link,receipt['packageSha256'])

    def test_non_ontovis_database_guard_performs_no_schema_or_data_write(self):
        class Cursor:
            def __init__(self):self.statements=[]
            def execute(self,statement):self.statements.append(statement)
            def fetchone(self):return ('synthetic-business-database',)
        cursor=Cursor()
        with self.assertRaises(migration.MigrationError) as caught:migration._target_guard(cursor)
        self.assertEqual(caught.exception.code,'REGISTRY_DEDICATED_DATABASE_REQUIRED')
        self.assertEqual(cursor.statements,['select current_database()'])

    def test_cli_database_error_does_not_print_a_dsn_or_password(self):
        receipt=self.export();environment={**os.environ,'ONTOVIS_REGISTRY_STAGE_DSN':'postgresql://synthetic:never-print-this@127.0.0.1:1/ontovis_synthetic'}
        result=subprocess.run([sys.executable,'-m','tools.project_registry_postgres','stage','--package',str(self.package),
                               '--package-sha256',receipt['packageSha256'],'--request-id',str(uuid4())],
                              cwd=Path(__file__).resolve().parents[1],env=environment,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,2)
        self.assertNotIn(b'never-print-this',result.stderr+result.stdout)
        self.assertNotIn(b'postgresql://',result.stderr+result.stdout)
        self.assertIn(result.stderr.strip(),(b'REGISTRY_POSTGRES_DRIVER_REQUIRED',b'REGISTRY_POSTGRES_UNAVAILABLE'))


if __name__=='__main__':unittest.main()
