"""Reuse explicitly shared or owned analysis revisions without copying private runs."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from uuid import UUID, uuid5

from . import analysis_drafts as drafts
from . import work_order_workflow as workflow
from .analysis_evidence import AnalysisEvidence, sha, validate_descriptor
from .analysis_source_reader import AnalysisSourceReader
from .authority import PreviewError
from .work_orders import require, text

FIXED = ('analysisSessionId', 'analysisRevision', 'analysisSha256')


def selector(body):
    value = {k: body[k] for k in FIXED}
    drafts.identifier(value['analysisSessionId'])
    require(type(value['analysisRevision']) is int and 1 <= value['analysisRevision'] <= 1000)
    sha(value['analysisSha256'])
    return value


def share_row(orders, fixed, owner):
    with orders.library.connect() as db:
        return db.execute('''select shared_at from work_order_analysis_shares where
            analysis_session_id=? and analysis_revision=? and analysis_sha256=? and owner_id=?''',
            (*(fixed[k] for k in FIXED), owner)).fetchone()


def reference(store, cursor, orders, actor, fixed, *, owner_only=False, active=False):
    session = fixed['analysisSessionId']
    cursor.execute(f'''select owner_id::text,head_revision from {drafts.SCHEMA}.analysis_sessions
        where connection_id=%s and project_code=%s and session_id=%s''',
        (store.connection_id, store.project_code, session))
    row = cursor.fetchone()
    require(row, 'NOT_FOUND_OR_FORBIDDEN', 404)
    owner, head = row
    shared = share_row(orders, fixed, owner)
    require(owner == actor or not owner_only and shared, 'NOT_FOUND_OR_FORBIDDEN', 404)
    lifecycle = store.lifecycle(cursor, session)['lifecycle']
    if active or owner != actor:
        require(lifecycle == 'active', 'ANALYSIS_TRASHED', 409)
    snapshot, revision = store._revision(cursor, session, fixed['analysisRevision'])
    require(revision[1] == fixed['analysisSha256'], 'ANALYSIS_CHANGED', 409)
    return {**fixed, 'snapshot': snapshot, 'headRevision': head, 'owned': owner == actor,
            'ownerId': owner, 'shared': bool(shared), 'updatedAt': revision[4]}


def sources(store, cursor, reference):
    cards = [card for card in reference['snapshot']['cards'] if 'source' in card]
    if not cards:
        return {}
    cursor.execute(f'''select evidence_ref_id::text,source_kind,descriptor_json,descriptor_sha256
        from {drafts.SCHEMA}.analysis_evidence_refs where session_id=%s and evidence_ref_id=any(%s::uuid[])''',
        (reference['analysisSessionId'], [card['source']['id'] for card in cards]))
    values = {eid: (kind, json.loads(raw), digest) for eid, kind, raw, digest in cursor.fetchall()}
    for card in cards:
        item = values.get(card['source']['id'])
        require(item and card['source']['revision'] == item[2]
                and drafts.digest(item[1]) == item[2], 'ANALYSIS_SOURCE_NOT_REGISTERED', 409)
        validate_descriptor(item[0], item[1])
    return values


def check_sources(reader, values):
    for kind, descriptor, _ in values.values():
        value = reader.read(kind, descriptor)
        if kind == 'work_order':
            from .work_order_attachments import fixed_metadata
            for attachment in value.get('workflow', {}).get('attachments', []):
                fixed = fixed_metadata(reader.reader, attachment)
                require(fixed['sourceSha256'] == attachment['sourceSha256'], 'SOURCE_CHANGED', 409)


def scope_for(order):
    data = order.get('workflow', {})
    system = data.get('faultSystem', '')
    if not order.get('workflowVersion'):
        from .simulated_faults import SOURCE_ID
        system = SOURCE_ID
    scope = {'simulated': order['sourceKind'] == 'simulated'}
    for key, value in (('faultCode', order['faultCode']), ('faultSystem', system), ('equipment', data.get('equipment'))):
        if value:
            scope[key] = value
    return scope


def applicability(snapshot):
    context = snapshot['context']
    return {k: v for k, v in {
        'faultCode': context.get('faultCode'), 'faultSystem': context.get('sourceConnectionId'),
        'simulated': bool(context.get('datasetId')),
        **snapshot.get('reuse', {}),
    }.items() if v is not None}


def listing(store, orders, reader, actor, order, body):
    require(set(body) <= {'orderId', 'q', 'all', 'cursor'})
    q = text(body.get('q', ''), 120, empty=True)
    browse = body.get('all', False)
    offset = body.get('cursor', 0)
    require(type(browse) is bool and type(offset) is int and 0 <= offset <= 10000)
    scope = scope_for(order)
    fault = '' if browse else scope.get('faultCode', '')
    system = '' if browse else scope.get('faultSystem', '')
    if not browse and not fault:
        return {'items': [], 'nextCursor': None}
    with orders.library.connect() as db:
        shares = [
            {'id': row[0], 'rev': row[1], 'sha': row[2], 'owner': row[3]}
            for row in db.execute('select analysis_session_id,analysis_revision,analysis_sha256,owner_id from work_order_analysis_shares')
        ]
    from .analysis_lifecycle import active_condition
    with store.connection.transaction(readonly=True) as cursor:
        cursor.execute(f'''with accessible as (
            select s.session_id,s.head_revision as revision,true as owned,null::text as shared_sha
                from {drafts.SCHEMA}.analysis_sessions s where s.owner_id=%s and s.connection_id=%s and s.project_code=%s
                and {active_condition(store)}
            union all
            select s.session_id,p.rev,false,p.sha from jsonb_to_recordset(%s::jsonb)
                as p(id uuid,rev int,sha text,owner uuid)
                join {drafts.SCHEMA}.analysis_sessions s on s.session_id=p.id and s.owner_id=p.owner
                where s.owner_id<>%s and s.connection_id=%s and s.project_code=%s and {active_condition(store)}
        ), revisions as (
            select a.session_id,a.revision,a.owned,r.content_sha256,r.created_at,r.snapshot_json::jsonb as value
            from accessible a join {drafts.SCHEMA}.analysis_revisions r
                on r.session_id=a.session_id and r.revision=a.revision
            where a.owned or r.content_sha256=a.shared_sha
        ), matches as (
            select *, coalesce(value#>>'{{reuse,faultSystem}}',value#>>'{{context,sourceConnectionId}}','') as system
            from revisions where position(lower(%s) in lower(value->>'title'))>0 or %s=''
        ), ranked as (
            select *,row_number() over(partition by session_id order by revision desc) as choice from matches
            where (%s='' or coalesce(value#>>'{{reuse,faultCode}}',value#>>'{{context,faultCode}}')=%s)
                and (%s='' or system in ('',%s))
        )
        select session_id::text,revision,content_sha256,created_at from ranked where choice=1
        order by (system<>'' and system=%s) desc,created_at desc,session_id limit 9 offset %s''',
            (actor, store.connection_id, store.project_code, json.dumps(shares),
             actor, store.connection_id, store.project_code, q, q, fault, fault, system, system, system, offset))
        page = cursor.fetchall()
        refs = []
        for row in page[:8]:
            fixed = dict(zip(FIXED, row[:3]))
            item = reference(store, cursor, orders, actor, fixed, active=True)
            refs.append((item, sources(store, cursor, item) if not item['owned'] else {}))
    items = []
    for item, fixed_sources in refs:
        try:
            check_sources(reader, fixed_sources)
            if not item['owned']:
                require(share_row(orders, item, item['ownerId']), 'NOT_FOUND_OR_FORBIDDEN', 404)
        except PreviewError as error:
            if error.status in (401, 502, 503, 504):
                raise
            continue
        data = applicability(item['snapshot'])
        equipment = scope.get('equipment', '').casefold()
        related_equipment = data.get('equipment', '').casefold()
        items.append({
            **{k: item[k] for k in (*FIXED, 'owned', 'shared', 'updatedAt', 'headRevision')},
            'title': item['snapshot']['title'], 'applicability': data,
            'sameCode': bool(scope.get('faultCode') and data.get('faultCode') == scope['faultCode']),
            'sameSystem': bool(scope.get('faultSystem') and data.get('faultSystem') == scope['faultSystem']),
            'sameEquipment': bool(equipment and equipment == related_equipment),
            'equipmentMismatch': bool(equipment and related_equipment and equipment != related_equipment),
            'simulationMismatch': bool(data.get('simulated')) != scope['simulated'],
        })
    return {'items': items, 'nextCursor': offset + 8 if len(page) > 8 else None}


def start_draft(store, orders, reader, actor, role, body, authorize):
    fields = {'orderId', 'expectedOrderRevision', 'requestId', 'title'}
    require(fields <= set(body) <= fields | {'base'})
    namespace = UUID(drafts.identifier(body['requestId']))
    title = text(body['title'], 120)
    order = orders.detail({'orderId': body['orderId']})
    workflow.require_processing(order, actor, role, body['expectedOrderRevision'])
    order_id = order['orderId']
    base = body.get('base')
    origin = None
    registered = {}
    if base is not None:
        require(type(base) is dict and set(base) == set(FIXED))
        with store.connection.transaction(readonly=True) as cursor:
            origin = reference(store, cursor, orders, actor, selector(base), active=True)
            registered = sources(store, cursor, origin)
        check_sources(reader, registered)

    def guard():
        authorize()
        value = orders.detail({'orderId': order_id})
        workflow.require_processing(value, actor, role, body['expectedOrderRevision'])
        if origin and not origin['owned']:
            require(share_row(orders, origin, origin['ownerId']), 'NOT_FOUND_OR_FORBIDDEN', 404)

    def request_id(suffix):
        return str(uuid5(namespace, suffix))

    source = order.get('workflow', {}).get('source')
    start = datetime.fromisoformat(order['alarmAt'].replace('Z', '+00:00'))
    context = {
        'objectIds': [], 'timeFrom': start.isoformat(timespec='seconds').replace('+00:00', 'Z'),
        'timeTo': (start + timedelta(minutes=3)).isoformat(timespec='seconds').replace('+00:00', 'Z'),
        'timezone': 'Asia/Shanghai',
    }
    if source:
        context.update(timeFrom=source['timeFrom'], timeTo=source['timeTo'])
    derived = None
    if origin:
        derived = {'analysisSessionId': origin['analysisSessionId'], 'analysisRevision': origin['analysisRevision'],
                   'contentSha256': origin['analysisSha256']}
    snapshot = {
        'schemaVersion': 2, 'ontobaseConnectionId': store.connection_id, 'projectCode': store.project_code,
        'title': title, 'status': 'analyzing', 'context': context, 'cards': [], 'relations': [],
        'viewport': {'x': 0, 'y': 0, 'zoom': 1}, 'workflowOrderId': order_id,
        'reuse': {**{k: v for k, v in (origin or {}).get('snapshot', {}).get('reuse', {}).items() if k in ('summary', 'advice')},
                  **scope_for(order)},
        **({'derivedFrom': derived} if derived else {}),
    }
    # Check all source selectors before committing a new analysis identity.
    order_descriptor = orders.capture(
        {'orderId': order_id, 'expectedOrderRevision': order['orderRevision']}, actor, guard)
    primary = None
    if source:
        identity = source['identity']
        alarm = reader.resolve('alarm', identity)
        if source.get('targetRds'):
            from .analysis_source_reader import selected
            try:
                primary = selected(reader._rds(source['targetRds']))
            except PreviewError as error:
                if error.status in (401, 403):
                    raise
    else:
        alarm = None
    if origin:
        require(len(origin['snapshot']['cards']) + 1 + bool(alarm) + bool(primary) <= 50,
                'WORK_ORDER_COPY_CARD_LIMIT', 409)
    prepared_attachments = []
    for item in order.get('workflow', {}).get('attachments', []):
        if not item['previewAvailable']:
            continue
        kind = 'photo' if item['previewKind'] == 'image' else 'document'
        fields = {'documentId': item['documentId'], 'contentVersionId': item['contentVersionId']}
        if kind == 'photo':
            fields['sourceType'] = 'project_document'
        else:
            fields['pageNumber'] = 1
        descriptor = reader.resolve(kind, fields)
        prepared_attachments.append((item, kind, descriptor))
    created = store.write(actor, 'admin', 'create', {'requestId': request_id('create'), 'snapshot': snapshot}, guard,
                          work_order_origin=order_id, derived_from=derived)
    session = created['analysisSessionId']
    evidence = AnalysisEvidence(store)

    def register(name, kind, descriptor):
        result = evidence.register(actor, {'analysisSessionId': session, 'expectedAnalysisRevision': 1,
            'requestId': request_id(name), 'sourceKind': kind, 'selector': descriptor},
            guard, lambda _kind, fixed: fixed)
        return {'id': result['evidenceRefId'], 'revision': result['sourceRevision'],
                'system': 'ontobase' if kind in ('object', 'drawing', 'document', 'photo') else 'ontovis',
                'ontobaseConnectionId': store.connection_id, 'projectCode': store.project_code}

    draft = deepcopy(snapshot)
    if origin:
        original = origin['snapshot']
        draft['cards'] = deepcopy(original['cards'])
        draft['relations'] = deepcopy(original['relations'])
        draft['viewport'] = deepcopy(original['viewport'])
        if 'frames' in original:
            draft['frames'] = deepcopy(original['frames'])
        for card in draft['cards']:
            if 'source' in card:
                key = card['source']['id']
                kind, descriptor, _ = registered[key]
                card['source'] = register('copy-' + key, kind, descriptor)
                card['historical'] = True
            else:
                card.pop('historical', None)
    order_ref = register('order', 'work_order', order_descriptor)
    draft['context']['workOrderId'] = order_id
    gaps = []

    def card(kind, name, fixed, title):
        if len(draft['cards']) >= 50:
            gaps.append(name)
            return
        occupied = {(row['x'], row['y']) for row in draft['cards']}
        x, y = 72, 84
        while (x, y) in occupied:
            y += 320
        draft['cards'].append({'id': request_id('card-' + name), 'kind': kind,
            'title': title[:120], 'x': x, 'y': y, 'width': 310, 'height': 280, 'pinned': False, 'source': fixed})

    card('work_order', 'order', order_ref, order['title'])
    if alarm:
        alarm_ref = register('alarm', 'alarm', alarm)
        draft['context'].update(**source['identity'], faultCode=source['faultCode'],
                                sourceConnectionId=source['faultSystem'], branch=source['branch'])
        card('alarm', 'alarm', alarm_ref, source['title'])
    if primary:
        object_ref = register('object', 'object', primary)
        draft['context']['objectIds'] = [primary['entityUid']]
        card('object', 'object', object_ref, source['targetRds'])
    for item, kind, descriptor in prepared_attachments:
        if len(draft['cards']) >= 50:
            gaps.append(item['attachmentId'])
            continue
        fixed = register(item['attachmentId'], kind, descriptor)
        card(kind, item['attachmentId'], fixed, item['title'])
    saved = store.write(actor, 'admin', 'save', {'requestId': request_id('save'),
        'analysisSessionId': session, 'expectedAnalysisRevision': 1, 'snapshot': draft}, guard)
    return {**saved, 'snapshot': draft, 'omittedCards': len(gaps)}


def request(sessions, engineering, orders, library, action, body, actor_id, actor, role, authorize):
    require(sessions.analysis_store_id is not None, 'ANALYSIS_NOT_ENABLED', 503)
    require(sessions.analysis_slots.acquire(timeout=5), 'ANALYSIS_BUSY', 503)
    store = None
    try:
        store = drafts.AnalysisDrafts(sessions.analysis_database_url, sessions.connection_id, orders.project_code)
        require(store.store_id == sessions.analysis_store_id, 'ANALYSIS_STORE_SCOPE_MISMATCH', 409)
        reader = AnalysisSourceReader(engineering, sessions.shared.project_models, orders, authorize, actor_id,
                                      scene_library=library)
        if action == 'analyses':
            require('orderId' in body)
            return listing(store, orders, reader, actor_id, orders.detail({'orderId': body['orderId']}), body)
        if action == 'analysis-draft':
            return start_draft(store, orders, reader, actor_id, role, body, authorize)
        require(set(FIXED) <= set(body))
        fixed = selector(body)
        with store.connection.transaction(readonly=action in ('analysis-reference', 'analysis-source')) as cursor:
            if action in ('analysis-share', 'workflow'):
                cursor.execute('select pg_advisory_xact_lock(%s)', (drafts.WRITE_LOCK,))
            item = reference(store, cursor, orders, actor_id, fixed, owner_only=action == 'analysis-share',
                             active=action == 'workflow' or body.get('share') is True)
            if action == 'analysis-share':
                require(set(body) == {*FIXED, 'requestId', 'share'} and type(body['share']) is bool)
                require(role == 'admin' or role == 'reviewer' and item['snapshot'].get('workflowOrderId'),
                        'ANALYSIS_WRITE_FORBIDDEN', 403)
                if role == 'reviewer':
                    order = orders.detail({'orderId': item['snapshot']['workflowOrderId']})
                    workflow.require_processing(order, actor_id, role)
                if body['share']:
                    check_sources(reader, sources(store, cursor, item))
                def share(db):
                    key = tuple(fixed[k] for k in FIXED[:2])
                    if body['share']:
                        db.execute('insert or ignore into work_order_analysis_shares values(?,?,?,?,?)',
                                   (*key, fixed['analysisSha256'], actor_id, datetime.now(timezone.utc).isoformat()))
                    else:
                        db.execute('delete from work_order_analysis_shares where analysis_session_id=? and analysis_revision=?', key)
                    return {**fixed, 'shared': body['share']}
                return orders._mutate(body, actor_id, authorize, share)
            values = sources(store, cursor, item)
            if action == 'workflow':
                check_sources(reader, values)
                return workflow.update(orders, body, actor_id, actor, role, authorize,
                    resolve=lambda _action, _body, _detail: fixed)
            if action == 'analysis-reference':
                require(set(body) == set(FIXED))
                if not item['owned']:
                    check_sources(reader, values)
                    require(share_row(orders, fixed, item['ownerId']), 'NOT_FOUND_OR_FORBIDDEN', 404)
                return {k: v for k, v in item.items() if k != 'ownerId'}
            require(action == 'analysis-source')
            require({*FIXED, 'evidenceRefId'} <= set(body) <= {*FIXED, 'evidenceRefId', 'pageNumber', 'content'})
            evidence_id = drafts.identifier(body['evidenceRefId'])
            value = values.get(evidence_id)
            require(value, 'NOT_FOUND_OR_FORBIDDEN', 404)
            kind, descriptor, revision = value
            if body.get('content'):
                require(body['content'] is True)
                if 'pageNumber' in body:
                    require(kind == 'document' and type(body['pageNumber']) is int)
                    descriptor = {**descriptor, 'pageNumber': body['pageNumber']}
                result = reader.content(kind, descriptor)
            else:
                result = {'evidenceRefId': evidence_id, 'sourceKind': kind, 'sourceRevision': revision,
                          'availability': 'available', 'source': reader.read(kind, descriptor)}
            if not item['owned']:
                require(share_row(orders, fixed, item['ownerId']), 'NOT_FOUND_OR_FORBIDDEN', 404)
            return result
    finally:
        if store is not None:
            store.close()
        sessions.analysis_slots.release()
