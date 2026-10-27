"""Bounded source viewers and source-authored links for fixed Canvas citations."""
from __future__ import annotations

import hashlib
import json
from urllib.parse import quote, urlencode

from . import analysis_drafts as d
from .authority import PreviewError

OB = 'urn:ontobase:document-knowledge:1:'


def literal(node, key):
    rows = node.get('payload', {}).get('properties', {}).get(OB + key, [])
    return str(rows[0].get('value', '')) if rows else ''


def bbox(value):
    if type(value) is not dict or set(value) != {'x', 'y', 'width', 'height'}:
        return None
    if not all(type(v) in (int, float) and 0 <= v <= 1 for v in value.values()):
        return None
    if value['width'] <= 0 or value['height'] <= 0 or value['x'] + value['width'] > 1.000001 or value['y'] + value['height'] > 1.000001:
        return None
    return value


def image_selector(box, revision):
    return {'kind': 'image_bbox', 'renditionId': 'source-region', 'displayRevision': revision,
            'regionKind': 'device_region', 'coordinateSpace': 'oriented_display_normalized', 'bbox': box} if box else None


def drawing_identity(reader, descriptor):
    if 'drawingUid' in descriptor:
        uid = descriptor['drawingUid']
        location = None
    else:
        ref = descriptor['evidenceRef']
        if not ref.startswith('location:'):
            return None, None
        location = reader.reader._request('GET', '/api/v1/object-locations/' + quote(ref.split(':', 1)[1], safe=''))
        expected = descriptor['entityUid']
        if location.get('entity_uid') != expected:
            obj = reader.read('object', {key: descriptor[key] for key in ('entityUid', 'expectedEntityRevision', 'installationContextId', 'expectedHierarchyRevision')})
            expected = obj['item'].get('sourceTemplateEntityUid')
        d.require(location.get('project_code') == reader.reader.project_code and
                  location.get('entity_uid') == expected and not location.get('deleted_at'), 'SOURCE_CHANGED', 409)
        uid = location['drawing_uid']
    value = reader.reader._request('GET', '/api/v1/drawings/' + quote(uid, safe=''))
    d.require(value.get('project_code') == reader.reader.project_code, 'NOT_FOUND_OR_FORBIDDEN', 404)
    return value, location


def drawing_bytes(reader, descriptor):
    drawing, _ = drawing_identity(reader, descriptor)
    d.require(drawing is not None, 'ANALYSIS_SOURCE_UNAVAILABLE', 404)
    value = reader.reader.authority.source_bytes('/api/v1/drawings/' + quote(drawing['drawing_uid'], safe='') + '/pdf', ('application/pdf',))
    d.require(value['sha256'] == descriptor['expectedContentSha256'], 'SOURCE_CHANGED', 409)
    reader.authorize()
    return value


def object_geometry(row, revision):
    imported = row.get('entity_properties', {}).get('result_import', {})
    # Only source records tied to these exact PDF bytes may place an overlay.
    if imported.get('drawing_revision') != revision:
        return None
    return bbox(row.get('bbox'))


def drawing_classification(row):
    imported = (row.get('entity_properties') or {}).get('result_import') or {}
    standard = (imported.get('classification') or {}).get('standard') or {}
    if not isinstance(standard, dict) or not isinstance(standard.get('code'), str) or not standard['code'].strip():
        return None
    fields = {'code': 'code', 'revisionId': 'revision_id', 'tableRevision': 'table_revision',
              'nameZh': 'name_zh', 'nameEn': 'name_en', 'reviewState': 'review_state'}
    return {key: standard[source].strip() for key, source in fields.items() if isinstance(standard.get(source), str)}


def drawing_type_label(row):
    classification = drawing_classification(row)
    if classification:
        name = classification.get('nameZh') or classification.get('nameEn')
        return classification['code'] + (' · ' + name if name else '')
    return row.get('object_type') or 'unknown'


