"""Explicit project policies and a single bounded, owner-scoped analysis runner."""
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
import json
from threading import Event, Lock, Thread
import time
from urllib.parse import quote

from .authority import PreviewError
from .assistant_store import AssistantStore, ACTIVE, identifier, require, validate_policy
from .assistant_summaries import summarize, redact, validate_answer
from .assistant_graph import material_summary
from .assistant_retrieval import plan as retrieval_plan, retrieve
from .assistant_conversations import build_history
from .assistant_transport import call_source

@dataclass
class Job:
    sid: str
    project: str
    owner: str
    cancelled: Event = field(default_factory=Event)
    thread: object = None
    stop_code: str = 'ASSISTANT_CANCELLED'
    private: tuple = ()


class AssistantRuntime:
    def __init__(self, library, connection_id):
        self.store=AssistantStore(library,connection_id)
        self.lock=Lock();self.jobs={}

    def close(self):
        with self.lock:
            jobs=list(self.jobs.values())
            for job in jobs:job.cancelled.set()
        for job in jobs:
            if job.thread:job.thread.join(timeout=21)

    def cancel_session(self,sid):
        with self.lock:
            for job in self.jobs.values():
                if job.sid==sid:job.cancelled.set()

    def start(self,row,body,policy,service,prepare,authorize,source_call):
        project,owner=row['project'],row['owner']
        with self.lock:
            try:
                previous=self.store.by_request(project,owner,body['requestId'])
                from .assistant_store import digest
                require(previous['fingerprint']==digest(body),'ASSISTANT_REQUEST_CONFLICT',409)
                return self.store.public(previous)
            except PreviewError as error:
                if error.status!=404:raise
            require(len(self.jobs)<2 and not any(j.project==project and j.owner==owner for j in self.jobs.values()),'ASSISTANT_BUSY',429)
            record,created=self.store.begin(project,owner,body,policy['revision'],service['serviceRevision'])
            if not created:return self.store.public(record)
            job=Job(row['sid'],project,owner,private=tuple(row.get('private',(project,))));self.jobs[record['id']]=job
            thread=Thread(target=self._run,args=(record,job,body,policy,service,prepare,authorize,source_call),daemon=True)
            job.thread=thread;thread.start()
        return self.store.public(record)

    def _run(self,record,job,body,policy,service,prepare,authorize,source_call):
        run_id=record['id'];deadline=time.monotonic()+policy['policy']['seconds'];progress=[];summaries=[]
        def guard(force=False):
            require(not job.cancelled.is_set(),job.stop_code,409)
            require(time.monotonic()<deadline,'ASSISTANT_TIMEOUT',504)
            current=self.store.policy(job.project)['policy']
            require(current['enabled'] and current['reads']>=planned_operations
                and current['parallel']>=policy['policy']['parallel'] and current['seconds']>=policy['policy']['seconds']
                and set(policy['policy']['allowedKinds'])<=set(current['allowedKinds']), 'ASSISTANT_POLICY_CHANGED',409)
            require(self.store.run(job.project,job.owner,run_id)['state']!='cancel_requested','ASSISTANT_CANCELLED',409)
            authorize(force)
        planned_operations = len(body['evidenceRefIds'])
        try:
            guard(True)
            fixed,reader=prepare(guard)
            require(all(ref['sourceKind'] in policy['policy']['allowedKinds'] for ref,_ in fixed),'ASSISTANT_TOOL_NOT_ALLOWED',403)
            plans = retrieval_plan(fixed, body['question'], policy['policy']['reads'])
            planned_operations = sum(item['operations'] for item in plans)
            def one(index,item):
                ref,descriptor=item;guard()
                try:
                    material=retrieve(reader,ref['sourceKind'],descriptor,plans[index],job.private)
                    guard()
                    return {'key':f'E{index+1}','kind':ref['sourceKind'],**material,'evidenceRefId':ref['evidenceRefId'],
                        'sourceRevision':ref['sourceRevision'],'availability':'available'}
                except PreviewError as error:
                    if error.status in (401,403) or error.code.startswith('ASSISTANT_'):raise
                    return {'key':f'E{index+1}','kind':ref['sourceKind'],'evidenceRefId':ref['evidenceRefId'],
                        'sourceRevision':ref['sourceRevision'],'availability':'unavailable','reason':error.code}
            with ThreadPoolExecutor(max_workers=policy['policy']['parallel'],thread_name_prefix='ontovis-evidence') as pool:
                futures=[pool.submit(one,i,item) for i,item in enumerate(fixed)]
                try:
                    for future in as_completed(futures,timeout=max(0.1,deadline-time.monotonic())):
                        item=future.result();summaries.append(item);progress.append({'key':item['key'],'state':item['availability']})
                        guard();self.store.update(run_id,'reading',progress=progress,sources=sorted(summaries,key=lambda r:r['key']))
                finally:
                    for future in futures:future.cancel()
            guard(True);summaries.sort(key=lambda r:r['key'])
            available=[{k:r[k] for k in ('key','kind','summary')} for r in summaries if r['availability']=='available']
            require(bool(available),'ASSISTANT_NO_EVIDENCE',409)
            records=[]
            if record.get('conversation_id'):
                _,records=self.store.conversation(job.project,job.owner,record['conversation_id'],record['turn_no'])
            history,skipped=build_history(records,summaries,service['serviceRevision'],job.private)
            self.store.update(run_id,'model',sources=summaries)
            result=source_call({'operationId':run_id,'expectedServiceRevision':service['serviceRevision'],
                'expectedAccessRevision':service['accessRevision'],'question':redact(body['question'],job.private),
                'evidence':available,'history':history},job.cancelled,deadline)
            guard(True);self.store.update(run_id,'validating')
            require(result.get('serviceRevision')==service['serviceRevision'] and result.get('purpose')=='ontovis_analysis'
                    and result.get('modelCalls')==1 and result.get('engineeringConfirmation') is False,'ASSISTANT_OUTPUT_INVALID',502)
            answer=validate_answer(result.get('answer'),{r['key'] for r in available})
            result={'answer':answer,'usage':{k:v for k,v in result.get('usage',{}).items() if k in ('prompt_tokens','completion_tokens','total_tokens') and type(v) is int and 0<=v<=50000},
                'modelCalls':1,'engineeringConfirmation':False,'partial':len(available)!=len(summaries),
                'context':dict(includedTurns=len(history),skippedTurns=skipped)}
            guard(True)
            self.store.update(run_id,'partial' if result['partial'] else 'complete',result=result)
        except (PreviewError,FutureTimeout) as error:
            code=job.stop_code if job.cancelled.is_set() else error.code if isinstance(error,PreviewError) else 'ASSISTANT_TIMEOUT'
            state='cancelled' if code=='ASSISTANT_CANCELLED' else 'changed' if code in (
                'ACCESS_CHANGED','SESSION_CHANGED','SESSION_EXPIRED','FORBIDDEN','ASSISTANT_POLICY_CHANGED','ASSISTANT_CONFIGURATION_CHANGED') else 'failed'
            self.store.update(run_id,state,error=code)
        except Exception:
            self.store.update(run_id,'failed',error='ASSISTANT_INTERNAL_ERROR')
        finally:
            with self.lock:self.jobs.pop(run_id,None)


