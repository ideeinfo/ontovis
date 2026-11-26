"""Add fixed drawings using the same registered relations as the canvas."""
import json
import re

from .analysis_preview import drawing_identity
from .analysis_recommendations import PAGE_SIZE, _drawing_page_key
from .analysis_source_reader import selected
from .assistant_store import require
from .assistant_summaries import redact
from .authority import PreviewError
from .related_drawings import RelatedDrawingsReader


def drawing_add_scope(question):
    alarm = r'(?P<alarm>(?:当前|本次|这条|这个)?(?:故障)?报警)'
    target = rf'(?:(?:与)?{alarm}的?(?:相关|关联|涉及)?的?|(?:当前画布的?)?(?:相关|关联)?的?)\s*(?:工程|电气)?图纸'
    verb = r'(?:加入|添加|加上|加)'
    text = question.strip().rstrip('。！？!?')
    request = re.fullmatch(rf'(?:请帮我|帮我|请)?\s*{verb}\s*{target}\s*(?:(?:到|至)(?:当前)?画布[上中]?)?', text)
    if request is None:
        request = re.fullmatch(rf'(?:请帮我|帮我|请)?\s*(?:把|将)\s*{target}\s*{verb}(?:(?:到|至)(?:当前)?画布[上中]?)?', text)
    if request:
        return 'alarm' if request['alarm'] else 'canvas'
    if re.fullmatch(r'(?:please )?add (?:the )?(?:(?:related|associated|engineering) )?drawings?(?: to (?:the )?canvas)?\.?', text, re.I):
        return 'canvas'
    return None


def drawing_context(body, draft):
    # Restrict expansion to the owned draft's current object, alarm and drawing cards.
    ids = dict.fromkeys(card['source']['id'] for card in draft['cards']
        if card.get('source') and not card.get('historical') and card['kind'] in ('object', 'alarm', 'drawing'))
    return {**body, 'evidenceRefIds': list(ids)}


def _drawing_objects(reader, fixed, draft, body, scope, allowed, read):
    require({'object', 'drawing'} <= allowed, 'ASSISTANT_TOOL_NOT_ALLOWED', 403)
    objects = {ref['evidenceRefId']: descriptor for ref, descriptor in fixed if ref['sourceKind'] == 'object'}
    if not objects:
        return {}
    explicit = body.get('preferSelectedEvidence', False)
    chosen = set(body['evidenceRefIds'])
    if scope == 'canvas' and explicit:
        chosen_objects = {ref: descriptor for ref, descriptor in objects.items() if ref in chosen}
        if chosen_objects:
            return chosen_objects

    alarms = [descriptor for ref, descriptor in fixed if ref['sourceKind'] == 'alarm'
              and (scope == 'alarm' or not explicit or ref['evidenceRefId'] in chosen)]
    if scope == 'alarm' or alarms:
        require('alarm' in allowed, 'ASSISTANT_TOOL_NOT_ALLOWED', 403)
        current_event = draft['context'].get('eventId')
        current = next((descriptor for descriptor in alarms if descriptor['eventId'] == current_event), None)
        if current is None and len(alarms) == 1 and (scope == 'canvas' or not current_event):
            current = alarms[0]
        if current is None:
            return {}
        dataset = read(lambda: reader.read('alarm', current))['dataset']
        target = selected(read(lambda: reader._rds(dataset['primaryRds'])))
        return {ref: descriptor for ref, descriptor in objects.items() if descriptor == target}
    return {} if explicit else objects


def _recorded_drawings(reader, descriptor):
    return RelatedDrawingsReader(reader.reader).resolve({**descriptor, 'includeDescendants': True, 'limit': PAGE_SIZE})


def _record_gap(gaps, error):
    if error.status in (401, 403) or error.code in ('ASSISTANT_CANCELLED', 'ASSISTANT_POLICY_CHANGED',
            'ACCESS_CHANGED', 'SESSION_CHANGED', 'ASSISTANT_TIMEOUT'):
        raise error
    gaps.append(error.code)


def _already_on_canvas(tools, fixed, candidates, gaps):
    by_hash = {row['contentSha256'] for _, row in candidates.values()}
    identifiable = {(row['drawingUid'], row['contentSha256']): key for key, (_, row) in candidates.items()}
    present = set()
    for ref, descriptor in fixed:
        if ref['sourceKind'] != 'drawing' or descriptor['expectedContentSha256'] not in by_hash:
            continue
        digest = descriptor['expectedContentSha256']
        match = identifiable.get((descriptor.get('drawingUid'), digest))
        if match:
            present.add(match)
            continue
        try:
            def source_page():
                drawing, _ = drawing_identity(tools.reader, descriptor)
                if drawing is not None:
                    return drawing.get('source_page_number')
                return tools.reader.read('drawing', descriptor).get('pageNumber')
            page = tools.read(source_page)
        except PreviewError as error:
            _record_gap(gaps, error)
            continue
        present.add(_drawing_page_key({'pageNumber': page, 'contentSha256': digest}))
    return present