def drawing_preview(reader, descriptor, options):
    drawing, selected = drawing_identity(reader, descriptor)
    if drawing is None:
        return {'kind': 'drawing', 'objects': [], 'ports': [], 'references': [], 'connections': [],
                'gaps': ['此引用未提供图纸对象标识。']}
    revision = descriptor['expectedContentSha256']
    path = '/api/v1/drawings/' + quote(drawing['drawing_uid'], safe='')
    section = options.get('section', 'objects'); cursor = options.get('cursor', 0)
    d.require(section in ('objects', 'ports', 'connections', 'references'))
    result = {'kind': 'drawing', 'drawingUid': drawing['drawing_uid'], 'title': drawing.get('drawing_name'),
              'pageNumber': drawing.get('source_page_number'), 'drawingNumber': drawing.get('drawing_no'),
              'sourceRevision': revision, 'objects': [], 'ports': [], 'connections': [], 'references': [], 'gaps': [], 'nextCursor': None}
    if selected:
        result['focusId'] = selected['id']
        result['selector'] = image_selector(object_geometry(selected, revision), revision)
    if section == 'objects':
        rows = reader.reader._request('GET', path + '/object-locations')['items']
        for row in rows[cursor:cursor + 200]:
            box = object_geometry(row, revision)
            result['objects'].append({'id': row['id'], 'entityUid': row.get('entity_uid'),
                'title': row.get('display_name') or row.get('rds_designation') or row['id'],
                'identifier': row.get('rds_designation'), 'bbox': box, 'state': row.get('review_status'),
                'objectType': row.get('object_type'), 'classification': drawing_classification(row),
                'sourceInstanceId': row.get('text_span', {}).get('source_instance_id'),
                'properties': {'类型': drawing_type_label(row), '分类复核': (drawing_classification(row) or {}).get('reviewState'), '位号': row.get('rds_designation'),
                               '来源批次': row.get('source_run_id'), '审核状态': row.get('review_status')}})
        result['nextCursor'] = cursor + 200 if len(rows) > cursor + 200 else None
        result['total'] = len(rows)
    else:
        kind = 'drawing_references' if section == 'references' else section
        batches = reader.reader._request('GET', path + '/result-relation-imports?' + urlencode({'kind': kind, 'newest_first': 'true', 'limit': 1}))
        if not batches['items']:
            return result
        batch = batches['items'][0]
        records = reader.reader._request('GET', path + '/result-relation-imports/' + batch['id'] + '/records?' + urlencode({'kind': kind, 'limit': 200, 'after': cursor}))
        current = records.get('source_state') == 'current' and records.get('drawing_revision') == revision
        owners = {}
        if section == 'ports' and current:
            locations = reader.reader._request('GET', path + '/object-locations')['items']
            for loc in locations:
                imported = loc.get('entity_properties', {}).get('result_import', {})
                owner_id = loc.get('text_span', {}).get('source_instance_id') or imported.get('source_instance_id')
                if owner_id and imported.get('drawing_revision') == revision:
                    # An ambiguous source instance cannot identify a port owner.
                    owners[owner_id] = None if owner_id in owners else loc
        result['nextCursor'] = records.get('next_after')
        if not current:
            result['gaps'].append('此批关系对应另一图纸版本，保留文字，未叠加到当前图面。')
        for wrapper in records['items']:
            row = wrapper['document']; box = None
            if section == 'ports':
                position = row.get('display_position') or row.get('position', {})
                point = position.get('normalized')
                if current and position.get('state') == 'located' and point and all(type(point.get(k)) in (int, float) and 0 <= point[k] <= 1 for k in ('x', 'y')):
                    box = {'x': max(0, min(.99, point['x'] - .005)), 'y': max(0, min(.99, point['y'] - .005)), 'width': .01, 'height': .01}
                owner_id = row.get('source_instance_id')
                owner_row = owners.get(owner_id)
                if row.get('owner_resolution', {}).get('state') not in (None, 'resolved'):
                    owner_row = None
                owner = (owner_row.get('display_name') or owner_row.get('rds_designation')) if owner_row else owner_id
                item = {'id': row['source_port_id'], 'title': '端口 ' + row['label'] if row.get('label') else '未命名端口',
                        'owner': owner, 'ownerId': owner_id, 'objectType': owner_row.get('object_type') if owner_row else None,
                        'classification': drawing_classification(owner_row) if owner_row else None,
                        'bbox': box, 'state': row.get('review_state'),
                        'properties': {'所属对象': owner, '对象类型': drawing_type_label(owner_row) if owner_row else None,
                                       '分类复核': (drawing_classification(owner_row) or {}).get('reviewState') if owner_row else None,
                                       '端口类型': row.get('port_type_text'), '方向': row.get('direction_text')}}
            elif section == 'references':
                display = row.get('display_bbox', {})
                box = bbox(display.get('normalized_bbox') if display else row.get('normalized_bbox')) if current else None
                target = row.get('target') or {}
                item = {'id': row['source_reference_id'], 'title': row.get('target_label') or row['source_reference_id'],
                        'bbox': box, 'state': row.get('resolution', {}).get('state'), 'targetDrawingUid': target.get('drawing_uid'),
                        'targetTitle': target.get('drawing_name'), 'targetRevision': target.get('drawing_revision'),
                        'reason': target.get('basis'), 'semantics': row.get('relationship_semantics'),
                        'properties': {'目标图纸': target.get('drawing_name'), '印刷页号': target.get('printed_page'),
                                       '引用类型': row.get('relationship_semantics'), '依据': target.get('basis')}}
                if current and target.get('status') == 'bound' and target.get('drawing_uid') and target.get('drawing_revision'):
                    item['selector'] = {'drawingUid': target['drawing_uid'], 'expectedContentSha256': target['drawing_revision']}
            else:
                item = {'id': row['source_connection_id'], 'title': row.get('relationship_type_text') or '连接',
                        'bbox': None, 'state': row.get('review_state'), 'properties': {
                            '起点': row.get('endpoint_a', {}).get('source_id'), '终点': row.get('endpoint_b', {}).get('source_id'),
                            '连接类型': row.get('relationship_type_text')}}
            result[section].append(item)
    return result


