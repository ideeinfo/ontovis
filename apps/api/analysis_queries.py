"""Alarm-scoped Canvas preparation; bounded recommendations and owned history."""
from __future__ import annotations

import copy
import json
from urllib.parse import urlencode
from uuid import UUID, uuid5

from . import analysis_drafts as d, simulated_faults as sim
from .analysis_evidence import AnalysisEvidence
from .analysis_source_reader import selected
from .authority import PreviewError
from .analysis_recommendations import recommendation


def entry_dataset(reader, entry):
    d.require(type(entry) is dict and set(entry) in ({'datasetId','datasetRevision'}, {'orderId'}))
    order = None
    if 'orderId' in entry:
        order = reader.orders.detail({'orderId': entry['orderId']})
        if order.get('workflowVersion'):
            source = order['workflow'].get('source')
            if not source:
                return None, order
            identity = source['identity']
            sim.catalogue(reader.reader.project_code)
            return sim.dataset(identity['datasetId'], identity['datasetRevision']), order
        dataset = sim.identity(order['faultCode'])
    else:
        dataset = sim.dataset(entry['datasetId'], entry['datasetRevision'])
    sim.catalogue(reader.reader.project_code)
    return dataset, order


def matching_history(store, actor, dataset, object_id, authorize):
    from .analysis_lifecycle import active_condition
    authorize()
    with store.connection.transaction(readonly=True) as cur:
        # Scope/owner index and fixed context expressions avoid fetching every Canvas.
        cur.execute(f'''select s.session_id::text,s.head_revision,r.snapshot_json,r.content_sha256
            from {d.SCHEMA}.analysis_sessions s join {d.SCHEMA}.analysis_revisions r
              on r.session_id=s.session_id and r.revision=s.head_revision
            where s.connection_id=%s and s.project_code=%s and s.owner_id=%s
              and {active_condition(store)}
              and r.snapshot_json::jsonb#>>'{{context,faultCode}}'=%s
              and r.snapshot_json::jsonb#>>'{{context,sourceConnectionId}}'=%s
              and r.snapshot_json::jsonb->>'schemaVersion'='2'
            order by coalesce((r.snapshot_json::jsonb#>>'{{context,eventId}}'=%s
              and r.snapshot_json::jsonb#>>'{{context,datasetId}}'=%s
              and r.snapshot_json::jsonb#>>'{{context,datasetRevision}}'=%s),false) desc,
              coalesce((r.snapshot_json::jsonb#>'{{context,objectIds}}' ? %s),false) desc,
              coalesce((r.snapshot_json::jsonb#>>'{{context,branch}}'=%s),false) desc,s.updated_at desc,s.session_id
            limit 20''', (store.connection_id,store.project_code,actor,dataset['faultCode'],dataset['sourceConnectionId'],
                         dataset['datasetId']+'-event-1',dataset['datasetId'],dataset['datasetRevision'],object_id or '',dataset['branch']))
        rows = cur.fetchall()
    authorize()
    return [{'analysisSessionId': r[0], 'analysisRevision': r[1], 'snapshot': json.loads(r[2]), 'contentSha256': r[3]} for r in rows]


