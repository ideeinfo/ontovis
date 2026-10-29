"""Project-local demo work orders; every mutation has a guarded transaction."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from uuid import UUID

from .authority import PreviewError
from .demo_faults import BATCH, DEMO_PROJECT, RULE_REVISION, diagnosis, scenarios
from .work_order_diagnosis import initial_plan, validate_plan, complete, reset_results

STATES = ('open', 'diagnosing', 'investigating', 'review', 'closed')
TRANSITIONS = {'accept': ('open', 'diagnosing'), 'investigate': ('diagnosing', 'investigating'),
               'submit': ('investigating', 'review'), 'return': ('review', 'investigating'),
               'close': ('review', 'closed'), 'reopen': ('closed', 'investigating')}


def require(value, code='INVALID_REQUEST', status=422):
    if not value:
        raise PreviewError(status, code)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    try:
        return hashlib.sha256(encoded(value).encode()).hexdigest()
    except (UnicodeError, ValueError):
        raise PreviewError(422, 'INVALID_REQUEST') from None


def text(value, limit=2000, *, empty=False):
    require(isinstance(value, str) and len(value) <= limit and (empty or value.strip())
            and all(ord(c) >= 32 or c in '\n\r\t' for c in value))
    return value.strip()


class WorkOrders:
    def __init__(self, library, project_code):
        self.library, self.project_code = library, project_code
        with library.connect() as db:
            scope = db.execute('select project_code from library where id=1').fetchone()
            require(scope is not None and scope[0] == project_code, 'WORKSPACE_SCOPE_INVALID', 409)
            db.executescript('''
                create table if not exists work_order_batches (
                    batch_id text primary key, revision text not null, targets text not null, created_at text not null);
                create table if not exists work_orders (
                    order_id text primary key, batch_id text not null, ordinal integer not null,
                    fault_code text not null, title text not null, cabinet text not null,
                    state text not null, revision integer not null, alarm_at text not null,
                    updated_at text not null, checks text not null, note text not null,
                    unique(batch_id, ordinal));
                create table if not exists work_order_events (
                    order_id text not null, revision integer not null, action text not null,
                    actor text not null, recorded_at text not null, previous_state text,
                    state text not null, note text not null, primary key(order_id, revision));
                create table if not exists work_order_requests (
                    request_id text primary key, payload_sha256 text not null, response text not null);
                create table if not exists work_order_diagnostics (
                    order_id text not null references work_orders(order_id), order_revision integer not null,
                    snapshot text not null, source_graph text not null, actor text not null, recorded_at text not null,
                    primary key(order_id, order_revision));
                create trigger if not exists work_order_diagnostics_no_update before update on work_order_diagnostics
                    begin select raise(abort, 'immutable investigation revision'); end;
                create trigger if not exists work_order_diagnostics_no_delete before delete on work_order_diagnostics
                    begin select raise(abort, 'retained investigation revision'); end;
                create table if not exists work_order_snapshots (
                    order_id text not null references work_orders(order_id), order_revision integer not null,
                    snapshot_json text not null, content_sha256 text not null, actor text not null, recorded_at text not null,
                    primary key(order_id,order_revision));
                create trigger if not exists work_order_snapshots_no_update before update on work_order_snapshots
                    begin select raise(abort, 'immutable work order snapshot'); end;
                create trigger if not exists work_order_snapshots_no_delete before delete on work_order_snapshots
                    begin select raise(abort, 'retained work order snapshot'); end;
                create table if not exists work_order_analysis_links (
                    order_id text not null references work_orders(order_id), order_revision integer not null,
                    analysis_session_id text not null, analysis_revision integer not null, analysis_sha256 text not null,
                    primary key(order_id,order_revision));
                create trigger if not exists work_order_analysis_links_no_update before update on work_order_analysis_links
                    begin select raise(abort, 'immutable analysis link'); end;
                create trigger if not exists work_order_analysis_links_no_delete before delete on work_order_analysis_links
                    begin select raise(abort, 'retained analysis link'); end;
                create table if not exists work_order_assistant_transfers (
                    order_id text not null references work_orders(order_id), order_revision integer not null,
                    run_id text not null, snapshot_json text not null, primary key(order_id,order_revision));
                create trigger if not exists work_order_assistant_transfers_no_update before update on work_order_assistant_transfers
                    begin select raise(abort, 'immutable assistant transfer'); end;
                create trigger if not exists work_order_assistant_transfers_no_delete before delete on work_order_assistant_transfers
                    begin select raise(abort, 'retained assistant transfer'); end;
            ''')

    @staticmethod
    def empty(can_seed=False):
        return {'items': [], 'total': 0, 'nextCursor': None, 'snapshotRevision': 'work-orders:empty',
                'capabilities': {'canWrite': False, 'canSeedDemo': can_seed}, 'sourceKind': 'simulated'}

    @staticmethod
    def _snapshot(db):
        rows = db.execute('select order_id,revision from work_orders order by order_id').fetchall()
        return 'work-orders:' + digest([list(row) for row in rows]) if rows else 'work-orders:empty'

    @staticmethod
    def _public(row):
        return {'orderId': row['order_id'], 'batchId': row['batch_id'], 'number': row['ordinal'],
                'faultCode': row['fault_code'], 'title': row['title'],
                'cabinet': 'CN2' if row['batch_id'] == BATCH and row['cabinet'] == 'CN' else row['cabinet'],
                'state': row['state'], 'orderRevision': row['revision'], 'alarmAt': row['alarm_at'],
                'updatedAt': row['updated_at'], 'checks': json.loads(row['checks']), 'note': row['note'],
                'sourceKind': 'simulated', 'engineeringConfirmation': False}

    def listing(self, body, can_write):
        require(set(body) <= {'q', 'state', 'cursor', 'limit', 'expectedSnapshotRevision'})
        q = text(body.get('q', ''), 200, empty=True)
        state, start, limit = body.get('state', ''), body.get('cursor', 0), body.get('limit', 50)
        require(state in ('', *STATES) and type(start) is int and 0 <= start <= 10000
                and type(limit) is int and 1 <= limit <= 50)
        with self.library.connect() as db:
            snapshot = self._snapshot(db)
            if start or 'expectedSnapshotRevision' in body:
                require(body.get('expectedSnapshotRevision') == snapshot, 'WORK_ORDER_CHANGED', 409)
            # Escape LIKE metacharacters so a search is a literal phrase.
            phrase = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            predicate = "(title like ? escape '\\' or fault_code like ? escape '\\' or order_id like ? escape '\\') and (?='' or state=?)"
            params = (phrase, phrase, phrase, state, state)
            total = db.execute('select count(*) from work_orders where ' + predicate, params).fetchone()[0]
            rows = db.execute('select * from work_orders where ' + predicate + ' order by ordinal limit ? offset ?',
                              (*params, limit, start)).fetchall()
            return {'items': [self._public(row) for row in rows], 'total': total,
                    'nextCursor': start + limit if start + limit < total else None, 'snapshotRevision': snapshot,
                    'capabilities': {'canWrite': can_write, 'canSeedDemo': can_write and self.project_code == DEMO_PROJECT},
                    'sourceKind': 'simulated'}

    def _detail(self, db, identifier):
        row = db.execute('select * from work_orders where order_id=?', (identifier,)).fetchone()
        require(row is not None, 'NOT_FOUND_OR_FORBIDDEN', 404)
        batch = db.execute('select * from work_order_batches where batch_id=?', (row['batch_id'],)).fetchone()
        events = db.execute('select * from work_order_events where order_id=? order by revision', (identifier,)).fetchall()
        require(len(events) <= 100, 'WORK_ORDER_EVENT_LIMIT', 413)
        record = db.execute('select * from work_order_diagnostics where order_id=? order by order_revision desc limit 1', (identifier,)).fetchone()
        graph = json.loads(record['source_graph']) if record else diagnosis(row['fault_code'])
        plan = json.loads(record['snapshot']) if record else initial_plan(row['fault_code'], graph)
        transfers = [json.loads(saved[0]) for saved in db.execute(
            'select snapshot_json from work_order_assistant_transfers where order_id=? order by order_revision', (identifier,))]
        return {**self._public(row), 'diagnosis': graph, 'investigation': plan,
                **({'assistantTransfers': transfers} if transfers else {}),
                'investigationRevision': record['order_revision'] if record else None,
                'investigationComplete': bool(record) and complete(plan),
                'investigationHistory': [{'orderRevision': saved['order_revision'], 'actor': saved['actor'], 'recordedAt': saved['recorded_at']}
                    for saved in db.execute('select order_revision,actor,recorded_at from work_order_diagnostics where order_id=? order by order_revision desc', (identifier,))],
                'createdRuleRevision': batch['revision'], 'targets': json.loads(batch['targets']),
                'analysisLinks': [{'orderRevision': link['order_revision'], 'analysisSessionId': link['analysis_session_id'],
                    'analysisRevision': link['analysis_revision'], 'analysisSha256': link['analysis_sha256']}
                    for link in db.execute('select * from work_order_analysis_links where order_id=? order by order_revision', (identifier,))],
                'events': [{'revision': event['revision'], 'action': event['action'], 'actor': event['actor'],
                            'recordedAt': event['recorded_at'], 'from': event['previous_state'],
                            'to': event['state'], 'note': event['note']} for event in events]}

    def detail(self, body):
        require(set(body) == {'orderId'})
        identifier = text(body['orderId'], 100)
        with self.library.connect() as db:
            return self._detail(db, identifier)

    def diagnosis_history(self, body):
        require(set(body) == {'orderId', 'orderRevision'} and type(body['orderRevision']) is int and body['orderRevision'] > 0)
        identifier = text(body['orderId'], 100)
        with self.library.connect() as db:
            row = db.execute('select * from work_order_diagnostics where order_id=? and order_revision=?',
                             (identifier, body['orderRevision'])).fetchone()
            require(row is not None, 'NOT_FOUND_OR_FORBIDDEN', 404)
            return {'orderId': identifier, 'orderRevision': row['order_revision'], 'investigation': json.loads(row['snapshot']),
                    'diagnosis': json.loads(row['source_graph']), 'actor': row['actor'], 'recordedAt': row['recorded_at']}

    def _retain(self, db, value, actor):
        raw = encoded(value)
        require(len(raw.encode()) <= 128 * 1024, 'WORK_ORDER_SNAPSHOT_LIMIT', 413)
        db.execute('insert or ignore into work_order_snapshots values(?,?,?,?,?,?)',
            (value['orderId'], value['orderRevision'], raw, digest(value), actor, value['updatedAt']))
        stored = db.execute('select snapshot_json from work_order_snapshots where order_id=? and order_revision=?',
                            (value['orderId'], value['orderRevision'])).fetchone()
        require(stored[0] == raw, 'WORK_ORDER_SNAPSHOT_CHANGED', 409)

    def capture(self, body, actor, guard):
        require(set(body) == {'orderId', 'expectedOrderRevision'})
        require(type(body['expectedOrderRevision']) is int and body['expectedOrderRevision'] > 0)
        identifier = text(body['orderId'], 100); text(actor, 200)
        with self.library.connect() as db:
            db.execute('begin immediate'); guard()
            value = self._detail(db, identifier)
            require(value['orderRevision'] == body['expectedOrderRevision'], 'WORK_ORDER_CHANGED', 409)
            self._retain(db, value, actor); guard()
            return {'orderId': identifier, 'orderRevision': value['orderRevision'], 'snapshotSha256': digest(value)}

    def fixed_snapshot(self, body):
        require(set(body) == {'orderId', 'orderRevision', 'snapshotSha256'})
        require(type(body['orderRevision']) is int and body['orderRevision'] > 0)
        with self.library.connect() as db:
            row = db.execute('select snapshot_json,content_sha256 from work_order_snapshots where order_id=? and order_revision=?',
                (text(body['orderId'], 100), body['orderRevision'])).fetchone()
            require(row is not None, 'WORK_ORDER_HISTORY_UNAVAILABLE', 404)
            require(row['content_sha256'] == body['snapshotSha256'], 'WORK_ORDER_SNAPSHOT_CHANGED', 409)
            value = json.loads(row['snapshot_json'])
            require(digest(value) == row['content_sha256'], 'WORK_ORDER_STORAGE_INVALID', 409)
            return value

    def link_analysis(self, body, actor, guard, analysis_guard):
        require(set(body) == {'requestId', 'orderId', 'expectedOrderRevision', 'analysisSessionId',
                             'analysisRevision', 'analysisSha256'})
        identifier = text(body['orderId'], 100)
        require(type(body['expectedOrderRevision']) is int and 1 <= body['expectedOrderRevision'] < 100)
        require(type(body['analysisRevision']) is int and 1 <= body['analysisRevision'] <= 1000)
        try:
            require(str(UUID(body['analysisSessionId'])) == body['analysisSessionId'])
        except (ValueError, TypeError, AttributeError):
            raise PreviewError(422, 'INVALID_REQUEST') from None
        require(type(body['analysisSha256']) is str and len(body['analysisSha256']) == 64
                and all(c in '0123456789abcdef' for c in body['analysisSha256']))
        def operation(db):
            value = self._detail(db, identifier)
            require(value['orderRevision'] == body['expectedOrderRevision'], 'WORK_ORDER_CHANGED', 409)
            self._retain(db, value, actor)
            revision = value['orderRevision'] + 1; stamp = datetime.now(timezone.utc).isoformat()
            analysis_guard()
            db.execute('insert into work_order_analysis_links values(?,?,?,?,?)',
                (identifier, revision, body['analysisSessionId'], body['analysisRevision'], body['analysisSha256']))
            db.execute('update work_orders set revision=?,updated_at=? where order_id=?', (revision, stamp, identifier))
            db.execute('insert into work_order_events values(?,?,?,?,?,?,?,?)',
                (identifier, revision, 'link_analysis', actor, stamp, value['state'], value['state'], '关联已保存分析修订'))
            value = self._detail(db, identifier); self._retain(db, value, actor)
            analysis_guard()
            return {'orderId': identifier, 'orderRevision': revision,
                    'analysisSessionId': body['analysisSessionId'], 'analysisRevision': body['analysisRevision'],
                    'analysisSha256': body['analysisSha256']}
        def authorized():
            guard(); analysis_guard()
        return self._mutate(body, actor, authorized, operation)

    def _mutate(self, body, actor, guard, operation):
        text(actor, 200)
        try:
            request_id = str(UUID(body.get('requestId')))
        except (ValueError, TypeError, AttributeError):
            raise PreviewError(422, 'INVALID_REQUEST') from None
        require(request_id == body['requestId'])
        fingerprint = digest({'actor': actor, 'body': body})
        with self.library.connect() as db:
            db.execute('begin immediate')
            guard()
            previous = db.execute('select * from work_order_requests where request_id=?', (request_id,)).fetchone()
            if previous:
                require(previous['payload_sha256'] == fingerprint, 'REQUEST_REUSE_CONFLICT', 409)
                guard()
                return json.loads(previous['response'])
            result = operation(db)
            db.execute('insert into work_order_requests values(?,?,?)', (request_id, fingerprint, encoded(result)))
            guard()  # The connect context rolls back when authorization changes.
            return result

    def apply_assistant(self, body, actor, guard, proposed, analysis):
        from .assistant_work_orders import selected_items, merge_plan
        require(set(body) == {'requestId', 'orderId', 'expectedOrderRevision', 'runId', 'expectedProposalSha256', 'items'})
        identifier = text(body['orderId'], 100)
        require(type(body['expectedOrderRevision']) is int and 0 < body['expectedOrderRevision'] < 100)
        require(body['runId'] == proposed['runId'] and body['expectedProposalSha256'] == proposed['proposalSha256'],
                'ASSISTANT_PROPOSAL_CHANGED', 409)
        def operation(db):
            value = self._detail(db, identifier)
            require(value['orderRevision'] == body['expectedOrderRevision'], 'WORK_ORDER_CHANGED', 409)
            require(value['state'] in ('diagnosing', 'investigating'), 'WORK_ORDER_STATE_CONFLICT', 409)
            rows = selected_items(body['items'], proposed, value['diagnosis'])
            plan = merge_plan(value, proposed, rows)
            self._retain(db, value, actor)
            revision = value['orderRevision'] + 1; stamp = datetime.now(timezone.utc).isoformat()
            keys = {key for item in rows for key in item['refs']}
            transfer = {key: proposed[key] for key in ('runId', 'runVersion', 'proposalSha256', 'conversationId', 'conversationVersion',
                        'analysisSessionId', 'analysisRevision')}
            transfer.update(orderRevision=revision, analysisSha256=analysis['contentSha256'], actor=actor,
                            recordedAt=stamp, items=rows, sources=[s for s in proposed['sources'] if s['key'] in keys],
                            engineeringConfirmation=False)
            db.execute('insert into work_order_assistant_transfers values(?,?,?,?)',
                       (identifier, revision, proposed['runId'], encoded(transfer)))
            db.execute('insert into work_order_analysis_links values(?,?,?,?,?)',
                       (identifier, revision, proposed['analysisSessionId'], proposed['analysisRevision'], analysis['contentSha256']))
            db.execute('insert into work_order_diagnostics values(?,?,?,?,?,?)',
                       (identifier, revision, encoded(plan), encoded(value['diagnosis']), actor, stamp))
            db.execute('update work_orders set revision=?,updated_at=? where order_id=?', (revision, stamp, identifier))
            db.execute('insert into work_order_events values(?,?,?,?,?,?,?,?)',
                       (identifier, revision, 'adopt_assistant', actor, stamp, value['state'], value['state'], '采纳助手排查建议（待核验）'))
            result = self._detail(db, identifier); self._retain(db, result, actor)
            return result
        return self._mutate(body, actor, guard, operation)

    def seed(self, body, targets, actor, guard):
        require(set(body) == {'requestId', 'expectedSnapshotRevision'})
        require(self.project_code == DEMO_PROJECT, 'DEMO_PROJECT_REQUIRED', 403)
        require(set(targets) == {'CN', 'CN1'} and all(type(item) is dict for item in targets.values()))
        def operation(db):
            batch = db.execute('select * from work_order_batches where batch_id=?', (BATCH,)).fetchone()
            if batch:
                require(batch['revision'] in ('pds-diagnostic-rules:1', RULE_REVISION) and json.loads(batch['targets']) == targets,
                        'WORK_ORDER_TARGET_CHANGED', 409)
                return {'batchId': BATCH, 'created': 0, 'total': 20, 'snapshotRevision': self._snapshot(db)}
            require(body['expectedSnapshotRevision'] == self._snapshot(db), 'WORK_ORDER_CHANGED', 409)
            now = datetime.now(timezone.utc)
            stamp = now.isoformat()
            db.execute('insert into work_order_batches values(?,?,?,?)', (BATCH, RULE_REVISION, encoded(targets), stamp))
            for scenario in scenarios():
                identifier = 'DEMO-PDS-WO-' + str(scenario['ordinal']).zfill(3)
                alarm_at = (now - timedelta(minutes=(21 - scenario['ordinal']) * 37)).isoformat()
                db.execute('insert into work_orders values(?,?,?,?,?,?,?,?,?,?,?,?)',
                    (identifier, BATCH, scenario['ordinal'], scenario['code'], scenario['title'], scenario['cabinet'],
                     'open', 1, alarm_at, stamp, '[]', ''))
                db.execute('insert into work_order_events values(?,?,?,?,?,?,?,?)',
                    (identifier, 1, 'seed_demo', actor, stamp, None, 'open', '模拟报警生成演示工单；无真实监测源'))
            return {'batchId': BATCH, 'created': 20, 'total': 20, 'snapshotRevision': self._snapshot(db)}
        return self._mutate(body, actor, guard, operation)

    def action(self, body, actor, guard):
        fields = {'requestId', 'orderId', 'expectedOrderRevision', 'action', 'checks', 'note'}
        require(set(body) == fields | ({'investigation'} if body.get('action') == 'save_diagnosis' else set()))
        identifier = text(body['orderId'], 100)
        action = body['action']
        require(isinstance(action, str) and action in (*TRANSITIONS, 'save', 'save_diagnosis'))
        revision = body['expectedOrderRevision']
        require(type(revision) is int and revision > 0)
        note = text(body['note'], empty=action not in ('submit', 'return', 'close', 'reopen'))
        checks = body['checks']
        require(type(checks) is list and len(checks) <= 4 and all(isinstance(item, str) for item in checks)
                and len(set(checks)) == len(checks) and set(checks) <= {'alarm-context', 'circuit', 'photo-location', 'review'})
        def operation(db):
            value = self._detail(db, identifier)
            require(value['orderRevision'] == revision, 'WORK_ORDER_CHANGED', 409)
            self._retain(db, value, actor)
            require(revision < 100, 'WORK_ORDER_EVENT_LIMIT', 413)
            previous = value['state']
            state = previous
            if action == 'save_diagnosis':
                require(previous in ('diagnosing', 'investigating'), 'WORK_ORDER_STATE_CONFLICT', 409)
            elif action == 'save':
                require(previous in ('diagnosing', 'investigating', 'review'), 'WORK_ORDER_STATE_CONFLICT', 409)
            else:
                source, state = TRANSITIONS[action]
                require(previous == source, 'WORK_ORDER_STATE_CONFLICT', 409)
            if action in ('submit', 'close'):
                require(len(checks) == 4, 'WORK_ORDER_CHECKS_REQUIRED', 422)
                require(value['investigationComplete'], 'WORK_ORDER_DIAGNOSIS_REQUIRED', 422)
            saved_checks = [] if action in ('return', 'reopen') else checks
            stamp = datetime.now(timezone.utc).isoformat()
            db.execute('update work_orders set state=?,revision=?,updated_at=?,checks=?,note=? where order_id=? and revision=?',
                       (state, revision + 1, stamp, encoded(saved_checks), note, identifier, revision))
            db.execute('insert into work_order_events values(?,?,?,?,?,?,?,?)',
                       (identifier, revision + 1, action, actor, stamp, previous, state, note))
            if action in ('save_diagnosis', 'return', 'reopen') or value['investigationRevision'] is None:
                plan = validate_plan(body['investigation'], value['diagnosis']) if action == 'save_diagnosis' else value['investigation']
                if action in ('return', 'reopen'):
                    plan = reset_results(plan)
                db.execute('insert into work_order_diagnostics values(?,?,?,?,?,?)',
                           (identifier, revision + 1, encoded(plan), encoded(value['diagnosis']), actor, stamp))
            value = self._detail(db, identifier)
            self._retain(db, value, actor)
            return value
        return self._mutate(body, actor, guard, operation)
