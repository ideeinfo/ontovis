"""Object candidates verified against the fixed sources on an analysis canvas."""

from urllib.parse import quote

from . import simulated_faults as sim
from .analysis_evidence import SELECTION
from .analysis_preview import document_preview, drawing_bytes
from .analysis_recommendations import recommendation
from .authority import PreviewError
from .demo_faults import diagnosis


def object_recommendation(item, reason, reason_en, *, identifier=None, relevance='object_association'):
    tag = next((entry['value'] for entry in item.get('identifiers', []) if entry['role'] == 'primary'), None)
    return recommendation('object', item.get('displayName') or identifier or tag or item['entityUid'],
        {'entityUid': item['entityUid'], 'expectedEntityRevision': item['entityRevision']},
        reason, reasonEn=reason_en, relevance=relevance, identifier=identifier or tag or item['entityUid'])


def alarm_object_recommendations(reader, dataset, *, read=None):
    fault = dataset['faultCode']
    primary = dataset['primaryRds']
    tags = [(primary, f'由 {fault} 的报警配置指定', f'Specified by the alarm configuration for {fault}'),
            ('=WEC+'+dataset['cabinet'], '本次报警涉及的柜体', 'Cabinet involved in this alarm')]
    channel = sim.PROFILES[fault].get('channel')
    for node in diagnosis(fault)['nodes']:
        if node['kind'] != 'component':
            continue
        if channel and node['rds'] == channel['rds']:
            address = channel['address']
            tags.append((channel['moduleRds'], f'检查该模块的 {address} 通道', f'Check channel {address} on this module'))
        else:
            tags.append((node['rds'], f"{node['label']} · {fault} 排查清单", f'Listed in the {fault} troubleshooting checklist'))
    rows, gaps = [], []
    seen_tags, seen_objects = set(), set()
    for tag, reason, reason_en in tags:
        if tag in seen_tags:
            continue
        seen_tags.add(tag)
        try:
            lookup = lambda: reader._rds(tag)
            item = (read(lookup) if read else lookup())['item']
        except PreviewError as error:
            if error.code == 'ASSISTANT_READ_LIMIT':
                gaps.append(error.code)
                break
            if error.status in (401, 403, 504) or error.status == 409 and error.code != 'DIAGNOSTIC_OBJECT_UNRESOLVED':
                raise
            gaps.append(error.code)
            continue
        if item['entityUid'] in seen_objects:
            continue
        seen_objects.add(item['entityUid'])
        basis = 'simulation_mapping' if tag == primary else 'simulation_rule'
        row = object_recommendation(item, reason, reason_en, identifier=tag, relevance=basis)
        row['matchType'] = basis
        rows.append(row)
    return rows, gaps


def _resolve_objects(reader, uids):
    identities = list(dict.fromkeys(filter(None, uids)))
    for start in range(0, len(identities), 50):
        batch = identities[start:start+50]
        items = reader.reader._resolve(batch, missing_ok=True)
        yield from (items[uid] for uid in batch if uid in items)


def _card_objects(reader, kind, descriptor, alarms, read):
    if (kind == 'document' and not descriptor.get('knowledgeNodeId')
            or kind == 'photo' and 'entityUid' not in descriptor):
        return [], []
    if kind == 'drawing' and 'drawingUid' in descriptor:
        read(lambda: drawing_bytes(reader, descriptor))
        uid = descriptor['drawingUid']
        locations = reader.reader._request('GET', '/api/v1/drawings/' + quote(uid, safe='') + '/object-locations')['items']
        uids = (row.get('entity_uid') for row in locations if row.get('project_code') == reader.reader.project_code
                and row.get('drawing_uid') == uid and not row.get('deleted_at'))
        return [object_recommendation(item, '图纸上的登记对象', 'Object recorded on this drawing')
                for item in _resolve_objects(reader, uids)], []
    value = read(lambda: reader.read(kind, descriptor))
    if kind in ('alarm', 'trend', 'work_order'):
        if kind == 'work_order':
            source = (value.get('workflow') or {}).get('source')
            if not source or value['workflow']['sourceKind'] != 'simulated':
                return [], []
            fixed = source['identity']
            sim.catalogue(reader.reader.project_code)
            dataset = sim.dataset(fixed['datasetId'], fixed['datasetRevision'])
        else:
            dataset = value['dataset']
        key = (dataset['datasetId'], dataset['datasetRevision'])
        if key not in alarms:
            alarms[key] = alarm_object_recommendations(reader, dataset, read=read)
        return alarms[key]
    if kind == 'object':
        item = value['item']
        rows = [object_recommendation(item, '画布中的工程对象', 'Engineering object on the canvas', relevance='selected_object')]
        path = (value.get('ancestors') or {}).get('path', [])
        parents = [path[0]['object']] if path else _resolve_objects(reader, [item.get('definitionParentEntityUid')])
        rows.extend(object_recommendation(parent, '已登记的所属设备', 'Recorded parent equipment') for parent in parents)
        return rows, []
    if 'entityUid' in descriptor:
        item = value.get('item') or reader.read('object', {key: descriptor[key] for key in SELECTION})['item']
        return [object_recommendation(item, '此资料的登记对象', 'Object linked to this material')], []
    if kind == 'document':
        mappings = document_preview(reader, descriptor, {}).get('objectMappings', [])
        uids = (row['entityUid'] for row in mappings if row['nodeId'] == descriptor['knowledgeNodeId'])
        return [object_recommendation(item, '知识节点的已确认对象映射', 'Confirmed object mapping for the knowledge node')
                for item in _resolve_objects(reader, uids)], []
    if kind == 'model':
        from .analysis_model_links import frozen_configuration_bindings, scene_bindings
        version = descriptor['modelVersionId']
        bindings, truncated = scene_bindings(reader, reader.scene_library, model_versions=[version])
        bindings = [row for row in bindings if not row.get('configurationId') and row['sceneState'] == 'active']
        bindings += frozen_configuration_bindings(reader, reader.scene_library, version, descriptor.get('configurationRefs', []))
        components = {item['componentKey'] for item in value['components']}
        uids = ((row.get('equipmentEntityUid') or row['entityUid']) if row['wholeModel'] else row['entityUid']
                for row in bindings if set(row['componentKeys']) <= components)
        return [object_recommendation(item, '三维模型的登记绑定', 'Recorded binding for this model')
                for item in _resolve_objects(reader, uids)], ['MODEL_BINDINGS_TRUNCATED'] if truncated else []
    return [], []


def canvas_object_recommendations(reader, fixed, *, read=None):
    rows, alarms, gaps = {}, {}, []
    if read is None:
        def read(operation):
            return operation()
    for ref, descriptor in fixed:
        identity = ref['evidenceRefId']
        try:
            candidates, missing = _card_objects(reader, ref['sourceKind'], descriptor, alarms, read)
        except PreviewError as error:
            if error.status in (401, 403) or error.code in ('ASSISTANT_CANCELLED', 'ASSISTANT_POLICY_CHANGED',
                    'ACCESS_CHANGED', 'SESSION_CHANGED', 'ASSISTANT_TIMEOUT'):
                raise
            gaps.append(error.code)
            if error.code == 'ASSISTANT_READ_LIMIT':
                break
            continue
        gaps.extend(missing)
        for item in candidates:
            uid = item['selector']['entityUid']
            previous = rows.setdefault(uid, {**item, 'relatedSourceRefs': []})
            if identity not in previous['relatedSourceRefs']:
                previous['relatedSourceRefs'].append(identity)
        if 'ASSISTANT_READ_LIMIT' in missing:
            break
    return list(rows.values()), list(dict.fromkeys(gaps))
