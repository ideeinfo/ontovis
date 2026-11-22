"""Run saved-version cockpit navigation against an isolated project."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import uuid4

from tests import test_scene_engineering as engineering
from tests.assistant_model_usage_fixture import CONNECTION, PROJECT, ModelUsageFixture
from tests.test_model_upload import glb
from tests.test_regional_catalog import RegionalCatalogTests
from tests.test_scene_bindings_http import SCENES
from tests.work_order_13002_fixture import serve_workbench
from tools.publish_regional_catalog import activate


@contextmanager
def browser_site(public):
    fixture=ModelUsageFixture()
    fixture.setUpClass()
    try:
        fixture.setUp()
        with patch.multiple(engineering,PROJECT=PROJECT,CONNECTION=CONNECTION), TemporaryDirectory() as tmp:
            source=fixture.source
            source.projects[PROJECT]='导航测试项目'
            source_request=source.request

            def request(account,method,path,body=None):
                route=urlsplit(path).path
                if method=='GET' and route==f'/api/v1/projects/{PROJECT}/equipment':
                    return dict(projectCode=PROJECT,items=[],nextCursor=None,snapshotRevision='equipment:1')
                if method=='GET' and route.endswith(('/installations','/objects')):
                    return dict(items=[],total=0,nextCursor=None)
                return source_request(account,method,path,body)

            source.request=request
            fixture.admin=fixture.login('writer')
            fixture.data=glb(fixture.root/'navigation.glb').read_bytes()
            state, model, _=fixture.upload(fixture.metadata(displayName='合成导航模型'))
            assert state==200, model
            state, fixture.version, _=fixture.calibrate(fixture.calibration(model))
            assert state==200 and fixture.version['canPlace']
            original=fixture.ok(SCENES+'/create',dict(displayName='导航历史场景',clientRequestId=str(uuid4())))
            snapshot=deepcopy(original['snapshot'])
            first=fixture.item('历史设备 A01')
            second=fixture.item('历史设备 B02')
            second['placement']['position']['xM']=35
            snapshot['instances']=[first,second]
            saved=fixture.saved(original,snapshot)
            snapshot=deepcopy(saved['snapshot'])
            snapshot['displayName']='导航当前场景'
            snapshot['instances'][0]['displayName']='当前设备 A01'
            current=fixture.saved(saved,snapshot)

            regional=RegionalCatalogTests()
            regional.folder=Path(tmp)
            publication=activate(fixture.sessions.regional_catalog_root,regional.build('browser'))

            grant=source.permissions['writer'][PROJECT]

            def revoke():
                source.permissions['writer'].pop(PROJECT,None)

            with serve_workbench(public.resolve(strict=True),fixture.sessions,{'/test-navigation/revoke':revoke}) as origin:
                yield dict(origin=origin,projectCode=PROJECT,sceneId=saved['sceneId'],sceneRevision=saved['sceneRevision'],
                           currentRevision=current['sceneRevision'],instanceId=first['sceneModelInstanceId'],
                           currentName=snapshot['displayName'],historicalName=saved['snapshot']['displayName'],
                           historicalInstance=first['displayName'],currentInstance='当前设备 A01',catalogRevision=publication)
                source.permissions['writer'][PROJECT]=grant
                assert fixture.open_ok(current)['sceneRevision']==current['sceneRevision']
                assert fixture.open_ok(saved,saved['sceneRevision'])['snapshot']==saved['snapshot']
    finally:
        fixture.doCleanups()
        fixture.tearDownClass()