def node_evidence(reader, descriptor, node=None):
    release = descriptor['knowledgeReleaseId']; local = node or descriptor['knowledgeNodeId']
    value = reader.reader._request('GET', reader.reader.prefix + '/knowledge-releases/' + quote(release, safe='') + '/nodes/' + quote(local, safe='') + '/evidence')
    d.require(value['document_id'] == descriptor['documentId'] and value['content_version_id'] == descriptor['contentVersionId'], 'SOURCE_CHANGED', 409)
    return value


def document_preview(reader, descriptor, options):
    result = {'kind': 'document', 'nodes': [], 'relations': [], 'evidence': [], 'gaps': [], 'nextCursor': None}
    fixed = dict(descriptor)
    if 'knowledgeReleaseId' not in fixed:
        releases = reader.reader._request('GET', reader.reader.prefix + '/documents/' + fixed['documentId'] + '/knowledge/releases?' + urlencode({'limit': 20, 'version_id': fixed['contentVersionId']}))
        release = next((row for row in releases.get('items', []) if row.get('content_version_id') == fixed['contentVersionId'] and row.get('state') == 'published'), None)
        if not release:
            result['gaps'].append('此固定文档版本暂无已发布知识图谱。'); return result
        fixed['knowledgeReleaseId'] = release['id']
    params = {'view': 'application', 'limit': 100, 'cursor': options.get('cursor', 0)}
    if options.get('q'): params['q'] = options['q']
    elif fixed.get('knowledgeNodeId') and options.get('graphScope') != 'all': params['root'] = fixed['knowledgeNodeId']
    value = reader.reader._request('GET', reader.reader.prefix + '/knowledge-releases/' + fixed['knowledgeReleaseId'] + '/graph?' + urlencode(params))
    d.require(value['document_id'] == fixed['documentId'] and value['content_version_id'] == fixed['contentVersionId'], 'SOURCE_CHANGED', 409)
    d.require(value['available_for_analysis'], 'KNOWLEDGE_RELEASE_UNAVAILABLE', 409)
    result.update(releaseId=fixed['knowledgeReleaseId'], state=value['state'], scope=value.get('scope'),
                  limitations=value.get('limitations'), nextCursor=value.get('next_cursor'))
    release = reader.reader._request('GET', reader.reader.prefix + '/documents/' + fixed['documentId'] + '/knowledge/releases/' + fixed['knowledgeReleaseId'] + '?view=application')['item']
    result['objectMappings'] = []
    node_ids = {n['local_id'] for n in value['nodes']}
    mappings = [m for m in release.get('payload', {}).get('mappings', []) if m.get('local_id') in node_ids
                and m.get('state') == 'confirmed' and (m.get('target') or {}).get('kind') == 'formal'][:100]
    for mapping in mappings:
        target = mapping.get('target') or {}
        if mapping.get('state') != 'confirmed' or target.get('kind') != 'formal': continue
        try: location = reader.reader._request('GET', '/api/v1/object-locations/' + quote(target['id'], safe=''))
        except PreviewError as error:
            if error.status in (401,403): raise
            result['gaps'].append('部分知识节点的对象映射当前不可用。'); continue
        if location.get('project_code') == reader.reader.project_code and location.get('row_version') == target.get('row_version') and not location.get('deleted_at'):
            result['objectMappings'].append({'nodeId': mapping['local_id'], 'entityUid': location['entity_uid'], 'title': mapping.get('display_name')})
        if len(result['objectMappings']) >= 100: break
    result['nodes'] = [{'id': n['local_id'], 'kind': n['kind'], 'title': literal(n, 'title'),
                        'statement': literal(n, 'statement'), 'faultCode': literal(n, 'fault_code'),
                        'properties': {key.removeprefix(OB): ', '.join(str(v.get('value', '')) for v in values)
                                       for key, values in n.get('payload', {}).get('properties', {}).items()}}
                       for n in value['nodes']]
    result['relations'] = [{'id': n['local_id'], 'from': n['payload']['subject_id'], 'to': n['payload']['object_id'],
                            'label': n['payload']['predicate'].removeprefix(OB)} for n in value['relations']]
    focus = options.get('nodeId') or fixed.get('knowledgeNodeId') or (result['nodes'][0]['id'] if result['nodes'] else None)
    if focus:
        ev = node_evidence(reader, fixed, focus)
        result['focusId'] = focus
        result['evidence'] = [{'id': row['local_id'], 'text': row.get('raw_text'), 'page': row['selector'].get('page'),
                              'bbox': bbox(row['selector'].get('bbox')), 'renditionId': row['selector'].get('rendition_id')}
                             for row in ev['items']]
        boxes = [r['bbox'] for r in result['evidence'] if r['page'] == descriptor['pageNumber'] and r['bbox']]
        if boxes:
            x = min(b['x'] for b in boxes); y = min(b['y'] for b in boxes)
            result['selector'] = image_selector({'x': x, 'y': y, 'width': max(b['x'] + b['width'] for b in boxes) - x,
                                                 'height': max(b['y'] + b['height'] for b in boxes) - y}, descriptor['sourceSha256'])
    return result


