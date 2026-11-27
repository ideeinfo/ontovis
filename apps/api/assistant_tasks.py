"""Bounded project tools for the existing assistant runner, separate from Canvas membership."""
import hashlib
import json
import re
from urllib.parse import urlencode
from uuid import uuid4

from .assistant_store import require, digest
from .assistant_summaries import redact, summarize, work_order_summary, answer_batches
from .authority import PreviewError
from .assistant_canvas_tasks import ACTIONS, plan_candidate_additions, require_target, result_targets, validate_draft_plan
from .assistant_drawings import drawing_add_scope, drawing_answer
from . import assistant_alarm_materials

PROTOCOL='ontovis-engineering-tasks-v1'
QUERY_TOOLS=('work_orders','objects','materials','graph','knowledge')
CATALOGUE_TOOLS=('equipment_materials','processing_tasks','equipment_configurations')

DISPOSITION_GUIDANCE = (
    '请结合本轮授权摘要和画布上下文给出整体处置建议。先归纳已知情况及影响范围，再给出有依据的待验证假设，'
    '明确缺少的资料与需核对的对象。按优先级列出人工核验、可考虑的处置与恢复验证，每项写清对象、依据及通过条件。'
    '人工笔记和画布手工连线只用于识别待核线索；历史参考不能证明当前状态。仅元数据的来源不能证明图面、接线或实际几何。'
    '无依据的环节写明需要核实的内容，不编造现场结果或确认根因，不要求直接控制设备。'
)


def _disposition_clause(question):
    return bool(re.match(
        r'(?:(?:请帮我|帮我|请|能否|能不能|可以)\s*)?(?:基于|结合|根据|参考|按)?'
        r'(?:(?:当前|现有|这张|本次|本轮)?(?:的)?(?:画布|报警|故障|历史工单|手册|资料)[^。；\n]{0,28}?)?'
        r'(?:生成|给出|提供|分析|整理|提出|输出|给我|制定)\s*[^。；\n]{0,40}?'
        r'(?:处置|排查|故障处理)的?(?:建议|方案|计划|流程)'
        r'|(?:整体|综合|完整|总体)(?:处置|排查)(?:建议|方案|计划|流程)'
        r'|(?:(?:这次|本次|当前)(?:报警|故障))?(?:该|应该)?(?:如何|怎么)(?:处置|排查|处理)'
        r'|(?:please )?(?:generate|provide|suggest|draft|give me) [^.!?\n]{0,60}'
        r'(?:response plan|disposition plan|troubleshooting plan|overall recommendations)',
        question.strip(), re.I))


def turn_requests(question):
    # Quoted titles and note contents remain part of the edit instruction.
    parts, start = [], 0
    separators = r'“[^”]*”|「[^」]*」|『[^』]*』|"[^"]*"|[，,；;。\n]|然后|并且|并|再'
    for match in re.finditer(separators, question):
        if match[0][0] in '“「『"':
            continue
        parts.append(question[start:match.start()].strip())
        start = match.end()
    parts.append(question[start:].strip())
    advice = [_disposition_clause(part.removeprefix('先').strip()) for part in parts]
    if not any(advice):
        return question, False
    edit_parts = [part for part, is_advice in zip(parts, advice) if part and not is_advice]
    if len(edit_parts)==1 and re.fullmatch(r'(?:基于|结合|根据|参考|按)(?:当前|现有|这张|本次|本轮)?(?:的)?(?:画布|报警|故障|历史工单|手册|资料)', edit_parts[0]):
        edit_parts.clear()
    return '，'.join(edit_parts), True


def disposition_request(question):
    return turn_requests(question)[1]


def disposition_context(draft, planning, reads, private):
    by_ref = {read['evidenceRefId']: read for read in reads}
    cards = []
    note_budget = 4800
    for card, key in zip(draft['cards'], planning['cards']):
        row = {k: key[k] for k in ('key', 'kind', 'title', 'historical', 'frame')}
        ref = card.get('source', {}).get('id')
        if ref:
            read = by_ref.get(ref, {})
            row.update(evidenceState=read.get('state', 'not_selected'))
            if read.get('sourceKey'):
                row.update(evidence=read['sourceKey'], metadataOnly=read['metadataOnly'])
        else:
            note = redact(card.get('note', ''), private)
            excerpt = note[:min(320, note_budget)]
            note_budget -= len(excerpt)
            row.update(note=excerpt, noteTruncated=len(excerpt)<len(note), checkState=card.get('checkState', 'not_started'))
        cards.append(row)
    return {**{key: planning[key] for key in ('title', 'status', 'faultCode', 'timeFrom', 'timeTo', 'timezone', 'groups')},
            'cards': cards, 'manualRelations': planning['relations']}


def canonical_additions(plan, results, question):
    """Bind directory additions to named candidates. An empty target never selects a page."""
    normalized = ' '.join(question.casefold().split())

    def mentioned(text):
        text = ' '.join(text.casefold().split())
        return len(text) >= 2 and re.search(r'(?<![a-z0-9])'+re.escape(text)+r'(?![a-z0-9])',normalized)

    material_types = {'drawing':r'图纸|\bdrawings?\b','object':r'工程对象|\bengineering objects?\b',
                      'document':r'文档|手册|\b(?:documents?|manuals?)\b','photo':r'照片|\bphotos?\b'}
    requested = {kind for kind, pattern in material_types.items() if re.search(pattern, question, re.I)}
    candidates = [row for row in results if row.get('selector') and (not requested or row['kind'] in requested)]
    exact = [row for row in candidates if mentioned(row['title']) or mentioned(row['identifier'])]
    for action in plan['actions']:
        if action['kind'] != 'add_results':
            continue
        if action['targets']:
            selected = result_targets(candidates, action['targets'])
            # The first planning call has no R keys. An invented alias cannot select a directory item.
            require_target(all(row in exact or row['identifier'] in action['targets'] for row in selected), 'result')
        else:
            require_target(len(exact)==1, 'result')
            selected = exact
        action['targets'] = [row['key'] for row in selected]


