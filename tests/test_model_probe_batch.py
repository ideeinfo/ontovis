import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from tools import model_probe_batch as batch

ROOT = Path(__file__).parents[1]


class ModelProbeBatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.output = self.root / 'batch'
        self.manifest = self.root / 'manifest.json'
        binary = struct.pack('<9f', 0, 0, 0, 1, 0, 0, 0, 1, 0)
        document = {'asset': {'version': '2.0', 'generator': 'synthetic Q-09 batch fixture'},
                    'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0, 'extras': {'fixture': True}}],
                    'meshes': [{'primitives': [{'attributes': {'POSITION': 0}}]}],
                    'buffers': [{'byteLength': len(binary)}], 'bufferViews': [{'buffer': 0, 'byteLength': len(binary)}],
                    'accessors': [{'bufferView': 0, 'componentType': 5126, 'type': 'VEC3', 'count': 3,
                                   'min': [0, 0, 0], 'max': [1, 1, 0]}]}
        raw = json.dumps(document).encode()
        raw += b' ' * (-len(raw) % 4)
        chunks = struct.pack('<II', len(raw), 0x4E4F534A) + raw + struct.pack('<II', len(binary), 0x004E4942) + binary
        self.source = self.root / 'source.glb'
        self.source.write_bytes(struct.pack('<4sII', b'glTF', 2, 12 + len(chunks)) + chunks)
        self.rows = [{'id': 'fixture-a', 'source': self.source.name, 'sha256': self.sha(self.source)}]
        self.write_manifest()

    def sha(self, path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def write_manifest(self, rows=None):
        self.manifest.write_text(json.dumps({'schemaVersion': 1, 'models': self.rows if rows is None else rows}))

    def run_batch(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return batch.run_batch(self.output, **kwargs)

    def start(self, **kwargs):
        return self.run_batch(manifest=self.manifest, **kwargs)

    def state(self):
        return json.loads((self.output / 'checkpoint.json').read_text())

    def assert_code(self, code, function, *args, **kwargs):
        with self.assertRaises(batch.BatchError) as error:
            function(*args, **kwargs)
        self.assertEqual(error.exception.code, code)

    def wait_for(self, condition, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(.02)
        self.fail('Timed out waiting for the controlled test process.')

    def parent(self, *, slow=False, pause_second=False):
        # Only this test harness substitutes a slow probe; production commands remain fixed.
        helper = self.root / 'slow_worker.py'
        helper.write_text("import os,sys,time\nfrom pathlib import Path\nfrom tools import model_probe_batch as b\n"
                          "def slow(*args,**kwargs):\n"
                          " args[1].mkdir(parents=True)\n"
                          " (args[1]/'report.json').write_text('{\"status\":')\n"
                          " Path(sys.argv[5]).write_text(str(os.getpid()))\n"
                          " time.sleep(60)\n"
                          "b.run_probe=slow\n"
                          "raise SystemExit(b.worker(Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3],int(sys.argv[4])))\n")
        pid_path = self.root / 'worker.pid'
        program = ("import signal,sys,time\nfrom pathlib import Path\nfrom tools import model_probe_batch as b\n"
                   f"original=b.worker_command\nhelper={str(helper)!r}\npid_path={str(pid_path)!r}\n"
                   "def command(model,path,timeout):\n"
                   f" if {slow!r} or ({pause_second!r} and model['id']=='fixture-b'):\n"
                   "  return [sys.executable,helper,model['source'],str(path),model['sha256'],str(timeout),pid_path]\n"
                   " return original(model,path,timeout)\n"
                   "b.worker_command=command\n"
                   "raise SystemExit(b.main(sys.argv[1:]))\n")
        log = (self.root / 'parent.log').open('wb')
        process = subprocess.Popen([sys.executable, '-c', program, 'start', '--manifest', str(self.manifest),
                                    '--output', str(self.output), '--timeout-seconds', '30'],
                                   cwd=ROOT, stdout=log, stderr=log, env={**os.environ, 'PYTHONPATH': str(ROOT)})
        log.close()
        def cleanup():
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
        self.addCleanup(cleanup)
        return process, pid_path

    def test_success_is_private_fingerprinted_and_never_engineering_approval(self):
        before = (self.source.read_bytes(), self.source.stat().st_mtime_ns)
        state = self.start()
        self.assertEqual(state['status'], 'passed')
        self.assertEqual(state['counts'], {'pending': 0, 'running': 0, 'passed': 1, 'failed': 0})
        self.assertFalse(state['releaseEligible'])
        self.assertEqual(state['verificationScope'], 'local_batch_only')
        self.assertEqual((self.source.read_bytes(), self.source.stat().st_mtime_ns), before)
        attempt = state['items'][0]['attempts'][0]
        path = batch.attempt_path(self.output, 0, 1)
        for name, reference in attempt['files'].items():
            self.assertEqual(reference['sha256'], self.sha(path / name))
        report = json.loads((path / 'report.json').read_text())
        self.assertFalse(report['releaseReadiness']['eligible'])
        self.assertFalse(report['releaseReadiness']['G2Passed'])
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o700)
        for file in self.output.rglob('*'):
            if file.is_file():
                self.assertEqual(file.stat().st_mode & 0o777, 0o600)

    def test_completed_resume_reuses_reports_without_reprocessing(self):
        self.start()
        before = {str(p): (self.sha(p), p.stat().st_mtime_ns) for p in (self.output / 'items').rglob('*.json')}
        with patch.object(batch, 'process_one', side_effect=AssertionError('must reuse')):
            state = self.run_batch()
        self.assertEqual(state['status'], 'passed')
        self.assertEqual(len(state['items'][0]['attempts']), 1)
        self.assertEqual(before, {str(p): (self.sha(p), p.stat().st_mtime_ns)
                                  for p in (self.output / 'items').rglob('*.json')})

    def test_existing_output_is_never_replaced(self):
        self.start()
        before = (self.output / 'checkpoint.json').read_bytes()
        with self.assertRaises(FileExistsError):
            self.start()
        self.assertEqual((self.output / 'checkpoint.json').read_bytes(), before)

    def test_bad_model_is_recorded_and_following_model_still_runs(self):
        bad = self.root / 'bad.glb'
        bad.write_bytes(b'not a GLB')
        self.write_manifest([{'id': 'fixture-bad', 'source': bad.name, 'sha256': self.sha(bad)}, *self.rows])
        state = self.start()
        self.assertEqual(state['status'], 'failed')
        self.assertEqual(state['counts']['failed'], 1)
        self.assertEqual(state['counts']['passed'], 1)
        self.assertEqual(state['items'][0]['attempts'][0]['errorCode'], 'INVALID_MODEL')
        with patch.object(batch, 'process_one', side_effect=AssertionError('failure is retained')):
            self.assertEqual(self.run_batch()['status'], 'failed')

    def test_invalid_manifest_and_wrong_hash_never_create_batch(self):
        variants = [[], self.rows * 2, [{**self.rows[0], 'id': '../escape'}],
                    [{**self.rows[0], 'sha256': '0' * 64}], [{**self.rows[0], 'sha256': 'ABC'}],
                    [{**self.rows[0], 'unexpected': True}], [{**self.rows[0], 'source': 'https://example.com/a.glb'}]]
        for rows in variants:
            with self.subTest(rows=rows):
                self.write_manifest(rows)
                with self.assertRaises((batch.BatchError, OSError)):
                    self.start()
                self.assertFalse(self.output.exists())

    def test_timeout_and_input_budgets_are_enforced(self):
        for timeout in (0, 601, True):
            self.assert_code('INVALID_MANIFEST', self.start, timeout=timeout)
        with patch.object(batch, 'MAX_MODELS', 0):
            self.assert_code('INVALID_MANIFEST', self.start)
        with patch.object(batch, 'MAX_TOTAL_BYTES', 1):
            self.assert_code('LIMIT_EXCEEDED', self.start)
        with patch.object(batch, 'MAX_BYTES', 1):
            self.assert_code('LIMIT_EXCEEDED', self.start)

    def test_changed_input_rejects_resume_without_touching_checkpoint(self):
        self.start()
        before = (self.output / 'checkpoint.json').read_bytes()
        self.source.write_bytes(self.source.read_bytes() + b'change')
        self.assert_code('INPUT_CHANGED', self.run_batch)
        self.assertEqual((self.output / 'checkpoint.json').read_bytes(), before)

    def test_changed_output_or_missing_catalog_is_not_reused(self):
        self.start()
        catalog = batch.attempt_path(self.output, 0, 1) / 'components.json'
        original = catalog.read_bytes()
        catalog.write_bytes(original + b' ')
        self.assert_code('OUTPUT_CHANGED', self.run_batch)
        catalog.unlink()
        self.assert_code('OUTPUT_CHANGED', self.run_batch)

    def test_processor_or_plan_changes_require_a_new_batch(self):
        self.start()
        with patch.object(batch, 'processors', return_value={}):
            self.assert_code('PROCESSOR_CHANGED', self.run_batch)
        path = self.output / 'plan.json'
        path.write_bytes(path.read_bytes() + b' ')
        self.assert_code('PLAN_CHANGED', self.run_batch)

    def test_linked_inputs_output_parents_and_reports_are_rejected(self):
        linked = self.root / 'linked.glb'
        linked.symlink_to(self.source)
        self.write_manifest([{**self.rows[0], 'source': linked.name}])
        self.assert_code('UNSAFE_PATH', self.start)
        linked.unlink()
        os.link(self.source, linked)
        self.assert_code('UNSAFE_PATH', self.start)
        linked.unlink()
        self.write_manifest()
        self.output.symlink_to(self.root / 'elsewhere')
        self.assert_code('UNSAFE_PATH', self.start)
        self.output.unlink()
        self.start()
        catalog = batch.attempt_path(self.output, 0, 1) / 'components.json'
        catalog.unlink()
        catalog.symlink_to(self.source)
        self.assert_code('UNSAFE_PATH', self.run_batch)

    def test_a_second_process_cannot_own_the_same_batch(self):
        process, pid_path = self.parent(slow=True)
        self.wait_for(pid_path.exists)
        self.assert_code('BATCH_BUSY', self.run_batch)
        batch.cancel_batch(self.output)
        self.assertEqual(process.wait(timeout=5), 130)

    def test_cancel_terminates_worker_preserves_attempt_and_resumes(self):
        process, pid_path = self.parent(slow=True)
        self.wait_for(pid_path.exists)
        worker_pid = int(pid_path.read_text())
        partial = batch.attempt_path(self.output, 0, 1) / 'report.json'
        partial_bytes = partial.read_bytes()
        self.assertTrue(batch.cancel_batch(self.output)['cancellationRequested'])
        self.assertTrue(batch.cancel_batch(self.output)['cancellationRequested'])
        self.assertEqual(process.wait(timeout=5), 130)
        with self.assertRaises(ProcessLookupError):
            os.kill(worker_pid, 0)
        state = self.state()
        self.assertEqual(state['status'], 'cancelled')
        self.assertEqual(state['items'][0]['attempts'][0]['status'], 'cancelled')
        resumed = self.run_batch()
        self.assertEqual(resumed['status'], 'passed')
        self.assertEqual([row['status'] for row in resumed['items'][0]['attempts']], ['cancelled', 'passed'])
        self.assertEqual(partial.read_bytes(), partial_bytes)
        self.assertFalse(batch.cancel_batch(self.output)['cancellationRequested'])

    def test_sigterm_uses_the_same_cancellation_checkpoint(self):
        process, pid_path = self.parent(slow=True)
        self.wait_for(pid_path.exists)
        process.send_signal(signal.SIGTERM)
        self.assertEqual(process.wait(timeout=5), 130)
        self.assertEqual(self.state()['status'], 'cancelled')
        self.assertEqual(self.run_batch()['status'], 'passed')

    def test_sigkill_stops_orphan_and_only_reprocesses_interrupted_item(self):
        other = self.root / 'other.glb'
        other.write_bytes(self.source.read_bytes())
        self.write_manifest([*self.rows, {'id': 'fixture-b', 'source': other.name, 'sha256': self.sha(other)}])
        process, pid_path = self.parent(pause_second=True)
        self.wait_for(pid_path.exists)
        first = batch.attempt_path(self.output, 0, 1) / 'report.json'
        preserved = (first.read_bytes(), first.stat().st_mtime_ns)
        worker_pid = int(pid_path.read_text())
        partial = batch.attempt_path(self.output, 1, 1) / 'report.json'
        partial_bytes = partial.read_bytes()
        process.kill()
        self.assertEqual(process.wait(timeout=5), -signal.SIGKILL)
        self.wait_for(lambda: self.worker_has_exited(worker_pid))
        state = self.run_batch()
        self.assertEqual(state['status'], 'passed')
        self.assertEqual(len(state['items'][0]['attempts']), 1)
        self.assertEqual([row['status'] for row in state['items'][1]['attempts']], ['interrupted', 'passed'])
        self.assertEqual((first.read_bytes(), first.stat().st_mtime_ns), preserved)
        self.assertEqual(partial.read_bytes(), partial_bytes)

    def worker_has_exited(self, pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        # Linux may retain an already-dead orphan until its external reaper runs.
        status = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True)
        return not status.stdout.strip() or status.stdout.strip().startswith('Z')

    def test_worker_timeout_is_terminal_and_preserves_failure(self):
        with patch.object(batch, 'worker_command', side_effect=lambda model, path, timeout:
                          [sys.executable, '-c', 'import time; time.sleep(60)']):
            state = self.start(timeout=1)
        self.assertEqual(state['status'], 'failed')
        self.assertEqual(state['items'][0]['attempts'][0]['errorCode'], 'WORKER_TIMEOUT')
        with patch.object(batch, 'process_one', side_effect=AssertionError('terminal failure')):
            self.assertEqual(self.run_batch()['status'], 'failed')

    def test_partial_worker_report_after_crash_or_timeout_does_not_stop_following_model(self):
        other = self.root / 'other.glb'
        other.write_bytes(self.source.read_bytes())
        self.write_manifest([*self.rows, {'id': 'fixture-b', 'source': other.name, 'sha256': self.sha(other)}])
        original = batch.worker_command
        for mode in ('crash', 'timeout'):
            with self.subTest(mode=mode):
                self.output = self.root / mode
                def partial(model, path, timeout):
                    if model['id'] != 'fixture-a':
                        return original(model, path, timeout)
                    program = ("from pathlib import Path; import sys,time; p=Path(sys.argv[1]); p.mkdir(); "
                               "(p/'report.json').write_text('{\"status\":'); "
                               + ('time.sleep(60)' if mode == 'timeout' else 'sys.exit(3)'))
                    return [sys.executable, '-c', program, str(path)]
                with patch.object(batch, 'worker_command', side_effect=partial):
                    state = self.start(timeout=1)
                self.assertEqual(state['counts']['failed'], 1)
                self.assertEqual(state['counts']['passed'], 1)
                self.assertEqual(state['items'][0]['attempts'][0]['errorCode'],
                                 'WORKER_TIMEOUT' if mode == 'timeout' else 'WORKER_FAILED')
                report = batch.attempt_path(self.output, 0, 1) / 'report.json'
                self.assertEqual(report.read_bytes(), b'{"status":')
                with patch.object(batch, 'process_one', side_effect=AssertionError('retain failed partial output')):
                    self.assertEqual(self.run_batch()['status'], 'failed')

    def test_atomic_checkpoint_failure_preserves_previous_receipt(self):
        self.start()
        path = self.output / 'checkpoint.json'
        before = path.read_bytes()
        with patch.object(batch.os, 'replace', side_effect=OSError('synthetic atomic write failure')):
            with self.assertRaises(OSError):
                self.run_batch()
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.run_batch()['status'], 'passed')

    def test_report_written_before_checkpoint_failure_is_preserved_but_not_reused(self):
        original = batch.save
        def fail_after_report(output, state):
            if state['items'][0]['status'] == 'passed':
                raise OSError('synthetic receipt write failure after report')
            return original(output, state)
        with patch.object(batch, 'save', side_effect=fail_after_report):
            with self.assertRaises(OSError):
                self.start()
        self.assertEqual(self.state()['items'][0]['status'], 'running')
        report = batch.attempt_path(self.output, 0, 1) / 'report.json'
        preserved = (report.read_bytes(), report.stat().st_mtime_ns)
        state = self.run_batch()
        self.assertEqual(state['status'], 'passed')
        self.assertEqual([row['status'] for row in state['items'][0]['attempts']], ['interrupted', 'passed'])
        self.assertEqual((report.read_bytes(), report.stat().st_mtime_ns), preserved)

    def test_input_change_during_processing_never_commits_a_passed_item(self):
        original = batch.process_one
        def change_after_probe(model, path, timeout, lock_fd, stop):
            result = original(model, path, timeout, lock_fd, stop)
            self.source.write_bytes(self.source.read_bytes() + b'changed during processing')
            return result
        with patch.object(batch, 'process_one', side_effect=change_after_probe):
            self.assert_code('INPUT_CHANGED', self.start)
        self.assertEqual(self.state()['items'][0]['status'], 'running')
        self.assert_code('INPUT_CHANGED', self.run_batch)

    def test_cli_has_real_exit_codes_and_no_source_attributes_in_stdout(self):
        command = [sys.executable, str(ROOT / 'tools/model_probe_batch.py'), 'start',
                   '--manifest', str(self.manifest), '--output', str(self.output)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(rows[-1]['event'], 'batch_finished')
        self.assertFalse(rows[-1]['releaseEligible'])
        self.assertNotIn('sourceExtras', result.stdout)
        repeated = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertEqual(repeated.returncode, 1)


if __name__ == '__main__':
    unittest.main()
