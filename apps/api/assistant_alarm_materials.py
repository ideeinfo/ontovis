"""Use the existing alarm and material associations for an explicit canvas addition."""
import json
import re
from typing import NamedTuple

from .analysis_evidence import SELECTION
from .analysis_object_recommendations import object_recommendation
from .analysis_recommendations import _source_page, registered_recommendation_revisions
from .assistant_canvas_tasks import plan_candidate_additions, result_targets
from .assistant_drawings import drawings_on_canvas
from .assistant_graph import material_summary
from .assistant_store import require
from .assistant_summaries import redact
from .authority import PreviewError


def alarm_material_add(question):
    subject = (r'(?:与)?(?:当前|本次|这次|这条|该)?(?:故障)?报警的?'
               r'(?:相关|关联|涉及)的?(?:资料|材料|证据)(?:卡片)?')
    verb = r'(?:加入|添加|加上|放入)'
    place = r'(?:(?:到|至)(?:当前)?画布[上中]?)?'
    return bool(re.fullmatch(rf'(?:请帮我|帮我|请)?\s*(?:{verb}\s*{subject}|(?:把|将)\s*{subject}\s*{verb})\s*{place}',
                             question.strip().removeprefix('先').strip().rstrip('。！？!?')))


class LinkedMaterials(NamedTuple):
    scope: str
    kinds: frozenset[str]


def linked_add_scope(question):
    """Identify a list of requested material types independently of its order."""
    text = ' '.join(question.strip().rstrip('。.!！?？').split())
    alarm = r'(?P<alarm>(?:当前|本次|这次|这条|该|选中(?:的)?)?(?:故障)?报警)'
    scope = rf'(?:(?:与)?{alarm}的?|(?:当前|本次)?画布(?:中|上)?的?|(?:选中|所选)(?:的)?卡片的?)?'
    related = r'(?:直接)?(?:(?:相关|关联|涉及|对应)的?)?'
    kinds = {'object':r'工程对象', 'drawing':r'(?:工程|电气)?图纸', 'document':r'(?:文档|手册|说明书)',
             'photo':r'(?:现场)?(?:照片|图片)'}
    material = '(?:'+'|'.join(kinds.values())+')'
    join = r'(?:[,，、]|以及|和|及|与|跟)(?:其)?'
    material_list = rf'(?P<materials>{material}(?:{join}{related}{material})*)'
    targets = rf'{scope}{related}{material_list}(?:卡片)?'
    verb = r'(?:加入|添加|加上|补上|放入|加|放)'
    together = r'(?:一起|同时|一并|都)?'
    place = r'(?:(?:到|至)?(?:当前)?画布[上中]?)?'
    prefix = rf'(?:请帮我|帮我|请|能否|能不能|可以)?(?:自动)?{together}'
    compact = text.replace(' ', '')
    request = (re.fullmatch(rf'{prefix}{verb}{targets}{place}', compact) or
               re.fullmatch(rf'{prefix}(?:把|将){targets}{together}{verb}{place}', compact) or
               re.fullmatch(rf'{prefix}(?:为|给){alarm}{together}{verb}{related}{material_list}{place}',compact))
    if request:
        return LinkedMaterials('alarm' if request['alarm'] else 'canvas',
                               frozenset(kind for kind, pattern in kinds.items() if re.search(pattern,request['materials'])))
    kinds = {'object':r'engineering objects?', 'drawing':r'(?:engineering |electrical )?drawings?',
             'document':r'(?:documents?|manuals?)', 'photo':r'(?:photos?|pictures?)'}
    material = '(?:'+'|'.join(kinds.values())+')'
    request = re.fullmatch(
        r'(?:please )?add (?:the )?(?:directly )?(?:related |associated )?'
        rf'(?P<materials>{material}(?:(?:, (?:and )?| and )(?:their |related )?{material})*)'
        r'(?: for (?P<alarm>(?:the current|this|the selected) alarm))?(?: to (?:the )?canvas)?',
        text, re.I)
    if request:
        return LinkedMaterials('alarm' if request['alarm'] else 'canvas',
                               frozenset(kind for kind, pattern in kinds.items()
                                         if re.search(r'\b'+pattern+r'\b',request['materials'],re.I)))
    return None