def edit_review(error, has_choices):
    if error.code == 'ASSISTANT_TARGET_AMBIGUOUS':
        target = getattr(error, 'target', 'instruction')
        messages = {
            'card': '',
            'group': '请在指令中写明要修改的分组名称。',
            'relation': '请在指令中写明连线两端的卡片名称。',
            'result': ('可从下方结果选择要加入的资料，也可在指令中写明名称或位号。'
                       if has_choices else '请在指令中写明要加入的资料名称或位号。'),
            'instruction': '请补充要修改的内容。',
        }
        return dict(target=target, message=messages[target])
    messages = {
        'ANALYSIS_HISTORY_READ_ONLY': ('card', '历史参考卡片为只读。请从当前画布选择卡片。'),
        'ASSISTANT_SOURCE_RELATION_READ_ONLY': ('relation', '可修改画布上的手工连线。请写明连线两端的卡片名称。'),
        'ASSISTANT_HISTORY_EMPTY': ('instruction', '当前没有对应的撤销或重做记录。'),
        'ASSISTANT_HISTORY_EXCLUSIVE': ('instruction', '请单独发送撤销、重做或恢复历史的指令。'),
        'ASSISTANT_SOURCE_MISMATCH': ('instruction', '请指定原卡片与同一来源的新版本。'),
        'ANALYSIS_CHANGED': ('instruction', '请指定当前画布中可恢复的一版历史。'),
        'ANALYSIS_SIZE_LIMIT': ('instruction', '这批操作超过画布容量，请缩小操作范围。'),
    }
    target, message = messages.get(error.code, ('instruction', '请补充具体的修改内容后再发送。'))
    return dict(target=target, message=message)


def equipment_configuration_question(value):
    """Only route an explicit catalogue lookup, leaving conversational requests to the planner."""
    query = re.fullmatch(r'(?:请)?(?:查询|查看|显示|列出)\s*(?:设备配置\s*[：:]\s*([^，,。？?\n]+)|([^，,。？?\n]*?)的?设备配置)[。？?]?',value.strip())
    if not query:
        english=re.fullmatch(r'(?:show|find|view) device configurations?(?: for ([^,.?\n]+))?[.?]?',value.strip(),re.IGNORECASE)
        return (english[1] or '').strip() if english and len(english[1] or '')<=200 else None
    term = (query[1] or query[2] or '').strip()
    return term if len(term)<=200 else None


def related_object_add_request(question):
    target = (r'(?:所有|全部)?(?:(?P<alarm>(?:当前|本次|这条|这个)?(?:故障)?报警)的?'
              r'(?:相关|关联|涉及)?的?|(?:当前画布的?)?(?:相关|关联)的?)(?:所有|全部)?工程对象')
    text = question.strip().rstrip('。！？!?')
    request = re.fullmatch(r'(?:请\s*)?(?:加入|添加)\s*'+target+r'\s*(?:(?:到|至)(?:当前)?画布[上中]?)?', text)
    if request is None:
        request = re.fullmatch(r'(?:请\s*)?(?:把|将)\s*'+target+r'\s*(?:加入|添加)(?:到|至)?(?:当前)?画布[上中]?', text)
    if request is None and re.fullmatch(r'(?:please )?add (?:the )?(?:related|associated) engineering objects(?: to (?:the )?canvas)?\.?',text,re.I):
        return 'canvas'
    return ('alarm' if request['alarm'] else 'canvas') if request else None


def contextual_addition(question):
    def scope(text):
        drawing, objects = drawing_add_scope(text), related_object_add_request(text)
        return drawing, objects, None if drawing or objects else assistant_alarm_materials.linked_add_scope(text)
    text = question.strip().removeprefix('先').strip()
    scopes = scope(text)
    if any(scopes):
        return (*scopes, False)
    clauses = re.split(r'[，,；;\n]|然后|并且|(?<!一)并|再', text, maxsplit=1)
    if len(clauses) == 2:
        scopes = scope(clauses[0])
    return (*scopes, any(scopes))


def replay_equipment_context(context, fixed, question):
    from . import simulated_faults
    if context.get('sourceConnectionId')!=simulated_faults.SOURCE_ID:
        return None
    # The selected alarm is an owned, fixed source on this canvas revision.
    if not any(ref['sourceKind']=='alarm' and all(descriptor.get(key)==context.get(key)
               for key in ('eventId','datasetId','datasetRevision')) for ref,descriptor in fixed):
        return None
    if not re.search(r'这台设备|这个(?:设备|柜体|柜)|(?:这条|本次|当前)(?:测试|模拟)?报警|(?:this|current) (?:equipment|cabinet|(?:test )?alarm)',question,re.I):
        return None
    return simulated_faults.dataset(context['datasetId'],context['datasetRevision'])


def snapshot(body, connection, project):
    from .analysis_drafts import validate_snapshot
    raw=body.get('snapshotJson')
    require(type(raw) is str and len(raw.encode())<=262144)
    try:value=json.loads(raw)
    except (ValueError,TypeError):require(False)
    validate_snapshot(value,connection,project)
    require(value['schemaVersion']==2)
    return value,hashlib.sha256(raw.encode()).hexdigest()


def draft_history(body,connection,project):
    raw=body.get('historyJson','{}')
    require(type(raw) is str and len(raw.encode())<=524288)
    try:value=json.loads(raw)
    except (ValueError,TypeError):require(False)
    require(type(value) is dict and set(value)<= {'undo','redo'})
    for item in value.values():
        snapshot(dict(snapshotJson=json.dumps(item,ensure_ascii=False)),connection,project)
    return value


