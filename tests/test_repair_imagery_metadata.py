from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.imagery_library import ImageryLibrary
from apps.api.model_library import ModelLibrary
from apps.api.storage_lease import StorageInUse, storage_lease
from tools import model_store_backup as backup
from tools import repair_imagery_metadata as repair


class ImageryMetadataRepairTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.library = ModelLibrary(self.root / 'library', 'synthetic-project', str(uuid4()))
        self.images = ImageryLibrary(self.library, python_executable=sys.executable)
        self.target = self.library.root / 'library.sqlite3'
        self.original = self.root / 'original.sqlite3'
        self.version = str(uuid4())
        self.actor = 'synthetic-owner'
        self.payload = {'clientRequestId': str(uuid4()), 'displayName': '旧名称 · 合成影像',
                        'sourceNote': 'Synthetic source', 'licenseNote': 'Synthetic license',
                        'attribution': 'Synthetic author', 'acquiredAt': '2026-10-13',
                        'qualityNote': 'Synthetic overview', 'rightsDeclared': True}
        self.renamed = dict(self.payload, displayName='当前名称 · 合成影像')
        source, self.texture = b'II*\x00synthetic-source', b'\x89PNG\r\n\x1a\nsynthetic-texture'
        self.directory = self.images.root / 'versions' / self.version
        self.directory.mkdir()
        (self.directory / 'source.tif').write_bytes(source)
        (self.directory / 'texture.png').write_bytes(self.texture)
        self.source_sha = backup._fingerprint(self.directory / 'source.tif')[0]['sha256']
        self.texture_sha = backup._fingerprint(self.directory / 'texture.png')[0]['sha256']
        manifest = {'bytes': len(self.texture), 'sha256': self.texture_sha, 'mediaType': 'image/png'}
        report = {'schemaVersion': 1, 'coverageWgs84': [1, 2, 3, 4]}
        report_sha = backup._digest(report)
        self.revision = 'imagery:' + backup._digest([self.source_sha, self.payload, report_sha, manifest])
        original_json = backup._canonical(self.payload).decode()
        with self.library.connect() as db:
            db.execute('insert into imagery_versions values (?,?,?,?,?,?,?,?,?,?)',
                       (self.version, self.source_sha, self.revision, self.payload['displayName'], original_json,
                        backup._canonical(report).decode(), report_sha, backup._canonical(manifest).decode(),
                        len(source) + len(self.texture), '2026-10-23T00:00:00Z'))
            db.execute('insert into imagery_requests values (?,?,?,?,?)',
                       (self.actor, self.payload['clientRequestId'], original_json, self.source_sha, self.version))
        shutil.copyfile(self.target, self.original)
        renamed_json = backup._canonical(self.renamed).decode()
        with self.library.connect() as db:
            db.execute('begin immediate')
            self.guard = db.execute("select sql from sqlite_master where name='imagery_no_update'").fetchone()[0]
            db.execute('drop trigger imagery_no_update')
            db.execute('update imagery_versions set name=?,metadata=?', (self.renamed['displayName'], renamed_json))
            db.execute(self.guard)
            db.execute('update imagery_requests set payload=?', (renamed_json,))

    def run_repair(self, *, apply=False, expected=None, service_stopped=True):
        return repair.repair(self.library.root, self.original, self.version, self.revision,
                             expected or backup._digest(self.renamed), apply=apply, service_stopped=service_stopped)

    def verify_store(self):
        entries, _ = backup._inventory(self.library.root)
        return backup._database(self.library.root, entries)

    def test_repair_restores_strict_backup_and_original_retry_without_changing_display_or_identity(self):
        before = self.target.read_bytes()
        original = self.original.read_bytes()
        with self.assertRaisesRegex(backup.BackupError, 'INVALID_STORE'):
            self.verify_store()
        self.assertEqual(self.run_repair()['status'], 'ready')
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(self.run_repair(apply=True)['status'], 'repaired')
        self.verify_store()
        self.assertEqual(self.original.read_bytes(), original)
        fixed = self.images.upload_result(self.payload, self.source_sha, self.actor, lambda: None)
        self.assertEqual((fixed['state'], fixed['imageryVersionId'], fixed['contentRevision']),
                         ('completed', self.version, self.revision))
        self.assertEqual(fixed['displayName'], self.renamed['displayName'])
        self.assertEqual(fixed['metadata'], self.payload)
        self.assertEqual(self.images.content(self.version, self.revision, self.texture_sha, lambda: None), self.texture)
        with self.assertRaises(PreviewError) as changed:
            self.images.upload_result(self.renamed, self.source_sha, self.actor, lambda: None)
        self.assertEqual(changed.exception.code, 'REQUEST_CONFLICT')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'immutable imagery'), self.library.connect() as db:
            db.execute('update imagery_versions set name=?', ('Unexpected rename',))
        repaired = self.target.read_bytes()
        self.assertEqual(self.run_repair(apply=True)['status'], 'already_repaired')
        self.assertEqual(self.target.read_bytes(), repaired)

    def test_changed_target_or_texture_refuses_without_writes(self):
        before = self.target.read_bytes()
        with self.assertRaisesRegex(backup.BackupError, 'REPAIR_METADATA_CHANGED'):
            self.run_repair(apply=True, expected='0' * 64)
        (self.directory / 'texture.png').write_bytes(b'corrupt')
        with self.assertRaisesRegex(backup.BackupError, 'REGISTERED_FILE_CHANGED'):
            self.run_repair(apply=True)
        self.assertEqual(self.target.read_bytes(), before)

    def test_disagreeing_original_request_is_not_used_as_recovery_evidence(self):
        with closing(sqlite3.connect(self.original)) as db, db:
            db.execute('update imagery_requests set payload=?', (backup._canonical(self.renamed).decode(),))
        before = self.target.read_bytes()
        with self.assertRaisesRegex(backup.BackupError, 'REPAIR_UPLOAD_MISMATCH'):
            self.run_repair(apply=True)
        self.assertEqual(self.target.read_bytes(), before)

    def test_failed_readback_rolls_back_the_update_and_guard(self):
        before = self.target.read_bytes()
        read = repair._image_and_request
        with patch.object(repair, '_image_and_request', side_effect=[
            self._read_version(read, self.target), self._read_version(read, self.original),
            backup.BackupError('REPAIR_VERIFICATION_FAILED'),
        ]):
            with self.assertRaisesRegex(backup.BackupError, 'REPAIR_VERIFICATION_FAILED'):
                self.run_repair(apply=True)
        self.assertEqual(self.target.read_bytes(), before)
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'immutable imagery'), self.library.connect() as db:
            db.execute('update imagery_versions set name=?', ('Unexpected rename',))

    def _read_version(self, read, path):
        with closing(sqlite3.connect(path)) as db:
            db.row_factory = sqlite3.Row
            return read(db, self.version)

    def test_offline_declaration_and_library_lease_are_required(self):
        with self.assertRaisesRegex(backup.BackupError, 'SERVICE_MUST_BE_STOPPED'):
            self.run_repair(apply=True, service_stopped=False)
        with storage_lease((self.library.root,)), self.assertRaises(StorageInUse):
            self.run_repair(apply=True)
