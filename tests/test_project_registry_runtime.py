"""Input guards do not need a PostgreSQL driver or a live source service."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.project_sessions import ProjectSessions
from apps.api import postgres_project_workspaces as pg
from tests import test_project_registry_postgres as fixture
from tools import model_store_backup as paired, project_store_backup as backups
from tools import project_registry_runtime as migration


class RegistryRuntimeInputTests(unittest.TestCase):
    setUp = fixture.RegistryPackageTests.setUp

    def test_missing_stop_or_existing_destination_never_connects_to_pg(self):
        with patch.object(pg, 'RegistryConnection') as connect:
            with self.assertRaises(paired.BackupError):
                migration.activate_new(self.backup, self.receipt['manifestSha256'], 'unused', self.root/'new')
            with self.assertRaises(paired.BackupError):
                migration.activate_new(self.backup, self.receipt['manifestSha256'], 'unused', self.backup, service_stopped=True)
            connect.assert_not_called()

    def test_bad_backup_manifest_never_connects_or_creates_destination(self):
        with patch.object(pg, 'RegistryConnection') as connect, self.assertRaises(paired.BackupError):
            migration.activate_new(self.backup, '0'*64, 'unused', self.root/'new', service_stopped=True)
        connect.assert_not_called()
        self.assertFalse((self.root/'new').exists())

    def test_pg_marker_prevents_default_service_and_sqlite_snapshot_from_using_old_registry(self):
        marker = self.sessions.registry.root/pg.MARKER
        marker.write_text(json.dumps({'format':pg.FORMAT,'storeId':str(uuid4()),'connectionId':'ontobase-primary'}))
        before = paired._inventory(self.sessions.registry.root)
        with self.assertRaisesRegex(ValueError, 'REGISTRY_POSTGRES_REQUIRED'):
            ProjectSessions('http://127.0.0.1:1',library_root=self.sessions.shared.library.root,
                            workspace_root=self.sessions.registry.root)
        with self.assertRaises(paired.BackupError) as caught:
            backups.snapshot(self.sessions.registry.root,self.root/'bad-backup',
                library_root=self.sessions.shared.library.root,service_stopped=True)
        self.assertEqual(caught.exception.code, 'REGISTRY_POSTGRES_BACKUP_REQUIRED')
        self.assertEqual(paired._inventory(self.sessions.registry.root), before)

    def test_marker_link_oversize_wrong_version_and_missing_marker_fail_closed(self):
        root = self.root/'marker';root.mkdir();marker=root/pg.MARKER
        for raw in (None, b'x'*1025, b'{', json.dumps({'format':'future','storeId':str(uuid4()),'connectionId':'a'}).encode()):
            if raw is not None:marker.write_bytes(raw)
            with self.subTest(raw=raw is None),self.assertRaises(PreviewError) as caught:pg.read_marker(root)
            self.assertEqual(caught.exception.code,'REGISTRY_MARKER_INVALID')
        marker.unlink();marker.symlink_to(self.package)
        with self.assertRaises(PreviewError):pg.read_marker(root)

    def test_pg_configuration_does_not_fall_back_when_marker_is_missing(self):
        before=paired._inventory(self.sessions.registry.root)
        with patch.object(pg,'RegistryConnection') as connect,self.assertRaises(PreviewError):
            ProjectSessions('http://127.0.0.1:1',library_root=self.sessions.shared.library.root,
                workspace_root=self.sessions.registry.root,registry_backend='postgres',registry_database_url='unused')
        connect.assert_not_called()
        self.assertEqual(paired._inventory(self.sessions.registry.root),before)

    def test_cli_database_failure_never_prints_config_or_secret(self):
        secret='synthetic-runtime-secret-never-print'
        env={**os.environ,'ONTOVIS_REGISTRY_DSN':'postgresql://test:'+secret+'@127.0.0.1:1/ontovis_test'}
        result=subprocess.run([sys.executable,'-m','tools.project_registry_runtime','activate-new','--backup',str(self.backup),
            '--manifest-sha256',self.receipt['manifestSha256'],'--destination',str(self.root/'failed'),
            '--service-stopped'],env=env,cwd=Path(__file__).resolve().parents[1],capture_output=True,timeout=10)
        self.assertEqual(result.returncode,2)
        self.assertNotIn(secret.encode(),result.stderr+result.stdout)
        self.assertNotIn(b'postgresql://',result.stderr+result.stdout)
        self.assertIn(result.stderr.strip(),(b'REGISTRY_POSTGRES_UNAVAILABLE',b'REGISTRY_POSTGRES_DRIVER_REQUIRED'))
        self.assertFalse((self.root/'failed').exists())


if __name__=='__main__':unittest.main()
