"""Synthetic assistant answers, real project work-order transactions."""
from copy import deepcopy
import sqlite3
import unittest
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.assistant_work_orders import proposal
from apps.api.assistant_store import encoded
from tests import test_work_orders as order_tests


def synthetic_run():
    return {'runId': str(uuid4()), 'version': 5, 'state': 'complete', 'conversationId': str(uuid4()),
            'conversationVersion': 2, 'analysisSessionId': str(uuid4()), 'analysisRevision': 3,
            'sources': [{'key': 'E3', 'kind': 'object', 'evidenceRefId': str(uuid4()), 'sourceRevision': 'r1',
                         'summaryHash': 'a' * 64, 'retrievalRevision': 'b' * 64, 'availability': 'available'}],
            'result': {'answer': {'observations': [{'text': '合成观察，不自动填写结果', 'refs': ['E3']}],
                       'hypotheses': [{'text': '合成测量链偏差假设', 'refs': ['E3']}],
                       'nextSteps': [{'text': '核对独立参照温度', 'refs': ['E3']}],
                       'gaps': [{'text': '缺适用手册', 'refs': []}]}}}


class AssistantWorkOrderTests(unittest.TestCase):
    def setUp(self):
        self.fixture = order_tests.WorkOrderTests(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.fixture.seed(); self.orders = self.fixture.orders
        self.detail = self.fixture.action(self.fixture.first(), 'accept')
        self.run = synthetic_run(); self.proposed = proposal(self.run)
        self.analysis = {'contentSha256': 'c' * 64}

    def body(self, ids=('hypotheses-0', 'nextSteps-0'), detail=None):
        return {'requestId': str(uuid4()), 'orderId': self.detail['orderId'],
                'expectedOrderRevision': (detail or self.detail)['orderRevision'], 'runId': self.run['runId'],
                'expectedProposalSha256': self.proposed['proposalSha256'],
                'items': [{'id': key, 'text': next(r['text'] for r in self.proposed['items'] if r['id'] == key),
                           'targetKey': ''} for key in ids]}

    def apply(self, body, guard=lambda: None):
        return self.orders.apply_assistant(body, 'synthetic-person', guard, self.proposed, self.analysis)

    def error(self, code, call):
        with self.assertRaises(PreviewError) as found: call()
        self.assertEqual(code, found.exception.code)

    def counts(self):
        with self.orders.library.connect() as db:
            return {name: db.execute('select count(*) from ' + name).fetchone()[0] for name in
                    ('work_order_events', 'work_order_snapshots', 'work_order_diagnostics',
                     'work_order_assistant_transfers', 'work_order_analysis_links', 'work_order_requests')}

    def test_selected_edits_append_without_observations_results_or_state_changes(self):
        body = self.body(); body['items'][0]['text'] = '人工编辑的待验证假设'
        result = self.apply(body)
        self.assertEqual(self.detail['state'], result['state'])
        for key in ('note', 'checks', 'engineeringConfirmation'):
            self.assertEqual(self.detail[key], result[key])
        plan = result['investigation']; old = self.detail['investigation']
        self.assertEqual(old['hypotheses'], plan['hypotheses'][:-1]); self.assertEqual(old['steps'], plan['steps'][:-1])
        self.assertEqual({'status': 'candidate', 'basis': ''}, {k: plan['hypotheses'][-1][k] for k in ('status', 'basis')})
        self.assertEqual('人工编辑的待验证假设', plan['hypotheses'][-1]['description'])
        self.assertEqual(('pending', ''), (plan['steps'][-1]['outcome'], plan['steps'][-1]['result']))
        self.assertEqual((old['conclusion'], old['reviewBasis']), (plan['conclusion'], plan['reviewBasis']))
        transfer = result['assistantTransfers'][0]
        self.assertEqual('合成测量链偏差假设', transfer['items'][0]['originalText'])
        self.assertEqual('E3', transfer['sources'][0]['key'])
        self.assertEqual(self.run['sources'][0]['evidenceRefId'], transfer['sources'][0]['evidenceRefId'])
        self.assertFalse(transfer['engineeringConfirmation']); self.assertEqual(2, len(transfer['items']))
        self.assertEqual(self.run['analysisRevision'], result['analysisLinks'][-1]['analysisRevision'])
        self.assertFalse(result['investigationComplete'])

    def test_replay_and_additional_unselected_items_are_not_duplicate_writes(self):
        body = self.body(); first = self.apply(body); before = self.counts()
        self.assertEqual(first, self.apply(body)); self.assertEqual(before, self.counts())
        duplicate = self.body(detail=first)
        self.error('ASSISTANT_ITEM_ALREADY_APPLIED', lambda: self.apply(duplicate))
        second = self.apply(self.body(('gaps-0',), first))
        self.assertEqual(2, len(second['assistantTransfers']))
        self.assertTrue(second['investigation']['steps'][-1]['title'].startswith('补充证据：'))

    def test_changed_revision_or_proposal_rolls_back_all_tables(self):
        before = self.counts(); stale = self.body(); stale['expectedOrderRevision'] -= 1
        self.error('WORK_ORDER_CHANGED', lambda: self.apply(stale))
        wrong = self.body(); wrong['expectedProposalSha256'] = 'd' * 64
        self.error('ASSISTANT_PROPOSAL_CHANGED', lambda: self.apply(wrong))
        self.assertEqual(before, self.counts())

    def test_unaccepted_and_closed_orders_cannot_be_changed(self):
        body = self.body(); body.update(orderId='DEMO-PDS-WO-002', expectedOrderRevision=1)
        self.error('WORK_ORDER_STATE_CONFLICT', lambda: self.apply(body))
        with self.orders.library.connect() as db:
            db.execute("update work_orders set state='closed' where order_id=?", (self.detail['orderId'],))
        self.error('WORK_ORDER_STATE_CONFLICT', lambda: self.apply(self.body()))

    def test_invalid_and_excessive_items_never_set_supported_results_or_conclusion(self):
        before = self.counts()
        for patch in ({'status': 'supported'}, {'outcome': 'observed'}, {'targetKey': 'unknown'},
                      {'id': 'observations-0'}, {'text': '   '}):
            body = self.body(); body['items'][0].update(patch)
            self.error('ASSISTANT_TRANSFER_INVALID', lambda: self.apply(body))
        plan = deepcopy(self.detail['investigation'])
        while len(plan['hypotheses']) < 6:
            plan['hypotheses'].append({'id': str(uuid4()), 'description': '占位', 'status': 'candidate', 'basis': ''})
        current = self.fixture.action(self.detail, 'save_diagnosis', investigation=plan)
        self.error('WORK_ORDER_PLAN_LIMIT', lambda: self.apply(self.body(detail=current)))
        self.assertEqual(0, self.counts()['work_order_assistant_transfers'])
        self.assertEqual(before['work_order_analysis_links'], self.counts()['work_order_analysis_links'])

    def test_final_guard_failure_rolls_back_and_no_new_snapshot_breaks_legacy_capture(self):
        self.orders.capture({'orderId': self.detail['orderId'], 'expectedOrderRevision': self.detail['orderRevision']},
                            'synthetic-person', lambda: None)
        before = self.counts(); calls = []
        def guard():
            calls.append(True)
            if len(calls) > 1: raise PreviewError(409, 'ACCESS_CHANGED')
        self.error('ACCESS_CHANGED', lambda: self.apply(self.body(), guard))
        self.assertEqual(before, self.counts())
        result = self.apply(self.body())
        with self.orders.library.connect() as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('delete from work_order_assistant_transfers')
        later = self.fixture.action(result, 'save_diagnosis', investigation=result['investigation'])
        self.assertEqual(result['assistantTransfers'], later['assistantTransfers'])

    def test_hidden_or_unavailable_answer_and_invalid_reference_cannot_form_proposal(self):
        value = deepcopy(self.run); value['state'] = 'changed'
        self.error('ASSISTANT_TRANSFER_UNAVAILABLE', lambda: proposal(value))
        value = deepcopy(self.run); value['result']['answer']['hypotheses'][0]['refs'] = ['E1']
        self.error('ASSISTANT_REFERENCE_INVALID', lambda: proposal(value))

    def test_backup_checks_selected_text_and_refs_against_the_original_run(self):
        from tools.analysis_workbench_backup import _assistant_transfer
        result = self.apply(self.body()); transfer = result['assistantTransfers'][0]
        record = {'id': self.run['runId'], 'version': self.run['version'], 'state': 'complete',
                  'analysis_id': self.run['analysisSessionId'], 'analysis_revision': self.run['analysisRevision'],
                  'policy_revision': 1, 'created_at': 'synthetic-time', 'updated_at': 'synthetic-time',
                  'input_json': encoded({'question': '合成问题'}), 'sources_json': encoded(self.run['sources']),
                  'progress_json': '[]', 'result_json': encoded(self.run['result']), 'error_code': None,
                  'conversation_id': self.run['conversationId'], 'turn_no': self.run['conversationVersion'],
                  'parent_run_id': None, 'connection_id': 'synthetic-connection', 'project_code': 'Demo-PDS',
                  'owner': 'synthetic-person'}
        def verify(saved, receipt=record):
            return _assistant_transfer(receipt, saved, 'synthetic-connection', 'Demo-PDS', result['orderRevision'],
                self.run['analysisSessionId'], self.run['analysisRevision'], 'synthetic-person', 'c'*64,
                result['investigation'], result['diagnosis'])
        verify(transfer)
        for key, value in [('originalText', '伪造原文'), ('refs', ['E1']), ('text', '不等于保存时的条目')]:
            changed = deepcopy(transfer); changed['items'][0][key] = value
            self.error('ANALYSIS_PAIR_ASSISTANT_MISMATCH', lambda: verify(changed))
        self.error('ANALYSIS_PAIR_ASSISTANT_MISMATCH', lambda: verify(transfer, {**record, 'project_code': 'OTHER'}))
