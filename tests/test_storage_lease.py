"""Actual process exclusion before SQLite cleanup and during offline copies."""
from pathlib import Path
import selectors
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from apps.api.storage_lease import StorageInUse, storage_lease
from tools import model_store_backup as paired, project_store_backup as projects


ROOT = Path(__file__).resolve().parents[1]
CHILD = '''from pathlib import Path
import sys
from apps.api.storage_lease import StorageInUse,storage_lease
try:
 with storage_lease([Path(p) for p in sys.argv[2:]],shared=sys.argv[1]=='shared'):
  print('held',flush=True)
  sys.stdin.read()
except StorageInUse:
 print('STORAGE_IN_USE',flush=True)
 raise SystemExit(3)
'''


class StorageLeaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.a, self.z = self.root/'a', self.root/'z'
        self.a.mkdir(); self.z.mkdir()

    def stop(self, process):
        if process.poll() is None:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream: stream.close()

    def start(self, command, expected='held'):
        process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(self.stop, process)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            self.assertTrue(selector.select(timeout=8), 'Candidate process did not become ready')
        line = process.stdout.readline().decode().strip()
        if line != expected and process.poll() is not None:
            self.fail(process.stderr.read(4096).decode(errors='replace'))
        self.assertEqual(line, expected)
        return process

    def hold(self, *roots, shared=False):
        return self.start([sys.executable,'-c',CHILD,'shared' if shared else 'exclusive',*map(str,roots)])

    def probe(self, *roots, shared=False):
        return subprocess.run([sys.executable,'-c',CHILD,'shared' if shared else 'exclusive',*map(str,roots)],
                              cwd=ROOT, input=b'', capture_output=True, timeout=8).returncode

    def test_exclusive_directory_lock_blocks_another_process_without_lock_files(self):
        before = self.a.stat().st_mtime_ns
        with storage_lease((self.a,)):
            self.assertEqual(self.probe(self.a), 3)
            self.assertEqual(self.probe(self.a,shared=True), 3)
            self.assertEqual(list(self.a.iterdir()), [])
            self.assertEqual(self.a.stat().st_mtime_ns, before)
        self.assertEqual(self.probe(self.a), 0)

    def test_shared_snapshot_locks_coexist_and_block_a_service(self):
        self.hold(self.a, shared=True)
        self.assertEqual(self.probe(self.a, shared=True), 0)
        self.assertEqual(self.probe(self.a), 3)

    def test_nested_service_roots_cannot_bypass_each_other_but_siblings_can(self):
        child=self.a/'nested';child.mkdir()
        with storage_lease((self.a,)):
            self.assertEqual(self.probe(child),3)
            self.assertEqual(self.probe(self.z),0)
        with storage_lease((child,)):
            self.assertEqual(self.probe(self.a),3)

    def test_busy_later_root_releases_every_partially_acquired_root(self):
        self.hold(self.z)
        with self.assertRaises(StorageInUse):
            with storage_lease((self.z,self.a)):
                self.fail('A busy root was accepted')
        self.assertEqual(self.probe(self.a), 0)
        self.assertEqual(self.probe(self.z), 3)

    def test_exception_and_process_death_release_without_stale_pid_cleanup(self):
        with self.assertRaisesRegex(RuntimeError,'synthetic'):
            with storage_lease((self.a,)):
                raise RuntimeError('synthetic')
        self.assertEqual(self.probe(self.a), 0)
        process=self.hold(self.a)
        process.kill(); process.wait(timeout=5)
        self.assertEqual(self.probe(self.a), 0)

    def test_symlink_and_non_directory_roots_are_refused(self):
        link=self.root/'link'; link.symlink_to(self.a,target_is_directory=True)
        file=self.root/'file'; file.write_bytes(b'synthetic')
        for path in (link, link/'nested', file):
            with self.subTest(path=path), self.assertRaises((ValueError,OSError)):
                with storage_lease((path,),create=True):
                    self.fail('An unsafe root was accepted')
        self.assertEqual(file.read_bytes(),b'synthetic')

    def test_offline_flag_cannot_bypass_an_active_service_lock(self):
        self.hold(self.a)
        for operation,code in ((lambda:paired.snapshot(self.a,self.z,self.root/'pair',service_stopped=True),'OFFLINE_REQUIRED'),
                               (lambda:projects.snapshot(self.z,self.root/'project',library_root=self.a,service_stopped=True),'SERVICE_MUST_BE_STOPPED')):
            with self.subTest(code=code), self.assertRaises(paired.BackupError) as caught:
                operation()
            self.assertEqual(caught.exception.code,code)
        self.assertFalse((self.root/'pair').exists())
        self.assertFalse((self.root/'project').exists())

    def test_snapshot_holds_shared_lock_through_capture_and_copy(self):
        observed=[]
        def capture(*args):
            observed.append(self.probe(self.a))
            return {},{}
        def copy(*args):
            observed.append(self.probe(self.a))
            return {'synthetic':'receipt'}
        with patch.object(paired,'_capture',capture),patch.object(paired,'_copy',copy):
            self.assertEqual(paired.snapshot(self.a,self.z,self.root/'backup',service_stopped=True),{'synthetic':'receipt'})
        self.assertEqual(observed,[3,3])
        self.assertEqual(self.probe(self.a),0)

    def service_command(self, library, registry):
        return [sys.executable,'-m','apps.api.workbench_server','--library-root',str(library),
                '--workspace-root',str(registry),'--port','0','--source','http://127.0.0.1:1',
                '--origin','https://fixture.invalid']

    def test_second_real_service_is_refused_before_temporary_upload_cleanup(self):
        command=self.service_command(self.a,self.z)+['--terrain-python',sys.executable]
        self.start(command,'ONTOVis evidence workbench ready')
        pending=self.a/'temporary/upload-inflight.glb'
        pending.write_bytes(b'synthetic pending upload')
        before=(pending.read_bytes(),pending.stat().st_mtime_ns)
        public=self.a/'temporary/public-geodata-inflight';public.mkdir()
        (public/'partial').write_bytes(b'synthetic public partial')
        with sqlite3.connect(self.a/'library.sqlite3') as db:
            db.execute("insert into public_geo_jobs values ('synthetic-job','synthetic-actor','synthetic-request','{}',"
                       "'running','fetching','synthetic-revision','{}',null,'2026-10-25','2026-10-25')")
            job_before=db.execute('select * from public_geo_jobs').fetchall()
        result=subprocess.run(command,cwd=ROOT,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,2,result.stderr.decode())
        self.assertIn(b'STORAGE_IN_USE',result.stderr)
        self.assertNotIn(b'workbench ready',result.stdout)
        self.assertEqual((pending.read_bytes(),pending.stat().st_mtime_ns),before)
        self.assertEqual((public/'partial').read_bytes(),b'synthetic public partial')
        with sqlite3.connect(self.a/'library.sqlite3') as db:
            self.assertEqual(db.execute('select * from public_geo_jobs').fetchall(),job_before)
        self.assertEqual(self.probe(self.a),3)

    def test_registry_collision_alone_blocks_startup_and_releases_other_root(self):
        self.start(self.service_command(self.a,self.z),'ONTOVis evidence workbench ready')
        different=self.root/'b'
        result=subprocess.run(self.service_command(different,self.z),cwd=ROOT,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,2,result.stderr.decode())
        self.assertFalse((different/'library.sqlite3').exists())
        self.assertEqual(self.probe(different),0)

    def test_failed_http_bind_closes_sessions_and_releases_storage(self):
        from apps.api import workbench_server as server
        arguments=self.service_command(self.a,self.z)
        with patch('apps.api.project_sessions.ProjectSessions') as sessions, \
                patch.object(server,'ThreadingHTTPServer',side_effect=OSError('synthetic bind failure')), \
                patch.object(sys,'argv',arguments[2:]):
            with self.assertRaisesRegex(OSError,'synthetic bind failure'):
                server.main()
        sessions.return_value.close.assert_called_once()
        self.assertEqual(self.probe(self.a,self.z),0)


if __name__=='__main__':
    unittest.main()
