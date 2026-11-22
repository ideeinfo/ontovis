"""Serve a built workbench with real saved scenes and synthetic project adopters."""
from contextlib import contextmanager
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from mimetypes import guess_type
from threading import Event, Thread
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import uuid4

from apps.api.assistant_store import DEFAULT
from apps.api.authority import PreviewError
from apps.api.session_http import handler_type
from tests import test_scene_engineering as engineering
from tests.test_analysis_drafts import snapshot
from tests.test_equipment_http import EquipmentAuthority
from tests.test_model_upload import glb
from tests.test_project_model_http import ProjectModelHttpTests
from tests.test_scene_bindings_http import SCENES, SceneBindingsHttpTests
from tests.test_work_order_workflow_integration import ANALYSIS, WorkOrderWorkflowIntegrationTests

PROJECT = 'SYNTHETIC-A'
CONNECTION = 'ontobase-primary'
TITLE = 'Q-24 隔离验收 · 模型使用清单'
SCENE = '同名验收场景'
ASSISTANT = '/api/workbench/assistant'


class ModelUsageFixture(WorkOrderWorkflowIntegrationTests):
    listing = ProjectModelHttpTests.listing
    metadata = ProjectModelHttpTests.metadata
    upload = ProjectModelHttpTests.upload
    calibration = ProjectModelHttpTests.calibration
    calibrate = ProjectModelHttpTests.calibrate
    item = SceneBindingsHttpTests.item
    check = SceneBindingsHttpTests.check
    checked_body = SceneBindingsHttpTests.checked_body
    saved = SceneBindingsHttpTests.saved
    opened = SceneBindingsHttpTests.opened
    open_ok = SceneBindingsHttpTests.open_ok

    def request(self, path, body=None, **options):
        if path.startswith(SCENES):
            body = {**self.body(), **(body or {})}
        return super().request(path, body, **options)


@contextmanager
def browser_site(public):
    public = public.resolve(strict=True)
    if not (public/'index.html').is_file():
        raise ValueError('A built workbench directory is required')
    fixture = ModelUsageFixture()
    fixture.setUpClass()
    try:
        fixture.setUp()
        with patch.multiple(engineering,PROJECT=PROJECT,CONNECTION=CONNECTION):
            yield from configured_site(public,fixture)
    finally:
        fixture.doCleanups()
        fixture.tearDownClass()


