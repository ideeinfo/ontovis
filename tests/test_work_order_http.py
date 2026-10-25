"""Current grants through the actual same-origin, explicitly scoped dispatcher."""
from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.project_sessions import ProjectSessions
from apps.api.session_http import handler_type
from tests.test_project_workspaces import ProjectsAuthority
from tests import test_scene_http as transport

ROOT = '/api/workbench/work-orders'


class WorkOrderHttpTests(unittest.TestCase):
    request = transport.SceneHttpTests.request
    login = transport.SceneHttpTests.login

    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        patches = [patch.object(ProjectsAuthority, 'projects', {'Demo-PDS': 'Synthetic demo', 'B': 'Other project'}),
                   patch.object(ProjectsAuthority, 'permissions', {'member': {'Demo-PDS': 'admin', 'B': 'admin'},
                                                                'reader': {'Demo-PDS': 'member'}})]
        for item in patches: item.start(); self.addCleanup(item.stop)
        self.sessions = ProjectSessions('http://127.0.0.1:18001', library_root=self.root / 'unused',
                                       workspace_root=self.root / 'projects', factory=ProjectsAuthority)
        self.addCleanup(self.sessions.close)
        self.targets = {key: {'entityUid': 'fixture-' + key} for key in ('CN', 'CN1')}
        self.sessions._demo_order_targets = lambda reader: self.targets
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler_type(self.sessions, transport.ORIGIN, development=True))
        thread = Thread(target=self.server.serve_forever, daemon=True); thread.start()
        self.addCleanup(self.server.server_close); self.addCleanup(thread.join); self.addCleanup(self.server.shutdown)
        self.admin = self.login('member')

    def body(self, **value):
        return {'projectRef': {'ontobaseConnectionId': 'ontobase-primary', 'projectCode': 'Demo-PDS'}, **value}

    def seed(self):
        return self.request(ROOT + '/seed-demo', self.body(requestId=str(uuid4()), expectedSnapshotRevision='work-orders:empty'))

    def test_current_project_scope_origin_anonymous_and_member_write_gates(self):
        self.assertEqual(self.request(ROOT, {})[0], 422)
        self.assertEqual(self.request(ROOT, self.body(), client=False)[0], 401)
        self.assertEqual(self.request(ROOT, self.body(), headers={'Origin': 'https://wrong.invalid'})[0], 403)
        self.assertEqual(self.request(ROOT, self.body(projectRef={'ontobaseConnectionId': 'wrong', 'projectCode': 'Demo-PDS'}))[0], 404)
        self.assertEqual(self.request(ROOT, self.body())[1]['total'], 0)
        self.assertIsNone(self.sessions.registry.lookup('Demo-PDS'))
        reader = self.login('reader')
        result = self.request(ROOT + '/seed-demo', self.body(requestId=str(uuid4()), expectedSnapshotRevision='work-orders:empty'), client=reader)
        self.assertEqual((result[0], result[1]['code']), (403, 'WORK_ORDER_WRITE_FORBIDDEN'))

    def test_seed_detail_action_current_permission_and_cross_project_no_disclosure(self):
        status, seeded, _ = self.seed()
        self.assertEqual((status, seeded['created']), (200, 20))
        item = self.request(ROOT, self.body())[1]['items'][0]
        detail_body = self.body(orderId=item['orderId'])
        self.assertEqual(self.request(ROOT + '/detail', detail_body)[1]['orderRevision'], 1)
        other = {'ontobaseConnectionId': 'ontobase-primary', 'projectCode': 'B'}
        self.assertEqual(self.request(ROOT + '/detail', {**detail_body, 'projectRef': other})[0], 404)
        self.assertEqual(self.request(ROOT + '/seed-demo', self.body(projectRef=other, requestId=str(uuid4()), expectedSnapshotRevision='work-orders:empty'))[0], 403)
        body = self.body(orderId=item['orderId'], expectedOrderRevision=1, action='accept', checks=[], note='', requestId=str(uuid4()))
        self.assertEqual(self.request(ROOT + '/action', body)[1]['state'], 'diagnosing')
        ProjectsAuthority.permissions['member']['Demo-PDS'] = 'member'
        denied = self.request(ROOT + '/action', body)
        self.assertEqual((denied[0], denied[1]['code']), (403, 'WORK_ORDER_WRITE_FORBIDDEN'))
        self.assertEqual(self.request(ROOT + '/detail', detail_body)[0], 200)
        ProjectsAuthority.permissions['member'].pop('Demo-PDS')
        self.assertEqual(self.request(ROOT + '/detail', detail_body)[0], 403)

    def test_permission_change_during_mutation_rolls_back_before_response(self):
        self.seed()
        item = self.request(ROOT, self.body())[1]['items'][0]
        original = self.sessions._access
        calls = []
        def access(*args):
            calls.append(1)
            if len(calls) == 3: ProjectsAuthority.permissions['member']['Demo-PDS'] = 'member'
            return original(*args)
        self.sessions._access = access
        status, result, _ = self.request(ROOT + '/action', self.body(orderId=item['orderId'],
            expectedOrderRevision=1, action='accept', checks=[], note='', requestId=str(uuid4())))
        self.assertEqual((status, result['code']), (409, 'ACCESS_CHANGED'))
        self.sessions._access = original
        self.assertEqual(self.request(ROOT + '/detail', self.body(orderId=item['orderId']))[1]['orderRevision'], 1)


if __name__ == '__main__': unittest.main()
