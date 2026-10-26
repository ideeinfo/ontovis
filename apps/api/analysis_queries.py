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


def entry_dataset(reader, entry):
    d.require(type(entry) is dict and set(entry) in ({'datasetId','datasetRevision'}, {'orderId'}))
    order = None
    if 'orderId' in entry:
        order = reader.orders.detail({'orderId': entry['orderId']})
        dataset = sim.identity(order['faultCode'])
    else:
        dataset = sim.dataset(entry['datasetId'], entry['datasetRevision'])
    sim.catalogue(reader.reader.project_code)
    return dataset, order


def matching_history(store, actor, dataset, object_id, authorize):
    authorize()
    with store.connection.transaction(readonly=True) as cur:
        # Scope/owner index and fixed context expressions avoid fetching every Canvas.
        cur.execute(f'''select s.session_id::text,s.head_revision,r.snapshot_json,r.content_sha256
            from {d.SCHEMA}.analysis_sessions s join {d.SCHEMA}.analysis_revisions r
              on r.session_id=s.session_id and r.revision=s.head_revision
            where s.connection_id=%s and s.project_code=%s and s.owner_id=%s
              and r.snapshot_json::jsonb#>>'{{context,faultCode}}'=%s
              and r.snapshot_json::jsonb#>>'{{context,sourceConnectionId}}'=%s
              and r.snapshot_json::jsonb->>'schemaVersion'='2'
            order by (r.snapshot_json::jsonb#>>'{{context,eventId}}'=%s) desc,
              (r.snapshot_json::jsonb#>'{{context,objectIds}}' ? %s) desc,
              (r.snapshot_json::jsonb#>>'{{context,branch}}'=%s) desc,s.updated_at desc,s.session_id
            limit 20''', (store.connection_id,store.project_code,actor,dataset['faultCode'],dataset['sourceConnectionId'],
                         dataset['datasetId']+'-event-1',object_id or '',dataset['branch']))
        rows = cur.fetchall()
    authorize()
    return [{'analysisSessionId': r[0], 'analysisRevision': r[1], 'snapshot': json.loads(r[2]), 'contentSha256': r[3]} for r in rows]


def recommendation(kind, title, selector, reason, **extra):
    return {'key': d.digest([kind,selector]), 'kind': kind, 'title': title[:120], 'selector': selector, 'reason': reason, **extra}


