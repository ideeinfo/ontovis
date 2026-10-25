"""Real project SQLite transactions; all alarms and engineering inputs are synthetic."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.demo_faults import diagnosis, scenarios
from apps.api.model_library import ModelLibrary
from apps.api.work_orders import WorkOrders


class WorkOrderTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.library = ModelLibrary(self.root / 'A', 'Demo-PDS', None)
        self.orders = WorkOrders(self.library, 'Demo-PDS')
        self.targets = {key: {'entityUid': 'synthetic-' + key} for key in ('CN', 'CN1')}
        self.guard = lambda: None

    def seed(self, body=None):
        return self.orders.seed(body or {'requestId': str(uuid4()), 'expectedSnapshotRevision': 'work-orders:empty'},
                                self.targets, 'synthetic-admin', self.guard)

    def action(self, detail, action, note='演示检查记录', checks=None, **changes):
        body = {'requestId': str(uuid4()), 'orderId': detail['orderId'], 'expectedOrderRevision': detail['orderRevision'],
                'action': action, 'checks': detail['checks'] if checks is None else checks, 'note': note, **changes}
        return self.orders.action(body, 'synthetic-admin', self.guard)

    def error(self, code, function, *args, **kwargs):
        with self.assertRaises(PreviewError) as result: function(*args, **kwargs)
        self.assertEqual(result.exception.code, code)

    def first(self):
        return self.orders.detail({'orderId': 'DEMO-PDS-WO-001'})

    def complete_plan(self, detail):
        plan = deepcopy(detail['investigation'])
        for step in plan['steps']:
            step.update(outcome='gap', result='合成验收：资料适用性待核实，已记录证据缺口。')
        plan.update(conclusion='演示流程完成；尚不确认现场根因。', reviewBasis='合成记录，仅验证人工复核流程。')
        return self.action(detail, 'save_diagnosis', investigation=plan)

    def test_twenty_unique_orders_seven_typical_codes_and_reference_only_graph(self):
        self.assertEqual(self.seed()['created'], 20)
        result = self.orders.listing({}, True)
        self.assertEqual((result['total'], len({item['orderId'] for item in result['items']})), (20, 20))
        self.assertEqual(len({item['faultCode'] for item in result['items']}), 7)
        self.assertEqual({item['cabinet'] for item in result['items']}, {'CN2', 'CN1'})
        for item in result['items']:
            detail = self.orders.detail({'orderId': item['orderId']})
            self.assertEqual(detail['sourceKind'], 'simulated')
            self.assertFalse(detail['engineeringConfirmation'])
            graph = detail['diagnosis']
            self.assertEqual(graph['source']['projectCode'], 'ON-SHORE')
            self.assertEqual(graph['mode'], 'demonstration_rules')
            identifiers = {node['id'] for node in graph['nodes']}
            self.assertTrue(all(edge['source'] in identifiers and edge['target'] in identifiers for edge in graph['edges']))
        self.assertIn('术语', diagnosis('13058')['gap'])

    def test_legacy_cn_batch_reads_cn2_without_replacing_orders_or_events(self):
        self.seed()
        with self.library.connect() as db:
            db.execute("update work_order_batches set revision='pds-diagnostic-rules:1'")
            db.execute("update work_orders set cabinet='CN' where cabinet='CN2'")
            before={table:[tuple(row) for row in db.execute('select * from '+table)]
                    for table in ('work_order_batches','work_orders','work_order_events')}
        reader=WorkOrders(self.library,'Demo-PDS')
        listing=reader.listing({},False)
        self.assertEqual(listing['total'],20)
        signal=next(row for row in listing['items'] if row['cabinet']=='CN2')
        detail=reader.detail({'orderId':signal['orderId']})
        self.assertEqual(detail['createdRuleRevision'],'pds-diagnostic-rules:1')
        self.assertEqual(detail['diagnosis']['revision'],'pds-diagnostic-rules:2')
        self.assertIn('CN2',{node['id'] for node in detail['diagnosis']['nodes']})
        self.assertEqual(self.seed()['created'],0)
        with self.library.connect() as db:
            after={table:[tuple(row) for row in db.execute('select * from '+table)] for table in before}
        self.assertEqual(before,after)

    def test_seed_retry_and_another_request_do_not_duplicate_or_reset(self):
        body = {'requestId': str(uuid4()), 'expectedSnapshotRevision': 'work-orders:empty'}
        result = self.seed(body)
        self.assertEqual(self.seed(body), result)
        accepted = self.action(self.first(), 'accept')
        self.assertEqual(self.seed()['created'], 0)
        self.assertEqual(self.first()['orderRevision'], accepted['orderRevision'])

    def test_every_order_can_complete_the_demo_lifecycle_and_reopen(self):
        self.seed()
        for item in self.orders.listing({}, True)['items']:
            detail = self.action(item, 'accept')
            detail = self.action(detail, 'investigate')
            detail = self.complete_plan(detail)
            detail = self.action(detail, 'submit', checks=[check['id'] for check in detail['diagnosis']['checks']])
            detail = self.action(detail, 'close')
            self.assertEqual(detail['state'], 'closed')
            self.assertEqual([event['to'] for event in detail['events']], ['open', 'diagnosing', 'investigating', 'investigating', 'review', 'closed'])
            self.assertEqual(self.orders.detail({'orderId': item['orderId']}), detail)
        reopened = self.action(self.first(), 'reopen')
        self.assertEqual((reopened['state'], reopened['checks']), ('investigating', []))
        self.assertFalse(reopened['investigationComplete'])
        self.assertTrue(all(step['outcome'] == 'pending' and not step['result'] for step in reopened['investigation']['steps']))

    def test_required_checks_and_review_notes_and_return(self):
        self.seed(); detail = self.action(self.action(self.first(), 'accept'), 'investigate')
        self.error('WORK_ORDER_CHECKS_REQUIRED', self.action, detail, 'submit', checks=[])
        self.error('INVALID_REQUEST', self.action, detail, 'submit', note='  ')
        self.error('WORK_ORDER_DIAGNOSIS_REQUIRED', self.action, detail, 'submit', checks=[check['id'] for check in detail['diagnosis']['checks']])
        detail = self.complete_plan(detail)
        reviewed = self.action(detail, 'submit', checks=[check['id'] for check in detail['diagnosis']['checks']])
        self.error('WORK_ORDER_CHECKS_REQUIRED', self.action, reviewed, 'close', checks=[])
        returned = self.action(reviewed, 'return')
        self.assertEqual((returned['state'], returned['checks']), ('investigating', []))
        self.assertFalse(returned['investigationComplete'])
        previous = self.orders.diagnosis_history({'orderId': detail['orderId'], 'orderRevision': detail['investigationRevision']})
        self.assertEqual(previous['investigation'], detail['investigation'])

    def test_per_order_edits_are_persisted_pinned_and_isolated(self):
        self.seed(); detail = self.action(self.first(), 'accept')
        other = self.orders.detail({'orderId': 'DEMO-PDS-WO-002'})
        self.assertNotEqual(detail['investigation']['hypotheses'], other['investigation']['hypotheses'])
        plan = deepcopy(detail['investigation'])
        plan['hypotheses'][0].update(description='自定义原因候选', status='supported', basis='合成观察依据')
        plan['steps'].append({'id': 'custom-step', 'title': '自定义核对', 'targetKey': 'CN2', 'outcome': 'pending', 'result': ''})
        saved = self.action(detail, 'save_diagnosis', investigation=plan)
        self.assertEqual(saved['investigation'], plan)
        self.assertEqual(self.orders.detail({'orderId': other['orderId']}), other)
        with patch('apps.api.work_orders.diagnosis', side_effect=AssertionError('pinned source must be read')):
            self.assertEqual(WorkOrders(self.library, 'Demo-PDS').detail({'orderId': detail['orderId']}), saved)
        self.error('WORK_ORDER_CHANGED', self.action, detail, 'save_diagnosis', investigation=plan)

    def test_review_gate_rechecks_every_saved_diagnosis_requirement(self):
        self.seed(); detail = self.complete_plan(self.action(self.action(self.first(), 'accept'), 'investigate'))
        complete = deepcopy(detail['investigation'])
        mutations = [lambda p: p.update(conclusion=''), lambda p: p.update(reviewBasis=''),
            lambda p: p['steps'][0].update(outcome='pending'), lambda p: p['steps'][0].update(result=''),
            lambda p: p['hypotheses'][0].update(status='supported', basis='')]
        for mutate in mutations:
            plan = deepcopy(complete); mutate(plan)
            detail = self.action(detail, 'save_diagnosis', investigation=plan)
            self.assertFalse(detail['investigationComplete'])
            self.error('WORK_ORDER_DIAGNOSIS_REQUIRED', self.action, detail, 'submit', checks=[c['id'] for c in detail['diagnosis']['checks']])

    def test_diagnosis_revisions_are_immutable_and_exact_reads_are_scoped(self):
        self.seed(); detail = self.action(self.first(), 'accept'); saved = self.complete_plan(detail)
        original = self.orders.diagnosis_history({'orderId': detail['orderId'], 'orderRevision': detail['investigationRevision']})
        self.assertEqual(original['investigation'], detail['investigation'])
        for sql in ('update work_order_diagnostics set actor=?', 'delete from work_order_diagnostics where actor=?'):
            with self.assertRaises(sqlite3.IntegrityError), self.library.connect() as db:
                db.execute(sql, ('synthetic-admin',))
        other = WorkOrders(ModelLibrary(self.root / 'B', 'B', None), 'B')
        self.error('NOT_FOUND_OR_FORBIDDEN', other.diagnosis_history, {'orderId': detail['orderId'], 'orderRevision': saved['investigationRevision']})
        self.error('NOT_FOUND_OR_FORBIDDEN', self.orders.diagnosis_history, {'orderId': detail['orderId'], 'orderRevision': 99})
        self.error('INVALID_REQUEST', self.orders.diagnosis_history, {'orderId': detail['orderId'], 'orderRevision': True})

    def test_diagnosis_retry_concurrency_and_revocation_are_transactional(self):
        self.seed(); detail = self.action(self.first(), 'accept'); plan = deepcopy(detail['investigation'])
        plan['conclusion'] = '合成修订'
        request = str(uuid4())
        saved = self.action(detail, 'save_diagnosis', investigation=plan, requestId=request)
        self.assertEqual(self.action(detail, 'save_diagnosis', investigation=plan, requestId=request), saved)
        self.error('REQUEST_REUSE_CONFLICT', self.action, detail, 'save_diagnosis', investigation={**plan, 'conclusion': 'changed'}, requestId=request)
        calls = []
        def guard():
            calls.append(1)
            if len(calls) == 2: raise PreviewError(403, 'FORBIDDEN')
        self.guard = guard
        self.error('FORBIDDEN', self.action, saved, 'save_diagnosis', investigation=plan)
        self.assertEqual(self.first(), saved)
        self.guard = lambda: None
        def submit(_):
            try: return self.action(saved, 'save_diagnosis', investigation=plan)['orderRevision']
            except PreviewError as error: return error.code
        with ThreadPoolExecutor(2) as pool: result = list(pool.map(submit, range(2)))
        self.assertCountEqual(result, [saved['orderRevision'] + 1, 'WORK_ORDER_CHANGED'])

    def test_invalid_diagnosis_and_review_edits_never_modify_rows(self):
        self.seed(); detail = self.action(self.first(), 'accept')
        mutations = [lambda p: p.update(hypotheses=[]), lambda p: p.update(steps=[]),
            lambda p: p.update(extra=True), lambda p: p['steps'][0].update(targetKey='foreign-object'),
            lambda p: p['steps'][0].update(outcome=[]), lambda p: p['steps'][0].update(id='invalid.id'),
            lambda p: p['hypotheses'][0].update(status='confirmed'),
            lambda p: p['steps'].append(deepcopy(p['steps'][0])),
            lambda p: p.update(conclusion='x' * 2001)]
        for mutate in mutations:
            plan = deepcopy(detail['investigation']); mutate(plan)
            self.error('WORK_ORDER_DIAGNOSIS_INVALID', self.action, detail, 'save_diagnosis', investigation=plan)
            self.assertEqual(self.first(), detail)
        plan = deepcopy(detail['investigation']); plan['conclusion'] = '\ud800'
        self.error('INVALID_REQUEST', self.action, detail, 'save_diagnosis', investigation=plan)
        plan = deepcopy(detail['investigation'])
        for i in range(12):
            plan['steps'].append({**plan['steps'][0], 'id': 'huge-' + str(i), 'result': '字' * 2000})
        plan['steps'] = plan['steps'][-12:]
        self.error('WORK_ORDER_DIAGNOSIS_INVALID', self.action, detail, 'save_diagnosis', investigation=plan)
        detail = self.complete_plan(self.action(detail, 'investigate'))
        review = self.action(detail, 'submit', checks=[check['id'] for check in detail['diagnosis']['checks']])
        self.error('WORK_ORDER_STATE_CONFLICT', self.action, review, 'save_diagnosis', investigation=review['investigation'])
        closed = self.action(review, 'close')
        self.error('WORK_ORDER_STATE_CONFLICT', self.action, closed, 'save_diagnosis', investigation=closed['investigation'])

    def test_legacy_closed_orders_are_not_rewritten_on_read(self):
        self.seed()
        with self.library.connect() as db:
            db.execute("update work_orders set state='closed' where order_id='DEMO-PDS-WO-001'")
            before = [tuple(row) for row in db.execute('select * from work_orders')]
        detail = WorkOrders(self.library, 'Demo-PDS').detail({'orderId': 'DEMO-PDS-WO-001'})
        self.assertIsNone(detail['investigationRevision'])
        self.assertFalse(detail['investigationComplete'])
        with self.library.connect() as db:
            self.assertEqual([tuple(row) for row in db.execute('select * from work_orders')], before)
            self.assertEqual(db.execute('select count(*) from work_order_diagnostics').fetchone()[0], 0)

    def test_stale_version_illegal_transition_and_identity_change(self):
        self.seed(); original = self.first()
        self.error('WORK_ORDER_STATE_CONFLICT', self.action, original, 'close')
        self.action(original, 'accept')
        self.error('WORK_ORDER_CHANGED', self.action, original, 'accept')
        changed = {**self.targets, 'CN': {'entityUid': 'different'}}
        self.error('WORK_ORDER_TARGET_CHANGED', self.orders.seed,
                   {'requestId': str(uuid4()), 'expectedSnapshotRevision': 'work-orders:empty'}, changed, 'synthetic-admin', self.guard)

    def test_request_replay_is_actor_bound_and_different_payload_conflicts(self):
        self.seed(); original = self.first()
        body = {'requestId': str(uuid4()), 'orderId': original['orderId'], 'expectedOrderRevision': 1,
                'action': 'accept', 'checks': [], 'note': ''}
        result = self.orders.action(body, 'synthetic-admin', self.guard)
        self.assertEqual(self.orders.action(body, 'synthetic-admin', self.guard), result)
        self.error('REQUEST_REUSE_CONFLICT', self.orders.action, {**body, 'note': 'different'}, 'synthetic-admin', self.guard)
        self.error('REQUEST_REUSE_CONFLICT', self.orders.action, body, 'another-admin', self.guard)
        self.assertEqual(len(self.first()['events']), 2)

    def test_final_guard_rolls_back_orders_events_and_request_receipt(self):
        calls = []
        def guard():
            calls.append(1)
            if len(calls) == 2: raise PreviewError(403, 'FORBIDDEN')
        self.guard = guard
        self.error('FORBIDDEN', self.seed)
        with self.library.connect() as db:
            for table in ('work_order_batches', 'work_orders', 'work_order_events', 'work_order_requests'):
                self.assertEqual(db.execute('select count(*) from ' + table).fetchone()[0], 0)

    def test_revocation_rolls_back_action_and_cannot_replay_success(self):
        self.seed(); original = self.first(); calls = []
        def guard():
            calls.append(1)
            if len(calls) == 2: raise PreviewError(403, 'FORBIDDEN')
        self.guard = guard
        self.error('FORBIDDEN', self.action, original, 'accept')
        self.assertEqual(self.first(), original)

    def test_concurrent_accept_has_one_winner(self):
        self.seed(); original = self.first()
        def submit(_):
            try: return self.action(original, 'accept')['state']
            except PreviewError as error: return error.code
        with ThreadPoolExecutor(2) as pool: result = list(pool.map(submit, range(2)))
        self.assertCountEqual(result, ['diagnosing', 'WORK_ORDER_CHANGED'])
        self.assertEqual(len(self.first()['events']), 2)

    def test_new_consumer_reads_persisted_progress_and_project_isolation(self):
        self.seed(); detail = self.action(self.first(), 'accept')
        reopened = WorkOrders(self.library, 'Demo-PDS')
        self.assertEqual(reopened.detail({'orderId': detail['orderId']}), detail)
        other = WorkOrders(ModelLibrary(self.root / 'B', 'B', None), 'B')
        self.assertEqual(other.listing({}, True)['total'], 0)
        self.error('WORKSPACE_SCOPE_INVALID', WorkOrders, self.library, 'B')
        self.error('NOT_FOUND_OR_FORBIDDEN', other.detail, {'orderId': detail['orderId']})
        self.error('DEMO_PROJECT_REQUIRED', other.seed,
                   {'requestId': str(uuid4()), 'expectedSnapshotRevision': 'work-orders:empty'}, self.targets, 'admin', self.guard)

    def test_filtered_pagination_has_snapshot_and_literal_search(self):
        self.seed(); result = self.orders.listing({'limit': 3}, True)
        self.assertEqual((len(result['items']), result['nextCursor'], result['total']), (3, 3, 20))
        next_page = self.orders.listing({'limit': 3, 'cursor': 3, 'expectedSnapshotRevision': result['snapshotRevision']}, True)
        self.assertFalse({x['orderId'] for x in result['items']} & {x['orderId'] for x in next_page['items']})
        self.action(self.first(), 'accept')
        self.error('WORK_ORDER_CHANGED', self.orders.listing,
                   {'cursor': 3, 'expectedSnapshotRevision': result['snapshotRevision']}, True)
        self.assertEqual(self.orders.listing({'q': '%'}, True)['total'], 0)
        self.assertEqual(self.orders.listing({'q': '13001'}, True)['total'], 3)

    def test_budget_and_parameter_rejections_leave_records_unchanged(self):
        self.seed(); original = self.first()
        for change in ({'expectedOrderRevision': True}, {'requestId': 'bad'}, {'checks': ['unknown']},
                       {'checks': ['review', 'review']}, {'note': 'x' * 2001}, {'extra': True}):
            self.error('INVALID_REQUEST', self.action, original, 'accept', **change)
        self.assertEqual(self.first(), original)
        for body in ({'limit': 0}, {'limit': True}, {'state': 'unknown'}, {'q': []}, {'cursor': -1}):
            self.error('INVALID_REQUEST', self.orders.listing, body, True)


if __name__ == '__main__': unittest.main()
