"""Host a built workbench and the synthetic 13002 scenario for a browser check."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from mimetypes import guess_type
from threading import Event, Thread
from urllib.parse import urlsplit
from uuid import uuid4
from apps.api.authority import PreviewError
from apps.api.session_http import handler_type
from apps.api.simulated_faults import identity
from tests.test_analysis_drafts import OTHER, snapshot
from tests.test_work_order_workflow_integration import ANALYSIS, WorkOrderWorkflowIntegrationTests

PROJECT = 'Demo-PDS'
TITLE = 'Q-26 隔离验收 · 13002 既有分析'
RECORD = '软件模拟验收。已核对 13002 回放的低读数与参照温度，按固定分析记录复测，等待现场资料。'


class EndToEnd(WorkOrderWorkflowIntegrationTests):
    def body(self, **values):
        return {'projectRef': {'ontobaseConnectionId': 'ontobase-primary', 'projectCode': PROJECT}, **values}


@contextmanager
def serve_workbench(public, sessions, controls=None, *, port=0):
    with ThreadingHTTPServer(('127.0.0.1',port),BaseHTTPRequestHandler) as server:
        origin = f'http://127.0.0.1:{server.server_port}'
        base = handler_type(sessions,origin,development=True)

        class UI(base):
            def do_POST(self):
                command = (controls or {}).get(urlsplit(self.path).path)
                if command is None:
                    return super().do_POST()
                command()
                return self.reply(200,{'ok':True})

            def do_GET(self):
                path = urlsplit(self.path).path
                if path.startswith('/api/'):
                    return super().do_GET()
                file = (public/(path.lstrip('/') or 'index.html')).resolve()
                if not file.is_relative_to(public) or not file.is_file():
                    return self.send_error(404)
                data = file.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type',guess_type(file.name)[0] or 'application/octet-stream')
                self.send_header('Content-Length',str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        server.RequestHandlerClass = UI
        thread = Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            yield origin
        finally:
            server.shutdown()
            thread.join()


@contextmanager
def browser_site(public):
    public = public.resolve(strict=True)
    if not (public/'index.html').is_file():
        raise ValueError('A built workbench directory is required')
    revoked = Event()
    fixture = EndToEnd()
    fixture.setUpClass()
    try:
        fixture.setUp()
        source = fixture.source
        source.projects = {PROJECT: 'Q-26 隔离试验场', 'B': '另一项目'}
        source.permissions = {'writer': {PROJECT: 'admin', 'B': 'admin'},
                              'other': {PROJECT: 'reviewer'}, 'reader': {PROJECT: 'viewer'}}
        source_request = source.request

        def request(account, method, path, body=None):
            if account.username == 'other' and path.endswith('/access') and revoked.is_set():
                raise PreviewError(403, 'FORBIDDEN')
            if method == 'GET' and path == f'/api/v1/projects/{PROJECT}/members':
                return {'items': [{'user_id': OTHER, 'username': 'other', 'role': 'reviewer', 'is_active': True}]}
            if method == 'GET' and path.endswith('/installations'):
                return {'items': [], 'total': 0, 'nextCursor': None}
            if method == 'GET' and path.endswith('/objects'):
                return {'items': [], 'total': 0, 'nextCursor': None}
            return source_request(account, method, path, body)

        source.request = request
        fixture.admin = fixture.login('writer')
        fixture.sessions.registry.prepare(PROJECT)
        sample = identity('13002')
        canvas = snapshot()
        canvas.update(schemaVersion=2, projectCode=PROJECT, ontobaseConnectionId='ontobase-primary',
                      title=TITLE, reuse=dict(faultCode=sample['faultCode'], faultSystem=sample['sourceConnectionId'],
                      equipment=sample['primaryRds'], simulated=True, summary='合成前置分析，只用于软件验收。',
                      advice='核对演练传感器与独立参照温度并记录结果。'))
        canvas['context'].update(timeFrom=sample['timeFrom'], timeTo=sample['timeTo'])
        first = fixture.ok(ANALYSIS+'/create', {'requestId':str(uuid4()), 'snapshot':canvas})
        canvas['cards'][0]['note'] = '隔离模拟记录。该固定版 r2 用作人工采纳。'
        second = fixture.ok(ANALYSIS+'/save', {'requestId':str(uuid4()), 'snapshot':canvas,
                            'analysisSessionId':first['analysisSessionId'], 'expectedAnalysisRevision':1})
        fixed = fixture.fixed(second)
        fixture.ok('analysis-share', {**fixed, 'requestId':str(uuid4()), 'share':True})
        canvas['cards'][0]['note'] = '后续 r3 仅用于核对 r2 引用保持。'
        latest = fixture.ok(ANALYSIS+'/save', {'requestId':str(uuid4()), 'snapshot':canvas,
                            'analysisSessionId':first['analysisSessionId'], 'expectedAnalysisRevision':2})
        with serve_workbench(public,fixture.sessions) as origin:
            yield dict(origin=origin, analysis=fixed, latest=latest['analysisRevision'],
                       title=TITLE, text=RECORD, projectCode=PROJECT,
                       alarm={key:sample[key] for key in ('datasetId','datasetRevision')}), revoked.set
    finally:
        fixture.doCleanups()
        fixture.tearDownClass()
