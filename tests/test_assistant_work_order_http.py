"""Normal workbench HTTP boundaries; synthetic authority, model and PG lock fixture."""
from contextlib import contextmanager
import json
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.work_orders import WorkOrders
from tests import test_assistant_http as fixture_http
from tests.test_assistant import answer


class AssistantWorkOrderHttpTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_http.AssistantHttpTests(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.sessions = self.fixture.sessions; self.request = self.fixture.request; self.fixture.enable()
        from apps.api.analysis_drafts import AnalysisDrafts as Previous
        self.deleted = False; self.locks = []
        parent = self
        class Cursor:
            def execute(inner, statement, args): parent.locks.append(statement)
        class Store(Previous):
            def __init__(inner, *args): super().__init__(*args); inner.connection = inner
            @contextmanager
            def transaction(inner): yield Cursor()
            def _session(inner, cursor, analysis, actor, active=False):
                if parent.deleted: raise PreviewError(409, 'ANALYSIS_TRASHED')
            def _revision(inner, cursor, analysis, revision): return None, [None, 'c' * 64]
        p = patch('apps.api.analysis_drafts.AnalysisDrafts', Store); p.start(); self.addCleanup(p.stop)
        space = self.sessions.registry.lookup('Demo-PDS'); self.orders = WorkOrders(self.sessions._workspace(space).library, 'Demo-PDS')
        self.orders.seed({'requestId': str(uuid4()), 'expectedSnapshotRevision': 'work-orders:empty'},
                         {key: {'entityUid': 'synthetic-' + key} for key in ('CN', 'CN1')}, 'synthetic-person', lambda: None)
        first = self.orders.detail({'orderId': 'DEMO-PDS-WO-001'})
        self.orders.action({'requestId': str(uuid4()), 'orderId': first['orderId'], 'expectedOrderRevision': 1,
                           'action': 'accept', 'checks': [], 'note': ''}, 'synthetic-person', lambda: None)
        model_patch = patch('apps.api.assistant_service.call_source', return_value={
            'answer': answer(), 'usage': {}, 'serviceRevision': 'a' * 64, 'purpose': 'ontovis_analysis',
            'modelCalls': 1, 'engineeringConfirmation': False})
        self.model = model_patch.start(); self.addCleanup(model_patch.stop)
        _, started = self.request('start', self.fixture.start_body())
        self.run_id = started['runId']
        for _ in range(100):
            _, run = self.request('status', {'runId': self.run_id})
            if run['state'] == 'complete': break
            time.sleep(.01)
        self.assertEqual('complete', run['state'])

    def preview(self): return self.request('work-order-preview', {'runId': self.run_id, 'orderId': 'DEMO-PDS-WO-001'})

    def body(self, preview):
        item = preview['proposal']['items'][0]
        return {'runId': self.run_id, 'orderId': preview['order']['orderId'], 'expectedOrderRevision': preview['order']['orderRevision'],
                'expectedProposalSha256': preview['proposal']['proposalSha256'], 'requestId': str(uuid4()),
                'items': [{'id': item['id'], 'text': '合成人工编辑建议', 'targetKey': ''}]}

    def test_preview_apply_and_same_request_restore_without_another_model(self):
        status, preview = self.preview(); self.assertEqual(200, status, preview); self.assertEqual(0, preview['modelCalls'])
        body = self.body(preview); status, result = self.request('work-order-apply', body)
        self.assertEqual(200, status, result); self.assertEqual('diagnosing', result['state'])
        self.assertFalse(result['engineeringConfirmation']); self.assertEqual(1, len(result['assistantTransfers']))
        self.assertEqual(result, self.request('work-order-apply', body)[1]); self.assertEqual(1, self.model.call_count)
        self.assertTrue(any('pg_advisory_xact_lock' in value for value in self.locks))
        self.assertIn(preview['proposal']['items'][0]['id'], self.preview()[1]['adoptedItemIds'])

    def test_origin_role_owner_and_project_guards_apply_to_both_routes(self):
        _, preview = self.preview(); body = self.body(preview)
        self.assertEqual(403, self.request('work-order-apply', body, origin=False)[0])
        self.assertEqual(404, self.request('work-order-apply', body, project='B')[0])
        self.assertEqual(404, self.request('work-order-preview', {'runId': self.run_id, 'orderId': body['orderId']}, project='B')[0])
        previous = self.sessions.rows[self.fixture.sid].subject_id
        self.sessions.rows[self.fixture.sid].subject_id = str(uuid4())
        self.assertEqual(404, self.preview()[0]); self.sessions.rows[self.fixture.sid].subject_id = previous
        fixture_http.ProjectsAuthority.permissions['member']['Demo-PDS'] = 'viewer'
        self.assertEqual(403, self.preview()[0]); self.assertEqual(403, self.request('work-order-apply', body)[0])
        self.assertEqual(1, self.model.call_count)

    def test_changed_sources_policy_and_deleted_analysis_never_write(self):
        _, preview = self.preview(); body = self.body(preview)
        self.deleted = True
        status, error = self.request('work-order-apply', body); self.assertEqual((409, 'ANALYSIS_TRASHED'), (status, error['code']))
        self.deleted = False
        from apps.api.assistant_store import DEFAULT
        self.sessions.assistant.store.publish('Demo-PDS', self.sessions.rows[self.fixture.sid].subject_id,
            {'requestId': str(uuid4()), 'expectedRevision': 1, 'policy': DEFAULT}, lambda: None)
        self.assertEqual(409, self.preview()[0]); self.assertEqual(409, self.request('work-order-apply', body)[0])
        self.assertEqual(2, self.orders.detail({'orderId': body['orderId']})['orderRevision'])
        self.assertEqual(1, self.model.call_count)

    def test_current_order_version_and_no_client_conclusion_override(self):
        _, preview = self.preview(); body = self.body(preview)
        invalid = {**body, 'conclusion': '不允许客户端携带'}
        self.assertEqual(422, self.request('work-order-apply', invalid)[0])
        self.orders.action({'requestId': str(uuid4()), 'orderId': body['orderId'], 'expectedOrderRevision': 2,
                           'action': 'investigate', 'checks': [], 'note': ''}, 'synthetic-person', lambda: None)
        status, error = self.request('work-order-apply', body)
        self.assertEqual((409, 'WORK_ORDER_CHANGED'), (status, error['code']))
        self.assertNotIn('assistantTransfers', self.orders.detail({'orderId': body['orderId']}))
        self.assertEqual(1, self.model.call_count)

    def test_material_summary_changes_hide_suggestions_without_another_model(self):
        _, preview = self.preview(); body = self.body(preview)
        with patch('apps.api.assistant_retrieval.material_summary', return_value={'summaryHash': 'f'*64}):
            self.assertEqual(409, self.preview()[0]); self.assertEqual(409, self.request('work-order-apply', body)[0])
        self.assertEqual(2, self.orders.detail({'orderId': body['orderId']})['orderRevision'])
        self.assertEqual(1, self.model.call_count)
