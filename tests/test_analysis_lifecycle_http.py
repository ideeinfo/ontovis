"""Protected lifecycle HTTP using v3 storage and synthetic project authorities."""
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.api import analysis_drafts as draft
from tests import test_analysis_http_integration as base, test_analysis_source_http_integration as sources
from tools import analysis_draft_backup as backup

ROOT = '/api/workbench/analysis-sessions'


@unittest.skipUnless(os.environ.get('ONTOVIS_ANALYSIS_TEST_DATABASE_URL'), 'Disposable PG required')
class AnalysisLifecycleHttpTests(unittest.TestCase):
    setUpClass = classmethod(base.AnalysisHttpIntegrationTests.setUpClass.__func__)
    tearDownClass = classmethod(base.AnalysisHttpIntegrationTests.tearDownClass.__func__)
    request = base.AnalysisHttpIntegrationTests.request
    login = base.AnalysisHttpIntegrationTests.login
    account = base.AnalysisHttpIntegrationTests.account
    start = base.AnalysisHttpIntegrationTests.start
    body = base.AnalysisHttpIntegrationTests.body
    value = base.AnalysisHttpIntegrationTests.value
    create = base.AnalysisHttpIntegrationTests.create
    detail = base.AnalysisHttpIntegrationTests.detail
    demo = sources.AnalysisSourceHttpTests.demo

    def setUp(self):
        provision = draft.provision
        with patch.object(draft, 'provision', side_effect=lambda url, connection: provision(url, connection, version=3)):
            base.AnalysisHttpIntegrationTests.setUp(self)

    def lifecycle(self, created, revision=0):
        return self.body(analysisSessionId=created['analysisSessionId'], expectedAnalysisRevision=created['analysisRevision'],
                         expectedLifecycleRevision=revision, requestId=str(uuid4()))

    def test_delete_restore_routes_keep_content_head_and_capabilities(self):
        created, _ = self.create(); body = self.lifecycle(created)
        deleted = self.request(ROOT+'/trash', body)
        self.assertEqual((deleted[0], deleted[1]['lifecycle']), (200, 'trashed')); self.assertTrue(deleted[1]['capabilities']['canManageLifecycle'])
        self.assertEqual(self.request(ROOT, self.body())[1]['total'], 0)
        self.assertEqual(self.request(ROOT, self.body(lifecycle='trashed'))[1]['total'], 1)
        self.assertEqual(self.detail(created)[1]['snapshot'], self.value())
        forbidden = self.request(ROOT+'/save', self.body(analysisSessionId=created['analysisSessionId'], expectedAnalysisRevision=1, requestId=str(uuid4()), snapshot=self.value()))
        self.assertEqual((forbidden[0], forbidden[1]['code']), (409, 'ANALYSIS_TRASHED'))
        restored = self.request(ROOT+'/untrash', self.lifecycle(created, 1))
        self.assertEqual((restored[0], restored[1]['lifecycleRevision']), (200, 2))
        self.assertEqual(self.detail(created)[1]['analysisRevision'], 1)
        self.assertEqual(self.request(ROOT+'/trash', body)[0], 200)
        self.assertEqual(self.request(ROOT, self.body())[1]['total'], 1)

    def test_anonymous_cross_project_owner_role_and_origin_do_not_delete(self):
        created, _ = self.create(); body = self.lifecycle(created); before = backup.export_package(self.urls[0])
        for client, status in ((False, 401), (self.login('other'), 404), (self.login('reader'), 403)):
            self.assertEqual(self.request(ROOT+'/trash', body, client=client)[0], status)
        cross = {**body, 'projectRef': {**body['projectRef'], 'projectCode': 'B'}}
        self.assertEqual(self.request(ROOT+'/trash', cross)[0], 404)
        self.assertEqual(self.request(ROOT+'/trash', body, headers={'Origin': 'https://wrong.invalid'})[0], 403)
        self.assertEqual(self.request(ROOT+'/trash', {**body, 'actorId': 'forged'})[0], 422)
        self.assertEqual(backup.export_package(self.urls[0]), before)

    def test_final_revocation_rolls_back_lifecycle_http(self):
        created, _ = self.create(); before = backup.export_package(self.urls[0]); calls = 0; original = self.sessions._access
        def access(*args):
            nonlocal calls
            calls += 1
            if calls == 3: self.source.permissions['writer']['SYNTHETIC-A'] = 'viewer'
            return original(*args)
        with patch.object(self.sessions, '_access', side_effect=access):
            response = self.request(ROOT+'/trash', self.lifecycle(created))
        self.assertEqual((response[0], response[1]['code']), (409, 'ACCESS_CHANGED'))
        self.assertEqual(backup.export_package(self.urls[0]), before)

    def test_deleted_canvas_keeps_saved_work_order_link_and_fixed_revision(self):
        project, created, orders = self.demo()
        linked = self.request(ROOT+'/link-work-order', {'projectRef': project, 'analysisSessionId': created['analysisSessionId'],
            'analysisRevision': 1, 'orderId': 'DEMO-PDS-WO-001', 'expectedOrderRevision': 1, 'requestId': str(uuid4())})
        self.assertEqual(linked[0], 200, linked[1]); before = orders.detail({'orderId': 'DEMO-PDS-WO-001'})
        body = {**self.lifecycle(created), 'projectRef': project}
        self.assertEqual(self.request(ROOT+'/trash', body)[0], 200)
        fixed = self.request(ROOT+'/detail', {'projectRef': project, 'analysisSessionId': created['analysisSessionId'], 'analysisRevision': 1})
        self.assertEqual((fixed[0], fixed[1]['lifecycle']), (200, 'trashed'))
        self.assertEqual(orders.detail({'orderId': 'DEMO-PDS-WO-001'}), before)
        rejected = self.request(ROOT+'/link-work-order', {'projectRef': project, 'analysisSessionId': created['analysisSessionId'],
            'analysisRevision': 1, 'orderId': 'DEMO-PDS-WO-001', 'expectedOrderRevision': before['orderRevision'], 'requestId': str(uuid4())})
        self.assertEqual((rejected[0], rejected[1]['code']), (409, 'ANALYSIS_TRASHED'))