def validate_plan(value, *, scene_directory=False, adopted_models=False, equipment_materials=False, processing_tasks=False,
                  equipment_configurations=False):
    require(type(value) is dict and set(value)=={'intent','queries','actions'},'ASSISTANT_OUTPUT_INVALID',502)
    require(value['intent'] in ('query','edit') and type(value['queries']) is list and len(value['queries'])<=2
        and type(value['actions']) is list and len(value['actions'])<=8,'ASSISTANT_OUTPUT_INVALID',502)
    require(value['intent']=='edit' or not value['actions'],'ASSISTANT_TOOL_NOT_ALLOWED',422)
    tools=set(QUERY_TOOLS)
    if scene_directory:tools.add('scenes')
    if adopted_models:tools.add('adopted_models')
    if equipment_materials:tools.add('equipment_materials')
    if processing_tasks:tools.add('processing_tasks')
    if equipment_configurations:tools.add('equipment_configurations')
    for q in value['queries']:
        require(type(q) is dict and set(q) in ({'tool','query','faultCode'},{'tool','query','faultCode','orderId'})
            and type(q['tool']) is str and q['tool'] in tools
            and all(type(q[k]) is str and len(q[k])<=200 for k in ('query','faultCode'))
            and type(q.get('orderId','')) is str and len(q.get('orderId',''))<=100,'ASSISTANT_TOOL_NOT_ALLOWED',422)
        if q['tool'] in ('scenes','adopted_models',*CATALOGUE_TOOLS):
            require(value['intent']=='query' and not q['faultCode'] and not q.get('orderId'),'ASSISTANT_TOOL_NOT_ALLOWED',422)
    for a in value['actions']:
        require(type(a) is dict and set(a)=={'kind','targets','text','x','y'} and a['kind'] in ACTIONS
            and type(a['targets']) is list and len(a['targets'])<=12 and all(type(t) is str and len(t)<=200 for t in a['targets'])
            and type(a['text']) is str and len(a['text'])<=4000
            and all(a[k] is None or type(a[k]) in (int,float) and -20000<=a[k]<=20000 for k in ('x','y')),
            'ASSISTANT_TOOL_NOT_ALLOWED',422)
    return value


def read_selected_evidence(tools, fixed):
    from .assistant_graph import material_summary

    receipts, skipped = [], {}
    for ref, descriptor in fixed:
        kind = ref['sourceKind']
        receipt = dict(evidenceRefId=ref['evidenceRefId'], kind=kind)
        receipts.append(receipt)
        if kind not in tools.allowed:
            state, reason = 'policy_excluded', 'ASSISTANT_TOOL_NOT_ALLOWED'
        else:
            try:
                if kind == 'alarm':
                    value = tools.alarm(descriptor)
                    material = dict(summary=summarize(tools.reader, kind, descriptor, tools.private, value=value))
                else:
                    material = tools.read(lambda: material_summary(tools.reader, kind, descriptor, tools.private))
                source = tools.source(kind, material.pop('summary'), sourceRevision=ref['sourceRevision'],
                                      evidenceRefId=ref['evidenceRefId'], descriptor=descriptor, **material)
                receipt.update(state='complete', sourceKey=source['key'],
                               metadataOnly=kind in ('drawing','photo','model') or kind=='document' and not descriptor.get('knowledgeNodeId'))
                continue
            except PreviewError as error:
                if error.status in (401,403):
                    raise
                state, reason = 'unavailable', error.code
        receipt.update(state=state, reason=reason)
        skipped[state,reason] = skipped.get((state,reason),0) + 1
    tools.trace.extend(dict(tool='selected_material',state=state,reason=reason,count=count)
                       for (state,reason),count in skipped.items())
    return receipts


