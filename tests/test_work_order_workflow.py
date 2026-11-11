"""Workflow state, retained records and version races in a real SQLite library."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from apps.api import work_order_workflow as workflow
from apps.api.assistant_summaries import work_order_summary
from apps.api.authority import PreviewError
from apps.api.model_library import ModelLibrary
from apps.api.work_orders import WorkOrders, digest


class WorkOrderWorkflowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.orders = WorkOrders(ModelLibrary(Path(temp.name), 'Demo-PDS', None), 'Demo-PDS')
        self.admin = str(uuid4())
        self.reviewer = str(uuid4())
        self.guard = lambda: None

    def create(self, **fields):
        body = {'requestId': str(uuid4()), 'title': '普通处置任务', 'issue': '核对采集通道', **fields}
        value = workflow.create(self.orders, body, self.admin, '管理员', self.guard)
        self.assertEqual(workflow.create(self.orders, body, self.admin, '管理员', self.guard), value)
        return self.orders.detail({'orderId': value['orderId']})

    def request(self, order, action, **fields):
        return {'requestId': str(uuid4()), 'orderId': order['orderId'],
                'expectedOrderRevision': order['orderRevision'], 'action': action, **fields}

    def apply(self, order, action, **fields):
        return workflow.update(self.orders, self.request(order, action, **fields),
                               self.admin, '管理员', 'admin', self.guard)

    def test_complete_from_text_then_archive_and_reopen_preserves_result(self):
        order = self.apply(self.create(), 'accept')
        occurred_at = '2026-11-11T03:00:00Z'
        order = self.apply(order, 'record', text='已核对登记编号，并记录复测结果。', occurredAt=occurred_at)
        record = order['workflow']['records'][0]
        order = self.apply(order, 'correct_record', recordId=record['recordId'], text='已核对编号并完成复测。')
        self.assertEqual(order['workflow']['records'][0]['occurredAt'], occurred_at)
        self.assertEqual(len(workflow.record_history(self.orders, {
            'orderId': order['orderId'], 'recordId': record['recordId'],
        })['items']), 2)
        completed = self.apply(order, 'complete', recordId=record['recordId'])
        archived = self.apply(completed, 'archive')
        self.assertEqual(archived['state'], 'archived')
        with self.assertRaisesRegex(PreviewError, 'WORK_ORDER_STATE_CONFLICT'):
            self.apply(archived, 'record', text='旧周期禁止修改')
        reopened = self.apply(archived, 'reopen', reason='新一轮复测')
        self.assertEqual(reopened['workflow']['cycle'], 2)
        self.assertIsNone(reopened['workflow']['result'])
        self.assertEqual(len(reopened['workflow']['records']), 1)
        fixed = self.orders.fixed_snapshot({'orderId': archived['orderId'],
            'orderRevision': archived['orderRevision'], 'snapshotSha256': digest(archived)})
        self.assertEqual(fixed['workflow']['result']['text'], '已核对编号并完成复测。')

    def test_legacy_transition_keeps_original_snapshot(self):
        self.orders.seed({'requestId': str(uuid4()), 'expectedSnapshotRevision': 'work-orders:empty'},
                         {'CN': {'entityUid': 'fixture-a'}, 'CN1': {'entityUid': 'fixture-b'}}, '管理员', self.guard)
        original = self.orders.detail({'orderId': 'DEMO-PDS-WO-001'})
        saved = self.apply(original, 'accept')
        self.assertEqual(saved['workflow']['legacyState'], 'open')
        fixed = self.orders.fixed_snapshot({'orderId': original['orderId'], 'orderRevision': 1,
                                           'snapshotSha256': digest(original)})
        self.assertEqual(fixed, original)
        with self.assertRaisesRegex(PreviewError, 'WORK_ORDER_USE_WORKFLOW'):
            self.orders.action({**self.request(saved, 'save'), 'note': '', 'checks': []}, '管理员', self.guard)

    def test_assigned_reviewer_and_replay_guard(self):
        order = self.create()
        assigned = workflow.update(self.orders, self.request(order, 'assign', handlerId=self.reviewer),
            self.admin, '管理员', 'admin', self.guard,
            resolve=lambda *_: {'userId': self.reviewer, 'name': '处理人员'})
        body = self.request(assigned, 'record', text='处理人员登记观察结果')
        saved = workflow.update(self.orders, body, self.reviewer, '处理人员', 'reviewer', self.guard)
        self.assertEqual(workflow.update(self.orders, body, self.reviewer, '处理人员', 'reviewer', self.guard), saved)
        with self.assertRaisesRegex(PreviewError, 'WORK_ORDER_WRITE_FORBIDDEN'):
            workflow.update(self.orders, body, self.reviewer, '处理人员', 'viewer', self.guard)
        workflow.update(self.orders, self.request(saved, 'assign', handlerId=self.admin),
            self.admin, '管理员', 'admin', self.guard,
            resolve=lambda *_: {'userId': self.admin, 'name': '管理员'})
        with self.assertRaisesRegex(PreviewError, 'WORK_ORDER_HANDLER_REQUIRED'):
            workflow.update(self.orders, body, self.reviewer, '处理人员', 'reviewer', self.guard)

    def test_concurrent_adoption_and_actual_record_summary(self):
        order = self.apply(self.create(faultCode='13001', simulated=True), 'accept')
        def adopt(index):
            fixed = {'analysisSessionId': str(uuid4()), 'analysisRevision': 3, 'analysisSha256': str(index)*64}
            try:
                return workflow.update(self.orders, self.request(order, 'adopt_analysis', **fixed),
                    self.admin, '管理员', 'admin', self.guard, resolve=lambda *_: fixed)
            except PreviewError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(adopt, [1, 2]))
        self.assertIn('WORK_ORDER_CHANGED', results)
        saved = next(row for row in results if isinstance(row, dict))
        recorded = self.apply(saved, 'record', text='现场人员报告复测读数稳定。')
        summary = work_order_summary(recorded, ())
        self.assertIn('现场人员报告复测读数稳定。', summary)
        self.assertIn('"result":null', summary)
        self.assertNotIn(saved['workflow']['adoptedAnalysis']['analysisSessionId'], summary)
        self.assertIn(recorded['workflow']['records'][0]['recordId'], summary)
        self.assertLessEqual(len(summary), 1000)
