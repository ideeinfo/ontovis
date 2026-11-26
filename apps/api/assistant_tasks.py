"""Bounded project tools for the existing assistant runner, separate from Canvas membership."""
import hashlib
import json
import re
from urllib.parse import urlencode
from uuid import uuid4

from .assistant_store import require, digest
from .assistant_summaries import redact, summarize, work_order_summary, validate_answer
from .authority import PreviewError
from .assistant_canvas_tasks import ACTIONS

PROTOCOL='ontovis-engineering-tasks-v1'
QUERY_TOOLS=('work_orders','objects','materials','graph','knowledge')
CATALOGUE_TOOLS=('equipment_materials','processing_tasks','equipment_configurations')


def equipment_configuration_question(value):
    """Only route an explicit catalogue lookup, leaving conversational requests to the planner."""
    query = re.fullmatch(r'(?:请)?(?:查询|查看|显示|列出)\s*(?:设备配置\s*[：:]\s*([^，,。？?\n]+)|([^，,。？?\n]*?)的?设备配置)[。？?]?',value.strip())
    if not query:
        english=re.fullmatch(r'(?:show|find|view) device configurations?(?: for ([^,.?\n]+))?[.?]?',value.strip(),re.IGNORECASE)
        return (english[1] or '').strip() if english and len(english[1] or '')<=200 else None
    term = (query[1] or query[2] or '').strip()
    return term if len(term)<=200 else None


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
        elif tools.reads >= tools.limit or len(tools.sources) >= 8:
            state, reason = 'budget_limited', 'ASSISTANT_READ_LIMIT'
        else:
            try:
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
    def __init__(self,reader,guard,limit,allowed,private):
        self.reader,self.guard,self.limit,self.allowed,self.private=reader,guard,limit,set(allowed),private
        self.reads=0;self.sources=[];self.results=[];self.graphs=[];self.trace=[]
        self.catalogue_observations=[]

    def read(self,operation):
        self.guard();require(self.reads<self.limit,'ASSISTANT_READ_LIMIT',409);self.reads+=1
        value=operation();self.guard();return value

    def source(self,kind,summary,**fields):
        require(kind in self.allowed,'ASSISTANT_TOOL_NOT_ALLOWED',403)
        if len(self.sources)>=8:return None
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
                if self.reads>=self.limit:break
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
    def model(phase,context,evidence):
        nonlocal calls
        guard(True);require(calls<3,'ASSISTANT_READ_LIMIT',409)
        runtime.store.update(run_id,'model',progress=trace)
        result=source_call(dict(operationId=str(uuid4()),expectedAccessRevision=service['accessRevision'],question=body['question'],
            evidence=evidence,workflow=dict(protocol=PROTOCOL,phase=phase,context=json.dumps(context,ensure_ascii=False))),job.cancelled,deadline)
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
        context=dict(faultCode=draft['context'].get('faultCode') or draft.get('reuse',{}).get('faultCode',''),mode=body['mode'],history=history,
            title=draft['title'],savedRevision=body['expectedAnalysisRevision'],canUndo='undo' in history_state,canRedo='redo' in history_state,
            newCardKeys=['C'+str(len(draft['cards'])+i+1) for i in range(8)],
            timeFrom=draft['context']['timeFrom'],timeTo=draft['context']['timeTo'],timezone=draft['context']['timezone'],
            cards=[dict(key=card_keys[c['id']],kind=c['kind'],title=c['title'][:80],pinned=c['pinned'],historical=c.get('historical',False),
                        frame=c.get('frameId'),x=c['x'],y=c['y'],width=c['width'],height=c['height']) for c in draft['cards']],
            groups=[dict(key='G'+str(i+1),title=g['title'][:80],cards=[card_keys[c['id']] for c in draft['cards'] if c.get('frameId')==g['id']]) for i,g in enumerate(draft.get('frames',[]))],
            relations=[dict(key='L'+str(i+1),source=card_keys[r['from']],target=card_keys[r['to']],kind=r['kind'],origin=r['origin']) for i,r in enumerate(draft['relations'])])
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
        replay=replay_equipment_context(draft['context'],fixed,question) if equipment_materials and 'alarm' in kinds else None
        replay_materials=replay is not None and re.fullmatch(r'(?:请问\s*)?(?:这台设备|这个(?:设备|柜体|柜))\s*有(?:哪些)?\s*(?:图纸|说明书|资料)(?:和(?:图纸|说明书|资料))?[？?。]?',question.strip())
        if replay_materials and not explicit_equipment:
            proposed=dict(intent='query',queries=[dict(tool='equipment_materials',query=replay['primaryRds'],faultCode='')],actions=[])
        elif explicit_equipment:
            require(equipment_configurations,'ASSISTANT_TOOL_NOT_ALLOWED',403)
            proposed=dict(intent='query',queries=[dict(tool='equipment_configurations',query=equipment_query,faultCode='')],actions=[])
        else:
            proposed=model('plan',context,[])['plan']
        plan=validate_plan(proposed,scene_directory=scene_directory,adopted_models=adopted_models,
                           equipment_materials=equipment_materials,processing_tasks=processing_tasks,
                           equipment_configurations=equipment_configurations)
        switches=set(service.get('settings',{}).get('tools',('selected_sources','engineering_neighborhood','manual_fault_lookup')))
        require(all(q['tool']!='graph' or 'engineering_neighborhood' in switches for q in plan['queries']), 'ASSISTANT_TOOL_NOT_ALLOWED',403)
        require(all(q['tool']!='knowledge' or 'manual_fault_lookup' in switches for q in plan['queries']), 'ASSISTANT_TOOL_NOT_ALLOWED',403)
        tools=ProjectTools(reader,guard,policy['policy']['reads'],policy['policy']['allowedKinds'],job.private)
        prefer_selected=body.get('preferSelectedEvidence',False) and not explicit_equipment
        selected_reads=read_selected_evidence(tools,fixed) if prefer_selected else []
        for q in plan['queries']:
            try:tools.query(q,replay=replay,drawings=bool(re.search(r'图纸|drawings?',question,re.I)))
            except PreviewError as error:
                if error.status in (401,403) or error.code in ('ASSISTANT_CANCELLED','ACCESS_CHANGED','SESSION_CHANGED','ASSISTANT_TIMEOUT'):raise
                state='budget_limited' if error.code=='ASSISTANT_READ_LIMIT' else 'unavailable'
                tools.trace.append(dict(tool=q['tool'],state=state,reason=error.code))
        if not prefer_selected and not explicit_equipment:
            selected_reads=read_selected_evidence(tools,fixed)
        trace=[dict(key=t['tool'],state=t['state']) for t in tools.trace]
        runtime.store.update(run_id,'reading',progress=trace,sources=tools.sources)
        evidence=[{k:s[k] for k in ('key','kind','summary')} for s in tools.sources]
        catalogue_query=explicit_equipment or body['taskId']=='query' and plan['queries'] and all(q['tool'] in CATALOGUE_TOOLS for q in plan['queries'])
        if catalogue_query:
            answer=tools.catalogue_answer()
        elif evidence:
            answer=validate_answer(model('answer',dict(scope='当前项目；尚未执行编辑',tools=tools.trace),evidence)['answer'],{s['key'] for s in evidence})
        elif plan['intent']=='edit' and plan['actions'] and not plan['queries']:
            message='已列出画布操作计划，尚未执行。' if body['mode']=='workbench' else '已列出画布操作建议，可转后台执行；驾驶舱未修改画布。'
            answer=dict(observations=[dict(text=message,refs=[])],hypotheses=[],gaps=[],nextSteps=[])
        else:answer=dict(observations=[],hypotheses=[],gaps=[dict(text='本次未取得可引用的项目资料。请查看检索过程中的范围或服务状态。',refs=[])],nextSteps=[])
        guard(True)
        result=dict(protocol=PROTOCOL,answer=answer,usage=usage,modelCalls=calls,engineeringConfirmation=False,
            partial=any(t['state']!='complete' or t.get('truncated') or t.get('nextCursor') is not None for t in tools.trace),
            model=dict(taskId=service.get('taskId','analysis'),provider=service.get('provider'),modelId=service.get('modelId')),
            task=dict(mode=body['mode'],baseDigest=base,plan=plan,results=tools.results,graphs=tools.graphs,trace=tools.trace,
                reads=tools.reads,readLimit=tools.limit,selectedReads=selected_reads,receipts=[],
                execution='query_only' if body['mode']=='cockpit_query' else 'ready' if plan['actions'] else 'query'))
        require(runtime.store.finish(run_id,'partial' if result['partial'] else 'complete',result,trace,tools.sources),
                'ASSISTANT_CANCELLED',409)
    except PreviewError as error:
        runtime.store.update(run_id,'cancelled' if error.code=='ASSISTANT_CANCELLED' else 'failed',progress=trace,error=error.code)
    except Exception:
        runtime.store.update(run_id,'failed',error='ASSISTANT_INTERNAL_ERROR')
    finally:
        with runtime.lock:runtime.jobs.pop(run_id,None)