def fault_documents(reader, fault_code):
    graph = reader.reader._request('GET', reader.reader.prefix + '/document-knowledge/graph?' + urlencode({'q': fault_code, 'kind': 'FaultDefinition', 'limit': 12}))
    rows = []
    for node in graph['nodes']:
        if literal(node, 'fault_code') != fault_code: continue
        source = node.get('source', {}); document = source.get('document', {})
        if not document.get('id'): continue
        version = reader.reader._request('GET', reader.reader.prefix + '/documents/' + document['id'] + '/versions/' + source['version']['id'])['item']
        fixed = {'documentId': document['id'], 'contentVersionId': version['id'], 'sourceSha256': version['source_sha256'],
                 'knowledgeReleaseId': source['release_id'], 'knowledgeNodeId': source['local_id']}
        evidence = node_evidence(reader, fixed)
        pages = [row['selector'].get('page') for row in evidence['items'] if type(row['selector'].get('page')) is int]
        if not pages: continue
        fixed['pageNumber'] = min(pages)
        rows.append({'title': document['name'], 'selector': fixed, 'reason': '故障码 ' + fault_code + ' 的已发布知识节点及手册原文 · 第 ' + str(fixed['pageNumber']) + ' 页'})
    return rows


def preview(reader, kind, descriptor, options):
    d.require(type(options) is dict and set(options) <= {'section', 'cursor', 'q', 'nodeId', 'graphScope'})
    d.require(type(options.get('cursor', 0)) is int and 0 <= options.get('cursor', 0) <= 10000)
    d.require(options.get('graphScope', 'related') in ('related', 'all'))
    for key in ('q', 'nodeId'):
        if key in options: d.text(options[key], 512)
    reader.read(kind, descriptor)
    if kind == 'drawing': return drawing_preview(reader, descriptor, options)
    if kind == 'document': return document_preview(reader, descriptor, options)
    return {'kind': kind, 'gaps': []}