def drawing_answer(tools, fixed, draft, body, scope, plan):
    gaps, candidates = [], {}
    truncated = False
    try:
        objects = _drawing_objects(tools.reader, fixed, draft, body, scope, tools.allowed, tools.read)
    except PreviewError as error:
        _record_gap(gaps, error)
        objects = {}
    visited = set()
    for ref, descriptor in objects.items():
        identity = tuple(descriptor[key] for key in ('entityUid', 'expectedEntityRevision', 'installationContextId', 'expectedHierarchyRevision'))
        if identity in visited:
            continue
        visited.add(identity)
        try:
            page = tools.read(lambda: _recorded_drawings(tools.reader, descriptor))
        except PreviewError as error:
            _record_gap(gaps, error)
            if error.code == 'ASSISTANT_READ_LIMIT':
                break
            continue
        truncated |= page['nextCursor'] is not None
        for row in page['items']:
            if row['availability'] == 'available':
                candidates.setdefault(_drawing_page_key(row), (ref, row))
    present = _already_on_canvas(tools, fixed, candidates, gaps)
    pending = [candidate for key, candidate in candidates.items() if key not in present]
    card_titles = {card['source']['id']: card['title'] for card in draft['cards'] if card.get('source')}
    for ref, row in pending[:PAGE_SIZE]:
        direct = any(match['relation'] in ('self', 'shared_definition') for match in row['matchedObjects'])
        basis = '登记关联' if direct else '下级对象图纸'
        reason = f'「{card_titles[ref]}」的{basis}' + (f' · 源页 {row["pageNumber"]}' if row['pageNumber'] is not None else '')
        tools.results.append(dict(key=f'R{len(tools.results)+1}', kind='drawing', title=row['title'][:120],
            identifier=row['drawingUid'], version=row['sourceRevision'], reason=reason, simulated=False,
            drawingObjectRefId=ref, selector=dict(drawingUid=row['drawingUid'], expectedContentSha256=row['contentSha256'])))

    count = len(pending)
    truncated |= count > len(tools.results)
    state = 'budget_limited' if 'ASSISTANT_READ_LIMIT' in gaps else 'unavailable' if gaps else 'complete'
    trace = dict(tool='related_drawings', state=state, scope='画布工程对象的登记图纸', count=len(tools.results), truncated=truncated)
    if gaps:
        trace['reason'] = gaps[0]
    tools.trace.append(trace)
    if count:
        message = f'找到 {count} 张可加入的关联图纸。'
    elif gaps or truncated:
        message = '已读取的范围内暂未找到可加入的图纸。'
    elif candidates:
        message = '当前范围内的关联图纸已在画布上。'
    elif objects:
        message = '这些工程对象暂无可用的登记图纸。'
    else:
        message = '请先加入当前报警的工程对象，或在画布资料中选择要查找图纸的工程对象。'
    summary = redact(json.dumps(dict(count=count,
        drawings=[dict(key=row['key'], title=row['title'], basis=row['reason']) for row in tools.results]),
        ensure_ascii=False), tools.private)[:1000]
    tools.catalogue_source('drawing', summary, message)
    answer = tools.catalogue_answer()
    room = 50-len(draft['cards'])
    if plan['intent'] == 'edit' and count:
        if not gaps and not truncated and count <= room:
            plan['actions'] = [dict(kind='add_results', targets=[row['key'] for row in tools.results], text='', x=None, y=None)]
        elif room:
            answer['nextSteps'].append(dict(text='可从下方选择要加入的图纸。', refs=[]))
        else:
            answer['gaps'].append(dict(text='画布已达卡片数量上限。', refs=[]))
    return answer


def checked_drawing_results(reader, fixed, draft, body, scope, allowed, plan, results, *, compound=False):
    """Recheck the registered relation before a fresh or retried draft application."""
    error = 'ASSISTANT_DRAWING_REVIEW_REQUIRED'
    actions = [action for action in plan['actions'] if action['kind']=='add_results'] if compound else plan['actions']
    require(len(actions) == 1 and actions[0]['kind'] == 'add_results' and actions[0]['targets'], error, 409)
    choices = {row['key']: row for row in results}
    rows = [choices.get(key) for key in actions[0]['targets']]
    require(all(row and row['kind'] == 'drawing' and row.get('drawingObjectRefId') for row in rows), error, 409)
    objects = _drawing_objects(reader, fixed, draft, body, scope, allowed, lambda operation: operation())
    pages = {}
    for row in rows:
        ref = row['drawingObjectRefId']
        require(ref in objects, error, 409)
        if ref not in pages:
            pages[ref] = {(item['drawingUid'], item['contentSha256'], item['sourceRevision'])
                          for item in _recorded_drawings(reader, objects[ref])['items'] if item['availability'] == 'available'}
        selector = row['selector']
        require((selector['drawingUid'], selector['expectedContentSha256'], row['version']) in pages[ref], error, 409)
    return rows