def alarm_anchor(fixed, draft, body):
    current = {card['id']: card['source']['id'] for card in draft['cards']
               if card['kind']=='alarm' and not card.get('historical')}
    current_refs = set(current.values())
    allowed = set(body['evidenceRefIds']) if body.get('preferSelectedEvidence') else current_refs
    alarms = [(ref, descriptor) for ref, descriptor in fixed if ref['sourceKind']=='alarm'
              and ref['evidenceRefId'] in current_refs and ref['evidenceRefId'] in allowed]
    focused_refs = {current[key] for key in body.get('focusCardIds',[]) if key in current}
    focused = [item for item in alarms if item[0]['evidenceRefId'] in focused_refs]
    if len(focused)==1:
        return focused[0]
    matching = [item for item in alarms if item[1]['eventId']==draft['context'].get('eventId')]
    return matching[0] if len(matching)==1 else alarms[0] if len(alarms)==1 else None


def linked_anchor(fixed, draft, body, scope, requested=()):
    kinds = {'alarm'} if scope == 'alarm' else {'alarm','object'}
    focus = set(body.get('focusCardIds',[]))
    drawings = scope == 'canvas' and 'photo' in requested
    current = {card['id']: card['source']['id'] for card in draft['cards']
               if (card['kind'] in kinds or drawings and card['kind']=='drawing' and card['id'] in focus)
               and not card.get('historical')}
    focused = {current[key] for key in focus if key in current}
    sources = [item for item in fixed if (item[0]['sourceKind'] in kinds or drawings
               and item[0]['sourceKind']=='drawing' and 'entityUid' in item[1])
               and item[0]['evidenceRefId'] in current.values()]
    if focused:
        matches = [item for item in sources if item[0]['evidenceRefId'] in focused]
        return matches[0] if len(matches)==1 else None
    alarms = [item for item in sources if item[0]['sourceKind']=='alarm']
    matching = [item for item in alarms if item[1]['eventId']==draft['context'].get('eventId')]
    if len(matching)==1:
        return matching[0]
    candidates = alarms or sources
    return candidates[0] if len(candidates)==1 else None


def _material_object_source(reader, kind, descriptor, allowed, read):
    if kind=='drawing':
        require('object' in allowed,'ASSISTANT_TOOL_NOT_ALLOWED',403)
        read(lambda:reader.read('drawing',descriptor))
        return {key:descriptor[key] for key in SELECTION}
    return descriptor if kind=='object' else None


def candidates(reader, dataset, kinds, read, *, trace=None, object_source=None, allow_drawing_fallback=True):
    """Read the registered material associations of the selected or alarm object."""
    def lookup(tool, operation):
        try:
            rows = read(operation)
        except PreviewError as error:
            if trace is None or error.status in (401,403) or error.code in (
                'ASSISTANT_CANCELLED','ASSISTANT_POLICY_CHANGED','ACCESS_CHANGED','SESSION_CHANGED','ASSISTANT_TIMEOUT'):
                raise
            trace.append(dict(tool=tool,state='unavailable',reason=error.code))
            return None
        if trace is not None:
            items=rows[0] if isinstance(rows,tuple) else rows
            trace.append(dict(tool=tool,state='complete',count=len(items) if isinstance(items,list) else 1))
        return rows

    rows = []
    primary = (dataset or {}).get('primaryRds')
    target = None
    if kinds.intersection(('object','drawing','photo')):
        if object_source is not None:
            target = lookup('objects',lambda:reader.read('object',object_source))
        elif primary:
            target = lookup('alarm_object',lambda:reader._rds(primary))
    if target and 'object' in kinds:
        reason = '报警配置指定的工程对象' if primary else '当前选中的工程对象'
        reason_en = 'Engineering object registered for this alarm.' if primary else 'Selected engineering object.'
        rows.append(object_recommendation(target['item'],reason,reason_en,identifier=primary))
    if target and 'drawing' in kinds:
        drawings = lookup('related_drawings',lambda:_source_page(reader,target,dataset,'drawings','drawings',None,'',{})[0]) or []
        name = target['item'].get('displayName') or primary
        for row in drawings:
            page = row['preview'].get('pageNumber')
            row['reason'] = (f'「{name}」的登记图纸' if name else '对象的登记图纸') + (f' · 第 {page} 页' if page is not None else '')
        if not drawings and allow_drawing_fallback:
            related = lookup('related_drawings',lambda:_source_page(reader,target,dataset,'drawings','related_drawings',None,'',{}))
            if related:
                drawings, cursor = related
                if cursor and trace is not None:
                    trace[-1]['truncated'] = True
                for row in drawings:
                    page = row['preview']['pageNumber']
                    row['reason'] = (f'「{name}」' if name else '') + row['reason'] + (f' · 第 {page} 页' if page is not None else '')
        rows.extend(drawings)
    if 'document' in kinds:
        rows.extend(lookup('alarm_manuals',lambda:_source_page(reader,None,dataset,'documents','fault',None,'',{})[0]) or [])
    if target and 'photo' in kinds:
        memo={}
        photos=[]
        for source in ('field','photos'):
            photos.extend(lookup('related_photos',lambda:_source_page(reader,target,dataset,'photos',source,None,'',memo)[0]) or [])
        for source in ('shared_photos','parent_photos'):
            if any(row.get('availability','available')=='available' for row in photos):break
            page=lookup('related_photos',lambda:_source_page(reader,target,dataset,'photos',source,None,'',memo))
            if page:
                photos.extend(page[0])
                if page[1] and trace is not None:trace[-1]['truncated']=True
        rows.extend(photos)
    return [row for row in rows if row.get('availability','available')=='available']


