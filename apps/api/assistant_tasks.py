"""Bounded project tools for the existing assistant runner, separate from Canvas membership."""
import hashlib
import json
from urllib.parse import urlencode
from uuid import uuid4

from .assistant_store import require, digest
from .assistant_summaries import redact, summarize, work_order_summary, validate_answer
from .authority import PreviewError

PROTOCOL='ontovis-engineering-tasks-v1'


def snapshot(body, connection, project):
    from .analysis_drafts import validate_snapshot
    raw=body.get('snapshotJson')
    require(type(raw) is str and len(raw.encode())<=262144)
    try:value=json.loads(raw)
    except (ValueError,TypeError):require(False)
    validate_snapshot(value,connection,project)
    require(value['schemaVersion']==2)
    return value,hashlib.sha256(raw.encode()).hexdigest()


def validate_plan(value):
    require(type(value) is dict and set(value)=={'intent','queries','actions'},'ASSISTANT_OUTPUT_INVALID',502)
    require(value['intent'] in ('query','edit') and type(value['queries']) is list and len(value['queries'])<=2
        and type(value['actions']) is list and len(value['actions'])<=8,'ASSISTANT_OUTPUT_INVALID',502)
    require(value['intent']=='edit' or not value['actions'],'ASSISTANT_TOOL_NOT_ALLOWED',422)
    for q in value['queries']:
        require(type(q) is dict and set(q)=={'tool','query','faultCode'} and q['tool'] in ('work_orders','objects','materials','graph','knowledge')
            and all(type(q[k]) is str and len(q[k])<=200 for k in ('query','faultCode')),'ASSISTANT_TOOL_NOT_ALLOWED',422)
    for a in value['actions']:
        require(type(a) is dict and set(a)=={'kind','targets','text','x','y'} and a['kind'] in
            ('add_results','remove_cards','add_note','arrange','rename','save','set_window','add_relation','move_card','resize_card')
            and type(a['targets']) is list and len(a['targets'])<=12 and all(type(t) is str and len(t)<=200 for t in a['targets'])
            and type(a['text']) is str and len(a['text'])<=4000
            and all(a[k] is None or type(a[k]) in (int,float) and -20000<=a[k]<=20000 for k in ('x','y')),
            'ASSISTANT_TOOL_NOT_ALLOWED',422)
    return value