def request(sessions,sid,path,payload):
    action=path.removeprefix('/api/workbench/assistant/')
    require(action in ('policy','preview','history','publish','rollback','summary','start','status','cancel','graph','conversations','conversation',
                       'work-order-preview','work-order-apply'))
    row=sessions.current(sid,authenticated=True,touch=action not in ('policy','status'))
    require(payload.get('expectedSessionRevision')==row.revision,'SESSION_CHANGED',409)
    project=sessions._ref(payload.get('projectRef'));actor=identifier(row.subject_id)
    body={k:v for k,v in payload.items() if k not in ('projectRef','expectedSessionRevision')}
    if sessions.assistant is None:
        with sessions.registry.lock:
            if sessions.assistant is None:sessions.assistant=AssistantRuntime(sessions.shared.library,sessions.connection_id)
    runtime=sessions.assistant
    try:access=sessions._access(sid,row,project)
    except PreviewError:
        runtime.cancel_session(sid);raise
    prefix='/api/v1/projects/'+quote(project,safe='')+'/ontovis-assistant'
    lease=[0.0];lease_lock=Lock()
    def authorize(force=False):
        sessions.guard(sid,row)
        if not force and time.monotonic()-lease[0]<5:return
        with lease_lock:
            if not force and time.monotonic()-lease[0]<5:return
            current=sessions._access(sid,row,project)
            require(current['accessRevision']==access['accessRevision'],'ACCESS_CHANGED',409)
            sessions.guard(sid,row);lease[0]=time.monotonic()
    def service():
        value=row.authority.request('GET',prefix+'/service');authorize()
        require(value.get('serviceRef')=='ontobase-qwen-ontovis-v1' and value.get('purpose')=='ontovis_analysis'
            and type(value.get('serviceRevision')) is str and len(value['serviceRevision'])==64
            and value.get('accessRevision')==access['accessRevision'],'ASSISTANT_SERVICE_UNAVAILABLE',502)
        return value
    def reply(value):
        sessions.guard(sid,row)
        return {**value,'projectRef':payload['projectRef'],'sessionRevision':row.revision,'accessRevision':access['accessRevision']}
    if action in ('policy','history','preview'):
        require(set(body)==({'policy'} if action=='preview' else set()))
        current=runtime.store.policy(project)
        if action=='preview':current={**current,'policy':validate_policy(body['policy'])}
        try:available=service()
        except PreviewError as error:
            if error.status in (401,403):raise
            available={'enabled':False,'canRun':False,'reason':error.code}
        return reply({**current,'service':available,'canManage':access.get('role')=='admin',
            **({'items':runtime.store.history(project)} if action=='history' else {})})
    require(access.get('role')=='admin','ASSISTANT_RUN_FORBIDDEN',403)
    if action in ('publish','rollback'):
        require(set(body)=={'requestId','expectedRevision','expectedAccessRevision','expectedServiceRevision',
                              'restoreRevision' if action=='rollback' else 'policy'})
        previous=runtime.store.policy(project)['policy']
        enabled=body.get('policy',{}).get('enabled',True)
        try:selected=service()
        except PreviewError as error:
            if enabled or error.status not in (502,503,504):raise
            selected={'serviceRevision':None}
        require(body['expectedAccessRevision']==access['accessRevision'] and
            body['expectedServiceRevision']==selected['serviceRevision'],'ASSISTANT_CONFIGURATION_CHANGED',409)
        result=runtime.store.publish(project,actor,body,lambda:authorize(True))
        current=result['policy']
        if not current['enabled'] or not set(previous['allowedKinds'])<=set(current['allowedKinds']) or any(current[k]<previous[k] for k in ('reads','parallel','seconds')):
            with runtime.lock:
                for job in runtime.jobs.values():
                    if job.project==project:job.stop_code='ASSISTANT_POLICY_CHANGED';job.cancelled.set()
        return reply(result)
    def prepare(guard):
        require(sessions.analysis_store_id is not None,'ANALYSIS_NOT_ENABLED',503)
        require(sessions.analysis_slots.acquire(timeout=5),'ANALYSIS_BUSY',503)
        store=None
        try:
            from .analysis_drafts import AnalysisDrafts
            from .analysis_evidence import AnalysisEvidence
            store=AnalysisDrafts(sessions.analysis_database_url,sessions.connection_id,project)
            require(store.store_id==sessions.analysis_store_id,'ANALYSIS_STORE_SCOPE_MISMATCH',409)
            detail=store.detail(actor,body['analysisSessionId'],lambda:guard(),revision=body['expectedAnalysisRevision'])
            require(detail.get('lifecycle')=='active','ANALYSIS_TRASHED',409)
            evidence=AnalysisEvidence(store)
            fixed=[evidence.descriptor(actor,{'analysisSessionId':body['analysisSessionId'],'evidenceRefId':e},lambda:guard()) for e in body['evidenceRefIds']]
        finally:
            if store:store.close()
            sessions.analysis_slots.release()
        from .analysis_source_reader import AnalysisSourceReader
        from .scene_engineering import SceneEngineeringReader
        from .work_orders import WorkOrders
        workspace=sessions.registry.lookup(project);require(workspace is not None,'NOT_FOUND_OR_FORBIDDEN',404)
        local=sessions._workspace(workspace)
        orders=WorkOrders(local.library,project)
        reader=AnalysisSourceReader(SceneEngineeringReader(row.authority,sessions.connection_id,project,guard),
            sessions.shared.project_models,orders,guard,actor,scene_library=local.library)
        return fixed,reader
    if action in ('summary','start','graph'):
        common={'analysisSessionId','expectedAnalysisRevision','evidenceRefIds'}
        start=common|{'requestId','question','expectedPolicyRevision','expectedAccessRevision','expectedServiceRevision'}
        require(set(body) in ((common, common|{'question'}) if action == 'summary' else (common,) if action == 'graph' else (start,start|{'conversationId','expectedConversationVersion','parentRunId'})))
        identifier(body['analysisSessionId']);require(type(body['expectedAnalysisRevision']) is int and 1<=body['expectedAnalysisRevision']<=1000)
        ids=body['evidenceRefIds'];require(type(ids) is list and 1<=len(ids)<=8 and all(type(e) is str for e in ids) and len(set(ids))==len(ids))
        for e in ids:identifier(e)
        policy=runtime.store.policy(project);require(len(ids)<=policy['policy']['reads'],'ASSISTANT_READ_LIMIT',422)
        if action=='graph':
            require(len(ids)==1)
            fixed,reader=prepare(authorize);ref,descriptor=fixed[0]
            require(ref['sourceKind']=='object','ASSISTANT_TOOL_NOT_ALLOWED',403)
            from .assistant_graph import read_graph
            value=read_graph(reader,descriptor);authorize(True)
            return reply({'graph':value,'evidenceRefId':ref['evidenceRefId'],'modelCalls':0})
        if action=='summary':
            require(type(body.get('question','')) is str and len(body.get('question',''))<=1000)
            fixed,reader=prepare(authorize)
            plans=retrieval_plan(fixed,body.get('question',''),policy['policy']['reads'])
            def preview(item):
                i,(ref,descriptor)=item
                require(ref['sourceKind'] in policy['policy']['allowedKinds'],'ASSISTANT_TOOL_NOT_ALLOWED',403)
                return {'key':f'E{i+1}','kind':ref['sourceKind'],'evidenceRefId':ref['evidenceRefId'],
                    **retrieve(reader,ref['sourceKind'],descriptor,plans[i],(project,access.get('projectName')))}
            with ThreadPoolExecutor(max_workers=policy['policy']['parallel'],thread_name_prefix='ontovis-summary') as pool:
                result=list(pool.map(preview,enumerate(fixed)))
            authorize(True);return reply({'items':result,'modelCalls':0})
        require(type(body['question']) is str and 0<len(body['question'].strip())<=1000 and '\0' not in body['question'])
        require(policy['policy']['enabled'],'ASSISTANT_POLICY_DISABLED',409)
        selected=service();require(selected.get('canRun') is True,'ASSISTANT_RUN_FORBIDDEN',403)
        require(type(body['expectedPolicyRevision']) is int and body['expectedPolicyRevision']==policy['revision'] and body['expectedAccessRevision']==access['accessRevision']
            and body['expectedServiceRevision']==selected['serviceRevision'],'ASSISTANT_CONFIGURATION_CHANGED',409)
        return reply(runtime.start({'project':project,'owner':actor,'sid':sid,'private':(project,access.get('projectName'))},body,policy,selected,prepare,authorize,
            lambda data,cancelled,deadline:call_source(row.authority,prefix+'/analyze',data,cancelled,deadline)))
    if action=='conversations':
        require(set(body)=={'analysisSessionId','expectedAnalysisRevision'})
        prepare_body=body;body={**body,'evidenceRefIds':[]}
        try:prepare(authorize)
        finally:body=prepare_body
        authorize(True)
        return reply({'items':runtime.store.conversations(project,actor,body['analysisSessionId'],body['expectedAnalysisRevision'])})

    validation_cache={};read_count=[0]
    def visible(record):
        nonlocal body
        if record['state'] not in ('complete','partial'):
            # Even a failed turn belongs to a live, authorized analysis revision.
            original=body;body={**json.loads(record['input_json']),'evidenceRefIds':[]}
            try:prepare(authorize)
            except PreviewError as error:return {**runtime.store.public(record,hide=True),'state':'changed','error':error.code}
            finally:body=original
            return runtime.store.public(record)
        selected=service();current=runtime.store.policy(project)
        if not current['policy']['enabled'] or selected['serviceRevision']!=record['service_revision']:
            return {**runtime.store.public(record,hide=True),'state':'changed','error':'ASSISTANT_CONFIGURATION_CHANGED'}
        original=body;body=json.loads(record['input_json'])
        try:
            fixed,reader=prepare(authorize)
            require(len(fixed)<=current['policy']['reads'] and all(ref['sourceKind'] in current['policy']['allowedKinds'] for ref,_ in fixed),
                'ASSISTANT_POLICY_CHANGED',409)
            from .assistant_store import digest
            previous={v['evidenceRefId']:v for v in json.loads(record['sources_json'])}
            require(sum(previous.get(ref['evidenceRefId'],{}).get('retrieval',{}).get('plan',{}).get('operations',1) for ref,_ in fixed)<=current['policy']['reads'],'ASSISTANT_POLICY_CHANGED',409)
            for ref,descriptor in fixed:
                old=previous.get(ref['evidenceRefId'],{})
                selected_plan=old.get('retrieval',{}).get('plan')
                key=digest([ref['sourceKind'],descriptor,selected_plan])
                if key not in validation_cache:
                    require(read_count[0]<8,'ASSISTANT_HISTORY_SCOPE_LIMIT',409);read_count[0]+=1
                    validation_cache[key]=(retrieve(reader,ref['sourceKind'],descriptor,selected_plan,(project,access.get('projectName'))) if selected_plan else material_summary(reader,ref['sourceKind'],descriptor,(project,access.get('projectName'))))
                old=previous.get(ref['evidenceRefId'],{});value=validation_cache[key]
                if old.get('summaryHash'):
                    require(old['summaryHash']==value['summaryHash'] and old.get('retrievalRevision')==value.get('retrievalRevision'),
                        'ASSISTANT_HISTORY_SOURCES_CHANGED',409)
        except PreviewError as error:
            return {**runtime.store.public(record,hide=True),'state':'changed','error':error.code}
        finally:body=original
        return runtime.store.public(record)

    if action in ('work-order-preview', 'work-order-apply'):
        fields = {'runId', 'orderId'} if action == 'work-order-preview' else {
            'requestId', 'runId', 'orderId', 'expectedOrderRevision', 'expectedProposalSha256', 'items'}
        require(set(body) == fields)
        record = runtime.store.run(project, actor, body['runId'])
        transfer_policy_revision = runtime.store.policy(project)['revision']
        validated = visible(record)
        require(validated['state'] in ('complete', 'partial') and validated['result'] is not None,
                'ASSISTANT_TRANSFER_UNAVAILABLE', 409)
        require(runtime.store.policy(project)['revision'] == transfer_policy_revision, 'ASSISTANT_POLICY_CHANGED', 409)
        from .assistant_work_orders import proposal
        from .work_orders import WorkOrders
        proposed = proposal(validated)
        workspace = sessions.registry.lookup(project)
        require(workspace is not None, 'NOT_FOUND_OR_FORBIDDEN', 404)
        orders = WorkOrders(sessions._workspace(workspace).library, project)
        if action == 'work-order-preview':
            detail = orders.detail({'orderId': body['orderId']})
            adopted = [item['sourceItemId'] for transfer in detail.get('assistantTransfers', [])
                       if transfer['runId'] == record['id'] for item in transfer['items']]
            authorize(True)
            return reply({'proposal': proposed, 'order': detail, 'adoptedItemIds': adopted, 'modelCalls': 0})
        # Serialize new references with analysis deletion; fixed revisions never change.
        from .analysis_drafts import AnalysisDrafts, WRITE_LOCK
        require(sessions.analysis_slots.acquire(timeout=5), 'ANALYSIS_BUSY', 503)
        store = None
        try:
            store = AnalysisDrafts(sessions.analysis_database_url, sessions.connection_id, project)
            require(store.store_id == sessions.analysis_store_id, 'ANALYSIS_STORE_SCOPE_MISMATCH', 409)
            with store.connection.transaction() as cursor:
                cursor.execute('select pg_advisory_xact_lock(%s)', (WRITE_LOCK,))
                store._session(cursor, record['analysis_id'], actor, active=True)
                _, fixed = store._revision(cursor, record['analysis_id'], record['analysis_revision'])
                def transfer_guard():
                    authorize(True)
                    store._session(cursor, record['analysis_id'], actor, active=True)
                    require(runtime.store.policy(project)['revision'] == transfer_policy_revision,
                            'ASSISTANT_POLICY_CHANGED', 409)
                    available = service()
                    require(available.get('canRun') is True and available['serviceRevision'] == record['service_revision'],
                            'ASSISTANT_CONFIGURATION_CHANGED', 409)
                    current = runtime.store.run(project, actor, record['id'])
                    require(current['version'] == record['version'] and current['state'] in ('complete', 'partial'),
                            'ASSISTANT_RUN_CHANGED', 409)
                value = orders.apply_assistant(body, actor, transfer_guard, proposed, {'contentSha256': fixed[1]})
        finally:
            if store: store.close()
            sessions.analysis_slots.release()
        return reply({**value, 'modelCalls': 0})

    if action=='conversation':
        require(set(body) in ({'conversationId'},{'conversationId','beforeTurn'}))
        head,records=runtime.store.conversation(project,actor,body['conversationId'],body.get('beforeTurn'))
        # Validate latest turns first; shared sources are read once within the eight-material budget.
        items=list(reversed([visible(r) for r in reversed(records)]))
        authorize(True)
        return reply({**head,'items':items,'hasEarlier':bool(records and records[0]['turn_no']>1)})

    require(set(body)==({'runId','expectedVersion'} if action=='cancel' else {'runId'} if 'runId' in body else {'requestId'}))
    record=runtime.store.run(project,actor,body['runId']) if 'runId' in body else runtime.store.by_request(project,actor,body['requestId'])
    if action=='cancel':
        record=runtime.store.cancel(project,actor,record['id'],body['expectedVersion'])
        with runtime.lock:
            job=runtime.jobs.get(record['id'])
            if job:job.cancelled.set()
    result=visible(record);authorize(True);return reply(result)