def recommendations(reader, body):
    d.require(type(body) is dict and 'entry' in body and set(body) <= {'entry','section','offset','cursor','entityUid','expectedEntityRevision','q'})
    manual=body['entry']=={'projectOnly':True} or body.get('section')=='objects' and 'q' in body
    dataset, order = (None,None) if manual else entry_dataset(reader, body['entry'])
    section = body.get('section', 'objects'); offset = body.get('offset', 0)
    d.require(section in ('objects','materials','documents','models','orders') and type(offset) is int and 0 <= offset <= 1000)
    cursor = body.get('cursor')
    d.require(cursor is None or isinstance(cursor,(str,int)) and not isinstance(cursor,bool))
    if isinstance(cursor,str): d.text(cursor,4096)
    rows, gaps = [], []
    def attempt(callback):
        try: callback()
        except PreviewError as error:
            if error.status in (401,403): raise
            gaps.append(error.code)
    if section == 'objects' and manual:
        query=body.get('q','');d.require(type(query) is str and len(query)<=200)
        if query.strip():
            value=reader.reader._request('GET',reader.reader.prefix+'/objects?'+urlencode({'q':query,'limit':8,**({'cursor':cursor} if cursor is not None else {})}))
            for item in value['items']:
                rows.append(recommendation('object',item['displayName'],{'entityUid':item['entityUid'],'expectedEntityRevision':item['entityRevision']},'本项目名称或位号检索；尚未声明与报警关联'))
            return {'items':rows,'nextOffset':None,'nextCursor':value.get('nextCursor'),'gaps':gaps,'dataset':None}
        else:gaps.append('输入对象名称或位号查找，或从设备层级直接进入分析。')
    elif section == 'objects':
        from .demo_faults import diagnosis
        tags = [(dataset['primaryRds'],'报警明确映射对象'),('=WEC+'+dataset['cabinet'],'已登记的所属柜体')]
        channel = sim.PROFILES[dataset['faultCode']].get('channel')
        tags += [(channel['moduleRds'] if channel and node['rds']==channel['rds'] else node['rds'],
                  '模块内地址 '+channel['address']+'；定位所属模块' if channel and node['rds']==channel['rds'] else '本故障码排查分支的参照对象')
                 for node in diagnosis(dataset['faultCode'])['nodes'] if node['kind']=='component']
        seen = set()
        for tag, reason in tags:
            if tag in seen: continue
            seen.add(tag)
            def add(tag=tag, reason=reason):
                value = reader._rds(tag); item = value['item']
                rows.append(recommendation('object', item.get('displayName',tag),
                    {k:selected(value)[k] for k in ('entityUid','expectedEntityRevision')},reason, identifier=tag))
            attempt(add)
    elif section == 'materials':
        if 'entityUid' in body:
            chosen = reader.reader.context_for_object(body['entityUid'],body.get('expectedEntityRevision'))
        elif dataset: chosen = reader._rds(dataset['primaryRds'])
        else:return {'items':[],'nextOffset':None,'gaps':['先选择对象的关联资料入口。'],'dataset':None}
        selection = selected(chosen)
        from .scene_evidence import SceneEvidenceReader
        for kind, source in (('drawing',SceneEvidenceReader(reader.reader)),('photo',reader.photos)):
            def add(kind=kind, source=source):
                for item in source.resolve(selection)['items']:
                    if kind == 'drawing' and item['availability'] != 'available': continue
                    if kind == 'photo' and not item.get('selector'): continue
                    rows.append(recommendation(kind,item['title'],{k:selection[k] for k in ('entityUid','expectedEntityRevision')} | {'evidenceRef':item['evidenceRef']},
                        '所选对象已有的资料关联', preview=item))
            attempt(add)
    elif section == 'documents':
        query = body.get('q', dataset['faultCode'] if dataset else '');d.require(type(query) is str and len(query)<=200)
        params={'q':query,'status':'active','limit':12}
        if cursor is not None:params['cursor']=cursor
        value = reader.reader._request('GET',reader.reader.prefix+'/documents?'+urlencode(params))
        for item in value['items']:
            if item.get('kind') == 'photo': continue
            rows.append(recommendation('document',item['name'],{'documentId':item['id'],'contentVersionId':item['current_version_id'],
                'sourceSha256':item['source_sha256'],'pageNumber':1}, '项目文档名称匹配；适用性需结合正文核对'))
        return {'items':rows, 'nextOffset':None,'nextCursor':value.get('next_cursor'), 'gaps':gaps, 'dataset':dataset}
    elif section == 'models':
        if 'q' in body or manual:
            value = reader.models.listing(reader.actor,reader.authorize,access_revision='analysis',q=body.get('q',''),limit=12,cursor=cursor)
            versions=[(item['displayName'],item['versions'][0]) for item in value['items'] if item.get('versions')]
            next_cursor=value['nextCursor'];reason='共享模型名称候选；以已有绑定及代理精度为准'
        else:
            # Match existing component metadata, not a whole-library client scan.
            # A same-named schematic component is explicitly a reference, not a binding.
            with reader.models.library.connect() as db:
                found=db.execute('''select a.name,p.asset_id,p.version_id,p.content_revision,v.sha256
                    from project_model_assets a join project_model_versions p on p.asset_id=a.id
                    join versions v on v.id=p.version_id
                    left join project_model_lifecycle l on l.asset_id=a.id
                    where a.project_code=? and coalesce(l.state,'active')='active'
                      and not exists(select 1 from project_model_versions p2 join versions v2 on v2.id=p2.version_id
                        where p2.asset_id=a.id and (v2.created_at>v.created_at or v2.created_at=v.created_at and v2.id>v.id))
                      and exists(select 1 from json_each(v.components) component
                        where json_extract(component.value,'$.displayName')=?)
                    order by a.name,a.id limit 13 offset ?''',(reader.models.project_code,dataset['cabinet'],offset)).fetchall()
            versions=[(row[0],{'modelAssetId':row[1],'modelVersionId':row[2],'contentRevision':row[3],'sha256':row[4]}) for row in found[:12]]
            next_cursor=offset+12 if len(found)>12 else None;reason='已有模型含 '+dataset['cabinet']+' 柜级构件；几何精度与对象绑定须分别查看'
        for title,v in versions:
            rows.append(recommendation('model',title,{'modelAssetId':v['modelAssetId'],'modelVersionId':v['modelVersionId'],
                'expectedContentRevision':v['contentRevision'],'expectedSha256':v['sha256']},reason))
        return {'items':rows,'nextOffset':next_cursor if isinstance(next_cursor,int) else None,
                'nextCursor':next_cursor if isinstance(next_cursor,str) else None,'gaps':gaps,'dataset':dataset}
    else:
        value = reader.orders.listing({'q':dataset['faultCode'] if dataset else body.get('q',''),'limit':12,'cursor':offset},False)
        for item in value['items']:
            rows.append(recommendation('work_order',item['title'],{'orderId':item['orderId'],'expectedOrderRevision':item['orderRevision']},'当前项目相同故障码工单' if dataset else '本项目工单；关联适用性需核对'))
        return {'items':rows,'nextOffset':value['nextCursor'],'nextCursor':None,'gaps':gaps,'dataset':dataset}
    limit = 8 if section == 'objects' else 12
    return {'items':rows[offset:offset+limit], 'nextOffset':offset+limit if len(rows)>offset+limit else None,'nextCursor':None,
            'gaps':gaps,'dataset':dataset}