def recommendations(reader, body, scene_library=None, *, cursor_key=None, session_revision=''):
    from .analysis_recommendations import (RELATED_SECTIONS, recommendation, related_recommendations,
        cursor_secret, scope_digest, encode_cursor, decode_cursor)
    d.require(type(body) is dict and 'entry' in body and set(body) <= {'entry','section','offset','cursor','entityUid','expectedEntityRevision','q'})
    dataset, order = (None,None) if body['entry']=={'projectOnly':True} else entry_dataset(reader,body['entry'])
    section=body.get('section','objects');offset=body.get('offset',0);query=body.get('q','')
    d.require(section in (*RELATED_SECTIONS,'objects','project_documents','models','orders','alarms','trends')
        and type(offset) is int and 0<=offset<=1000 and type(query) is str and len(query)<=200)
    cursor=body.get('cursor');d.require(cursor is None or type(cursor) in (str,int))
    if isinstance(cursor,str):d.text(cursor,12288)
    rows,gaps=[],[]
    def attempt(callback):
        try:callback()
        except PreviewError as error:
            if error.status in (401,403,409):raise
            gaps.append(error.code)
    if section in RELATED_SECTIONS:
        chosen=None
        if body.get('entityUid'):
            chosen=reader.reader.context_for_object(body['entityUid'],body.get('expectedEntityRevision'))
        elif dataset:
            try:chosen=reader._rds(dataset['primaryRds'])
            except PreviewError as error:
                if error.status in (401,403,409):raise
                gaps.append(error.code)
        value=related_recommendations(reader,{**body,'section':section},dataset,chosen,
            cursor_key=cursor_key,session_revision=session_revision)
        return {**value,'gaps':list(dict.fromkeys(gaps+value['gaps']))}
    if section=='project_documents':
        from .analysis_recommendations import _document
        params={'q':query,'status':'active','limit':12}
        if cursor is not None:params['cursor']=cursor
        value=reader.reader._request('GET',reader.reader.prefix+'/documents?'+urlencode(params))
        for item in value['items']:
            if item.get('preview_kind') not in ('pdf','image') and item.get('kind')!='photo':continue
            row=_document(dict(documentId=item['id'],contentVersionId=item.get('current_version_id'),title=item['name'],
                kind='photo' if item.get('preview_kind')=='image' or item.get('kind')=='photo' else 'pdf',
                availability='unavailable' if item.get('preview_error') or not item.get('current_version_id') else 'available'),
                '本项目文档检索','Project document library; no equipment or fault association is asserted.','catalogue_search')
            if row is not None:rows.append(row)
        return {'items':rows,'nextOffset':None,'nextCursor':value.get('next_cursor'),'gaps':gaps,'dataset':dataset,'order':'source'}
    if section=='objects' and query.strip():
        value=reader.reader._request('GET',reader.reader.prefix+'/objects?'+urlencode({'q':query,'limit':8,**({'cursor':cursor} if cursor is not None else {})}))
        for item in value['items']:
            rows.append(recommendation('object',item['displayName'],{'entityUid':item['entityUid'],'expectedEntityRevision':item['entityRevision']},
                '本项目名称或位号检索',relevance='catalogue_search',reasonEn='Project object name or identifier search.'))
        return {'items':rows,'nextOffset':None,'nextCursor':value.get('nextCursor'),'gaps':gaps,'dataset':dataset,'order':'source'}
    elif section=='objects':
        seen=set()
        if body.get('entityUid'):
            chosen=reader.reader.context_for_object(body['entityUid'],body.get('expectedEntityRevision'));item=chosen['item'];seen.add(item['entityUid'])
            rows.append(recommendation('object',item['displayName'],{'entityUid':item['entityUid'],'expectedEntityRevision':item['entityRevision']},
                '当前选中的工程对象',relevance='selected_object',reasonEn='The selected engineering object.'))
        if dataset:
            from .demo_faults import diagnosis
            tags=[(dataset['primaryRds'],'模拟报警配置的显式位号映射'),('=WEC+'+dataset['cabinet'],'演练配置指定的柜体')]
            channel=sim.PROFILES[dataset['faultCode']].get('channel')
            tags += [(channel['moduleRds'] if channel and node['rds']==channel['rds'] else node['rds'],
                '模块内地址 '+channel['address']+'；定位所属模块' if channel and node['rds']==channel['rds'] else '演练排查参照对象')
                for node in diagnosis(dataset['faultCode'])['nodes'] if node['kind']=='component']
            seen_tags=set()
            for tag,reason in tags:
                if tag in seen_tags:continue
                seen_tags.add(tag)
                def add(tag=tag,reason=reason):
                    value=reader._rds(tag);item=value['item']
                    if item['entityUid'] in seen:return
                    seen.add(item['entityUid']);basis='simulation_mapping' if tag==dataset['primaryRds'] else 'simulation_rule'
                    rows.append(recommendation('object',item.get('displayName',tag),
                        {k:selected(value)[k] for k in ('entityUid','expectedEntityRevision')},reason,relevance=basis,identifier=tag,matchType=basis))
                attempt(add)
        if not rows:gaps.append('选择工程对象、故障，或输入名称/位号检索。')
    elif section in ('alarms','trends'):
        if section=='alarms':
            def add_alarms():
                candidates=sim.catalogue(reader.reader.project_code)['items']
                candidates.sort(key=lambda item:(item['datasetId']!=(dataset or {}).get('datasetId'),
                    item['faultCode']!=(dataset or {}).get('faultCode'),item['timeFrom'],item['datasetId']))
                for item in candidates:
                    if query.casefold() not in (item['faultCode']+' '+item['title']+' '+item['primaryRds']).casefold():continue
                    current=dataset and item['datasetId']==dataset['datasetId'];same=dataset and item['faultCode']==dataset['faultCode']
                    rows.append(recommendation('alarm',item['faultCode']+' · '+item['title'],
                        {key:item[key] for key in ('datasetId','datasetRevision')}|{'eventId':item['datasetId']+'-event-1'},
                        '本次模拟报警' if current else '同码独立事件，仅作历史参照' if same else '本项目其他模拟报警',
                        relevance='same_event' if current else 'same_fault' if same else 'catalogue_search',preview={'dataset':item},identifier=item['primaryRds']))
            attempt(add_alarms)
        elif not dataset:gaps.append('先加入故障报警，再选择该报警的趋势。')
        else:
            metrics=(['sensor_temperature','reference_temperature'] if dataset['faultCode'] in ('13001','13002') else [])+['device_feedback','supply_voltage','overcurrent']
            names={'sensor_temperature':'传感器温度','reference_temperature':'独立参照温度','device_feedback':'状态反馈','supply_voltage':'供电电压','overcurrent':'过流信号'}
            for metric in metrics:
                if query.casefold() not in (names[metric]+' '+metric).casefold():continue
                rows.append(recommendation('trend',names[metric],
                    {key:dataset[key] for key in ('datasetId','datasetRevision','timeFrom','timeTo')}|{'metricId':metric},
                    '本次模拟报警的固定时间窗',relevance='same_event',reasonEn='Fixed time window of the current simulated alarm.'))
    elif section=='models':
        if body.get('entityUid'):chosen=reader.reader.context_for_object(body['entityUid'],body.get('expectedEntityRevision'))
        elif dataset and not query.strip():chosen=reader._rds('=WEC+'+dataset['cabinet'])
        elif query.strip():
            value=reader.models.listing(reader.actor,reader.authorize,access_revision='analysis',q=query,limit=12,cursor=cursor)
            for item in value['items']:
                if not item.get('versions'):continue
                version=item['versions'][0]
                rows.append(recommendation('model',item['displayName'],{'modelAssetId':version['modelAssetId'],'modelVersionId':version['modelVersionId'],
                    'expectedContentRevision':version['contentRevision'],'expectedSha256':version['sha256']},
                    '共享模型名称检索；未声明对象绑定',matchType='catalogue_search'))
            return {'items':rows,'nextOffset':None,'nextCursor':value['nextCursor'],'gaps':gaps,'dataset':dataset,'order':'source'}
        else:return {'items':[],'nextOffset':None,'nextCursor':None,'gaps':['先选择工程对象，或输入模型名检索。'],'dataset':dataset,'order':'relevance'}
        from .analysis_model_links import recommend_models
        values,following,model_gaps=recommend_models(reader,chosen,scene_library,offset=offset,query=query)
        for item in values:rows.append(recommendation('model',item['title'],item['selector'],item['reason'],relevance=item['matchType'],matchType=item['matchType']))
        return {'items':rows,'nextOffset':following,'nextCursor':None,'gaps':gaps+model_gaps,'dataset':dataset,'order':'relevance'}
    else:
        key=cursor_secret(reader,cursor_key);scope=scope_digest(reader,body,session_revision);expires=None
        if cursor is not None:
            position,expires=decode_cursor(cursor,key,scope)
            d.require(type(position) is dict and set(position)=={'offset','snapshot'},'ANALYSIS_RECOMMENDATIONS_CHANGED',409)
        else:
            d.require(offset==0,'ANALYSIS_RECOMMENDATIONS_CHANGED',409);position={'offset':0,'snapshot':None}
        fault = dataset['faultCode'] if dataset else order['faultCode'] if order else ''
        value=reader.orders.recommendation_listing({'q':query or fault,
            'faultCode':fault, 'orderId':order['orderId'] if order else '',
            'cursor':position['offset'],'expectedSnapshotRevision':position['snapshot'],'limit':12})
        for item in value['items']:
            current=order and item['orderId']==order['orderId'];same=dataset and item['faultCode']==dataset['faultCode']
            rows.append(recommendation('work_order',item['title'],{'orderId':item['orderId'],'expectedOrderRevision':item['orderRevision']},
                '当前工单' if current else '相同故障码工单' if same else '本项目工单检索',
                relevance='same_event' if current else 'same_fault' if same else 'catalogue_search',identifier=item['orderId']))
        following=encode_cursor(key,scope,{'offset':value['nextCursor'],'snapshot':value['snapshotRevision']},expires) if value['nextCursor'] is not None else None
        return {'items':rows,'nextOffset':None,'nextCursor':following,'gaps':gaps,'dataset':dataset,'order':'relevance'}
    limit=8 if section=='objects' else 12
    return {'items':rows[offset:offset+limit], 'nextOffset':offset+limit if len(rows)>offset+limit else None,
        'nextCursor':None,'gaps':gaps,'dataset':dataset,'order':'relevance'}