class ProjectTools:
    def __init__(self,reader,guard,limit,allowed,private):
        self.reader,self.guard,self.limit,self.allowed,self.private=reader,guard,limit,set(allowed),private
        self.reads=0;self.sources=[];self.results=[];self.graphs=[];self.trace=[]

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

    def query(self,q):
        reader=self.reader;tool=q['tool'];needle=q['query'];fault=q['faultCode']
        prefix=reader.reader.prefix
        if tool=='work_orders':
            require('work_order' in self.allowed,'ASSISTANT_TOOL_NOT_ALLOWED',403)
            result=self.read(lambda:reader.orders.assistant_search(dict(q=needle,faultCode=fault,cursor=0,limit=6,snapshotRevision=None)))
            rows=[]
            for item in result['items']:
                row=dict(key='R'+str(len(self.results)+1),kind='work_order',title=item['title'],
                    identifier=item['orderId'],version=item['orderRevision'],state=item['state'],faultCode=item['faultCode'],
                    simulated=item['sourceKind']=='simulated',reason='同故障代码 '+fault if fault else '项目工单检索',
                    selector=dict(orderId=item['orderId'],expectedOrderRevision=item['orderRevision']))
                self.results.append(row);rows.append(row)
            self.trace.append(dict(tool=tool,state='complete',count=len(rows),total=result['total'],
                nextCursor=result['nextCursor'],snapshotRevision=result['snapshotRevision'],filters=q))
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
            value=self.read(lambda:reader.reader._request('GET',prefix+'/objects?'+urlencode(dict(q=needle,limit=6))))
            items=value['items'];self.trace.append(dict(tool='objects',state='complete',count=len(items),nextCursor=value.get('nextCursor'),filters=q))
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
                selector.update(dict(sourceType='project_document') if photo else dict(pageNumber=1))
                self.results.append(dict(key='R'+str(len(self.results)+1),kind='photo' if photo else 'document',title=item['name'],
                    identifier=item['id'],version=item['current_version_id'],reason='项目资料目录；未读取图面或全文',simulated=False,selector=selector))
            self.source('document',redact(json.dumps(dict(scope='资料目录元数据，未读取正文、图面或照片',
                names=[r['name'] for r in value['items']]),ensure_ascii=False),self.private)[:1000])
            self.trace.append(dict(tool=tool,state='complete',count=len(value['items']),nextCursor=value.get('next_cursor'),filters=q))
        elif tool=='knowledge':
            require('document' in self.allowed,'ASSISTANT_TOOL_NOT_ALLOWED',403)
            params=dict(q=needle or fault,limit=12)
            if fault and (not needle or needle==fault):params['kind']='FaultDefinition'
            value=self.read(lambda:reader.reader._request('GET',prefix+'/document-knowledge/graph?'+urlencode(params)))
            require(value.get('project_code')==reader.reader.project_code and type(value.get('nodes')) is list and len(value['nodes'])<=13
                and type(value.get('relations')) is list,'SOURCE_UNAVAILABLE',502)
            from .analysis_preview import literal
            self.graphs.append(dict(kind='knowledge',graph=value))
            nodes=[dict(title=literal(n,'title'),statement=literal(n,'statement'),kind=n['kind'],
                release=n.get('source',{}).get('release_id'),evidenceIds=n.get('payload',{}).get('evidence_ids',[])) for n in value['nodes']]
            self.source('document',redact(json.dumps(dict(scope='已发布项目文档知识；名称关联不等于电气连通或因果',nodes=nodes[:4],
                truncated=len(nodes)>4 or value.get('next_cursor') is not None),ensure_ascii=False),self.private)[:1000],retrievalRevision=digest(value))
            self.trace.append(dict(tool=tool,state='complete',count=len(value['nodes']),nextCursor=value.get('next_cursor'),filters=q))
            roots=[node for node in value['nodes'] if node.get('source') and node['kind']!='KnowledgeAssociation'
                   and (not fault or literal(node,'fault_code')==fault)]
            if len(roots)==1 and value.get('next_cursor') is None and self.limit-self.reads>=3:
                from .fixed_documents import FixedDocuments
                from .analysis_preview import node_evidence
                from .assistant_knowledge import read_neighborhood,summary
                source=roots[0]['source']
                fixed=dict(documentId=source['document']['id'],contentVersionId=source['version']['id'])
                metadata=self.read(lambda:FixedDocuments(reader.reader).metadata(fixed))
                fixed.update(sourceSha256=metadata['sourceSha256'],knowledgeReleaseId=source['release_id'],knowledgeNodeId=source['local_id'],pageNumber=1)
                proof=self.read(lambda:node_evidence(reader,fixed))
                pages=[p['selector'].get('page') for p in proof['items'] if type(p['selector'].get('page')) is int]
                require(pages,'SOURCE_UNAVAILABLE',502);fixed['pageNumber']=min(pages)
                graph=self.read(lambda:read_neighborhood(reader,fixed))
                text=summary(graph,fixed,lambda s:redact(s,self.private))
                source_row=self.source('document',text,descriptor=fixed,retrievalRevision=digest(graph))
                references={p['id']:p for p in graph['evidence']}
                edges=[]
                for edge in graph['relations']:
                    edge_pages=[references[e]['page'] for e in edge['evidenceIds'] if e in references]
                    edges.append(dict(id=edge['id'],source=edge['source'],target=edge['target'],type=edge['predicate'],status='document_rule',
                        provenance=dict(recordId=source['release_id']+'/'+edge['id'],recordRevision=digest(graph),**(dict(pageNumber=min(edge_pages)) if edge_pages else {}))))
                self.graphs.append(dict(kind='knowledge',graph={**graph,'relations':edges}))
                self.trace.append(dict(tool='fixed_manual_neighborhood',state='complete',count=len(edges),truncated=graph['truncated']))


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
        context=dict(faultCode=draft['context'].get('faultCode',''),mode=body['mode'],history=history,
            title=draft['title'],cards=[dict(key='C'+str(i+1),kind=c['kind'],title=c['title']) for i,c in enumerate(draft['cards'])])
        plan=validate_plan(model('plan',context,[])['plan'])
        switches=set(service.get('settings',{}).get('tools',('selected_sources','engineering_neighborhood','manual_fault_lookup')))
        require(all(q['tool']!='graph' or 'engineering_neighborhood' in switches for q in plan['queries']), 'ASSISTANT_TOOL_NOT_ALLOWED',403)
        require(all(q['tool']!='knowledge' or 'manual_fault_lookup' in switches for q in plan['queries']), 'ASSISTANT_TOOL_NOT_ALLOWED',403)
        tools=ProjectTools(reader,guard,policy['policy']['reads'],policy['policy']['allowedKinds'],job.private)
        for q in plan['queries']:
            try:tools.query(q)
            except PreviewError as error:
                if error.status in (401,403) or error.code in ('ASSISTANT_CANCELLED','ACCESS_CHANGED','SESSION_CHANGED','ASSISTANT_TIMEOUT'):raise
                tools.trace.append(dict(tool=q['tool'],state='unavailable',reason=error.code))
        # Project tools get the read budget first; selected cards supply remaining analysis context.
        for ref,descriptor in fixed:
            if tools.reads>=tools.limit or len(tools.sources)>=8:break
            if ref['sourceKind'] not in tools.allowed:continue
            try:
                from .assistant_graph import material_summary
                material=tools.read(lambda:material_summary(reader,ref['sourceKind'],descriptor,job.private))
                tools.source(ref['sourceKind'],material['summary'],sourceRevision=ref['sourceRevision'],
                    fixedEvidenceRefId=ref['evidenceRefId'],descriptor=descriptor,**{k:v for k,v in material.items() if k!='summary'})
            except PreviewError as error:
                if error.status in (401,403):raise
                tools.trace.append(dict(tool='selected_material',state='unavailable',reason=error.code))
        trace=[dict(key=t['tool'],state=t['state']) for t in tools.trace]
        runtime.store.update(run_id,'reading',progress=trace,sources=tools.sources)
        evidence=[{k:s[k] for k in ('key','kind','summary')} for s in tools.sources]
        if evidence:
            answer=validate_answer(model('answer',dict(scope='当前项目；尚未执行编辑',tools=tools.trace),evidence)['answer'],{s['key'] for s in evidence})
        else:answer=dict(observations=[],hypotheses=[],gaps=[dict(text='本次未取得可引用的项目资料。请查看检索过程中的范围或服务状态。',refs=[])],nextSteps=[])
        guard(True)
        result=dict(protocol=PROTOCOL,answer=answer,usage=usage,modelCalls=calls,engineeringConfirmation=False,partial=any(t['state']=='unavailable' for t in tools.trace),
            model=dict(taskId=service.get('taskId','analysis'),provider=service.get('provider'),modelId=service.get('modelId')),
            task=dict(mode=body['mode'],baseDigest=base,plan=plan,results=tools.results,graphs=tools.graphs,trace=tools.trace,
                reads=tools.reads,readLimit=tools.limit,receipts=[],execution='query_only' if body['mode']=='cockpit_query' else 'ready' if plan['actions'] else 'query'))
        require(runtime.store.finish(run_id,'partial' if result['partial'] else 'complete',result,trace,tools.sources),
                'ASSISTANT_CANCELLED',409)
    except PreviewError as error:
        runtime.store.update(run_id,'cancelled' if error.code=='ASSISTANT_CANCELLED' else 'failed',progress=trace,error=error.code)
    except Exception:
        runtime.store.update(run_id,'failed',error='ASSISTANT_INTERNAL_ERROR')
    finally:
        with runtime.lock:runtime.jobs.pop(run_id,None)