def start_analysis(store, actor, reader, body, authorize):
    d.require(type(body) is dict and set(body) == {'entry','requestId'})
    if type(body['entry']) is dict and set(body['entry'])=={'entityUid','expectedEntityRevision','timeTo'}:
        return start_object_analysis(store,actor,reader,body,authorize)
    request_id = d.identifier(body['requestId']); dataset, order = entry_dataset(reader,body['entry'])
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
    n=len(snapshot['cards']); snapshot['cards'].append({'id':rid('note'),'kind':'analysis','title':'本次排查记录','note':'',
        'x':32+(n%3)*380,'y':48+(n//3)*300,'width':340,'height':250,'pinned':False,'checkState':'not_started','frameId':'current'})
    snapshot['context'].update({k:dataset[k] for k in ('faultCode','sourceConnectionId','branch','datasetId','datasetRevision')},eventId=event_id)
    snapshot['frames']=[{'id':'current','title':'本次调查','x':12,'y':12,'width':1140,'height':620}]
    imported = False; missing = []
    prior = history[0] if history else None
    if prior and len(prior['snapshot']['cards'])+len(snapshot['cards']) <= 50:
        snapshot['inheritedFrom']={k:prior[k] for k in ('analysisSessionId','analysisRevision','contentSha256')}
        old = prior['snapshot']; mapping={c['id']:rid('history-card-'+c['id']) for c in old['cards']}
        for card in old['cards']:
            clone=copy.deepcopy(card);clone.update(id=mapping[card['id']],y=card['y']+800,historical=True,frameId='history')
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
        store._session(cur,original_id,actor)
        if snapshot['schemaVersion']==2: validate_handles(cur,original_id,snapshot,store.schema_version)
        cur.execute(f'''select evidence_ref_id::text,source_kind,descriptor_json
            from {d.SCHEMA}.analysis_evidence_refs where session_id=%s''',(original_id,))
        refs=cur.fetchall()
    blank={**snapshot,'cards':[],'relations':[],'context':{k:v for k,v in snapshot['context'].items() if k in ('objectIds','timeFrom','timeTo','timezone')}}
    blank['context']['objectIds']=[];blank.pop('inheritedFrom',None)
    created=store.write(actor,'admin','create',{'requestId':str(uuid5(namespace,'create')),'snapshot':blank},authorize)
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
    primary = reader._rds(dataset['primaryRds'])['item']['entityUid']
    rows = matching_history(store, actor, dataset, primary, authorize)
    return {'items': [{'analysisSessionId':row['analysisSessionId'],'analysisRevision':row['analysisRevision'],
        'title':row['snapshot']['title'],'reason':('同一对象' if primary in row['snapshot']['context']['objectIds'] else '相同故障码；对象不同，需核对适用性')+
        (' · 相同分支' if row['snapshot']['context'].get('branch')==dataset['branch'] else ' · 分支不同，需核对适用性'),
        'eventId':row['snapshot']['context'].get('eventId')} for row in rows]}


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