def start_analysis(store, actor, reader, body, authorize):
    d.require(type(body) is dict and set(body) == {'entry','requestId'})
    if type(body['entry']) is dict and set(body['entry'])=={'entityUid','expectedEntityRevision','timeTo'}:
        return start_object_analysis(store,actor,reader,body,authorize)
    request_id = d.identifier(body['requestId']); dataset, order = entry_dataset(reader,body['entry'])
    d.require(dataset is not None, 'WORK_ORDER_USE_WORKFLOW', 409)
    namespace = UUID(request_id)
    rid = lambda name: str(uuid5(namespace,name))
    primary, gap = None, None
    try: primary = reader._rds(dataset['primaryRds'])
    except PreviewError as error:
        if error.status in (401,403): raise
        gap = error.code
    history = matching_history(store,actor,dataset,primary['item']['entityUid'] if primary else None,authorize)
    event_id = dataset['datasetId']+'-event-1'
    same = next((h for h in history if h['snapshot']['context'].get('eventId') == event_id
                 and all(h['snapshot']['context'].get(key) == dataset[key]
                         for key in ('sourceConnectionId','datasetId','datasetRevision','timeFrom','timeTo'))
                 and h['snapshot']['context'].get('objectIds') == ([primary['item']['entityUid']] if primary else [])
                 and (not order or h['snapshot']['context'].get('workOrderId') == body['entry']['orderId'])),None)
    if same:
        return {**same,'resumed':True,'historyImported':False,'gap':gap}
    blank = {'schemaVersion':2,'ontobaseConnectionId':store.connection_id,'projectCode':store.project_code,
        'title':dataset['faultCode']+' · '+dataset['title'],'status':'analyzing',
        'context':{'objectIds':[],'timeFrom':dataset['timeFrom'],'timeTo':dataset['timeTo'],'timezone':'Asia/Shanghai'},
        'cards':[],'relations':[],'viewport':{'x':24,'y':24,'zoom':.75},'frames':[]}
    created = store.write(actor,'admin','create',{'requestId':rid('create'),'snapshot':blank},authorize)
    session_id = created['analysisSessionId']; source = AnalysisEvidence(store)
    snapshot = copy.deepcopy(blank)
    def register(kind, selector, key, resolver=None):
        return source.register(actor,{'analysisSessionId':session_id,'expectedAnalysisRevision':1,'requestId':rid(key),
            'sourceKind':kind,'selector':selector},authorize,resolver or reader.resolve)
    def ref(kind, registered):
        return {'system':'ontobase' if kind in ('object','drawing','photo','document') else 'ontovis',
            'ontobaseConnectionId':store.connection_id,'projectCode':store.project_code,
            'id':registered['evidenceRefId'],'revision':registered['sourceRevision']}
    def add(kind,title,selector,key,resolver=None):
        registered = register(kind,selector,key,resolver)
        n = len(snapshot['cards']); snapshot['cards'].append({'id':rid(key),'kind':'model3d' if kind=='model' else kind,
            'title':title[:120],'x':32+(n%3)*380,'y':48+(n//3)*300,'width':340,'height':250,'pinned':False,
            'source':ref(kind,registered),'frameId':'current'})
    add('alarm',dataset['faultCode']+' · 本次报警',{'datasetId':dataset['datasetId'],'datasetRevision':dataset['datasetRevision'],'eventId':event_id},'alarm')
    if primary:
        add('object',dataset['primaryRds'],{k:selected(primary)[k] for k in ('entityUid','expectedEntityRevision')},'object',lambda kind,selector:selected(primary))
        snapshot['context']['objectIds']=[primary['item']['entityUid']]
    for metric in (('sensor_temperature','reference_temperature') if dataset['faultCode'] in ('13001','13002') else ('device_feedback',)):
        add('trend',{'sensor_temperature':'传感器温度','reference_temperature':'独立参照温度','device_feedback':'状态反馈'}[metric],
            {k:dataset[k] for k in ('datasetId','datasetRevision','timeFrom','timeTo')}|{'metricId':metric},metric)
    if order:
        item=order; add('work_order',item['title'],{'orderId':item['orderId'],'expectedOrderRevision':item['orderRevision']},'order')
        snapshot['context']['workOrderId']=item['orderId']
    try:
        from .analysis_preview import fault_documents
        manuals = fault_documents(reader, dataset['faultCode'])
        for index, manual in enumerate(manuals[:2]):
            add('document', manual['title'], manual['selector'], 'fault-manual-' + str(index))
    except PreviewError as error:
        if error.status in (401,403): raise
        gap = error.code
    n=len(snapshot['cards']); snapshot['cards'].append({'id':rid('note'),'kind':'analysis','title':'本次排查记录','note':'',
        'x':32+(n%3)*380,'y':48+(n//3)*300,'width':340,'height':250,'pinned':False,'checkState':'not_started','frameId':'current'})
    snapshot['context'].update({k:dataset[k] for k in ('faultCode','sourceConnectionId','branch','datasetId','datasetRevision')},eventId=event_id)
    current_bottom = max(c['y'] + c['height'] for c in snapshot['cards'])
    snapshot['frames']=[{'id':'current','title':'本次调查','x':12,'y':12,'width':1140,'height':current_bottom + 8}]
    imported = False; missing = []
    prior = history[0] if history else None
    if prior and len(prior['snapshot']['cards'])+len(snapshot['cards']) <= 50:
        snapshot['inheritedFrom']={k:prior[k] for k in ('analysisSessionId','analysisRevision','contentSha256')}
        old = prior['snapshot']; mapping={c['id']:rid('history-card-'+c['id']) for c in old['cards']}
        for card in old['cards']:
            clone=copy.deepcopy(card);clone.update(id=mapping[card['id']],y=card['y']+current_bottom+180,historical=True,frameId='history')
            if card['kind'] != 'analysis':
                kind = 'model' if card['kind']=='model3d' else card['kind']
                try:
                    _, descriptor = source.descriptor(actor,{'analysisSessionId':prior['analysisSessionId'],'evidenceRefId':card['source']['id']},authorize)
                    # The owned fixed citation can remain in the layout even if
                    # its content is now unavailable. Opening rechecks the source.
                    def resolve(kind, selector): return selector
                    clone['source']=ref(kind,register(kind,descriptor,'history-'+card['id'],resolve))
                except PreviewError as error:
                    if error.status in (401,403): raise
                    missing.append({'cardId':card['id'],'reason':error.code});continue
            snapshot['cards'].append(clone)
        admitted={c['id'] for c in snapshot['cards']}
        snapshot['relations']=[{**r,'id':rid('history-edge-'+r['id']),'from':mapping[r['from']],'to':mapping[r['to']]}
            for r in old['relations'] if mapping[r['from']] in admitted and mapping[r['to']] in admitted]
        inherited=[c for c in snapshot['cards'] if c.get('historical')]
        if inherited:
            left=min(c['x'] for c in inherited)-20;top=min(c['y'] for c in inherited)-36
            snapshot['frames'].append({'id':'history','title':'历史参考 · '+old['title'][:80], 'x':left,'y':top,
                'width':max(280,min(20000,max(c['x']+c['width'] for c in inherited)-left+20)),
                'height':max(220,min(20000,max(c['y']+c['height'] for c in inherited)-top+20))})
        imported=True
    saved=store.write(actor,'admin','save',{'requestId':rid('save'),'analysisSessionId':session_id,'expectedAnalysisRevision':1,'snapshot':snapshot},authorize)
    return {**saved,'snapshot':snapshot,'resumed':False,'historyImported':imported,'missingHistorySources':missing,'gap':gap,
        'historyReference':{k:prior[k] for k in ('analysisSessionId','analysisRevision','contentSha256')} if prior else None}


def copy_analysis(store, actor, body, authorize):
    from .analysis_canvas import validate_handles
    d.require(type(body) is dict and set(body) == {'analysisSessionId','requestId','snapshot'})
    original_id=d.identifier(body['analysisSessionId']); namespace=UUID(d.identifier(body['requestId']))
    snapshot=copy.deepcopy(body['snapshot']); d.validate_snapshot(snapshot,store.connection_id,store.project_code)
    authorize()
    with store.connection.transaction(readonly=True) as cur:
        head = store._session(cur,original_id,actor,active=True)[0]
        original, _ = store._revision(cur, original_id, head)
        d.require(all(original.get(key) == snapshot.get(key) for key in ('workflowOrderId', 'derivedFrom')),
                  'ANALYSIS_CONTEXT_CHANGED', 409)
        if snapshot['schemaVersion']==2: validate_handles(cur,original_id,snapshot,store.schema_version)
        cur.execute(f'''select evidence_ref_id::text,source_kind,descriptor_json
            from {d.SCHEMA}.analysis_evidence_refs where session_id=%s''',(original_id,))
        refs=cur.fetchall()
    blank={**snapshot,'cards':[],'relations':[],'context':{k:v for k,v in snapshot['context'].items() if k in ('objectIds','timeFrom','timeTo','timezone')}}
    blank['context']['objectIds']=[];blank.pop('inheritedFrom',None)
    created=store.write(actor,'admin','create',{'requestId':str(uuid5(namespace,'create')),'snapshot':blank},authorize,
        work_order_origin=blank.get('workflowOrderId'), derived_from=blank.get('derivedFrom'))
    sources=AnalysisEvidence(store);mapping={}
    for ref_id,kind,raw in refs:
        reference=sources.register(actor,{'analysisSessionId':created['analysisSessionId'],'expectedAnalysisRevision':1,
            'requestId':str(uuid5(namespace,ref_id)),'sourceKind':kind,'selector':json.loads(raw)},authorize,lambda kind,selector:selector)
        mapping[ref_id]=reference
    for card in snapshot['cards']:
        if 'source' in card:
            registered=mapping[card['source']['id']];card['source'].update(id=registered['evidenceRefId'],revision=registered['sourceRevision'])
    saved=store.write(actor,'admin','save',{'requestId':str(uuid5(namespace,'save')),'analysisSessionId':created['analysisSessionId'],
        'expectedAnalysisRevision':1,'snapshot':snapshot},authorize)
    return {**saved,'snapshot':snapshot}


def history_candidates(store, actor, reader, body, authorize):
    d.require(type(body) is dict and set(body) == {'entry'})
    dataset, _ = entry_dataset(reader, body['entry'])
    if not dataset:
        return {'items': []}
    primary = reader._rds(dataset['primaryRds'])['item']['entityUid']
    rows = matching_history(store, actor, dataset, primary, authorize)
    items=[]
    for row in rows:
        context=row['snapshot']['context']
        current=all(context.get(k)==v for k,v in {'eventId':dataset['datasetId']+'-event-1',
            'datasetId':dataset['datasetId'],'datasetRevision':dataset['datasetRevision']}.items())
        same_object=primary in context['objectIds']
        basis='same_event' if current else 'same_object_fault' if same_object else 'same_fault'
        reason='本次事件' if current else '同一对象、相同故障码' if same_object else '相同故障码；对象适用性待核对'
        reason+=' · 相同分支' if context.get('branch')==dataset['branch'] else ' · 分支适用性待核对'
        items.append({'analysisSessionId':row['analysisSessionId'],'analysisRevision':row['analysisRevision'],
            'title':row['snapshot']['title'],'reason':reason,'relevance':basis,
            'eventId':context.get('eventId')})
    return {'items':items}


def import_history(store, actor, body, authorize):
    """Prepare owned fixed references and a local snapshot; save remains explicit."""
    from .analysis_canvas import validate_handles
    d.require(type(body) is dict and set(body)=={'analysisSessionId','expectedAnalysisRevision','snapshot','historySessionId','historyRevision','requestId'})
    session_id=d.identifier(body['analysisSessionId']);namespace=UUID(d.identifier(body['requestId']))
    snapshot=copy.deepcopy(body['snapshot']);d.validate_snapshot(snapshot,store.connection_id,store.project_code)
    current=store.detail(actor,session_id,authorize)
    d.require(current['analysisRevision']==body['expectedAnalysisRevision'],'ANALYSIS_CHANGED',409)
    prior=store.detail(actor,body['historySessionId'],authorize,revision=body['historyRevision'])
    d.require(prior['analysisSessionId']!=session_id,'INVALID_REQUEST',422)
    d.require(snapshot['context'].get('faultCode') and all(snapshot['context'].get(k)==prior['snapshot']['context'].get(k)
        for k in ('faultCode','sourceConnectionId')),'ANALYSIS_HISTORY_SCOPE_MISMATCH',409)
    with store.connection.transaction(readonly=True) as cur: validate_handles(cur,session_id,snapshot,store.schema_version)
    removed={c['id'] for c in snapshot['cards'] if c.get('historical')}
    snapshot['cards']=[c for c in snapshot['cards'] if c['id'] not in removed]
    snapshot['relations']=[r for r in snapshot['relations'] if r['from'] not in removed and r['to'] not in removed]
    snapshot['frames']=[f for f in snapshot.get('frames',[]) if f['id']!='history']
    old=prior['snapshot'];old_cards=[c for c in old['cards'] if not c.get('historical')]
    d.require(len(old_cards)+len(snapshot['cards'])<=50,'ANALYSIS_SIZE_LIMIT',413)
    shift=max((c['y']+c['height'] for c in snapshot['cards']),default=0)+100-min((c['y'] for c in old_cards),default=0)
    mapping={c['id']:str(uuid5(namespace,c['id'])) for c in old_cards};sources=AnalysisEvidence(store)
    for card in old_cards:
        clone=copy.deepcopy(card);clone.update(id=mapping[card['id']],y=card['y']+shift,historical=True,frameId='history')
        if 'source' in card:
            reference,descriptor=sources.descriptor(actor,{'analysisSessionId':prior['analysisSessionId'],'evidenceRefId':card['source']['id']},authorize)
            registered=sources.register(actor,{'analysisSessionId':session_id,'expectedAnalysisRevision':body['expectedAnalysisRevision'],
                'requestId':str(uuid5(namespace,'ref:'+card['id'])),'sourceKind':reference['sourceKind'],'selector':descriptor},authorize,lambda kind,selector:selector)
            clone['source'].update(id=registered['evidenceRefId'],revision=registered['sourceRevision'])
        snapshot['cards'].append(clone)
    snapshot['relations'] += [{**r,'id':str(uuid5(namespace,'edge:'+r['id'])),'from':mapping[r['from']],'to':mapping[r['to']]}
        for r in old['relations'] if r['from'] in mapping and r['to'] in mapping]
    snapshot['inheritedFrom']={k:prior[k] for k in ('analysisSessionId','analysisRevision','contentSha256')}
    cards=[c for c in snapshot['cards'] if c.get('historical')]
    if cards:
        x=min(c['x'] for c in cards)-20;y=min(c['y'] for c in cards)-36
        snapshot['frames'].append({'id':'history','title':'历史参考 · '+old['title'][:80],'x':x,'y':y,
            'width':max(280,max(c['x']+c['width'] for c in cards)-x+20),'height':max(220,max(c['y']+c['height'] for c in cards)-y+20)})
    d.validate_snapshot(snapshot,store.connection_id,store.project_code)
    return {'snapshot':snapshot,'historyRevision':prior['analysisRevision']}


def start_object_analysis(store,actor,reader,body,authorize):
    from datetime import datetime,timedelta,timezone
    namespace=UUID(d.identifier(body['requestId']));item=reader.reader.context_for_object(body['entry']['entityUid'],body['entry']['expectedEntityRevision'])['item']
    now=d.utc(body['entry']['timeTo']);stamp=lambda value:value.isoformat(timespec='milliseconds').replace('+00:00','Z')
    snapshot={'schemaVersion':2,'ontobaseConnectionId':store.connection_id,'projectCode':store.project_code,'title':item['displayName'][:100]+' · 分析',
      'status':'analyzing','context':{'objectIds':[],'timeFrom':stamp(now-timedelta(hours=1)),'timeTo':stamp(now),'timezone':'Asia/Shanghai'},
      'cards':[],'relations':[],'viewport':{'x':24,'y':24,'zoom':1},'frames':[]}
    result=store.write(actor,'admin','create',{'snapshot':snapshot,'requestId':str(uuid5(namespace,'create'))},authorize)
    current=store.detail(actor,result['analysisSessionId'],authorize)
    if current['headRevision']>1:return {**current,'resumed':True,'historyImported':False}
    ref=AnalysisEvidence(store).register(actor,{'analysisSessionId':result['analysisSessionId'],'expectedAnalysisRevision':1,'requestId':str(uuid5(namespace,'ref')),
      'sourceKind':'object','selector':{k:body['entry'][k] for k in ('entityUid','expectedEntityRevision')}},authorize,reader.resolve)
    snapshot['context']['objectIds']=[item['entityUid']]
    snapshot['cards']=[{'id':str(uuid5(namespace,'object')),'kind':'object','title':item['displayName'][:120],'x':32,'y':40,'width':340,'height':250,'pinned':False,
      'source':{'system':'ontobase','ontobaseConnectionId':store.connection_id,'projectCode':store.project_code,'id':ref['evidenceRefId'],'revision':ref['sourceRevision']}},
      {'id':str(uuid5(namespace,'note')),'kind':'analysis','title':'本次排查记录','note':'','x':412,'y':40,'width':340,'height':250,'pinned':False,'checkState':'not_started'}]
    saved=store.write(actor,'admin','save',{'analysisSessionId':result['analysisSessionId'],'expectedAnalysisRevision':1,'requestId':str(uuid5(namespace,'save')),'snapshot':snapshot},authorize)
    return {**saved,'snapshot':snapshot,'resumed':False,'historyImported':False}