class ProjectTools:
    def __init__(self,reader,guard,allowed,private):
        self.reader,self.guard,self.allowed,self.private=reader,guard,set(allowed),private
        self.reads=0;self.sources=[];self.results=[];self.graphs=[];self.trace=[]
        self.catalogue_observations=[]
        self.alarm_reads={}

    def read(self,operation):
        self.guard();self.reads+=1
        value=operation();self.guard();return value

    def alarm(self, descriptor):
        key=digest(descriptor)
        if key not in self.alarm_reads:
            self.alarm_reads[key]=self.read(lambda:self.reader.read('alarm',descriptor))
        return self.alarm_reads[key]

    def source(self,kind,summary,**fields):
        require(kind in self.allowed,'ASSISTANT_TOOL_NOT_ALLOWED',403)
        row=dict(key='E'+str(len(self.sources)+1),kind=kind,summary=summary,summaryHash=digest(summary),
                 availability='available',evidenceRefId='')
        row.update(fields)
        self.sources.append(row);return row

    def catalogue_source(self,kind,summary,observation):
        source=self.source(kind,summary)
        if source:
            self.catalogue_observations.append(dict(text=observation,refs=[source['key']]))

    def catalogue_answer(self):
        gaps=[]
        if any(trace['state']!='complete' for trace in self.trace):
            gaps.append(dict(text='有读取未完成。可在检索过程查看原因。',refs=[]))
        if any(trace.get('truncated') for trace in self.trace):
            gaps.append(dict(text='只显示本轮读取的范围。可按更具体的名称继续查找。',refs=[]))
        return dict(observations=self.catalogue_observations,hypotheses=[],gaps=gaps,nextSteps=[])

    def query(self,q,*,replay=None,drawings=False):
        reader=self.reader;tool=q['tool'];needle=q['query'];fault=q['faultCode']
        prefix=reader.reader.prefix
        if tool=='work_orders':
            require('work_order' in self.allowed,'ASSISTANT_TOOL_NOT_ALLOWED',403)
            order_id=q.get('orderId','')
            # An exact identity filter must not be narrowed by an LLM's prose restatement.
            literal='' if fault or order_id else needle
            result=self.read(lambda:reader.orders.assistant_search(dict(q=literal,faultCode=fault,orderId=order_id,cursor=0,limit=6,snapshotRevision=None)))
            rows=[]
            for item in result['items']:
                row=dict(key='R'+str(len(self.results)+1),kind='work_order',title=item['title'],
                    identifier=item['orderId'],version=item['orderRevision'],state=item['state'],faultCode=item['faultCode'],
                    simulated=item['sourceKind']=='simulated',reason='同故障代码 '+fault if fault else '项目工单检索',
                    selector=dict(orderId=item['orderId'],expectedOrderRevision=item['orderRevision']))
                self.results.append(row);rows.append(row)
            self.trace.append(dict(tool=tool,state='complete',count=len(rows),total=result['total'],
                nextCursor=result['nextCursor'],snapshotRevision=result['snapshotRevision'],filters={**q,'query':literal,'orderId':order_id}))
            text=json.dumps(dict(kind='work_order',scope='项目工单库，不限画布；同码不代表同根因；尚未加入画布',
                total=result['total'],truncated=result['nextCursor'] is not None,
                items=[dict(key=r['key'],orderId=r['identifier'],revision=r['version'],faultCode=r['faultCode'],simulated=r['simulated']) for r in rows]),ensure_ascii=False,separators=(',',':'))
            # Each candidate keeps its full identity/version in the structured result, outside the model summary.
            self.source('work_order',redact(text,self.private)[:1000])
            for item in result['items'][:2]:
                detail=self.read(lambda:reader.orders.detail(dict(orderId=item['orderId'])))
                require(detail['orderRevision']==item['orderRevision'],'WORK_ORDER_CHANGED',409)
                self.source('work_order',work_order_summary(detail,self.private),projectOrderId=item['orderId'],sourceRevision=str(item['orderRevision']))
        elif tool in ('objects','graph'):
            require('object' in self.allowed,'ASSISTANT_TOOL_NOT_ALLOWED',403)
            from .analysis_source_reader import matches_project_identifier
            def lookup(params):
                value=self.read(lambda:reader.reader._request('GET',prefix+'/objects?'+urlencode({**params,'limit':6})))
                require(value.get('projectCode')==reader.reader.project_code and type(value.get('items')) is list
                    and len(value['items'])<=6,'SOURCE_UNAVAILABLE',502)
                return value
            identifier=needle.strip()
            value=lookup(dict(primaryIdentifier=identifier)) if identifier else lookup(dict(q=''))
            exact=bool(identifier and value['items'])
            if exact:
                require(all(matches_project_identifier(item,identifier,reader.reader.project_code) for item in value['items']),
                    'SOURCE_CHANGED',409)
            elif identifier:
                value=lookup(dict(q=needle))
            items=value['items'];self.trace.append(dict(tool='objects',state='complete',count=len(items),nextCursor=value.get('nextCursor'),
                match='primary_identifier' if exact else 'name_or_identifier',filters=q))
            for item in items:
                self.results.append(dict(key='R'+str(len(self.results)+1),kind='object',title=item['displayName'],
                    identifier=item['entityUid'],version=item['entityRevision'],reason='项目名称或位号匹配，不确认安装身份',simulated=False,
                    selector=dict(entityUid=item['entityUid'],expectedEntityRevision=item['entityRevision'])))
            if tool=='graph' and len(items)==1 and value.get('nextCursor') is None:
                from .analysis_source_reader import selected
                from .assistant_graph import read_graph,graph_summary
                context=self.read(lambda:reader.reader.context_for_object(items[0]['entityUid'],items[0]['entityRevision']))
                graph=self.read(lambda:read_graph(reader,selected(context)))
                self.graphs.append(dict(kind='engineering',graph=graph))
                self.source('object',graph_summary(graph,lambda s:redact(s,self.private)),retrievalRevision=graph['revision'])
                self.trace.append(dict(tool='graph',state='complete',count=len(graph['relations']),truncated=graph['truncated']))
            else:
                self.source('object',redact(json.dumps(dict(scope='对象检索目录，尚未读取图谱；多结果需先明确目标',
                    items=[dict(name=r['displayName'],revision=r['entityRevision']) for r in items]),ensure_ascii=False),self.private)[:1000])
        elif tool=='materials':
            require('document' in self.allowed,'ASSISTANT_TOOL_NOT_ALLOWED',403)
            value=self.read(lambda:reader.reader._request('GET',prefix+'/documents?'+urlencode(dict(q=needle,status='active',limit=6))))
            for item in value['items']:
                if not item.get('current_version_id') or item.get('preview_kind') not in ('pdf','image'):continue
                photo=item.get('preview_kind')=='image'
                if photo and 'photo' not in self.allowed:continue
                selector=dict(documentId=item['id'],contentVersionId=item['current_version_id'])
                preview=dict(selector,title=item['name'])
                selector.update(dict(sourceType='project_document') if photo else dict(pageNumber=1))
                self.results.append(dict(key='R'+str(len(self.results)+1),kind='photo' if photo else 'document',title=item['name'],
                    identifier=item['id'],version=item['current_version_id'],reason='项目资料目录；未读取图面或全文',
                    simulated=False,selector=selector,documentPreview=preview))
            self.source('document',redact(json.dumps(dict(scope='资料目录元数据，未读取正文、图面或照片',
                names=[r['name'] for r in value['items']]),ensure_ascii=False),self.private)[:1000])
            self.trace.append(dict(tool=tool,state='complete',count=len(value['items']),nextCursor=value.get('next_cursor'),filters=q))
        elif tool=='knowledge':
            require('document' in self.allowed,'ASSISTANT_TOOL_NOT_ALLOWED',403)
            from .assistant_project_knowledge import query
            query(self,q)
        elif tool=='equipment_materials':
            from .assistant_device_materials import query
            query(self,needle,replay=replay,drawings=drawings)
        elif tool=='processing_tasks':
            from .assistant_processing import query
            query(self,needle)
        elif tool=='scenes':
            require('model' in self.allowed,'ASSISTANT_TOOL_NOT_ALLOWED',403)
            require(callable(reader.scene_listing),'SCENE_UNAVAILABLE',503)
            value=self.read(lambda:reader.scene_listing(needle))
            items=[]
            for scene in value['items']:
                key='R'+str(len(self.results)+1)
                revision=scene['headRevision']
                self.results.append(dict(key=key,kind='scene',title=scene['displayName'],identifier=scene['sceneId'],
                    version=revision,instanceCount=scene['instanceCount'],reason='当前项目活动场景',simulated=False))
                items.append(dict(name=redact(scene['displayName'],self.private)[:40],
                    version=revision.removeprefix('scene:')[:8],instances=scene['instanceCount']))
            scope='当前项目活动场景目录，仅读取已保存版本和实例数'
            truncated=value['nextCursor'] is not None
            self.trace.append(dict(tool=tool,state='complete',count=len(items),scope=scope,
                                   truncated=truncated,snapshotRevision=value['snapshotRevision']))
            summary=json.dumps(dict(scope=scope,more=truncated,items=items),ensure_ascii=False,separators=(',',':'))
            self.source('model',summary,retrievalRevision=value['snapshotRevision'])
        elif tool=='adopted_models':
            require('model' in self.allowed,'ASSISTANT_TOOL_NOT_ALLOWED',403)
            require(callable(reader.adopted_model_listing),'MODEL_UNAVAILABLE',503)
            from .assistant_project_models import SCOPE, summary
            value=self.read(lambda:reader.adopted_model_listing(needle))
            for row in value['items']:
                self.results.append(dict(row,key='R'+str(len(self.results)+1),kind='adopted_model',
                    reason='项目采用配置',simulated=False))
            self.trace.append(dict(tool=tool,state='complete',count=len(value['items']),total=value['total'],scope=SCOPE,
                truncated=value['truncated'] or value['sceneUsageTruncated'],snapshotRevision=value['snapshotRevision']))
            self.source('model',summary(value,self.private),retrievalRevision=value['snapshotRevision'])
        elif tool=='equipment_configurations':
            require({'object','model'}<=self.allowed,'ASSISTANT_TOOL_NOT_ALLOWED',403)
            require(callable(reader.equipment_configuration_listing),'MODEL_UNAVAILABLE',503)
            from .assistant_project_models import DEVICE_SCOPE
            value=self.read(lambda:reader.equipment_configuration_listing(needle))
            for row in value['items']:
                self.results.append(dict(row,key='R'+str(len(self.results)+1),kind='equipment_configuration',
                    reason='设备当前采用',simulated=False))
            count=len(value['items'])
            configured=sum(bool(item['configurationId']) for item in value['items'])
            self.trace.append(dict(tool=tool,state='complete',count=count,scope=DEVICE_SCOPE,
                truncated=value['truncated'],snapshotRevision=value['snapshotRevision']))
            message=f'本轮查到 {count} 台设备，其中 {configured} 台有已保存的采用配置。' if count else '本项目未查到匹配的安装设备。'
            self.catalogue_source('model',message,message)


