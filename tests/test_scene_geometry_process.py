"""Process budgets/auth/cleanup without depending on the optional GIS runtime.

Positive calls use the actual fixed local-scene CLI. Controlled replacement
subprocesses only exercise malformed output, exit and timeout counterexamples;
none of those cases count as positive GIS acceptance.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.model_library import ModelLibrary
from apps.api.scene_geometry_process import SceneGeometryProcess


PROCESS_MODULE='apps.api.scene_geometry_process'
REAL_POPEN=subprocess.Popen


class SceneGeometryProcessTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.library=ModelLibrary(self.root/'private','fixture-project',str(uuid4()))
        self.terrain_root=self.root/'terrain-versions';self.terrain_root.mkdir()
        self.worker=SceneGeometryProcess(self.library,python_executable=Path(sys.executable).absolute(),
                                         terrain_root=self.terrain_root)
        self.children=[];self.addCleanup(self.close_children)

    def close_children(self):
        for child in self.children:
            if child.poll() is None:child.kill()
            child.wait(timeout=3)
            if child.stdout and not child.stdout.closed:child.stdout.close()

    def request(self):
        return {'kind':'validate','trustedTerrains':[],'snapshot':{
            'displayName':'本地进程夹具',
            'coordinateFrame':{'mode':'local_plane','frameRevision':'local-1','origin':[0,0,0],
                               'unit':'m','axes':'X_EAST_Y_UP_Z_SOUTH'},
            'terrain':None,'instances':[],
            'initialView':{'eye':[0,10,10],'target':[0,0,0]},
            'defaults':{'background':'plain','lighting':'neutral','terrainMaterial':'solid'}}}

    def expect(self,status,code,callback):
        with self.assertRaises(PreviewError) as caught:callback()
        self.assertEqual((caught.exception.status,caught.exception.code),(status,code))
        self.assertNotIn(str(self.root),str(caught.exception))

    def assert_clean(self):
        self.assertEqual(list((self.library.root/'temporary').iterdir()),[])
        self.assertTrue(self.worker.slots.acquire(blocking=False),'The unique processing slot leaked')
        self.worker.slots.release()

    def child(self,script):
        child=REAL_POPEN([sys.executable,'-c',script],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        self.children.append(child)
        return child

    def replacing_child(self,script):
        def create(*args,**kwargs):return self.child(script)
        return patch(PROCESS_MODULE+'.subprocess.Popen',side_effect=create)

    def test_invalid_or_oversize_input_is_rejected_before_process_or_private_file(self):
        circular={};circular['self']=circular
        for request,status,code in [({'number':float('inf')},422,'INVALID_REQUEST'),
                                    ({'number':float('nan')},422,'INVALID_REQUEST'),
                                    ({'unsupported':object()},422,'INVALID_REQUEST'),
                                    (circular,422,'INVALID_REQUEST'),
                                    ({'text':'x'*1048576},413,'SCENE_LIMIT_EXCEEDED')]:
            with self.subTest(code=code),patch(PROCESS_MODULE+'.subprocess.Popen') as spawn:
                self.expect(status,code,lambda:self.worker.process(request,lambda:None))
                spawn.assert_not_called();self.assert_clean()

    def test_busy_slot_rejects_before_writing_and_does_not_release_other_owner(self):
        self.assertTrue(self.worker.slots.acquire(blocking=False))
        try:
            with patch(PROCESS_MODULE+'.subprocess.Popen') as spawn:
                self.expect(429,'SCENE_GEOMETRY_BUSY',lambda:self.worker.process(self.request(),lambda:None))
                spawn.assert_not_called()
            self.assertEqual(list((self.library.root/'temporary').iterdir()),[])
            self.assertFalse(self.worker.slots.acquire(blocking=False))
        finally:self.worker.slots.release()
        self.assert_clean()

    def test_actual_fixed_child_invalid_request_cleans_private_file_and_can_retry(self):
        for _ in range(2):
            self.expect(422,'INVALID_REQUEST',lambda:self.worker.process({'kind':'validate','snapshot':{},'trustedTerrains':[]},lambda:None))
            self.assert_clean()

    def test_actual_fixed_local_child_rechecks_authorization_before_return(self):
        calls=[]
        def revoke_on_result():
            calls.append(True)
            if len(calls)==2:raise PreviewError(403,'SCENE_WRITE_FORBIDDEN')
        self.expect(403,'SCENE_WRITE_FORBIDDEN',lambda:self.worker.process(self.request(),revoke_on_result))
        self.assertEqual(len(calls),2);self.assert_clean()
        result=self.worker.process(self.request(),lambda:None)
        self.assertEqual(result['geometrySummary']['mode'],'local_plane')
        self.assertFalse(result['geometrySummary']['fieldAccuracyVerified']);self.assert_clean()

    def test_initial_denial_does_not_start_child(self):
        def deny():raise PreviewError(403,'SCENE_WRITE_FORBIDDEN')
        with patch(PROCESS_MODULE+'.subprocess.Popen') as spawn:
            self.expect(403,'SCENE_WRITE_FORBIDDEN',lambda:self.worker.process(self.request(),deny))
            spawn.assert_not_called()
        self.assert_clean()

    def test_oversize_child_output_is_killed_and_slot_released(self):
        with self.replacing_child("import sys,time;sys.stdout.write('x'*1024);sys.stdout.flush();time.sleep(5)"),\
             patch(PROCESS_MODULE+'.MAX_OUTPUT_BYTES',64):
            self.expect(413,'SCENE_LIMIT_EXCEEDED',lambda:self.worker.process(self.request(),lambda:None))
        self.assertIsNotNone(self.children[-1].poll());self.assertTrue(self.children[-1].stdout.closed)
        self.assert_clean()

    def test_parent_wall_timeout_kills_child_without_waiting_for_gis(self):
        with self.replacing_child('import time;time.sleep(10)'),\
             patch(PROCESS_MODULE+'.time.monotonic',side_effect=[0,66]):
            self.expect(422,'SCENE_LIMIT_EXCEEDED',lambda:self.worker.process(self.request(),lambda:None))
        self.assertIsNotNone(self.children[-1].poll());self.assertTrue(self.children[-1].stdout.closed)
        self.assert_clean()

    def test_unexpected_exit_and_malformed_output_do_not_return_success(self):
        cases=[('import sys;sys.exit(9)',422,'SCENE_LIMIT_EXCEEDED'),
               ("print('not-json')",502,'PROCESSING_UNAVAILABLE'),
               ("print('[]')",502,'PROCESSING_UNAVAILABLE'),
               ("print('{}')",502,'PROCESSING_UNAVAILABLE'),
               ("print('{\"code\":\"RESOURCE_CHANGED\"}');raise SystemExit(2)",409,'RESOURCE_CHANGED'),
               ("print('{\"code\":\"/private/untrusted\"}');raise SystemExit(2)",422,'INVALID_REQUEST'),
               ("print('{\"code\":[]}');raise SystemExit(2)",422,'INVALID_REQUEST'),
               ("print('{\"code\":{}}');raise SystemExit(2)",422,'INVALID_REQUEST')]
        for script,status,code in cases:
            with self.subTest(code=code),self.replacing_child(script):
                self.expect(status,code,lambda:self.worker.process(self.request(),lambda:None))
                self.assert_clean()

    def test_startup_failure_is_bounded_and_cleans_request_file(self):
        with patch(PROCESS_MODULE+'.subprocess.Popen',side_effect=OSError(str(self.root/'private-error'))):
            self.expect(503,'PROCESSING_UNAVAILABLE',lambda:self.worker.process(self.request(),lambda:None))
        self.assert_clean()

    def test_stdout_read_failure_is_bounded_and_kills_child(self):
        child=self.child("import sys,time;print('{}');sys.stdout.flush();time.sleep(5)")
        with patch(PROCESS_MODULE+'.subprocess.Popen',return_value=child),\
             patch(PROCESS_MODULE+'.os.read',side_effect=OSError(str(self.root/'private-read-error'))):
            self.expect(503,'PROCESSING_UNAVAILABLE',lambda:self.worker.process(self.request(),lambda:None))
        self.assertIsNotNone(child.poll());self.assertTrue(child.stdout.closed);self.assert_clean()

    def test_selector_creation_failure_does_not_leak_unique_slot(self):
        with patch(PROCESS_MODULE+'.selectors.DefaultSelector',side_effect=OSError('fd budget exhausted')):
            self.expect(503,'PROCESSING_UNAVAILABLE',lambda:self.worker.process(self.request(),lambda:None))
        self.assert_clean()
        self.expect(422,'INVALID_REQUEST',lambda:self.worker.process({'kind':'invalid'},lambda:None))
        self.assert_clean()

    def test_wait_failure_in_cleanup_does_not_leave_request_file_or_slot(self):
        child=self.child("print('not-json')")
        real_wait=child.wait;calls=[]
        def wait(*args,**kwargs):
            calls.append(True)
            if len(calls)==2:raise subprocess.TimeoutExpired('fixed-worker',3)
            return real_wait(*args,**kwargs)
        with patch(PROCESS_MODULE+'.subprocess.Popen',return_value=child),patch.object(child,'wait',side_effect=wait):
            self.expect(503,'PROCESSING_UNAVAILABLE',lambda:self.worker.process(self.request(),lambda:None))
        self.assertTrue(child.stdout.closed);self.assert_clean()
        self.expect(422,'INVALID_REQUEST',lambda:self.worker.process({'kind':'invalid'},lambda:None))
        self.assert_clean()


if __name__=='__main__':unittest.main()