def relationships(reader, fixed, scene_library):
    values, gaps = {}, []
    for reference, descriptor in fixed:
        try:
            values[reference['evidenceRefId']] = (reference['sourceKind'], descriptor, reader.read(reference['sourceKind'], descriptor))
        except PreviewError as error:
            if error.status in (401, 403): raise
            gaps.append({'evidenceRefId': reference['evidenceRefId'], 'reason': error.code})
    edges = []
    def add(a, b, kind, label, anchor=None, reason='', *, origin='source'):
        if kind == 'model_binding' and any(edge['fromRef'] == a and edge['toRef'] == b and edge['kind'] == kind
                and edge['anchor']['componentKeys'] == anchor['componentKeys'] for edge in edges):
            return
        edges.append({'id': d.digest([a, b, kind, anchor])[:32], 'fromRef': a, 'toRef': b, 'kind': kind, 'label': label,
                      'anchor': anchor, 'reason': reason, 'origin': origin})
    def gap(identity, reason):
        if not any(row['evidenceRefId']==identity and row['reason']==reason for row in gaps):
            gaps.append({'evidenceRefId': identity, 'reason': reason})
    from .analysis_source_reader import matches_project_identifier
    for identity, (kind, descriptor, value) in values.items():
        dataset = value.get('dataset', {})
        if kind != 'alarm' or dataset.get('sourceKind') != 'simulated' or not dataset.get('primaryRds'):
            continue
        matches = [(ref, target) for ref, (target_kind, target, obj) in values.items()
                   if target_kind == 'object' and matches_project_identifier(obj['item'],dataset['primaryRds'],reader.reader.project_code)]
        if len({target['entityUid'] for _,target in matches}) > 1:
            gap(identity,'ALARM_OBJECT_MAPPING_AMBIGUOUS'); continue
        for ref, target in matches:
            add(identity,ref,'alarm_object_mapping','模拟报警对象',{'entityUid':target['entityUid']},
                '固定模拟报警配置按项目主位号 '+dataset['primaryRds']+' 显式映射；不表示已确认故障原因或现场安装身份')
    drawings = {}
    for identity, (kind, descriptor, value) in values.items():
        if kind == 'drawing':
            try: drawings[identity] = drawing_preview(reader, descriptor, {'section': 'references'})
            except PreviewError as error:
                if error.status in (401, 403): raise
                gaps.append({'evidenceRefId': identity, 'reason': error.code})
        for object_id, (object_kind, target, obj) in values.items():
            if object_kind != 'object': continue
            uid = target['entityUid']
            if kind in ('photo', 'drawing') and descriptor.get('entityUid') == uid:
                anchor = value.get('selector') if kind == 'photo' else drawings.get(identity, {}).get('selector')
                add(object_id, identity, kind + '_location', '照片定位' if kind == 'photo' else '图纸定位',
                    {'entityUid': uid, 'selector': anchor}, '来源中已登记的对象关联')
            if kind == 'object' and obj['item'].get('definitionParentEntityUid') == descriptor['entityUid']:
                add(object_id, identity, 'containment', '所属设备', reason='OntoBase 已登记定义层级')
    for source, drawing in drawings.items():
        for ref in drawing['references']:
            for target, other in drawings.items():
                if source != target and ref.get('selector') and ref.get('targetDrawingUid') == other['drawingUid'] and ref.get('targetRevision') == other['sourceRevision']:
                    add(source, target, 'drawing_reference', '图纸引用 · ' + ref['title'], {'drawingUid': other['drawingUid']}, ref.get('reason') or '')
    from .analysis_model_links import scene_bindings, candidate_components, component_name_index
    models = {ref: desc for ref, (kind, desc, _) in values.items() if kind == 'model'}
    indexes = {ref: component_name_index(values[ref][2].get('components', [])) for ref in models}
    bindings, truncated = scene_bindings(reader,scene_library,model_versions=[model['modelVersionId'] for model in models.values()])
    if truncated:
        for identity in models: gap(identity,'MODEL_BINDINGS_TRUNCATED')
    for object_id, (kind, descriptor, obj) in values.items():
        if kind != 'object': continue
        for model_id, model in models.items():
            components = values[model_id][2].get('components', [])
            keys = {component.get('componentKey') for component in components}
            matched = [row for row in bindings if row['modelVersionId']==model['modelVersionId']
                       and row['entityUid']==descriptor['entityUid'] and set(row['componentKeys']) <= keys]
            active = [row for row in matched if row['sceneState']=='active']
            for row in active or matched:
                history = row['sceneState']!='active'
                anchor = {'componentKeys':row['componentKeys'],'sceneId':row['sceneId'],'sceneRevision':row['sceneRevision']}
                if history: anchor['referenceKind']='historical_binding'
                add(object_id,model_id,'model_binding_history' if history else 'model_binding',
                    '历史场景绑定' if history else '模型整体绑定' if row['wholeModel'] else '模型构件绑定',anchor,
                    '绑定保存在回收站场景中，只作历史参考' if history else '有效场景中已保存的对象绑定；几何精度保持来源标识',
                    origin='candidate' if history else 'source')
                if history:
                    gap(object_id,'MODEL_BINDING_IN_RECYCLE_BIN'); gap(model_id,'MODEL_BINDING_IN_RECYCLE_BIN')
            if matched: continue
            candidates = candidate_components(obj['item'],components,by_name=indexes[model_id])
            if not candidates: continue
            add(object_id,model_id,'model_name_candidate','同名构件候选',{'componentKeys':candidates[:32],'referenceKind':'name_candidate'},
                '模型构件名与对象的主标识匹配，只用于查看候选位置；没有把项目定义、安装对象或同名构件认定为同一对象',origin='candidate')
            gap(object_id,'MODEL_NAME_CANDIDATE_ONLY'); gap(model_id,'MODEL_NAME_CANDIDATE_ONLY')
            if any(row['modelVersionId']==model['modelVersionId'] and row['entityUid']!=descriptor['entityUid']
                   and set(row['componentKeys']) & set(candidates) for row in bindings):
                gap(object_id,'MODEL_BOUND_TO_DIFFERENT_OBJECT'); gap(model_id,'MODEL_BOUND_TO_DIFFERENT_OBJECT')
    # Same-code links require the actual published fault_code property, not a title match.
    for doc_id, (kind, descriptor, _) in values.items():
        if kind != 'document': continue
        try: graph = document_preview(reader, descriptor, {})
        except PreviewError as error:
            if error.status in (401,403): raise
            gaps.append({'evidenceRefId': doc_id, 'reason': error.code}); continue
        for mapping in graph.get('objectMappings', []):
            for object_id, (source_kind, target, _) in values.items():
                if source_kind == 'object' and target['entityUid'] == mapping['entityUid']:
                    add(object_id, doc_id, 'knowledge_mapping', '知识图谱对象', {'nodeId': mapping['nodeId']}, '已发布知识中的已确认对象映射')
        codes = {n['faultCode'] for n in graph['nodes'] if n['faultCode']}
        for alarm_id, (source_kind, _, value) in values.items():
            if source_kind in ('alarm', 'work_order') and (value.get('dataset', {}).get('faultCode') or value.get('faultCode')) in codes:
                matching = next(n for n in graph['nodes'] if n['faultCode'] == (value.get('dataset', {}).get('faultCode') or value.get('faultCode')))
                add(alarm_id, doc_id, 'fault_manual', '故障代码手册', {'nodeId': matching['id'], 'pageNumber': descriptor['pageNumber']}, '已发布故障节点的代码与当前报警代码一致；适用范围见手册')
    reader.authorize()
    unique = {edge['id']: edge for edge in edges}
    return {'items': sorted(unique.values(),key=lambda edge:edge['origin']!='source')[:200], 'gaps': gaps[:200]}
