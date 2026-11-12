"""Session-scoped work order workflow, with existing project/source authority."""
from . import work_order_attachments as attachments
from . import work_order_workflow as workflow
from .analysis_drafts import identifier
from .authority import PreviewError
from .scene_engineering import SceneEngineeringReader
from .work_orders import WorkOrders, digest, require, text

WORKFLOW_PATHS = (
    'create', 'workflow-detail', 'workflow', 'members', 'record-history',
    'attachments/catalogue', 'attachments/start', 'attachments/part',
    'attachments/complete', 'attachments/content',
    'analyses', 'analysis-reference', 'analysis-draft', 'analysis-share', 'analysis-source',
)
WORKFLOW_WRITES = {'create', 'workflow', 'attachments/start', 'attachments/part',
                   'attachments/complete', 'analysis-draft', 'analysis-share'}


def order_store(sessions, workspace):
    service = sessions._workspace(workspace)
    if not hasattr(service, 'work_orders'):
        with sessions.registry.lock:
            if not hasattr(service, 'work_orders'):
                service.work_orders = WorkOrders(service.library, workspace['project_code'])
    return service.work_orders, service.library


def members(reader):
    response = reader._request('GET', reader.prefix + '/members')
    return [
        {'userId': identifier(item['user_id']), 'name': text(item['username'], 200), 'role': item['role']}
        for item in response['items'] if item.get('is_active') is True and item.get('role') in ('admin', 'reviewer')
    ]


def alarm_source(project, alarm):
    from . import simulated_faults
    require(type(alarm) is dict and set(alarm) == {'datasetId', 'datasetRevision'})
    simulated_faults.catalogue(project)
    events = simulated_faults.alarms(alarm['datasetId'], alarm['datasetRevision'])
    dataset, event = events['dataset'], events['items'][0]
    return {
        'identity': {'datasetId': dataset['datasetId'], 'datasetRevision': dataset['datasetRevision'],
                     'eventId': event['sourceEventId']},
        'eventAt': event['occurredAt'], 'faultCode': dataset['faultCode'],
        'faultSystem': dataset['sourceConnectionId'], 'timeFrom': dataset['timeFrom'],
        'timeTo': dataset['timeTo'], 'branch': dataset['branch'], 'title': dataset['title'],
        'targetRds': dataset['primaryRds'],
    }


def request(sessions, sid, row, project, access, action, body, *, stream=None, length=None):
    actor_id = identifier(row.subject_id)
    actor = row.authority.username
    role = access.get('role')
    manager = role == 'admin'

    def authorize():
        sessions.guard(sid, row)
        current = sessions._access(sid, row, project)
        require(current['accessRevision'] == access['accessRevision'] and current.get('role') == role,
                'ACCESS_CHANGED', 409)

    reader = SceneEngineeringReader(row.authority, sessions.connection_id, project, lambda: sessions.guard(sid, row))
    if action == 'members':
        require(not body)
        require(manager, 'WORK_ORDER_WRITE_FORBIDDEN', 403)
        return {'items': members(reader)}
    if action == 'attachments/catalogue':
        return attachments.catalogue(reader, body)
    workspace = sessions.registry.lookup(project)
    if action == 'create':
        require(manager, 'WORK_ORDER_WRITE_FORBIDDEN', 403)
        source = alarm_source(project, body['alarm']) if 'alarm' in body else None
        authorize()
        if workspace is None:
            workspace = sessions.registry.prepare(project)
        orders, _ = order_store(sessions, workspace)
        return workflow.create(orders, body, actor_id, actor, authorize, source)
    require(workspace is not None, 'NOT_FOUND_OR_FORBIDDEN', 404)
    orders, library = order_store(sessions, workspace)
    if action == 'workflow-detail':
        value = orders.detail(body)
        return {**value, 'snapshotSha256': digest(value), 'actorId': actor_id,
                'canManage': manager, 'canProcess': workflow.can_process(value, actor_id, role),
                'canAttach': workflow.can_attach(value, actor_id, role)}
    if action == 'record-history':
        return workflow.record_history(orders, body)
    if action == 'attachments/content':
        required = {'orderId', 'orderRevision', 'snapshotSha256', 'attachmentId'}
        require(required <= set(body) <= required | {'pageNumber'})
        attachment_id = identifier(body['attachmentId'])
        fixed = orders.fixed_snapshot({k: body[k] for k in ('orderId', 'orderRevision', 'snapshotSha256')})
        attachment = next((item for item in fixed.get('workflow', {}).get('attachments', [])
                           if item['attachmentId'] == attachment_id), None)
        require(attachment, 'WORK_ORDER_ATTACHMENT_NOT_FOUND', 404)
        return attachments.content(reader, attachment, page=body.get('pageNumber'))
    if action.startswith('attachments/'):
        require({'orderId', 'expectedOrderRevision', 'uploadId'} <= set(body))
        def check_order():
            value = orders.detail({'orderId': body['orderId']})
            require(type(body['expectedOrderRevision']) is int and value['orderRevision'] == body['expectedOrderRevision'],
                    'WORK_ORDER_CHANGED', 409)
            require(workflow.can_attach(value, actor_id, role), 'WORK_ORDER_HANDLER_REQUIRED', 403)
        check_order()
        authorize()
        upload = {key: value for key, value in body.items() if key not in ('orderId', 'expectedOrderRevision')}
        result = attachments.upload(reader, action.split('/')[1], upload, stream=stream, length=length)
        check_order()
        return result
    if action == 'workflow' and body.get('action') not in ('link_analysis', 'adopt_analysis'):
        def resolve(operation, target, _detail):
            if operation == 'assign':
                if target == actor_id:
                    return {'userId': actor_id, 'name': actor}
                selected = next((item for item in members(reader) if item['userId'] == target), None)
                require(selected, 'WORK_ORDER_HANDLER_UNAVAILABLE', 409)
                return {k: selected[k] for k in ('userId', 'name')}
            return attachments.fixed_metadata(reader, target)
        return workflow.update(orders, body, actor_id, actor, role, authorize, resolve=resolve)
    from .work_order_analyses import request as analysis_request
    return analysis_request(sessions, reader, orders, library, action, body, actor_id, actor, role, authorize)
