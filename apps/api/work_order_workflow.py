"""Project work orders with fixed, read-only treatment records for Canvas."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json

from .analysis_drafts import identifier
from .work_orders import WORKFLOW_STATES, digest, encoded, require, text

LEGACY_STATES = {
    'open': 'pending', 'diagnosing': 'processing', 'investigating': 'processing',
    'review': 'processing', 'closed': 'completed',
}
MANAGEMENT = {'accept', 'assign', 'archive', 'reopen', 'void'}
PROCESSING = {
    'record', 'correct_record', 'complete', 'attach', 'detach',
    'link_analysis', 'adopt_analysis', 'clear_analysis',
}
BATCH = 'work-order-workflow-v1'


def state_of(value):
    return LEGACY_STATES.get(value['state'], value['state'])


def handler_is(value, actor_id):
    return (value.get('handler') or {}).get('userId') == actor_id


def can_process(value, actor_id, role):
    return role in ('admin', 'reviewer') and state_of(value) == 'processing' and handler_is(value, actor_id)


def require_processing(value, actor_id, role, revision=None):
    if revision is not None:
        require(type(revision) is int and value['orderRevision'] == revision, 'WORK_ORDER_CHANGED', 409)
    require(state_of(value) == 'processing', 'WORK_ORDER_STATE_CONFLICT', 409)
    require(can_process(value, actor_id, role), 'WORK_ORDER_HANDLER_REQUIRED', 403)


def can_attach(value, actor_id, role):
    return can_process(value, actor_id, role) or (
        state_of(value) == 'pending' and role == 'admin'
        and value.get('workflow', {}).get('creatorId') == actor_id
    )


def new_workflow(actor, stamp, issue, *, fault_system='', equipment='', source=None, simulated=False):
    return {
        'issue': issue, 'createdBy': actor, 'createdAt': stamp, 'handler': None,
        'sourceKind': 'simulated' if simulated or source else 'manual',
        'source': source, 'faultSystem': fault_system, 'equipment': equipment,
        'records': [], 'attachments': [], 'cycle': 1,
        'adoptedAnalysis': None, 'result': None, 'completedAt': None, 'archivedAt': None,
    }


def legacy_workflow(value, actor, stamp):
    first = next(iter(value['events']), {})
    workflow = new_workflow(first.get('actor', actor), first.get('recordedAt', stamp), '', simulated=True)
    workflow['legacyState'] = value['state']
    if value['state'] == 'closed':
        result = value.get('note') or value['investigation'].get('conclusion')
        if result:
            workflow['result'] = {'text': result, 'recordId': None, 'cycle': 1}
        close = next((event for event in reversed(value['events']) if event['action'] == 'close'), None)
        workflow['completedAt'] = close['recordedAt'] if close else None
    return workflow


def create(orders, body, actor_id, actor, authorize, source=None):
    require({'requestId', 'title', 'issue'} <= set(body) <= {
        'requestId', 'title', 'issue', 'faultCode', 'faultSystem', 'equipment', 'simulated', 'alarm',
    })
    title = text(body['title'], 120)
    issue = text(body['issue'], 4000)
    fault = text(body.get('faultCode', ''), 100, empty=True)
    system = text(body.get('faultSystem', ''), 120, empty=True)
    equipment = text(body.get('equipment', ''), 200, empty=True)
    simulated = body.get('simulated', False)
    require(type(simulated) is bool and (not system or fault))
    if source:
        require(not fault or fault == source['faultCode'], 'WORK_ORDER_SOURCE_CHANGED', 409)
        fault, system = source['faultCode'], source['faultSystem']
        equipment = equipment or source.get('targetRds', '')
    source_event = digest(source['identity']) if source else None

    def operation(db):
        if source_event:
            previous = db.execute('select order_id from work_order_workflows where source_event=?',
                                  (source_event,)).fetchone()
            if previous:
                return {'orderId': previous[0], 'existing': True}
        stamp = datetime.now(timezone.utc).isoformat()
        db.execute('insert or ignore into work_order_batches values(?,?,?,?)', (BATCH, '1', '{}', stamp))
        number = db.execute('select coalesce(max(ordinal),0)+1 from work_orders where batch_id=?', (BATCH,)).fetchone()[0]
        order_id = f'WO-{number:05}'
        workflow = new_workflow(actor, stamp, issue, fault_system=system, equipment=equipment,
                                source=source, simulated=simulated)
        workflow['creatorId'] = actor_id
        db.execute('insert into work_orders values(?,?,?,?,?,?,?,?,?,?,?,?)', (
            order_id, BATCH, number, fault, title, '', 'pending', 1,
            source['eventAt'] if source else stamp, stamp, '[]', '',
        ))
        db.execute('insert into work_order_workflows values(?,?,?)', (order_id, source_event, encoded(workflow)))
        db.execute('insert into work_order_events values(?,?,?,?,?,?,?,?)',
                   (order_id, 1, 'create', actor, stamp, None, 'pending', ''))
        value = orders._detail(db, order_id)
        orders._retain(db, value, actor)
        return {'orderId': order_id, 'orderRevision': 1, 'existing': False}

    return orders._mutate(body, actor_id, authorize, operation)


def record_for(workflow, record_id):
    identifier(record_id)
    record = next((row for row in workflow['records'] if row['recordId'] == record_id), None)
    require(record is not None, 'WORK_ORDER_RECORD_NOT_FOUND', 404)
    return record


def write_record(workflow, body, action, actor, stamp, revision):
    from .analysis_drafts import utc
    value = text(body['text'], 4000)
    occurred_at = body.get('occurredAt')
    if occurred_at is not None:
        utc(occurred_at)
    if action == 'correct_record':
        record = record_for(workflow, body['recordId'])
        require(record['cycle'] == workflow['cycle'], 'WORK_ORDER_RECORD_FIXED', 409)
        record.update(text=value, occurredAt=body.get('occurredAt', record['occurredAt']), editedBy=actor,
                      editedAt=stamp, recordRevision=revision)
    else:
        adopted = workflow['adoptedAnalysis']
        workflow['records'].append({
            'recordId': body['requestId'], 'recordRevision': revision, 'text': value,
            'actor': actor, 'recordedAt': stamp, 'occurredAt': occurred_at, 'cycle': workflow['cycle'],
            'basis': {k: adopted[k] for k in ('analysisSessionId', 'analysisRevision', 'analysisSha256')} if adopted else None,
        })


def update(orders, body, actor_id, actor, role, authorize, *, resolve=None):
    fields = {'requestId', 'orderId', 'expectedOrderRevision', 'action'}
    action = body.get('action')
    required, optional = {
        'accept': (set(), set()),
        'assign': ({'handlerId'}, {'reason'}),
        'archive': (set(), set()),
        'reopen': ({'reason'}, set()),
        'void': ({'reason'}, set()),
        'record': ({'text'}, {'occurredAt'}),
        'correct_record': ({'recordId', 'text'}, {'occurredAt'}),
        'complete': (set(), {'result', 'recordId'}),
        'attach': ({'documentId', 'contentVersionId'}, {'recordId'}),
        'detach': ({'attachmentId'}, set()),
        'adopt_analysis': ({'analysisSessionId', 'analysisRevision', 'analysisSha256'}, {'reason'}),
        'link_analysis': ({'analysisSessionId', 'analysisRevision', 'analysisSha256'}, set()),
        'clear_analysis': (set(), {'reason'}),
    }.get(action if isinstance(action, str) else None, (None, None))
    require(required is not None and fields | required <= set(body) <= fields | required | optional)
    order_id = text(body['orderId'], 100)
    revision = body['expectedOrderRevision']
    require(type(revision) is int and revision > 0)
    require(role == 'admin' if action in MANAGEMENT else role in ('admin', 'reviewer'),
            'WORK_ORDER_WRITE_FORBIDDEN', 403)
    reason = text(body.get('reason', ''), 1000, empty=action not in ('reopen', 'void'))

    def operation(db):
        detail = orders._detail(db, order_id)
        require(detail['orderRevision'] == revision, 'WORK_ORDER_CHANGED', 409)
        previous = state = state_of(detail)
        require(previous in WORKFLOW_STATES, 'WORK_ORDER_STATE_CONFLICT', 409)
        require(revision < 100, 'WORK_ORDER_EVENT_LIMIT', 413)
        stamp = datetime.now(timezone.utc).isoformat()
        workflow = deepcopy(detail['workflow']) if 'workflow' in detail else legacy_workflow(detail, actor, stamp)
        note = reason
        link = None
        if action in ('attach', 'detach'):
            require(can_attach(detail, actor_id, role), 'WORK_ORDER_HANDLER_REQUIRED', 403)
        elif action in PROCESSING:
            require_processing(detail, actor_id, role)
        if action == 'accept':
            require(previous == 'pending' or previous == 'processing' and not workflow['handler'],
                    'WORK_ORDER_STATE_CONFLICT', 409)
            state = 'processing'
            workflow['handler'] = {'userId': actor_id, 'name': actor}
        elif action == 'assign':
            require(previous in ('pending', 'processing'), 'WORK_ORDER_STATE_CONFLICT', 409)
            target = resolve(action, identifier(body['handlerId']), detail)
            note = reason or target['name']
            if workflow['handler']:
                note = f"{workflow['handler']['name']} → {target['name']}" + (f" · {reason}" if reason else '')
            workflow['handler'] = target
            state = 'processing'
        elif action == 'archive':
            require(previous == 'completed', 'WORK_ORDER_STATE_CONFLICT', 409)
            state = 'archived'
            workflow['archivedAt'] = stamp
        elif action == 'reopen':
            require(previous in ('completed', 'archived'), 'WORK_ORDER_STATE_CONFLICT', 409)
            state = 'processing'
            workflow.update(cycle=workflow['cycle'] + 1, result=None, completedAt=None, archivedAt=None,
                            handler={'userId': actor_id, 'name': actor})
        elif action == 'void':
            require(previous in ('pending', 'processing'), 'WORK_ORDER_STATE_CONFLICT', 409)
            state = 'archived'
            workflow['archivedAt'] = stamp
            workflow['result'] = {'text': reason, 'recordId': None, 'cycle': workflow['cycle'], 'voided': True}
        elif action in ('record', 'correct_record'):
            write_record(workflow, body, action, actor, stamp, revision + 1)
        elif action == 'complete':
            require(('result' in body) != ('recordId' in body))
            record_id = body.get('recordId')
            if record_id:
                record = record_for(workflow, record_id)
                require(record['cycle'] == workflow['cycle'], 'WORK_ORDER_RECORD_FIXED', 409)
                result = record['text']
            else:
                result = text(body.get('result'), 4000)
            workflow['result'] = {'text': result, 'recordId': record_id, 'cycle': workflow['cycle']}
            workflow['completedAt'] = stamp
            state = 'completed'
        elif action == 'attach':
            record_id = body.get('recordId')
            if record_id is not None:
                record_for(workflow, record_id)
            fixed = resolve(action, body, detail)
            if any(all(item.get(k) == fixed[k] for k in ('documentId', 'contentVersionId'))
                   and item['recordId'] == record_id for item in workflow['attachments']):
                return detail
            workflow['attachments'].append({
                **fixed, 'attachmentId': body['requestId'], 'recordId': record_id,
                'actor': actor, 'recordedAt': stamp,
            })
        elif action == 'detach':
            attachment_id = identifier(body['attachmentId'])
            remaining = [item for item in workflow['attachments'] if item['attachmentId'] != attachment_id]
            require(len(remaining) != len(workflow['attachments']), 'WORK_ORDER_ATTACHMENT_NOT_FOUND', 404)
            workflow['attachments'] = remaining
        elif action in ('link_analysis', 'adopt_analysis'):
            link = resolve(action, body, detail)
            same = lambda row: row and all(row[k] == link[k] for k in ('analysisSessionId', 'analysisRevision', 'analysisSha256'))
            if action == 'link_analysis' and any(same(row) for row in detail['analysisLinks']):
                return detail
            if action == 'adopt_analysis':
                if same(workflow['adoptedAnalysis']):
                    return detail
                workflow['adoptedAnalysis'] = {
                    **link, 'orderRevision': revision + 1, 'actor': actor, 'actorId': actor_id,
                    'recordedAt': stamp, 'reason': reason,
                }
        elif action == 'clear_analysis':
            if not workflow['adoptedAnalysis']:
                return detail
            workflow['adoptedAnalysis'] = None
        orders._retain(db, detail, actor)
        db.execute('''insert into work_order_workflows(order_id,data) values(?,?)
            on conflict(order_id) do update set data=excluded.data''', (order_id, encoded(workflow)))
        db.execute('update work_orders set state=?,revision=?,updated_at=? where order_id=? and revision=?',
                   (state, revision + 1, stamp, order_id, revision))
        db.execute('insert into work_order_events values(?,?,?,?,?,?,?,?)', (
            order_id, revision + 1, 'workflow_link_analysis' if action == 'link_analysis' else action,
            actor, stamp, detail['state'], state, note,
        ))
        if link:
            db.execute('insert into work_order_analysis_links values(?,?,?,?,?)', (
                order_id, revision + 1, link['analysisSessionId'], link['analysisRevision'], link['analysisSha256'],
            ))
        saved = orders._detail(db, order_id)
        orders._retain(db, saved, actor)
        return saved

    def replay_guard(db):
        if action in PROCESSING:
            detail = orders._detail(db, order_id)
            require(handler_is(detail, actor_id) or (
                action in ('attach', 'detach') and can_attach(detail, actor_id, role)
            ), 'WORK_ORDER_HANDLER_REQUIRED', 403)

    return orders._mutate(body, actor_id, authorize, operation, replay_guard=replay_guard)


def record_history(orders, body):
    require(set(body) == {'orderId', 'recordId'})
    order_id = text(body['orderId'], 100)
    record_id = identifier(body['recordId'])
    with orders.library.connect() as db:
        rows = db.execute('''select snapshot_json,content_sha256 from work_order_snapshots
            where order_id=? order by order_revision desc''', (order_id,)).fetchall()
    versions = {}
    for raw, sha in rows:
        value = json.loads(raw)
        require(digest(value) == sha, 'WORK_ORDER_STORAGE_INVALID', 409)
        for item in value.get('workflow', {}).get('records', []):
            if item['recordId'] == record_id:
                versions.setdefault(item['recordRevision'], item)
    require(versions, 'WORK_ORDER_RECORD_NOT_FOUND', 404)
    return {'items': list(versions.values())}
