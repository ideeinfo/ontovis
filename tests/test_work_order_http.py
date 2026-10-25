"""Current grants through the actual same-origin, explicitly scoped dispatcher."""
from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from unittest.mock import Mock, patch
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

    def test_per_order_diagnosis_history_uses_current_project_and_permission(self):
        self.seed()
        order_id = 'DEMO-PDS-WO-001'
        body = self.body(orderId=order_id, expectedOrderRevision=1, action='accept', checks=[], note='', requestId=str(uuid4()))
        detail = self.request(ROOT + '/action', body)[1]
        plan = detail['investigation']
        plan['conclusion'] = '合成编辑验收'
        saved = self.request(ROOT + '/action', {**body, 'action': 'save_diagnosis', 'expectedOrderRevision': 2,
            'requestId': str(uuid4()), 'investigation': plan})
        self.assertEqual((saved[0], saved[1]['investigation']['conclusion']), (200, '合成编辑验收'))
        history_body = self.body(orderId=order_id, orderRevision=3)
        reader = self.login('reader')
        self.assertEqual(self.request(ROOT + '/diagnosis-history', history_body, client=reader)[0], 200)
        denied = self.request(ROOT + '/action', {**body, 'action': 'save_diagnosis', 'expectedOrderRevision': 3,
            'requestId': str(uuid4()), 'investigation': plan}, client=reader)
        self.assertEqual((denied[0], denied[1]['code']), (403, 'WORK_ORDER_WRITE_FORBIDDEN'))
        other = {'ontobaseConnectionId': 'ontobase-primary', 'projectCode': 'B'}
        self.assertEqual(self.request(ROOT + '/diagnosis-history', {**history_body, 'projectRef': other}, client=self.admin)[0], 404)
        ProjectsAuthority.permissions['reader'].pop('Demo-PDS')
        self.assertEqual(self.request(ROOT + '/diagnosis-history', history_body, client=reader)[0], 403)

    def test_diagnosis_transport_budget_accepts_bounded_long_results(self):
        self.seed()
        body = self.body(orderId='DEMO-PDS-WO-001', expectedOrderRevision=1, action='accept', checks=[], note='', requestId=str(uuid4()))
        detail = self.request(ROOT + '/action', body)[1]
        plan = detail['investigation']
        plan['steps'] = [{**plan['steps'][0], 'id': 'step-' + str(i), 'result': 'x' * 1900} for i in range(10)]
        saved = self.request(ROOT + '/action', {**body, 'action': 'save_diagnosis', 'expectedOrderRevision': 2,
            'requestId': str(uuid4()), 'investigation': plan})
        self.assertEqual(saved[0], 200)
        self.assertEqual(len(saved[1]['investigation']['steps']), 10)

    def test_exact_project_electrical_tag_can_be_read_without_accepting_pending_identity(self):
        self.seed()
        identity={'value':'=WEC+CN1-1B4','role':'primary','scheme':'electrical_tag',
                  'status':'needs_review','scopeType':'project','scopeKey':'Demo-PDS'}
        item={'entityUid':'synthetic-formal','entityRevision':'r1','identifiers':[identity]}
        reader=Mock(prefix='/api/v1/projects/Demo-PDS')
        reader._request.return_value={'projectCode':'Demo-PDS','items':[item],'nextCursor':None}
        reader.context_for_object.return_value={'item':item,'context':None}
        body=self.body(orderId='DEMO-PDS-WO-001',locateKey='part-0')
        with patch('apps.api.project_sessions.SceneEngineeringReader',return_value=reader):
            status,result,_=self.request(ROOT+'/locate',body)
            self.assertEqual(status,200,result)
            self.assertEqual(result['referenceMatch']['status'],'needs_review')
            self.assertFalse(result['engineeringConfirmation'])
            reader.context_for_object.assert_called_once_with('synthetic-formal','r1')
            for changes in ({'role':'alias'},{'scopeKey':'B'},{'scopeType':'drawing'},
                            {'value':'+CN1-1B4'},{'status':'retired'},{'scheme':'unknown'}):
                with self.subTest(changes=changes):
                    reader._request.return_value={'projectCode':'Demo-PDS','items':[
                        {**item,'identifiers':[{**identity,**changes}]}],'nextCursor':None}
                    status,result,_=self.request(ROOT+'/locate',body)
                    self.assertEqual((status,result['code']),(409,'DIAGNOSTIC_OBJECT_UNRESOLVED'))
            reader._request.return_value={'projectCode':'Demo-PDS','items':[item,{**item,'entityUid':'another'}],'nextCursor':None}
            self.assertEqual(self.request(ROOT+'/locate',body)[0],409)
            reader._request.return_value={'projectCode':'Demo-PDS','items':[item],'nextCursor':None}
            reader.context_for_object.return_value={'item':{**item,'identifiers':[]},'context':None}
            self.assertEqual(self.request(ROOT+'/locate',body)[1]['code'],'ENGINEERING_CHANGED')

    def cabinet(self):
        return {'entityUid':'synthetic-cabinet','entityRevision':'r1','objectKind':'cabinet',
                'objectScope':'definition','installationContextId':None,
                'identifiers':[{'value':'=WEC+CN2','role':'primary','scheme':'electrical_tag','status':'needs_review',
                                'scopeType':'project','scopeKey':'Demo-PDS'}]}

    def test_cn2_reads_formal_cabinet_definition_and_server_paged_members(self):
        self.seed();item=self.cabinet()
        reader=Mock(prefix='/api/v1/projects/Demo-PDS')
        reader._request.return_value={'projectCode':'Demo-PDS','items':[item],'nextCursor':None}
        reader.context_for_object.return_value={'item':item,'context':None}
        reader.cabinet_members.return_value={'items':[],'total':264,'nextCursor':'synthetic-next','snapshotRevision':'s1','basisKind':'user_declared'}
        body=self.body(orderId='DEMO-PDS-WO-007',locateKey='CN2')
        with patch('apps.api.project_sessions.SceneEngineeringReader',return_value=reader):
            status,result,_=self.request(ROOT+'/locate',body)
            self.assertEqual(status,200,result)
            self.assertEqual(result['cabinetReference'],{'code':'CN2','purpose':'project_definition'})
            self.assertEqual(result['cabinetMembers']['total'],264)
            reader.context_for_object.assert_called_once_with('synthetic-cabinet','r1')
            self.assertIn('primaryIdentifier=%3DWEC%2BCN2',reader._request.call_args.args[1])
            self.assertEqual(self.request(ROOT+'/locate',{**body,'memberCursor':'synthetic-next'})[0],200)
            reader.cabinet_members.assert_called_with(item,'synthetic-next')
            for fields in ({'objectScope':'installation'},{'objectKind':'unknown'}):
                reader.context_for_object.return_value={'item':{**item,**fields},'context':None}
                self.assertEqual(self.request(ROOT+'/locate',body)[1]['code'],'DIAGNOSTIC_OBJECT_UNRESOLVED')

    def test_cabinet_full_tag_requires_the_recorded_parent_and_rejects_bad_inputs(self):
        self.seed();rds='=WEC+CN2-SYNTHETIC';parent=self.cabinet()
        identity={'value':rds,'role':'primary','scheme':'electrical_tag','status':'needs_review',
                  'scopeType':'project','scopeKey':'Demo-PDS'}
        item={'entityUid':'synthetic-cabinet-member','entityRevision':'r1','identifiers':[identity],
              'definitionParentEntityUid':parent['entityUid']}
        reader=Mock(prefix='/api/v1/projects/Demo-PDS')
        reader._request.return_value={'projectCode':'Demo-PDS','items':[item],'nextCursor':None}
        reader.context_for_object.side_effect=lambda uid,*args:{'item':parent if uid==parent['entityUid'] else item,'context':None}
        body=self.body(orderId='DEMO-PDS-WO-007',locateKey='CN2',referenceRds=rds)
        with patch('apps.api.project_sessions.SceneEngineeringReader',return_value=reader):
            status,result,_=self.request(ROOT+'/locate',body)
            self.assertEqual(status,200,result)
            self.assertEqual(result['referenceMatch']['value'],rds)
            self.assertEqual(result['definitionParent'],parent)
            for changes in ({'referenceRds':'=WEC+CN1-SYNTHETIC'},{'referenceRds':'+CN2-SYNTHETIC'},
                            {'referenceRds':'=WEC+CN2-'},{'referenceRds':rds+'\n'},
                            {'locateKey':'part-0'},{'extra':True},{'memberCursor':'extra'}):
                with self.subTest(changes=changes):
                    self.assertEqual(self.request(ROOT+'/locate',{**body,**changes})[0],422)
            item['definitionParentEntityUid']=None
            self.assertEqual(self.request(ROOT+'/locate',body)[1]['code'],'CABINET_MEMBERSHIP_UNRESOLVED')
            item['definitionParentEntityUid']=parent['entityUid'];parent['identifiers'][0]['value']='=WEC+CN1'
            self.assertEqual(self.request(ROOT+'/locate',body)[1]['code'],'CABINET_MEMBERSHIP_UNRESOLVED')


if __name__ == '__main__': unittest.main()
