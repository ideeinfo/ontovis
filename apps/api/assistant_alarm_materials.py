"""Use the existing alarm and material associations for an explicit canvas addition."""
import json
import re

from .analysis_object_recommendations import object_recommendation
from .analysis_recommendations import _source_page, registered_recommendation_revisions
from .assistant_canvas_tasks import result_targets
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


def candidates(reader, dataset, kinds, read, *, trace=None):
    """Only use the configured alarm object and the material picker's fixed associations."""
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
            trace.append(dict(tool=tool,state='complete',count=len(rows) if isinstance(rows,list) else 1))
        return rows

    rows = []
    target = lookup('alarm_object',lambda:reader._rds(dataset['primaryRds'])) \
        if dataset.get('primaryRds') and kinds.intersection(('object','drawing')) else None
    if target and 'object' in kinds:
        rows.append(object_recommendation(target['item'],'报警配置指定的工程对象',
            'Engineering object registered for this alarm.',identifier=dataset['primaryRds']))
    if target and 'drawing' in kinds:
        rows.extend(lookup('related_drawings',lambda:_source_page(reader,target,dataset,'drawings','drawings',None,'',{})[0]) or [])
    if 'document' in kinds:
        rows.extend(lookup('alarm_manuals',lambda:_source_page(reader,None,dataset,'documents','fault',None,'',{})[0]) or [])
    return [row for row in rows if row.get('availability','available')=='available']


def allowed_kinds(kinds, switches):
    return kinds.intersection(('object','drawing','document') if 'manual_fault_lookup' in switches else ('object','drawing'))


def plan_addition(tools, fixed, draft, anchor, plan, switches, *, analyze=False):
    if anchor is None:
        answer=tools.catalogue_answer()
        answer['gaps'].append(dict(text='请选中要分析的报警卡片，再查找它的关联资料。',refs=[]))
        return answer
    _, descriptor=anchor
    if 'alarm' not in tools.allowed:
        answer=tools.catalogue_answer()
        answer['gaps'].append(dict(text='当前项目策略未允许读取报警。',refs=[]))
        return answer
    wanted=allowed_kinds(tools.allowed,switches)
    try:
        dataset=tools.alarm(descriptor)['dataset']
    except PreviewError as error:
        if error.status in (401,403,504) or error.code in ('ACCESS_CHANGED','SESSION_CHANGED') or error.code.startswith('ASSISTANT_'):
            raise
        tools.trace.append(dict(tool='alarm_object',state='unavailable',reason=error.code))
        return tools.catalogue_answer()
    rows=candidates(tools.reader,dataset,wanted,tools.read,trace=tools.trace)
    current={card['source']['id'] for card in draft['cards'] if card.get('source') and not card.get('historical')}
    registered=[(ref['sourceKind'],value,ref['sourceRevision']) for ref,value in fixed if ref['evidenceRefId'] in current]
    unique, existing = {}, set()
    for row in rows:
        identity = row.get('assetKey',row['key'])
        unique.setdefault(identity,row)
        if registered_recommendation_revisions(row,registered):
            existing.add(identity)
    sources=[]
    for identity,row in unique.items():
        selector=row['selector']
        kind=row['kind']
        version=selector.get('expectedEntityRevision') or selector.get('expectedSourceRevision') or selector.get('contentVersionId')
        summary=redact(json.dumps(dict(title=row['title'],reason=row['reason'],
            scope='已核对的报警关联登记与固定出处。图纸和手册仅含此处列出的元数据。'),
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
        if identity not in existing:
            tools.results.append(dict(key=f'R{len(tools.results)+1}',kind=kind,title=row['title'],
                identifier=row.get('identifier') or row.get('assetKey',row['key']),version=version,
                reason=row['reason'],selector=selector,simulated=False))
    answer=tools.catalogue_answer()
    if sources:
        answer['observations'].append(dict(text=f'按本次报警核对了 {len(sources)} 项登记资料。',refs=sources[:8]))
    room=min(12,50-len(draft['cards']))
    if plan['intent']=='edit' and 0<len(tools.results)<=room:
        plan['actions']=[dict(kind='add_results',targets=[r['key'] for r in tools.results],text='',x=None,y=None)]
    if not tools.results:
        answer['gaps'].append(dict(text='关联资料已在画布上，或本轮没有读到新的登记资料。',refs=[]))
    elif len(tools.results)>room:
        answer['nextSteps'].append(dict(text='可从已核对的候选中选择本次要加入的资料。',refs=[]))
    return answer


def checked_additions(reader, fixed, draft, body, allowed, switches, plan, results):
    anchor=alarm_anchor(fixed,draft,body)
    require(anchor and 'alarm' in allowed,'ASSISTANT_TARGET_AMBIGUOUS',409)
    chosen=[row for action in plan['actions'] if action['kind']=='add_results'
            for row in result_targets(results,action['targets'])]
    require(chosen,'ASSISTANT_TARGET_AMBIGUOUS',409)
    kinds={row['kind'] for row in chosen}
    require(kinds<=allowed_kinds(allowed,switches),'ASSISTANT_TOOL_NOT_ALLOWED',403)
    live=candidates(reader,reader.read('alarm',anchor[1])['dataset'],kinds,lambda operation:operation())
    require(all(any(row['kind']==item['kind'] and row['selector']==item['selector'] for item in live) for row in chosen),
            'SOURCE_CHANGED',409)