def configured_site(public, fixture):
    source = fixture.source
    source.projects[PROJECT] = 'Q-24 合成项目'
    equipment = EquipmentAuthority('http://127.0.0.1:1')
    equipment.application.update(name='合成采用配置',specificationName='合成型号 Q24',
        specificationRevisionId=equipment.source_ref['specificationRevisionId'],revision=1)
    equipment.adopted = True
    source_request = source.request
    revoked = Event()
    model_calls = []

    def request(account, method, path, body=None):
        route = urlsplit(path).path
        if route.endswith('/access') and revoked.is_set():
            raise PreviewError(403,'FORBIDDEN')
        if route.endswith('/ontovis-assistant/service'):
            role = source.permissions[account.username].get(PROJECT)
            if not role:
                raise PreviewError(403,'FORBIDDEN')
            return dict(serviceRef=DEFAULT['serviceRef'],purpose='ontovis_analysis',serviceRevision='a'*64,
                        accessRevision=PROJECT+':'+role,enabled=True,canRun=True,modelId='synthetic-model')
        if route.startswith(f'/api/v1/projects/{PROJECT}/equipment') or route.startswith('/api/v1/equipment-catalog/'):
            return equipment.request(method,path,body)
        if route.endswith(('/objects/resolve','/relations','/ancestors')) or '/installations/' in route:
            return equipment.request(method,path,body)
        if method=='GET' and route.endswith(('/installations','/objects')):
            return dict(items=[],total=0,nextCursor=None)
        return source_request(account,method,path,body)

    def model_reply(_account, _path, body, *_timing):
        phase = body['workflow']['phase']
        model_calls.append(phase)
        common = dict(usage={},modelCalls=1,engineeringConfirmation=False,purpose='ontovis_analysis',serviceRevision='a'*64)
        if phase=='plan':
            return dict(common,plan=dict(intent='query',queries=[dict(tool='adopted_models',query='',faultCode='',orderId='')],actions=[]))
        return dict(common,answer=dict(observations=[dict(text='已读取合成项目采用模型的使用清单。',refs=['E1'])],
                                       hypotheses=[],gaps=[],nextSteps=[]))

    source.request = request
    fixture.admin = fixture.login('writer')
    fixture.data = glb(fixture.root/'synthetic.glb').read_bytes()
    models = []
    for number in range(1,7):
        status, model, _ = fixture.upload(fixture.metadata(displayName=f'固定模型 {number}'))
        assert status==200, model
        status, calibrated, _ = fixture.calibrate(fixture.calibration(model))
        assert status==200 and calibrated['canPlace']
        models.append(calibrated)
    models.sort(key=lambda model:model['modelVersionId'])
    fixture.version = models[-1]
    profile = dict(projectApplicationRef=equipment.source_ref,models=[
        dict(modelVersionId=model['modelVersionId'],mappings=[]) for model in models])
    fixture.ok('/api/workbench/equipment/configurations/save',dict(configurationId=str(uuid4()),
        expectedConfigurationRevision=None,snapshot=profile,clientRequestId=str(uuid4())))
    equipment.adopted = False
    saved = {}
    for number in range(1,6):
        created = fixture.ok(SCENES+'/create',dict(displayName=SCENE,clientRequestId=str(uuid4())))
        value = deepcopy(created['snapshot'])
        first, second, third = [fixture.item(name) for name in ('合成机位 A01','合成机位 A01','合成机位 A02')]
        second['visible'] = False
        second['placement']['position']['xM'] = 35
        third['placement']['position']['xM'] = 70
        value['instances'] = [first,second,third]
        opened = fixture.saved(created,value)
        saved[opened['sceneId']] = opened
    equipment.adopted = True
    target = saved[max(saved)]
    instance = target['snapshot']['instances'][1]

    def advance():
        value = deepcopy(target['snapshot'])
        value['description'] = '清单验收期间保存的新修订'
        return fixture.saved(target,value)['sceneRevision']

    board = snapshot()
    board.update(schemaVersion=2,projectCode=PROJECT,ontobaseConnectionId=CONNECTION,title=TITLE)
    analysis = fixture.ok(ANALYSIS+'/create',dict(snapshot=board,requestId=str(uuid4())))
    policy = fixture.ok(ASSISTANT+'/policy',{})
    fixture.ok(ASSISTANT+'/publish',dict(requestId=str(uuid4()),expectedRevision=0,
        expectedAccessRevision=policy['accessRevision'],expectedServiceRevision='a'*64,policy={**DEFAULT,'enabled':True}))

    server = ThreadingHTTPServer(('127.0.0.1',0),BaseHTTPRequestHandler)
    with patch('apps.api.assistant_task_api.call_source',side_effect=model_reply), server:
        origin = f'http://127.0.0.1:{server.server_port}'
        base = handler_type(fixture.sessions,origin,development=True)

        class UI(base):
            def do_GET(self):
                path = urlsplit(self.path).path
                if path.startswith('/api/'):
                    return super().do_GET()
                file = (public/(path.lstrip('/') or 'index.html')).resolve()
                if not file.is_relative_to(public) or not file.is_file():
                    return self.send_error(404)
                body = file.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type',guess_type(file.name)[0] or 'application/octet-stream')
                self.send_header('Content-Length',str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server.RequestHandlerClass = UI
        thread = Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            facts = dict(origin=origin,title=TITLE,analysisId=analysis['analysisSessionId'],sceneName=SCENE,
                sceneId=target['sceneId'],sceneRevision=target['sceneRevision'],instanceId=instance['sceneModelInstanceId'],
                instanceName=instance['displayName'],versionId=fixture.version['modelVersionId'])
            yield facts, advance, revoked.set, model_calls
        finally:
            server.shutdown()
            thread.join()