def related_object_answer(tools, fixed, draft, scope, plan):
    from .analysis_object_recommendations import canvas_object_recommendations

    require('object' in tools.allowed, 'ASSISTANT_TOOL_NOT_ALLOWED', 403)
    current = {card['source']['id'] for card in draft['cards'] if card.get('source') and not card.get('historical')}
    selected = [(ref, descriptor) for ref, descriptor in fixed
                if ref['evidenceRefId'] in current and ref['sourceKind'] in tools.allowed]
    existing = {(descriptor['entityUid'], descriptor['expectedEntityRevision'])
                for ref, descriptor in selected if ref['sourceKind'] == 'object'}
    if scope == 'alarm':
        event_id = draft['context'].get('eventId')
        selected = [(ref, descriptor) for ref, descriptor in selected if ref['sourceKind'] == 'alarm'
                    and (not event_id or descriptor['eventId'] == event_id)]
    else:
        selected.sort(key=lambda source: source[0]['sourceKind'] != 'alarm')
    if not selected:
        message = ('请在画布资料中选用当前报警，再加入它关联的工程对象。' if scope == 'alarm'
                   else '请在画布资料中选用报警或其他来源卡片，再加入关联的工程对象。')
        return dict(observations=[], hypotheses=[], gaps=[dict(text=message, refs=[])], nextSteps=[])

    rows, gaps = canvas_object_recommendations(tools.reader, selected, read=tools.read)
    candidates = [row for row in rows if (row['selector']['entityUid'], row['selector']['expectedEntityRevision']) not in existing]
    for row in candidates[:12]:
        selector = row['selector']
        tools.results.append(dict(key=f'R{len(tools.results)+1}', kind='object', title=row['title'],
            identifier=selector['entityUid'], version=selector['expectedEntityRevision'],
            reason=row['reason'], simulated=False, selector=selector))
    count = len(candidates)
    if count:
        message = f'根据所选卡片的关联依据，找到 {count} 个可加入的工程对象。'
    elif rows and not gaps:
        message = '所选卡片的关联工程对象均已加入当前画布。'
    else:
        message = '本轮暂无可加入的已登记工程对象。'
    scope_label = '所选报警的对象关联与排查依据' if scope == 'alarm' else '所选画布卡片的关联依据'
    state = 'unavailable' if gaps else 'complete'
    tools.trace.append(dict(tool='objects', state=state, scope=scope_label, count=len(tools.results),
                            total=count, truncated=count>len(tools.results), **({'reason': gaps[0]} if gaps else {})))
    summary = redact(json.dumps(dict(scope=scope_label, total=count,
        items=[dict(key=row['key'], title=row['title'], version=row['version']) for row in tools.results]), ensure_ascii=False), tools.private)[:1000]
    tools.catalogue_source('object', summary, message)
    answer = tools.catalogue_answer()
    plan_candidate_additions(draft, plan, tools.results, answer, complete=not gaps and count==len(tools.results))
    return answer


