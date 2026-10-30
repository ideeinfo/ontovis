from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from threading import Thread
import unittest
from uuid import uuid4
from apps.api.session_http import handler_type
from apps.api.weather_store import DEFAULT
from tests import test_project_workspaces as projects
from tests.test_weather import document,NOW


class WeatherHttpTests(unittest.TestCase):
    def setUp(self):
        self.fixture=projects.ProjectWorkspaceTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.sessions,self.sid=self.fixture.sessions,self.fixture.sid
        self.scene=self.fixture.create('A')
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler_type(self.sessions,'http://127.0.0.1:4180',development=True))
        self.server.daemon_threads=True;thread=Thread(target=self.server.serve_forever,daemon=True);thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(thread.join);self.addCleanup(self.server.shutdown)
        self.point=dict(sceneId=self.scene['sceneId'],label='Public example',latitude=39.9,longitude=116.4)
        self.config={**DEFAULT,'enabled':True,'points':[self.point]}
        self.assertEqual(self.request('config')[0],200)
        self.sessions.weather.clock=lambda:NOW
        self.calls=[]
        def fetch(*args):self.calls.append(args);return 200,document(),{}
        self.sessions.weather.fetcher=fetch
    def request(self,action,body=None,project='A',origin=True,revision=None):
        data=self.fixture.payload(project,**(body or {}))
        if revision:data['expectedSessionRevision']=revision
        headers={'Host':'127.0.0.1:4180','Content-Type':'application/json','Cookie':'ontovis_development_session='+self.sid}
        if origin:headers['Origin']='http://127.0.0.1:4180'
        conn=HTTPConnection(*self.server.server_address,timeout=10);conn.request('POST','/api/workbench/weather/'+action,json.dumps(data),headers)
        r=conn.getresponse();value=json.loads(r.read());conn.close();return r.status,value
    def save(self,config=None,revision=0):return self.request('save',dict(config=config or self.config,expectedRevision=revision,expectedAccessRevision='A:admin',requestId=str(uuid4())))
    def test_origin_session_scope_and_admin_checks(self):
        self.assertEqual(self.request('config',origin=False)[0],403)
        self.assertEqual(self.request('config',project=None)[0],422)
        self.assertEqual(self.request('config',revision='old')[0],409)
        projects.ProjectsAuthority.permissions['member']['A']='viewer'
        self.assertFalse(self.request('config')[1]['canManage']);self.assertEqual(self.save()[0],403)
        self.assertEqual(self.request('test',dict(config=self.config,sceneId=self.point['sceneId'],expectedAccessRevision='A:viewer'))[0],403)
    def test_default_does_not_query_and_test_does_not_save(self):
        self.assertEqual(self.request('current',dict(sceneId=self.point['sceneId']))[1]['status'],'unconfigured');self.assertEqual(self.calls,[])
        status,value=self.request('test',dict(config=self.config,sceneId=self.point['sceneId'],expectedAccessRevision='A:admin'))
        self.assertEqual(status,200,value);self.assertTrue(value['preview']);self.assertEqual(value['source']['kind'],'forecast')
        self.assertEqual(self.request('config')[1]['revision'],0)
    def test_save_read_disable_and_configuration_cas(self):
        self.assertEqual(self.save()[0],200);self.assertEqual(self.save()[0],409)
        self.assertEqual(self.request('current',dict(sceneId=self.point['sceneId']))[1]['status'],'available')
        self.assertEqual(self.save({**self.config,'enabled':False},1)[0],200)
        self.assertEqual(self.request('current',dict(sceneId=self.point['sceneId']))[1]['status'],'disabled');self.assertEqual(len(self.calls),1)
    def test_scene_cross_project_deleted_and_unknown_rejected(self):
        self.assertEqual(self.request('current',dict(sceneId=self.point['sceneId']),project='B')[0],404)
        self.assertEqual(self.save({**self.config,'points':[{**self.point,'sceneId':str(uuid4())}]})[0],404)
        self.fixture.call('scenes/delete','A',sceneId=self.scene['sceneId'],expectedSceneRevision=self.scene['sceneRevision'],expectedLifecycleRevision=0,clientRequestId=str(uuid4()))
        self.assertEqual(self.request('current',dict(sceneId=self.point['sceneId']))[0],404)
    def test_revocation_and_configuration_changes_after_fetch_discard_response(self):
        self.assertEqual(self.save()[0],200)
        def fetch(*args):
            del projects.ProjectsAuthority.permissions['member']['A'];return 200,document(),{}
        self.sessions.weather.fetcher=fetch
        self.assertEqual(self.request('current',dict(sceneId=self.point['sceneId']))[0],403)
    def test_client_cannot_set_upstream_url_or_cross_project_config(self):
        self.assertEqual(self.save({**self.config,'endpoint':'http://127.0.0.1'})[0],422)
        self.assertEqual(self.save()[0],200)
        self.assertEqual(self.request('config',project='B')[1]['revision'],0)
        self.assertEqual(self.request('current',dict(sceneId=self.point['sceneId'],endpoint='https://other'))[0],422)


if __name__=='__main__':unittest.main()