def allowed_kinds(kinds, switches):
    return kinds.intersection(('object','drawing','document') if 'manual_fault_lookup' in switches else ('object','drawing'))


def requested_kinds(kinds, switches, linked):
    allowed=allowed_kinds(kinds,switches)
    if linked:
        return (allowed | (kinds & {'photo'})) & linked.kinds
    return allowed


def material_location(kind, value):
    if kind=='document' and value.get('documentId') and value.get('contentVersionId'):
        return value['documentId'],value['contentVersionId'],value.get('pageNumber')
    if kind=='photo':
        version=value.get('expectedContentVersionId') or value.get('contentVersionId')
        if version:return (version,)
    return None


def equivalent_material(kind, selector, current_fixed, *, preview=None):
    location=material_location(kind,{**(preview or {}),**selector})
    if location:
        return next((ref for ref,value in current_fixed
                     if ref['sourceKind']==kind and material_location(kind,value)==location),None)
    return None


def plan_addition(tools, fixed, draft, anchor, plan, switches, *, analyze=False, linked=None):
    if anchor is None:
        answer=tools.catalogue_answer()
        answer['gaps'].append(dict(text='请选中要分析的报警卡片，再查找它的关联资料。',refs=[]))
        return answer
    ref, descriptor=anchor
    anchor_kind=ref['sourceKind']
    if anchor_kind not in tools.allowed:
        answer=tools.catalogue_answer()
        answer['gaps'].append(dict(text='当前项目策略未允许读取所选卡片的来源。',refs=[]))
        return answer
    wanted=requested_kinds(tools.allowed,switches,linked)
    try:
        dataset=tools.alarm(descriptor)['dataset'] if anchor_kind=='alarm' else None
        object_source=_material_object_source(tools.reader,anchor_kind,descriptor,tools.allowed,tools.read)
    except PreviewError as error:
        if error.status in (401,403,504) or error.code in ('ACCESS_CHANGED','SESSION_CHANGED') or error.code.startswith('ASSISTANT_'):
            raise
        tools.trace.append(dict(tool='alarm_object',state='unavailable',reason=error.code))
        return tools.catalogue_answer()
    rows=candidates(tools.reader,dataset,wanted,tools.read,trace=tools.trace,object_source=object_source)
    current={card['source']['id'] for card in draft['cards'] if card.get('source') and not card.get('historical')}
    current_fixed=[(ref,value) for ref,value in fixed if ref['evidenceRefId'] in current]
    registered=[(ref['sourceKind'],value,ref['sourceRevision']) for ref,value in current_fixed]
    unique, existing = {}, set()
    for row in rows:
        identity = row.get('assetKey',row['key'])
        unique.setdefault(identity,row)
        if registered_recommendation_revisions(row,registered) or linked and equivalent_material(
                row['kind'],row['selector'],current_fixed,preview=row.get('preview')):
            existing.add(identity)
    unverified=set()
    if linked:
        drawing_pages={key:(None,row['preview']) for key,row in unique.items()
                       if row['kind']=='drawing' and key not in existing}
        gaps=[]
        existing.update(drawings_on_canvas(tools.reader,current_fixed,drawing_pages,tools.read,gaps))
        if gaps:
            tools.trace.append(dict(tool='related_drawings',state='unavailable',reason=gaps[0]))
            unverified.update(drawing_pages)
    sources=[]
    for identity,row in unique.items():
        selector=row['selector']
        kind=row['kind']
        version=(selector.get('expectedEntityRevision') or selector.get('expectedSourceRevision') or
                 selector.get('contentVersionId') or (row.get('preview') or {}).get('sourceRevision'))
        summary=redact(json.dumps(dict(title=row['title'],reason=row['reason'],
            scope='已核对的资料登记关系。'),
            ensure_ascii=False),tools.private)[:1000]
        detail={'descriptor':selector} if kind=='document' else {}
        if kind=='document' and analyze:
            try:
                manual=tools.read(lambda:material_summary(tools.reader,kind,selector,tools.private))
                summary=manual['summary']
                detail.update({key:value for key,value in manual.items() if key!='summary'})
                tools.trace.append(dict(tool='fixed_manual_neighborhood',state='complete',count=1))
            except PreviewError as error:
                if error.status in (401,403,504) or error.code in ('ACCESS_CHANGED','SESSION_CHANGED') or error.code.startswith('ASSISTANT_'):
                    raise
                tools.trace.append(dict(tool='fixed_manual_neighborhood',state='unavailable',reason=error.code))
        sources.append(tools.source(kind,summary,**detail)['key'])
        if identity not in existing and identity not in unverified:
            tools.results.append(dict(key=f'R{len(tools.results)+1}',kind=kind,title=row['title'],
                identifier=row.get('identifier') or row.get('assetKey',row['key']),version=version,
                reason=row['reason'],selector=selector,simulated=False))
    answer=tools.catalogue_answer()
    if sources:
        scope='所选卡片' if linked else '本次报警'
        answer['observations'].append(dict(text=f'按{scope}核对了 {len(sources)} 项登记资料。',refs=sources[:8]))
    if linked:
        labels={'object':'工程对象','drawing':'图纸','document':'文档','photo':'照片'}
        found={row['kind'] for row in rows}
        for kind,label in labels.items():
            if kind not in linked.kinds:
                continue
            if kind not in wanted:
                answer['gaps'].append(dict(text=f'当前项目策略未启用{label}读取。',refs=[]))
            elif kind not in found:
                answer['gaps'].append(dict(text=f'本轮没有找到可加入的登记{label}。',refs=[]))
        if rows and not tools.results and not unverified:
            answer['observations'].append(dict(text='查到的关联资料已在画布上。',refs=[]))
    elif not tools.results:
        answer['gaps'].append(dict(text='关联资料已在画布上，或本轮没有读到新的登记资料。',refs=[]))
    complete=not any(row['state']!='complete' or row.get('truncated') for row in tools.trace)
    plan_candidate_additions(draft, plan, tools.results, answer, complete=complete and (not linked or linked.kinds<=found))
    return answer