def run(runtime,record,job,body,policy,service,prepare,authorize,source_call):
    import time
    run_id=record['id'];deadline=time.monotonic()+policy['policy']['seconds'];trace=[];usage={};calls=0
    def guard(force=False):
        require(not job.cancelled.is_set(),job.stop_code,409)
        require(time.monotonic()<deadline,'ASSISTANT_TIMEOUT',504)
        current=runtime.store.policy(job.project)
        require(current['revision']==policy['revision'] and current['policy']['enabled'],'ASSISTANT_POLICY_CHANGED',409)
        require(runtime.store.run(job.project,job.owner,run_id)['state']!='cancel_requested','ASSISTANT_CANCELLED',409)
        authorize(force)
    def model(phase,context,evidence,*,question=None):
        nonlocal calls
        guard(True)
        runtime.store.update(run_id,'model',progress=trace)
        result=source_call(dict(operationId=str(uuid4()),expectedAccessRevision=service['accessRevision'],
            question=redact(question if question is not None else body['question'],job.private)[:1000],
            evidence=evidence,workflow=dict(protocol=PROTOCOL,phase=phase,
                context=json.dumps(context,ensure_ascii=False,separators=(',',':')))),job.cancelled,deadline)
        guard(True);calls+=1
        require(result.get('modelCalls')==1 and result.get('engineeringConfirmation') is False,'ASSISTANT_OUTPUT_INVALID',502)
        for k,v in result.get('usage',{}).items():usage[k]=usage.get(k,0)+v
        return result
    tools=None
    try:
        draft,base=snapshot(body,runtime.store.connection_id,job.project)
        fixed,reader=prepare(guard)
        history=[]
        if record.get('conversation_id'):
            _,previous=runtime.store.conversation(job.project,job.owner,record['conversation_id'])
            history=[dict(question=json.loads(r['input_json'])['question'][:400],candidates=[{k:v for k,v in item.items() if k in ('identifier','version','faultCode','kind')} for item in (json.loads(r['result_json']).get('task',{}).get('results',[]) if r['result_json'] else [])][:6]) for r in previous if r['id']!=run_id][-3:]
        history_state=draft_history(body,runtime.store.connection_id,job.project)
        card_keys={c['id']:'C'+str(i+1) for i,c in enumerate(draft['cards'])}
        group_keys={g['id']:'G'+str(i+1) for i,g in enumerate(draft.get('frames',[]))}
        context=dict(faultCode=draft['context'].get('faultCode') or draft.get('reuse',{}).get('faultCode',''),mode=body['mode'],history=history,
            title=redact(draft['title'],job.private),status=draft['status'],savedRevision=body['expectedAnalysisRevision'],
            canUndo='undo' in history_state,canRedo='redo' in history_state,
            focusCards=[card_keys[card] for card in body.get('focusCardIds',[])],
            newCardKeys=['C'+str(len(draft['cards'])+i+1) for i in range(8)],
            timeFrom=draft['context']['timeFrom'],timeTo=draft['context']['timeTo'],timezone=draft['context']['timezone'],
            cards=[dict(key=card_keys[c['id']],kind=c['kind'],title=redact(c['title'],job.private)[:80],
                        pinned=c['pinned'],historical=c.get('historical',False),frame=group_keys.get(c.get('frameId')),
                        x=c['x'],y=c['y'],width=c['width'],height=c['height']) for c in draft['cards']],
            groups=[dict(key=group_keys[g['id']],title=redact(g['title'],job.private)[:80],
                         cards=[card_keys[c['id']] for c in draft['cards'] if c.get('frameId')==g['id']]) for g in draft.get('frames',[])],
            relations=[dict(key='L'+str(i+1),source=card_keys[r['from']],target=card_keys[r['to']],kind=r['kind'],origin=r['origin'],
                            reason=redact(r['reason'],job.private)[:64]) for i,r in enumerate(draft['relations'])])
        kinds=set(policy['policy']['allowedKinds'])
        allow_models='model' in kinds
        scene_directory=allow_models and callable(getattr(reader,'scene_listing',None))
        adopted_models=allow_models and callable(getattr(reader,'adopted_model_listing',None))
        equipment_materials='object' in kinds and bool({'document','photo'}&kinds)
        processing_tasks='document' in kinds
        equipment_configurations={'object','model'}<=kinds and callable(getattr(reader,'equipment_configuration_listing',None))
        if scene_directory:
            context['sceneDirectory']=True
        if adopted_models:
            context['adoptedModelDirectory']=True
        if equipment_materials:
            context['equipmentMaterials']=True
        if processing_tasks:
            context['processingTasks']=True
        equipment_query=equipment_configuration_question(body['question'])
        explicit_equipment=equipment_query is not None
        question=body['question']
        edit_question,disposition=turn_requests(question)
        switches=set(service.get('settings',{}).get('tools',('selected_sources','engineering_neighborhood','manual_fault_lookup')))
        drawing_scope,related_scope,linked,compound_add=contextual_addition(edit_question)
        alarm_materials=assistant_alarm_materials.alarm_material_add(edit_question)
        contextual_add=linked or related_scope or drawing_scope or alarm_materials
        if compound_add:
            context['relatedAddition']=(dict(kinds=sorted(linked.kinds),scope=linked.scope) if linked
                                        else dict(kind='drawing' if drawing_scope else 'object',scope=contextual_add))
        replay=replay_equipment_context(draft['context'],fixed,question) if equipment_materials and 'alarm' in kinds else None
        replay_materials=replay is not None and re.fullmatch(r'(?:请问\s*)?(?:这台设备|这个(?:设备|柜体|柜))\s*有(?:哪些)?\s*(?:图纸|说明书|资料)(?:和(?:图纸|说明书|资料))?[？?。]?',question.strip())
        if disposition and not edit_question:
            queries=[]
            if context['faultCode'] and 'work_order' in kinds and re.search(r'历史工单|同码工单|\bhistorical work orders?\b',question,re.I):
                queries.append(dict(tool='work_orders',query='',faultCode=context['faultCode']))
            if context['faultCode'] and 'document' in kinds and 'manual_fault_lookup' in switches and re.search(r'手册|知识库|\bmanuals?\b',question,re.I):
                queries.append(dict(tool='knowledge',query='',faultCode=context['faultCode']))
            proposed=dict(intent='query',queries=queries,actions=[])
        elif contextual_add and not compound_add:
            proposed=dict(intent='edit' if body['mode']=='workbench' else 'query',queries=[],actions=[])
        elif replay_materials and not explicit_equipment:
            proposed=dict(intent='query',queries=[dict(tool='equipment_materials',query=replay['primaryRds'],faultCode='')],actions=[])
        elif explicit_equipment:
            require(equipment_configurations,'ASSISTANT_TOOL_NOT_ALLOWED',403)
            proposed=dict(intent='query',queries=[dict(tool='equipment_configurations',query=equipment_query,faultCode='')],actions=[])
        else:
            proposed=model('plan',context,[],question=edit_question)['plan']
        plan=validate_plan(proposed,scene_directory=scene_directory,adopted_models=adopted_models,
                           equipment_materials=equipment_materials,processing_tasks=processing_tasks,
                           equipment_configurations=equipment_configurations)
        require(all(q['tool']!='graph' or 'engineering_neighborhood' in switches for q in plan['queries']), 'ASSISTANT_TOOL_NOT_ALLOWED',403)
        require(all(q['tool']!='knowledge' or 'manual_fault_lookup' in switches for q in plan['queries']), 'ASSISTANT_TOOL_NOT_ALLOWED',403)
        tools=ProjectTools(reader,guard,policy['policy']['allowedKinds'],job.private)
        if compound_add:
            plan['queries']=[]
        anchor=None
        if linked:
            anchor=assistant_alarm_materials.linked_anchor(fixed,draft,body,linked.scope,linked.kinds)
        elif alarm_materials:
            anchor=assistant_alarm_materials.alarm_anchor(fixed,draft,body)
        chosen=[item for item in fixed if item[0]['evidenceRefId'] in body['evidenceRefIds']]
        if anchor:
            chosen=[anchor]+[item for item in chosen if item!=anchor]
        needs_evidence=disposition or alarm_materials or (
            not explicit_equipment and not contextual_add and (plan['intent']=='query' or bool(plan['queries'])))
        prefer_selected=needs_evidence and (disposition or body.get('preferSelectedEvidence',False))
        selected_reads=read_selected_evidence(tools,chosen) if prefer_selected else []
        for q in plan['queries']:
            if (plan['intent']=='edit' and q['tool'] in ('objects','graph','materials') and not q['query'].strip()
                    and any(action['kind']=='add_results' for action in plan['actions'])):
                continue
            try:tools.query(q,replay=replay,drawings=bool(re.search(r'图纸|drawings?',question,re.I)))
            except PreviewError as error:
                if error.status in (401,403) or error.code in ('ASSISTANT_CANCELLED','ACCESS_CHANGED','SESSION_CHANGED','ASSISTANT_TIMEOUT'):raise
                tools.trace.append(dict(tool=q['tool'],state='unavailable',reason=error.code))
        if needs_evidence and not prefer_selected:
            selected_reads=read_selected_evidence(tools,chosen)
        addition_plan=dict(intent=plan['intent'],actions=[]) if compound_add else plan
        review=None
        if linked:
            if anchor:
                related_answer=assistant_alarm_materials.plan_addition(tools,fixed,draft,anchor,addition_plan,switches,
                                                                      linked=linked,analyze=disposition)
            else:
                relation='故障报警' if linked.scope=='alarm' else '故障报警或工程对象'
                has_source=any(card['kind'] in ('alarm','object') and not card.get('historical') for card in draft['cards'])
                if plan['intent']=='edit':
                    review=dict(target='card' if has_source else 'instruction',message=(
                        '请选择一张工程对象卡片，或在图纸中选中对象后点击「推荐照片」。'
                        if linked.scope=='canvas' and 'photo' in linked.kinds else
                        f'请选择一张{relation}卡片，再继续这条指令。' if has_source else
                        '请先在「加入资料」中添加一张故障报警或工程对象卡片。'))
                    plan['actions']=[]
                related_answer=tools.catalogue_answer()
        elif alarm_materials:
            related_answer=assistant_alarm_materials.plan_addition(tools,fixed,draft,anchor,plan,switches,analyze=disposition)
        elif drawing_scope:
            related_answer=drawing_answer(tools,fixed,draft,body,drawing_scope,addition_plan)
        else:
            related_answer=related_object_answer(tools,fixed,draft,related_scope,addition_plan) if related_scope else None
        if compound_add and plan['intent']=='edit' and not review:
            additions=[index for index,action in enumerate(plan['actions']) if action['kind']=='add_results']
            if len(additions)==1 and addition_plan['actions']:
                plan['actions'][additions[0]]=addition_plan['actions'][0]
            else:
                plan['actions']=[]
                related_answer['nextSteps'].append(dict(text='请先选定要加入的资料，再提交其余画布操作。',refs=[]))
        if plan['actions']:
            try:
                if not contextual_add:
                    canonical_additions(plan,tools.results,edit_question)
                validate_draft_plan(draft,plan,tools.results,fixed,history_state,body['expectedAnalysisRevision'],
                                    run_id,runtime.store.connection_id,job.project)
            except PreviewError as error:
                review=edit_review(error,any(row.get('selector') for row in tools.results))
                plan['actions']=[]
        if not review and plan['intent']=='edit' and not plan['actions'] and related_answer is None:
            review=dict(target='instruction',message='请补充具体的修改内容。')
        trace=[dict(key=t['tool'],state=t['state']) for t in tools.trace]
        runtime.store.update(run_id,'reading',progress=trace,sources=tools.sources)
        catalogue_query=explicit_equipment or body['taskId']=='query' and plan['queries'] and all(q['tool'] in CATALOGUE_TOOLS for q in plan['queries'])
        if disposition:
            if tools.sources:
                request=redact(question,job.private)[:1000-len(DISPOSITION_GUIDANCE)-2]+'\n\n'+DISPOSITION_GUIDANCE
                canvas=disposition_context(draft,context,selected_reads,job.private)
                def respond(evidence,aliases):
                    cards=[{key:value for key,value in card.items() if key!='evidence'} |
                           ({'evidence':aliases[card['evidence']]} if card.get('evidence') in aliases else {})
                           for card in canvas['cards']]
                    return model('answer',dict(scope='当前画布处置建议',canvas={**canvas,'cards':cards},
                                              tools=tools.trace),evidence,question=request)['answer']
                try:
                    answer=answer_batches(tools.sources,respond)
                except PreviewError as error:
                    if not plan['actions'] or not error.code.startswith((
                        'ASSISTANT_MODEL_', 'ASSISTANT_OUTPUT_', 'ASSISTANT_REFERENCE_')):
                        raise
                    tools.trace.append(dict(tool='disposition',state='unavailable',reason=error.code))
                    answer=dict(observations=[],hypotheses=[],gaps=[
                        dict(text='本轮关联资料已核对，生成处置建议时模型服务返回错误。',refs=[])],nextSteps=[])
                unread = sum(card.get('evidenceState','complete')!='complete' for card in canvas['cards'])
                if unread:
                    answer['gaps']=[dict(text=f'画布中有 {unread} 张来源卡片本轮未读取。可核对关键卡片后补充处置依据。',refs=[]),
                                    *answer['gaps'][:4]]
            else:
                answer=dict(observations=[],hypotheses=[],
                    gaps=[dict(text='本轮缺少可核对的报警、趋势或工程资料。',refs=[])],
                    nextSteps=[dict(text='先核对报警来源、发生时间和涉及的设备，再补充对应趋势或适用资料。',refs=[]),
                               dict(text='补齐依据后，按经核实的影响范围安排检查，并记录处置前后状态供复核。',refs=[])])
            if related_answer:
                for group in ('gaps','nextSteps'):
                    answer[group]=[*related_answer[group],*answer[group]][:5]
        elif review:
            answer=dict(observations=[],hypotheses=[],gaps=[],nextSteps=[])
        elif related_answer is not None or catalogue_query:
            answer=related_answer if related_answer is not None else tools.catalogue_answer()
        elif plan['intent']=='edit' and plan['actions']:
            message='已列出画布操作计划，尚未执行。' if body['mode']=='workbench' else '已列出画布操作建议，可转后台执行；驾驶舱未修改画布。'
            answer=dict(observations=[dict(text=message,refs=[])],hypotheses=[],gaps=[],nextSteps=[])
        elif tools.sources:
            answer=answer_batches(tools.sources,lambda evidence,_aliases:model(
                'answer',dict(scope='当前项目；尚未执行编辑',tools=tools.trace),evidence)['answer'])
        else:answer=dict(observations=[],hypotheses=[],gaps=[dict(text='本次未取得可引用的项目资料。请查看检索过程中的范围或服务状态。',refs=[])],nextSteps=[])
        trace=[dict(key=t['tool'],state=t['state']) for t in tools.trace]
        guard(True)
        result=dict(protocol=PROTOCOL,answer=answer,usage=usage,modelCalls=calls,engineeringConfirmation=False,
            partial=any(t['state']!='complete' or t.get('truncated') or t.get('nextCursor') is not None for t in tools.trace),
            model=dict(taskId=service.get('taskId','analysis'),provider=service.get('provider'),modelId=service.get('modelId')),
            task=dict(mode=body['mode'],baseDigest=base,plan=plan,results=tools.results,graphs=tools.graphs,trace=tools.trace,
                reads=tools.reads,selectedReads=selected_reads,receipts=[],
                execution='query_only' if body['mode']=='cockpit_query' else 'ready' if plan['actions'] else 'query',
                **({'editReview':review} if review else {}),
                **({'linkedAnchorRef':anchor[0]['evidenceRefId'] if anchor else None} if linked else {}),
                **({'disposition':True} if disposition else {})))
        require(runtime.store.finish(run_id,'partial' if result['partial'] else 'complete',result,trace,tools.sources),
                'ASSISTANT_CANCELLED',409)
    except PreviewError as error:
        runtime.store.update(run_id,'cancelled' if error.code=='ASSISTANT_CANCELLED' else 'failed',progress=trace,error=error.code)
    except Exception:
        runtime.store.update(run_id,'failed',error='ASSISTANT_INTERNAL_ERROR')
    finally:
        with runtime.lock:runtime.jobs.pop(run_id,None)
