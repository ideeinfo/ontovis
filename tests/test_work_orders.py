"""Real project SQLite transactions; all alarms and engineering inputs are synthetic."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
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
            detail = self.action(detail, 'submit', checks=[check['id'] for check in detail['diagnosis']['checks']])
            detail = self.action(detail, 'close')
            self.assertEqual(detail['state'], 'closed')
            self.assertEqual([event['to'] for event in detail['events']], ['open', 'diagnosing', 'investigating', 'review', 'closed'])
            self.assertEqual(self.orders.detail({'orderId': item['orderId']}), detail)
        reopened = self.action(self.first(), 'reopen')
        self.assertEqual((reopened['state'], reopened['checks']), ('investigating', []))

    def test_required_checks_and_review_notes_and_return(self):
        self.seed(); detail = self.action(self.action(self.first(), 'accept'), 'investigate')
        self.error('WORK_ORDER_CHECKS_REQUIRED', self.action, detail, 'submit', checks=[])
        self.error('INVALID_REQUEST', self.action, detail, 'submit', note='  ')
        reviewed = self.action(detail, 'submit', checks=[check['id'] for check in detail['diagnosis']['checks']])
        self.error('WORK_ORDER_CHECKS_REQUIRED', self.action, reviewed, 'close', checks=[])
        returned = self.action(reviewed, 'return')
        self.assertEqual((returned['state'], returned['checks']), ('investigating', []))

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