def checked_additions(reader, fixed, draft, body, allowed, switches, plan, results, *, linked=None, anchor_ref=None):
    anchor=linked_anchor(fixed,draft,body,linked.scope,linked.kinds) if linked else alarm_anchor(fixed,draft,body)
    if linked:
        require(anchor and anchor[0]['evidenceRefId']==anchor_ref,'ASSISTANT_LINKED_MATERIALS_CHANGED',409)
    require(anchor and anchor[0]['sourceKind'] in allowed,'ASSISTANT_TARGET_AMBIGUOUS',409)
    chosen=[row for action in plan['actions'] if action['kind']=='add_results'
            for row in result_targets(results,action['targets'])]
    require(chosen,'ASSISTANT_TARGET_AMBIGUOUS',409)
    kinds={row['kind'] for row in chosen}
    permitted=requested_kinds(allowed,switches,linked)
    require(kinds<=permitted,'ASSISTANT_TOOL_NOT_ALLOWED',403)
    ref,descriptor=anchor
    dataset=reader.read('alarm',descriptor)['dataset'] if ref['sourceKind']=='alarm' else None
    def read(operation):
        return operation()
    object_source=_material_object_source(reader,ref['sourceKind'],descriptor,allowed,read)
    whole_drawings=any(row['kind']=='drawing' and 'drawingUid' in row['selector'] for row in chosen)
    live=candidates(reader,dataset,kinds,read,object_source=object_source,allow_drawing_fallback=whole_drawings)
    matches=[next((row for row in live if row['kind']==item['kind'] and row['selector']==item['selector']
                   and ('drawingUid' not in item['selector'] or row['preview']['sourceRevision']==item['version'])),None)
             for item in chosen]
    require(all(matches),'ASSISTANT_LINKED_MATERIALS_CHANGED' if linked else 'SOURCE_CHANGED',409)
    if not linked:
        return {}
    drawing_pages={row['assetKey']:(None,row['preview']) for row in matches if row['kind']=='drawing'}
    current={card['source']['id'] for card in draft['cards'] if card.get('source') and not card.get('historical')}
    gaps=[]
    current_fixed=[(ref,value) for ref,value in fixed if ref['evidenceRefId'] in current]
    present=drawings_on_canvas(reader,current_fixed,drawing_pages,read,gaps)
    require(not gaps,'ASSISTANT_LINKED_MATERIALS_CHANGED',409)
    registered={}
    for item,row in zip(chosen,matches):
        ref=(present.get(row.get('assetKey')) if row['kind']=='drawing' else
             equivalent_material(row['kind'],row['selector'],current_fixed,preview=row.get('preview')))
        if ref:registered[item['key']]=ref
    return registered
