"""Real streaming HTTP over an isolated service with synthetic source access."""
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from threading import Thread
import time
import unittest
from unittest.mock import patch

from apps.api import simulated_faults as sim
from apps.api.session_http import handler_type
from apps.api.simulation_stream import PATH
from tests import test_project_workspaces as projects
from tests.test_simulation_stream import decode


class SimulationStreamHttpTests(unittest.TestCase):
    def setUp(self):
        self.fixture = projects.ProjectWorkspaceTests(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.sessions = self.fixture.sessions
        patcher = patch.dict(projects.ProjectsAuthority.projects, {'Demo-PDS': 'Synthetic demo'})
        patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch.dict(projects.ProjectsAuthority.permissions['member'], {'Demo-PDS': 'viewer'})
        patcher.start(); self.addCleanup(patcher.stop)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler_type(self.sessions, 'http://127.0.0.1:4180', development=True))
        self.server.daemon_threads = True
        self.thread = Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.addCleanup(self.stop)
        item = sim.identity('13001')
        self.body = self.fixture.payload('Demo-PDS', **{key: item[key] for key in ('datasetId', 'datasetRevision')}, fromSecond=179)
        self.headers = {'Host':'127.0.0.1:4180','Origin':'http://127.0.0.1:4180','Content-Type':'application/json',
                        'Cookie':'ontovis_development_session='+self.fixture.sid}

    def stop(self):
        self.sessions.simulation_streams.close(); self.server.shutdown(); self.server.server_close(); self.thread.join(3)

    def request(self, body=None, *, path=PATH, headers=None, method='POST'):
        connection = HTTPConnection(*self.server.server_address, timeout=3)
        connection.request(method, path, json.dumps(self.body if body is None else body), self.headers if headers is None else headers)
        response = connection.getresponse()
        self.addCleanup(connection.close)
        return connection, response

    @staticmethod
    def frame(response):
        lines = []
        while True:
            line = response.readline()
            if not line: raise AssertionError('Unexpected stream end')
            lines.append(line)
            if line == b'\n': return decode(b''.join(lines))

    def test_response_is_incremental_no_store_and_complete_releases_slot(self):
        start = time.monotonic(); _, response = self.request()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader('Content-Type'), 'text/event-stream; charset=utf-8')
        self.assertEqual(response.getheader('X-Accel-Buffering'), 'no')
        self.assertEqual(response.getheader('Cache-Control'), 'no-store')
        self.assertEqual(response.getheader('X-Session-Revision'), self.fixture.revision)
        self.assertIsNone(response.getheader('Content-Length'))
        self.assertEqual(self.frame(response)['event'], 'ready')
        self.assertEqual(self.frame(response)['data']['sequence'], 179)
        self.assertLess(time.monotonic()-start, .8)
        self.assertEqual(self.frame(response)['data']['sequence'], 180)
        self.assertEqual(self.frame(response)['event'], 'complete')
        self.assertEqual(response.read(), b'')
        self.assertEqual(self.sessions.simulation_streams.owners, {})
        self.assertIsNone(self.sessions.registry.lookup('Demo-PDS'))

    def test_resume_from_http_cursor_backfills_intervening_records(self):
        now = [1793232000.0]
        self.sessions.simulation_streams.clock = lambda: now[0]
        self.sessions.simulation_streams.monotonic = lambda: now[0]
        connection, response = self.request({**self.body, 'fromSecond':87})
        self.frame(response); cursor = self.frame(response)['id']
        connection.close(); now[0] += 6
        body = {key:value for key,value in self.body.items() if key != 'fromSecond'}
        connection, response = self.request({**body, 'cursor':cursor})
        self.assertEqual(response.status, 200)
        self.frame(response)
        for second in range(88, 94):
            value = self.frame(response)
            self.assertEqual(value['data']['sequence'], second)
            if second == 90: self.assertIsNone(value['data']['samples'][0]['value'])
        connection.close()

    def test_logout_is_a_terminal_stream_error_without_more_source_payload(self):
        connection, response = self.request({**self.body, 'fromSecond':60})
        self.frame(response); self.frame(response)
        self.sessions.logout(self.fixture.sid, self.fixture.revision)
        value = self.frame(response)
        self.assertEqual(value['event'], 'stream-error')
        self.assertEqual(value['data']['status'], 401)
        self.assertNotIn('detail', value['data'])
        self.assertEqual(response.read(), b'')

    def test_origin_anonymous_project_version_shape_and_exact_path_boundaries(self):
        cases = [({}, self.headers, PATH, 'POST', 409),
                 (self.body, {k:v for k,v in self.headers.items() if k!='Cookie'}, PATH, 'POST', 401),
                 (self.body, {**self.headers, 'Origin':'https://other.invalid'}, PATH, 'POST', 403),
                 ({**self.body, 'owner':'arbitrary'}, self.headers, PATH, 'POST', 422),
                 ({**self.body, 'expectedSessionRevision':'old'}, self.headers, PATH, 'POST', 409),
                 ({**self.body, 'datasetRevision':'old'}, self.headers, PATH, 'POST', 409),
                 ({**self.body, 'projectRef':{'ontobaseConnectionId':'ontobase-primary','projectCode':'B'}}, self.headers, PATH, 'POST', 404),
                 (self.body, self.headers, PATH+'/', 'POST', 404),
                 (self.body, self.headers, PATH+'?cursor=x', 'POST', 404),
                 (self.body, self.headers, PATH, 'GET', 404)]
        for body, headers, path, method, status in cases:
            with self.subTest(path=path, status=status):
                _, response = self.request(body, headers=headers, path=path, method=method)
                self.assertEqual(response.status, status, response.read())
        self.assertEqual(self.sessions.simulation_streams.owners, {})
