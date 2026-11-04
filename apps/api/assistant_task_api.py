"""HTTP boundary for project tasks and server-authorized draft receipts."""
import copy
import json
from uuid import uuid4
from .assistant_store import require,identifier,digest,encoded
from .assistant_tasks import PROTOCOL,snapshot,ProjectTools
from .assistant_transport import call_source


def handle(action,body,sessions,row,sid,project,actor,access,runtime,service,prepare,authorize,prefix):
    if action=='task-start':
        fields={'protocol','mode','snapshotJson','analysisSessionId','expectedAnalysisRevision','evidenceRefIds','requestId','question',
            'conversationId','expectedConversationVersion','parentRunId','expectedPolicyRevision','expectedAccessRevision','expectedServiceRevision','taskId'}
        require(set(body)==fields and body['protocol']==PROTOCOL and body['mode'] in ('workbench','cockpit_query'))
        identifier(body['analysisSessionId']);identifier(body['requestId'])
        require(type(body['expectedAnalysisRevision']) is int and 0<=body['expectedAnalysisRevision']<=1000)
        require(type(body['question']) is str and 0<len(body['question'].strip())<=1000 and '\0' not in body['question'])
        require(body['taskId'] in ('analysis','query','work_order'))
        ids=body['evidenceRefIds'];require(type(ids) is list and len(ids)<=8 and len(set(ids))==len(ids))
        for item in ids:identifier(item)
        board,_=snapshot(body,sessions.connection_id,project)
        if body['expectedAnalysisRevision']==0:
            require(not ids and all(c['kind']=='analysis' for c in board['cards']) and not board['context']['objectIds'])
        else:
            require(set(ids)<=set(c.get('source',{}).get('id') for c in board['cards']))
            with analysis_store(sessions,project) as store:
                detail=store.detail(actor,body['analysisSessionId'],lambda:authorize(True),revision=body['expectedAnalysisRevision'])
                require(detail.get('lifecycle')=='active','ANALYSIS_TRASHED',409)
                from .analysis_canvas import validate_handles
                with store.connection.transaction(readonly=True) as cursor:validate_handles(cursor,body['analysisSessionId'],board,store.schema_version)
        policy=runtime.store.policy(project);require(policy['policy']['enabled'],'ASSISTANT_POLICY_DISABLED',409)
        selected=service(body['taskId']);require(selected.get('canRun'),selected.get('reason') or 'ASSISTANT_RUN_FORBIDDEN',403)
        require(body['expectedAccessRevision']==access['accessRevision'] and body['expectedPolicyRevision']==policy['revision']
            and body['expectedServiceRevision']==selected['serviceRevision'],'ASSISTANT_CONFIGURATION_CHANGED',409)
        settings=selected['settings'];policy={**policy,'policy':{**policy['policy'],'reads':min(policy['policy']['reads'],settings['readLimit']),
            'parallel':min(policy['policy']['parallel'],settings['readParallel'])}}
        def invoke(data,cancelled,deadline):
            authorize(True);latest=service(body['taskId'])
            require(latest.get('canRun') and latest['serviceRevision']==selected['serviceRevision'],'ASSISTANT_CONFIGURATION_CHANGED',409)
            source_body={**data,'expectedServiceRevision':selected['sourceServiceRevision']}
            if selected.get('configuration'):source_body['configuration']=selected['configuration']
            value=call_source(row.authority,prefix+'/analyze',source_body,cancelled,deadline)
            require(value.get('serviceRevision')==selected['sourceServiceRevision'] and value.get('purpose')=='ontovis_analysis','ASSISTANT_CONFIGURATION_CHANGED',409)
            authorize(True);require(service(body['taskId'])['serviceRevision']==selected['serviceRevision'],'ASSISTANT_CONFIGURATION_CHANGED',409)
            return value
        return runtime.start(dict(project=project,owner=actor,sid=sid,private=(project,access.get('projectName'))),body,policy,selected,
                             lambda guard:prepare(guard,body),authorize,invoke)

    record=runtime.store.run(project,actor,body.get('runId'));original=json.loads(record['input_json'])
    require(original.get('protocol')==PROTOCOL and record['state'] in ('complete','partial') and record['result_json'],
            'ASSISTANT_TRANSFER_UNAVAILABLE',409)
    result=json.loads(record['result_json']);task=result['task']
    authorize(True)
    require(runtime.store.policy(project)['revision']==record['policy_revision'],'ASSISTANT_POLICY_CHANGED',409)
    selected=service(original['taskId'])
    require(selected.get('canRun') and selected['serviceRevision']==record['service_revision'],'ASSISTANT_CONFIGURATION_CHANGED',409)
    if action=='task-page':
        require(set(body)=={'runId','traceIndex'})
        index=body['traceIndex'];require(type(index) is int and 0<=index<len(task['trace']))
        trace=task['trace'][index];require(trace['tool']=='work_orders' and trace.get('nextCursor') is not None)
        _,reader=prepare(authorize,original)
        value=reader.orders.assistant_search(dict(q=trace['filters']['query'],faultCode=trace['filters']['faultCode'],
            cursor=trace['nextCursor'],limit=6,snapshotRevision=trace['snapshotRevision']))
        require(len(task['results'])+len(value['items'])<=50,'ASSISTANT_READ_LIMIT',409)
        for item in value['items']:
            task['results'].append(dict(key='R'+str(len(task['results'])+1),kind='work_order',title=item['title'],identifier=item['orderId'],
                version=item['orderRevision'],state=item['state'],faultCode=item['faultCode'],simulated=item['sourceKind']=='simulated',
                reason='同故障代码 '+trace['filters']['faultCode'] if trace['filters']['faultCode'] else '项目工单检索',
                selector=dict(orderId=item['orderId'],expectedOrderRevision=item['orderRevision'])))
        trace.update(nextCursor=value['nextCursor'],count=trace['count']+len(value['items']))
        authorize(True);runtime.store.update(record['id'],record['state'],result=result)
        return runtime.store.public(runtime.store.run(project,actor,record['id']))

    require(task['mode']=='workbench','ASSISTANT_QUERY_ONLY',403)
    from . import assistant_canvas_tasks as operations
    keys=body.get('selectedKeys');require(type(keys) is list and len(keys)<=12 and len(set(keys))==len(keys) and all(type(k) is str for k in keys))
    selection=digest(sorted(keys));prior=operations.load(runtime.store.library,record['id'],selection)
    if action=='task-ack':
        require(set(body)=={'runId','selectedKeys','snapshotJson','savedRevision'})
        require(prior is not None,'NOT_FOUND_OR_FORBIDDEN',404)
        prepared=json.loads(prior['prepared_json']);board,_=snapshot(body,sessions.connection_id,project)
        require(board==prepared['snapshot'],'ASSISTANT_DRAFT_CHANGED',409)
        saved=body['savedRevision'];require(saved is None or type(saved) is int and 1<=saved<=1000)
        if saved is not None:
            with analysis_store(sessions,project) as store:
                detail=store.detail(actor,prepared['analysis']['analysisSessionId'],lambda:authorize(True))
                require(detail['analysisRevision']==saved and detail['snapshot']==board,'ANALYSIS_CHANGED',409)
        receipt=dict(operationId=prepared['operationId'],state='saved' if saved is not None else 'applied_draft',saveRequested=prepared['wantsSave'],
            analysisSessionId=prepared['analysis']['analysisSessionId'],analysisRevision=saved or prepared['analysis']['analysisRevision'],
            snapshotSha256=digest(board),items=prepared['receipts'])
        receipt=operations.acknowledge(runtime.store.library,record['id'],selection,receipt)
        task['receipts']=[r for r in task['receipts'] if r['operationId']!=receipt['operationId']]+[receipt]
        runtime.store.update(record['id'],record['state'],result=result)
        return dict(receipt=receipt,run=runtime.store.public(runtime.store.run(project,actor,record['id'])))

    require(set(body)=={'runId','selectedKeys','snapshotJson'})
    board,base=snapshot(body,sessions.connection_id,project)
    require(base==task['baseDigest'],'ASSISTANT_DRAFT_CHANGED',409)
    if prior and prior.get('ack_json'):
        return {**json.loads(prior['prepared_json']),'alreadyApplied':True}
    if prior:
        require(prior['base_digest']==base,'ASSISTANT_REQUEST_CONFLICT',409)
    choices=task['results'];plan=copy.deepcopy(task['plan'])
    if keys:
        require(set(keys)<=set(r['key'] for r in choices),'ASSISTANT_TARGET_AMBIGUOUS',409)
        plan=dict(intent='edit',queries=[],actions=[dict(kind='add_results',targets=keys,text='',x=None,y=None)])
    require(plan['intent']=='edit' and plan['actions'],'ASSISTANT_TOOL_NOT_ALLOWED',403)
    _,reader=prepare(authorize,original)
    # A retained preparation is not a grant to use a now-stale source version.
    if prior:
        for candidate in choices:
            if any(a['kind']=='add_results' and (not a['targets'] or candidate['key'] in a['targets'] or candidate['identifier'] in a['targets']) for a in plan['actions']):
                reader.resolve(candidate['kind'],candidate['selector'])
        return json.loads(prior['prepared_json'])
    with runtime.lock:
        prior=operations.load(runtime.store.library,record['id'],selection)
        if prior:return json.loads(prior['prepared_json'])
        with analysis_store(sessions,project) as store:
            analysis_id=original['analysisSessionId'];revision=original['expectedAnalysisRevision'];baseline=None
            if revision==0:
                baseline=copy.deepcopy(board);baseline.update(cards=[],relations=[])
                baseline['context']={k:v for k,v in board['context'].items() if k in ('objectIds','timeFrom','timeTo','timezone')}
                created=store.write(actor,access['role'],'create',dict(requestId=operations.operation_id(record['id'],'container'),snapshot=baseline),lambda:authorize(True))
                analysis_id=created['analysisSessionId'];revision=created['analysisRevision']
                # Bind the formerly unsaved conversation to its new private container.
                with runtime.store.library.connect() as db:
                    db.execute('update assistant_conversations set analysis_id=?,analysis_revision=? where id=?',
                        (analysis_id,revision,record['conversation_id']))
                    db.execute('update assistant_runs set analysis_id=? where id in (select run_id from assistant_conversation_turns where conversation_id=?)',
                        (analysis_id,record['conversation_id']))
            current=store.detail(actor,analysis_id,lambda:authorize(True))
            require(current['analysisRevision']==revision and current.get('lifecycle')=='active','ANALYSIS_CHANGED',409)
            from .analysis_evidence import AnalysisEvidence
            evidence=AnalysisEvidence(store)
            def register(candidate,index):
                require(candidate['kind'] in runtime.store.policy(project)['policy']['allowedKinds'],'ASSISTANT_TOOL_NOT_ALLOWED',403)
                return evidence.register(actor,dict(analysisSessionId=analysis_id,expectedAnalysisRevision=revision,
                    requestId=operations.operation_id(record['id'],'register:'+candidate['key']),sourceKind=candidate['kind'],selector=candidate['selector']),
                    lambda:authorize(True),reader.resolve)
            updated,receipts,wants_save=operations.build(board,plan,choices,register,record['id'],sessions.connection_id,project)
            authorize(True)
            value=dict(operationId=operations.operation_id(record['id'],'batch:'+selection),baseDigest=base,snapshot=updated,receipts=receipts,
                wantsSave=wants_save,analysis={k:current[k] for k in ('analysisSessionId','analysisRevision','contentSha256','lifecycle','lifecycleRevision') if k in current},
                baseline=baseline)
            operations.retain(runtime.store.library,record['id'],selection,base,value)
            return value


class analysis_store:
    def __init__(self,sessions,project):self.sessions,self.project,self.store=sessions,project,None
    def __enter__(self):
        from .analysis_drafts import AnalysisDrafts
        require(self.sessions.analysis_store_id is not None,'ANALYSIS_NOT_ENABLED',503)
        require(self.sessions.analysis_slots.acquire(timeout=5),'ANALYSIS_BUSY',503)
        try:
            self.store=AnalysisDrafts(self.sessions.analysis_database_url,self.sessions.connection_id,self.project)
            require(self.store.store_id==self.sessions.analysis_store_id,'ANALYSIS_STORE_SCOPE_MISMATCH',409)
            return self.store
        except Exception:
            if self.store:self.store.close()
            self.sessions.analysis_slots.release();raise
    def __exit__(self,*exc):
        self.store.close();self.sessions.analysis_slots.release()
