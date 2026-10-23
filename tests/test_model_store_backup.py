"""Offline backup safety on synthetic real GLB, SQLite, scenes and terrain."""
from contextlib import closing
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.terrain_library import TerrainLibrary
from tests import test_legacy_scene_sources as sources
from tests.test_terrain_library import FAKE_PROCESSOR
import tools.model_store_backup as backup
from apps.api.imagery_library import ImageryLibrary


class ModelStoreBackupTests(unittest.TestCase):
    def add_imagery(self):
        images=ImageryLibrary(self.fixture.fixture.library,python_executable=sys.executable)
        identifier=str(uuid4());directory=images.root/'versions'/identifier;directory.mkdir()
        source=b'II*\x00synthetic-imagery-source';texture=b'\x89PNG\r\n\x1a\nsynthetic-texture'
        (directory/'source.tif').write_bytes(source);(directory/'texture.png').write_bytes(texture)
        source_sha=hashlib.sha256(source).hexdigest();manifest={'bytes':len(texture),'sha256':hashlib.sha256(texture).hexdigest(),'mediaType':'image/png'}
        metadata={'displayName':'Synthetic overview','acquiredAt':'2026-10-13'}
        report={'schemaVersion':1,'purpose':'overview','fieldAccuracyVerified':False,'heightDataUsed':False}
        report_sha=backup._digest(report);revision='imagery:'+backup._digest([source_sha,metadata,report_sha,manifest])
        with self.fixture.fixture.library.connect() as db:
            db.execute('insert into imagery_versions values (?,?,?,?,?,?,?,?,?,?)',(identifier,source_sha,revision,'Synthetic overview',json.dumps(metadata),json.dumps(report),report_sha,json.dumps(manifest),len(source)+len(texture),'2026-10-23T00:00:00Z'))
        return directory

    def test_imagery_source_texture_and_metadata_roundtrip_as_a_paired_backup(self):
        self.add_imagery();before=self.source_state();result=self.snapshot();restored=self.root/'restored-imagery'
        backup.restore_new(self.destination,restored,result['manifestSha256'],service_stopped=True)
        self.assertEqual(self.tree(restored/'workbench-library'),before[0]);self.assertEqual(self.source_state(),before)

    def test_changed_registered_imagery_texture_or_source_blocks_backup(self):
        directory=self.add_imagery();original=(directory/'texture.png').read_bytes()
        (directory/'texture.png').write_bytes(original[:-1]+b'X');self.reject(self.snapshot)
        (directory/'texture.png').write_bytes(original)
        (directory/'source.tif').write_bytes(b'changed source');self.reject(self.snapshot)

    def setUp(self):
        self.fixture = sources.LegacySceneSourcesTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.fixture.root.resolve()
        self.library = self.fixture.fixture.library.root
        self.model = self.fixture.fixed_root.resolve()
        self.destination = self.root/'backup'

    def tree(self, root):
        return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in root.rglob('*') if path.is_file() and not path.is_symlink()}

    def source_state(self):
        return self.tree(self.library), self.tree(self.model)

    def snapshot(self, **options):
        return backup.snapshot(self.library, self.model, self.destination,
                               service_stopped=options.get('service_stopped', True))

    def reject(self, call):
        with self.assertRaises(backup.BackupError): call()

    def activate(self):
        f = self.fixture.fixture
        return f.activate({**f.body, 'receipt': self.fixture.check()['receipt'],
                           'clientRequestId': str(uuid4())}, validator=self.fixture.sources)

    def add_terrain(self):
        executable = self.root/'fake-worker'
        executable.write_text('#!'+sys.executable+'\n'+FAKE_PROCESSOR); executable.chmod(0o700)
        terrain = TerrainLibrary(self.fixture.fixture.library, python_executable=executable)
        try:
            data = b'II*\x00synthetic-tiff-only'
            metadata = {'clientRequestId': str(uuid4()), 'displayName': 'Synthetic terrain',
                        'sourceNote': 'Synthetic fixture', 'licenseNote': 'Synthetic fixture',
                        'rightsDeclared': True, 'verticalDatum': 'EGM2008', 'heightUnit': 'm'}
            job = terrain.upload(io.BytesIO(data), len(data), metadata, 'synthetic-admin', lambda: None)
            deadline = time.monotonic()+4
            while time.monotonic() < deadline:
                result = terrain.job(job['jobId'], lambda: None)
                if result['state'] in ('ready', 'failed'): break
                time.sleep(.01)
            self.assertEqual(result['state'], 'ready')
            return terrain.root/'versions'/result['terrainVersionId']
        finally: terrain.close()

    def test_unregistered_roundtrip_preserves_every_file_without_initializing_app(self):
        kept = self.library/'temporary'/'upload-preserve.glb'; kept.write_bytes(b'keep incomplete input')
        (self.model/'unrecognized-note.txt').write_text('keep unknown regular files')
        before = self.source_state()
        with (patch('apps.api.model_library.ModelLibrary.__init__', side_effect=AssertionError('No initializer')),
              patch('apps.api.terrain_library.TerrainLibrary.__init__', side_effect=AssertionError('No initializer'))):
            result = self.snapshot()
            backup.verify(self.destination, result['manifestSha256'])
            restored = self.root/'restored'
            backup.restore_new(self.destination, restored, result['manifestSha256'], service_stopped=True)
        self.assertEqual(self.source_state(), before)
        self.assertEqual(self.tree(restored/'workbench-library'), before[0])
        self.assertEqual(self.tree(restored/'workbench-model'), before[1])
        self.assertTrue(kept.exists())
        self.assertEqual(self.destination.stat().st_mode & 0o777, 0o700)
        self.assertTrue(all(path.stat().st_mode & 0o777 == 0o600
                            for path in self.destination.rglob('*') if path.is_file()))

    def test_active_scenes_registry_audits_catalog_keys_and_terrain_survive_exactly(self):
        self.activate(); self.add_terrain(); before = self.source_state()
        with closing(sqlite3.connect(self.library/'library.sqlite3')) as db:
            names = {row[0] for row in db.execute("select name from sqlite_master where type='table'")}
            keys = [db.execute('select '+column+' from '+table).fetchone()[0] for table, column in
                    [('scene_catalog', 'cursor_key'), ('project_model_catalog', 'cursor_secret'),
                     ('terrain_catalog', 'cursor_secret')]]
        self.assertTrue({'scene_audit', 'scene_requests', 'legacy_scene_registry_audit',
                         'legacy_scene_registry_requests', 'project_model_audit'} <= names)
        result = self.snapshot(); restored = self.root/'restored'
        backup.restore_new(self.destination, restored, result['manifestSha256'], service_stopped=True)
        self.assertEqual(self.source_state(), before)
        self.assertEqual(self.tree(restored/'workbench-library'), before[0])
        with closing(sqlite3.connect(restored/'workbench-library'/'library.sqlite3')) as db:
            self.assertEqual(db.execute('select state from legacy_scene_registry_state').fetchone()[0], 'active')
            self.assertEqual(db.execute('select count(*) from legacy_scene_registry_entries').fetchone()[0], 2)
            self.assertGreater(db.execute('select count(*) from scene_audit').fetchone()[0], 0)
            with self.assertRaises(PreviewError) as caught: self.fixture.fixture.registry.assert_legacy_writable(db)
            self.assertEqual(caught.exception.code, 'LEGACY_MODEL_READ_ONLY')
        self.assertTrue(all(key not in (self.destination/'manifest.json').read_text() for key in keys))

    def test_offline_declaration_is_required_for_snapshot_and_restore(self):
        before = self.source_state(); self.reject(lambda: self.snapshot(service_stopped=False))
        self.assertFalse(self.destination.exists()); self.assertEqual(self.source_state(), before)
        result = self.snapshot(); restored = self.root/'restored'
        self.reject(lambda: backup.restore_new(self.destination, restored, result['manifestSha256']))
        self.assertFalse(restored.exists())

    def test_existing_or_overlapping_target_is_never_changed(self):
        self.destination.mkdir(); sentinel = self.destination/'keep'; sentinel.write_bytes(b'untouched')
        self.reject(self.snapshot); self.assertEqual(sentinel.read_bytes(), b'untouched')
        for destination in (self.library/'backup', self.model/'backup', self.root):
            with self.subTest(destination=destination.name):
                self.reject(lambda: backup.snapshot(self.library, self.model, destination, service_stopped=True))

    def test_restore_never_overwrites_existing_data(self):
        result = self.snapshot(); restored = self.root/'restored'; restored.mkdir()
        marker = restored/'keep'; marker.write_bytes(b'untouched')
        self.reject(lambda: backup.restore_new(self.destination, restored, result['manifestSha256'], service_stopped=True))
        self.assertEqual(marker.read_bytes(), b'untouched')

    def test_source_and_parent_symlinks_are_rejected(self):
        alias = self.root/'alias'; alias.symlink_to(self.model, target_is_directory=True)
        self.reject(lambda: backup.snapshot(self.library, alias, self.destination, service_stopped=True))
        linked = self.library/'linked.glb'; linked.symlink_to(self.model/'model.glb')
        self.reject(self.snapshot); self.assertFalse(self.destination.exists())

    def test_hardlinks_and_special_files_are_rejected(self):
        linked = self.library/'linked.glb'; os.link(self.model/'model.glb', linked)
        self.reject(self.snapshot); linked.unlink()
        fifo = self.library/'unsafe-fifo'; os.mkfifo(fifo)
        self.reject(self.snapshot); self.assertFalse(self.destination.exists())

    def test_target_parent_symlink_is_rejected(self):
        alias = self.root/'alias'; alias.symlink_to(self.root, target_is_directory=True)
        self.reject(lambda: backup.snapshot(self.library, self.model, alias/'backup', service_stopped=True))
        self.assertFalse(self.destination.exists())

    def test_sqlite_sidecars_are_refused_without_cleanup(self):
        for suffix in ('-journal', '-wal', '-shm'):
            with self.subTest(suffix=suffix):
                path = Path(str(self.library/'library.sqlite3')+suffix); path.write_bytes(b'not discarded')
                self.reject(self.snapshot); self.assertEqual(path.read_bytes(), b'not discarded'); path.unlink()
        self.assertFalse(self.destination.exists())

    def test_database_corruption_and_foreign_key_break_are_refused(self):
        database = self.library/'library.sqlite3'; raw = database.read_bytes()
        database.write_bytes(b'not SQLite'); self.reject(self.snapshot); database.write_bytes(raw)
        with closing(sqlite3.connect(database)) as db:
            db.execute('update bindings set version_id=?', (str(uuid4()),)); db.commit()
        self.reject(self.snapshot); self.assertFalse(self.destination.exists())

    def test_exclusive_database_writer_prevents_snapshot(self):
        with closing(sqlite3.connect(self.library/'library.sqlite3')) as db:
            db.execute('begin exclusive')
            self.reject(self.snapshot)
        self.assertFalse(self.destination.exists())

    def test_registered_glb_and_fixed_model_sha_or_scope_mismatch_are_refused(self):
        path = next((self.library/'files').glob('*.glb')); raw = path.read_bytes()
        path.unlink(); self.reject(self.snapshot); path.write_bytes(raw+b'x'); self.reject(self.snapshot)
        path.write_bytes(raw); config = self.model/'model.json'; value = json.loads(config.read_text())
        config.write_text(json.dumps({**value, 'projectCode': 'wrong-project'})); self.reject(self.snapshot)
        config.write_text(json.dumps(value)); fixed = self.model/'model.glb'; fixed.write_bytes(fixed.read_bytes()+b'x')
        self.reject(self.snapshot); self.assertFalse(self.destination.exists())

    def test_terrain_missing_and_tampered_artifacts_or_report_are_refused(self):
        directory = self.add_terrain()
        for path in (directory/'source.tif', directory/'derived'/'heights.f64', directory/'derived'/'report.json'):
            with self.subTest(artifact=path.name):
                raw = path.read_bytes(); path.unlink(); self.reject(self.snapshot)
                path.write_bytes(raw+b'x'); self.reject(self.snapshot); path.write_bytes(raw)
        self.assertFalse(self.destination.exists())

    def test_terrain_database_manifest_cannot_escape_or_lie_about_total_bytes(self):
        self.add_terrain()
        with closing(sqlite3.connect(self.library/'library.sqlite3')) as db:
            identifier, raw = db.execute('select id,manifest from terrain_versions').fetchone()
            manifest = json.loads(raw); manifest[0]['artifactId'] = '../outside'
            db.execute('update terrain_versions set manifest=? where id=?', (json.dumps(manifest), identifier)); db.commit()
            self.reject(self.snapshot)
            db.execute('update terrain_versions set manifest=?,total_bytes=total_bytes+1 where id=?', (raw, identifier)); db.commit()
            self.reject(self.snapshot)
        self.assertFalse(self.destination.exists())

    def test_external_manifest_sha_is_required_and_wrong_package_is_rejected(self):
        result = self.snapshot()
        for digest in ('', 'bad', '0'*64, None):
            with self.subTest(digest=digest): self.reject(lambda: backup.verify(self.destination, digest))
        (self.model/'second-capture-note').write_text('A different complete source capture')
        other = self.root/'other'; second = backup.snapshot(self.library, self.model, other, service_stopped=True)
        self.assertNotEqual(second['manifestSha256'], result['manifestSha256'])
        backup.verify(other, second['manifestSha256'])
        self.reject(lambda: backup.verify(other, result['manifestSha256']))

    def test_manifest_tamper_and_extra_or_changed_backup_file_are_rejected(self):
        result = self.snapshot(); manifest = self.destination/'manifest.json'; raw = manifest.read_bytes()
        manifest.write_text('{}'); self.reject(lambda: backup.verify(self.destination, result['manifestSha256']))
        manifest.write_bytes(raw); extra = self.destination/'workbench-model'/'extra'; extra.write_bytes(b'extra')
        self.reject(lambda: backup.verify(self.destination, result['manifestSha256'])); extra.unlink()
        model = self.destination/'workbench-model'/'model.glb'; model.write_bytes(model.read_bytes()+b'x')
        self.reject(lambda: backup.verify(self.destination, result['manifestSha256']))
        restored = self.root/'restored'
        self.reject(lambda: backup.restore_new(self.destination, restored, result['manifestSha256'], service_stopped=True))
        self.assertFalse(restored.exists())

    def test_source_change_during_copy_leaves_incomplete_target(self):
        copy_file = backup._copy_file; changed = False
        def mutate(source, target):
            nonlocal changed
            copy_file(source, target)
            if not changed:
                changed = True; path = self.model/'model.glb'; path.write_bytes(path.read_bytes()+b'changed')
        with patch.object(backup, '_copy_file', side_effect=mutate): self.reject(self.snapshot)
        self.assertTrue(self.destination.exists()); self.assertFalse((self.destination/'manifest.json').exists())

    def test_copy_interruption_keeps_private_incomplete_target_and_source(self):
        before = self.source_state()
        copy_file = backup._copy_file
        def interrupt(source, target):
            copy_file(source, target); raise OSError('injected disk failure after copying data')
        with patch.object(backup, '_copy_file', side_effect=interrupt): self.reject(self.snapshot)
        self.assertTrue(self.destination.exists()); self.assertFalse((self.destination/'manifest.json').exists())
        self.assertTrue(self.tree(self.destination))
        self.assertEqual(self.destination.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.source_state(), before)

    def test_restore_interruption_keeps_package_and_existing_source_unchanged(self):
        result = self.snapshot(); before = self.source_state(); package = self.tree(self.destination)
        restored = self.root/'restored'
        with patch.object(backup, '_copy_file', side_effect=OSError('injected disk failure')):
            self.reject(lambda: backup.restore_new(self.destination, restored, result['manifestSha256'], service_stopped=True))
        self.assertTrue(restored.exists()); self.assertFalse((restored/'manifest.json').exists())
        self.assertEqual(self.tree(self.destination), package); self.assertEqual(self.source_state(), before)

    def test_seal_sync_failure_retains_partial_package_that_cannot_verify(self):
        before, sync = self.source_state(), backup._sync
        def fail_seal(path):
            if all((self.destination/name).exists() for name in ('manifest.partial', 'manifest.json')):
                raise OSError('injected seal sync failure')
            sync(path)
        with patch.object(backup, '_sync', side_effect=fail_seal): self.reject(self.snapshot)
        partial = self.destination/'manifest.partial'; self.assertTrue(partial.exists())
        manifest = self.destination/'manifest.json'; self.assertTrue(manifest.exists())
        self.reject(lambda: backup.verify(self.destination, hashlib.sha256(manifest.read_bytes()).hexdigest()))
        self.assertEqual(self.source_state(), before)

    def test_final_seal_directory_swap_cannot_delete_outside_metadata(self):
        outside = self.root/'outside'; outside.mkdir()
        sentinel = outside/'manifest.partial'; sentinel.write_bytes(b'outside metadata must remain')
        moved, before, sync = self.root/'moved-backup', self.source_state(), backup._sync
        def swap_after_parent_sync(path):
            sync(path)
            if path == self.destination.parent:
                self.assertTrue((self.destination/'manifest.partial').is_file())
                self.assertTrue((self.destination/'manifest.json').is_file())
                self.destination.rename(moved)
                self.destination.symlink_to(outside, target_is_directory=True)
        with patch.object(backup, '_sync', side_effect=swap_after_parent_sync): self.reject(self.snapshot)
        self.assertTrue(self.destination.is_symlink()); self.assertTrue((moved/'manifest.partial').exists())
        self.assertEqual(sentinel.read_bytes(), b'outside metadata must remain')
        self.assertEqual(self.source_state(), before)
        digest = hashlib.sha256((moved/'manifest.json').read_bytes()).hexdigest()
        self.reject(lambda: backup.verify(self.destination, digest))
        self.reject(lambda: backup.verify(moved, digest))

    def test_final_source_model_directory_swap_cannot_complete_backup(self):
        outside = self.root/'outside'; outside.mkdir()
        (outside/'model.json').write_text('{}'); (outside/'model.glb').write_bytes(b'different outside model')
        library_before, model_before = self.source_state(); outside_before = self.tree(outside)
        moved, sync = self.root/'moved-model', backup._sync
        def swap_after_parent_sync(path):
            sync(path)
            if path == self.destination.parent:
                self.model.rename(moved)
                self.model.symlink_to(outside, target_is_directory=True)
        with patch.object(backup, '_sync', side_effect=swap_after_parent_sync): self.reject(self.snapshot)
        self.assertTrue(self.model.is_symlink()); self.assertTrue((self.destination/'manifest.partial').exists())
        digest = hashlib.sha256((self.destination/'manifest.json').read_bytes()).hexdigest()
        self.reject(lambda: backup.verify(self.destination, digest))
        self.assertEqual(self.tree(moved), model_before); self.assertEqual(self.tree(self.library), library_before)
        self.assertEqual(self.tree(outside), outside_before)

    def test_cli_roundtrip_and_wrong_external_sha_from_temporary_cwd(self):
        tool, outputs = Path(backup.__file__).resolve(), []
        def command(*args, code=0):
            run = subprocess.run([sys.executable, str(tool), *map(str, args)], cwd=self.root,
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, code, run.stderr); outputs.append(run.stdout)
            return json.loads(run.stdout)
        with closing(sqlite3.connect(self.library/'library.sqlite3')) as db:
            keys = [db.execute('select '+column+' from '+table).fetchone()[0] for table, column in
                    [('scene_catalog', 'cursor_key'), ('project_model_catalog', 'cursor_secret')]]
        before = self.source_state()
        result = command('snapshot', '--library-root', self.library, '--model-root', self.model,
                         '--destination', self.destination, '--service-stopped')
        digest = result['manifestSha256']
        command('verify', '--backup-root', self.destination, '--expected-manifest-sha256', digest)
        rejected, restored = self.root/'rejected', self.root/'cli-restored'
        failure = command('restore-new', '--backup-root', self.destination, '--expected-manifest-sha256', '0'*64,
                          '--destination', rejected, '--service-stopped', code=2)
        self.assertEqual(failure['state'], 'failed'); self.assertFalse(rejected.exists())
        command('restore-new', '--backup-root', self.destination, '--expected-manifest-sha256', digest,
                '--destination', restored, '--service-stopped')
        self.assertEqual(self.tree(restored/'workbench-library'), before[0]); self.assertEqual(self.source_state(), before)
        self.assertTrue(all(key not in output for output in outputs for key in keys))


if __name__ == '__main__': unittest.main()
